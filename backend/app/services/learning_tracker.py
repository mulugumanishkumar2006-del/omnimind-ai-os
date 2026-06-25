import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.app.models.database_models import SkillProgressDB
from backend.app.services.model_router import execute_llm_call
from backend.app.services.task_intelligence import create_task_entry

logger = logging.getLogger(__name__)

def add_or_update_skill(
    skill_name: str,
    level: str,
    progress: float,
    status: str,
    db: Session,
    targets: Optional[List[str]] = None
) -> SkillProgressDB:
    """Upsert skill acquisition milestones."""
    targets = targets or []
    skill = db.query(SkillProgressDB).filter(SkillProgressDB.skill_name.ilike(skill_name)).first()
    
    if skill:
        skill.level = level
        skill.progress = progress
        skill.status = status
        skill.targets = targets
    else:
        skill = SkillProgressDB(
            skill_name=skill_name,
            level=level,
            progress=progress,
            status=status,
            targets=targets
        )
        db.add(skill)
        
    db.commit()
    db.refresh(skill)
    return skill

def get_skills(db: Session) -> List[SkillProgressDB]:
    """Retrieve all logged skills."""
    return db.query(SkillProgressDB).order_by(SkillProgressDB.progress.desc()).all()

async def get_career_recommendations(db: Session) -> Dict[str, Any]:
    """Analyze current skill profile and generate career suggestions and gap roadmaps."""
    skills = get_skills(db)
    skill_list = [f"{s.skill_name} ({s.level}, progress: {s.progress}%)" for s in skills]
    
    prompt = f"""Based on the current user skills: {', '.join(skill_list) if skill_list else 'None logged yet'}.
Generate a career transition recommendation. Suggest:
1. A target high-level title (e.g. Principal AI Engineer, Staff MLOps).
2. Rationale behind the recommendation.
3. 3-5 specific skills they must acquire next (skill gap analysis).
4. Time estimate in months.

Format your response STRICTLY as a JSON object:
{{
  "recommended_path": "...",
  "rationale": "...",
  "required_skills": ["...", "..."],
  "timeline_months": 12
}}"""

    res = await execute_llm_call("LearningTrackerAgent", prompt, db, complexity_override="low")
    output = res["output"].strip()
    
    if output.startswith("```json"):
        output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
    output = output.strip()
    
    try:
        recommendations = json.loads(output)
        return recommendations
    except Exception as e:
        logger.error("Failed to parse career recommendations: %s. Output: %s", str(e), output)
        return {
            "recommended_path": "Staff AI Engineer",
            "rationale": "Strong programming fundamentals; transition to large-scale agent orchestration suggested.",
            "required_skills": ["LangGraph Orchestration", "SQLAlchemy Multi-Threading", "Distributed Caching"],
            "timeline_months": 6
        }

async def generate_learning_roadmap(skill_name: str, db: Session) -> Optional[Dict[str, Any]]:
    """Create a structured learning plan under Task Intelligence for a target skill."""
    prompt = f"""Generate a structured learning curriculum for the skill: "{skill_name}".
Provide 3 core projects or milestones. For each milestone, provide a title, description, and estimate of study hours.

Format your response STRICTLY as a JSON array:
[
  {{"title": "Milestone 1", "description": "curriculum content", "hours": 15.0}}
]"""

    res = await execute_llm_call("LearningRoadmapAgent", prompt, db, complexity_override="medium")
    output = res["output"].strip()
    
    if output.startswith("```json"):
        output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
    output = output.strip()
    
    try:
        roadmap_items = json.loads(output)
        
        # 1. Create a parent Learning Plan Goal in tasks DB
        goal_title = f"Master Skill: {skill_name}"
        parent_goal = create_task_entry(
            title=goal_title,
            task_type="learning_plan",
            db=db,
            description=f"Automated roadmap generated to acquire the skill: {skill_name}.",
            estimated_hours=sum(float(item.get("hours", 5.0)) for item in roadmap_items)
        )
        
        # 2. Add milestones under it
        created_tasks = []
        for idx, item in enumerate(roadmap_items):
            sub_task = create_task_entry(
                title=item.get("title", f"Milestone {idx+1}"),
                task_type="task",
                db=db,
                description=item.get("description", ""),
                parent_id=parent_goal.id,
                estimated_hours=float(item.get("hours", 5.0)),
                deadline=datetime.now() + timedelta(days=(idx + 1) * 7)
            )
            created_tasks.append(sub_task)
            
        # Add to local skills registry as active
        add_or_update_skill(
            skill_name=skill_name,
            level="Beginner",
            progress=0.0,
            status="learning",
            db=db,
            targets=[t.id for t in created_tasks]
        )
        
        return {
            "goal_id": parent_goal.id,
            "title": goal_title,
            "milestones_count": len(created_tasks)
        }
    except Exception as e:
        logger.error("Failed to generate learning roadmap: %s. Output: %s", str(e), output)
        return None
