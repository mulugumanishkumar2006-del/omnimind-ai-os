import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.database import engine, Base, SessionLocal
from backend.app.models.database_models import PromptDB
from backend.app.api.endpoints import (
    memory_router, task_router, kg_router, agent_router,
    prompt_router, meeting_router, learning_router, router_router,
    security_router, analytics_router, improvement_router, search_router
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API services for the OmniMind AI OS platform.",
    version="1.0.0"
)

# CORS configurations
allowed_origins = getattr(settings, "CORS_ORIGINS", [
    "http://localhost:8501", "http://127.0.0.1:8501",
    "http://localhost:8000", "http://127.0.0.1:8000"
])
has_wildcard = "*" in allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=not has_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request payload size boundary protection middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_upload_size = max_upload_size

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_upload_size:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Payload too large. Maximum allowed size is {self.max_upload_size} bytes."}
                    )
            except (ValueError, TypeError):
                pass
        return await call_next(request)

app.add_middleware(
    RequestSizeLimitMiddleware,
    max_upload_size=getattr(settings, "MAX_REQUEST_SIZE_BYTES", 10 * 1024 * 1024)
)

# Global unhandled exception handler preventing internal traceback / path leakage
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    logger.error("Unhandled internal server exception at %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."}
    )

# Mount Routers
api_prefix = settings.API_V1_STR
app.include_router(memory_router, prefix=api_prefix)
app.include_router(task_router, prefix=api_prefix)
app.include_router(kg_router, prefix=api_prefix)
app.include_router(agent_router, prefix=api_prefix)
app.include_router(prompt_router, prefix=api_prefix)
app.include_router(meeting_router, prefix=api_prefix)
app.include_router(learning_router, prefix=api_prefix)
app.include_router(router_router, prefix=api_prefix)
app.include_router(security_router, prefix=api_prefix)
app.include_router(analytics_router, prefix=api_prefix)
app.include_router(improvement_router, prefix=api_prefix)
app.include_router(search_router, prefix=api_prefix)


@app.get("/health", tags=["System"])
def health_check():
    """Retrieve system health status."""
    return {
        "status": "healthy",
        "app_name": settings.PROJECT_NAME,
        "mode": "simulation" if settings.SIMULATION_MODE else "production"
    }

# Serving the Vanilla HTML/JS frontend
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

@app.get("/")
def read_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

# Mount all other static files (style.css, app.js) at the root
app.mount("/", StaticFiles(directory=frontend_dir), name="static")


def seed_database():
    """Seeds the database with default prompt templates on startup."""
    db = SessionLocal()
    try:
        existing_prompts = db.query(PromptDB).count()
        if existing_prompts == 0:
            logger.info("Database is empty. Seeding default agent prompts into Prompt Studio.")
            
            default_prompts = [
                {
                    "name": "PlannerAgent",
                    "template": "You are a specialized Planner Agent. Given a goal, create a step-by-step roadmap to achieve it. Break it down into discrete requirements.",
                },
                {
                    "name": "ResearcherAgent",
                    "template": "You are a Researcher Agent. Analyze technical concepts and documentation, returning structured blueprints and citations.",
                },
                {
                    "name": "CodingAgent",
                    "template": "You are a Coding Agent. Given code blueprints and specs, generate high-quality Python or frontend code implementation blocks.",
                },
                {
                    "name": "ReviewerAgent",
                    "template": "You are a Reviewer Agent. Check code for style guidelines, performance bottlenecks, and validation rules.",
                },
                {
                    "name": "MeetingIntelligenceAgent",
                    "template": "You are a Meeting Intelligence Agent. Extract key summaries, team decisions, and actionable task assignments from meeting transcripts.",
                },
                {
                    "name": "KnowledgeGraphAgent",
                    "template": "You are a Knowledge Graph Extraction Agent. Extract entity nodes (concepts, tools, tech) and edges (relations) from text queries.",
                }
            ]
            
            for item in default_prompts:
                p = PromptDB(
                    name=item["name"],
                    template=item["template"],
                    version=1,
                    metrics={"avg_cost": 0.0, "avg_latency": 0.0, "avg_rating": 5.0},
                    is_active_a=True,
                    is_active_b=False
                )
                db.add(p)
            db.commit()
            logger.info("Successfully seeded default prompts.")
    except Exception as e:
        logger.error("Failed to seed database: %s", str(e))
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    """Trigger DB migrations and seeding on FastAPI launch."""
    logger.info("Initializing SQLite database tables.")
    Base.metadata.create_all(bind=engine)
    seed_database()
