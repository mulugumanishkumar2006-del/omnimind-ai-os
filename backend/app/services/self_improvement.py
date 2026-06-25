import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from backend.app.models.database_models import SelfImprovementDB, PromptDB
from backend.app.services.model_router import execute_llm_call

logger = logging.getLogger(__name__)

def log_failure_case(
    prompt_name: str,
    input_text: str,
    output_text: str,
    failure_type: str,  # hallucination, low_confidence, user_correction
    evaluation_score: float,
    db: Session,
    correction_details: Optional[str] = None
) -> SelfImprovementDB:
    """Register an agent failure or user correction milestone."""
    log_entry = SelfImprovementDB(
        prompt_name=prompt_name,
        input_text=input_text,
        output_text=output_text,
        failure_type=failure_type,
        evaluation_score=evaluation_score,
        correction_details=correction_details
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry

async def optimize_prompt_from_failure(failure_id: str, db: Session) -> Optional[PromptDB]:
    """Execute evaluation loop: Failure Analysis -> Prompt Optimization -> Update Prompt Studio version."""
    failure = db.query(SelfImprovementDB).filter(SelfImprovementDB.id == failure_id).first()
    if not failure:
        return None
        
    # Get active template in Prompt Studio
    active_prompt = db.query(PromptDB).filter(
        PromptDB.name == failure.prompt_name
    ).order_by(PromptDB.version.desc()).first()
    
    current_template = active_prompt.template if active_prompt else "Default Agent Template"
    
    prompt = f"""You are a Meta-Prompt Optimization Agent. An agent execution failed.
Your task is to rewrite the system prompt template to avoid this failure in the future.

Current Prompt Template:
\"\"\"{current_template}\"\"\"

Failure Analysis Context:
- Target Prompt: {failure.prompt_name}
- Input Query: {failure.input_text}
- Erroneous Output: {failure.output_text}
- Failure Type: {failure.failure_type}
- Evaluation Score: {failure.evaluation_score}/1.0
- Correction Context: {failure.correction_details or 'None provided'}

Provide only the optimized version of the prompt template. Focus on injecting strict constraints, formatting rules, or few-shot corrections directly addressing the failure context. Keep the general structure but fix the gap.
"""

    res = await execute_llm_call("PromptOptimizerAgent", prompt, db, complexity_override="medium")
    optimized_template = res["output"].strip()
    
    # Version bump and write to Prompt Studio database
    new_version = (active_prompt.version + 1) if active_prompt else 1
    
    new_prompt = PromptDB(
        name=failure.prompt_name,
        template=optimized_template,
        version=new_version,
        metrics={"avg_cost": 0.0, "avg_latency": 0.0, "avg_rating": 5.0},
        is_active_a=True,  # Set as candidate for A/B testing
        is_active_b=False
    )
    db.add(new_prompt)
    db.commit()
    db.refresh(new_prompt)
    
    # Update failure log link
    failure.optimized_prompt_id = new_prompt.id
    db.commit()
    
    return new_prompt

def get_self_improvement_reports(db: Session, limit: int = 15) -> List[SelfImprovementDB]:
    """Get the optimization auditing history logs."""
    return db.query(SelfImprovementDB).order_by(SelfImprovementDB.created_at.desc()).limit(limit).all()
