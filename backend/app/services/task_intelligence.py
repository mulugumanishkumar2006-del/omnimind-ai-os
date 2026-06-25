import json
import logging
from typing import List, Dict, Any, Optional
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

async def generate_goal_breakdown(goal_id: str, db: Session) -> List[TaskDB]:
    """Use the model router to break down a high-level goal into actionable subtasks."""
    goal = db.query(TaskDB).filter(TaskDB.id == goal_id).first()
    if not goal:
        return []
        
    prompt = f"""Break down the following goal into a list of 3-5 subtasks, projects, or learning plan steps.
For each item, specify a title, description, task_type ('task', 'project', or 'learning_plan'), and estimated_hours.
Format your response STRICTLY as a JSON array of objects.

Goal: "{goal.title}"
Description: "{goal.description or ''}"

Example Response:
[
  {{"title": "Subtask 1", "description": "Details here", "type": "task", "estimated_hours": 4.5}}
]"""

    res = await execute_llm_call("GoalBreakdownAgent", prompt, db, complexity_override="medium")
    output = res["output"].strip()
    
    # Strip markdown block ticks if present
    if output.startswith("```json"):
        output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
    output = output.strip()
    
    subtasks = []
    try:
        subtasks_data = json.loads(output)
        if isinstance(subtasks_data, list):
            for item in subtasks_data:
                title = item.get("title", "Untitled Subtask")
                desc = item.get("description", "")
                t_type = item.get("type", "task")
                est_hrs = float(item.get("estimated_hours", 2.0))
                
                # Auto-assign deadline (staggered in increments of 7 days)
                days_offset = (len(subtasks) + 1) * 7
                deadline = datetime.now() + timedelta(days=days_offset)
                
                subtask = create_task_entry(
                    title=title,
                    task_type=t_type,
                    db=db,
                    description=desc,
                    parent_id=goal.id,
                    estimated_hours=est_hrs,
                    deadline=deadline
                )
                subtasks.append(subtask)
        else:
            logger.error("JSON is not a list structure: %s", output)
    except Exception as e:
        logger.error("Failed to parse goal breakdown JSON: %s. Output: %s", str(e), output)
        
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
