import json
import logging
import networkx as nx
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from backend.app.models.database_models import GraphNodeDB, GraphEdgeDB
from backend.app.services.model_router import execute_llm_call

logger = logging.getLogger(__name__)

async def extract_knowledge(content: str, db: Session) -> Dict[str, Any]:
    """Extract entities and relationships from content and save to the knowledge graph."""
    prompt = f"""Analyze the text below and extract key entities (concepts, libraries, databases, frameworks, projects) and the relationships between them.
Format the output STRICTLY as a JSON object with two keys:
1. "nodes": a list of objects containing "id" (unique lowercase identifier, e.g. "python"), "label" (display name, e.g. "Python"), and "type" (category, e.g. "Language", "Library", "Database").
2. "edges": a list of objects containing "source_id" (matching a node's id), "target_id" (matching a node's id), "relation" (how they connect, e.g. "written_in", "stores_data_in", "part_of"), and "weight" (value between 0.1 and 1.0).

Text to analyze:
"{content}"

Example Response:
{{
  "nodes": [
    {{"id": "python", "label": "Python", "type": "Language"}}
  ],
  "edges": [
    {{"source_id": "langgraph", "target_id": "python", "relation": "written_in", "weight": 1.0}}
  ]
}}"""

    res = await execute_llm_call("KnowledgeGraphAgent", prompt, db, complexity_override="medium")
    output = res["output"].strip()
    
    # Clean output formatting
    if output.startswith("```json"):
        output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
    output = output.strip()
    
    extracted_data = {"nodes": [], "edges": []}
    try:
        data = json.loads(output)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        # Save Nodes
        for n in nodes:
            node_id = n.get("id", "").strip().lower()
            label = n.get("label", "")
            node_type = n.get("type", "Concept")
            if not node_id or not label:
                continue
                
            # Upsert node
            existing_node = db.query(GraphNodeDB).filter(GraphNodeDB.id == node_id).first()
            if not existing_node:
                db_node = GraphNodeDB(
                    id=node_id,
                    label=label,
                    type=node_type,
                    properties=n.get("properties", {})
                )
                db.add(db_node)
            
            # Always return the nodes identified in the text
            extracted_data["nodes"].append({"id": node_id, "label": label, "type": node_type})
                
        db.commit()
        
        # Save Edges
        for e in edges:
            src = e.get("source_id", "").strip().lower()
            tgt = e.get("target_id", "").strip().lower()
            rel = e.get("relation", "connects_to")
            wt = float(e.get("weight", 1.0))
            
            if not src or not tgt:
                continue
                
            # Verify nodes exist (or insert them placeholders)
            for node_id in [src, tgt]:
                exists = db.query(GraphNodeDB).filter(GraphNodeDB.id == node_id).first()
                if not exists:
                    # Create placeholder node
                    ph_node = GraphNodeDB(
                        id=node_id,
                        label=node_id.capitalize(),
                        type="Concept"
                    )
                    db.add(ph_node)
            db.commit()
            
            # Check edge duplication
            exists_edge = db.query(GraphEdgeDB).filter(
                GraphEdgeDB.source_id == src,
                GraphEdgeDB.target_id == tgt,
                GraphEdgeDB.relation == rel
            ).first()
            
            if not exists_edge:
                db_edge = GraphEdgeDB(
                    source_id=src,
                    target_id=tgt,
                    relation=rel,
                    weight=wt
                )
                db.add(db_edge)
            
            # Always return the edges identified in the text
            extracted_data["edges"].append({"source": src, "target": tgt, "relation": rel})
                
        db.commit()
    except Exception as e:
        logger.error("Failed to parse knowledge graph extraction: %s. Output: %s", str(e), output)
        
    return extracted_data

def get_graph_data(db: Session) -> Dict[str, Any]:
    """Retrieve all nodes and edges from database for graph compilation."""
    nodes = db.query(GraphNodeDB).all()
    edges = db.query(GraphEdgeDB).all()
    
    return {
        "nodes": [{"id": n.id, "label": n.label, "type": n.type, "properties": n.properties} for n in nodes],
        "edges": [{"id": e.id, "source": e.source_id, "target": e.target_id, "relation": e.relation, "weight": e.weight} for e in edges]
    }

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
