import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

def test_fastapi_app_instance():
    """Verify that the FastAPI application can be imported and initialized."""
    assert isinstance(app, FastAPI)
    assert app.title == "OmniMind AI OS"

def test_health_endpoint(client):
    """Verify that the /health endpoint returns healthy status and metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "app_name" in data
    assert "mode" in data

def test_api_docs_availability(client):
    """Verify interactive Swagger documentation and OpenAPI schema are accessible."""
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
    assert "swagger" in docs_resp.text.lower() or "html" in docs_resp.text.lower()

    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    openapi_data = openapi_resp.json()
    assert "openapi" in openapi_data
    assert "/health" in openapi_data["paths"]

def test_html_interface_and_assets(client):
    """Verify that the HTML single-page frontend and static assets are served properly."""
    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert "OmniMind" in index_resp.text

    css_resp = client.get("/style.css")
    assert css_resp.status_code == 200

    js_resp = client.get("/app.js")
    assert js_resp.status_code == 200

def test_api_v1_endpoints_mounted(client):
    """Verify that API v1 endpoints are registered and respond."""
    resp = client.get("/api/v1/memories/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
