import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "OmniMind AI OS"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:///./omnimind.db"
    
    # Redis Cache
    REDIS_URL: Optional[str] = None
    
    # ChromaDB
    CHROMA_DB_DIR: str = "./chroma_db"
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "")
    CLAUDE_API_KEY: Optional[str] = os.getenv("CLAUDE_API_KEY", "")
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY", "")
    
    # Embedding config
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    
    # Simulation Settings
    # If True, we generate mock responses for LLM operations if keys are missing
    SIMULATION_MODE: bool = True

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
