import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from backend.app.core.database import Base
from backend.app.models.database_models import (
    MemoryDB, TaskDB, GraphNodeDB, GraphEdgeDB, PromptDB,
    MeetingDB, SelfImprovementDB, ModelRouteLogDB, SecurityThreatLogDB,
    AnalyticsMetricDB, SkillProgressDB, AgentSessionDB
)

def test_database_table_initialization_isolated():
    """Verify all database tables initialize cleanly on an isolated test database."""
    # Use an in-memory SQLite engine to guarantee isolation from the user's local database
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    
    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    
    inspector = inspect(test_engine)
    table_names = set(inspector.get_table_names())
    
    expected_tables = {
        "memories",
        "tasks",
        "graph_nodes",
        "graph_edges",
        "prompts",
        "meetings",
        "self_improvement_logs",
        "model_route_logs",
        "security_threat_logs",
        "analytics_metrics",
        "skill_progress",
        "agent_sessions"
    }
    
    for table in expected_tables:
        assert table in table_names, f"Table '{table}' was not created in database."

def test_isolated_db_crud_operations():
    """Verify CRUD operations work as expected on an isolated database session."""
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    db = TestingSession()
    try:
        # Create a test prompt record
        prompt = PromptDB(
            name="TestAgent",
            template="You are a test agent.",
            version=1,
            metrics={"avg_cost": 0.0},
            is_active_a=True,
            is_active_b=False
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        
        # Verify it was persisted
        fetched = db.query(PromptDB).filter(PromptDB.name == "TestAgent").first()
        assert fetched is not None
        assert fetched.name == "TestAgent"
        assert fetched.template == "You are a test agent."
    finally:
        db.close()
