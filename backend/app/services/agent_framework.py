import time
import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
from backend.app.models.database_models import AgentSessionDB
from backend.app.services.model_router import execute_llm_call
from backend.app.core.security_scanner import scan_text

logger = logging.getLogger(__name__)

class AgentFramework:
    """Orchestrates multi-agent collaboration pipelines and tracks execution states."""
    
    def __init__(self, db: Session):
        self.db = db

    async def run_collaboration_pipeline(self, goal: str) -> AgentSessionDB:
        """Run the multi-agent execution pipeline.
        
        Sequence: Coordinator -> Planner -> Researcher -> Coder -> Reviewer -> Security -> Analytics
        """
        # 1. Initialize session in database
        session_entry = AgentSessionDB(
            goal=goal,
            status="running",
            steps=[],
            communication_graph={}
        )
        self.db.add(session_entry)
        self.db.commit()
        self.db.refresh(session_entry)

        steps = []
        
        # Helper to log a step
        def log_step(agent: str, action: str, msg: str, cost: float = 0.0, latency: float = 0.0):
            step = {
                "agent_name": agent,
                "action": action,
                "message": msg,
                "cost": cost,
                "latency": latency,
                "timestamp": datetime.now().isoformat()
            }
            steps.append(step)
            session_entry.steps = steps
            self.db.commit()
            
        # Compile communication graph structure
        comm_graph = {
            "nodes": [
                {"id": "CoordinatorAgent", "label": "Coordinator", "group": "coord"},
                {"id": "PlannerAgent", "label": "Planner", "group": "worker"},
                {"id": "ResearcherAgent", "label": "Researcher", "group": "worker"},
                {"id": "CodingAgent", "label": "Coder", "group": "worker"},
                {"id": "ReviewerAgent", "label": "Reviewer", "group": "worker"},
                {"id": "SecurityAgent", "label": "Security", "group": "security"},
                {"id": "AnalyticsAgent", "label": "Analytics", "group": "analytics"}
            ],
            "edges": [
                {"from": "CoordinatorAgent", "to": "PlannerAgent", "label": "assign_goal"},
                {"from": "PlannerAgent", "to": "ResearcherAgent", "label": "need_info"},
                {"from": "ResearcherAgent", "to": "CodingAgent", "label": "send_specs"},
                {"from": "CodingAgent", "to": "ReviewerAgent", "label": "request_review"},
                {"from": "ReviewerAgent", "to": "SecurityAgent", "label": "security_check"},
                {"from": "SecurityAgent", "to": "AnalyticsAgent", "label": "audit_cost"},
                {"from": "AnalyticsAgent", "to": "CoordinatorAgent", "label": "compile_report"}
            ]
        }
        session_entry.communication_graph = comm_graph
        self.db.commit()

        # Step 1: Coordinator initializes
        t0 = time.time()
        log_step("CoordinatorAgent", "Initialize workflow", f"Received user goal: '{goal}'. Triggering multi-agent collaboration cascade.")
        time.sleep(0.3)  # Small simulation lag to feel real-time in UI
        
        # Step 2: Planner Agent
        t_plan = time.time()
        plan_prompt = f"Plan out the coding and research steps to achieve this goal: {goal}"
        plan_res = await execute_llm_call("PlannerAgent", plan_prompt, self.db, complexity_override="low")
        log_step(
            "PlannerAgent", 
            "Create Execution Roadmap", 
            plan_res["output"], 
            cost=plan_res["cost"], 
            latency=time.time() - t_plan
        )
        time.sleep(0.5)

        # Step 3: Researcher Agent
        t_res = time.time()
        res_prompt = f"Conduct a brief research summary regarding: {goal}. Provide key links or libraries to use."
        res_res = await execute_llm_call("ResearcherAgent", res_prompt, self.db, complexity_override="low")
        log_step(
            "ResearcherAgent", 
            "Technical Research & Context Retrieval", 
            res_res["output"], 
            cost=res_res["cost"], 
            latency=time.time() - t_res
        )
        time.sleep(0.5)

        # Step 4: Coding Agent
        t_code = time.time()
        code_prompt = f"Generate code structure or blueprints addressing the goal: {goal} using the research context."
        code_res = await execute_llm_call("CodingAgent", code_prompt, self.db, complexity_override="medium")
        log_step(
            "CodingAgent", 
            "Generate Blueprints & Code Blocks", 
            code_res["output"], 
            cost=code_res["cost"], 
            latency=time.time() - t_code
        )
        time.sleep(0.5)

        # Step 5: Reviewer Agent
        t_rev = time.time()
        rev_prompt = f"Inspect and conduct a code review of the generated details for: {goal}."
        rev_res = await execute_llm_call("ReviewerAgent", rev_prompt, self.db, complexity_override="low")
        log_step(
            "ReviewerAgent", 
            "Code Quality Inspection", 
            rev_res["output"], 
            cost=rev_res["cost"], 
            latency=time.time() - t_rev
        )
        time.sleep(0.3)

        # Step 6: Security Agent
        t_sec = time.time()
        # Scan code output for security threat
        sec_results = scan_text(code_res["output"], self.db)
        sec_message = f"Scanned code block. Safety score: {sec_results['safety_score']}%. Risk level: {sec_results['risk_level']}. "
        if sec_results["is_safe"]:
            sec_message += "No vulnerabilities or prompt injection signatures detected."
        else:
            sec_message += f"Alert! Detected potential risks: {', '.join(sec_results['threats'])}"
            
        log_step(
            "SecurityAgent", 
            "Vulnerability Scan & Guardrails Check", 
            sec_message, 
            cost=0.0001, 
            latency=time.time() - t_sec
        )
        time.sleep(0.3)

        # Step 7: Analytics Agent
        t_an = time.time()
        # Aggregate costs
        total_cost = sum(s["cost"] for s in steps)
        total_latency = sum(s["latency"] for s in steps)
        analytics_msg = f"Audited agent workflow token metrics. Total estimated query cost: ${total_cost:.5f}. Total pipeline duration: {total_latency:.2f}s."
        log_step(
            "AnalyticsAgent", 
            "Observability & Cost Auditing", 
            analytics_msg, 
            cost=0.0, 
            latency=time.time() - t_an
        )
        
        # Final status update
        session_entry.status = "success"
        self.db.commit()
        
        return session_entry

def get_agent_sessions(db: Session, limit: int = 10) -> List[AgentSessionDB]:
    """Retrieve history of agent workflow sessions."""
    return db.query(AgentSessionDB).order_by(AgentSessionDB.created_at.desc()).limit(limit).all()
