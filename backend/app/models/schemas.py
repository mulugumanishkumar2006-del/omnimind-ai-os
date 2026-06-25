from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

# ==================== Memory ====================
class MemoryBase(BaseModel):
    content: str
    type: str  # short_term, long_term, session, semantic
    importance_score: float = 0.0
    metadata_json: Dict[str, Any] = Field(default_factory=dict)

class MemoryCreate(MemoryBase):
    pass

class MemoryResponse(MemoryBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Tasks / Goals ====================
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    type: str  # goal, project, task, learning_plan
    status: str = "pending"  # pending, in_progress, completed, blocked
    parent_id: Optional[str] = None
    estimated_hours: float = 0.0
    deadline: Optional[datetime] = None
    progress: float = 0.0

class TaskCreate(TaskBase):
    pass

class TaskResponse(TaskBase):
    id: str
    created_at: datetime
    subtasks: List['TaskResponse'] = []

    class Config:
        from_attributes = True

class GoalBreakdownRequest(BaseModel):
    goal_id: str
    depth: int = 2

# ==================== Knowledge Graph ====================
class NodeBase(BaseModel):
    id: str
    label: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class NodeResponse(NodeBase):
    created_at: datetime

    class Config:
        from_attributes = True

class EdgeBase(BaseModel):
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0

class EdgeResponse(EdgeBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

class GraphResponse(BaseModel):
    nodes: List[NodeResponse]
    edges: List[EdgeResponse]

class KGExtractionRequest(BaseModel):
    content: str

# ==================== Prompts ====================
class PromptBase(BaseModel):
    name: str
    template: str
    version: int = 1
    metrics: Dict[str, Any] = Field(default_factory=dict)
    is_active_a: bool = False
    is_active_b: bool = False

class PromptCreate(BaseModel):
    name: str
    template: str

class PromptResponse(PromptBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

class PromptCompareRequest(BaseModel):
    prompt_a_id: str
    prompt_b_id: str
    test_input: str

# ==================== Meetings ====================
class MeetingBase(BaseModel):
    title: str
    transcript: Optional[str] = None
    summary: Optional[str] = None
    action_items: List[Dict[str, Any]] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)

class MeetingCreate(BaseModel):
    title: str
    transcript: str

class MeetingResponse(MeetingBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Self-Improvement ====================
class SelfImprovementBase(BaseModel):
    prompt_name: str
    input_text: str
    output_text: str
    failure_type: str
    evaluation_score: float
    correction_details: Optional[str] = None
    optimized_prompt_id: Optional[str] = None

class SelfImprovementResponse(SelfImprovementBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Model Routing ====================
class ModelRouteRequest(BaseModel):
    prompt_name: str
    prompt_text: str
    complexity_override: Optional[str] = None  # low, medium, high

class ModelRouteLogResponse(BaseModel):
    id: str
    prompt_name: str
    provider: str
    model_name: str
    complexity: str
    cost: float
    latency: float
    reliability_success: bool
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Security ====================
class SecurityScanRequest(BaseModel):
    input_text: str

class SecurityThreatLogResponse(BaseModel):
    id: str
    scan_type: str
    input_text: str
    threats_detected: List[str]
    safety_score: float
    risk_level: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Analytics ====================
class AnalyticsMetricResponse(BaseModel):
    id: str
    metric_name: str
    value: float
    metadata_json: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Learning ====================
class SkillProgressBase(BaseModel):
    skill_name: str
    level: str = "Beginner"
    progress: float = 0.0
    status: str = "not_started"
    targets: List[str] = Field(default_factory=list)

class SkillProgressCreate(SkillProgressBase):
    pass

class SkillProgressResponse(SkillProgressBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

class CareerRecommendationResponse(BaseModel):
    recommended_path: str
    rationale: str
    required_skills: List[str]
    timeline_months: int

# ==================== Agent Sessions ====================
class AgentRunRequest(BaseModel):
    goal: str

class AgentStep(BaseModel):
    agent_name: str
    action: str
    message: str
    cost: float = 0.0
    latency: float = 0.0
    timestamp: str

class AgentSessionResponse(BaseModel):
    id: str
    goal: str
    status: str
    steps: List[AgentStep]
    communication_graph: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Search ====================
class HybridSearchRequest(BaseModel):
    query: str
    limit: int = 5
    collection_filter: Optional[str] = None  # memory, task, meeting, graph

class Citation(BaseModel):
    source_type: str
    source_id: str
    title: str
    text_snippet: str
    confidence: float

class HybridSearchResponse(BaseModel):
    query: str
    results: List[Dict[str, Any]]
    citations: List[Citation]
