import pytest
import os
import shutil
import tempfile
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.models.database_models import MemoryDB, TaskDB, MeetingDB, GraphNodeDB
from backend.app.services.memory_engine import (
    add_memory,
    get_memory_by_id,
    get_memory_timeline,
    search_memories,
    edit_memory,
    delete_memory_by_id,
    ALLOWED_MEMORY_TYPES
)
from backend.app.services.search_service import run_hybrid_search, compute_entity_lexical_score
from backend.app.core.vector_store import (
    LocalVectorStore,
    _deterministic_offline_embedding,
    get_embedding,
    add_document,
    query_documents,
    get_vector_store_status
)

@pytest.fixture
def isolated_db():
    """Create an isolated in-memory SQLite database session with StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(isolated_db):
    """FastAPI TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield isolated_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# =====================================================================
# 1. MEMORY TYPES LIFECYCLE & VALIDATION
# =====================================================================

@pytest.mark.asyncio
async def test_all_four_memory_types_supported(isolated_db):
    """Verify that short_term, long_term, session, and semantic memories can all be created and queried."""
    types_to_test = ["short_term", "long_term", "session", "semantic"]
    created_ids = {}

    for m_type in types_to_test:
        mem = await add_memory(
            content=f"Important context for memory category {m_type}",
            memory_type=m_type,
            db=isolated_db,
            metadata={"category": m_type}
        )
        assert mem.id is not None
        assert mem.type == m_type
        assert mem.created_at is not None
        assert mem.importance_score > 0.0
        created_ids[m_type] = mem.id

    # Query timeline filtered by each specific type
    for m_type in types_to_test:
        timeline = get_memory_timeline(isolated_db, memory_type=m_type)
        assert len(timeline) >= 1
        assert all(m.type == m_type for m in timeline)
        assert any(m.id == created_ids[m_type] for m in timeline)

def test_invalid_memory_type_rejected(client):
    """Verify that unknown memory types are rejected with HTTP 400."""
    res = client.post("/api/v1/memories/", json={
        "content": "This should fail because of unknown type",
        "type": "ephemeral_cache"
    })
    assert res.status_code == 400
    assert "Invalid memory type" in res.json()["detail"]

def test_empty_memory_content_rejected(client):
    """Verify that empty or whitespace-only memory content is rejected."""
    res = client.post("/api/v1/memories/", json={
        "content": "   \n\t   ",
        "type": "short_term"
    })
    assert res.status_code == 400
    assert "cannot be empty" in res.json()["detail"]


# =====================================================================
# 2. SESSION ISOLATION & FILTERING
# =====================================================================

@pytest.mark.asyncio
async def test_session_memory_isolation(isolated_db):
    """Verify memories tagged with session_id can be isolated in timeline and search."""
    session_alpha = "sess_alpha_101"
    session_beta = "sess_beta_202"

    # Create memory for Session Alpha
    mem_a = await add_memory(
        content="Alpha confidential: Project Titan launch date is November 15.",
        memory_type="session",
        db=isolated_db,
        metadata={"session_id": session_alpha}
    )

    # Create memory for Session Beta
    mem_b = await add_memory(
        content="Beta notes: Project Titan budget approved for $500,000.",
        memory_type="session",
        db=isolated_db,
        metadata={"session_id": session_beta}
    )

    # 1. Timeline filtering by session_id
    timeline_alpha = get_memory_timeline(isolated_db, session_id=session_alpha)
    assert any(m.id == mem_a.id for m in timeline_alpha)
    assert not any(m.id == mem_b.id for m in timeline_alpha)

    timeline_beta = get_memory_timeline(isolated_db, session_id=session_beta)
    assert any(m.id == mem_b.id for m in timeline_beta)
    assert not any(m.id == mem_a.id for m in timeline_beta)

    # 2. Search filtering by session_id
    search_alpha = search_memories("Titan", isolated_db, session_id=session_alpha)
    assert any(m["id"] == mem_a.id for m in search_alpha)
    assert not any(m["id"] == mem_b.id for m in search_alpha)

    search_beta = search_memories("Titan", isolated_db, session_id=session_beta)
    assert any(m["id"] == mem_b.id for m in search_beta)
    assert not any(m["id"] == mem_a.id for m in search_beta)


# =====================================================================
# 3. MEMORY API CRUD ENDPOINTS
# =====================================================================

def test_memory_api_full_crud(client, isolated_db):
    """Verify POST, GET /{id}, GET timeline, PUT, and DELETE endpoints."""
    # 1. Create
    create_res = client.post("/api/v1/memories/", json={
        "content": "Architecture decision: We use ChromaDB and SQLite.",
        "type": "semantic",
        "metadata_json": {"source": "architecture_review"}
    })
    assert create_res.status_code == 200
    data = create_res.json()
    mem_id = data["id"]
    assert data["type"] == "semantic"
    assert data["importance_score"] > 0.0

    # 2. Get by ID
    get_res = client.get(f"/api/v1/memories/{mem_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == mem_id
    assert "Architecture decision" in get_res.json()["content"]

    # 3. Update content and type
    put_res = client.put(f"/api/v1/memories/{mem_id}", json={
        "content": "Updated decision: We strictly require ChromaDB with SQLite persistence.",
        "type": "long_term"
    })
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["type"] == "long_term"
    assert "strictly require ChromaDB" in updated["content"]

    # 4. Search updated content
    search_res = client.get("/api/v1/memories/search?query=strictly")
    assert search_res.status_code == 200
    matches = search_res.json()
    assert any(m["id"] == mem_id for m in matches)

    # 5. Delete
    del_res = client.delete(f"/api/v1/memories/{mem_id}")
    assert del_res.status_code == 200

    # 6. Verify 404 after deletion
    get_del = client.get(f"/api/v1/memories/{mem_id}")
    assert get_del.status_code == 404


# =====================================================================
# 4. DETERMINISTIC OFFLINE EMBEDDINGS & PERSISTENCE
# =====================================================================

def test_deterministic_offline_embeddings():
    """Verify that offline embeddings are 100% deterministic and semantically aligned."""
    text1 = "FastAPI microservices architecture with Python and Docker"
    text2 = "FastAPI Docker microservices"
    text_unrelated = "Baking chocolate cookies with butter and sugar"

    vec1 = np.array(_deterministic_offline_embedding(text1))
    vec1_repeat = np.array(_deterministic_offline_embedding(text1))
    vec2 = np.array(_deterministic_offline_embedding(text2))
    vec_unrelated = np.array(_deterministic_offline_embedding(text_unrelated))

    # Determinism across separate invocations
    np.testing.assert_allclose(vec1, vec1_repeat, rtol=1e-5)

    # Related texts have high cosine similarity
    sim_related = float(np.dot(vec1, vec2))
    # Unrelated texts have very low similarity
    sim_unrelated = float(np.dot(vec1, vec_unrelated))

    assert sim_related > 0.40, f"Expected strong similarity, got {sim_related}"
    assert sim_unrelated < 0.20, f"Expected near zero similarity, got {sim_unrelated}"
    assert sim_related > sim_unrelated * 2

def test_empty_string_embedding():
    """Verify empty or whitespace strings return zero vectors safely."""
    empty_vec = get_embedding("   ")
    assert len(empty_vec) == 384
    assert all(v == 0.0 for v in empty_vec)

def test_local_vector_store_persistence_across_restarts():
    """Verify LocalVectorStore persists to JSON and reloads across store re-instantiations."""
    temp_dir = tempfile.mkdtemp()
    try:
        # First instance: add documents
        store1 = LocalVectorStore(persist_dir=temp_dir)
        emb1 = _deterministic_offline_embedding("Machine learning pipeline optimization")
        emb2 = _deterministic_offline_embedding("Database schema migrations with Alembic")
        
        store1.add("test_col", "doc_1", "ML pipeline optimization", emb1, {"topic": "ml"})
        store1.add("test_col", "doc_2", "Alembic migrations", emb2, {"topic": "db"})
        assert store1.count("test_col") == 2

        # Second instance simulating application restart: reload from same persist_dir
        store2 = LocalVectorStore(persist_dir=temp_dir)
        assert store2.count("test_col") == 2

        # Query restarted store
        query_emb = _deterministic_offline_embedding("pipeline optimization")
        hits = store2.query("test_col", query_emb, n_results=1)
        assert len(hits) == 1
        assert hits[0]["id"] == "doc_1"
        assert hits[0]["similarity"] > 0.40

        # Query with where filter
        db_hits = store2.query("test_col", query_emb, n_results=5, where={"topic": "db"})
        assert len(db_hits) == 1
        assert db_hits[0]["id"] == "doc_2"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# 5. MEANINGFUL HYBRID SEARCH & DYNAMIC SCORING
# =====================================================================

def test_hybrid_search_continuous_scoring_and_citations(isolated_db):
    """Verify hybrid search returns continuous, differentiated scores, not static 0.8."""
    # Seed task with exact title
    task_exact = TaskDB(
        title="Deploy Redis Cluster",
        description="Configure clustering on 3 nodes",
        type="task",
        status="pending"
    )
    # Seed task with partial match in description
    task_partial = TaskDB(
        title="Infrastructure Setup",
        description="Installing various tools including Redis caching",
        type="task",
        status="pending"
    )
    isolated_db.add_all([task_exact, task_partial])
    isolated_db.commit()

    # Search for "Deploy Redis Cluster"
    res = run_hybrid_search("Deploy Redis Cluster", isolated_db, limit=5, collection_filter="task")
    assert len(res["results"]) >= 2
    assert len(res["citations"]) >= 2

    score_exact = res["results"][0]["score"]
    score_partial = res["results"][1]["score"]

    # Exact match should rank higher than partial match
    assert score_exact > score_partial
    assert score_exact >= 0.90, f"Expected >= 0.90 for exact match, got {score_exact}"

    # Citations match results
    assert res["citations"][0]["confidence"] == score_exact
    assert "Deploy Redis Cluster" in res["citations"][0]["title"]

def test_hybrid_search_collection_filter_validation(client):
    """Verify invalid collection filter returns HTTP 400."""
    res = client.post("/api/v1/search/", json={
        "query": "Database",
        "collection_filter": "unsupported_collection"
    })
    assert res.status_code == 400
    assert "Invalid collection_filter" in res.json()["detail"]

def test_vector_store_status_diagnostics():
    """Verify get_vector_store_status returns transparent diagnostic metadata."""
    status = get_vector_store_status()
    assert "backend" in status
    assert status["backend"] in ["chromadb", "local_vector_store"]
    assert "embedding_provider" in status
    assert status["embedding_provider"] in ["sentence_transformers", "deterministic_offline"]
    assert status["dimension"] == 384
