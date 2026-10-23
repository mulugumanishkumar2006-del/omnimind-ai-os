import os
import re
import json
import logging
import hashlib
import numpy as np
from typing import List, Dict, Any, Optional
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy SentenceTransformer embedding model loading
_model = None
_model_load_attempted = False

def get_embedding_model():
    """Lazily load SentenceTransformer embedding model if available.
    
    If model loading fails or takes too long, fall back gracefully to the deterministic
    offline embedding engine without crashing or blocking future operations.
    """
    global _model, _model_load_attempted
    if _model is not None:
        return _model
    if _model_load_attempted:
        return None
        
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Initializing SentenceTransformer model: %s", settings.EMBEDDING_MODEL_NAME)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return _model
    except Exception as e:
        logger.warning(
            "SentenceTransformer not available or failed to load: %s. Using deterministic offline embedding engine.",
            str(e)
        )
        _model = None
        return None

def _deterministic_offline_embedding(text: str, dim: int = 384) -> List[float]:
    """Generate a 100% deterministic, normalized feature-hashing embedding vector.
    
    Uses SHA-256 and sublinear term frequency + character n-grams.
    Maintains consistent similarity across application restarts without downloading weights.
    """
    if not text or not str(text).strip():
        return [0.0] * dim

    clean_text = str(text).lower().strip()
    words = re.findall(r'\b\w+\b', clean_text)
    if not words:
        words = [clean_text]

    tf: Dict[str, float] = {}
    for w in words:
        tf[w] = tf.get(w, 0.0) + 1.0

    # Include word-internal trigrams with gentle weight for typo and partial match tolerance
    for w in words:
        if len(w) >= 3:
            for i in range(len(w) - 2):
                gram = w[i:i+3]
                tf[gram] = tf.get(gram, 0.0) + 0.15

    vec = np.zeros(dim, dtype=np.float32)
    for token, count in tf.items():
        weight = 1.0 + np.log(count)
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        seed = int(token_hash[:8], 16)
        rng = np.random.RandomState(seed)
        token_vec = rng.randn(dim)
        token_norm = np.linalg.norm(token_vec)
        if token_norm > 0:
            vec += (token_vec / token_norm) * weight

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()

def get_embedding(text: str) -> List[float]:
    """Generate a vector embedding for the given text.
    
    Uses SentenceTransformer if available, otherwise falls back to a deterministic,
    continuous feature-hashing offline projection that preserves term/n-gram similarity
    across application restarts.
    """
    if not text or not str(text).strip():
        return [0.0] * 384
        
    text_str = str(text).strip()
    model = get_embedding_model()
    if model is not None:
        try:
            embedding = model.encode(text_str)
            return embedding.tolist()
        except Exception as e:
            logger.error("Error generating neural embedding: %s. Falling back to deterministic engine.", str(e))
            
    return _deterministic_offline_embedding(text_str)


class LocalVectorStore:
    """A clean, NumPy-based cosine similarity vector database.
    
    Used when ChromaDB is unavailable or fails. Persists to a local JSON file.
    """
    def __init__(self, persist_dir: str):
        self.persist_path = os.path.join(persist_dir, "local_vector_store.json")
        os.makedirs(persist_dir, exist_ok=True)
        self.data: Dict[str, List[Dict[str, Any]]] = {}  # collection_name -> list of docs
        self.load()

    def load(self):
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                logger.info("Loaded local vector store from %s", self.persist_path)
            except Exception as e:
                logger.error("Failed to load local vector store: %s", str(e))
                self.data = {}

    def save(self):
        try:
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save local vector store: %s", str(e))

    def add(self, collection_name: str, id: str, text: str, embedding: List[float], metadata: Dict[str, Any]):
        if collection_name not in self.data:
            self.data[collection_name] = []
        
        # Remove existing if present to support upserts
        self.data[collection_name] = [d for d in self.data[collection_name] if d["id"] != id]
        
        self.data[collection_name].append({
            "id": id,
            "text": text,
            "embedding": embedding,
            "metadata": metadata
        })
        self.save()

    def query(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if collection_name not in self.data or not self.data[collection_name]:
            return []
        
        docs = self.data[collection_name]
        q_vec = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []
            
        results = []
        for d in docs:
            # Metadata filter matching
            if where:
                match = True
                doc_meta = d.get("metadata") or {}
                for k, v in where.items():
                    if doc_meta.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            d_vec = np.array(d["embedding"], dtype=np.float32)
            denom = q_norm * np.linalg.norm(d_vec)
            if denom > 0:
                raw_sim = float(np.dot(q_vec, d_vec) / denom)
                # Map cosine similarity to [0.0, 1.0]
                similarity = round(max(0.0, min(1.0, float(raw_sim))), 4)
            else:
                similarity = 0.0
            
            results.append({
                "id": d["id"],
                "text": d["text"],
                "metadata": d["metadata"],
                "similarity": similarity
            })
        
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:n_results]

    def delete(self, collection_name: str, id: str):
        if collection_name in self.data:
            self.data[collection_name] = [d for d in self.data[collection_name] if d["id"] != id]
            self.save()

    def count(self, collection_name: str) -> int:
        return len(self.data.get(collection_name, []))


# Initialize the Vector Store client
_vector_store_client = None
_use_chroma = False

try:
    import chromadb
    client = chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)
    _vector_store_client = client
    _use_chroma = True
    logger.info("ChromaDB persistent client successfully initialized.")
except Exception as e:
    logger.warning("ChromaDB initialization failed, using local numpy vector store: %s", str(e))
    _vector_store_client = LocalVectorStore(persist_dir=settings.CHROMA_DB_DIR)
    _use_chroma = False

def add_document(collection_name: str, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
    """Add or update a document and its embedding in the vector store."""
    global _vector_store_client, _use_chroma
    metadata = metadata or {}
    embedding = get_embedding(text)
    
    if _use_chroma:
        try:
            collection = _vector_store_client.get_or_create_collection(name=collection_name)
            if hasattr(collection, "upsert"):
                collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[metadata]
                )
            else:
                try:
                    collection.delete(ids=[doc_id])
                except Exception:
                    pass
                collection.add(
                    ids=[doc_id],
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[metadata]
                )
            return
        except Exception as e:
            logger.error("ChromaDB add error, falling back to LocalVectorStore: %s", str(e))
            _vector_store_client = LocalVectorStore(persist_dir=settings.CHROMA_DB_DIR)
            _use_chroma = False
            
    # Local store fallback
    _vector_store_client.add(collection_name, doc_id, text, embedding, metadata)

def query_documents(
    collection_name: str,
    query_text: str,
    n_results: int = 5,
    where: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Query the vector store for similar documents with optional metadata filter."""
    if not query_text or not str(query_text).strip():
        return []
        
    embedding = get_embedding(query_text)
    
    if _use_chroma:
        try:
            collection = _vector_store_client.get_or_create_collection(name=collection_name)
            query_kwargs = {
                "query_embeddings": [embedding],
                "n_results": n_results
            }
            if where:
                query_kwargs["where"] = where
                
            results = collection.query(**query_kwargs)
            output = []
            if results and results.get("ids") and len(results["ids"][0]) > 0:
                for idx in range(len(results["ids"][0])):
                    dist = results["distances"][0][idx] if results.get("distances") else 0.0
                    # For normalized embeddings with squared Euclidean distance:
                    # similarity = 1 - (dist / 2.0)
                    sim = max(0.0, min(1.0, 1.0 - (float(dist) / 2.0)))
                    output.append({
                        "id": results["ids"][0][idx],
                        "text": results["documents"][0][idx],
                        "metadata": results["metadatas"][0][idx] if results.get("metadatas") else {},
                        "similarity": round(sim, 4)
                    })
            return output
        except Exception as e:
            logger.error("ChromaDB query error, falling back to LocalVectorStore: %s", str(e))
            
    # Local store fallback
    return _vector_store_client.query(collection_name, embedding, n_results, where=where)

def delete_document(collection_name: str, doc_id: str):
    """Delete a document from the vector store."""
    if _use_chroma:
        try:
            collection = _vector_store_client.get_or_create_collection(name=collection_name)
            collection.delete(ids=[doc_id])
            return
        except Exception as e:
            logger.error("ChromaDB delete error: %s", str(e))
            
    # Local store fallback
    _vector_store_client.delete(collection_name, doc_id)

def get_vector_store_status() -> Dict[str, Any]:
    """Retrieve operational diagnostics of the vector storage and embedding subsystem."""
    model = get_embedding_model()
    is_real_model = model is not None
    return {
        "backend": "chromadb" if _use_chroma else "local_vector_store",
        "embedding_provider": "sentence_transformers" if is_real_model else "deterministic_offline",
        "model_name": settings.EMBEDDING_MODEL_NAME if is_real_model else "offline_ngram_hashing",
        "dimension": 384,
        "persist_dir": settings.CHROMA_DB_DIR
    }

