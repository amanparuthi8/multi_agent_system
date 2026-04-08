# Multi-Agent AI System

> Production-ready multi-agent AI assistant for tasks, scheduling, and knowledge management.
> Built with **Google ADK · Gemini 2.5 Flash · AlloyDB · MCP Toolbox · Cloud Run**

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Agent Role Definitions](#2-agent-role-definitions)
3. [Data Schema](#3-data-schema)
4. [MCP Tool Interfaces](#4-mcp-tool-interfaces)
5. [Workflow Design Patterns](#5-workflow-design-patterns)
6. [Project Structure](#6-project-structure)
7. [Local Development Setup](#7-local-development-setup)
8. [GitHub Setup](#8-github-setup)
9. [Cloud Run Deployment](#9-cloud-run-deployment)
10. [API Reference](#10-api-reference)
11. [End-to-End Workflow Example](#11-end-to-end-workflow-example)
12. [Design Decisions](#12-design-decisions)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        CLIENT (Web / Mobile / CLI)                       │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │  HTTPS  POST /api/v1/query
┌──────────────────────────────────▼───────────────────────────────────────┐
│                    FastAPI  (Cloud Run — stateless)                       │
│   /health  /api/v1/query  /api/v1/tasks  /api/v1/events                  │
│            /api/v1/notes  /api/v1/workflows                              │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │  ADK Runner
┌──────────────────────────────────▼───────────────────────────────────────┐
│           ORCHESTRATOR  (root_agent — gemini-2.5-flash)                   │
│  • Classifies intent                                                     │
│  • Writes user_id / session_id to ADK shared state                      │
│  • Transfers control to the right sub-agent                             │
└───────┬──────────────┬───────────────────┬────────────────┬─────────────┘
        │              │                   │                │
┌───────▼──────┐ ┌─────▼────────┐ ┌───────▼───────┐ ┌──────▼───────────┐
│  task_agent  │ │calendar_agent│ │knowledge_agent│ │ workflow_agent   │
│ create_task  │ │schedule_event│ │ create_note   │ │ (full toolset)   │
│ list_tasks   │ │ list_events  │ │ search_notes  │ │ Plan→Execute→    │
│ update_task  │ │check_conflict│ │ get_history   │ │ Validate loop    │
│ delete_task  │ │              │ │               │ │ Retry+branching  │
└──────┬───────┘ └──────┬───────┘ └───────┬───────┘ └────────┬─────────┘
       └────────────────┴─────────────────┴──────────────────┘
                                   │  HTTP  (toolbox-core)
┌──────────────────────────────────▼───────────────────────────────────────┐
│              MCP TOOLBOX SERVER  (port 5000)                             │
│   tools.yaml: sources → tools → toolsets                                 │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │  pg8000
┌──────────────────────────────────▼───────────────────────────────────────┐
│                   ALLOYDB  (PostgreSQL 15-compatible)                     │
│   tasks │ events │ notes (VECTOR 768) │ interactions │ workflows          │
│   google_ml_integration · pgvector · ScaNN                               │
└──────────────────────────────────────────────────────────────────────────┘
```

Key design principles:

- **Separation of concerns** — each agent owns one domain; orchestrator owns routing only
- **MCP-only tool access** — all DB operations go through MCP Toolbox, never direct SQL from agents
- **Stateless API** — Cloud Run instances share no in-process state; session context lives in AlloyDB
- **In-database AI** — embeddings generated at INSERT time via AlloyDB's `embedding()` function
- **Externalized config** — all secrets via env vars / Secret Manager

---

## 2. Agent Role Definitions

**Orchestrator (`root_agent`)** — session init, intent classification, sub-agent routing. Uses `init_session_state` + `get_recent_interactions`. Transfers to: task keywords → `task_agent`; calendar keywords → `calendar_agent`; knowledge keywords → `knowledge_agent`; multi-domain → `workflow_agent`.

**Task Agent** — full task lifecycle (create, list, update, delete) via `task_toolset`. Infers priority from natural language ("ASAP" → critical), formats output with priority emojis.

**Calendar Agent** — event scheduling with mandatory conflict detection via `calendar_toolset`. Always runs `check_conflicts` first — blocks booking if conflict found.

**Knowledge Agent** — semantic notes storage and natural-language retrieval via `knowledge_toolset` + `memory_toolset`. Uses AlloyDB AI vector search (768-dim), shows similarity scores.

**Workflow Agent** — multi-step compound workflows spanning all domains via `full_toolset`. Enforces Plan → Execute → Validate loop with automatic retry.

---

## 3. Data Schema

### tasks
`task_id UUID PK | user_id TEXT | title TEXT | status (pending/in_progress/done/cancelled) | priority (low/medium/high/critical) | due_date TIMESTAMP | tags TEXT[] | metadata JSONB`

### events
`event_id UUID PK | user_id TEXT | title TEXT | start_time TIMESTAMP | end_time TIMESTAMP | location TEXT | attendees TEXT[] | linked_task_id UUID FK`

### notes
`note_id UUID PK | user_id TEXT | title TEXT | content TEXT | tags TEXT[] | content_vector VECTOR(768)` — ScaNN index for cosine similarity search. **768-dim MUST match text-embedding-005** (Lab 6 requirement).

### interactions
`interaction_id UUID PK | session_id TEXT | user_id TEXT | agent_name TEXT | role TEXT | content TEXT | tool_calls JSONB` — `session_id` groups a conversation for short-term memory.

### workflows
`workflow_id UUID PK | user_id TEXT | name TEXT | status TEXT | steps JSONB | result JSONB | error TEXT`

---

## 4. MCP Tool Interfaces

Toolsets defined in `mcp_toolbox/tools.yaml`, served by MCP Toolbox binary.

| Toolset | Tools | Agent |
|---------|-------|-------|
| `task_toolset` | create_task, list_tasks, update_task_status, delete_task | task_agent |
| `calendar_toolset` | schedule_event, list_events, check_conflicts | calendar_agent |
| `knowledge_toolset` | create_note, search_notes | knowledge_agent |
| `memory_toolset` | get_recent_interactions | knowledge_agent, orchestrator |
| `full_toolset` | all above | workflow_agent |

The `search_notes` tool runs `embedding('text-embedding-005', $query)` directly inside AlloyDB SQL — zero application-layer embedding code. The `check_conflicts` tool uses PostgreSQL's native `tsrange` overlap operator.

---

## 5. Workflow Design Patterns

### Planning → Execution → Validation Loop

The `workflow_agent` is instructed to always output a numbered plan before calling any tool, then execute steps in order, passing outputs between steps using `$step_name.field` references, and finish with a validation summary table.

### Retry with Exponential Back-off (WorkflowEngine)

Each step retries up to `retry_limit` times with back-off: 1s → 2s → 4s. Timeout is enforced via `asyncio.wait_for`. Dependent steps are skipped when their dependency fails. All state is persisted to AlloyDB after each step so workflows survive process restarts.

### Conditional Branching

If `check_conflicts` returns `conflict_count > 0`, the workflow reports the conflicting events and pauses for user input before proceeding. If a required `task_id` is unknown, `list_tasks` is called to let the user choose.

---

## 6. Project Structure

```
multi-agent-system/
├── agents/
│   ├── __init__.py          exports root_agent
│   ├── orchestrator.py      primary controller / router
│   ├── task_agent.py        task CRUD domain
│   ├── calendar_agent.py    scheduling domain
│   ├── knowledge_agent.py   notes + semantic search
│   └── workflow_agent.py    multi-step compound workflows
├── api/
│   ├── main.py              FastAPI app factory, middleware, lifespan
│   └── routers/
│       ├── query.py         POST /api/v1/query  ← main ADK entry point
│       ├── tasks.py         CRUD /api/v1/tasks
│       ├── events.py        CRUD /api/v1/events
│       ├── notes.py         CRUD + semantic search /api/v1/notes
│       └── workflows.py     trigger + poll /api/v1/workflows
├── database/
│   ├── schema.sql           AlloyDB DDL (idempotent)
│   ├── connection.py        SQLAlchemy engine + session helpers
│   └── models.py            ORM models
├── mcp_toolbox/
│   └── tools.yaml           MCP Toolbox server config
├── tools/
│   └── mcp_tools.py         toolbox-core client + toolset factories
├── workflows/
│   └── engine.py            WorkflowEngine + retry + pre-built factories
├── scripts/
│   ├── deploy.sh            Cloud Run deployment (8 steps)
│   └── run_local.sh         start MCP + API + ADK UI locally
├── tests/
│   ├── test_workflows.py    WorkflowEngine unit tests
│   └── test_api.py          FastAPI integration tests
├── Dockerfile               multi-stage build
├── requirements.txt
└── .env.example
```

---

## 7. Local Development Setup

### Prerequisites
- Python 3.12, `uv` (`pip install uv`), gcloud CLI

```bash
# 1. Clone + configure
git clone https://github.com/YOUR_ORG/multi-agent-system.git
cd multi-agent-system
cp .env.example .env
# Edit .env: GOOGLE_CLOUD_PROJECT, ALLOYDB_*, etc.

# 2. Virtual environment (Lab 2 pattern)
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# 3. Authenticate
gcloud auth application-default login

# 4. Apply database schema
psql $DATABASE_URL -f database/schema.sql
# Then in AlloyDB Studio: CALL google_ml.create_model('gemini-2.5-flash', ...)

# 5. Download MCP Toolbox binary (Lab 4 pattern)
VERSION=0.23.0
curl -O https://storage.googleapis.com/genai-toolbox/v$VERSION/linux/amd64/toolbox
mv toolbox mcp_toolbox/toolbox && chmod +x mcp_toolbox/toolbox

# 6. Run everything
./scripts/run_local.sh
# Or manually:
# Terminal 1: ./mcp_toolbox/toolbox --tools-file="mcp_toolbox/tools.yaml"
# Terminal 2: uvicorn api.main:app --port 8080 --reload
# Terminal 3: cd agents && adk web

# 7. Test
pytest tests/ -v
```

---

## 8. GitHub Setup

```bash
git init && git add .
git commit -m "feat: initial multi-agent system"
git remote add origin https://github.com/YOUR_ORG/multi-agent-system.git
git branch -M main && git push -u origin main
```

GitHub Actions CI/CD is in `.github/workflows/ci-cd.yml`. It runs pytest, builds the image, and deploys to Cloud Run on every push to `main`.

Required secrets: `GCP_PROJECT_ID`, `GCP_SA_KEY`, `ALLOYDB_PASSWORD`.

---

## 9. Cloud Run Deployment

### One command
```bash
chmod +x scripts/deploy.sh && ./scripts/deploy.sh
```

### What it does

| Step | Action |
|------|--------|
| 1 | Enable all required GCP APIs |
| 2 | Create Artifact Registry Docker repository |
| 3 | Create service account + bind IAM roles (aiplatform.user, alloydb.client, logging.logWriter) |
| 4 | Build Docker image via Cloud Build → push to Artifact Registry |
| 5 | Prompt to apply AlloyDB schema |
| 6 | Instructions for MCP Toolbox sidecar deployment |
| 7 | Deploy API to Cloud Run (0–10 instances, 2 CPU / 2 GiB, authenticated-only) |
| 8 | Print service URL + test commands |

### Manual deploy
```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/mas-repo/multi-agent-system:latest"

gcloud builds submit . --tag="$IMAGE"

gcloud run deploy multi-agent-system \
  --image="$IMAGE" --platform=managed --region="$REGION" \
  --service-account="mas-service-account@${PROJECT_ID}.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},MODEL=gemini-2.5-flash,GOOGLE_GENAI_USE_VERTEXAI=1" \
  --set-secrets="ALLOYDB_PASSWORD=alloydb-password:latest" \
  --min-instances=0 --max-instances=10 --cpu=2 --memory=2Gi
```

---

## 10. API Reference

### `POST /api/v1/query`
```bash
curl -X POST https://YOUR_URL/api/v1/query \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","session_id":"s-1","message":"Schedule standup tomorrow 9am"}'
```
Returns: `{session_id, response, agent_used, tool_calls[], interaction_id, latency_ms}`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + MCP status |
| POST | `/api/v1/tasks/` | Create task directly |
| GET | `/api/v1/tasks/?user_id=X` | List tasks |
| PATCH | `/api/v1/tasks/{id}` | Update task |
| DELETE | `/api/v1/tasks/{id}` | Delete task |
| POST | `/api/v1/events/` | Create event |
| GET | `/api/v1/events/?user_id=X` | List events |
| POST | `/api/v1/notes/search` | Semantic vector search |
| POST | `/api/v1/workflows/trigger` | Trigger async workflow |
| GET | `/api/v1/workflows/{id}` | Poll workflow status |

Interactive docs at `https://YOUR_URL/docs`

---

## 11. End-to-End Workflow Example

**User:** *"Schedule a product review with sarah@co.com next Monday 2–3pm, create a follow-up task to send notes, and save our product vision as a note."*

```
POST /api/v1/query
  → FastAPI → ADK Runner → orchestrator
  → intent: multi-domain → transfer to workflow_agent

workflow_agent PLAN:
  1. check_conflicts(Monday 14:00–15:00)
  2. schedule_event("Product Review", attendees, ...)  ← depends on 1
  3. create_task("Send meeting notes", priority=high)  ← depends on 2
  4. create_note("Product Vision", content=...)        ← parallel with 3

EXECUTION (WorkflowEngine):
  Step 1 → AlloyDB tsrange check → {conflict_count: 0} ✅
  Step 2 → AlloyDB INSERT events → {event_id: "evt-abc"} ✅
  Step 3 → AlloyDB INSERT tasks  → {task_id: "tsk-def"} ✅
  Step 4 → AlloyDB INSERT notes  → embedding() auto-runs → {note_id: "nte-ghi"} ✅

VALIDATION TABLE:
  | Step | Tool            | Status | Key Output        |
  |------|-----------------|--------|-------------------|
  | 1    | check_conflicts | ✅     | 0 conflicts       |
  | 2    | schedule_event  | ✅     | event_id=evt-abc  |
  | 3    | create_task     | ✅     | task_id=tsk-def   |
  | 4    | create_note     | ✅     | note_id=nte-ghi   |

Both turns saved to interactions table (session continuity).

Response: "📅 Product Review scheduled Monday 14:00–15:00 with sarah@co.com.
           ✅ Task 'Send meeting notes' created (high priority).
           📝 Product Vision note saved.
           ✅ Done: 4 actions completed."
```

---

## 12. Design Decisions

| Decision | Choice | Justification from .md |
|----------|--------|------------------------|
| LLM | `gemini-2.5-flash` | Used in Labs 1, 2, 3, 4 — best speed/capability balance |
| Agent framework | Google ADK `1.14.0` | All 6 labs use ADK; provides SequentialAgent, Runner, session management |
| MCP pattern | `toolbox-core` ToolboxSyncClient | Lab 4 pattern; enterprise connection pooling + auth + OpenTelemetry |
| Database | AlloyDB PostgreSQL | Labs 5 & 6; ScaNN vector index + in-DB embeddings via `google_ml_integration` |
| Embedding | `text-embedding-005` → VECTOR(768) | Lab 6 explicit: *"must match text-embedding-005 (768-dim)"* |
| Deployment | Cloud Run | Lab 1; serverless, scales to zero, pay-per-request |
| Container | `python:3.12-slim` + `uv` | Lab 2 Python 3.12 + uv used in Labs 1/2/3 |
| DB driver | `pg8000` (pure Python) | No libpq dependency → smaller image; AlloyDB speaks standard PG wire |
| API layer | FastAPI + Uvicorn | Not in .md — chosen for async ADK runner compatibility and REST API layer |

**One documented deviation:** The `.md` deploys agents directly via `adk deploy cloud_run`. This system wraps ADK inside FastAPI to expose REST endpoints (CRUD, workflow triggers, health) alongside the chat interface — required for programmatic integrations. The ADK Web UI is still accessible locally via `cd agents && adk web`.
