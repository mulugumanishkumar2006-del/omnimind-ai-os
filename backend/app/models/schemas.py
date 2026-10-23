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

class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    type: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None

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

class TaskProgressUpdate(BaseModel):
    progress: float
    status: Optional[str] = "in_progress"

class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[float] = None
    estimated_hours: Optional[float] = None
    deadline: Optional[datetime] = None

class ObjectivePlanRequest(BaseModel):
    objective: str
    target_days: Optional[int] = 7
    category: Optional[str] = "learning_plan"
    auto_execute: Optional[bool] = False

class TaskResponse(TaskBase):
    id: str
    created_at: datetime
    subtasks: List['TaskResponse'] = Field(default_factory=list)

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
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class EdgeBase(BaseModel):
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0

class EdgeResponse(EdgeBase):
    id: str
    source: Optional[str] = None
    target: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class GraphResponse(BaseModel):
    nodes: List[NodeResponse]
    edges: List[EdgeResponse]

class KGExtractionRequest(BaseModel):
    content: str

class KGExtractionResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    is_heuristic: bool = False
    is_simulated: bool = False
    extracted_count: int = 0

class KGNodeDetailResponse(NodeResponse):
    in_edges: List[EdgeResponse] = Field(default_factory=list)
    out_edges: List[EdgeResponse] = Field(default_factory=list)
    degree: int = 0

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
    provider: Optional[str] = None
    model: Optional[str] = None
    allow_fallback: Optional[bool] = None

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

class SecurityFinding(BaseModel):
    category: str
    severity: str  # low, medium, high, critical
    matched_pattern: str
    explanation: str
    recommended_action: str
    snippet: str

class SecurityScanResponse(BaseModel):
    is_safe: bool
    safety_score: float
    risk_level: str
    threats: List[str]
    findings: List[SecurityFinding] = Field(default_factory=list)
    scrubbed_preview: str

class SecurityScrubRequest(BaseModel):
    input_text: str

class SecurityScrubResponse(BaseModel):
    original_text: str
    scrubbed_text: str
    pii_detected: bool

class OutputSanitizeRequest(BaseModel):
    text: str

class OutputSanitizeResponse(BaseModel):
    original_text: str
    sanitized_text: str
    contains_xss_or_unsafe: bool

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
    task_id: Optional[str] = None
    max_steps: Optional[int] = None
    max_retries: Optional[int] = None
    provider_override: Optional[str] = None
    model_override: Optional[str] = None

class AgentStep(BaseModel):
    agent_name: str
    action: str
    message: str
    cost: float = 0.0
    latency: float = 0.0
    timestamp: str
    execution_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_role: Optional[str] = None
    status: Optional[str] = "completed"  # pending, running, completed, failed, retrying
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    is_simulated: Optional[bool] = False
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    retry_count: Optional[int] = 0
    failure_details: Optional[str] = None

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
