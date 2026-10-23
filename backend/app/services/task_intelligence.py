import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.app.models.database_models import TaskDB
from backend.app.services.model_router import execute_llm_call

logger = logging.getLogger(__name__)

def create_task_entry(
    title: str,
    task_type: str,
    db: Session,
    description: Optional[str] = None,
    parent_id: Optional[str] = None,
    estimated_hours: float = 0.0,
    deadline: Optional[datetime] = None,
    progress: float = 0.0,
    status: str = "pending"
) -> TaskDB:
    """Create a task, goal, project, or learning plan."""
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty or whitespace.")
    title = title.strip()
    db_task = TaskDB(
        title=title,
        description=description,
        type=task_type,
        status=status,
        parent_id=parent_id,
        estimated_hours=estimated_hours,
        deadline=deadline,
        progress=progress
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    # Recalculate parent progress if applicable
    if parent_id:
        recalculate_parent_progress(parent_id, db)
        
    return db_task

VALID_TASK_TYPES = {"goal", "project", "task", "learning_plan"}
VALID_TASK_STATUSES = {"pending", "in_progress", "completed", "blocked"}

def validate_plan_structure(subtasks_data: Any) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    """Validate that model-generated or submitted plan items adhere to structural and safety constraints."""
    if not isinstance(subtasks_data, list):
        return False, [], "Plan data must be a JSON array of task objects."
    if len(subtasks_data) == 0:
        return False, [], "Plan must contain at least one task or milestone."
        
    validated = []
    for idx, item in enumerate(subtasks_data):
        if not isinstance(item, dict):
            return False, [], f"Item at index {idx} is not a valid JSON object."
            
        raw_title = str(item.get("title", "")).strip()
        if not raw_title:
            return False, [], f"Item at index {idx} is missing a non-empty 'title'."
        if len(raw_title) > 255:
            raw_title = raw_title[:252] + "..."
            
        # Reject shell injection or dangerous execution keywords in task title
        for dangerous in ["rm -rf", "sh -c", "eval(", "exec(", "<script"]:
            if dangerous in raw_title.lower():
                return False, [], f"Item at index {idx} contains forbidden execution keyword '{dangerous}'."

        desc = str(item.get("description", "")).strip()
        t_type = str(item.get("type", "task")).lower()
        if t_type not in VALID_TASK_TYPES:
            t_type = "task"
            
        try:
            est_hrs = float(item.get("estimated_hours", 2.0))
            est_hrs = max(0.1, min(100.0, est_hrs))
        except (ValueError, TypeError):
            est_hrs = 2.0
            
        validated.append({
            "title": raw_title,
            "description": desc,
            "type": t_type,
            "estimated_hours": round(est_hrs, 1)
        })
        
    return True, validated, None

def deterministic_plan_decomposition(objective: str, target_days: int = 7) -> List[Dict[str, Any]]:
    """Fallback deterministic decomposition ensuring reliable, structured planning without AI dependency."""
    clean_obj = objective.strip()
    return [
        {
            "title": f"Phase 1: Foundations & Environment Setup for '{clean_obj[:40]}'",
            "description": f"Establish baseline requirements, workspace setup, and prerequisite research for {clean_obj}.",
            "type": "task",
            "estimated_hours": 3.0
        },
        {
            "title": "Phase 2: Core Architecture & Milestone Implementation",
            "description": "Construct the primary components and implement foundational logic following specifications.",
            "type": "project",
            "estimated_hours": 6.0
        },
        {
            "title": "Phase 3: Integration, Practical Exercises & Testing",
            "description": "Validate the implementation against initial objectives, resolve defects, and verify execution.",
            "type": "task",
            "estimated_hours": 4.5
        },
        {
            "title": "Phase 4: Synthesis, Final Review & Knowledge Capture",
            "description": "Conduct thorough code/workflow review, synthesize learnings into memory vault, and document results.",
            "type": "learning_plan",
            "estimated_hours": 2.5
        }
    ]

async def generate_goal_breakdown(
    goal_id: str,
    db: Session,
    use_deterministic_fallback: bool = True
) -> Optional[List[TaskDB]]:
    """Use the model router to break down a high-level goal into actionable subtasks with schema validation."""
    goal = db.query(TaskDB).filter(TaskDB.id == goal_id).first()
    if not goal:
        return None
        
    prompt = f"""Break down the following goal into a list of 3-5 subtasks, projects, or learning plan steps.
For each item, specify a title, description, task_type ('task', 'project', or 'learning_plan'), and estimated_hours.
Format your response STRICTLY as a JSON array of objects.

Goal: "{goal.title}"
Description: "{goal.description or ''}"

Example Response:
[
  {{"title": "Subtask 1", "description": "Details here", "type": "task", "estimated_hours": 4.5}}
]"""

    subtasks_data = None
    validation_err = None
    try:
        res = await execute_llm_call("GoalBreakdownAgent", prompt, db, complexity_override="medium")
        if res.get("success", False) and res.get("output"):
            output = res["output"].strip()
            # Strip markdown block ticks if present
            if output.startswith("```json"):
                output = output[7:]
            if output.startswith("```"):
                output = output[3:]
            if output.endswith("```"):
                output = output[:-3]
            output = output.strip()
            
            raw_parsed = json.loads(output)
            is_valid, validated_items, err_msg = validate_plan_structure(raw_parsed)
            if is_valid:
                subtasks_data = validated_items
            else:
                validation_err = err_msg
                logger.warning("Model-generated plan failed validation: %s", err_msg)
        else:
            validation_err = res.get("error", "LLM call failed")
    except Exception as e:
        validation_err = str(e)
        logger.warning("Exception during goal breakdown generation: %s", str(e))
        
    # If model failed or produced invalid structure, utilize deterministic decomposition
    if not subtasks_data:
        if use_deterministic_fallback:
            logger.info("Using deterministic goal decomposition for goal '%s'. Reason: %s", goal.title, validation_err)
            subtasks_data = deterministic_plan_decomposition(goal.title)
        else:
            return []
            
    subtasks = []
    for item in subtasks_data:
        days_offset = (len(subtasks) + 1) * 2
        deadline = datetime.now() + timedelta(days=days_offset)
        subtask = create_task_entry(
            title=item["title"],
            task_type=item.get("type", "task"),
            db=db,
            description=item.get("description", ""),
            parent_id=goal.id,
            estimated_hours=item.get("estimated_hours", 2.0),
            deadline=deadline
        )
        subtasks.append(subtask)
        
    return subtasks

def update_task_progress(task_id: str, progress: float, status: str, db: Session) -> Optional[TaskDB]:
    """Update task progress and recursively trigger parent progress aggregation."""
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not task:
        return None
        
    task.progress = min(100.0, max(0.0, progress))
    task.status = status
    db.commit()
    db.refresh(task)
    
    if task.parent_id:
        recalculate_parent_progress(task.parent_id, db)
        
    return task

def recalculate_parent_progress(parent_id: str, db: Session):
    """Aggregate progress of all subtasks and update parent progress score."""
    parent = db.query(TaskDB).filter(TaskDB.id == parent_id).first()
    if not parent:
        return
        
    children = db.query(TaskDB).filter(TaskDB.parent_id == parent_id).all()
    if not children:
        return
        
    total_progress = sum(child.progress for child in children)
    avg_progress = total_progress / len(children)
    
    parent.progress = round(avg_progress, 1)
    
    # Auto-update status based on progress
    if parent.progress == 100.0:
        parent.status = "completed"
    elif parent.progress > 0.0:
        parent.status = "in_progress"
    else:
        parent.status = "pending"
        
    db.commit()
    
    # Propagate progress further up the hierarchy
    if parent.parent_id:
        recalculate_parent_progress(parent.parent_id, db)

def suggest_next_actions(db: Session, limit: int = 5) -> List[TaskDB]:
    """Retrieve actionable tasks that are pending or in_progress, prioritizing subtasks."""
    # Find all tasks that are active (pending/in_progress)
    return db.query(TaskDB)\
        .filter(TaskDB.status.in_(["pending", "in_progress"]))\
        .order_by(TaskDB.deadline.asc(), TaskDB.estimated_hours.asc())\
        .limit(limit)\
        .all()

def get_task_by_id(task_id: str, db: Session) -> Optional[TaskDB]:
    """Retrieve a single task or goal by its ID."""
    return db.query(TaskDB).filter(TaskDB.id == task_id).first()

async def create_goal_with_plan(
    objective: str,
    db: Session,
    target_days: int = 7,
    category: str = "learning_plan",
    auto_execute: bool = False
) -> Dict[str, Any]:
    """Submit a high-level objective and automatically generate a validated, structured plan."""
    clean_obj = (objective or "").strip()
    if not clean_obj:
        raise ValueError("Objective cannot be empty or whitespace.")

    # 1. Create top-level parent Goal
    deadline = datetime.now() + timedelta(days=target_days)
    parent_goal = create_task_entry(
        title=clean_obj,
        task_type="goal" if category == "goal" else category,
        db=db,
        description=f"High-level objective planned over {target_days} days.",
        deadline=deadline,
        estimated_hours=target_days * 2.0
    )

    # 2. Decompose into structured milestones
    subtasks = await generate_goal_breakdown(parent_goal.id, db, use_deterministic_fallback=True)

    return {
        "goal": parent_goal,
        "subtasks": subtasks or [],
        "total_subtasks": len(subtasks or []),
        "target_days": target_days
    }

def update_task_details(
    task_id: str,
    db: Session,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    estimated_hours: Optional[float] = None,
    deadline: Optional[datetime] = None
) -> Optional[TaskDB]:
    """Update general fields of a task or goal."""
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not task:
        return None

    if title is not None and title.strip():
        task.title = title.strip()
    if description is not None:
        task.description = description.strip()
    if estimated_hours is not None:
        task.estimated_hours = max(0.0, float(estimated_hours))
    if deadline is not None:
        task.deadline = deadline
    if progress is not None:
        task.progress = min(100.0, max(0.0, float(progress)))
    if status is not None and status in VALID_TASK_STATUSES:
        task.status = status

    db.commit()
    db.refresh(task)

    if task.parent_id:
        recalculate_parent_progress(task.parent_id, db)

    return task

def delete_task_entry(task_id: str, db: Session) -> bool:
    """Safely delete a task and cascade removal to child subtasks."""
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not task:
        return False

    # Remove children first
    children = db.query(TaskDB).filter(TaskDB.parent_id == task_id).all()
    for child in children:
        db.delete(child)

    parent_id = task.parent_id
    db.delete(task)
    db.commit()

    if parent_id:
        recalculate_parent_progress(parent_id, db)

    return True
