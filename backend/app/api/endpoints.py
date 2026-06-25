from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi.responses import HTMLResponse

from backend.app.core.database import get_db
from backend.app.models import schemas
from backend.app.models.database_models import (
    MemoryDB, TaskDB, GraphNodeDB, GraphEdgeDB, PromptDB,
    MeetingDB, SelfImprovementDB, ModelRouteLogDB, SecurityThreatLogDB,
    AnalyticsMetricDB, SkillProgressDB, AgentSessionDB
)
from backend.app.services import (
    memory_engine, task_intelligence, knowledge_graph,
    agent_framework, meeting_assistant, learning_tracker,
    self_improvement, model_router, search_service
)
from backend.app.core import security_scanner

# Define individual sub-routers
memory_router = APIRouter(prefix="/memories", tags=["Memory Engine"])
task_router = APIRouter(prefix="/tasks", tags=["Task Intelligence"])
kg_router = APIRouter(prefix="/knowledge", tags=["Knowledge Graph"])
agent_router = APIRouter(prefix="/agents", tags=["Multi-Agent System"])
prompt_router = APIRouter(prefix="/prompts", tags=["Prompt Studio"])
meeting_router = APIRouter(prefix="/meetings", tags=["Meeting Assistant"])
learning_router = APIRouter(prefix="/learning", tags=["Learning Tracker"])
router_router = APIRouter(prefix="/router", tags=["Model Router"])
security_router = APIRouter(prefix="/security", tags=["Security Center"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics Center"])
improvement_router = APIRouter(prefix="/improvement", tags=["Self-Improvement Engine"])
search_router = APIRouter(prefix="/search", tags=["AI Search"])

# ==================== Memory Routes ====================
@memory_router.post("/", response_model=schemas.MemoryResponse)
async def create_memory(memory: schemas.MemoryCreate, db: Session = Depends(get_db)):
    return await memory_engine.add_memory(
        content=memory.content,
        memory_type=memory.type,
        db=db,
        metadata=memory.metadata_json
    )

@memory_router.get("/", response_model=List[schemas.MemoryResponse])
def get_timeline(
    type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    return memory_engine.get_memory_timeline(db, memory_type=type, limit=limit)

@memory_router.get("/search")
def search(query: str, limit: int = 5, db: Session = Depends(get_db)):
    return memory_engine.search_memories(query, db, limit=limit)

@memory_router.put("/{id}", response_model=schemas.MemoryResponse)
def update_memory(id: str, content: str, db: Session = Depends(get_db)):
    mem = memory_engine.edit_memory(id, content, db)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem

@memory_router.delete("/{id}")
def delete_memory(id: str, db: Session = Depends(get_db)):
    success = memory_engine.delete_memory_by_id(id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "success", "detail": "Memory deleted"}


# ==================== Task Routes ====================
@task_router.post("/", response_model=schemas.TaskResponse)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    return task_intelligence.create_task_entry(
        title=task.title,
        task_type=task.type,
        db=db,
        description=task.description,
        parent_id=task.parent_id,
        estimated_hours=task.estimated_hours,
        deadline=task.deadline,
        progress=task.progress,
        status=task.status
    )

@task_router.get("/", response_model=List[schemas.TaskResponse])
def list_tasks(db: Session = Depends(get_db)):
    # Build hierarchical tree
    all_tasks = db.query(TaskDB).all()
    task_map = {t.id: schemas.TaskResponse.from_orm(t) for t in all_tasks}
    roots = []
    
    for t_id, t_resp in task_map.items():
        if t_resp.parent_id and t_resp.parent_id in task_map:
            # Append to parent subtask array
            task_map[t_resp.parent_id].subtasks.append(t_resp)
        else:
            roots.append(t_resp)
            
    return roots

@task_router.get("/suggest", response_model=List[schemas.TaskResponse])
def suggest_actions(limit: int = 5, db: Session = Depends(get_db)):
    return task_intelligence.suggest_next_actions(db, limit=limit)

@task_router.post("/{id}/breakdown", response_model=List[schemas.TaskResponse])
async def breakdown_goal(id: str, db: Session = Depends(get_db)):
    return await task_intelligence.generate_goal_breakdown(id, db)

@task_router.put("/{id}/progress", response_model=schemas.TaskResponse)
def update_progress(id: str, progress: float, status: str, db: Session = Depends(get_db)):
    task = task_intelligence.update_task_progress(id, progress, status, db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ==================== Knowledge Graph Routes ====================
@kg_router.post("/extract", response_model=Dict[str, Any])
async def extract_kg(req: schemas.KGExtractionRequest, db: Session = Depends(get_db)):
    return await knowledge_graph.extract_knowledge(req.content, db)

@kg_router.get("/graph", response_model=schemas.GraphResponse)
def get_graph(db: Session = Depends(get_db)):
    return knowledge_graph.get_graph_data(db)

@kg_router.get("/view", response_class=HTMLResponse)
def view_network(db: Session = Depends(get_db)):
    return knowledge_graph.generate_visjs_html(db)


# ==================== Multi-Agent System Routes ====================
@agent_router.post("/run", response_model=schemas.AgentSessionResponse)
async def run_pipeline(req: schemas.AgentRunRequest, db: Session = Depends(get_db)):
    framework = agent_framework.AgentFramework(db)
    return await framework.run_collaboration_pipeline(req.goal)

@agent_router.get("/sessions", response_model=List[schemas.AgentSessionResponse])
def get_sessions(limit: int = 10, db: Session = Depends(get_db)):
    return agent_framework.get_agent_sessions(db, limit=limit)


# ==================== Prompt Studio Routes ====================
@prompt_router.post("/", response_model=schemas.PromptResponse)
def create_prompt(prompt: schemas.PromptCreate, db: Session = Depends(get_db)):
    # Find latest version
    latest = db.query(PromptDB).filter(PromptDB.name == prompt.name).order_by(PromptDB.version.desc()).first()
    ver = (latest.version + 1) if latest else 1
    
    db_prompt = PromptDB(
        name=prompt.name,
        template=prompt.template,
        version=ver,
        metrics={"avg_cost": 0.0, "avg_latency": 0.0, "avg_rating": 5.0}
    )
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)
    return db_prompt

@prompt_router.get("/", response_model=List[schemas.PromptResponse])
def list_prompts(db: Session = Depends(get_db)):
    return db.query(PromptDB).order_by(PromptDB.name.asc(), PromptDB.version.desc()).all()

@prompt_router.post("/compare")
async def compare_prompts(req: schemas.PromptCompareRequest, db: Session = Depends(get_db)):
    prompt_a = db.query(PromptDB).filter(PromptDB.id == req.prompt_a_id).first()
    prompt_b = db.query(PromptDB).filter(PromptDB.id == req.prompt_b_id).first()
    
    if not prompt_a or not prompt_b:
        raise HTTPException(status_code=404, detail="One or both prompts not found")
        
    # Execute A
    run_a = await model_router.execute_llm_call(prompt_a.name, f"{prompt_a.template}\nInput:\n{req.test_input}", db)
    # Execute B
    run_b = await model_router.execute_llm_call(prompt_b.name, f"{prompt_b.template}\nInput:\n{req.test_input}", db)
    
    return {
        "prompt_a": {"id": prompt_a.id, "version": prompt_a.version, "output": run_a["output"], "cost": run_a["cost"], "latency": run_a["latency"]},
        "prompt_b": {"id": prompt_b.id, "version": prompt_b.version, "output": run_b["output"], "cost": run_b["cost"], "latency": run_b["latency"]}
    }


# ==================== Meeting Assistant Routes ====================
@meeting_router.post("/process", response_model=schemas.MeetingResponse)
async def process_transcript(req: schemas.MeetingCreate, db: Session = Depends(get_db)):
    return await meeting_assistant.process_meeting_transcript(
        title=req.title,
        transcript=req.transcript,
        db=db
    )

@meeting_router.get("/", response_model=List[schemas.MeetingResponse])
def list_meetings(limit: int = 10, db: Session = Depends(get_db)):
    return meeting_assistant.get_meetings(db, limit=limit)


# ==================== Learning Tracker Routes ====================
@learning_router.get("/skills", response_model=List[schemas.SkillProgressResponse])
def get_skills(db: Session = Depends(get_db)):
    return learning_tracker.get_skills(db)

@learning_router.post("/skills", response_model=schemas.SkillProgressResponse)
def upsert_skill(skill: schemas.SkillProgressCreate, db: Session = Depends(get_db)):
    return learning_tracker.add_or_update_skill(
        skill_name=skill.skill_name,
        level=skill.level,
        progress=skill.progress,
        status=skill.status,
        db=db,
        targets=skill.targets
    )

@learning_router.get("/career", response_model=schemas.CareerRecommendationResponse)
async def get_career_paths(db: Session = Depends(get_db)):
    return await learning_tracker.get_career_recommendations(db)

@learning_router.post("/roadmap")
async def build_roadmap(skill_name: str = Query(...), db: Session = Depends(get_db)):
    result = await learning_tracker.generate_learning_roadmap(skill_name, db)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to generate learning roadmap")
    return result


# ==================== Model Router Routes ====================
@router_router.post("/route")
async def dynamic_route(req: schemas.ModelRouteRequest, db: Session = Depends(get_db)):
    return await model_router.execute_llm_call(
        prompt_name=req.prompt_name,
        prompt_text=req.prompt_text,
        db=db,
        complexity_override=req.complexity_override
    )

@router_router.get("/logs", response_model=List[schemas.ModelRouteLogResponse])
def get_routing_logs(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(ModelRouteLogDB).order_by(ModelRouteLogDB.created_at.desc()).limit(limit).all()


# ==================== Security Center Routes ====================
@security_router.post("/scan")
def scan_input(req: schemas.SecurityScanRequest, db: Session = Depends(get_db)):
    return security_scanner.scan_text(req.input_text, db)

@security_router.get("/logs", response_model=List[schemas.SecurityThreatLogResponse])
def get_threat_logs(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(SecurityThreatLogDB).order_by(SecurityThreatLogDB.created_at.desc()).limit(limit).all()


# ==================== Self-Improvement Routes ====================
@improvement_router.post("/logs", response_model=schemas.SelfImprovementResponse)
def add_failure_record(req: schemas.SelfImprovementBase, db: Session = Depends(get_db)):
    return self_improvement.log_failure_case(
        prompt_name=req.prompt_name,
        input_text=req.input_text,
        output_text=req.output_text,
        failure_type=req.failure_type,
        evaluation_score=req.evaluation_score,
        db=db,
        correction_details=req.correction_details
    )

@improvement_router.get("/logs", response_model=List[schemas.SelfImprovementResponse])
def list_improvement_logs(limit: int = 20, db: Session = Depends(get_db)):
    return self_improvement.get_self_improvement_reports(db, limit=limit)

@improvement_router.post("/logs/{id}/optimize", response_model=schemas.PromptResponse)
async def optimize_prompt_from_log(id: str, db: Session = Depends(get_db)):
    opt_prompt = await self_improvement.optimize_prompt_from_failure(id, db)
    if not opt_prompt:
        raise HTTPException(status_code=400, detail="Failed to optimize prompt. Check log ID.")
    return opt_prompt


# ==================== AI Operations / Analytics Routes ====================
@analytics_router.get("/dashboard")
def get_analytics_summary(db: Session = Depends(get_db)):
    logs = db.query(ModelRouteLogDB).all()
    threats = db.query(SecurityThreatLogDB).all()
    memories = db.query(MemoryDB).all()
    tasks = db.query(TaskDB).all()
    
    total_calls = len(logs)
    avg_latency = sum(l.latency for l in logs) / total_calls if total_calls > 0 else 0.0
    p95_latency = sorted([l.latency for l in logs])[int(total_calls * 0.95)] if total_calls > 10 else avg_latency
    total_cost = sum(l.cost for l in logs)
    success_rate = (sum(1 for l in logs if l.reliability_success) / total_calls * 100) if total_calls > 0 else 100.0
    
    # Model distributions
    models = {}
    for l in logs:
        models[l.model_name] = models.get(l.model_name, 0) + 1
        
    return {
        "active_users": 1,
        "sessions": len(db.query(AgentSessionDB).all()),
        "total_calls": total_calls,
        "avg_latency": round(avg_latency, 2),
        "p95_latency": round(p95_latency, 2),
        "total_cost": round(total_cost, 4),
        "success_rate": round(success_rate, 1),
        "model_distribution": models,
        "total_threats": len(threats),
        "memory_growth": len(memories),
        "tasks_active": sum(1 for t in tasks if t.status in ["pending", "in_progress"])
    }


# ==================== AI Search Routes ====================
@search_router.post("/", response_model=schemas.HybridSearchResponse)
def hybrid_search(req: schemas.HybridSearchRequest, db: Session = Depends(get_db)):
    return search_service.run_hybrid_search(
        query=req.query,
        db=db,
        limit=req.limit,
        collection_filter=req.collection_filter
    )
