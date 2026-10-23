import time
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.database_models import AgentSessionDB, GraphNodeDB
from backend.app.services.model_router import execute_llm_call, redact_secrets
from backend.app.core.security_scanner import scan_text
from backend.app.services import memory_engine

logger = logging.getLogger(__name__)

class AgentFramework:
    """Orchestrates multi-agent collaboration pipelines with bounded execution, retries, and traceability."""
    
    def __init__(self, db: Session):
        self.db = db

    async def run_collaboration_pipeline(
        self,
        goal: str,
        task_id: Optional[str] = None,
        max_steps: Optional[int] = None,
        max_retries: Optional[int] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> AgentSessionDB:
        """Run the multi-agent collaboration cascade:
        Coordinator -> Planner -> Researcher -> Coder -> Reviewer -> Security -> Analytics
        """
        clean_goal = redact_secrets(goal.strip() if goal else "")
        if not clean_goal:
            raise ValueError("Goal cannot be empty or whitespace.")

        effective_max_steps = max_steps or settings.MAX_AGENT_STEPS
        effective_max_retries = max_retries if max_retries is not None else settings.MAX_AGENT_RETRIES

        # 1. Initialize session entry in database
        session_entry = AgentSessionDB(
            goal=clean_goal,
            status="running",
            steps=[],
            communication_graph={}
        )
        self.db.add(session_entry)
        self.db.commit()
        self.db.refresh(session_entry)

        steps: List[Dict[str, Any]] = []
        total_steps_executed = 0

        # Helper to log and persist execution steps
        def log_step(
            agent: str,
            role: str,
            action: str,
            msg: str,
            status: str = "completed",
            cost: float = 0.0,
            latency: float = 0.0,
            provider: Optional[str] = None,
            model: Optional[str] = None,
            is_simulated: bool = False,
            input_summary: Optional[str] = None,
            retry_count: int = 0,
            failure_details: Optional[str] = None,
            start_time_iso: Optional[str] = None
        ):
            now_iso = datetime.now().isoformat()
            step_record = {
                "execution_id": session_entry.id,
                "task_id": task_id,
                "agent_name": agent,
                "agent_role": role,
                "action": action,
                "message": redact_secrets(msg),
                "status": status,
                "cost": round(cost, 6),
                "latency": round(latency, 4),
                "provider": provider,
                "model": model,
                "is_simulated": is_simulated,
                "input_summary": redact_secrets(input_summary) if input_summary else None,
                "output_summary": redact_secrets(msg[:300] + "..." if len(msg) > 300 else msg),
                "retry_count": retry_count,
                "failure_details": redact_secrets(failure_details) if failure_details else None,
                "start_time": start_time_iso or now_iso,
                "end_time": now_iso,
                "timestamp": now_iso
            }
            steps.append(step_record)
            session_entry.steps = list(steps)
            self.db.commit()

        # Initialize communication graph
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
            ],
            "metadata": {
                "task_id": task_id,
                "max_steps": effective_max_steps,
                "max_retries": effective_max_retries,
                "provider_override": provider_override,
                "model_override": model_override
            }
        }
        session_entry.communication_graph = comm_graph
        self.db.commit()

        # Bounded step invoker with retries
        async def call_agent_bounded(
            agent_name: str,
            role: str,
            action: str,
            prompt: str,
            complexity: str = "medium"
        ) -> Tuple[bool, Dict[str, Any]]:
            nonlocal total_steps_executed

            for attempt in range(effective_max_retries + 1):
                if total_steps_executed >= effective_max_steps:
                    err_msg = f"Bounded execution limit of {effective_max_steps} steps reached. Aborting."
                    log_step(
                        agent=agent_name,
                        role=role,
                        action=action,
                        msg=err_msg,
                        status="failed",
                        retry_count=attempt,
                        failure_details=err_msg
                    )
                    return False, {"output": err_msg, "success": False, "error": err_msg}

                total_steps_executed += 1
                t_start = time.time()
                start_iso = datetime.now().isoformat()

                try:
                    call_kwargs = {"complexity_override": complexity}
                    if provider_override is not None:
                        call_kwargs["provider_override"] = provider_override
                    if model_override is not None:
                        call_kwargs["model_override"] = model_override

                    res = await execute_llm_call(
                        agent_name,
                        prompt,
                        self.db,
                        **call_kwargs
                    )
                except Exception as call_err:
                    res = {
                        "output": "",
                        "success": False,
                        "error": str(call_err),
                        "cost": 0.0,
                        "latency": time.time() - t_start,
                        "provider": provider_override or "unknown",
                        "model": model_override or "unknown",
                        "is_simulated": False
                    }

                step_latency = time.time() - t_start
                is_success = res.get("success", False) and bool(res.get("output", "").strip())

                if is_success:
                    log_step(
                        agent=agent_name,
                        role=role,
                        action=action,
                        msg=res["output"],
                        status="completed",
                        cost=res.get("cost", 0.0),
                        latency=step_latency,
                        provider=res.get("provider"),
                        model=res.get("model"),
                        is_simulated=res.get("is_simulated", False),
                        input_summary=prompt[:150],
                        retry_count=attempt,
                        start_time_iso=start_iso
                    )
                    return True, res
                else:
                    raw_err = res.get("error") or "Model returned empty or unsuccessful response."
                    err_detail = redact_secrets(raw_err)
                    
                    if attempt < effective_max_retries and total_steps_executed < effective_max_steps:
                        logger.warning("%s attempt %d failed: %s. Retrying...", agent_name, attempt + 1, err_detail)
                        log_step(
                            agent=agent_name,
                            role=role,
                            action=f"{action} (Retry {attempt + 1})",
                            msg=f"Attempt {attempt + 1} failed: {err_detail}. Retrying...",
                            status="retrying",
                            cost=res.get("cost", 0.0),
                            latency=step_latency,
                            provider=res.get("provider"),
                            model=res.get("model"),
                            is_simulated=res.get("is_simulated", False),
                            input_summary=prompt[:150],
                            retry_count=attempt + 1,
                            failure_details=err_detail,
                            start_time_iso=start_iso
                        )
                        await asyncio.sleep(0.1)
                    else:
                        log_step(
                            agent=agent_name,
                            role=role,
                            action=action,
                            msg=f"Agent execution failed after {attempt + 1} attempt(s): {err_detail}",
                            status="failed",
                            cost=res.get("cost", 0.0),
                            latency=step_latency,
                            provider=res.get("provider"),
                            model=res.get("model"),
                            is_simulated=res.get("is_simulated", False),
                            input_summary=prompt[:150],
                            retry_count=attempt,
                            failure_details=err_detail,
                            start_time_iso=start_iso
                        )
                        return False, res

            return False, {"output": "Max retries exceeded", "success": False, "error": "Max retries exceeded"}

        pipeline_success = True
        failure_reasons = []

        try:
            # -------------------------------------------------------------
            # Step 1: Coordinator initializes
            # -------------------------------------------------------------
            log_step(
                agent="CoordinatorAgent",
                role="Coordinator",
                action="Initialize workflow",
                msg=f"Received user goal: '{clean_goal}'. Enforcing max_steps={effective_max_steps}, max_retries={effective_max_retries}. Triggering multi-agent collaboration cascade.",
                status="completed"
            )
            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 2: Planner Agent
            # -------------------------------------------------------------
            plan_prompt = f"""You are the Planner Agent. Given the high-level objective below, create a structured, step-by-step roadmap to achieve it.
Break it down into discrete requirements, phases, and verifiable deliverables.

Goal: "{clean_goal}"
"""
            ok_plan, plan_res = await call_agent_bounded(
                agent_name="PlannerAgent",
                role="Planner",
                action="Create Execution Roadmap",
                prompt=plan_prompt,
                complexity="low"
            )
            if not ok_plan:
                pipeline_success = False
                failure_reasons.append("Planner agent failed to generate execution roadmap")
                session_entry.status = "failed"
                self.db.commit()
                return session_entry

            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 3: Researcher Agent (Project Knowledge & Memory Retrieval)
            # -------------------------------------------------------------
            retrieved_context_items = []
            try:
                # 1. Search knowledge graph for matching concepts
                graph_nodes = self.db.query(GraphNodeDB).filter(
                    GraphNodeDB.label.ilike(f"%{clean_goal[:30]}%")
                ).limit(4).all()
                if graph_nodes:
                    retrieved_context_items.extend([f"KG Concept: {n.label} ({n.type})" for n in graph_nodes])
                
                # 2. Search persistent memories for relevant background
                matching_mems = memory_engine.search_memories(clean_goal, self.db, limit=3)
                if matching_mems:
                    for m in matching_mems:
                        m_text = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                        if m_text:
                            retrieved_context_items.append(f"Memory: {m_text[:150]}")
            except Exception as ctx_err:
                logger.warning("Non-fatal error retrieving knowledge context: %s", str(ctx_err))

            knowledge_snippet = "\n".join(retrieved_context_items) if retrieved_context_items else "No prior project memory or graph entities matched."

            res_prompt = f"""You are the Researcher Agent. Conduct technical research and gather relevant specifications for:
Goal: "{clean_goal}"

Execution Plan Context:
{plan_res['output']}

Approved Knowledge & Memory Context:
{knowledge_snippet}

Synthesize your research findings, architecture patterns, and technical guidelines into structured findings.
"""
            ok_res, res_res = await call_agent_bounded(
                agent_name="ResearcherAgent",
                role="Researcher",
                action="Technical Research & Context Retrieval",
                prompt=res_prompt,
                complexity="low"
            )
            if not ok_res:
                pipeline_success = False
                failure_reasons.append("Researcher agent failed to gather context")
                session_entry.status = "failed"
                self.db.commit()
                return session_entry

            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 4: Coding Agent (Generates Proposed Code Blueprints)
            # -------------------------------------------------------------
            code_prompt = f"""You are the Coding Agent. Produce proposed code blocks, implementation structures, or blueprints addressing:
Goal: "{clean_goal}"

Execution Plan:
{plan_res['output']}

Research Findings:
{res_res['output']}

Provide modular, production-ready, clean code blocks. Do not execute or run scripts."""

            ok_code, code_res = await call_agent_bounded(
                agent_name="CodingAgent",
                role="Coder",
                action="Generate Blueprints & Code Blocks",
                prompt=code_prompt,
                complexity="medium"
            )
            if not ok_code:
                pipeline_success = False
                failure_reasons.append("Coding agent failed to generate blueprints")
                session_entry.status = "failed"
                self.db.commit()
                return session_entry

            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 5: Reviewer Agent (Defect Inspection & Validation)
            # -------------------------------------------------------------
            rev_prompt = f"""You are the Reviewer Agent. Inspect and review the generated implementation details against the original goal and execution roadmap.
Original Goal: "{clean_goal}"

Proposed Implementation:
{code_res['output']}

Check for defects, boundary conditions, style guidelines, and missing error handling. Provide clear critique or approval.
"""
            ok_rev, rev_res = await call_agent_bounded(
                agent_name="ReviewerAgent",
                role="Reviewer",
                action="Code Quality Inspection",
                prompt=rev_prompt,
                complexity="low"
            )
            if not ok_rev:
                pipeline_success = False
                failure_reasons.append("Reviewer agent failed code inspection")
                session_entry.status = "failed"
                self.db.commit()
                return session_entry

            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 6: Security Agent (Deterministic Vulnerability & Injection Scan)
            # -------------------------------------------------------------
            t_sec = time.time()
            sec_results = scan_text(code_res["output"], self.db)
            sec_latency = time.time() - t_sec

            if not sec_results["is_safe"]:
                pipeline_success = False
                failure_reasons.append(f"Security Alert: {', '.join(sec_results['threats'])}")
                sec_status = "failed"
                sec_message = f"Alert! Detected potential risks: {', '.join(sec_results['threats'])}. Safety score: {sec_results['safety_score']}%. Risk level: {sec_results['risk_level']}."
            else:
                sec_status = "completed"
                sec_message = f"Scanned code blocks. Safety score: {sec_results['safety_score']}%. Risk level: {sec_results['risk_level']}. No injection signatures or dangerous patterns detected."

            log_step(
                agent="SecurityAgent",
                role="Security",
                action="Vulnerability Scan & Guardrails Check",
                msg=sec_message,
                status=sec_status,
                cost=0.0001,
                latency=sec_latency,
                is_simulated=False,
                failure_details=None if sec_results["is_safe"] else f"Security Alert: {', '.join(sec_results['threats'])}"
            )
            await asyncio.sleep(0.02)

            # -------------------------------------------------------------
            # Step 7: Analytics Agent (Cost & Observability Audit)
            # -------------------------------------------------------------
            t_an = time.time()
            total_cost = sum(s["cost"] for s in steps)
            total_latency = sum(s["latency"] for s in steps)
            total_retries = sum(s.get("retry_count", 0) for s in steps)

            outcome_str = "Pipeline completed successfully." if pipeline_success else f"Pipeline flagged issues: {'; '.join(failure_reasons)}"
            analytics_msg = (
                f"Audited agent workflow metrics. Steps executed: {len(steps)}. "
                f"Total retries: {total_retries}. Total estimated cost: ${total_cost:.5f}. "
                f"Total cumulative latency: {total_latency:.2f}s. Outcome: {outcome_str}"
            )

            log_step(
                agent="AnalyticsAgent",
                role="Analytics",
                action="Observability & Cost Auditing",
                msg=analytics_msg,
                status="completed" if pipeline_success else "failed",
                cost=0.0,
                latency=time.time() - t_an,
                is_simulated=False
            )

            # Update final session status and persist
            session_entry.status = "success" if pipeline_success else "failed"
            self.db.commit()

        except Exception as e:
            logger.error("Agent workflow pipeline uncaught error: %s", str(e), exc_info=True)
            log_step(
                agent="CoordinatorAgent",
                role="Coordinator",
                action="Pipeline Error",
                msg=f"Workflow execution halted: {redact_secrets(str(e))}",
                status="failed",
                failure_details=redact_secrets(str(e))
            )
            session_entry.status = "failed"
            self.db.commit()

        return session_entry

def get_agent_sessions(db: Session, limit: int = 10) -> List[AgentSessionDB]:
    """Retrieve history of agent workflow sessions."""
    return db.query(AgentSessionDB).order_by(AgentSessionDB.created_at.desc()).limit(limit).all()

def get_agent_session_by_id(session_id: str, db: Session) -> Optional[AgentSessionDB]:
    """Retrieve a specific agent workflow session by its ID."""
    return db.query(AgentSessionDB).filter(AgentSessionDB.id == session_id).first()
