import time
import httpx
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.database_models import ModelRouteLogDB

logger = logging.getLogger(__name__)

# Constants for cost tracking (simulated prices per 1k tokens)
TOKEN_PRICING = {
    "openai": {"input": 0.005, "output": 0.015, "default_model": "gpt-4o"},
    "claude": {"input": 0.003, "output": 0.015, "default_model": "claude-3-5-sonnet"},
    "gemini": {"input": 0.00125, "output": 0.00375, "default_model": "gemini-1.5-flash"},
    "deepseek": {"input": 0.00014, "output": 0.00028, "default_model": "deepseek-chat"},
    "local": {"input": 0.0, "output": 0.0, "default_model": "llama3"}
}

def analyze_complexity(prompt_text: str) -> str:
    """Analyze prompt to determine complexity (low, medium, or high)."""
    word_count = len(prompt_text.split())
    if word_count > 150 or any(kw in prompt_text.lower() for kw in ["design", "architecture", "debug", "refactor", "optimize", "analyze"]):
        return "high"
    elif word_count > 50 or any(kw in prompt_text.lower() for kw in ["explain", "summarize", "list", "how to"]):
        return "medium"
    return "low"

def route_request(complexity: str) -> tuple[str, str]:
    """Determine provider and model based on query complexity."""
    if complexity == "high":
        # Route to more capable models
        if settings.CLAUDE_API_KEY:
            return "claude", TOKEN_PRICING["claude"]["default_model"]
        elif settings.OPENAI_API_KEY:
            return "openai", TOKEN_PRICING["openai"]["default_model"]
    elif complexity == "medium":
        # Route to balanced models
        if settings.GEMINI_API_KEY:
            return "gemini", TOKEN_PRICING["gemini"]["default_model"]
        elif settings.DEEPSEEK_API_KEY:
            return "deepseek", TOKEN_PRICING["deepseek"]["default_model"]
    
    # Low complexity or default fallback
    if settings.GEMINI_API_KEY:
        return "gemini", TOKEN_PRICING["gemini"]["default_model"]
    elif settings.OPENAI_API_KEY:
        return "openai", "gpt-3.5-turbo"
    
    return "local", TOKEN_PRICING["local"]["default_model"]

async def execute_llm_call(
    prompt_name: str,
    prompt_text: str,
    db: Session,
    complexity_override: Optional[str] = None
) -> Dict[str, Any]:
    """Execute LLM call via routed provider, tracking costs, latency and saving logs."""
    complexity = complexity_override or analyze_complexity(prompt_text)
    provider, model = route_request(complexity)
    
    start_time = time.time()
    success = True
    output_text = ""
    input_tokens = len(prompt_text) // 4  # Rough heuristic
    output_tokens = 0
    cost = 0.0
    
    # 1. Real API execution check
    has_key = {
        "openai": bool(settings.OPENAI_API_KEY),
        "claude": bool(settings.CLAUDE_API_KEY),
        "gemini": bool(settings.GEMINI_API_KEY),
        "deepseek": bool(settings.DEEPSEEK_API_KEY),
        "local": False
    }.get(provider, False)
    
    if has_key and not settings.SIMULATION_MODE:
        try:
            output_text, input_tokens, output_tokens = await _call_real_provider(provider, model, prompt_text)
        except Exception as e:
            logger.error("Real LLM call failed, reverting to simulation: %s", str(e))
            success = False
            output_text = _generate_simulated_response(prompt_name, prompt_text)
            output_tokens = len(output_text) // 4
    else:
        # Simulation Mode
        output_text = _generate_simulated_response(prompt_name, prompt_text)
        output_tokens = len(output_text) // 4
    
    latency = time.time() - start_time
    
    # Calculate pricing
    rates = TOKEN_PRICING.get(provider, {"input": 0.0, "output": 0.0})
    cost = ((input_tokens / 1000) * rates["input"]) + ((output_tokens / 1000) * rates["output"])
    
    # Log to DB
    log_entry = ModelRouteLogDB(
        prompt_name=prompt_name,
        provider=provider,
        model_name=model,
        complexity=complexity,
        cost=cost,
        latency=latency,
        reliability_success=success
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    
    return {
        "output": output_text,
        "provider": provider,
        "model": model,
        "cost": cost,
        "latency": latency,
        "tokens": input_tokens + output_tokens,
        "success": success
    }

async def _call_real_provider(provider: str, model: str, prompt: str) -> tuple[str, int, int]:
    """Private helper to invoke external APIs using httpx."""
    # We implement simple HTTP integrations for each provider
    async with httpx.AsyncClient(timeout=30.0) as client:
        if provider == "openai":
            headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
            r = await client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            res = r.json()
            return (
                res["choices"][0]["message"]["content"],
                res["usage"]["prompt_tokens"],
                res["usage"]["completion_tokens"]
            )
            
        elif provider == "gemini":
            headers = {"Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            res = r.json()
            content = res["candidates"][0]["content"]["parts"][0]["text"]
            # Estimate tokens roughly since gemini returns tokens in metadata sometimes
            return content, len(prompt) // 4, len(content) // 4
            
        elif provider == "claude":
            headers = {
                "x-api-key": settings.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]
            }
            r = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            r.raise_for_status()
            res = r.json()
            return (
                res["content"][0]["text"],
                res["usage"]["input_tokens"],
                res["usage"]["output_tokens"]
            )
            
        elif provider == "deepseek":
            headers = {"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
            r = await client.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            res = r.json()
            return (
                res["choices"][0]["message"]["content"],
                res["usage"]["prompt_tokens"],
                res["usage"]["completion_tokens"]
            )
            
    raise NotImplementedError(f"Provider {provider} not supported.")

def _generate_simulated_response(prompt_name: str, prompt_text: str) -> str:
    """Rich domain simulation engine to provide realistic responses for all 12 modules."""
    prompt_lower = prompt_text.lower()
    
    # 1. Goal / Task breaking simulation
    if "breakdown" in prompt_lower or "break down" in prompt_lower or "learning roadmap" in prompt_lower:
        if "ai engineer" in prompt_lower:
            return """[
  {
    "title": "Master Python Core & MLOps basics",
    "description": "Learn advanced async python, packaging, pip, docker basics, and testing.",
    "type": "learning_plan",
    "estimated_hours": 40.0
  },
  {
    "title": "Study Deep Learning & Transformer Models",
    "description": "Understand transformers architecture, self-attention, tokenization, and HuggingFace API.",
    "type": "learning_plan",
    "estimated_hours": 60.0
  },
  {
    "title": "Agent System Architecture with LangGraph",
    "description": "Learn statecharts, cyclical agent graphs, memory checkpointing, and tool routing.",
    "type": "project",
    "estimated_hours": 50.0
  },
  {
    "title": "Build OmniMind AI OS Portfolio App",
    "description": "Assemble the multi-agent dashboard with databases, search citation, and local vector fallback.",
    "type": "project",
    "estimated_hours": 80.0
  }
]"""
        else:
            return """[
  {
    "title": "Research & Requirements Analysis",
    "description": "Define the target outcome, audit dependencies, and map requirements.",
    "type": "task",
    "estimated_hours": 8.0
  },
  {
    "title": "Prototype Development",
    "description": "Implement core functional functions and write unit tests.",
    "type": "project",
    "estimated_hours": 20.0
  },
  {
    "title": "Testing and Verification",
    "description": "Perform end-to-end user testing and benchmark latency/reliability.",
    "type": "task",
    "estimated_hours": 10.0
  }
]"""
            
    # 2. Knowledge Graph Node/Edge extraction simulation
    elif "extract entity" in prompt_lower or "relationship" in prompt_lower or "knowledge graph" in prompt_lower:
        return """{
  "nodes": [
    {"id": "python", "label": "Python", "type": "Language", "properties": {"level": "core"}},
    {"id": "langgraph", "label": "LangGraph", "type": "Library", "properties": {"type": "agentic"}},
    {"id": "chromadb", "label": "ChromaDB", "type": "Database", "properties": {"type": "vector"}},
    {"id": "sqlite", "label": "SQLite", "type": "Database", "properties": {"type": "relational"}}
  ],
  "edges": [
    {"source_id": "langgraph", "target_id": "python", "relation": "written_in", "weight": 1.0},
    {"source_id": "langgraph", "target_id": "chromadb", "relation": "integrates_with", "weight": 0.8},
    {"source_id": "chromadb", "target_id": "sqlite", "relation": "stores_metadata_in", "weight": 0.5}
  ]
}"""

    # 3. Agent workflow simulator responses
    elif "coordinator" in prompt_name.lower():
        return "Received user instruction. delegating to PlannerAgent to map out the execution roadmap."
    elif "planner" in prompt_name.lower():
        return "Created execution plan. Spawning ResearchAgent to retrieve documentation and CodingAgent to implement."
    elif "researcher" in prompt_name.lower():
        return "Retrieved technical details: ChromaDB uses PersistentClient, and SQLite connection needs check_same_thread=False."
    elif "coder" in prompt_name.lower():
        return "Generated file contents successfully. Submitting to ReviewerAgent for code inspection and validation checks."
    elif "reviewer" in prompt_name.lower():
        return "Review complete! All imports are sound, fallbacks are active, and no threat signatures found."
    
    # 4. Security Center simulation
    elif "jailbreak" in prompt_lower or "prompt injection" in prompt_lower or "expose sensitive" in prompt_lower:
        return """{
  "threats": ["Jailbreak Attempt", "PII Exposure Risk"],
  "safety_score": 35.0,
  "risk_level": "high"
}"""
    
    # 5. Self-Improvement response evaluator
    elif "evaluate response" in prompt_lower or "failure analysis" in prompt_lower:
        return """{
  "failure_detected": true,
  "failure_type": "hallucination",
  "score": 0.45,
  "optimized_instruction": "Always cross-reference the local SQL model parameters before referencing cloud PostgreSQL column names."
}"""

    # 6. Meeting summarization
    elif "meeting summary" in prompt_lower or "action item" in prompt_lower:
        return """{
  "summary": "The team aligned on implementing a NumPy fallback vector store because some developer laptops do not have local C++ compilers installed to build chromadb natively.",
  "action_items": [
    {"title": "Implement LocalVectorStore NumPy class", "assignee": "Lead Engineer", "due": "2026-06-28"},
    {"title": "Configure config file fallback settings", "assignee": "MLOps Architect", "due": "2026-06-26"}
  ],
  "decisions": [
    "Default database to SQLite instead of cloud PostgreSQL to run locally instantly."
  ]
}"""

    # 7. Learning Career path simulator
    elif "career recommendation" in prompt_lower or "skill gap" in prompt_lower:
        return """{
  "recommended_path": "Principal MLOps and Agent Systems Architect",
  "rationale": "Given your strong background in Python, databases, and multi-agent workflow engines, migrating into system optimization, LLM evaluations, and continuous learning pipelines provides the highest leverage.",
  "required_skills": ["LangGraph", "ChromaDB", "Evaluation Pipelines", "Prompt A/B Testing", "Kubernetes"],
  "timeline_months": 8
}"""

    # 8. General conversational fallback
    return f"This is a simulated high-quality response from OmniMind AI OS. I have analyzed your request: '{prompt_text[:60]}...' and processed it using the integrated agents framework."
