import re
import json
import logging
import networkx as nx
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import GraphNodeDB, GraphEdgeDB, MemoryDB
from backend.app.services.model_router import execute_llm_call
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Standard permitted entity types
ALLOWED_ENTITY_TYPES = {
    "concept", "language", "library", "framework", "database",
    "tool", "project", "organization", "person", "protocol"
}

KNOWN_TECH_TERMS = {
    "python": ("Python", "Language"),
    "fastapi": ("FastAPI", "Framework"),
    "sqlite": ("SQLite", "Database"),
    "redis": ("Redis", "Database"),
    "docker": ("Docker", "Tool"),
    "postgresql": ("PostgreSQL", "Database"),
    "react": ("React", "Framework"),
    "streamlit": ("Streamlit", "Framework"),
    "networkx": ("NetworkX", "Library"),
    "ollama": ("Ollama", "Tool"),
    "langchain": ("LangChain", "Framework"),
    "chroma": ("ChromaDB", "Database"),
    "pydantic": ("Pydantic", "Library"),
    "sqlalchemy": ("SQLAlchemy", "Library")
}


def deterministic_kg_extraction(content: str) -> Dict[str, Any]:
    """Heuristic fallback extraction when LLMs fail or are unconfigured.
    
    Identifies known programming languages, frameworks, and capitalized proper nouns.
    """
    nodes: List[Dict[str, Any]] = []
    seen_ids = set()

    # 1. Match known technical entities
    content_lower = content.lower()
    for tech_id, (label, tech_type) in KNOWN_TECH_TERMS.items():
        if re.search(r'\b' + re.escape(tech_id) + r'\b', content_lower):
            if tech_id not in seen_ids:
                seen_ids.add(tech_id)
                nodes.append({
                    "id": tech_id,
                    "label": label,
                    "type": tech_type,
                    "properties": {"extraction_method": "deterministic_heuristic"}
                })

    # 2. Extract capitalized title words as candidate concepts
    proper_nouns = re.findall(r'\b[A-Z][a-zA-Z0-9_-]{2,}\b', content)
    stopwords = {"The", "This", "That", "With", "From", "Into", "Over", "Under", "When", "What", "Here"}
    for noun in proper_nouns:
        clean_id = noun.lower().strip()
        if clean_id not in seen_ids and noun not in stopwords:
            seen_ids.add(clean_id)
            nodes.append({
                "id": clean_id,
                "label": noun,
                "type": "Concept",
                "properties": {"extraction_method": "deterministic_heuristic"}
            })

    # 3. Create linear/semantic edges between discovered nodes
    edges: List[Dict[str, Any]] = []
    if len(nodes) >= 2:
        for i in range(len(nodes) - 1):
            src = nodes[i]["id"]
            tgt = nodes[i + 1]["id"]
            edges.append({
                "source_id": src,
                "target_id": tgt,
                "relation": "relates_to",
                "weight": 0.8
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "is_heuristic": True,
        "is_simulated": True
    }


async def extract_knowledge(
    content: str,
    db: Session,
    source_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Extract entities and relationships from content and save to the persistent knowledge graph."""
    if not content or not content.strip():
        raise ValueError("Content cannot be empty")
        
    max_chars = getattr(settings, "MAX_INPUT_CHAR_LENGTH", 50000)
    if len(content) > max_chars:
        raise ValueError(f"Content length exceeds {max_chars} characters limit")

    clean_content = content.strip()
    prompt = f"""Analyze the text below and extract key entities (concepts, libraries, databases, frameworks, projects) and the relationships between them.
Format the output STRICTLY as a JSON object with two keys:
1. "nodes": a list of objects containing "id" (unique lowercase identifier, e.g. "python"), "label" (display name, e.g. "Python"), and "type" (category, e.g. "Language", "Library", "Database").
2. "edges": a list of objects containing "source_id" (matching a node's id), "target_id" (matching a node's id), "relation" (how they connect, e.g. "written_in", "stores_data_in", "part_of"), and "weight" (value between 0.1 and 1.0).

Text to analyze:
"{clean_content}"

Example Response:
{{
  "nodes": [
    {{"id": "python", "label": "Python", "type": "Language"}}
  ],
  "edges": [
    {{"source_id": "langgraph", "target_id": "python", "relation": "written_in", "weight": 1.0}}
  ]
}}"""

    is_heuristic = False
    is_simulated = False
    raw_output = ""

    try:
        res = await execute_llm_call("KnowledgeGraphAgent", prompt, db, complexity_override="medium")
        raw_output = res.get("output", "").strip()
        is_simulated = res.get("is_simulated", False)
    except Exception as llm_err:
        logger.warning("LLM extraction failed, using deterministic fallback: %s", str(llm_err))
        raw_output = ""

    # Parse JSON or fallback
    data = None
    if raw_output:
        # Strip markdown fences
        cleaned_text = raw_output
        if "```json" in cleaned_text:
            cleaned_text = cleaned_text.split("```json", 1)[1]
        if "```" in cleaned_text:
            cleaned_text = cleaned_text.split("```", 1)[0]
        cleaned_text = cleaned_text.strip()
        
        # Regex search for JSON object if extra conversational prefix/suffix exists
        json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

    if not data or not isinstance(data.get("nodes"), list) or len(data.get("nodes", [])) == 0:
        logger.info("Using deterministic heuristic extraction for knowledge graph.")
        data = deterministic_kg_extraction(clean_content)
        is_heuristic = True
        is_simulated = True

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    extracted_nodes: List[Dict[str, Any]] = []
    extracted_edges: List[Dict[str, Any]] = []

    # 1. Save and Upsert Nodes
    seen_node_ids = set()
    for n in nodes:
        raw_id = str(n.get("id", "")).strip().lower()
        node_id = re.sub(r'[^a-z0-9_-]', '_', raw_id)
        label = str(n.get("label", "")).strip() or node_id.capitalize()
        
        raw_type = str(n.get("type", "Concept")).strip().lower()
        node_type = raw_type.capitalize() if raw_type in ALLOWED_ENTITY_TYPES else "Concept"
        
        if not node_id or len(node_id) < 2:
            continue
            
        if node_id not in seen_node_ids:
            seen_node_ids.add(node_id)
            
            node_props = dict(n.get("properties", {}))
            if source_metadata:
                node_props.update(source_metadata)
            if is_heuristic:
                node_props["is_heuristic"] = True

            existing_node = db.query(GraphNodeDB).filter(GraphNodeDB.id == node_id).first()
            if existing_node:
                # Update existing properties
                merged = dict(existing_node.properties or {})
                merged.update(node_props)
                existing_node.properties = merged
                existing_node.label = label
                existing_node.type = node_type
            else:
                db_node = GraphNodeDB(
                    id=node_id,
                    label=label,
                    type=node_type,
                    properties=node_props
                )
                db.add(db_node)
            
            extracted_nodes.append({"id": node_id, "label": label, "type": node_type, "properties": node_props})

    try:
        db.commit()
    except Exception as db_err:
        logger.error("Error committing nodes to graph DB: %s", str(db_err))
        db.rollback()

    # 2. Save and Upsert Edges
    seen_edge_keys = set()
    for e in edges:
        raw_src = str(e.get("source_id") or e.get("source") or "").strip().lower()
        raw_tgt = str(e.get("target_id") or e.get("target") or "").strip().lower()
        src = re.sub(r'[^a-z0-9_-]', '_', raw_src)
        tgt = re.sub(r'[^a-z0-9_-]', '_', raw_tgt)
        
        raw_rel = str(e.get("relation", "connects_to")).strip().lower()
        rel = re.sub(r'[^a-z0-9_-]', '_', raw_rel) or "connects_to"
        
        try:
            wt = max(0.1, min(1.0, float(e.get("weight", 1.0))))
        except (ValueError, TypeError):
            wt = 1.0

        if not src or not tgt or src == tgt:
            continue

        # Ensure both endpoints exist in DB (create placeholder if needed)
        for nid in [src, tgt]:
            if not db.query(GraphNodeDB).filter(GraphNodeDB.id == nid).first():
                ph = GraphNodeDB(id=nid, label=nid.capitalize(), type="Concept", properties={"is_placeholder": True})
                db.add(ph)
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        edge_key = (src, tgt, rel)
        if edge_key not in seen_edge_keys:
            seen_edge_keys.add(edge_key)
            
            exists_edge = db.query(GraphEdgeDB).filter(
                GraphEdgeDB.source_id == src,
                GraphEdgeDB.target_id == tgt,
                GraphEdgeDB.relation == rel
            ).first()

            if exists_edge:
                exists_edge.weight = wt
            else:
                db_edge = GraphEdgeDB(
                    source_id=src,
                    target_id=tgt,
                    relation=rel,
                    weight=wt
                )
                db.add(db_edge)

            extracted_edges.append({
                "source": src,
                "target": tgt,
                "source_id": src,
                "target_id": tgt,
                "relation": rel,
                "weight": wt
            })

    try:
        db.commit()
    except Exception as db_err:
        logger.error("Error committing edges to graph DB: %s", str(db_err))
        db.rollback()

    return {
        "nodes": extracted_nodes,
        "edges": extracted_edges,
        "is_heuristic": is_heuristic,
        "is_simulated": is_simulated,
        "extracted_count": len(extracted_nodes)
    }


def get_graph_data(
    db: Session,
    limit: Optional[int] = None,
    node_type: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve all or filtered nodes and edges from SQLite database."""
    query = db.query(GraphNodeDB)
    if node_type and node_type.strip():
        query = query.filter(GraphNodeDB.type.ilike(node_type.strip()))
    if limit and limit > 0:
        query = query.limit(limit)
    nodes = query.all()
    node_ids = {n.id for n in nodes}

    edge_query = db.query(GraphEdgeDB)
    if node_type and node_type.strip():
        edge_query = edge_query.filter(
            GraphEdgeDB.source_id.in_(node_ids),
            GraphEdgeDB.target_id.in_(node_ids)
        )
    edges = edge_query.all()

    return {
        "nodes": [
            {
                "id": n.id,
                "label": n.label,
                "type": n.type,
                "properties": n.properties or {},
                "created_at": n.created_at
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_id": e.source_id,
                "target_id": e.target_id,
                "source": e.source_id,
                "target": e.target_id,
                "relation": e.relation,
                "weight": e.weight,
                "created_at": e.created_at
            }
            for e in edges
        ]
    }


def get_node_by_id(node_id: str, db: Session) -> Optional[Dict[str, Any]]:
    """Retrieve a single node along with its incident in-edges, out-edges, and connectivity degree."""
    clean_id = node_id.strip().lower()
    node = db.query(GraphNodeDB).filter(GraphNodeDB.id == clean_id).first()
    if not node:
        return None

    in_edges = db.query(GraphEdgeDB).filter(GraphEdgeDB.target_id == clean_id).all()
    out_edges = db.query(GraphEdgeDB).filter(GraphEdgeDB.source_id == clean_id).all()

    return {
        "id": node.id,
        "label": node.label,
        "type": node.type,
        "properties": node.properties or {},
        "created_at": node.created_at,
        "degree": len(in_edges) + len(out_edges),
        "in_edges": [
            {"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "relation": e.relation, "weight": e.weight}
            for e in in_edges
        ],
        "out_edges": [
            {"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "relation": e.relation, "weight": e.weight}
            for e in out_edges
        ]
    }


def get_node_neighbors(node_id: str, db: Session, depth: int = 1) -> Dict[str, Any]:
    """Retrieve the k-hop neighborhood subgraph centered around a target entity."""
    clean_id = node_id.strip().lower()
    center_node = db.query(GraphNodeDB).filter(GraphNodeDB.id == clean_id).first()
    if not center_node:
        return {"nodes": [], "edges": []}

    visited_node_ids = {clean_id}
    current_frontier = {clean_id}

    for _ in range(min(depth, 3)):
        edges = db.query(GraphEdgeDB).filter(
            (GraphEdgeDB.source_id.in_(current_frontier)) |
            (GraphEdgeDB.target_id.in_(current_frontier))
        ).all()
        
        next_frontier = set()
        for e in edges:
            for endpoint in [e.source_id, e.target_id]:
                if endpoint not in visited_node_ids:
                    visited_node_ids.add(endpoint)
                    next_frontier.add(endpoint)
        current_frontier = next_frontier
        if not current_frontier:
            break

    nodes = db.query(GraphNodeDB).filter(GraphNodeDB.id.in_(visited_node_ids)).all()
    edges = db.query(GraphEdgeDB).filter(
        GraphEdgeDB.source_id.in_(visited_node_ids),
        GraphEdgeDB.target_id.in_(visited_node_ids)
    ).all()

    return {
        "center_node_id": clean_id,
        "nodes": [
            {"id": n.id, "label": n.label, "type": n.type, "properties": n.properties or {}}
            for n in nodes
        ],
        "edges": [
            {"source_id": e.source_id, "target_id": e.target_id, "relation": e.relation, "weight": e.weight}
            for e in edges
        ]
    }


def delete_node(node_id: str, db: Session) -> bool:
    """Delete an entity node and cascade-delete its incident edges."""
    clean_id = node_id.strip().lower()
    node = db.query(GraphNodeDB).filter(GraphNodeDB.id == clean_id).first()
    if not node:
        return False

    # Delete connected edges
    db.query(GraphEdgeDB).filter(
        (GraphEdgeDB.source_id == clean_id) | (GraphEdgeDB.target_id == clean_id)
    ).delete(synchronize_session=False)

    db.delete(node)
    db.commit()
    return True


def search_nodes(query: str, db: Session, limit: int = 20) -> List[Dict[str, Any]]:
    """Case-insensitive search across entity IDs, labels, and types."""
    if not query or not query.strip():
        return []
    clean_q = f"%{query.strip().lower()}%"
    from sqlalchemy import or_, func
    nodes = db.query(GraphNodeDB).filter(
        or_(
            func.lower(GraphNodeDB.id).like(clean_q),
            func.lower(GraphNodeDB.label).like(clean_q),
            func.lower(GraphNodeDB.type).like(clean_q)
        )
    ).limit(limit).all()

    return [
        {"id": n.id, "label": n.label, "type": n.type, "properties": n.properties or {}}
        for n in nodes
    ]


async def extract_from_memory(memory_id: str, db: Session) -> Optional[Dict[str, Any]]:
    """Extract entities directly from a persistent memory record and record cross-linking metadata."""
    clean_id = memory_id.strip()
    memory = db.query(MemoryDB).filter(MemoryDB.id == clean_id).first()
    if not memory or not memory.content:
        return None

    return await extract_knowledge(
        content=memory.content,
        db=db,
        source_metadata={"source_memory_id": clean_id, "source_type": memory.type}
    )

def generate_visjs_html(db: Session) -> str:
    """Generate interactive VisJS network HTML containing nodes/edges.
    
    Dynamically sizes nodes based on degree of connectivity calculated via NetworkX.
    """
    graph_data = get_graph_data(db)
    nodes = graph_data["nodes"]
    edges = graph_data["edges"]
    
    # Compute node degrees using networkx for sizing
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        G.add_edge(e["source"], e["target"])
        
    degrees = dict(G.degree())
    
    # Map colors to node types
    colors = {
        "language": "#FFD700",      # gold
        "library": "#00FA9A",       # medium spring green
        "database": "#FF4500",      # orange red
        "project": "#1E90FF",       # dodger blue
        "concept": "#BA55D3",       # medium orchid
        "default": "#ADFF2F"        # green yellow
    }
    
    vis_nodes = []
    for n in nodes:
        node_id = n["id"]
        node_type = n["type"].lower()
        node_color = colors.get(node_type, colors["default"])
        
        deg = degrees.get(node_id, 1)
        size = 15 + (deg * 5)  # Dynamic sizing
        
        vis_nodes.append({
            "id": node_id,
            "label": n["label"],
            "title": f"Type: {n['type']}\nDegree: {deg}",
            "color": {
                "background": node_color,
                "border": "#222222",
                "highlight": {
                    "background": "#FFFFFF",
                    "border": "#000000"
                }
            },
            "size": size,
            "font": {"color": "#FFFFFF", "size": 14}
        })
        
    vis_edges = []
    for e in edges:
        vis_edges.append({
            "from": e["source"],
            "to": e["target"],
            "label": e["relation"],
            "title": f"Relation: {e['relation']}\nWeight: {e['weight']}",
            "value": e["weight"],
            "color": {"color": "#848484", "highlight": "#FFFFFF"},
            "font": {"color": "#CCCCCC", "size": 10}
        })
        
    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    
    # HTML/JS iframe template for vis.js
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style type="text/css">
            body {{
                background-color: #0E1117;
                margin: 0;
                padding: 0;
                overflow: hidden;
            }}
            #mynetwork {{
                width: 100vw;
                height: 100vh;
                border: none;
            }}
        </style>
    </head>
    <body>
    <div id="mynetwork"></div>
    <script type="text/javascript">
        var nodes = new vis.DataSet({nodes_json});
        var edges = new vis.DataSet({edges_json});

        var container = document.getElementById('mynetwork');
        var data = {{
            nodes: nodes,
            edges: edges
        }};
        var options = {{
            nodes: {{
                shape: 'dot',
                borderWidth: 2,
                shadow: true
            }},
            edges: {{
                width: 2,
                arrows: {{
                    to: {{enabled: true, scaleFactor: 0.5}}
                }},
                shadow: true
            }},
            physics: {{
                barnesHut: {{
                    gravitationalConstant: -8000,
                    centralGravity: 0.3,
                    springLength: 95,
                    springConstant: 0.04,
                    damping: 0.09,
                    avoidOverlap: 0.1
                }},
                stabilization: {{iterations: 150}}
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 200,
                navigationButtons: true,
                keyboard: true
            }}
        }};
        var network = new vis.Network(container, data, options);
        
        // Return click events back if needed in future integrations
        network.on("click", function (params) {{
            if (params.nodes.length > 0) {{
                var nodeId = params.nodes[0];
                console.log("Clicked node: " + nodeId);
            }}
        }});
    </script>
    </body>
    </html>
    """
    return html_content
