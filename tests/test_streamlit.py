import os
import sys
import pytest

def test_streamlit_widgets_module_import():
    """Verify that frontend.components.widgets can be imported and contains expected functions."""
    from frontend.components import widgets
    
    expected_renderers = [
        "render_memory_vault",
        "render_task_workspace",
        "render_graph_viewer",
        "render_agent_viewer",
        "render_prompt_studio",
        "render_search_interface",
        "render_meeting_room",
        "render_learning_dashboard",
        "render_router_dashboard",
        "render_security_dashboard",
        "render_improvement_dashboard",
        "render_analytics_dashboard",
    ]
    
    for renderer in expected_renderers:
        assert hasattr(widgets, renderer), f"Widget module is missing function '{renderer}'."
        assert callable(getattr(widgets, renderer))

def test_frontend_app_import():
    """Verify that frontend.app can be imported cleanly."""
    import frontend.app
    assert hasattr(frontend.app, "BACKEND_URL")

def test_backend_url_environment_override(monkeypatch):
    """Verify that API_BASE_URL env variable overrides the default URL."""
    custom_url = "http://backend-service:8000/api/v1"
    monkeypatch.setenv("API_BASE_URL", custom_url)
    
    # Reload frontend.app to test env var pickup
    import importlib
    import frontend.app
    importlib.reload(frontend.app)
    
    assert frontend.app.BACKEND_URL == custom_url
    
    # Restore default
    monkeypatch.delenv("API_BASE_URL", raising=False)
    importlib.reload(frontend.app)
    assert frontend.app.BACKEND_URL == "http://127.0.0.1:8000/api/v1"
