# Foundry Multi-Session Build — PriorAuth Pro

**Date:** 2026-04-19
**Status:** Design approved — ready for implementation plan
**Scope:** Execution strategy for rerunning S-CORP Foundry to complete PriorAuth Pro for the Agents Assemble Healthcare Hackathon
**Companion docs:** [PriorAuth Pro Design](2026-04-12-priorauth-pro-design.md) · [PriorAuth Pro Implementation Plan](2026-04-12-priorauth-pro-implementation.md)

---

## 1. Background

The prior Foundry build (`~/.shadow/workspace/forge_1776001633/`, 2026-04-12) produced 67 quality files (~376 KB) covering the full backend infrastructure — FastAPI, SQLAlchemy 2.0 models, rules engine with real clinical policy data, RAG engine, FHIR R4 client, 12 test files. Two files failed to generate due to repeated Gemini 3.1 Pro 503 errors (`worker/tasks.py`, `tests/test_auth_requests.py`), and several modules were never in scope for that run (reasoning agents, Google ADK / A2A protocol integration, React dashboard, deployment infrastructure, demo polish).

This design covers how we rerun Foundry in **Enterprise mode** (`BuildOrchestrator`) across multiple Claude Code sessions to complete the missing work, with explicit handling for 503 storms, context limits, and the 22-day deadline (submission due 2026-05-11).

---

## 2. Key Decisions Locked In

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Scope** | Preserve the 67 baseline files; Foundry builds only what's missing |
| 2 | **Decomposition** | 6 granular modules (fine-grained blast radius, aligned with natural approval gates) |
| 3 | **Model strategy** | Gemini 3.1 Pro primary everywhere; rely on Foundry's fallback chain (3.1 Pro → 2.5 Pro → 3 Flash → 2.5 Flash) and circuit breaker for 503s |
| 4 | **Session pacing** | Auto-drive multiple modules per session; pause at module boundary when Claude context hits ~70-80% |
| 5 | **Output location** | Build directly in `D:\SHADOW\prior-auth-pro\` via BuildOrchestrator's `workspace_override` config — real-time GitHub backup, authentic per-module commit history |

---

## 3. Section 1 — Pre-Flight Setup

Non-LLM work done at the start of Session 1, before any Foundry call.

### 3.1 Target repo structure

```
D:\SHADOW\prior-auth-pro\
├── .git/                          # git init here
├── .gitignore                     # Python + Node + .shadow/ excludes
├── README.md                      # v0 stub (rewritten by Module 6)
├── LICENSE                        # MIT
├── docs/
│   ├── design.md                  # copy from S-CORP/docs/plans/2026-04-12-priorauth-pro-design.md
│   ├── foundry-build-log.md       # module-by-module progress tracker
│   └── module-briefs/             # input briefs passed to Foundry (one per module)
│       ├── M1-llm-worker-tasks.md
│       ├── M2-clinical-agents.md
│       ├── M3-adk-a2a.md
│       ├── M4-react-dashboard.md
│       ├── M5-deployment.md
│       └── M6-polish.md
├── backend/                       # 67 baseline files land here
│   ├── api/ core/ engines/ fhir/ migrations/ models/ tests/ worker/
│   ├── alembic.ini, .env.example, pytest.ini, requirements.txt
└── .foundry-state.json            # persistent state across Claude sessions
```

### 3.2 Pre-flight tasks

1. **Copy 67 baseline files** from `~/.shadow/workspace/forge_1776001633/` → `D:\SHADOW\prior-auth-pro\backend\`
2. **Delete broken placeholder files** — `worker/tasks.py`, `tests/test_auth_requests.py` (Module 1 rebuilds them)
3. **Fix known issues** — strip the stray `the` on line 13 of `requirements.txt`
4. **Git init + baseline commit** — `baseline: infrastructure from prior Foundry run (67 files, API + models + rules + RAG + FHIR + tests)`
5. **GitHub repo** — create `dilip-kumar-22/prior-auth-pro` public, MIT, push baseline
6. **Initialize `.foundry-state.json`** — persistent session-handoff state file
7. **Foundry readiness smoke test** — verify env vars, `BuildOrchestrator` imports, workspace_override works with a throwaway test project
8. **Write 6 module briefs** — including WebFetched external specs (A2A protocol + Prompt Opinion agent card schema) for M3

### 3.3 `.foundry-state.json` shape

```json
{
  "project_id": "proj_XXXXXXXX",
  "workspace": "D:/SHADOW/prior-auth-pro",
  "modules_completed": [],
  "current_module": null,
  "current_module_status": null,
  "last_session_ended_at": null,
  "last_git_tag": null,
  "notes": []
}
```

**Estimated pre-flight time:** 30-45 minutes.

---

## 4. Section 2 — The 6 Module Briefs

### Module 1 — LLM Worker Tasks (Gemini 3.1 Pro reasoning core)

**Purpose:** Rebuild the two files killed by the prior 503 storm. This is the clinical reasoning engine.

**Files to create:**
- `backend/worker/tasks.py` — ARQ tasks:
  - `process_auth_request_task(ctx, auth_request_id)` — FHIR extract → classify → rules → RAG → Gemini 3.1 Pro decision → `AuthEvent` audit trail
  - `generate_appeal_task(ctx, appeal_id)` — denial context → Gemini 3.1 Pro appeal letter with clinical citations
- `backend/worker/llm_client.py` — Gemini 3.1 Pro/Flash wrapper with structured output (Pydantic schemas)
- `backend/tests/test_auth_requests.py` — missing test file from prior run
- `backend/tests/test_worker_tasks.py` — new, mocked Gemini, full extract→rules→rag→decide flow

**Integrates with:** `engines/rules/`, `engines/rag/`, `fhir/client.py`, `models/auth_request.py`, `models/workflow.py` (uses `AuthEvent` for event sourcing).

**Success criteria:** All 67 existing files still green. New tests pass without real Gemini calls.

### Module 2 — Clinical Agents Layer

**Purpose:** Refactor Module 1's flat worker tasks into structured agent classes (prep for ADK/A2A in Module 3).

**Files to create:**
- `backend/agents/__init__.py`
- `backend/agents/base.py` — abstract `BaseAgent`
- `backend/agents/orchestrator.py` — router (Gemini 3.1 Pro, classifies intent and dispatches)
- `backend/agents/extraction.py` — FHIR → structured clinical summary (Gemini 3.1 Flash)
- `backend/agents/auth.py` — prior auth decision (Gemini 3.1 Pro)
- `backend/agents/appeal.py` — appeal letter generation (Gemini 3.1 Pro)
- `backend/agents/prompts/*.md.j2` — externalized jinja2 prompt templates
- `backend/tests/test_agents/` — one test file per agent

**Integrates with:** `worker/llm_client.py` (Module 1), existing models.

**Success criteria:** Each agent callable in isolation. No hardcoded prompt strings. All tests pass.

### Module 3 — ADK / A2A Integration (hackathon requirement)

**Purpose:** Wrap Module 2's agents in Google ADK + A2A protocol so Prompt Opinion can discover and invoke them.

**Files to create:**
- `backend/adk/__init__.py`
- `backend/adk/server.py` — ADK server, binds to `/a2a`
- `backend/adk/handlers.py` — A2A JSON-RPC handlers (`send`, `get`, `cancel`, `sendSubscribe`)
- `backend/adk/agent_card.py` — Prompt Opinion agent card descriptor
- `backend/adk/fhir_context.py` — FHIR Bundle decoder from A2A message metadata
- `backend/prompt-opinion-manifest.yaml` — publishing manifest
- `backend/tests/test_adk/` — protocol conformance tests

**External inputs (fetched pre-flight, pasted inline into brief):** A2A JSON-RPC spec, Prompt Opinion agent card schema, FHIR context extension URI conventions.

**Integrates with:** `agents/orchestrator.py` is the A2A entry point.

**Success criteria:** `curl`-able A2A endpoint. Agent card validates. Conformance tests pass.

### Module 4 — React Dashboard (demo centerpiece)

**Purpose:** Clinician-facing UI and the <3min demo video's visual core.

**Files to create:** full React 18 + TypeScript + Vite + Tailwind + shadcn/ui app under `frontend/`:
- `frontend/src/pages/` — Dashboard, AuthRequestDetail, AppealEditor, Queue
- `frontend/src/components/PipelineView.tsx` — **the money shot**: animated EXTRACT → CLASSIFY → RULES → RAG → DECIDE with per-node confidence gauges, latency badges, citation drawers
- `frontend/src/components/ConfidenceQueues.tsx` — split view (auto-approved / flagged / pended)
- `frontend/src/components/ImpactWidget.tsx` — manual vs AI metrics comparison
- `frontend/src/components/BatchRunner.tsx` — 10-parallel-request demo trigger
- `frontend/src/lib/websocket.ts` — WebSocket client for live pipeline updates
- `frontend/src/lib/api.ts` — typed REST client (openapi-typescript generated)
- Vitest + Testing Library suite

**Design language:** Dark medical-grade theme (deep navy/charcoal, teal/cyan active states, amber warnings).

**Integrates with:** backend REST + WebSocket (not A2A — A2A is for Prompt Opinion, not clinicians).

**Success criteria:** `npm run dev` renders all 4 pages. Pipeline animation triggers on a real auth request. Dark theme consistent.

### Module 5 — Deployment Infrastructure

**Purpose:** One-command deploy. Docker Compose stack + CI.

**Files to create:**
- `docker-compose.yml` — postgres (pgvector:pg16) + backend + frontend
- `backend/Dockerfile`, `frontend/Dockerfile`, `.dockerignore` (both)
- `Makefile` — `up`, `down`, `test`, `seed`, `demo`
- `.github/workflows/ci.yml` — ruff + eslint + pytest + vitest + docker build + GHCR push
- `scripts/seed_demo_data.py` — 20 synthetic FHIR cases + payer policies
- `.env.example` (root)

**Success criteria:** `docker compose up` boots cleanly. Dashboard at `:3000`, backend at `:8000`. CI green.

### Module 6 — Polish & Integration

**Purpose:** Everything needed for a hackathon-quality submission.

**Files to create:**
- `backend/tests/test_e2e/` — full user journeys (auto-approve, auto-deny, AI-review, appeal, batch-10)
- `backend/tests/fixtures/` — 20 synthetic FHIR Bundles (all 4 specialties + edge cases)
- `backend/tests/fixtures/payer_policies/` — 5 payer policy sets (UH, Aetna, Cigna, BCBS, Humana)
- `docs/DEMO_SCRIPT.md` — 3-minute walkthrough with timestamps
- `docs/ARCHITECTURE.md`, `docs/FHIR_INTEGRATION.md`, `docs/APPEAL_EXAMPLES.md`
- `README.md` (rewritten) — quick-start, screenshots, demo GIF, architecture diagram, judging-criteria mapping
- `CONTRIBUTING.md`, `SECURITY.md` (HIPAA-aware notes, PHI handling, audit trail)

**Success criteria:** E2E tests pass. README renders cleanly with screenshots. Demo script runs end-to-end.

### Scope totals

**Additional files across all 6 modules:** ~80-120 files, ~5,000-7,000 LOC on top of the 67-file baseline. Reasoning-heavy content (prompts, E2E scenarios, appeal examples) ≈ 30%; structured code ≈ 70%.

---

## 5. Section 3 — Orchestration Loop

### Session 1 (today)

1. Execute all Section 1 pre-flight (~30-45 min)
2. Write all 6 module briefs to `docs/module-briefs/` (~45 min, includes WebFetch of A2A + Prompt Opinion docs for M3)
3. Commit pre-flight work, push
4. Kick off Foundry with Module 1 brief:
   ```python
   orch = BuildOrchestrator()
   project = await orch.plan(
       request="<M1 brief contents>",
       config={
         "workspace_override": "D:/SHADOW/prior-auth-pro",
         "build_model": "gemini/gemini-3.1-pro",
         "project_name": "prior-auth-pro-module-1"
       }
   )
   await orch.start(project.id)
   ```
5. Poll `orch.get_status(project_id)` every ~45s, surface compact status lines to Commander
6. On Module completion: auto-commit, push to GitHub, plan + start next module
7. At ~70-80% context: `orch.pause(project_id)`, update state file, end session

**Expected Session 1 outcome:** Modules 1 + 2 complete, possibly M3 started.

### Session 2+ resume flow

Opening moves (automated):
1. Read `.foundry-state.json`
2. `git log --oneline -20` + `git tag --sort=-creatordate | head` to verify state matches disk
3. Confirm with Commander in one sentence
4. `orch.resume(project_id)` if paused mid-module, or `orch.plan(next_brief) + orch.start()` for fresh module
5. Same pause-at-context-limit loop

**State DB is source of truth** (`~/.shadow/data/build_orchestrator.db`). `.foundry-state.json` is Claude-facing convenience. If they disagree, DB wins.

### During active builds

- Poll every ~45s, surface status every ~5 min
- Watch for stalls (>5 min with no sprint state change + open circuit breaker → investigate)
- Watch for 503 fallback events on reasoning-critical files, flag them
- Tail `BUILD_JOURNAL.md`
- Don't do unrelated work

### Status line format

```
[M3 · Module 3/6 · ADK/A2A · Phase 1/2 · Sprint 2/3 · 42% complete · 18 files · last event: ARCHITECT done, DECOMPOSE starting]
```

Module completion summary:
```
✓ Module 3 complete · ADK/A2A · 22 files, 1,847 LOC · 3 phases · 12 sprints · 0 fallback events · git tag module_3_complete · pushed
```

### Session handoff

End-of-session checklist:
1. `orch.pause(project_id)` if mid-module
2. Write state to `.foundry-state.json`
3. Commit + push state file and any build log entries
4. Brief Commander with modules done, remaining, quality concerns, recommended next session start

Start-of-session checklist (first 3 actions):
1. Read `.foundry-state.json`
2. Read last 10 entries of `docs/foundry-build-log.md`
3. Verify `orch.get_status(project_id)` matches state file

---

## 6. Section 4 — 503 & Failure Recovery

### Layer 1 — Automatic (Foundry built-in)

- Per-request retry with exponential backoff (3× on primary)
- Model fallback chain: 3.1 Pro → 2.5 Pro → 3 Flash → 2.5 Flash
- Circuit breaker: 5 failures / 60s → OPEN 60s → HALF_OPEN probe → CLOSED
- Rate limit self-throttling (150 RPM/model)

### Layer 2 — Per-file failure

Foundry writes `# LLM error: ...` comment and continues. Claude:
1. Grep workspace for `# LLM error:` at each sprint boundary
2. Classify: transient 503 → queue for retry; systemic overload → pause + wait 10-15 min + resume; content filter → revise brief
3. At module end: `orch.retry_sprint(sprint_id)` on queued failures
4. **Escape hatch:** 3+ failed retries → hand-write the single file, flag in session notes

### Layer 3 — Sprint failure

Sprint never completes. Claude:
1. Read error from DB + `BUILD_JOURNAL.md`
2. Classify: brief too vague → rewrite brief; missing external spec → gather + paste inline → retry; true Foundry bug → abandon, hand-write scope
3. Always communicate brief changes to Commander before retrying

### Layer 4 — Module failure

Multiple sprints failed, architecture broken. Claude:
1. `orch.pause(project_id)`
2. Tell Commander plainly: what it produced, why it's broken, 3 options
3. Options: nuke + retry with new brief / hand-finish module / reduce scope
4. Proceed on Commander's call — no silent success

### Layer 5 — Claude context limit mid-build

Mid-sprint emergency: `orch.pause()`, commit state with `"paused_mid_sprint"`, end session. BuildOrchestrator resume handles mid-sprint state.

Worst case: lose ~1 sprint (~5-10 files), Foundry regenerates on resume.

### Layer 6 — Catastrophic failure

| Failure | Recovery |
|---------|----------|
| State DB corrupt | Reconstruct from `git log` + workspace listing |
| Workspace disk corrupt | Re-clone from GitHub (last module pushed), re-run in-progress module only |
| Gemini keys revoked | Rotate in `.env`, smoke test, resume. Zero code lost. |
| Foundry itself breaks | Patch if small; else hand-finish remaining modules with subagents |

### Hand-finish decision table

| Situation | Default action |
|-----------|---------------|
| 1-2 files failed, rest of sprint clean | Targeted retry |
| Single sprint failed, brief fine | Retry once, then hand-finish |
| Multiple sprints failing in a module | Pause, show options, get decision |
| Module failed completely | Hand-finish or reduce scope (Commander's call) |
| 503 storm >30 min, all models rate-limited | Pause, wait for off-peak, resume |
| **<5 days to deadline, any module failing** | **Hand-finish by default** |

---

## 7. Section 5 — Git & GitHub Strategy

### Branch strategy

`master`-only. Git tags as audit trail.

Tag pattern:
```
baseline                          # pre-flight commit
phase_M1_phase_0_<ts>             # Foundry-generated per phase
phase_M1_phase_1_<ts>
module_1_complete                 # Claude-added per module
...
module_6_complete
v0.9-alpha                        # first polish pass done
v1.0                              # Devpost submission
```

### Commit cadence

| Event | Author | Message format |
|-------|--------|---------------|
| Pre-flight baseline | Claude | `baseline: infrastructure from prior Foundry run (67 files)` |
| Foundry sprint | Foundry | `feat(MN): sprint N — <scope>` |
| Foundry phase | Foundry | `chore(MN): phase N complete` + tag |
| Module done | Claude | `feat: module N complete — <summary>` + tag |
| Hand-finished file | Claude | `fix(MN): hand-finish <file> (Foundry fallback)` |
| Session end mid-build | Claude | `session end: MN paused at sprint X/Y` |
| Brief revision | Claude | `docs(briefs): revise MN brief — <reason>` |

**Rule:** no "WIP" or "update" messages. Every commit names a module and concrete change.

### Push cadence

- After baseline (immediately)
- After every module completion (main backup event)
- At session end (state file + log updates)
- After hand-finished files (don't batch)

**Don't** push on every Foundry phase tag — too noisy. Module boundaries are right granularity.

### GitHub repo settings

- Name: `prior-auth-pro`
- Visibility: Public (hackathon requirement)
- License: MIT
- Topics: `healthcare`, `ai-agents`, `gemini`, `fhir`, `prior-authorization`, `a2a-protocol`, `hackathon`
- Default branch: `master`
- Enable: Actions, Issues
- Disable: Wiki, Projects, Discussions

### `.gitignore` excludes

`node_modules/`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `*.pyc`, `.env`, `.DS_Store`, demo video file, `~/.shadow/` workspace artifacts. Screenshots kept under 500KB each.

### Concurrency safety

Foundry's git calls are serialized (`build_orchestrator.py` line 557-565). Claude never `git add .` during active sprint — only at sprint/module boundaries when Foundry idle.

### Submission push (end of Module 6)

1. `git tag v0.9-alpha` → push
2. E2E test (Docker compose, demo scenarios)
3. Record 3-minute demo video → upload (YouTube/Loom) → link in README + Devpost
4. Devpost submission form
5. Final commit: `release: v1.0 Devpost submission` → `git tag v1.0` → push
6. GitHub Release from v1.0 with notes matching Devpost
7. Submit on Devpost before 2026-05-11 23:00 EDT

Target: **everything done by 2026-05-08** (3-day buffer).

---

## 8. Section 6 — Timeline & Deadline Math

### Fixed dates

| Date | Event |
|------|-------|
| 2026-04-19 (today) | Session 1 — pre-flight + M1 + M2 |
| 2026-05-08 | Internal deadline — buildable + demo recorded |
| 2026-05-09 to 10 | Buffer for polish |
| **2026-05-11 23:00 EDT** | **Devpost submission deadline (hard)** |
| ~2026-05-27 | Winners announced |

### Projected session schedule

| # | Target date | Scope | Duration | Modules done |
|---|-------------|-------|----------|--------------|
| 1 | 2026-04-19 | Pre-flight + M1 + M2 | 4-6h | M1, M2 |
| 2 | 2026-04-21 | M3 + M4 start | 4-5h | M3 |
| 3 | 2026-04-24 | M4 finish | 4-5h | M4 |
| 4 | 2026-04-27 | M5 + M6 start | 3-4h | M5 |
| 5 | 2026-04-30 | M6 | 3-4h | M6 |
| 6 | 2026-05-03 | Integration testing + demo rehearsal | 2-3h | — |
| 7 | 2026-05-06 | Demo video + Devpost submission draft | 2-3h | — |
| 8 | 2026-05-08 | Final polish, submit early | 1-2h | **Submitted** |

### Slack analysis

- Total estimated work: ~25-30 hours across 8 sessions
- If every session hits target: submission ready May 8 (3 days early)
- If 2 sessions slip: submission ready May 11 morning (same-day, tight)
- If 4 sessions slip: hand-finish remaining modules starting ~May 5

Plan survives 4 bad sessions and still ships.

### Red-flag escalation triggers

| Trigger | Action |
|---------|--------|
| Any module takes >2 sessions | Pause, reassess scope, consider hand-finishing |
| Same file fails Foundry 3+ times | Hand-finish that file |
| Gemini 3.1 Pro unavailable >4h straight | Switch that module to 2.5 Pro primary |
| May 3 without M4 done | Cut scope: drop `BatchRunner` + `ImpactWidget`, keep `PipelineView` only |
| May 6 without M6 done | Skip extended docs (keep README + DEMO_SCRIPT only), ship |
| May 8 without build complete | Stop Foundry, hand-finish everything, ship what works |

### Submission success criteria (May 11)

Required:
1. Public GitHub repo with clean commit history
2. `docker compose up` works on fresh machine
3. Dashboard renders + processes demo auth request end-to-end
4. A2A endpoint responds to Prompt Opinion protocol calls
5. Agent card validates against Prompt Opinion schema
6. <3min demo video uploaded
7. Devpost submission form complete
8. README has screenshots, architecture diagram, quick-start

Nice-to-have (non-blocking):
- 90%+ test coverage
- All 6 modules as originally scoped
- Full 20-scenario demo fixture set
- Published to Prompt Opinion Marketplace (if platform allows before results)

---

## 9. Next step

Transition to **writing-plans skill** to create the executable implementation plan. The plan will break Section 1 pre-flight + Section 2 module briefs into numbered, actionable tasks with exact commands, file paths, success criteria — the artifact Claude executes from in each session.

Plan will land at `docs/plans/2026-04-19-foundry-multi-session-implementation.md`.
