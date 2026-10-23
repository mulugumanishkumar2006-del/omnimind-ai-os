import re
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import MemoryDB
from backend.app.core.vector_store import add_document, query_documents, delete_document
from backend.app.services.model_router import execute_llm_call

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_TYPES = {"short_term", "long_term", "session", "semantic"}

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
    
    return round(min(10.0, score), 2)

def compute_lexical_score(query: str, text: str) -> float:
    """Compute a continuous lexical relevance score between 0.0 and 1.0."""
    if not query or not query.strip() or not text or not text.strip():
        return 0.0
        
    q_clean = query.strip().lower()
    t_clean = text.strip().lower()
    
    # Exact full match or substring match
    if q_clean == t_clean:
        return 0.98
    if q_clean in t_clean:
        return 0.90
        
    # Token matching
    q_tokens = [w for w in re.findall(r'\b\w+\b', q_clean) if len(w) > 1]
    if not q_tokens:
        q_tokens = [q_clean]
        
    t_tokens = set(re.findall(r'\b\w+\b', t_clean))
    matched = sum(1 for tok in q_tokens if tok in t_tokens)
    
    if matched == 0:
        return 0.0
        
    ratio = matched / len(q_tokens)
    # Continuous confidence scale: 0.40 to 0.85
    return round(0.40 + (0.45 * ratio), 4)

async def add_memory(
    content: str,
    memory_type: str,
    db: Session,
    metadata: Optional[Dict[str, Any]] = None,
    importance_score: Optional[float] = None
) -> MemoryDB:
    """Create a new memory, score it, summarize if necessary, index semantically, and save to DB."""
    if not content or not content.strip():
        raise ValueError("Memory content cannot be empty or whitespace.")
    content = content.strip()
    
    if not memory_type or not str(memory_type).strip():
        raise ValueError("Memory type must be specified.")
    clean_type = str(memory_type).strip().lower()
    if clean_type not in ALLOWED_MEMORY_TYPES:
        raise ValueError(
            f"Invalid memory type '{memory_type}'. Allowed types: {', '.join(sorted(ALLOWED_MEMORY_TYPES))}"
        )
        
    metadata = dict(metadata) if metadata else {}
    
    # Determine importance score
    if importance_score is not None and importance_score > 0.0:
        calc_score = round(float(importance_score), 2)
    else:
        calc_score = calculate_importance(content)
    
    # Auto-summarization for long memories (>300 chars)
    summary = content
    if len(content) > 300:
        prompt = f"Summarize this memory into a single sentence under 100 characters:\n\n{content}"
        try:
            res = await execute_llm_call("MemorySummarizer", prompt, db, complexity_override="low")
            if res.get("success", False) and res.get("output"):
                summary = res["output"]
            else:
                summary = content[:147] + "..."
        except Exception as e:
            logger.warning("Auto-summarization failed, using truncated content: %s", str(e))
            summary = content[:147] + "..."
        
    metadata["summary"] = summary
    
    # Save database entry
    db_memory = MemoryDB(
        content=content,
        type=clean_type,
        importance_score=calc_score,
        metadata_json=metadata
    )
    db.add(db_memory)
    db.commit()
    db.refresh(db_memory)
    
    # Add to semantic vector store
    session_id = metadata.get("session_id", "")
    try:
        add_document(
            collection_name="memories",
            doc_id=db_memory.id,
            text=content,
            metadata={"type": clean_type, "importance": calc_score, "session_id": str(session_id)}
        )
    except Exception as e:
        logger.error("Failed to index memory semantically: %s", str(e))
        
    return db_memory

def get_memory_by_id(memory_id: str, db: Session) -> Optional[MemoryDB]:
    """Retrieve a single memory by its unique stable ID."""
    return db.query(MemoryDB).filter(MemoryDB.id == memory_id).first()

def get_memory_timeline(
    db: Session,
    memory_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50
) -> List[MemoryDB]:
    """Retrieve chronologically ordered memories, optionally filtered by type and/or session_id."""
    query = db.query(MemoryDB)
    if memory_type:
        clean_type = memory_type.strip().lower()
        query = query.filter(MemoryDB.type == clean_type)
        
    if session_id:
        try:
            query = query.filter(MemoryDB.metadata_json["session_id"].as_string() == session_id)
            return query.order_by(MemoryDB.created_at.desc()).limit(limit).all()
        except Exception:
            # Fallback in-memory session matching for dialects without JSON index operators
            items = query.order_by(MemoryDB.created_at.desc()).all()
            return [
                m for m in items
                if isinstance(m.metadata_json, dict) and str(m.metadata_json.get("session_id")) == str(session_id)
            ][:limit]
            
    return query.order_by(MemoryDB.created_at.desc()).limit(limit).all()

def search_memories(
    query: str,
    db: Session,
    limit: int = 5,
    memory_type: Optional[str] = None,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Hybrid semantic search: combines vector similarity and lexical matching with reciprocal blending."""
    if not query or not query.strip():
        return []
    query = query.strip()
    
    clean_type = memory_type.strip().lower() if memory_type else None
    
    # 1. Vector Search
    where_filter = {}
    if clean_type:
        where_filter["type"] = clean_type
    if session_id:
        where_filter["session_id"] = str(session_id)
        
    vector_scores: Dict[str, float] = {}
    try:
        vector_results = query_documents(
            "memories",
            query,
            n_results=limit * 2,
            where=where_filter if where_filter else None
        )
        for vr in vector_results:
            vector_scores[vr["id"]] = vr.get("similarity", 0.0)
    except Exception as e:
        logger.error("Vector search query error in search_memories: %s", str(e))

    # 2. Candidate collection (from vector hits and keyword matches)
    candidate_ids = set(vector_scores.keys())
    
    # Keyword search across DB records
    kw_query = db.query(MemoryDB)
    if clean_type:
        kw_query = kw_query.filter(MemoryDB.type == clean_type)
    
    # Match query substring or tokens
    tokens = [t for t in re.findall(r'\b\w+\b', query) if len(t) > 1]
    if tokens:
        token_filters = [MemoryDB.content.ilike(f"%{t}%") for t in tokens[:4]]
        from sqlalchemy import or_
        kw_matches = kw_query.filter(or_(*token_filters)).limit(limit * 2).all()
    else:
        kw_matches = kw_query.filter(MemoryDB.content.ilike(f"%{query}%")).limit(limit * 2).all()
        
    for kw_mem in kw_matches:
        if session_id and isinstance(kw_mem.metadata_json, dict):
            if str(kw_mem.metadata_json.get("session_id")) != str(session_id):
                continue
        candidate_ids.add(kw_mem.id)

    # 3. Retrieve records, calculate blended scores
    results = []
    if candidate_ids:
        records = db.query(MemoryDB).filter(MemoryDB.id.in_(list(candidate_ids))).all()
        for mem in records:
            # Verify type filter
            if clean_type and mem.type.lower() != clean_type:
                continue
            # Verify session filter
            if session_id:
                doc_sess = mem.metadata_json.get("session_id") if isinstance(mem.metadata_json, dict) else None
                if str(doc_sess) != str(session_id):
                    continue

            v_score = vector_scores.get(mem.id, 0.0)
            lex_score = compute_lexical_score(query, mem.content)
            
            # Blended score: reward items matched in both channels
            if v_score > 0.0 and lex_score > 0.0:
                blended = min(1.0, 0.55 * v_score + 0.40 * lex_score + 0.05)
            elif v_score > 0.0:
                blended = v_score
            else:
                blended = lex_score

            results.append({
                "id": mem.id,
                "content": mem.content,
                "type": mem.type,
                "importance_score": mem.importance_score,
                "created_at": mem.created_at,
                "similarity": round(blended, 4),
                "metadata": mem.metadata_json
            })

    # Sort descending by score
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]

def edit_memory(
    memory_id: str,
    new_content: str,
    db: Session,
    new_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[MemoryDB]:
    """Modify database memory content, type, or metadata, and update semantic vector index."""
    if not new_content or not new_content.strip():
        raise ValueError("Memory content cannot be empty.")
    new_content = new_content.strip()
    
    db_mem = db.query(MemoryDB).filter(MemoryDB.id == memory_id).first()
    if not db_mem:
        return None
        
    db_mem.content = new_content
    db_mem.importance_score = calculate_importance(new_content)
    
    if new_type:
        clean_type = new_type.strip().lower()
        if clean_type not in ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"Invalid memory type '{new_type}'. Allowed types: {', '.join(sorted(ALLOWED_MEMORY_TYPES))}"
            )
        db_mem.type = clean_type
        
    if metadata is not None:
        merged_meta = dict(db_mem.metadata_json or {})
        merged_meta.update(metadata)
        db_mem.metadata_json = merged_meta

    db.commit()
    db.refresh(db_mem)
    
    # Update Vector Store
    sess_id = db_mem.metadata_json.get("session_id", "") if isinstance(db_mem.metadata_json, dict) else ""
    try:
        add_document(
            collection_name="memories",
            doc_id=db_mem.id,
            text=new_content,
            metadata={
                "type": db_mem.type,
                "importance": db_mem.importance_score,
                "session_id": str(sess_id)
            }
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

