import uuid
from sqlalchemy import Column, String, Float, DateTime, Boolean, ForeignKey, JSON, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from backend.app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class MemoryDB(Base):
    __tablename__ = "memories"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    content = Column(Text, nullable=False)
    type = Column(String(50), nullable=False)  # short_term, long_term, session, semantic
    importance_score = Column(Float, default=0.0)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TaskDB(Base):
    __tablename__ = "tasks"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # goal, project, task, learning_plan
    status = Column(String(50), default="pending")  # pending, in_progress, completed, blocked
    parent_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    estimated_hours = Column(Float, default=0.0)
    deadline = Column(DateTime, nullable=True)
    progress = Column(Float, default=0.0)  # 0.0 to 100.0
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GraphNodeDB(Base):
    __tablename__ = "graph_nodes"
    
    id = Column(String(255), primary_key=True)  # Entity/Topic name or UUID
    label = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # Entity, Topic, Concept
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GraphEdgeDB(Base):
    __tablename__ = "graph_edges"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_id = Column(String(255), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(String(255), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False)
    relation = Column(String(100), nullable=False)  # interacts_with, part_of, belongs_to, etc.
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PromptDB(Base):
    __tablename__ = "prompts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    template = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    metrics = Column(JSON, default=dict)  # {"avg_cost": 0, "avg_latency": 0, "avg_rating": 0}
    is_active_a = Column(Boolean, default=False)
    is_active_b = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MeetingDB(Base):
    __tablename__ = "meetings"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False)
    transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    action_items = Column(JSON, default=list)  # list of tasks generated
    decisions = Column(JSON, default=list)  # list of decisions made
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SelfImprovementDB(Base):
    __tablename__ = "self_improvement_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    prompt_name = Column(String(100), nullable=False)
    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=False)
    failure_type = Column(String(50), nullable=False)  # hallucination, low_confidence, user_correction
    evaluation_score = Column(Float, nullable=False)
    correction_details = Column(Text, nullable=True)
    optimized_prompt_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ModelRouteLogDB(Base):
    __tablename__ = "model_route_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    prompt_name = Column(String(100), nullable=False)
    provider = Column(String(50), nullable=False)  # OpenAI, Gemini, Claude, DeepSeek, Local
    model_name = Column(String(100), nullable=False)
    complexity = Column(String(20), nullable=False)  # low, medium, high
    cost = Column(Float, default=0.0)
    latency = Column(Float, default=0.0)  # seconds
    reliability_success = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SecurityThreatLogDB(Base):
    __tablename__ = "security_threat_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    scan_type = Column(String(50), nullable=False)  # injection, jailbreak, sensitive_data
    input_text = Column(Text, nullable=False)
    threats_detected = Column(JSON, default=list)
    safety_score = Column(Float, default=100.0)  # 0 to 100
    risk_level = Column(String(20), default="none")  # none, low, medium, high
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AnalyticsMetricDB(Base):
    __tablename__ = "analytics_metrics"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    metric_name = Column(String(100), nullable=False)  # active_users, session_count, memory_growth, etc.
    value = Column(Float, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SkillProgressDB(Base):
    __tablename__ = "skill_progress"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    skill_name = Column(String(100), nullable=False)
    level = Column(String(50), default="Beginner")  # Beginner, Intermediate, Advanced, Expert
    progress = Column(Float, default=0.0)  # 0.0 to 100.0
    status = Column(String(50), default="not_started")  # not_started, learning, completed
    targets = Column(JSON, default=list)  # tasks/projects mapped to this skill
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentSessionDB(Base):
    """Tracks running agent workflows and agent communication histories."""
    __tablename__ = "agent_sessions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    goal = Column(Text, nullable=False)
    status = Column(String(50), default="running")  # running, success, failed
    steps = Column(JSON, default=list)  # sequence of agent actions
    communication_graph = Column(JSON, default=dict)  # nodes/edges of agent communication
    created_at = Column(DateTime(timezone=True), server_default=func.now())
