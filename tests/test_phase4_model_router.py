import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.database_models import Base, ModelRouteLogDB
from backend.app.services.model_router import (
    execute_llm_call,
    get_router_diagnostics,
    redact_secrets,
    OllamaProvider,
    OpenAIProvider,
    ClaudeProvider,
    GeminiProvider,
    DeepSeekProvider,
    route_request,
)
from backend.app.core.config import settings

# In-memory SQLite session for tests
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

# ---------------------------------------------------------------------------
# 1. Secret Redaction Tests
# ---------------------------------------------------------------------------
def test_secret_redaction_generic_patterns():
    # OpenAI sk- style
    err_openai = "Failed connecting to api.openai.com with key sk-proj-1234567890abcdef1234567890"
    redacted = redact_secrets(err_openai)
    assert "sk-proj-1234567890abcdef1234567890" not in redacted
    assert "[REDACTED_API_KEY]" in redacted

    # Anthropic sk-ant- style
    err_claude = "401 Unauthorized: Bearer sk-ant-api03-abcdef12345678901234567890"
    redacted_c = redact_secrets(err_claude)
    assert "sk-ant-api03-abcdef12345678901234567890" not in redacted_c
    assert "[REDACTED_API_KEY]" in redacted_c

    # Google Gemini key in URL query param
    err_gemini = "400 Client Error: https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=AIzaSyD-1234567890abcdefghijklmnopqrstuv"
    redacted_g = redact_secrets(err_gemini)
    assert "AIzaSyD-1234567890abcdefghijklmnopqrstuv" not in redacted_g
    assert "[REDACTED_API_KEY]" in redacted_g

def test_secret_redaction_configured_keys():
    with patch.object(settings, "OPENAI_API_KEY", "super-secret-custom-key-xyz"):
        err = "Error contacting server with key super-secret-custom-key-xyz at endpoint"
        redacted = redact_secrets(err)
        assert "super-secret-custom-key-xyz" not in redacted
        assert "[REDACTED_API_KEY]" in redacted

# ---------------------------------------------------------------------------
# 2. Model & Complexity Selection Tests
# ---------------------------------------------------------------------------
def test_model_selection_complexity_routing():
    # With CLAUDE_API_KEY set, high complexity routes to claude
    with patch.object(settings, "CLAUDE_API_KEY", "sk-ant-test"), patch.object(settings, "DEFAULT_LLM_PROVIDER", None):
        p_high, m_high = route_request("high")
        assert p_high == "claude"
        assert "claude" in m_high

    # With GEMINI_API_KEY set, medium complexity routes to gemini
    with patch.object(settings, "GEMINI_API_KEY", "AIzaSyTest"), patch.object(settings, "DEFAULT_LLM_PROVIDER", None):
        p_med, m_med = route_request("medium")
        assert p_med == "gemini"

    # With no API keys, routes to ollama
    with patch.object(settings, "CLAUDE_API_KEY", None), patch.object(settings, "OPENAI_API_KEY", None), \
         patch.object(settings, "GEMINI_API_KEY", None), patch.object(settings, "DEEPSEEK_API_KEY", None), \
         patch.object(settings, "DEFAULT_LLM_PROVIDER", None):
        p_def, m_def = route_request("low")
        assert p_def == "ollama"

def test_model_selection_default_provider_override():
    with patch.object(settings, "DEFAULT_LLM_PROVIDER", "ollama"), patch.object(settings, "DEFAULT_LLM_MODEL", "phi3:mini"):
        p, m = route_request("high")
        assert p == "ollama"
        assert m == "phi3:mini"

# ---------------------------------------------------------------------------
# 3. Provider Adapter Unit Tests (Mocked HTTP responses)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ollama_provider_success():
    provider = OllamaProvider()
    fake_response = {
        "message": {"content": "Ollama generated unit test response"},
        "prompt_eval_count": 15,
        "eval_count": 25,
        "total_duration": 450_000_000
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        content, in_tok, out_tok, meta = await provider.call("llama3.2:3b", "Hello Ollama")
        
        assert content == "Ollama generated unit test response"
        assert in_tok == 15
        assert out_tok == 25
        assert meta["eval_count"] == 25

@pytest.mark.asyncio
async def test_ollama_health_check_reachable():
    provider = OllamaProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3.2:3b"}, {"name": "phi:latest"}]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = await provider.check_health()
        assert health["reachable"] is True
        assert "llama3.2:3b" in health["models"]

@pytest.mark.asyncio
async def test_ollama_health_check_unreachable():
    provider = OllamaProvider()
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        health = await provider.check_health()
        assert health["reachable"] is False
        assert health["models"] == []

@pytest.mark.asyncio
async def test_openai_provider_success():
    provider = OpenAIProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "OpenAI generated answer"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(settings, "OPENAI_API_KEY", "sk-test-valid-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            content, in_tok, out_tok, _ = await provider.call("gpt-4o", "Hello OpenAI")
            assert content == "OpenAI generated answer"
            assert in_tok == 10
            assert out_tok == 20

@pytest.mark.asyncio
async def test_claude_provider_success():
    provider = ClaudeProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"text": "Claude generated response"}],
        "usage": {"input_tokens": 12, "output_tokens": 30}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(settings, "CLAUDE_API_KEY", "sk-ant-test-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            content, in_tok, out_tok, _ = await provider.call("claude-3-5-sonnet", "Hello Claude")
            assert content == "Claude generated response"
            assert in_tok == 12
            assert out_tok == 30

@pytest.mark.asyncio
async def test_gemini_provider_success():
    provider = GeminiProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Gemini generated text"}]}}],
        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 18}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(settings, "GEMINI_API_KEY", "AIzaSyTestKey"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            content, in_tok, out_tok, _ = await provider.call("gemini-1.5-flash", "Hello Gemini")
            assert content == "Gemini generated text"
            assert in_tok == 8
            assert out_tok == 18

@pytest.mark.asyncio
async def test_deepseek_provider_success():
    provider = DeepSeekProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "DeepSeek code answer"}}],
        "usage": {"prompt_tokens": 14, "completion_tokens": 28}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(settings, "DEEPSEEK_API_KEY", "sk-dsk-test-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            content, in_tok, out_tok, _ = await provider.call("deepseek-chat", "Hello DeepSeek")
            assert content == "DeepSeek code answer"
            assert in_tok == 14
            assert out_tok == 28

# ---------------------------------------------------------------------------
# 4. Simulation Mode Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simulation_mode_honest_labeling(db_session):
    with patch.object(settings, "SIMULATION_MODE", True):
        res = await execute_llm_call(
            prompt_name="TestSimulation",
            prompt_text="What is the speed of light?",
            db=db_session
        )
        assert res["success"] is True
        assert res["is_simulated"] is True
        assert res["is_fallback"] is False
        assert "(simulated)" in res["provider"]
        assert len(res["output"]) > 0

# ---------------------------------------------------------------------------
# 5. Honest Failure vs Explicit Fallback Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_real_provider_failure_honest_no_fallback(db_session):
    """When a real provider fails and fallback is disabled, an honest error must be returned."""
    with patch.object(settings, "SIMULATION_MODE", False):
        with patch.object(settings, "ALLOW_SIMULATION_FALLBACK", False):
            with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused to 127.0.0.1:11434")):
                res = await execute_llm_call(
                    prompt_name="TestHonestFailure",
                    prompt_text="Test prompt",
                    db=db_session,
                    provider_override="ollama",
                    model_override="phi:latest"
                )
                assert res["success"] is False
                assert res["is_simulated"] is False
                assert res["is_fallback"] is False
                assert "Provider Error (ollama)" in res["output"]
                assert res["error"] is not None

@pytest.mark.asyncio
async def test_real_provider_failure_explicit_fallback(db_session):
    """When a real provider fails and fallback is explicitly allowed, fallback must be disclosed."""
    with patch.object(settings, "SIMULATION_MODE", False):
        with patch.object(settings, "ALLOW_SIMULATION_FALLBACK", True):
            with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")):
                res = await execute_llm_call(
                    prompt_name="TestFallbackDisclosed",
                    prompt_text="Test prompt for fallback",
                    db=db_session,
                    provider_override="ollama",
                    model_override="phi:latest"
                )
                assert res["success"] is False
                assert res["is_simulated"] is True
                assert res["is_fallback"] is True
                assert "simulated fallback" in res["provider"]
                assert res["fallback_reason"] is not None
                assert "timed out" in res["fallback_reason"].lower()

@pytest.mark.asyncio
async def test_missing_credentials_honest_error(db_session):
    """Calling an unconfigured remote provider without fallback returns an honest error."""
    with patch.object(settings, "SIMULATION_MODE", False):
        with patch.object(settings, "ALLOW_SIMULATION_FALLBACK", False):
            with patch.object(settings, "OPENAI_API_KEY", ""):
                res = await execute_llm_call(
                    prompt_name="TestMissingCreds",
                    prompt_text="Prompt without API key",
                    db=db_session,
                    provider_override="openai",
                    model_override="gpt-4o"
                )
                assert res["success"] is False
                assert res["is_simulated"] is False
                assert "not configured with an API key" in res["output"]

# ---------------------------------------------------------------------------
# 6. Database Logging Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_router_logs_persisted_to_db(db_session):
    with patch.object(settings, "SIMULATION_MODE", True):
        res = await execute_llm_call(
            prompt_name="DBLoggingTest",
            prompt_text="Persist this log",
            db=db_session
        )
        logs = db_session.query(ModelRouteLogDB).filter(ModelRouteLogDB.prompt_name == "DBLoggingTest").all()
        assert len(logs) == 1
        assert logs[0].prompt_name == "DBLoggingTest"
        assert logs[0].reliability_success is True

# ---------------------------------------------------------------------------
# 7. Router Diagnostics Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_router_diagnostics():
    mock_health = {"reachable": True, "models": ["phi:latest", "llama3.2:3b"]}
    with patch("backend.app.services.model_router.OllamaProvider.check_health", new_callable=AsyncMock) as mock_chk:
        mock_chk.return_value = mock_health
        diag = await get_router_diagnostics()
        assert "providers" in diag
        assert diag["providers"]["ollama"]["reachable"] is True
        assert "phi:latest" in diag["providers"]["ollama"]["available_models"]
        assert "openai" in diag["providers"]

# ---------------------------------------------------------------------------
# 8. Optional Manual / Live Ollama Integration Test
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_ollama_integration_if_available(db_session):
    """Optional manual integration test that runs against a live Ollama server if reachable."""
    provider = OllamaProvider()
    health = await provider.check_health()
    if not health.get("reachable", False) or not health.get("models"):
        pytest.skip("Local Ollama daemon is not reachable or has no models installed.")

    available_models = health["models"]
    # Pick lightweight model for fast local verification
    fast_candidates = ["phi:latest", "phi3:mini", "llama3.2:3b", "gemma3:4b"]
    test_model = next((m for m in fast_candidates if m in available_models), available_models[0])
    
    with patch.object(settings, "SIMULATION_MODE", False):
        with patch.object(settings, "ALLOW_SIMULATION_FALLBACK", False):
            res = await execute_llm_call(
                prompt_name="LiveOllamaTest",
                prompt_text="Reply with 'PING_OK'.",
                db=db_session,
                provider_override="ollama",
                model_override=test_model
            )
            assert res["success"] is True
            assert res["is_simulated"] is False
            assert res["provider"] == "ollama"
            assert res["model"] == test_model
            assert len(res["output"]) > 0
            assert res["tokens"] > 0
