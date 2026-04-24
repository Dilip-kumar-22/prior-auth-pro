# Foundry Multi-Session Build — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rerun S-CORP Foundry across multiple Claude Code sessions to finish PriorAuth Pro for the Agents Assemble Healthcare Hackathon (submit by 2026-05-11 23:00 EDT).

**Architecture:** BuildOrchestrator (Enterprise mode) builds into `D:/SHADOW/prior-auth-pro/` via `workspace_override`. Six modules, each kicked off with its own brief, Foundry self-drives 12-step pipeline per sprint. Claude polls status, handles 503 fallouts, commits at module boundaries. State persisted in `.foundry-state.json` + `~/.shadow/data/build_orchestrator.db` for cross-session resume.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + ARQ + PostgreSQL/pgvector · React 18 + TypeScript + Vite + Tailwind + shadcn/ui · Google ADK + A2A JSON-RPC · Gemini 3.1 Pro (primary) with 2.5 Pro / 3 Flash / 2.5 Flash fallback · Docker Compose · GitHub Actions.

**Companion docs:**
- [Design doc](2026-04-19-foundry-multi-session-design.md) — scope, decisions, failure recovery, timeline
- [Original PriorAuth Pro design](2026-04-12-priorauth-pro-design.md) — product architecture

---

## Phase 1 — Pre-Flight Setup (Session 1, ~45 min)

Non-LLM work: scaffold the repo, seed it with the 67 baseline files, git-init, publish to GitHub, verify Foundry imports.

### Task 1: Verify prerequisites

**Step 1: Check Python env has key deps loaded**

Run: `cd D:/SHADOW/S-CORP/backend && python -c "from core.build_orchestrator import BuildOrchestrator; from core.llm import call_with_fallback; print('OK')"`

Expected: `OK`

**Step 2: Check Gemini keys present**

Run: `python -c "import os; from dotenv import load_dotenv; load_dotenv('D:/SHADOW/S-CORP/backend/.env'); print('primary' if os.getenv('GEMINI_API_KEY') else 'MISSING'); print('secondary' if os.getenv('GEMINI_API_KEY_2') else 'absent')"`

Expected: `primary` followed by `secondary` or `absent`. If `MISSING`, stop and ask Commander before proceeding.

**Step 3: Check baseline workspace exists**

Run: `ls "C:/Users/Dilip Kumar/.shadow/workspace/forge_1776001633" | head -20`

Expected: Listing shows `api/`, `core/`, `engines/`, `fhir/`, `migrations/`, `models/`, `tests/`, `worker/`, and top-level files like `alembic.ini`, `requirements.txt`.

**Step 4: Check `gh` CLI is authenticated**

Run: `gh auth status`

Expected: Logged in as `Dilip-kumar-22`. If not, stop.

### Task 2: Create target repo structure

**Step 1: Make top-level directory**

Run: `mkdir -p D:/SHADOW/prior-auth-pro/backend D:/SHADOW/prior-auth-pro/docs/module-briefs`

Expected: No error. Verify: `ls D:/SHADOW/prior-auth-pro`

### Task 3: Copy baseline files

**Step 1: Copy 67 files from Foundry workspace**

Run:
```bash
cp -r "C:/Users/Dilip Kumar/.shadow/workspace/forge_1776001633/." D:/SHADOW/prior-auth-pro/backend/
```

Expected: Silent success.

**Step 2: Verify file count landed**

Run: `find D:/SHADOW/prior-auth-pro/backend -type f | wc -l`

Expected: 69 files (67 good + 2 broken placeholders we will remove next).

### Task 4: Delete broken placeholder files

**Step 1: Remove the two files killed by prior 503 storm**

Run:
```bash
rm D:/SHADOW/prior-auth-pro/backend/worker/tasks.py
rm D:/SHADOW/prior-auth-pro/backend/tests/test_auth_requests.py
```

Expected: Silent success. Module 1 will regenerate both.

**Step 2: Confirm no other `# LLM error:` placeholders remain**

Run (Grep tool): pattern `# LLM error:` path `D:/SHADOW/prior-auth-pro/backend`

Expected: Zero matches. If any appear, delete those files too and note in session log.

### Task 5: Fix `requirements.txt` stray "the" on line 13

**Step 1: Read requirements.txt**

Read: `D:/SHADOW/prior-auth-pro/backend/requirements.txt`

**Step 2: Find line containing the stray "the"**

The prior audit flagged a literal word "the" on line 13 that is not a valid pip requirement.

**Step 3: Edit to remove the line**

Use Edit tool to replace the stray "the\n" line with empty string. Leave surrounding lines untouched.

**Step 4: Verify file still parses as requirements**

Run: `python -m pip install --dry-run --quiet -r D:/SHADOW/prior-auth-pro/backend/requirements.txt 2>&1 | head -5`

Expected: No parse errors (network errors OK — we only care that pip can read the file).

### Task 6: Write `.gitignore`

**Step 1: Create `.gitignore`**

Write: `D:/SHADOW/prior-auth-pro/.gitignore`

Content:
```
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
venv/
*.egg-info/
dist/
build/

# Node
node_modules/
.vite/
.next/
dist/
coverage/

# Environment
.env
.env.local
*.env.local

# IDE
.vscode/
.idea/
*.swp
*~

# OS
.DS_Store
Thumbs.db

# Foundry workspace (we write through workspace_override)
.shadow/

# Generated demo artifacts (kept out of repo)
demo.mp4
*.mov
screenshots/*.psd
```

### Task 7: Write `LICENSE`

**Step 1: Create MIT license**

Write: `D:/SHADOW/prior-auth-pro/LICENSE`

Content: Standard MIT license text with `2026 Dilip Kumar`.

### Task 8: Write stub `README.md`

**Step 1: Minimal README (rewritten by Module 6 later)**

Write: `D:/SHADOW/prior-auth-pro/README.md`

Content:
```markdown
# PriorAuth Pro

AI-powered prior authorization for healthcare — built for the Agents Assemble Healthcare Hackathon (2026).

**Status:** In active build via S-CORP Foundry. Full README generated by Module 6.

## Architecture (short version)

- **Backend:** FastAPI + SQLAlchemy 2.0 async + pgvector, Gemini 3.1 Pro reasoning core, FHIR R4 clinical context, rules engine with real payer policies
- **Frontend:** React 18 + TypeScript + Vite + Tailwind + shadcn/ui
- **Agents:** Google ADK + A2A JSON-RPC for Prompt Opinion publishing
- **Infra:** Docker Compose (postgres/pgvector + backend + frontend)

## Quick start (provisional)

```bash
docker compose up
# Dashboard: http://localhost:3000
# Backend: http://localhost:8000
# A2A endpoint: http://localhost:8000/a2a
```

## License

MIT
```

### Task 9: Copy design docs into new repo

**Step 1: Copy PriorAuth Pro design doc**

Run:
```bash
cp D:/SHADOW/S-CORP/docs/plans/2026-04-12-priorauth-pro-design.md D:/SHADOW/prior-auth-pro/docs/design.md
```

Expected: Silent success.

**Step 2: Copy this plan & its design doc**

Run:
```bash
cp D:/SHADOW/S-CORP/docs/plans/2026-04-19-foundry-multi-session-design.md D:/SHADOW/prior-auth-pro/docs/foundry-build-design.md
cp D:/SHADOW/S-CORP/docs/plans/2026-04-19-foundry-multi-session-implementation.md D:/SHADOW/prior-auth-pro/docs/foundry-build-plan.md
```

Expected: Silent success.

### Task 10: Create `docs/foundry-build-log.md`

**Step 1: Write header-only log**

Write: `D:/SHADOW/prior-auth-pro/docs/foundry-build-log.md`

Content:
```markdown
# Foundry Build Log

Session-by-session record of the Foundry rerun. Append-only.

Schema per entry:
- **Date/Time:** local time, 24h
- **Session #**
- **Modules worked:** IDs + status (started / completed / paused / blocked)
- **Files added/modified:** count
- **LOC delta:** approx
- **Fallback events:** count by model (3.1Pro→2.5Pro, 3Flash→2.5Flash, etc.)
- **Hand-finishes:** file paths if any
- **Notes:** anything future sessions must know

---
```

### Task 11: Initialize `.foundry-state.json`

**Step 1: Write initial state**

Write: `D:/SHADOW/prior-auth-pro/.foundry-state.json`

Content:
```json
{
  "project_id": null,
  "workspace": "D:/SHADOW/prior-auth-pro",
  "modules_completed": [],
  "current_module": null,
  "current_module_status": null,
  "last_session_ended_at": null,
  "last_git_tag": null,
  "notes": [
    "Initialized 2026-04-19. Session 1 will set project_id after first orch.plan() call."
  ]
}
```

### Task 12: Git init + baseline commit

**Step 1: Init repo, configure identity if not already set**

Run: `cd D:/SHADOW/prior-auth-pro && git init -b master`

Expected: `Initialized empty Git repository...`

**Step 2: First status check**

Run: `cd D:/SHADOW/prior-auth-pro && git status`

Expected: Large list of untracked files.

**Step 3: Stage everything**

Run: `cd D:/SHADOW/prior-auth-pro && git add -A`

**Step 4: Baseline commit**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git commit -m "$(cat <<'EOF'
baseline: infrastructure from prior Foundry run (67 files)

Copied from ~/.shadow/workspace/forge_1776001633/ — backend API, models, rules
engine with real payer seed data (Aetna, UnitedHealth), RAG engine with pgvector,
FHIR R4 client, 12 test files.

Removed two placeholder files killed by 503 storm during prior run:
- worker/tasks.py
- tests/test_auth_requests.py

Module 1 of the Foundry rerun will regenerate both.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

### Task 13: Create GitHub repo and push

**Step 1: Create public repo**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && gh repo create prior-auth-pro \
  --public \
  --source=. \
  --description "AI-powered prior authorization for healthcare. Agents Assemble Hackathon 2026." \
  --homepage "https://github.com/Dilip-kumar-22/prior-auth-pro"
```

Expected: Repo URL printed.

**Step 2: Add topics**

Run:
```bash
gh repo edit Dilip-kumar-22/prior-auth-pro \
  --add-topic healthcare \
  --add-topic ai-agents \
  --add-topic gemini \
  --add-topic fhir \
  --add-topic prior-authorization \
  --add-topic a2a-protocol \
  --add-topic hackathon
```

Expected: Silent success.

**Step 3: Push master**

Run: `cd D:/SHADOW/prior-auth-pro && git push -u origin master`

Expected: Push succeeds.

### Task 14: Tag baseline

**Step 1: Create tag**

Run: `cd D:/SHADOW/prior-auth-pro && git tag -a baseline -m "Pre-flight baseline — 67 files from prior Foundry run"`

**Step 2: Push tag**

Run: `cd D:/SHADOW/prior-auth-pro && git push origin baseline`

Expected: Tag pushed.

### Task 15: Foundry readiness smoke test

**Step 1: Write throwaway test script**

Write: `D:/SHADOW/S-CORP/scripts/foundry_smoke_test.py`

Content:
```python
"""Foundry readiness smoke test — confirms BuildOrchestrator works with workspace_override."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

from core.build_orchestrator import BuildOrchestrator


async def main():
    orch = BuildOrchestrator()
    project = await orch.plan(
        request="Create a single Python file `hello.py` that prints 'Foundry smoke test OK'.",
        config={
            "workspace_override": str(Path.home() / ".shadow" / "workspace" / "foundry_smoke"),
            "build_model": "gemini/gemini-3.1-pro",
            "project_name": "foundry-smoke-test",
        },
    )
    print(f"project_id={project.id}")
    status = await orch.get_status(project.id)
    print(f"initial status: {status}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Run it**

Run: `cd D:/SHADOW/S-CORP && python scripts/foundry_smoke_test.py`

Expected: Output shows `project_id=proj_...` and initial status dict. No import errors, no API key errors.

**Step 3: Clean up test artifacts**

Run: `rm -rf "C:/Users/Dilip Kumar/.shadow/workspace/foundry_smoke"`

Expected: Silent.

**Step 4: If smoke test failed**

- Import error → fix path or missing dep in `backend/`. Re-run.
- `API key not found` → double-check `.env`. Re-run.
- Any other error → stop, ask Commander, do NOT proceed to Phase 2.

### Task 16: Commit pre-flight completion

**Step 1: Stage changes to `.foundry-state.json` and log (none yet, but will be used later)**

Run: `cd D:/SHADOW/prior-auth-pro && git status`

Expected: Clean tree (nothing should have changed since Task 13; smoke test wrote to `.shadow/`, not into the repo).

**Step 2: Skip commit if nothing to commit.**

---

## Phase 2 — Write 6 Module Briefs (Session 1, ~45 min)

Each brief is the input to one `orch.plan()` call. Written to `docs/module-briefs/Mn-*.md` in the new repo. The brief itself lives in the repo (auditable by judges) and its content is piped into Foundry as the `request` parameter.

Briefs follow a common template — see Task 17 template block. Copy-adapt per module.

### Task 17: Write M1 brief (LLM Worker Tasks)

**Step 1: Create file**

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M1-llm-worker-tasks.md`

Content:
```markdown
# Module 1 — LLM Worker Tasks (Gemini 3.1 Pro reasoning core)

## Purpose

Rebuild the two files killed by the prior 503 storm. This module is the clinical reasoning core: the background tasks that process an incoming prior-auth request through the full pipeline (FHIR extract → classify → rules → RAG → Gemini decision → audit trail).

## Files to create

### 1. `backend/worker/tasks.py`

Two ARQ background tasks:

- `process_auth_request_task(ctx, auth_request_id: int) -> dict`
  - Load `AuthRequest` by ID.
  - Fetch FHIR Bundle via `fhir.client.client_from_session(ctx)` → use `fhir.resources.extract_clinical_context`.
  - Classify request type (medication / imaging / procedure / dme) using simple CPT prefix rules first; only call Gemini if ambiguous.
  - Run `engines.rules.engine.RulesEngine` — returns `auto_approve`, `auto_deny`, or `ai_review`.
  - If `ai_review`: run `engines.rag.engine.RagEngine` to pull top-K relevant guidelines, then call `generate_auth_decision()` from `worker/llm_client.py`.
  - Write decision → append `AuthEvent` rows (event sourcing: `REQUEST_RECEIVED`, `CLASSIFIED`, `RULES_EVALUATED`, `RAG_SEARCHED`, `AI_DECIDED`, `DECISION_FINALIZED`).
  - Emit WebSocket update per event.
  - Return `{"status": "approved"|"denied"|"pended", "decision_id": int, "latency_ms": int}`.

- `generate_appeal_task(ctx, appeal_id: int) -> dict`
  - Load `Appeal` + linked denied `AuthRequest`.
  - Build context: denial reason, clinical summary, relevant guideline citations.
  - Call Gemini 3.1 Pro with structured output schema (`AppealLetter` Pydantic model with sections: `introduction`, `clinical_justification`, `policy_citations`, `conclusion`).
  - Persist rendered letter to `Appeal.letter_markdown`.
  - Return `{"status": "generated", "appeal_id": int, "letter_length": int}`.

Both tasks must be idempotent (safe to retry if ARQ redelivers). Use `AuthEvent` table as dedup check.

### 2. `backend/worker/llm_client.py`

Wrapper around Gemini with structured output support:

- `GeminiClient` class:
  - `__init__(api_key, model="gemini-3.1-pro")`
  - `async generate_structured(prompt: str, schema: type[BaseModel], **kwargs) -> BaseModel` — uses Gemini's JSON mode + response_schema param, falls back to JSON-parsing if schema unsupported.
  - `async generate_text(prompt: str, **kwargs) -> str`
  - Retry with exponential backoff on 503/429 (3 tries, 2^n seconds).
  - Fallback chain on persistent 503: 3.1 Pro → 2.5 Pro → 3 Flash → 2.5 Flash. Log the fallback.

- Top-level helpers used by `tasks.py`:
  - `async generate_auth_decision(clinical_context: ClinicalContext, relevant_guidelines: list[Guideline]) -> AuthDecision`
  - `async generate_appeal_letter(appeal_context: AppealContext) -> AppealLetter`

- Pydantic schemas (new file `backend/worker/schemas.py` or inline):
  - `AuthDecision` — `decision: Literal["approve", "deny", "pend"]`, `reasoning: str`, `confidence: float`, `key_factors: list[str]`, `cited_guidelines: list[str]`
  - `AppealLetter` — fields described above

### 3. `backend/tests/test_auth_requests.py`

Tests the `/auth-requests` REST endpoints (CRUD). Regenerate from scratch — this is the file the prior 503 storm killed.

- `test_create_auth_request_valid` — POST valid payload, expect 201 + enqueues ARQ task.
- `test_create_auth_request_missing_patient` — POST missing required field, expect 422.
- `test_get_auth_request_with_events` — GET returns request + event timeline.
- `test_list_auth_requests_pagination` — cursor pagination.
- Use `httpx.AsyncClient` against FastAPI app. Mock ARQ redis with fakeredis. Use pytest fixtures from `conftest.py`.

### 4. `backend/tests/test_worker_tasks.py`

Integration tests with mocked Gemini:

- `test_process_auth_request_auto_approve` — rules engine auto-approves, no Gemini call.
- `test_process_auth_request_auto_deny` — rules engine auto-denies.
- `test_process_auth_request_ai_review_approve` — rules route to AI, mocked Gemini returns approve.
- `test_process_auth_request_ai_review_deny` — same, Gemini returns deny with reasoning.
- `test_process_auth_request_idempotency` — same task_id run twice, events appended only once.
- `test_generate_appeal_produces_valid_markdown` — mocked Gemini returns `AppealLetter`, persisted letter has all 4 sections.
- Mock `GeminiClient.generate_structured` with `unittest.mock.AsyncMock` returning canned `AuthDecision` / `AppealLetter` instances.

## Integrations (existing files to respect, do NOT modify)

- `backend/engines/rules/engine.py` — use as-is
- `backend/engines/rag/engine.py` — use as-is
- `backend/fhir/client.py`, `backend/fhir/resources.py` — use as-is
- `backend/models/auth_request.py`, `backend/models/appeal.py`, `backend/models/workflow.py` — use `AuthEvent` for event sourcing, don't add new columns
- `backend/worker/main.py` — already registers `process_auth_request_task` and `generate_appeal_task` in `WorkerSettings.functions`. Don't edit.

## Success criteria

- `pytest backend/tests/ -x -q` passes (all 14+ tests green).
- `ruff check backend/worker/ backend/tests/test_auth_requests.py backend/tests/test_worker_tasks.py` clean.
- No Gemini calls in test suite.
- `worker/llm_client.py` and `worker/tasks.py` each ≤ 400 LOC.

## Out of scope for this module

- Agent layer refactor (Module 2 does it)
- ADK / A2A wrapper (Module 3)
- UI (Module 4)
- Docker / CI (Module 5)
- E2E tests + docs (Module 6)

## Model guidance

Primary: `gemini/gemini-3.1-pro`. On 503 storms, Foundry should auto-fall-back via its chain. No per-file model overrides needed.
```

### Task 18: Write M2 brief (Clinical Agents)

**Step 1: Create file**

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M2-clinical-agents.md`

Content follows the same template. Key specifics (the rest mirrors M1's structure):

**Purpose:** Refactor M1's flat worker tasks into structured agent classes (`BaseAgent` → `ExtractionAgent` / `AuthAgent` / `AppealAgent`, with `OrchestratorAgent` as router). Externalize prompts to jinja2 templates. Prep for ADK/A2A wrapping in Module 3.

**Files to create:**
- `backend/agents/__init__.py` — exports all agents
- `backend/agents/base.py` — `BaseAgent` abstract class with `async run(input: TInput) -> TOutput`, telemetry hooks, prompt template loader
- `backend/agents/orchestrator.py` — classifies incoming request intent (`auth_review` / `appeal_generation` / `clarification`), dispatches to specific agent
- `backend/agents/extraction.py` — FHIR Bundle → `ClinicalContext` Pydantic model (uses Gemini 3.1 Flash, structured output)
- `backend/agents/auth.py` — `ClinicalContext` + guidelines → `AuthDecision` (Gemini 3.1 Pro)
- `backend/agents/appeal.py` — denial context → `AppealLetter` (Gemini 3.1 Pro)
- `backend/agents/prompts/extraction.md.j2`, `auth.md.j2`, `appeal.md.j2`, `orchestrator.md.j2` — jinja2 prompt templates (load with `jinja2.Environment(loader=PackageLoader('agents', 'prompts'))`)
- `backend/tests/test_agents/test_base.py` — telemetry hooks, prompt loader
- `backend/tests/test_agents/test_extraction.py`, `test_auth.py`, `test_appeal.py`, `test_orchestrator.py` — one per agent, mocked Gemini

**Refactor — worker tasks become thin:**
- `worker/tasks.py::process_auth_request_task` becomes: `OrchestratorAgent().run(request)` — the orchestrator internally calls extraction → rules → (rag if needed) → auth agent.
- `worker/tasks.py::generate_appeal_task` becomes: `AppealAgent().run(appeal_context)`.

**Success criteria:**
- Each agent has ≥3 tests with mocked LLM.
- All M1 tests still pass (no API contract change).
- Zero hardcoded prompt strings — all prompts come from `.md.j2` templates.
- `pytest backend/tests/ -x -q` green.

**Integrates with:** `worker/llm_client.py` (M1), existing models, existing rules/rag engines.

**Out of scope:** ADK wrapper (M3).

### Task 19: WebFetch A2A protocol spec

**Step 1: Fetch A2A JSON-RPC spec**

Use WebFetch tool on: `https://a2aproject.github.io/a2a/specification/`
Prompt: "Extract the complete JSON-RPC method signatures for `message/send`, `message/sendSubscribe`, `tasks/get`, `tasks/cancel`. Include request/response schemas and error codes."

Save response to scratch: `D:/SHADOW/prior-auth-pro/docs/module-briefs/_a2a-spec-fetched.md` (prefixed with `_` — gets deleted post-M3 to avoid noise).

**Step 2: If URL is broken**, try `https://github.com/a2aproject/A2A` readme. If still missing, use WebSearch for "A2A protocol JSON-RPC spec 2026" and pick the most authoritative result.

### Task 20: WebFetch Prompt Opinion agent card spec

**Step 1: Fetch Prompt Opinion agent card schema**

Use WebFetch tool on: `https://promptopinion.com/docs/agent-card` (or the closest docs URL — adjust after WebSearch if needed).
Prompt: "Extract the full JSON schema for a Prompt Opinion agent card, all required and optional fields, and any publishing manifest format if separate."

Save response to: `D:/SHADOW/prior-auth-pro/docs/module-briefs/_prompt-opinion-spec-fetched.md`.

**Step 2: If site structure unknown**, WebSearch for "Prompt Opinion agent marketplace publish agent card JSON". Fetch the top 2 relevant pages.

### Task 21: Write M3 brief (ADK / A2A integration)

**Step 1: Create file — inline the fetched specs**

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M3-adk-a2a.md`

**Purpose:** Wrap M2's agents in Google ADK + A2A protocol so Prompt Opinion can discover and invoke them. This is the hackathon's non-negotiable technical requirement.

**Files to create:**
- `backend/adk/__init__.py`
- `backend/adk/server.py` — Google ADK server config, binds to FastAPI at `/a2a`
- `backend/adk/handlers.py` — A2A JSON-RPC handlers: `handle_send`, `handle_send_subscribe` (SSE streaming), `handle_get`, `handle_cancel`
- `backend/adk/agent_card.py` — emits Prompt Opinion-compatible agent card at `GET /.well-known/agent-card.json`
- `backend/adk/fhir_context.py` — decodes FHIR Bundle from A2A message metadata (`message.metadata.fhir_context`), wraps in `ClinicalContext`
- `backend/prompt-opinion-manifest.yaml` — publishing manifest per Prompt Opinion spec
- `backend/tests/test_adk/test_handlers.py` — A2A protocol conformance (send → task → poll get → result)
- `backend/tests/test_adk/test_agent_card.py` — card validates against schema
- `backend/tests/test_adk/test_streaming.py` — sendSubscribe SSE streams task events correctly

**Embedded specs** (paste full content of `_a2a-spec-fetched.md` and `_prompt-opinion-spec-fetched.md` into this brief under "## External specifications" section, quoted verbatim). This is Foundry's only source of truth for the protocol details.

**Integrates with:** `agents/orchestrator.py` (M2) is the A2A entry point. Each incoming A2A message creates an ADK Task; the handler calls `OrchestratorAgent().run()`, streams events.

**Success criteria:**
- `curl -X POST http://localhost:8000/a2a -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"message/send","params":{...},"id":1}'` returns a valid task response.
- Agent card validates against the schema in `_prompt-opinion-spec-fetched.md`.
- All conformance tests pass (mocked underlying agent).

**Out of scope:** Actual publishing to Prompt Opinion Marketplace (happens post-build, manual).

**Step 2: After M3 build completes, delete `_a2a-spec-fetched.md` and `_prompt-opinion-spec-fetched.md`** — they were scaffolding inputs, not final artifacts.

### Task 22: Write M4 brief (React Dashboard)

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M4-react-dashboard.md`

**Purpose:** Clinician-facing dashboard — the demo video's visual core. Dark medical-grade theme (deep navy/charcoal, teal/cyan active, amber warnings).

**Scaffold with Vite:**
- `frontend/` — Vite + React 18 + TypeScript + Tailwind + shadcn/ui
- `frontend/package.json` — deps: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `tailwindcss`, `vite`, `typescript`, `zod`, `openapi-typescript`, shadcn/ui deps, `recharts`, `framer-motion`
- `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`

**Pages (under `frontend/src/pages/`):**
- `Dashboard.tsx` — overview: queue summary, recent decisions, impact metrics
- `AuthRequestDetail.tsx` — single request with live `PipelineView` animation
- `AppealEditor.tsx` — appeal drafting with Gemini-generated letter + inline edits
- `Queue.tsx` — split queue (auto-approved / flagged / pended), filterable

**Components (under `frontend/src/components/`):**
- `PipelineView.tsx` — **the money shot**: animated 5-stage pipeline (EXTRACT → CLASSIFY → RULES → RAG → DECIDE), each node has confidence gauge, latency badge, expandable citation drawer. Use framer-motion. Updates via WebSocket.
- `ConfidenceQueues.tsx` — 3-column split
- `ImpactWidget.tsx` — manual vs AI comparison (time saved, $ saved, error rate delta)
- `BatchRunner.tsx` — button fires 10 parallel requests, renders animated grid of pipeline cards
- `ui/` — shadcn components (Button, Card, Drawer, Badge, Gauge, etc.) — use shadcn CLI to install

**Libs (under `frontend/src/lib/`):**
- `api.ts` — typed fetch client generated from backend OpenAPI schema via `openapi-typescript`
- `websocket.ts` — WebSocket client hook (`useAuthRequestStream(id)` → yields pipeline events)

**Tests:**
- `frontend/src/__tests__/PipelineView.test.tsx` — renders 5 stages, advances on mock WebSocket events
- `frontend/src/__tests__/ConfidenceQueues.test.tsx`, `BatchRunner.test.tsx`, `AppealEditor.test.tsx`
- Vitest + Testing Library.

**Success criteria:**
- `cd frontend && npm install && npm run build` succeeds.
- `npm run dev` renders all 4 pages.
- `npm run test` all green.
- Dark theme consistent across all pages.

**Out of scope:** Docker (M5), E2E tests (M6).

**Integrates with:** backend REST + WebSocket at `ws://localhost:8000/ws/auth-requests/:id`. NOT A2A (A2A is for Prompt Opinion, not the browser).

### Task 23: Write M5 brief (Deployment)

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M5-deployment.md`

**Files to create:**
- `docker-compose.yml` (root) — services: `postgres` (pgvector/pgvector:pg16), `backend` (build from `./backend`), `frontend` (build from `./frontend`), optional `arq-worker`. Named volumes for postgres data. Healthchecks on all services.
- `backend/Dockerfile` — multi-stage Python 3.11 build
- `backend/.dockerignore`
- `frontend/Dockerfile` — multi-stage Node 20 build → nginx serve
- `frontend/.dockerignore`
- `.env.example` (root) — consolidated env vars (GEMINI_API_KEY, DATABASE_URL, REDIS_URL, etc.)
- `Makefile` (root) — targets: `up`, `down`, `logs`, `test`, `seed`, `demo`, `format`, `lint`
- `.github/workflows/ci.yml` — on push: ruff → eslint → pytest → vitest → docker build (both images) → push to GHCR (tagged with commit SHA + `latest` on master)
- `scripts/seed_demo_data.py` — loads 20 synthetic FHIR Bundles + 5 payer policies into Postgres via SQLAlchemy

**Success criteria:**
- `docker compose up --build` on a fresh machine: all services healthy in <60s.
- Dashboard reachable at `http://localhost:3000`, backend at `:8000`, A2A at `:8000/a2a`.
- CI green on the first push after this module completes.
- `make demo` runs seed + triggers a batch-10 demo request end-to-end.

**Out of scope:** Terraform / cloud deploy. Hackathon only needs local Docker.

### Task 24: Write M6 brief (Polish & Integration)

Write: `D:/SHADOW/prior-auth-pro/docs/module-briefs/M6-polish.md`

**Files to create:**
- `backend/tests/test_e2e/test_auto_approve_flow.py` — full POST → decision (auto-approved)
- `backend/tests/test_e2e/test_auto_deny_flow.py`
- `backend/tests/test_e2e/test_ai_review_flow.py` — with stubbed Gemini
- `backend/tests/test_e2e/test_appeal_flow.py` — denied → generate appeal
- `backend/tests/test_e2e/test_batch_10.py` — 10 parallel, all complete
- `backend/tests/fixtures/fhir/` — 20 synthetic Bundles (5 per specialty: rheumatology, neurology, orthopedics, sleep medicine)
- `backend/tests/fixtures/payer_policies/` — Aetna, UnitedHealth (already present), Cigna, BCBS, Humana
- `docs/DEMO_SCRIPT.md` — 3-min walkthrough with timestamps: 0:00 intro, 0:20 pipeline visualization, 1:00 appeal demo, 1:40 batch-10, 2:20 A2A+Prompt Opinion, 2:50 closing
- `docs/ARCHITECTURE.md` — diagram + component map
- `docs/FHIR_INTEGRATION.md` — how the FHIR client works, what we extract, what we don't
- `docs/APPEAL_EXAMPLES.md` — 3 real-ish appeal letter samples
- `README.md` (rewrite) — screenshots, demo GIF, architecture diagram, judging-criteria mapping, quick-start, tech stack, acknowledgments
- `CONTRIBUTING.md`
- `SECURITY.md` — HIPAA-aware notes (how we'd handle real PHI in prod — current demo uses synthetic data only)

**Success criteria:**
- All E2E tests pass via `pytest backend/tests/test_e2e/ -q`.
- README renders cleanly on GitHub, screenshots visible.
- Demo script walks through all features referenced, end-to-end, in ≤3 min.

### Task 25: Commit + push briefs

**Step 1: Status check**

Run: `cd D:/SHADOW/prior-auth-pro && git status`

Expected: 6 new files in `docs/module-briefs/`, possibly 2 `_*-fetched.md` scratch files.

**Step 2: Stage & commit**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git add docs/module-briefs/ && git commit -m "$(cat <<'EOF'
docs(briefs): M1-M6 module briefs for Foundry build

One brief per module. M3 embeds fetched A2A + Prompt Opinion specs inline
so Foundry has everything in one input.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**Step 3: Push**

Run: `cd D:/SHADOW/prior-auth-pro && git push`

---

## Phase 3 — Foundry Module Build Cycle (Sessions 1-5)

**Cycle template** — executed once per module. All six cycles follow the same 6 tasks.

### Per-module cycle (6 tasks per module)

**Cycle Task A: Launch module**

Write: `D:/SHADOW/S-CORP/scripts/launch_module.py` (first time only — reused across modules)

Content:
```python
"""Launch a Foundry module. Usage: python launch_module.py M1"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

from core.build_orchestrator import BuildOrchestrator


MODULE_BRIEF_PATHS = {
    "M1": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M1-llm-worker-tasks.md",
    "M2": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M2-clinical-agents.md",
    "M3": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M3-adk-a2a.md",
    "M4": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M4-react-dashboard.md",
    "M5": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M5-deployment.md",
    "M6": "D:/SHADOW/prior-auth-pro/docs/module-briefs/M6-polish.md",
}

STATE_FILE = Path("D:/SHADOW/prior-auth-pro/.foundry-state.json")


async def main(module_id: str):
    brief = Path(MODULE_BRIEF_PATHS[module_id]).read_text(encoding="utf-8")
    orch = BuildOrchestrator()
    project = await orch.plan(
        request=brief,
        config={
            "workspace_override": "D:/SHADOW/prior-auth-pro",
            "build_model": "gemini/gemini-3.1-pro",
            "project_name": f"prior-auth-pro-module-{module_id.lower()[1:]}",
        },
    )
    await orch.start(project.id)

    state = json.loads(STATE_FILE.read_text())
    state["project_id"] = project.id
    state["current_module"] = module_id
    state["current_module_status"] = "running"
    state["last_session_ended_at"] = None
    STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"launched {module_id} as project_id={project.id}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```

Run: `cd D:/SHADOW/S-CORP && python scripts/launch_module.py M1` (replace `M1` per cycle)

Expected: `launched M1 as project_id=proj_...`

**Cycle Task B: Poll status**

Run (in background): Use existing `core.build_orchestrator.get_status(project_id)` via a small loop:
```python
# D:/SHADOW/S-CORP/scripts/poll_status.py
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
from core.build_orchestrator import BuildOrchestrator

async def main():
    state = json.loads(Path("D:/SHADOW/prior-auth-pro/.foundry-state.json").read_text())
    pid = state["project_id"]
    orch = BuildOrchestrator()
    while True:
        s = await orch.get_status(pid)
        print(f"[{time.strftime('%H:%M:%S')}] {s}")
        if s.get("status") in ("complete", "failed", "paused"):
            break
        await asyncio.sleep(45)

asyncio.run(main())
```

Run: `cd D:/SHADOW/S-CORP && python scripts/poll_status.py` — let it run in background; surface one-line status to Commander every 5 min.

While polling:
- Grep `D:/SHADOW/prior-auth-pro/backend` for `# LLM error:` every sprint boundary. If any found, note file path and module for retry post-cycle.
- If status unchanged >5 min AND circuit breaker state is OPEN, tell Commander and investigate.
- If context usage approaches 70%, proceed to session-end handoff even if module not complete.

**Cycle Task C: Verify module output**

After status reaches `complete`:

**Step 1: Verify files exist**

For M1: check `backend/worker/tasks.py`, `backend/worker/llm_client.py`, `backend/tests/test_auth_requests.py`, `backend/tests/test_worker_tasks.py` exist.

Run: `ls D:/SHADOW/prior-auth-pro/backend/worker/ D:/SHADOW/prior-auth-pro/backend/tests/ | grep -E 'tasks|llm_client|auth_requests|worker_tasks'`

**Step 2: Grep for `# LLM error:`**

Run (Grep tool): pattern `# LLM error:` path `D:/SHADOW/prior-auth-pro/backend`

Expected: Zero matches. If non-zero, apply Section 4 failure recovery from design doc.

**Step 3: Run tests** (backend modules only — M4 onward adds frontend)

Run: `cd D:/SHADOW/prior-auth-pro/backend && python -m pytest tests/ -x -q`

Expected: All tests pass.

**Step 4: Lint**

Run: `cd D:/SHADOW/prior-auth-pro/backend && ruff check .`

Expected: Clean. If violations exist, decide: if <10, hand-finish (Edit tool). If ≥10, re-run module with revised brief.

**Cycle Task D: Hand-finish any failed files**

For each `# LLM error:` found:
1. Attempt `orch.retry_sprint(sprint_id)` once if the brief was clear.
2. If retry fails: hand-write the file. Use Edit/Write based on content from brief.
3. Re-run test suite after hand-finish.

**Cycle Task E: Commit + tag + push**

**Step 1: Status & diff summary**

Run: `cd D:/SHADOW/prior-auth-pro && git status && git diff --stat HEAD`

**Step 2: Commit**

Run (substitute N = module number and summary):
```bash
cd D:/SHADOW/prior-auth-pro && git add -A && git commit -m "$(cat <<'EOF'
feat: module N complete — <one-line-module-summary>

<bullet list of major files added>
<fallback events + hand-finishes, if any>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

**Step 3: Tag & push**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git tag -a module_N_complete -m "Module N complete"
cd D:/SHADOW/prior-auth-pro && git push && git push origin module_N_complete
```

**Cycle Task F: Update state & log**

**Step 1: Update `.foundry-state.json`**

Edit `D:/SHADOW/prior-auth-pro/.foundry-state.json`:
- Append module ID to `modules_completed`
- Clear `current_module` and `current_module_status`
- Set `last_git_tag` to `module_N_complete`

**Step 2: Append to `docs/foundry-build-log.md`**

Append entry with date, session #, module(s) worked, file count, LOC delta, fallback count, hand-finish list, notes.

**Step 3: Commit state+log update**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git add .foundry-state.json docs/foundry-build-log.md && git commit -m "state: module N done, updated log" && git push
```

### Per-module cycle invocations

| # | Module | Cycle tasks | Target session | Expected duration |
|---|--------|-------------|----------------|-------------------|
| 26 | **M1** — LLM Worker Tasks | A → F | S1 | 45-75 min |
| 27 | **M2** — Clinical Agents | A → F | S1 | 45-75 min |
| 28 | **M3** — ADK / A2A | A → F | S2 | 60-90 min (largest reasoning brief) |
| 29 | **M4** — React Dashboard | A → F | S2-3 | 90-120 min (most files) |
| 30 | **M5** — Deployment | A → F | S4 | 30-60 min |
| 31 | **M6** — Polish | A → F | S4-5 | 60-90 min |

**Context limit handling between modules:**
- At ~70-80% context, invoke session handoff (Task 32) even if next module hasn't started.
- Don't start a module with <25% context remaining — it won't complete before the handoff.

### Task 32: Session handoff (end-of-session)

Run at the end of every session that isn't the final one.

**Step 1: If module mid-build, pause**

Run (if `current_module_status == "running"`):
```python
# in a small script or inline python -c
import asyncio, json
from pathlib import Path
from core.build_orchestrator import BuildOrchestrator
state = json.loads(Path("D:/SHADOW/prior-auth-pro/.foundry-state.json").read_text())
async def go():
    orch = BuildOrchestrator()
    await orch.pause(state["project_id"])
asyncio.run(go())
```

**Step 2: Update state file**

Edit `.foundry-state.json`:
- Set `current_module_status` to `"paused"` (if paused) or leave `null` (if completed cleanly at module boundary)
- Set `last_session_ended_at` to current ISO datetime
- Append to `notes` array: what was done this session, what to start next session

**Step 3: Append to `docs/foundry-build-log.md`** — final entry for the session.

**Step 4: Commit + push**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git add .foundry-state.json docs/foundry-build-log.md && git commit -m "session end: <session #>, <modules done this session>" && git push
```

**Step 5: Brief Commander** with one paragraph: what's done, what's next, any concerns.

### Task 33: Session start (Session 2+)

Run at the start of every session after Session 1.

**Step 1: Read `.foundry-state.json`**

Read: `D:/SHADOW/prior-auth-pro/.foundry-state.json`

**Step 2: Read last 10 entries of build log**

Read tail of `docs/foundry-build-log.md`.

**Step 3: Verify DB agrees with state file**

Run:
```python
import asyncio, json
from pathlib import Path
from core.build_orchestrator import BuildOrchestrator
state = json.loads(Path("D:/SHADOW/prior-auth-pro/.foundry-state.json").read_text())
async def go():
    orch = BuildOrchestrator()
    if state.get("project_id"):
        s = await orch.get_status(state["project_id"])
        print(s)
asyncio.run(go())
```

If DB status disagrees with state file, trust DB. Update state file accordingly.

**Step 4: Resume or launch next**

- If `current_module_status == "paused"`: `orch.resume(project_id)` and re-enter Cycle Task B (polling).
- Else: launch next module per Cycle Task A.

---

## Phase 4 — Integration & Submission (Sessions 6-8)

### Task 34: Full stack integration test (Session 6)

**Step 1: Fresh `docker compose up --build`**

Run: `cd D:/SHADOW/prior-auth-pro && docker compose up --build -d`

Wait for all services healthy. Expected: `docker compose ps` shows all services `healthy`.

**Step 2: Seed demo data**

Run: `cd D:/SHADOW/prior-auth-pro && make seed`

Expected: "Seeded 20 FHIR Bundles, 5 payer policy sets" or similar.

**Step 3: Smoke test each demo scenario manually**

For each of: auto-approve, auto-deny, AI-review, appeal-generation, batch-10:
- Navigate to dashboard, trigger scenario
- Verify PipelineView animates
- Verify decision persists in DB (`docker exec backend psql -U postgres -c "SELECT id, status FROM auth_requests ORDER BY id DESC LIMIT 5"`)
- Note any UI or logic glitches. Fix inline via Edit, commit as `fix(e2e): <what>`.

**Step 4: Smoke test A2A endpoint**

Run:
```bash
curl -X POST http://localhost:8000/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"Review auth for CPT 70551 with ICD G35"}]}},"id":1}'
```

Expected: JSON-RPC response with `result.task` containing a task ID.

**Step 5: Smoke test agent card**

Run: `curl http://localhost:8000/.well-known/agent-card.json | jq .`

Expected: Valid JSON with all required Prompt Opinion fields.

### Task 35: Demo rehearsal (Session 7)

**Step 1: Dry run the 3-min demo script**

Follow `docs/DEMO_SCRIPT.md` end-to-end, using a stopwatch. Target ≤3 min.

**Step 2: Identify rough spots**

Common: PipelineView starts too fast to read; confidence gauges too small; dark theme unreadable text. Fix each, commit as `polish: <what>`.

**Step 3: Dry run again** until demo is crisp.

### Task 36: Record demo video (Session 7)

**Step 1: Record**

Tool: OBS / ShareX / Loom. 1080p, 30fps, with voiceover walking through DEMO_SCRIPT timestamps.

**Step 2: Upload**

Upload to YouTube (unlisted) or Loom. Copy the link.

**Step 3: Add link to README and Devpost draft**

Edit `D:/SHADOW/prior-auth-pro/README.md` — add `## Demo` section with thumbnail + link.

### Task 37: Devpost submission draft (Session 7)

**Step 1: Create submission draft on Devpost** (do NOT submit yet)

Fields:
- Title: `PriorAuth Pro`
- Tagline: one sentence
- Inspiration / What it does / How we built it / Challenges / Accomplishments / What's next — drawn from README and design doc
- Tech stack tags: Python, FastAPI, React, TypeScript, Gemini, Google ADK, FHIR, PostgreSQL, Docker
- GitHub link, video link
- Team: solo (Dilip Kumar)

**Step 2: Save draft, don't submit yet** — final review in Task 39.

### Task 38: Final polish (Session 8, morning)

**Step 1: One final pass on README**

Verify: screenshots load, demo link works, architecture diagram visible, quick-start commands copy-paste cleanly.

**Step 2: Run full test suite one last time**

Run: `cd D:/SHADOW/prior-auth-pro/backend && python -m pytest tests/ -q` and `cd D:/SHADOW/prior-auth-pro/frontend && npm run test`

Expected: Both green.

**Step 3: v0.9-alpha tag**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git tag -a v0.9-alpha -m "Pre-submission — all modules complete, buildable, demo recorded"
cd D:/SHADOW/prior-auth-pro && git push origin v0.9-alpha
```

### Task 39: Submit

**Step 1: Final Devpost review with Commander**

Share the draft URL with Commander for one-minute review. Apply any requested edits.

**Step 2: Submit on Devpost**

Click submit. Verify confirmation email.

**Step 3: Tag v1.0 + push**

Run:
```bash
cd D:/SHADOW/prior-auth-pro && git tag -a v1.0 -m "Devpost submission 2026-05-XX"
cd D:/SHADOW/prior-auth-pro && git push origin v1.0
```

**Step 4: Create GitHub Release from v1.0**

Run: `gh release create v1.0 --title "PriorAuth Pro v1.0 — Hackathon Submission" --notes-file docs/DEMO_SCRIPT.md`

**Step 5: Final commit to log**

Append to `docs/foundry-build-log.md`: "SUBMITTED YYYY-MM-DD HH:MM EDT."

Commit + push.

---

## Cross-cutting concerns

### Memory updates

After every session, update project memory:
- `C:/Users/Dilip Kumar/.claude/projects/D--SHADOW-S-CORP/memory/project_hackathon.md` — add current status, next session target.

No memory updates mid-module (too noisy).

### Failure recovery reference

All 6 layers of failure recovery are detailed in **Section 4** of the design doc (`D:/SHADOW/prior-auth-pro/docs/foundry-build-design.md`). When something breaks, look there first — don't re-invent. Hand-finish decision table is in that same section.

### Status line format

Use this compact one-liner when surfacing status to Commander:
```
[M3 · 3/6 · ADK/A2A · Phase 1/2 · Sprint 2/3 · 42% · 18 files · ARCHITECT done, DECOMPOSE starting]
```

Module completion summary:
```
✓ Module 3 complete · ADK/A2A · 22 files, 1,847 LOC · 12 sprints · 0 fallbacks · tagged module_3_complete · pushed
```

### What NOT to do

- No `git add .` during active Foundry sprint — wait for sprint boundary
- No unrelated work during active builds — pure oversight mode
- No "update" or "WIP" commit messages — every commit names module + concrete change
- No pushing baseline + briefs in one commit — keep them separate for audit clarity (already enforced by task order above)
- No rerunning a module just because output is "meh" — if success criteria pass, commit and move on. Polish is Module 6's job.

---

## Success criteria (overall)

The plan succeeds if, by 2026-05-11 23:00 EDT:

1. Public GitHub repo `Dilip-kumar-22/prior-auth-pro` exists with clean commit history showing baseline → 6 module milestones → v1.0
2. `docker compose up` on a fresh machine boots dashboard + backend + postgres
3. Dashboard at `:3000` processes a demo auth request end-to-end with live pipeline animation
4. A2A endpoint at `:8000/a2a` responds to valid JSON-RPC calls
5. Agent card at `:8000/.well-known/agent-card.json` validates against Prompt Opinion schema
6. <3min demo video uploaded and linked from README
7. Devpost submission complete with GitHub link, video link, tech tags
8. README has screenshots, architecture diagram, quick-start, MIT license

Nice-to-have (non-blocking): 90%+ test coverage, full 20-scenario fixture set, publication to Prompt Opinion Marketplace.
