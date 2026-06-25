import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import MemoryDB, TaskDB, MeetingDB, GraphNodeDB
from backend.app.core.vector_store import query_documents
from backend.app.services.memory_engine import search_memories

logger = logging.getLogger(__name__)

def run_hybrid_search(
    query: str,
    db: Session,
    limit: int = 5,
    collection_filter: Optional[str] = None
) -> Dict[str, Any]:
    """Search across memories, tasks, meetings, and knowledge nodes. Compile citations."""
    results: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    
    # 1. Search Memories (Semantic Vector Search)
    if not collection_filter or collection_filter == "memory":
        memory_matches = search_memories(query, db, limit=limit)
        for m in memory_matches:
            results.append({
                "type": "memory",
                "title": f"Memory ({m['type'].replace('_', ' ').title()})",
                "content": m["content"],
                "score": m["similarity"],
                "created_at": m["created_at"]
            })
            citations.append({
                "source_type": "memory",
                "source_id": m["id"],
                "title": f"Memory Vault [{m['type'].title()}]",
                "text_snippet": m["content"][:150] + ("..." if len(m["content"]) > 150 else ""),
                "confidence": m["similarity"]
            })

    # 2. Search Tasks (Keyword Database Search)
    if not collection_filter or collection_filter == "task":
        task_matches = db.query(TaskDB).filter(
            (TaskDB.title.ilike(f"%{query}%")) | 
            (TaskDB.description.ilike(f"%{query}%"))
        ).limit(limit).all()
        
        for t in task_matches:
            results.append({
                "type": "task",
                "title": f"Task: {t.title}",
                "content": t.description or "No description",
                "score": 0.8,
                "created_at": t.created_at
            })
            citations.append({
                "source_type": "task",
                "source_id": t.id,
                "title": f"Task: {t.title}",
                "text_snippet": t.description[:150] if t.description else "No description",
                "confidence": 0.8
            })

    # 3. Search Meetings (Keyword Database Search)
    if not collection_filter or collection_filter == "meeting":
        meeting_matches = db.query(MeetingDB).filter(
            (MeetingDB.title.ilike(f"%{query}%")) |
            (MeetingDB.transcript.ilike(f"%{query}%")) |
            (MeetingDB.summary.ilike(f"%{query}%"))
        ).limit(limit).all()
        
        for m in meeting_matches:
            results.append({
                "type": "meeting",
                "title": f"Meeting: {m.title}",
                "content": m.summary or m.transcript[:300],
                "score": 0.75,
                "created_at": m.created_at
            })
            citations.append({
                "source_type": "meeting",
                "source_id": m.id,
                "title": f"Meeting summary of '{m.title}'",
                "text_snippet": m.summary[:150] if m.summary else m.transcript[:150],
                "confidence": 0.75
            })

    # 4. Search Knowledge Graph Nodes (Keyword Node ID/Label Search)
    if not collection_filter or collection_filter == "graph":
        node_matches = db.query(GraphNodeDB).filter(
            (GraphNodeDB.id.ilike(f"%{query}%")) |
            (GraphNodeDB.label.ilike(f"%{query}%"))
        ).limit(limit).all()
        
        for n in node_matches:
            results.append({
                "type": "graph_node",
                "title": f"KG Node: {n.label}",
                "content": f"Entity category: {n.type}. Metadata details: {n.properties}",
                "score": 0.85,
                "created_at": n.created_at
            })
            citations.append({
                "source_type": "graph",
                "source_id": n.id,
                "title": f"Knowledge Node: {n.label}",
                "text_snippet": f"Entity category: {n.type}",
                "confidence": 0.85
            })

    # Sort combined results by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    citations.sort(key=lambda x: x["confidence"], reverse=True)
    
    return {
        "query": query,
        "results": results[:limit],
        "citations": citations[:limit]
    }
