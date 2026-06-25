import os
import json
import logging
import numpy as np
from typing import List, Dict, Any, Optional
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Attempt to load SentenceTransformer for local embeddings
try:
    from sentence_transformers import SentenceTransformer
    # Cache the model load
    _model = None
    def get_embedding_model():
        global _model
        if _model is None:
            logger.info("Initializing SentenceTransformer model: %s", settings.EMBEDDING_MODEL_NAME)
            _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return _model
except Exception as e:
    logger.warning("SentenceTransformer not loaded, falling back to mock embeddings: %s", str(e))
    def get_embedding_model():
        return None

def get_embedding(text: str) -> List[float]:
    """Generate a vector embedding for the given text."""
    model = get_embedding_model()
    if model is not None:
        try:
            embedding = model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error("Error generating embedding: %s", str(e))
    
    # Mock embedding fallback (deterministic 384-dimensional vector based on text hash)
    # 384 is the dimension of all-MiniLM-L6-v2
    h = hash(text)
    np.random.seed(abs(h) % (2**32))
    mock_vector = np.random.randn(384)
    norm = np.linalg.norm(mock_vector)
    if norm > 0:
        mock_vector = mock_vector / norm
    return mock_vector.tolist()


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
        
        # Remove existing if present
        self.data[collection_name] = [d for d in self.data[collection_name] if d["id"] != id]
        
        self.data[collection_name].append({
            "id": id,
            "text": text,
            "embedding": embedding,
            "metadata": metadata
        })
        self.save()

    def query(self, collection_name: str, query_embedding: List[float], n_results: int = 5) -> List[Dict[str, Any]]:
        if collection_name not in self.data or not self.data[collection_name]:
            return []
        
        docs = self.data[collection_name]
        q_vec = np.array(query_embedding)
        
        results = []
        for d in docs:
            d_vec = np.array(d["embedding"])
            # Cosine similarity
            denom = (np.linalg.norm(q_vec) * np.linalg.norm(d_vec))
            similarity = float(np.dot(q_vec, d_vec) / denom) if denom > 0 else 0.0
            
            results.append({
                "id": d["id"],
                "text": d["text"],
                "metadata": d["metadata"],
                "similarity": similarity
            })
        
        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:n_results]

    def delete(self, collection_name: str, id: str):
        if collection_name in self.data:
            self.data[collection_name] = [d for d in self.data[collection_name] if d["id"] != id]
            self.save()


# Initialize the Vector Store client
_vector_store_client = None
_use_chroma = False

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    # Try initializing persistent Chroma client
    client = chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)
    _vector_store_client = client
    _use_chroma = True
    logger.info("ChromaDB persistent client successfully initialized.")
except Exception as e:
    logger.warning("ChromaDB initialization failed, using local numpy vector store: %s", str(e))
    _vector_store_client = LocalVectorStore(persist_dir=settings.CHROMA_DB_DIR)
    _use_chroma = False

def add_document(collection_name: str, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
    """Add a document and its embedding to the vector store."""
    global _vector_store_client, _use_chroma
    metadata = metadata or {}
    embedding = get_embedding(text)
    
    if _use_chroma:
        try:
            collection = _vector_store_client.get_or_create_collection(name=collection_name)
            collection.add(
                ids=[doc_id],
                documents=[text],
                embeddings=[embedding],
                metadatas=[metadata]
            )
            return
        except Exception as e:
            logger.error("ChromaDB add error, falling back to LocalVectorStore: %s", str(e))
            # Fallback to local store instance in-case chroma fails dynamically
            _vector_store_client = LocalVectorStore(persist_dir=settings.CHROMA_DB_DIR)
            _use_chroma = False
            
    # Local store fallback
    _vector_store_client.add(collection_name, doc_id, text, embedding, metadata)

def query_documents(collection_name: str, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Query the vector store for similar documents."""
    embedding = get_embedding(query_text)
    
    if _use_chroma:
        try:
            collection = _vector_store_client.get_or_create_collection(name=collection_name)
            results = collection.query(
                query_embeddings=[embedding],
                n_results=n_results
            )
            # Reformat to standardized output
            output = []
            if results and results.get("ids") and len(results["ids"][0]) > 0:
                for idx in range(len(results["ids"][0])):
                    output.append({
                        "id": results["ids"][0][idx],
                        "text": results["documents"][0][idx],
                        "metadata": results["metadatas"][0][idx] if results.get("metadatas") else {},
                        "similarity": 1.0 - (results["distances"][0][idx] if results.get("distances") else 0.0)
                    })
            return output
        except Exception as e:
            logger.error("ChromaDB query error, falling back to LocalVectorStore: %s", str(e))
            
    # Local store fallback
    return _vector_store_client.query(collection_name, embedding, n_results)

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
