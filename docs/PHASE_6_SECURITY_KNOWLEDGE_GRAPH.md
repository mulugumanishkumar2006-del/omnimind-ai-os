# OmniMind AI OS — Phase 6: Knowledge Graph, Security, and Privacy

## Executive Summary

Phase 6 hardens OmniMind AI OS by completing and integrating the knowledge graph service, security scanner, and privacy boundaries. Grounded in the actual SQLite storage schema and FastAPI architecture, this phase eliminates mock stubs, resolves privacy leaks in audit logs, introduces structured vulnerability analysis, prevents cross-site scripting (XSS) in model outputs, establishes deterministic heuristic extraction fallbacks, and hardens application boundaries against oversized payloads and unhandled error disclosure.

All 88 automated tests across Phases 2 through 6 pass without external model dependencies, and `verify_services.py` verifies all programmatic components.

---

## 1. Actual Graph-Storage Architecture

OmniMind AI OS does **not** use an external graph database (e.g., Neo4j or Amazon Neptune). Instead, it implements a persistent relational property graph backed by SQLite via SQLAlchemy:

- **Entities (`graph_nodes` table)**:
  - `id`: Normalized string identifier (alphanumeric and underscores, e.g., `fastapi`, `postgresql`).
  - `label`: Human-readable display label (e.g., `"FastAPI"`, `"PostgreSQL Database"`).
  - `type`: Categorized entity type (restricted to `['Concept', 'Technology', 'Person', 'Organization', 'Project', 'Document', 'Database', 'Task', 'Tool']`).
  - `properties`: JSON field storing arbitrary key-value metadata, including `source_metadata` and heuristic extraction flags (`"is_heuristic": true`).
  - `created_at`: UTC timestamp.

- **Relationships (`graph_edges` table)**:
  - `id`: Auto-incrementing primary key.
  - `source_id`: Foreign key referencing `graph_nodes.id` (`ondelete="CASCADE"`).
  - `target_id`: Foreign key referencing `graph_nodes.id` (`ondelete="CASCADE"`).
  - `relation`: Normalized relationship type (e.g., `depends_on`, `written_in`, `uses`, `manages`).
  - `weight`: Float between `0.1` and `1.0` representing link strength or confidence.
  - `properties`: JSON dictionary for relationship context.
  - `created_at`: UTC timestamp.

- **In-Memory NetworkX Graph**:
  - The `KnowledgeGraph` service builds an in-memory `networkx.DiGraph` from the database tables for topology computations, neighbor lookups, and visual serialization into nodes/links JSON format for D3 / Streamlit graphs.

- **Deduplication and Idempotency**:
  - Repeated submissions with matching entity IDs perform an **upsert**: the existing node's label and type are updated, and new properties are merged into the existing properties dictionary without duplicate records.
  - Edge deduplication checks for existing `(source_id, target_id, relation)` tuples before insertion.

---

## 2. Entity and Relationship Extraction Behavior

### 2.1 Extraction Pipeline
1. **Input Validation**: The content is trimmed and checked against `settings.MAX_INPUT_CHAR_LENGTH` (50,000 characters). Oversized or empty content raises a validation error.
2. **LLM Extraction**: An asynchronous prompt is routed to `execute_llm_call("KnowledgeGraphAgent", prompt, db, complexity_override="medium")`.
3. **Structured Extraction Prompt**: The model is instructed to output strictly valid JSON conforming to `{"nodes": [...], "edges": [...]}`.
4. **Resilient Parsing**: Markdown fences (````json ... ````) and surrounding conversational text are automatically stripped and regex-extracted.
5. **Deterministic Heuristic Fallback**:
   - If the LLM call fails, returns malformed JSON, or produces an empty node set, the service automatically invokes `deterministic_kg_extraction(clean_content)`.
   - The deterministic extractor identifies capitalized nouns, technology keywords (e.g., Python, FastAPI, Docker, SQLite, React, PostgreSQL), and relational markers (e.g., `uses`, `depends on`, `written in`, `integrates with`).
   - The response explicitly flags `is_heuristic: true` and `is_simulated: true` so frontend and calling agents know the result was generated heuristically rather than by a large language model.

### 2.2 Memory and Task Integration
- `extract_from_memory(memory_id, db)`: Retrieves a persistent memory record from `MemoryDB`, validates its existence, extracts entities/edges tagged with `source_type: "memory"` and `memory_id`, and stores them in the graph.
- Node inspection and neighborhood search endpoints (`/api/v1/knowledge/nodes/{id}`, `/api/v1/knowledge/nodes/{id}/neighbors`, `/api/v1/knowledge/search`) allow traversing multi-hop relationships.

---

## 3. Security Scanner and Boundary Hardening

### 3.1 Detection Capabilities
The security scanner operates as a pattern-based defense-in-depth layer analyzing user prompts, agent interactions, and model responses:

| Category | Patterns & Detections | Severity |
| :--- | :--- | :--- |
| **System Instruction Override** | `ignore previous instructions`, `disregard all prior instructions`, `override system prompt`, `reveal your instructions` | High / Critical |
| **Jailbreak Personas** | `DAN mode`, `developer mode enabled`, `jailbreak active`, `act as an unrestricted AI` | Critical |
| **Shell & Command Abuse** | `rm -rf /`, `curl http://... \| sh`, `format c:`, `powershell -enc` | Critical |
| **Credential & Secret Leaks** | OpenAI keys (`sk-[a-zA-Z0-9]{20,}`), AWS Access Keys (`AKIA[0-9A-Z]{16}`), GitHub tokens (`ghp_[0-9a-zA-Z]{36}`), Private Keys (`-----BEGIN (RSA \|EC \|OPENSSH )?PRIVATE KEY-----`) | Critical |
| **PII Exposure** | Social Security Numbers (`\b\d{3}-\d{2}-\d{4}\b`), Credit Card numbers (`\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b`) | High |

### 3.2 Sensitive Data Redaction & Safe Logging
- **`scrub_sensitive_data(text)`**: Automatically replaces identified API keys, private keys, SSNs, credit cards, and email addresses with redaction tokens (e.g., `[REDACTED_API_KEY]`, `[REDACTED_SSN]`).
- **Privacy-Preserving Audit Logs**: When an incident is recorded in `SecurityThreatLogDB`, the stored prompt is scrubbed before writing to the database. Raw API keys and personal identifiers are **never** logged in plaintext.

### 3.3 Output Sanitization (XSS Prevention)
- **`sanitize_output(text)`**: Inspects downstream model outputs for HTML injection attacks (`<script>`, `<iframe>`, `javascript:`, `<object>`, inline event handlers `onerror=`, `onload=`, etc.) and neutralizes dangerous tags and attributes before browser rendering.

### 3.4 Limitations
> [!WARNING]
> **Pattern-Based Defense Limitation**: The security scanner is a regex and rule-based filter. It cannot provide a mathematical guarantee against novel semantic obfuscations, multi-step indirect prompt injections, or base64/rot13 encoded payloads. It must be treated as one layer in a defense-in-depth posture alongside strict least-privilege agent tools, sandboxed execution, and human oversight.

---

## 4. API and Application Boundary Protections

| Protection Layer | Implementation Details |
| :--- | :--- |
| **CORS Restriction** | Replaced wildcard `allow_origins=["*"]` with configurable `settings.CORS_ORIGINS` (defaults to `http://localhost:8501`, `http://127.0.0.1:8501`, `http://localhost:3000`, `http://127.0.0.1:8000`). |
| **Payload Size Limit** | Added `RequestSizeLimitMiddleware` enforcing a 10 MB maximum request body size (`413 Payload Too Large`). |
| **Input Truncation Limits** | Graph extraction and security scan inputs enforce `MAX_INPUT_CHAR_LENGTH = 50,000` to prevent memory exhaustion / ReDoS. |
| **Sanitized Error Handling** | Global exception handler catches unhandled exceptions and returns a generic `500 Internal Server Error` with an internal incident ID, suppressing raw stack traces and internal file paths. |

---

## 5. Automated Tests and Verification Results

The automated test suite in `tests/test_phase6_security_knowledge_graph.py` contains 14 focused tests verifying every requirement:

1. `test_kg_deterministic_extraction_fallback`: Heuristic fallback extracts valid nodes and edges with `is_heuristic: True`.
2. `test_kg_mocked_llm_extraction`: Extraction from mocked LLM JSON output.
3. `test_kg_repeated_submission_deduplication`: Idempotent entity upserting without duplicate IDs.
4. `test_kg_malformed_llm_output_graceful_recovery`: Graceful fallback on corrupt JSON.
5. `test_kg_input_size_validation`: Rejection of oversized or empty payloads.
6. `test_kg_node_neighbors_and_querying`: Querying node details and directional neighbors.
7. `test_kg_extract_from_memory_integration`: Generating graph nodes directly from persistent memory records.
8. `test_security_scanner_prompt_injection_detection`: Flagging instruction override and jailbreak personas.
9. `test_security_scanner_credential_and_pii_detection`: Detecting OpenAI keys, AWS keys, private keys, SSNs, credit cards.
10. `test_security_scanner_benign_text_no_false_positive`: Normal technical sentences pass without false alarms.
11. `test_security_scrubbing_and_safe_threat_logging`: Verifying that DB threat logs store scrubbed prompts without raw secrets.
12. `test_output_sanitizer_xss_protection`: Stripping `<script>` and `onerror=` handlers from model outputs.
13. `test_security_api_endpoints`: Testing `/api/v1/security/scan` and `/api/v1/security/sanitize` endpoints.
14. `test_knowledge_graph_api_endpoints`: Testing `/nodes/{id}`, `/neighbors`, `/search`, and `/extract-from-memory`.

### Test Suite Execution Output
```
======================= 14 passed, 16 warnings in 4.86s =======================
================= 88 passed, 17 warnings in 94.48s (0:01:34) ==================
```

All 88 tests across the complete test suite pass.

---

## 6. Known Vulnerabilities and Remaining Gaps

1. **Authentication and Authorization**: The application currently runs in local development mode without user authentication or JWT tokens. Multi-tenant isolation and role-based access control (RBAC) are not implemented.
2. **Advanced Semantic Injections**: The scanner uses regex rules; advanced polyglot attacks, cypher-based jailbreaks, or linguistic evasion techniques require a dedicated classification model (e.g., Llama Guard).
3. **Graph Scaling**: Graph storage uses SQLite relational tables with in-memory NetworkX caching. For graphs with >100,000 nodes, migration to a dedicated graph engine or indexed document store would be required.
