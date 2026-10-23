import re
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import MemoryDB, TaskDB, MeetingDB, GraphNodeDB
from backend.app.services.memory_engine import search_memories

logger = logging.getLogger(__name__)

ALLOWED_COLLECTIONS = {"memory", "task", "meeting", "graph"}

def compute_entity_lexical_score(query: str, title: str, body: Optional[str] = None) -> float:
    """Compute normalized lexical relevance score in [0.35, 0.98]."""
    if not query or not query.strip():
        return 0.0
    
    q_clean = query.strip().lower()
    t_clean = (title or "").strip().lower()
    b_clean = (body or "").strip().lower()
    
    if q_clean == t_clean:
        return 0.98
    if q_clean in t_clean:
        return 0.92
    if b_clean and q_clean in b_clean:
        return 0.85
        
    q_tokens = [w for w in re.findall(r'\b\w+\b', q_clean) if len(w) > 1]
    if not q_tokens:
        q_tokens = [q_clean]
        
    t_tokens = set(re.findall(r'\b\w+\b', t_clean))
    b_tokens = set(re.findall(r'\b\w+\b', b_clean)) if b_clean else set()
    
    matched_title = sum(1 for tok in q_tokens if tok in t_tokens)
    matched_body = sum(1 for tok in q_tokens if tok in b_tokens)
    
    ratio_t = matched_title / len(q_tokens)
    ratio_b = matched_body / len(q_tokens)
    
    combined_ratio = (ratio_t * 0.65) + (ratio_b * 0.35)
    if combined_ratio <= 0.0:
        return 0.40
        
    final_score = 0.40 + (0.50 * min(1.0, combined_ratio))
    return round(final_score, 4)

def extract_snippet(text: str, query: str, max_chars: int = 150) -> str:
    """Extract a representative snippet centered around query terms if possible."""
    if not text:
        return ""
    clean_text = text.strip()
    if len(clean_text) <= max_chars:
        return clean_text
        
    lower_text = clean_text.lower()
    lower_query = query.lower()
    idx = lower_text.find(lower_query)
    
    if idx == -1:
        # Check individual tokens
        tokens = [t for t in re.findall(r'\b\w+\b', lower_query) if len(t) > 2]
        for tok in tokens:
            t_idx = lower_text.find(tok)
            if t_idx != -1:
                idx = t_idx
                break
                
    if idx == -1:
        return clean_text[:max_chars].rstrip() + "..."
        
    start = max(0, idx - 40)
    end = min(len(clean_text), start + max_chars)
    snippet = clean_text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean_text):
        snippet = snippet + "..."
    return snippet

def run_hybrid_search(
    query: str,
    db: Session,
    limit: int = 5,
    collection_filter: Optional[str] = None
) -> Dict[str, Any]:
    """Search across memories, tasks, meetings, and knowledge nodes with dynamic scores and citations."""
    if not query or not query.strip():
        return {
            "query": query,
            "results": [],
            "citations": []
        }
    query = query.strip()
    
    clean_filter = None
    if collection_filter:
        cf = collection_filter.strip().lower()
        if cf not in ALLOWED_COLLECTIONS and cf != "all":
            raise ValueError(
                f"Invalid collection_filter '{collection_filter}'. Allowed: {', '.join(sorted(ALLOWED_COLLECTIONS))}, or None."
            )
        clean_filter = cf if cf != "all" else None

    results: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    
    # 1. Search Memories (Semantic Vector + Lexical Search)
    if not clean_filter or clean_filter == "memory":
        memory_matches = search_memories(query, db, limit=limit)
        for m in memory_matches:
            sim = m.get("similarity", 0.75)
            results.append({
                "type": "memory",
                "title": f"Memory ({m['type'].replace('_', ' ').title()})",
                "content": m["content"],
                "score": sim,
                "created_at": m["created_at"]
            })
            citations.append({
                "source_type": "memory",
                "source_id": m["id"],
                "title": f"Memory Vault [{m['type'].title()}]",
                "text_snippet": extract_snippet(m["content"], query),
                "confidence": sim
            })

    from sqlalchemy import or_
    tokens = [t for t in re.findall(r'\b\w+\b', query) if len(t) > 2]

    # 2. Search Tasks (Keyword Database Search)
    if not clean_filter or clean_filter == "task":
        if tokens:
            task_filters = [(TaskDB.title.ilike(f"%{t}%")) | (TaskDB.description.ilike(f"%{t}%")) for t in tokens[:4]]
            task_matches = db.query(TaskDB).filter(or_(*task_filters)).limit(limit * 2).all()
        else:
            task_matches = db.query(TaskDB).filter(
                (TaskDB.title.ilike(f"%{query}%")) | 
                (TaskDB.description.ilike(f"%{query}%"))
            ).limit(limit * 2).all()
        
        for t in task_matches:
            score = compute_entity_lexical_score(query, t.title, t.description)
            results.append({
                "type": "task",
                "title": f"Task: {t.title}",
                "content": t.description or "No description",
                "score": score,
                "created_at": t.created_at
            })
            citations.append({
                "source_type": "task",
                "source_id": t.id,
                "title": f"Task: {t.title}",
                "text_snippet": extract_snippet(t.description or "No description", query),
                "confidence": score
            })

    # 3. Search Meetings (Keyword Database Search)
    if not clean_filter or clean_filter == "meeting":
        if tokens:
            meeting_filters = [
                (MeetingDB.title.ilike(f"%{t}%")) |
                (MeetingDB.transcript.ilike(f"%{t}%")) |
                (MeetingDB.summary.ilike(f"%{t}%"))
                for t in tokens[:4]
            ]
            meeting_matches = db.query(MeetingDB).filter(or_(*meeting_filters)).limit(limit * 2).all()
        else:
            meeting_matches = db.query(MeetingDB).filter(
                (MeetingDB.title.ilike(f"%{query}%")) |
                (MeetingDB.transcript.ilike(f"%{query}%")) |
                (MeetingDB.summary.ilike(f"%{query}%"))
            ).limit(limit * 2).all()
        
        for m in meeting_matches:
            score = compute_entity_lexical_score(query, m.title, m.summary or m.transcript)
            snippet_text = m.summary or m.transcript or "No transcript"
            results.append({
                "type": "meeting",
                "title": f"Meeting: {m.title}",
                "content": snippet_text[:300],
                "score": score,
                "created_at": m.created_at
            })
            citations.append({
                "source_type": "meeting",
                "source_id": m.id,
                "title": f"Meeting: {m.title}",
                "text_snippet": extract_snippet(snippet_text, query),
                "confidence": score
            })

    # 4. Search Knowledge Graph Nodes (Keyword Node ID/Label Search)
    if not clean_filter or clean_filter == "graph":
        if tokens:
            node_filters = [(GraphNodeDB.id.ilike(f"%{t}%")) | (GraphNodeDB.label.ilike(f"%{t}%")) for t in tokens[:4]]
            node_matches = db.query(GraphNodeDB).filter(or_(*node_filters)).limit(limit * 2).all()
        else:
            node_matches = db.query(GraphNodeDB).filter(
                (GraphNodeDB.id.ilike(f"%{query}%")) |
                (GraphNodeDB.label.ilike(f"%{query}%"))
            ).limit(limit * 2).all()

        
        for n in node_matches:
            body_text = f"Entity category: {n.type}. Properties: {n.properties}"
            score = compute_entity_lexical_score(query, n.label, body_text)
            results.append({
                "type": "graph_node",
                "title": f"KG Node: {n.label}",
                "content": body_text,
                "score": score,
                "created_at": n.created_at
            })
            citations.append({
                "source_type": "graph",
                "source_id": n.id,
                "title": f"Knowledge Node: {n.label}",
                "text_snippet": extract_snippet(body_text, query),
                "confidence": score
            })

    # Sort combined results and citations by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    citations.sort(key=lambda x: x["confidence"], reverse=True)
    
    return {
        "query": query,
        "results": results[:limit],
        "citations": citations[:limit]
    }

