import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    PROJECT_NAME: str = "OmniMind AI OS"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:////tmp/omnimind.db" if os.getenv("VERCEL") else "sqlite:///./omnimind.db"
    
    # Redis Cache
    REDIS_URL: Optional[str] = None
    
    # ChromaDB
    CHROMA_DB_DIR: str = "/tmp/chroma_db" if os.getenv("VERCEL") else "./chroma_db"
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "")
    CLAUDE_API_KEY: Optional[str] = os.getenv("CLAUDE_API_KEY", "")
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY", "")
    
    # Ollama Local LLM Configuration
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_TIMEOUT: float = float(os.getenv("OLLAMA_TIMEOUT", "60.0"))
    
    # Model configuration
    DEFAULT_LLM_PROVIDER: Optional[str] = os.getenv("DEFAULT_LLM_PROVIDER", None)
    DEFAULT_LLM_MODEL: Optional[str] = os.getenv("DEFAULT_LLM_MODEL", None)
    
    # Embedding config
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    
    # Simulation Settings
    # If True, we generate mock responses for LLM operations if keys are missing
    SIMULATION_MODE: bool = True
    ALLOW_SIMULATION_FALLBACK: bool = False

    # Multi-Agent Workflow Execution Policy
    MAX_AGENT_STEPS: int = int(os.getenv("MAX_AGENT_STEPS", "10"))
    MAX_AGENT_RETRIES: int = int(os.getenv("MAX_AGENT_RETRIES", "2"))

    # Security & Boundary Protection
    CORS_ORIGINS: List[str] = [
        origin.strip() for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8501,http://127.0.0.1:8501,http://localhost:8000,http://127.0.0.1:8000"
        ).split(",") if origin.strip()
    ]
    MAX_REQUEST_SIZE_BYTES: int = int(os.getenv("MAX_REQUEST_SIZE_BYTES", str(10 * 1024 * 1024)))  # 10 MB
    MAX_INPUT_CHAR_LENGTH: int = int(os.getenv("MAX_INPUT_CHAR_LENGTH", "50000"))

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore"
    )

settings = Settings()

