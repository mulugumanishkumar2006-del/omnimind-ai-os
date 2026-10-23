# OmniMind AI OS — Phase 2: Core Functionality Audit Report

## 1. Executive Summary

This document presents a comprehensive audit of all 12 core backend modules and 5 critical workflows in OmniMind AI OS. Every module has been inspected against its actual implementation in `backend/app/`, evaluating API endpoints, service functions, database models, external dependencies, real vs. simulated behaviors, and regression vulnerability.

---

## 2. Comprehensive Module Audit Table

| Module | Existing Functionality | Verified Working Behavior | Missing or Broken Behavior | Simulated / Hardcoded Behavior | Tests Required | Priority |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Memory Engine** | CRUD operations, semantic vector storage, importance scoring, auto-summarization, timeline query. | Memory insertion, SQLite persistence, vector indexing, timeline chronological ordering. | 1. ChromaDB `collection.add()` raises `DuplicateIDError` on memory updates, knocking Chroma offline.<br>2. `PUT /memories/{id}` expects `content` as query parameter rather than JSON request body.<br>3. Empty/whitespace content accepted.<br>4. Empty search query returns arbitrary matches. | Memory summarization (>300 chars) returns generic boilerplate in simulation mode rather than summary. | Add, retrieve, search, edit, delete, restart persistence, empty input rejection. | **HIGH** |
| **2. Semantic & Hybrid Search** | Cross-table retrieval across memories, tasks, meetings, and knowledge nodes with citations. | Multi-source querying, collection filtering (`memory`, `task`, `meeting`, `graph`), citation compilation. | 1. Empty/whitespace query returns arbitrary records from all tables instead of empty results.<br>2. Invalid collection filter fails silently. | Static confidence scores for non-vector records (Task=0.8, Meeting=0.75, Graph=0.85). | Multi-entity search, empty query validation, citation integrity. | **MEDIUM** |
| **3. Task Intelligence** | Task & goal creation, recursive progress recalculation, goal breakdown into subtasks, action suggestions. | Task hierarchy building, progress propagation from children to parents, action suggestions filtering. | 1. `POST /{id}/breakdown` returns `[]` with HTTP 200 on non-existent task ID instead of 404.<br>2. `PUT /{id}/progress` takes query params instead of JSON body; resetting subtasks to 0.0 leaves parent status unchanged.<br>3. Empty title accepted without validation. | Goal breakdown returns hardcoded 4 AI Engineer tasks or 3 generic tasks in simulation. | Goal creation, breakdown, progress update, parent progress aggregation, 404 on missing ID. | **HIGH** |
| **4. Knowledge Graph** | Entity & relation extraction, VisJS graph data generation, interactive HTML view with NetworkX degree sizing. | Graph nodes and edges storage, graph JSON serialization, NetworkX degree computation. | 1. Intra-batch duplicate node IDs crash `db.commit()` with `IntegrityError` (nodes queried before commit).<br>2. Repeated extraction submissions can duplicate edges if multiple identical edges exist in response.<br>3. Empty content extracts hardcoded tech nodes. | Simulation mode returns fixed 4 nodes (python, langgraph, chromadb, sqlite) regardless of input text. | Entity extraction, graph retrieval, repeated submissions duplicate prevention, intra-batch duplicate handling. | **HIGH** |
| **5. Multi-Agent Framework** | Sequential 7-agent collaboration pipeline, session tracking, communication graph visualization. | Session creation, step logging, communication graph compilation, session history retrieval. | 1. **Outputs are NOT passed between agents**: CodingAgent prompt does not contain Researcher findings; ReviewerAgent does not receive Coder's code.<br>2. **Fabricated success**: Pipeline unconditionally marks `status="success"` even if LLM fails or security scan detects jailbreak.<br>3. Synchronous `time.sleep()` blocks the asyncio event loop. | Simulated step execution and canned agent messages. | Agent execution trace, downstream output passing, honest failure reporting on security flags or LLM failures. | **HIGH** |
| **6. Model Router** | Dynamic routing by complexity, real API integration (OpenAI, Gemini, Claude, DeepSeek), cost & latency tracking, simulation fallback. | Complexity heuristics, provider env override, DB logging, simulation labeling (`is_simulated=True`, provider labeled `(simulated)`). | 1. When real provider call fails, error details are discarded without reporting reason.<br>2. Provider `"local"` raises `NotImplementedError` in `_call_real_provider`.<br>3. Simulator responses for `MemorySummarizer` and `PromptOptimizerAgent` return wrong formats. | Full simulation when API keys are absent or `SIMULATION_MODE=True`. | Real provider failure handling, error detail propagation, simulation transparency. | **HIGH** |
| **7. Prompt Studio** | Prompt versioning, prompt creation, prompt listing, A/B side-by-side prompt comparison. | Prompt insertion, automatic version incrementation per prompt name, side-by-side comparison execution. | 1. Missing `GET /prompts/{id}` or active version lookup.<br>2. Missing endpoints to activate version for A/B testing (`is_active_a`, `is_active_b`).<br>3. Empty prompt name/template accepted without validation. | Simulation mode executes mock comparison. | Prompt creation, version incrementation, comparison endpoint, empty input validation. | **MEDIUM** |
| **8. Security Scanner & PII** | Regex-based PII detection (Email, Credit Card, SSN, API Keys), jailbreak/injection keyword scanning, threat logging, data scrubbing. | PII detection, jailbreak detection, safety scoring, threat DB logging, text scrubbing. | 1. `scrub_sensitive_data` service function has NO corresponding API endpoint (`POST /security/scrub`).<br>2. Empty input text lacks validation. | None (deterministic regex rules). | API scan & scrub endpoints, threat logging, clean vs malicious text detection. | **MEDIUM** |
| **9. Meeting Intelligence** | Meeting transcript processing, action item extraction, decision tracking, auto-spawning tasks and memories. | Meeting DB record creation, automatic cross-linking to Memory Vault, action item task generation. | 1. `int(item.get("days_to_complete"))` crashes on strings like `"3 days"`.<br>2. Missing `GET /meetings/{id}` endpoint.<br>3. Empty transcript/title lacks validation. | Returns hardcoded meeting summary about vector store and SQLite in simulation mode. | Transcript processing, memory creation, task generation, string days tolerance. | **MEDIUM** |
| **10. Learning Tracker** | Skill progress logging, career path recommendation, automated learning roadmap generation under tasks. | Skill progress upsert, ordered skill retrieval, learning plan parent goal and milestones task generation. | 1. `generate_learning_roadmap` returns 400 without specific error message on invalid JSON.<br>2. Empty skill name lacks validation. | Returns hardcoded MLOps career recommendation in simulation mode. | Skill upsert, roadmap generation with task linkage, career recommendation fetch. | **LOW** |
| **11. Self-Improvement System** | Failure case logging, automated prompt optimization from failure cases, optimization history auditing. | Failure case logging, version bump on optimized prompt, failure record linking. | 1. **Simulator collision**: `PromptOptimizerAgent` prompt matches `"failure analysis"`, returning evaluation JSON instead of prompt template, corrupting `PromptDB.template`.<br>2. `POST /logs/{id}/optimize` returns 400 instead of 404 on missing log ID. | Simulation returns mock prompt rewrite. | Failure logging, prompt optimization workflow, template validity check, 404 on missing ID. | **HIGH** |
| **12. Operations & Analytics** | Aggregated system metrics: total calls, latency (avg, p95), total cost, reliability rate, model distribution, active tasks. | Summary statistics computation, model distribution mapping, active task count. | 1. Unbounded `.all()` queries in memory for model logs.<br>2. Empty database edge cases in latency sorting.<br>3. `AnalyticsMetricDB` table is completely unused. | Hardcoded `active_users: 1`. | Dashboard metric structure, edge case handling with empty tables. | **LOW** |

---

## 3. Workflow Audit & Failure Analysis

### Workflow 1: Memory Engine Workflow
- **Issue 1**: ChromaDB `add_document` calls `collection.add(...)`. On updates, Chroma raises `DuplicateIDError`. The catch block permanently sets `_use_chroma = False` for all subsequent operations.
  - **Resolution**: Use `collection.upsert(...)` instead of `collection.add(...)`.
- **Issue 2**: `PUT /api/v1/memories/{id}` defines `content: str` as an endpoint argument without a Pydantic model or `Body(...)`, forcing callers to pass content as a URL query string (`?content=...`).
  - **Resolution**: Create `MemoryUpdate` schema and accept JSON body while supporting query string fallback.
- **Issue 3**: Empty or whitespace content creates invalid memory records.
  - **Resolution**: Add string validation checking `content.strip()`.

### Workflow 2: Task Intelligence Workflow
- **Issue 1**: `POST /api/v1/tasks/{id}/breakdown` returns HTTP 200 with `[]` on missing task IDs.
  - **Resolution**: Raise `HTTPException(status_code=404, detail="Task not found")`.
- **Issue 2**: `PUT /api/v1/tasks/{id}/progress` expects query params. Parent status does not reset to `pending` when all children have `progress == 0.0`.
  - **Resolution**: Support `TaskProgressUpdate` schema, and update status logic to set `parent.status = "pending"` when `parent.progress == 0.0`.

### Workflow 3: Knowledge Graph Workflow
- **Issue 1**: Submitting text with repeated entities in the same extraction batch causes `IntegrityError: UNIQUE constraint failed: graph_nodes.id` because uncommitted nodes in the active loop cannot be found by `db.query(GraphNodeDB)`.
  - **Resolution**: Track pending node IDs in a local set during the loop before committing.
- **Issue 2**: Repeated text submissions in simulation mode always extract the exact same 4 nodes (`python`, `langgraph`, `chromadb`, `sqlite`).
  - **Resolution**: Support dynamic simulated extraction based on tokens present in the input text when in simulation mode.

### Workflow 4: Model Routing Workflow
- **Issue 1**: When real API providers fail (e.g. 401 Unauthorized or network down), the router catches the exception and returns `success=False` but drops the error details.
  - **Resolution**: Add `"error"` and `"error_detail"` fields to the response payload for honest diagnostics.
- **Issue 2**: Provider `"local"` raises `NotImplementedError` if invoked in real execution.
  - **Resolution**: Provide graceful handling or Ollama HTTP client support.

### Workflow 5: Multi-Agent Workflow
- **Issue 1**: Output passing between agents is broken: CodingAgent only receives `{goal}` without Researcher's findings; ReviewerAgent only receives `{goal}` without Coder's generated code.
  - **Resolution**: Chain agent outputs: Pass Planner roadmap to Researcher; pass Researcher context to Coder; pass Coder output to Reviewer; pass Reviewer notes and code to Security scanner.
- **Issue 2**: Pipeline unconditionally sets `session_entry.status = "success"` even if an agent call fails or SecurityAgent flags a vulnerability.
  - **Resolution**: Track execution success and flag `status = "failed"` if any critical step fails or if security scan finds high-risk threats.
- **Issue 3**: Synchronous `time.sleep()` blocks the asyncio event loop.
  - **Resolution**: Replace with `await asyncio.sleep(...)` with 0 delay in testing mode.

### Workflow 6: Self-Improvement System
- **Issue 1**: In `optimize_prompt_from_failure`, the prompt contains `"Failure Analysis Context:"`, matching the simulator's `"failure analysis"` branch which returns evaluation JSON instead of prompt text, corrupting `PromptDB.template`.
  - **Resolution**: Add dedicated simulator handling for `PromptOptimizerAgent` returning an improved prompt template string.
- **Issue 2**: `POST /logs/{id}/optimize` returns 400 instead of 404 when ID does not exist.
  - **Resolution**: Return HTTP 404 when failure log is not found.

### Workflow 7: Security Center
- **Issue 1**: `scrub_sensitive_data` is implemented in the service layer but missing an API endpoint.
  - **Resolution**: Expose `POST /api/v1/security/scrub` with request and response schemas.

---

## 4. Priority Implementation Plan

1. **Defect 1 (Critical - Multi-Agent Framework)**: Pass outputs downstream between agents; report honest failure status on security threats or LLM errors; replace blocking sleep with async sleep.
2. **Defect 2 (Critical - Knowledge Graph Engine)**: Fix intra-batch duplicate node crashes via pending node set; prevent duplicate edges; add dynamic simulated entity extraction.
3. **Defect 3 (Critical - Memory Engine & Vector Store)**: Use `collection.upsert()` in ChromaDB to prevent `DuplicateIDError` and vector store fallback; support JSON body in `PUT /memories/{id}`; validate non-empty content and search queries.
4. **Defect 4 (High - Self-Improvement System)**: Fix `PromptOptimizerAgent` simulator collision so optimized prompts store real prompt templates instead of JSON; return 404 on missing log ID.
5. **Defect 5 (High - Task Intelligence)**: Return 404 on missing task ID breakdown; support JSON body for progress updates; correct parent status when subtasks are 0%.
6. **Defect 6 (Medium - Model Router)**: Retain and report honest error details on provider failures; maintain simulation labeling transparency.
7. **Defect 7 (Medium - Security Center)**: Expose `POST /api/v1/security/scrub` endpoint with request schema.
8. **Defect 8 (Medium - Meeting Intelligence)**: Gracefully handle string `days_to_complete` in action items; add `GET /meetings/{id}` endpoint.
