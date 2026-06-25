import json
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.app.models.database_models import MeetingDB
from backend.app.services.model_router import execute_llm_call
from backend.app.services.task_intelligence import create_task_entry
from backend.app.services.memory_engine import add_memory

logger = logging.getLogger(__name__)

async def process_meeting_transcript(
    title: str,
    transcript: str,
    db: Session
) -> MeetingDB:
    """Analyze a transcript, extract summary/actions/decisions, and spawn action items as system tasks."""
    prompt = f"""Analyze the meeting transcript below and extract:
1. A concise meeting summary.
2. A list of key decisions made.
3. Action items. For each action item, specify a title, description, assignee, and days_to_complete.

Format your output STRICTLY as a JSON object:
{{
  "summary": "...",
  "decisions": ["...", "..."],
  "action_items": [
    {{"title": "...", "description": "...", "assignee": "...", "days_to_complete": 3}}
  ]
}}

Transcript:
"{transcript}"
"""
    
    res = await execute_llm_call("MeetingIntelligenceAgent", prompt, db, complexity_override="medium")
    output = res["output"].strip()
    
    # Strip markdown block ticks if present
    if output.startswith("```json"):
        output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
    output = output.strip()
    
    summary = "Summary generation failed or returned invalid JSON format."
    decisions = []
    action_items = []
    
    try:
        data = json.loads(output)
        summary = data.get("summary", "")
        decisions = data.get("decisions", [])
        action_items = data.get("action_items", [])
    except Exception as e:
        logger.error("Failed to parse meeting analysis JSON: %s. Output: %s", str(e), output)
        summary = f"Partial analysis: {output[:200]}..."
        
    # Save meeting DB record
    db_meeting = MeetingDB(
        title=title,
        transcript=transcript,
        summary=summary,
        decisions=decisions,
        action_items=action_items
    )
    db.add(db_meeting)
    db.commit()
    db.refresh(db_meeting)
    
    # Create an associated memory entry automatically
    memory_content = f"Meeting: {title}\nSummary: {summary}\nDecisions: {', '.join(decisions)}"
    await add_memory(
        content=memory_content,
        memory_type="session",
        db=db,
        metadata={"source": "meeting", "meeting_id": db_meeting.id}
    )
    
    # Spawn action items into the Task Intelligence system
    for item in action_items:
        t_title = f"[{item.get('assignee', 'Unassigned')}] {item.get('title')}"
        t_desc = f"Action item from meeting '{title}'. Assigned to {item.get('assignee', 'Unassigned')}.\n\nDescription: {item.get('description', '')}"
        days = int(item.get("days_to_complete", 5))
        deadline = datetime.now() + timedelta(days=days)
        
        try:
            create_task_entry(
                title=t_title,
                task_type="task",
                db=db,
                description=t_desc,
                estimated_hours=float(days * 2),  # Heuristic estimation
                deadline=deadline
            )
        except Exception as e:
            logger.error("Failed to auto-create task from meeting action item: %s", str(e))
            
    return db_meeting

def get_meetings(db: Session, limit: int = 10) -> List[MeetingDB]:
    """Retrieve history of analyzed meetings."""
    return db.query(MeetingDB).order_by(MeetingDB.created_at.desc()).limit(limit).all()
