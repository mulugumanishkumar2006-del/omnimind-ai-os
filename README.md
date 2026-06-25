# OmniMind AI OS

OmniMind AI OS is a production-grade AI Operating System designed as an intelligent unified workspace. It integrates semantic memory vaults, collaborative hierarchical task planner engines, real-time interactive knowledge graph discovery, dynamic multi-agent orchestrators, and prompt versioning systems into a cohesive application.

The platform is designed to run **out-of-the-box** using automatic database adapters (SQLite), memory vector fallback stores (in-memory/NumPy cosine similarity if ChromaDB is unavailable), caching abstractions (in-memory if Redis is absent), and a robust **Simulation Mode** (which mock-simulates LLM responses if API keys are not supplied, allowing instant portfolio evaluations).

---

## Key Modules

1. **Memory Engine**: Manages Long-Term, Short-Term, Session, and Semantic Memories. Automatically grades content importance and indexes them into vector storage.
2. **Task Intelligence System**: Decomposes high-level goals into step-by-step roadmaps, projects, and learning plans with automatic effort estimations and progress tracking.
3. **Knowledge Graph Engine**: Discovers entities and relationships in user notes and transcripts, rendering them as an interactive VisJS network graph.
4. **Multi-Agent Framework**: Orchestrates Planner, Researcher, Coder, Reviewer, Security, and Analytics agents to execute complex objectives.
5. **Prompt Studio**: Houses prompt version control, variant editing, and side-by-side A/B comparison metrics.
6. **AI Search Engine**: Combines SQL keyword queries and vector semantic queries to yield citation-backed results.
7. **Meeting Intelligence**: Simulates transcription, aggregates decisions, and auto-spawns action items as active task objectives.
8. **Learning Tracker**: Graphs skills acquisitions, benchmarks competencies, and auto-injects targeted curricula.
9. **Dynamic Model Router**: Allocates API queries to Claude, OpenAI, Gemini, or DeepSeek based on complexity, cost, and speed profiles.
10. **Operations Center (Ops)**: Observes system latency distributions (P95), success rates, cost aggregations, and model usage distributions.
11. **Security Center**: Audits inputs for jailbreaks, prompt injections, and sensitive PII exposures.
12. **Self-Improvement Engine**: Captures failure logs (hallucinations/low scores), executes meta-prompt optimizations, and bumps configurations in the Prompt Studio.

---

## Technical Architecture

```mermaid
graph TD
    User[Streamlit Frontend] <--> API[FastAPI Backend]
    
    subgraph Core Engines
        API --> Memory[Memory Engine]
        API --> Task[Task Intelligence]
        API --> Graph[Knowledge Graph]
        API --> Agent[Agent Framework]
        API --> Router[Model Router]
    end

    subgraph Adapters & Data
        Memory --> SQLite[(SQLite / PG Database)]
        Memory --> VecStore[(ChromaDB / NumPy Fallback)]
        Agent --> Cache[(In-Memory Cache / Redis)]
    end

    subgraph Routing Targets
        Router --> Sim[Simulation Engine]
        Router --> GPT[OpenAI API]
        Router --> Claude[Claude API]
        Router --> Gemini[Gemini API]
    end
```

---

## Getting Started

### Prerequisites
- Python 3.10 or 3.11
- pip (Python package installer)

### Quick Start (Local Setup)

1. Clone the repository and navigate to the project directory:
   ```bash
   cd OmniMind-AI-OS
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Boot up the entire OS using the master orchestrator runner script:
   ```bash
   python run.py
   ```
   This command starts the FastAPI server on `http://127.0.0.1:8000` and launches the Streamlit client on `http://127.0.0.1:8501`.

4. Open your browser and navigate to `http://127.0.0.1:8501`.

---

## Production Configurations (Optional)

To switch the system from local fallback databases and Simulation Mode to production endpoints:

1. Create a `.env` file in the root folder or configure environment variables:
   ```env
   # Database (defaults to local sqlite)
   DATABASE_URL=postgresql://user:pass@host:5432/dbname
   
   # Caching (defaults to local in-memory)
   REDIS_URL=redis://localhost:6379/0
   
   # API Keys (Provide keys to disable Simulation Mode for that provider)
   OPENAI_API_KEY=sk-proj-...
   CLAUDE_API_KEY=sk-ant-...
   GEMINI_API_KEY=AIzaSy...
   DEEPSEEK_API_KEY=sk-...
   ```

2. Alternatively, input API keys directly in the **System Configurations** panel located in the Streamlit client sidebar.

---

## Containerized Deployment (Docker)

To run the containerized multi-tier stack locally:

```bash
docker-compose up --build
```
This boots:
- **FastAPI backend** container on port `8000`
- **Streamlit frontend** container on port `8501`
- Persistent docker volumes for the local vector store cache.

---

## API Documentation

FastAPI automatically serves interactive Swagger documentation:
- **Interactive docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **JSON OpenAPI Schema**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

---

## Verification & Testing

Verify system dependencies, schema integrity, and end-to-end service orchestration:
```bash
python verify_services.py
```
This runs programmatic test routines on memory semantic searches, security scans, agent pipelines, and database relations, ensuring full system stability.
