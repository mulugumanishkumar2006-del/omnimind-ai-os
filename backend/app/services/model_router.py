import re
import time
import httpx
import logging
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.database_models import ModelRouteLogDB

logger = logging.getLogger(__name__)

# Constants for cost tracking (prices in USD per 1k tokens)
TOKEN_PRICING = {
    "openai": {"input": 0.005, "output": 0.015, "default_model": "gpt-4o"},
    "claude": {"input": 0.003, "output": 0.015, "default_model": "claude-3-5-sonnet"},
    "gemini": {"input": 0.00125, "output": 0.00375, "default_model": "gemini-1.5-flash"},
    "deepseek": {"input": 0.00014, "output": 0.00028, "default_model": "deepseek-chat"},
    "ollama": {"input": 0.0, "output": 0.0, "default_model": "llama3:latest"},
    "local": {"input": 0.0, "output": 0.0, "default_model": "llama3:latest"}
}

def redact_secrets(text: Optional[str]) -> str:
    """Redact known API keys, tokens, and authorization parameters from error messages and logs."""
    if not text:
        return ""
    sanitized = str(text)
    for key in [
        settings.OPENAI_API_KEY,
        settings.GEMINI_API_KEY,
        settings.CLAUDE_API_KEY,
        settings.DEEPSEEK_API_KEY
    ]:
        if key and len(key) > 5:
            sanitized = sanitized.replace(key, "[REDACTED_API_KEY]")
            
    # Redact standard provider secret formats (OpenAI, Anthropic Claude, Google Gemini, DeepSeek)
    sanitized = re.sub(r'sk-[a-zA-Z0-9_\-]{20,}', '[REDACTED_API_KEY]', sanitized)
    sanitized = re.sub(r'AIzaSy[0-9A-Za-z_\-]{33}', '[REDACTED_API_KEY]', sanitized)
    
    # Redact query parameter keys and authorization headers
    sanitized = re.sub(r'(key|api_key|token|auth|secret)[\s:=]+([A-Za-z0-9_\-\.]{8,})', r'\1=[REDACTED_KEY]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'Bearer\s+[A-Za-z0-9_.-]{8,}', 'Bearer [REDACTED_TOKEN]', sanitized, flags=re.IGNORECASE)
    return sanitized


# =====================================================================
# PROVIDER ADAPTERS
# =====================================================================

class BaseProviderAdapter:
    """Interface definition for LLM providers."""
    async def call(self, model: str, prompt: str, timeout: float) -> Tuple[str, int, int, Dict[str, Any]]:
        raise NotImplementedError

class OllamaProvider(BaseProviderAdapter):
    """Local LLM provider interfacing with the Ollama HTTP API."""
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    async def check_health(self, timeout: float = 2.0) -> Dict[str, Any]:
        """Detect whether the Ollama daemon is reachable and enumerate installed models."""
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {"reachable": True, "base_url": self.base_url, "models": models}
                return {"reachable": False, "base_url": self.base_url, "status_code": r.status_code}
        except Exception as e:
            return {"reachable": False, "base_url": self.base_url, "models": [], "error": redact_secrets(str(e))}

    async def call(self, model: str, prompt: str, timeout: Optional[float] = None) -> Tuple[str, int, int, Dict[str, Any]]:
        call_timeout = timeout or settings.OLLAMA_TIMEOUT
        chat_url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }

        try:
            async with httpx.AsyncClient(timeout=call_timeout) as client:
                r = await client.post(chat_url, json=payload)
                if r.status_code == 404:
                    err_msg = ""
                    try:
                        err_msg = r.json().get("error", "")
                    except Exception:
                        err_msg = r.text
                    raise RuntimeError(
                        f"Ollama model '{model}' not found on server at {self.base_url}: {err_msg}. "
                        f"Run 'ollama pull {model}' to download it."
                    )
                r.raise_for_status()
                res = r.json()
                
                content = res.get("message", {}).get("content", "")
                if not content:
                    raise RuntimeError("Ollama returned an empty response.")
                    
                input_tokens = res.get("prompt_eval_count") or (len(prompt) // 4)
                output_tokens = res.get("eval_count") or (len(content) // 4)
                metadata = {
                    "total_duration_ns": res.get("total_duration"),
                    "load_duration_ns": res.get("load_duration"),
                    "prompt_eval_count": res.get("prompt_eval_count"),
                    "eval_count": res.get("eval_count")
                }
                return content, int(input_tokens), int(output_tokens), metadata
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running ('ollama serve')."
            )
        except httpx.TimeoutException:
            raise RuntimeError(
                f"Ollama request to {self.base_url} timed out after {call_timeout}s."
            )
        except Exception as e:
            raise RuntimeError(redact_secrets(str(e)))

class OpenAIProvider(BaseProviderAdapter):
    """Remote OpenAI LLM Provider."""
    async def call(self, model: str, prompt: str, timeout: float = 30.0) -> Tuple[str, int, int, Dict[str, Any]]:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured.")
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
                r.raise_for_status()
                res = r.json()
                content = res["choices"][0]["message"]["content"]
                in_tok = res.get("usage", {}).get("prompt_tokens", len(prompt) // 4)
                out_tok = res.get("usage", {}).get("completion_tokens", len(content) // 4)
                return content, in_tok, out_tok, {"finish_reason": res["choices"][0].get("finish_reason")}
        except Exception as e:
            raise RuntimeError(redact_secrets(str(e)))

class GeminiProvider(BaseProviderAdapter):
    """Remote Google Gemini LLM Provider."""
    async def call(self, model: str, prompt: str, timeout: float = 30.0) -> Tuple[str, int, int, Dict[str, Any]]:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured.")
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY
        }
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                res = r.json()
                content = res["candidates"][0]["content"]["parts"][0]["text"]
                usage = res.get("usageMetadata", {})
                in_tok = usage.get("promptTokenCount", len(prompt) // 4)
                out_tok = usage.get("candidatesTokenCount", len(content) // 4)
                return content, in_tok, out_tok, {"usageMetadata": usage}
        except Exception as e:
            raise RuntimeError(redact_secrets(str(e)))

class ClaudeProvider(BaseProviderAdapter):
    """Remote Anthropic Claude LLM Provider."""
    async def call(self, model: str, prompt: str, timeout: float = 30.0) -> Tuple[str, int, int, Dict[str, Any]]:
        if not settings.CLAUDE_API_KEY:
            raise ValueError("CLAUDE_API_KEY is not configured.")
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
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
                r.raise_for_status()
                res = r.json()
                content = res["content"][0]["text"]
                in_tok = res.get("usage", {}).get("input_tokens", len(prompt) // 4)
                out_tok = res.get("usage", {}).get("output_tokens", len(content) // 4)
                return content, in_tok, out_tok, {}
        except Exception as e:
            raise RuntimeError(redact_secrets(str(e)))

class DeepSeekProvider(BaseProviderAdapter):
    """Remote DeepSeek LLM Provider."""
    async def call(self, model: str, prompt: str, timeout: float = 30.0) -> Tuple[str, int, int, Dict[str, Any]]:
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY is not configured.")
        headers = {
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers)
                r.raise_for_status()
                res = r.json()
                content = res["choices"][0]["message"]["content"]
                in_tok = res.get("usage", {}).get("prompt_tokens", len(prompt) // 4)
                out_tok = res.get("usage", {}).get("completion_tokens", len(content) // 4)
                return content, in_tok, out_tok, {}
        except Exception as e:
            raise RuntimeError(redact_secrets(str(e)))


PROVIDERS: Dict[str, BaseProviderAdapter] = {
    "ollama": OllamaProvider(),
    "local": OllamaProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "claude": ClaudeProvider(),
    "deepseek": DeepSeekProvider()
}

def analyze_complexity(prompt_text: str) -> str:
    """Analyze prompt to determine complexity (low, medium, or high)."""
    word_count = len(prompt_text.split())
    if word_count > 150 or any(kw in prompt_text.lower() for kw in ["design", "architecture", "debug", "refactor", "optimize", "analyze"]):
        return "high"
    elif word_count > 50 or any(kw in prompt_text.lower() for kw in ["explain", "summarize", "list", "how to"]):
        return "medium"
    return "low"

def route_request(complexity: str) -> Tuple[str, str]:
    """Determine provider and model based on query complexity, environment variables, or availability."""
    if settings.DEFAULT_LLM_PROVIDER:
        provider = settings.DEFAULT_LLM_PROVIDER.lower()
        default_model = TOKEN_PRICING.get(provider, {}).get("default_model", "default")
        model = settings.DEFAULT_LLM_MODEL or default_model
        return provider, model

    if complexity == "high":
        if settings.CLAUDE_API_KEY:
            return "claude", TOKEN_PRICING["claude"]["default_model"]
        elif settings.OPENAI_API_KEY:
            return "openai", TOKEN_PRICING["openai"]["default_model"]
    elif complexity == "medium":
        if settings.GEMINI_API_KEY:
            return "gemini", TOKEN_PRICING["gemini"]["default_model"]
        elif settings.DEEPSEEK_API_KEY:
            return "deepseek", TOKEN_PRICING["deepseek"]["default_model"]
    
    # Low complexity or default provider
    if settings.GEMINI_API_KEY:
        return "gemini", TOKEN_PRICING["gemini"]["default_model"]
    elif settings.OPENAI_API_KEY:
        return "openai", "gpt-3.5-turbo"
    
    return "ollama", TOKEN_PRICING["ollama"]["default_model"]

async def _call_real_provider(provider: str, model: str, prompt: str) -> Tuple[str, int, int, Dict[str, Any]]:
    """Private dispatcher to invoke real LLM provider adapters."""
    clean_provider = provider.lower()
    adapter = PROVIDERS.get(clean_provider)
    if not adapter:
        raise NotImplementedError(f"Provider '{provider}' is not supported.")
    return await adapter.call(model, prompt, timeout=settings.OLLAMA_TIMEOUT if clean_provider in ("ollama", "local") else 30.0)

async def execute_llm_call(
    prompt_name: str,
    prompt_text: str,
    db: Session,
    complexity_override: Optional[str] = None,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    allow_fallback_override: Optional[bool] = None
) -> Dict[str, Any]:
    """Execute LLM call via routed or overridden provider with cost/latency tracking and honest simulation reporting."""
    complexity = complexity_override or analyze_complexity(prompt_text)
    
    routed_provider, routed_model = route_request(complexity)
    provider = (provider_override or routed_provider).lower()
    model = model_override or routed_model
    
    # Determine fallback policy
    allow_fallback = (
        allow_fallback_override
        if allow_fallback_override is not None
        else settings.ALLOW_SIMULATION_FALLBACK
    )
    
    start_time = time.time()
    success = True
    output_text = ""
    input_tokens = len(prompt_text) // 4
    output_tokens = 0
    cost = 0.0
    is_simulated = False
    is_fallback = False
    fallback_reason: Optional[str] = None
    error_detail: Optional[str] = None
    raw_metadata: Dict[str, Any] = {}
    
    # Check if this provider has credentials / can run in real mode
    has_credentials = {
        "openai": bool(settings.OPENAI_API_KEY),
        "claude": bool(settings.CLAUDE_API_KEY),
        "gemini": bool(settings.GEMINI_API_KEY),
        "deepseek": bool(settings.DEEPSEEK_API_KEY),
        "ollama": True,
        "local": True
    }.get(provider, False)
    
    # If explicit SIMULATION_MODE is enabled or requested provider is simulated
    if settings.SIMULATION_MODE or provider in ("simulated", "simulation"):
        is_simulated = True
        output_text = _generate_simulated_response(prompt_name, prompt_text)
        output_tokens = len(output_text) // 4
        logged_provider = f"{provider} (simulated)"
    else:
        # Real provider execution
        if has_credentials:
            try:
                output_text, input_tokens, output_tokens, raw_metadata = await _call_real_provider(provider, model, prompt_text)
                is_simulated = False
                success = True
                logged_provider = provider
            except Exception as e:
                error_detail = redact_secrets(str(e))
                logger.error("Real LLM call failed for provider %s: %s", provider, error_detail)
                
                if allow_fallback:
                    # Disclose explicit simulation fallback
                    success = False
                    is_simulated = True
                    is_fallback = True
                    fallback_reason = error_detail
                    logged_provider = f"{provider} (simulated fallback)"
                    output_text = _generate_simulated_response(prompt_name, prompt_text)
                    output_tokens = len(output_text) // 4
                else:
                    # Honest failure: do NOT silently mask with simulated text
                    success = False
                    is_simulated = False
                    is_fallback = False
                    logged_provider = provider
                    output_text = f"Provider Error ({provider}): {error_detail}"
                    output_tokens = 0
        else:
            # Provider missing credentials
            error_detail = f"Provider '{provider}' is not configured with an API key."
            if allow_fallback:
                success = False
                is_simulated = True
                is_fallback = True
                fallback_reason = error_detail
                logged_provider = f"{provider} (simulated fallback)"
                output_text = _generate_simulated_response(prompt_name, prompt_text)
                output_tokens = len(output_text) // 4
            else:
                success = False
                is_simulated = False
                is_fallback = False
                logged_provider = provider
                output_text = f"Provider Error ({provider}): {error_detail}"
                output_tokens = 0
                
    latency = time.time() - start_time
    
    # Calculate pricing (0 for simulated or failed calls)
    if not is_simulated and success:
        rates = TOKEN_PRICING.get(provider, {"input": 0.0, "output": 0.0})
        cost = ((input_tokens / 1000) * rates["input"]) + ((output_tokens / 1000) * rates["output"])
    else:
        cost = 0.0
        
    # Log execution to DB
    try:
        log_entry = ModelRouteLogDB(
            prompt_name=prompt_name,
            provider=logged_provider[:50],
            model_name=model,
            complexity=complexity,
            cost=round(cost, 6),
            latency=round(latency, 4),
            reliability_success=success
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
    except Exception as log_err:
        logger.error("Failed to persist model routing log to database: %s", str(log_err))

    return {
        "output": output_text,
        "provider": logged_provider,
        "model": model,
        "cost": round(cost, 6),
        "latency": round(latency, 4),
        "tokens": input_tokens + output_tokens,
        "success": success,
        "is_simulated": is_simulated,
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "error": error_detail,
        "metadata": raw_metadata
    }

async def get_router_diagnostics() -> Dict[str, Any]:
    """Retrieve operational status of all supported LLM providers and runtime routing configuration."""
    ollama_status = await OllamaProvider().check_health()
    return {
        "simulation_mode": settings.SIMULATION_MODE,
        "allow_simulation_fallback": settings.ALLOW_SIMULATION_FALLBACK,
        "default_provider": settings.DEFAULT_LLM_PROVIDER,
        "default_model": settings.DEFAULT_LLM_MODEL,
        "providers": {
            "ollama": {
                "configured": True,
                "base_url": settings.OLLAMA_BASE_URL,
                "reachable": ollama_status.get("reachable", False),
                "available_models": ollama_status.get("models", [])
            },
            "openai": {"configured": bool(settings.OPENAI_API_KEY)},
            "claude": {"configured": bool(settings.CLAUDE_API_KEY)},
            "gemini": {"configured": bool(settings.GEMINI_API_KEY)},
            "deepseek": {"configured": bool(settings.DEEPSEEK_API_KEY)}
        }
    }

def _generate_simulated_response(prompt_name: str, prompt_text: str) -> str:
    """Rich domain simulation engine providing realistic responses for all 12 modules in simulation mode."""
    prompt_lower = prompt_text.lower()
    
    # 0. Prompt Optimizer simulation
    if "promptoptimizer" in prompt_name.lower() or "meta-prompt optimization agent" in prompt_lower:
        return "You are an optimized agent system prompt. Verify inputs strictly, enforce JSON formatting rules, and handle error edge cases gracefully."

    # 0.1 Memory Summarizer simulation
    elif "memorysummarizer" in prompt_name.lower() or "summarize this memory" in prompt_lower:
        clean_text = prompt_text.replace("Summarize this memory into a single sentence under 100 characters:\n\n", "").strip()
        first_line = clean_text.split("\n")[0].split(".")[0].strip()
        return f"Summary: {first_line[:75]}."

    # 1. Goal / Task breaking simulation
    elif "breakdown" in prompt_lower or "break down" in prompt_lower or "learning roadmap" in prompt_lower:
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
    elif "extract entity" in prompt_lower or "relationship" in prompt_lower or "knowledge graph" in prompt_lower or "knowledgegraph" in prompt_name.lower():
        tokens = re.findall(r"\b[A-Za-z0-9_-]{3,20}\b", prompt_text)
        stop_words = {"analyze", "the", "text", "below", "and", "extract", "key", "entities", "concepts", "format", "output", "strictly", "json", "object", "nodes", "edges", "example", "response", "list", "matching", "relation", "weight", "between", "unique", "identifier", "display", "name", "category", "how", "they", "connect", "written_in", "part_of", "true", "false", "for", "with", "from"}
        keywords = [t for t in tokens if t.lower() not in stop_words]
        unique_kw = []
        for k in keywords:
            if k.lower() not in [u.lower() for u in unique_kw]:
                unique_kw.append(k)
        if len(unique_kw) >= 2:
            chosen = unique_kw[:4]
            nodes = [{"id": c.lower(), "label": c.capitalize(), "type": "Concept", "properties": {}} for c in chosen]
            edges = []
            for i in range(len(nodes) - 1):
                edges.append({
                    "source_id": nodes[i]["id"],
                    "target_id": nodes[i+1]["id"],
                    "relation": "relates_to",
                    "weight": 0.8
                })
            import json as _json
            return _json.dumps({"nodes": nodes, "edges": edges})
        else:
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
    elif "evaluate response" in prompt_lower:
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

