# PriorAuth Pro — Design Document

**Date**: 2026-04-12
**Project**: Agents Assemble Healthcare AI Hackathon
**Deadline**: 2026-05-11
**Target**: 1st Place ($7,500)

---

## 1. Product Identity & Scope

**Name**: PriorAuth Pro

**One-liner**: An enterprise-grade AI agent that automates prior authorization workflows — from initial FHIR data extraction through clinical evidence matching, auth decision generation, and denial appeal creation — published on the Prompt Opinion marketplace via A2A protocol.

**Specialties covered** (multi-specialty):
- **Medications** — high-cost drugs, specialty pharmacy, step therapy
- **Imaging/Radiology** — MRI, CT, PET scans
- **Procedures/Surgery** — elective procedures, outpatient surgery
- **DME** — durable medical equipment (wheelchairs, CPAP, prosthetics)

**Core workflow**:
```
Clinician triggers auth request (via Prompt Opinion or dashboard)
    |
1. EXTRACTION  — Gemini 3.1 Flash pulls relevant FHIR data
                  (Patient, Condition, MedicationRequest, Procedure,
                   Observation, Coverage, DocumentReference)
    |
2. CLASSIFICATION — Identify auth type (med/imaging/procedure/dme)
                    + payer + plan + service requested
    |
3. RULES CHECK — Deterministic policy engine matches against
                  structured payer criteria -> instant approve/deny
                  if clear match
    |
4. AI REASONING — For edge cases: Gemini 3.1 Pro analyzes clinical
                   evidence against guidelines (RAG), generates
                   determination with cited evidence
    |
5. DECISION — Approve / Deny / Pend (need more info)
    |
6. APPEAL (if denied) — Gemini 3.1 Pro generates counter-evidence
                         letter citing clinical guidelines, patient
                         history, and medical necessity
    |
7. TRACKING — Dashboard shows real-time status, audit trail,
               evidence chain, time-to-decision metrics
```

**Key differentiators**:
- Rules-first approach (fast, deterministic) with AI fallback (intelligent)
- Full audit trail with cited evidence — critical for healthcare compliance
- Appeal generation with clinical guideline citations
- Multi-specialty coverage
- Production-ready FHIR integration via Prompt Opinion's credential bridging

---

## 2. Agent Architecture

```
+----------------------------------------------------------+
|                    PROMPT OPINION PLATFORM                |
|         (A2A JSON-RPC + FHIR context in metadata)        |
+----------------------------+-----------------------------+
                             |
+----------------------------v-----------------------------+
|              ORCHESTRATOR AGENT (router)                  |
|  - Receives A2A messages from Prompt Opinion             |
|  - Classifies intent (new auth / status check / appeal)  |
|  - Routes to specialist agent                            |
|  - Aggregates responses                                  |
|  - Model: Gemini 3.1 Flash (lightweight routing)         |
+-----+----------------+----------------+-----------------+
      |                |                |
+-----v------+  +------v-------+  +----v--------+
| EXTRACTION |  | AUTH         |  | APPEAL      |
| AGENT      |  | AGENT        |  | AGENT       |
|            |  |              |  |             |
| Gemini 3.1 |  | Gemini 3.1  |  | Gemini 3.1 |
| Flash      |  | Pro          |  | Pro         |
|            |  |              |  |             |
| - FHIR     |  | - Rules      |  | - Denial    |
|   query    |  |   engine     |  |   analysis  |
| - Parse    |  | - RAG        |  | - Counter   |
| - Norm-    |  |   lookup     |  |   evidence  |
|   alize    |  | - Clinical   |  | - Letter    |
| - Clas-    |  |   reasoning  |  |   gen       |
|   sify     |  | - Decision   |  | - Guideline |
|            |  |   + evidence |  |   citation  |
+-----+------+  +------+-------+  +----+--------+
      |                |                |
+-----v----------------v----------------v-----------------+
|                    SHARED LAYER                          |
|  +----------+  +-----------+  +-----------+  +--------+ |
|  | FHIR     |  | RULES     |  | RAG       |  | AUDIT  | |
|  | CLIENT   |  | ENGINE    |  | ENGINE    |  | LOGGER | |
|  |          |  |           |  |           |  |        | |
|  | R4 API   |  | Payer     |  | pgvector  |  | Every  | |
|  | Patient  |  | policies  |  | CMS/USPSTF|  | decide | |
|  | Cond.    |  | CPT/ICD   |  | guidelines|  | logged | |
|  | MedReq   |  | matching  |  | Embeddings|  | with   | |
|  | Proc.    |  | Auto-     |  | via Gemini|  | evid.  | |
|  | Coverage |  | approve   |  |           |  | chain  | |
|  +----------+  +-----------+  +-----------+  +--------+ |
+----------------------------+-----------------------------+
                             |
+----------------------------v-----------------------------+
|              REST API (FastAPI)                           |
|  /api/auth-requests    - CRUD + status                   |
|  /api/appeals          - create/track appeals            |
|  /api/dashboard        - metrics, analytics              |
|  /api/audit-trail      - decision history + evidence     |
|  /api/guidelines       - browse loaded policies          |
+----------------------------+-----------------------------+
                             |
+----------------------------v-----------------------------+
|              REACT DASHBOARD                             |
|  - Auth request queue (real-time status)                 |
|  - Decision detail view (evidence chain + citations)     |
|  - Appeal workspace (edit + submit)                      |
|  - Analytics (time-to-decision, approval rates, etc.)    |
|  - Audit log viewer                                      |
+----------------------------------------------------------+
```

**Agent communication**: Orchestrator uses Google ADK's `AgentTool` to delegate to specialist agents. Internal communication stays in-process (modular monolith), external communication with Prompt Opinion uses A2A JSON-RPC.

**Data flow for a new auth request**:
1. Prompt Opinion sends A2A message with FHIR context in metadata
2. `shared/middleware.py` extracts FHIR credentials -> session state
3. Orchestrator classifies intent -> routes to extraction agent
4. Extraction agent queries FHIR server -> returns normalized patient data
5. Orchestrator passes extracted data -> auth agent
6. Auth agent runs rules engine first -> if clear match, instant decision
7. If ambiguous -> RAG lookup for clinical guidelines -> Gemini 3.1 Pro reasons through evidence -> decision with citations
8. Decision + full evidence chain logged to audit trail (event store)
9. Response sent back via A2A to Prompt Opinion
10. Dashboard updated via WebSocket

---

## 3. Data Models & Storage

**Database**: PostgreSQL 16 + pgvector extension (single DB for relational + vector)

### Event-Sourced Architecture

Every state transition is an event. The auth request's current state is derived from its event history. The audit trail IS the data.

```
AuthRequest
  id                  UUID (PK)
  patient_id          VARCHAR (from FHIR)
  auth_type           ENUM (medication | imaging | procedure | dme)
  service_requested   VARCHAR (CPT/HCPCS code + description)
  diagnosis_codes     JSONB (list of ICD-10)
  payer_id            VARCHAR
  plan_id             VARCHAR
  priority            ENUM (urgent | standard)
  fhir_bundle         JSONB (raw FHIR response — preserved for compliance)
  created_at          TIMESTAMP
  updated_at          TIMESTAMP
  -- Status, decision, evidence are derived from AuthEvent history

AuthEvent (single source of truth)
  id                  UUID (PK)
  auth_request_id     UUID (FK -> AuthRequest)
  event_type          ENUM (created | data_extracted | classified |
                            rule_matched | rule_no_match | rag_queried |
                            decision_made | appealed | appeal_resolved |
                            flagged_for_review | clinician_override)
  agent_name          VARCHAR
  model_used          VARCHAR (gemini-3.1-pro | gemini-3.1-flash)
  payload             JSONB (full input/output snapshot)
  confidence_score    FLOAT (0-1)
  latency_ms          INTEGER
  timestamp           TIMESTAMP

PayerPolicy (rules engine)
  id                  UUID (PK)
  payer_name          VARCHAR
  policy_code         VARCHAR (unique)
  service_category    ENUM (medication | imaging | procedure | dme)
  cpt_codes           JSONB (list)
  icd10_required      JSONB (diagnoses that auto-qualify)
  documentation_req   JSONB (what must be submitted)
  auto_approve        JSONB (deterministic approval criteria)
  auto_deny           JSONB (deterministic denial criteria)
  requires_ai_review  BOOLEAN (edge case flag)
  effective_date      DATE
  expiry_date         DATE

Appeal
  id                  UUID (PK)
  auth_request_id     UUID (FK -> AuthRequest)
  denial_reason       TEXT (original)
  counter_evidence    JSONB (generated citations)
  appeal_letter       TEXT (generated)
  guidelines_cited    JSONB (list of references)
  status              ENUM (draft | submitted | under_review | resolved)
  outcome             ENUM (overturned | upheld | NULL)
  created_at          TIMESTAMP

WorkflowStep
  id                  UUID (PK)
  auth_request_id     UUID (FK -> AuthRequest)
  step_type           ENUM (extraction | classification | rules_check |
                            rag_lookup | reasoning | decision)
  status              ENUM (queued | running | completed | failed)
  agent_name          VARCHAR
  started_at          TIMESTAMP
  completed_at        TIMESTAMP
  input_hash          VARCHAR (integrity verification)
  output_hash         VARCHAR
  retry_count         INTEGER DEFAULT 0
```

### Vector Store (pgvector)

Collections stored as tables with `vector(768)` columns:
- `cms_guidelines` — CMS National/Local Coverage Determinations
- `uspstf_recommendations` — preventive care guidelines
- `clinical_criteria` — InterQual/MCG-style clinical criteria (synthetic)
- `drug_formularies` — formulary tier + step therapy rules

### Seed Data

Synthetic payer policies and clinical guidelines covering all 4 specialties. No real PHI. FHIR data from Prompt Opinion credential bridging or HAPI FHIR public test server.

---

## 4. Tech Stack & Project Structure

### Tech Stack

```
BACKEND (Python 3.11+)
  Framework:      Google ADK (Agent Development Kit) - A2A protocol
  API:            FastAPI + Uvicorn - REST for dashboard
  LLMs:           Gemini 3.1 Pro (reasoning) + Gemini 3.1 Flash (extraction)
  Database:       PostgreSQL 16 + pgvector extension
  ORM:            SQLAlchemy 2.0 (async) + Alembic (migrations)
  Embeddings:     Gemini embedding model -> pgvector
  FHIR Client:    fhir.resources (Pydantic FHIR R4 models)
  Validation:     Pydantic v2 (data models + API schemas)
  WebSocket:      FastAPI WebSocket (live dashboard updates)
  Testing:        pytest + pytest-asyncio
  Linting:        ruff

FRONTEND (React Dashboard)
  Framework:      React 18 + TypeScript + Vite
  UI:             Tailwind CSS + shadcn/ui
  State:          Zustand
  Charts:         Recharts
  Real-time:      WebSocket
  Icons:          Lucide React

INFRASTRUCTURE
  Containers:     Docker Compose (3 services)
    agent         Python backend - A2A + REST API
    dashboard     React - nginx served
    postgres      pgvector/pgvector:pg16
  Dev:            honcho (run all services locally)
  CI:             GitHub Actions (lint + test)

PROMPT OPINION INTEGRATION
  Protocol:       A2A JSON-RPC (agent-to-agent)
  FHIR Context:   metadata extension URI -> beforeModelCallback -> session state
  Auth:           X-API-Key header validation
  Discovery:      /.well-known/agent-card.json
  Publish:        Agent Card URL registered on PO Marketplace
```

### Project Structure

```
prior-auth-pro/
  agents/
    orchestrator/
      agent.py              Google ADK Agent - routes intents
      tools.py              classify_intent, route_request
    extraction/
      agent.py              Gemini 3.1 Flash - FHIR data pull
      tools.py              query_patient, extract_clinical_data
    auth/
      agent.py              Gemini 3.1 Pro - auth decisions
      tools.py              check_rules, lookup_guidelines, make_decision
    appeal/
      agent.py              Gemini 3.1 Pro - appeal generation
      tools.py              analyze_denial, generate_appeal_letter
  engines/
    rules/
      engine.py             deterministic policy matcher
      policies.py           payer policy loader
      seed_data/            synthetic payer policies JSON
    rag/
      engine.py             pgvector search + reranking
      ingest.py             guideline ingestion pipeline
      guidelines/           CMS/USPSTF/clinical criteria docs
  fhir/
    client.py               async FHIR R4 client
    resources.py            Patient, Condition, MedRequest handlers
    context.py              FHIR credential extraction from A2A
  models/
    database.py             SQLAlchemy engine + session
    auth_request.py         AuthRequest + AuthEvent
    payer_policy.py         PayerPolicy
    appeal.py               Appeal
    workflow.py             WorkflowStep
  api/
    main.py                 FastAPI app - REST + WebSocket
    routes/
      auth_requests.py
      appeals.py
      dashboard.py
      audit.py
    schemas/                Pydantic request/response schemas
  shared/                   from po-adk-python
    middleware.py            API key + FHIR metadata bridging
    fhir_hook.py            beforeModelCallback
    app_factory.py          A2A ASGI app builder
    logging_utils.py
  dashboard/                React app
    src/
      components/
        AuthQueue.tsx
        DecisionDetail.tsx
        PipelineView.tsx
        AppealWorkspace.tsx
        Analytics.tsx
        AuditLog.tsx
        ImpactMetrics.tsx
        BatchRunner.tsx
      stores/
      services/
      App.tsx
    package.json
    vite.config.ts
  migrations/               Alembic
  tests/
    test_extraction.py
    test_rules_engine.py
    test_rag_engine.py
    test_auth_agent.py
    test_appeal_agent.py
    test_api.py
  docker-compose.yml
  Procfile                  honcho - local dev
  requirements.txt
  .env.example
  README.md
```

---

## 5. Differentiator Features

### 5A: Explainable AI Pipeline View

Real-time horizontal pipeline visualization animating as the agent processes:

```
[EXTRACT] --> [CLASSIFY] --> [RULES CHECK] --> [RAG LOOKUP] --> [DECIDE]
```

Each node:
- Pulses green when complete, spins when active, grey when queued
- Expands on click to show: input/output data, model used, confidence gauge, time taken, citations
- Animates left-to-right via WebSocket in real time

### 5B: Confidence-Based Human-in-the-Loop

```
Confidence >= 90%  ->  AUTO-APPROVE/DENY (green: "High Confidence")
Confidence 70-89%  ->  AUTO-DECIDE + FLAG (yellow: "Review Recommended")
Confidence < 70%   ->  PEND (red: "Clinician Review Required")
```

Split view: auto-processed on left, flagged for review on right. Clinician can approve, override, or request more evidence. Every interaction logged.

### 5C: Impact Comparison Widget

Live metrics card:
- Manual process: 45 min, 3 calls, 2 faxes, $31/case
- PriorAuth Pro: 34 sec, 0 calls, 0 faxes, $0.04/case
- Updates in real-time from actual processing data
- Shows daily totals: requests processed, time saved, estimated annual savings

### 5D: Batch Processing Mode

- "Demo: 10 synthetic cases" button
- Dashboard grid fills with rows, each showing mini pipeline
- Parallel processing via asyncio
- Summary card: "10 requests, 7 approved, 2 denied, 1 flagged — 48 seconds"

---

## 6. Dashboard Design

**Theme**: Medical-grade dark UI (Bloomberg Terminal meets Epic Systems)

- **Background**: Deep navy `#0a0f1e`
- **Accents**: Electric blue `#3b82f6`
- **Approved**: Green `#22c55e`
- **Denied**: Red `#ef4444`
- **Flagged**: Amber `#f59e0b`
- **Typography**: Inter

**Pages**:
- Auth Queue — main view with pipeline, request list, decision detail, impact metrics
- Analytics — charts (approval rates, time trends, payer breakdown)
- Appeals — appeal workspace (generate/edit/track)
- Audit Log — full event history (searchable, filterable)
- Policy Browser — loaded payer policies + guidelines
- Settings — API keys, FHIR config, model preferences

---

## 7. Testing Strategy

**Unit tests**: Rules engine, RAG engine, FHIR client, data models in isolation.

**Integration tests**: Each agent pipeline end-to-end (extraction, auth, appeal, orchestrator).

**Scenario tests**: Full workflows with realistic clinical cases:
- Auto-approve (MRI with clear indication)
- Auto-deny (cosmetic exclusion)
- AI-review (edge case requiring reasoning)
- Appeal flow (denial -> appeal -> counter-evidence)
- Batch (10 concurrent requests)
- Human-in-the-loop (low confidence flagging)

**Test data**: Synthetic FHIR Bundles covering all 4 specialties. No real PHI.

---

## 8. Deployment & Publishing

**Local dev**: `docker compose up --build` (postgres + agent + dashboard)

**Production**: Railway or Fly.io (Docker, free tier, managed Postgres)

**Agent Card**: Published to Prompt Opinion Marketplace at `/.well-known/agent-card.json`

**Demo video** (<3 min):
```
0:00-0:20  Problem statement ($31B/year, 45 min per case)
0:20-0:40  Architecture overview (multi-agent + dual engine)
0:40-1:30  Live demo: single auth request through pipeline
1:30-2:00  Live demo: batch mode (10 requests)
2:00-2:20  Appeal generation with citations
2:20-2:40  Impact metrics + human-in-the-loop
2:40-3:00  Prompt Opinion integration + closing
```

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Track | A2A Full Agent | Higher AI Factor score, uses Google ADK natively |
| Use case | Prior Authorization | Biggest pain point ($31B/year), resonates with all judges |
| Architecture | Modular Monolith | Enterprise code quality + simple deployment |
| Repo | Standalone (fork po-adk-python) | Clean separation from S-CORP |
| Models | Gemini 3.1 Pro + Flash + RAG | Multi-model shows production thinking |
| Auth engine | Rules + RAG dual engine | Deterministic + intelligent reasoning |
| Database | PostgreSQL + pgvector | Single DB for relational + vector |
| Audit | Event-sourced | Tamper-evident, compliance-ready |
| Dashboard | Standalone React | Polished UI wins demos |
| Deployment | Docker Compose (3 services) | Simple, reproducible |
