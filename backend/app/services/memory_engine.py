import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import MemoryDB
from backend.app.core.vector_store import add_document, query_documents, delete_document
from backend.app.services.model_router import execute_llm_call

logger = logging.getLogger(__name__)

def calculate_importance(content: str) -> float:
    """Calculate importance score between 0.0 and 10.0.
    
    Uses keywords and content length heuristics or simulated LLM ranking.
    """
    score = 1.0
    lower_content = content.lower()
    
    # Keyword matches
    high_value_keywords = ["goal", "deadline", "architecture", "password", "api", "project", "critical", "bug", "error"]
    medium_value_keywords = ["meeting", "discuss", "plan", "learn", "course", "tomorrow", "next week"]
    
    for kw in high_value_keywords:
        if kw in lower_content:
            score += 2.0
            
    for kw in medium_value_keywords:
        if kw in lower_content:
            score += 1.0
            
    # Length heuristic
    score += min(3.0, len(content) / 300.0)
    
    return min(10.0, score)

async def add_memory(
    content: str,
    memory_type: str,
    db: Session,
    metadata: Optional[Dict[str, Any]] = None
) -> MemoryDB:
    """Create a new memory, score it, summarize if necessary, index semantically, and save to DB."""
    metadata = metadata or {}
    importance_score = calculate_importance(content)
    
    # Auto-summarization for long memories
    summary = content
    if len(content) > 300:
        prompt = f"Summarize this memory into a single sentence under 100 characters:\n\n{content}"
        res = await execute_llm_call("MemorySummarizer", prompt, db, complexity_override="low")
        summary = res["output"]
        
    metadata["summary"] = summary
    
    # Save database entry
    db_memory = MemoryDB(
        content=content,
        type=memory_type,
        importance_score=importance_score,
        metadata_json=metadata
    )
    db.add(db_memory)
    db.commit()
    db.refresh(db_memory)
    
    # Add to semantic vector store
    try:
        add_document(
            collection_name="memories",
            doc_id=db_memory.id,
            text=content,
            metadata={"type": memory_type, "importance": importance_score}
        )
    except Exception as e:
        logger.error("Failed to index memory semantically: %s", str(e))
        
    return db_memory

def search_memories(query: str, db: Session, limit: int = 5) -> List[Dict[str, Any]]:
    """Hybrid semantic search: search vector store, then map results back to database records."""
    vector_results = query_documents("memories", query, n_results=limit)
    
    results = []
    for vr in vector_results:
        mem_id = vr["id"]
        # Fetch detailed database record
        db_mem = db.query(MemoryDB).filter(MemoryDB.id == mem_id).first()
        if db_mem:
            results.append({
                "id": db_mem.id,
                "content": db_mem.content,
                "type": db_mem.type,
                "importance_score": db_mem.importance_score,
                "created_at": db_mem.created_at,
                "similarity": vr.get("similarity", 1.0),
                "metadata": db_mem.metadata_json
            })
            
    return results

def get_memory_timeline(db: Session, memory_type: Optional[str] = None, limit: int = 50) -> List[MemoryDB]:
    """Retrieve chronologically ordered memories, optionally filtered by type."""
    query = db.query(MemoryDB)
    if memory_type:
        query = query.filter(MemoryDB.type == memory_type)
    return query.order_by(MemoryDB.created_at.desc()).limit(limit).all()

def edit_memory(memory_id: str, new_content: str, db: Session) -> Optional[MemoryDB]:
    """Modify database memory content and update semantic index."""
    db_mem = db.query(MemoryDB).filter(MemoryDB.id == memory_id).first()
    if not db_mem:
        return None
        
    db_mem.content = new_content
    db_mem.importance_score = calculate_importance(new_content)
    db.commit()
    db.refresh(db_mem)
    
    # Update Vector Store
    try:
        add_document(
            collection_name="memories",
            doc_id=db_mem.id,
            text=new_content,
            metadata={"type": db_mem.type, "importance": db_mem.importance_score}
        )
    except Exception as e:
        logger.error("Failed to update memory index: %s", str(e))
        
    return db_mem

def delete_memory_by_id(memory_id: str, db: Session) -> bool:
    """Delete a memory from database and semantic index."""
    db_mem = db.query(MemoryDB).filter(MemoryDB.id == memory_id).first()
    if not db_mem:
        return False
        
    db.delete(db_mem)
    db.commit()
    
    # Remove from Vector Store
    try:
        delete_document("memories", memory_id)
    except Exception as e:
        logger.error("Failed to delete memory index: %s", str(e))
        
    return True
