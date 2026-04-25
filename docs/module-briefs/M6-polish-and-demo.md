# Module 6 — Polish, Fixtures & Demo Materials

## Purpose

Final mile: hackathon judges and demo viewers see a polished, plausible system. End-to-end test coverage proves it works. Fixtures fill the dashboard with realistic content. Documentation explains the architecture, the FHIR integration, and the appeal workflow. The DEMO_SCRIPT.md is the literal recording script for the submission video.

This module produces no new application logic — it's tests, fixtures, and prose.

## Existing repo context

After M1-M5:
- Backend agents + ADK working
- React dashboard rendering
- Docker Compose stack runnable
- `seed_demo_data.py` exists but only has placeholder fixtures

What's missing: realistic fixtures, the E2E test that proves the demo path, and the documents that turn this from "code on disk" into a "submission-ready hackathon project."

## Files to create

### 1. `backend/tests/fixtures/fhir_bundles/` — 20 realistic FHIR R4 Bundles

Five clinical scenarios, four bundles each, with variation in patient demographics, severity, and prior treatment history:

| Scenario | Drug/Procedure | Expected outcome |
|----------|----------------|------------------|
| **Oncology (4 bundles)** | Pembrolizumab for NSCLC | 2 auto-approve (criteria met), 1 ai-review (close call), 1 auto-deny (PD-L1 < 1%) |
| **Cardiac imaging (4)** | Cardiac MRI for HCM | 3 auto-approve, 1 ai-review (incomplete documentation) |
| **Orthopedic (4)** | Total knee arthroplasty | 2 auto-approve, 1 ai-review, 1 auto-deny (BMI threshold) |
| **Mental health (4)** | Esketamine for TRD | 1 auto-approve, 2 ai-review, 1 auto-deny (insufficient SSRI trials) |
| **Pediatric specialty (4)** | Growth hormone for ISS | 1 auto-approve, 2 ai-review (height percentile borderline), 1 auto-deny |

Each bundle includes: Patient, Condition (ICD-10 + SNOMED), MedicationRequest or ServiceRequest (CPT/HCPCS), Encounter, Practitioner, Coverage, and 2-3 Observations supporting the diagnosis.

Generate with a small Python helper `scripts/generate_fhir_fixtures.py` that uses the `fhir.resources` library — deterministic from seed values for reproducibility.

Naming: `{scenario}-{seq}-{expected_outcome}.json` e.g. `oncology-01-approve.json`, `cardiac-03-aireview.json`.

### 2. `backend/tests/fixtures/policies/` — 5 payer policies

Each policy is a JSON document with:
```json
{
  "payer_id": "aetna",
  "policy_id": "ONCOLOGY-2025-PEMBROLIZUMAB",
  "title": "Aetna 2025 Oncology — Pembrolizumab Coverage",
  "effective_date": "2025-01-01",
  "rules": [
    {
      "rule_id": "PEMBRO-01",
      "type": "auto_approve_if",
      "criteria": [
        {"resource": "Condition", "code": "C34.90", "system": "icd10"},
        {"resource": "Observation", "code": "PD-L1", "value_op": ">=", "value": 50},
        {"resource": "Observation", "code": "ECOG", "value_op": "<=", "value": 1}
      ]
    },
    {
      "rule_id": "PEMBRO-02",
      "type": "auto_deny_if",
      "criteria": [
        {"resource": "Observation", "code": "PD-L1", "value_op": "<", "value": 1}
      ]
    }
  ],
  "guidelines_text": "Long-form policy text used by RAG / cited by AuthAgent..."
}
```

5 policies — one per scenario, same payer/scenario coverage as the fixtures.

### 3. `backend/tests/test_e2e/` — End-to-end suite

`test_full_pipeline.py`: Spins up an in-process Postgres (via `pytest-postgresql`) + fakeredis, posts a fixture bundle to `/api/v1/auth-requests`, waits for the worker to drain, asserts the resulting Decision matches the expected_outcome embedded in the fixture filename.

```python
@pytest.mark.parametrize("fixture_path", list(FIXTURES.glob("*.json")))
async def test_fixture_produces_expected_decision(fixture_path, client, worker, db):
    bundle = json.loads(fixture_path.read_text())
    expected = parse_expected_from_filename(fixture_path)  # "approve" | "deny" | "aireview"

    resp = await client.post("/api/v1/auth-requests", json={"fhir_bundle": bundle, ...})
    auth_id = resp.json()["id"]

    await worker.drain(timeout=30)

    decision = await db.get(Decision, auth_id=auth_id)
    assert decision.outcome == expected, f"{fixture_path.name}: got {decision.outcome}, expected {expected}"
```

Mock Gemini responses with deterministic canned outputs based on the input fixture. (Real-Gemini E2E is a separate manual smoke; CI uses mocks.)

`test_appeal_pipeline.py`: For each `auto_deny` decision, generates an appeal letter, asserts it cites the policy, references the clinical context, and is at least 200 words.

`test_adk_endpoint.py`: Hits `/.well-known/agent-card.json` and `/adk/v1/jsonrpc` (`message/send`, `tasks/get`), asserts spec compliance.

### 4. `frontend/e2e/` — Playwright E2E

```bash
cd frontend && npm install -D @playwright/test
npx playwright install chromium
```

`frontend/e2e/dashboard.spec.ts`:
- Visit `/`, assert ImpactWidget renders
- Click "Run sample batch" in BatchRunner, wait for first request to start, assert PipelineView shows `extraction` stage active
- Assert ConfidenceQueues count increments

`frontend/e2e/auth-detail.spec.ts`:
- Navigate to `/auth/1` (assumes seeded data)
- Switch through all 5 tabs, assert content renders
- Click "Generate Appeal" if denied, assert AppealEditor loads

`frontend/e2e/appeal-editor.spec.ts`:
- Edit appeal text, save, assert toast confirms save
- Submit, assert status badge changes

Add to `frontend/package.json`: `"test:e2e": "playwright test"`.

### 5. `DEMO_SCRIPT.md` — root

The literal recording script for a 3-minute demo video. Structure:

```markdown
# PriorAuth Pro — 3-Minute Demo Script

**Total runtime:** 2:55. Recorded at 1920×1080, 60fps. Browser zoom 110%.

## Setup (off-screen, before recording)
1. `make demo` — system is up, queues populated
2. Browser open at http://localhost:5173
3. Terminal visible in second monitor (for one shot)

## Take 1 — The Hook (0:00–0:20)

[Camera: Dashboard hero shot]

**Voiceover:** "Prior auth costs the US healthcare system $25 billion a year and 14 hours per clinician per week. Most of that is friction. Today I'll show you PriorAuth Pro — a multi-agent system that handles routine cases automatically and helps clinicians focus on the cases that need human judgment."

[B-roll: ImpactWidget counting up "47 decisions in 4.2 minutes · 39.5 hours saved"]

## Take 2 — The Live Pipeline (0:20–1:00)

[Action: click "Run sample batch" in BatchRunner]

**Voiceover:** "Watch what happens when 20 prior auth requests come in at once."

[The PipelineView animates — extraction → rules → RAG → decide → done — for one focused request, while ConfidenceQueues fill in real time]

**Voiceover:** "Each request goes through five stages: FHIR extraction with Gemini Flash, deterministic rules evaluation, RAG retrieval against payer policy, AI reasoning by Gemini Pro, and persisted audit trail. The orchestrator is built on Google ADK and exposes A2A so other agents can call us."

## Take 3 — Auto-Approval (1:00–1:30)

[Action: click an auto-approved item]

[AuthRequestDetail page renders. Walk through Decision tab → Clinical Context → Guidelines Cited]

**Voiceover:** "This pembrolizumab request was auto-approved in 4 seconds. The system extracted PD-L1 expression of 65%, ECOG 1, and stage IIIB NSCLC from the FHIR bundle, matched against Aetna's 2025 oncology policy, and produced a fully cited decision."

## Take 4 — Needs AI Review (1:30–2:15)

[Action: click an item in "Needs Review" queue]

**Voiceover:** "Here's a borderline case. The rules engine couldn't auto-decide because the patient's BMI is 39.8 — just under the threshold. So it routed to AI review."

[Decision tab shows AI reasoning paragraph citing both supporting and conflicting evidence]

**Voiceover:** "The clinician sees both sides — the patient's documented mobility loss, and the missing 6-month conservative therapy trial — and can override or accept in one click."

## Take 5 — Appeal Generation (2:15–2:45)

[Action: click an auto-denied item, click "Generate Appeal"]

[AppealEditor opens. Generated letter visible]

**Voiceover:** "When a request is denied, PriorAuth Pro can draft an appeal letter — citing the medical record, citing the policy, and structuring the argument. The clinician reviews, edits inline, and submits."

[Action: click Submit]

## Take 6 — The Wrap (2:45–2:55)

[Camera: pulled back, dashboard showing all queues populated]

**Voiceover:** "PriorAuth Pro. Multi-agent. FHIR-native. ADK-built. A2A-exposed. Repo and demo data linked below."

[End card: GitHub URL + team name]

## Recording notes

- Use OBS, 60fps, hardware encoder
- Run `node frontend/scripts/preload-demo-state.js` to put PipelineView in a known state before Take 2
- All Voiceover read with Eleven Labs voice "Rachel" if doing post-production VO
- Subtitles burned in for accessibility
```

### 6. Documentation files — root

#### `README.md` (rewrite)

Replace the placeholder README from baseline with:
- Hero header + GIF/screenshot of dashboard
- 3-bullet pitch ("What is PriorAuth Pro / Why it matters / Try it in 90 seconds")
- Quickstart (`make demo`)
- Architecture diagram (Mermaid)
- Tech stack list
- Hackathon credits + license
- Links to: ARCHITECTURE.md, FHIR_INTEGRATION.md, APPEAL_EXAMPLES.md, DEMO_SCRIPT.md, CONTRIBUTING.md, SECURITY.md

#### `docs/ARCHITECTURE.md`

Long-form (~3000 words) explanation:
- System diagram (Mermaid C4-style)
- Module-by-module: M1 (LLM worker), M2 (agents), M3 (ADK/A2A), M4 (frontend), M5 (deploy), M6 (polish)
- Data flow walkthrough: a single auth request from POST through PipelineView
- The AuthEvent event-sourcing pattern and why it's the source of truth
- Circuit breaker + 503 fallback chain
- Trade-offs accepted: in-process vs distributed agents, single-payer schema, no auth

#### `docs/FHIR_INTEGRATION.md`

- Which FHIR resources we consume (Patient, Condition, MedicationRequest, ServiceRequest, Observation, Encounter, Coverage)
- How ExtractionAgent maps FHIR → ClinicalContext (with example)
- Limitations: R4 only, no Reference resolution beyond the bundle, ICD-10 + SNOMED + RxNorm + LOINC + CPT supported

#### `docs/APPEAL_EXAMPLES.md`

3 fully-worked appeals from fixtures. For each:
- The original denial (with payer reasoning)
- The clinical context summary
- The generated letter (verbatim)
- Annotation pointing out where each cited fact came from

#### `docs/CONTRIBUTING.md`

Standard contributor guide. Setup, branching strategy, ruff/eslint, commit conventions (Conventional Commits), how to run tests.

#### `docs/SECURITY.md`

- PHI handling: in-memory only during processing, audit log redacts patient identifiers, no PHI logged to disk
- API keys via env, never committed
- Disclosure: this is a hackathon prototype, not HIPAA-compliant. Production deployment requires BAA + encryption-at-rest + access controls + audit logging review.

### 7. `frontend/public/og-image.png` — social preview

1200×630 promotional image. Generate with the `canvas-design` or `frontend-design` skill (or hand-export from Figma): dark background, the PipelineView visual, "PriorAuth Pro" wordmark, "Multi-agent prior authorization · Built for Agents Assemble 2026".

### 8. Demo state preloader — `frontend/scripts/preload-demo-state.js`

Small Node script that hits the API to seed predictable state for the demo recording:
- 1 in-flight auth request paused at `extraction.completed` (so PipelineView shows that exact state on first frame)
- 12 auto-approved + 5 auto-denied + 3 needs-review pre-populated
- 1 appeal in draft state ready to demo

Idempotent — if run twice, doesn't double-seed.

### 9. CHANGELOG.md update

Append entries for M1-M6 in conventional-changelog format.

### 10. License audit — `THIRD_PARTY_LICENSES.md`

Auto-generated list of dependencies + their licenses. Use `pip-licenses` for backend, `license-checker` for frontend. Required by some hackathon submissions.

```bash
pip install pip-licenses
pip-licenses --format=markdown --with-urls > /tmp/be-licenses.md
cd frontend && npx license-checker --csv > /tmp/fe-licenses.csv
# Combine + cleanup into THIRD_PARTY_LICENSES.md
```

## Success criteria

1. `pytest backend/tests/test_e2e/` — all 20 fixtures produce expected outcomes; appeals cite correctly; ADK endpoint spec-compliant.
2. `cd frontend && npm run test:e2e` — Playwright E2E green.
3. `make demo` produces the same dashboard state every time (deterministic fixtures).
4. README renders cleanly on GitHub with the hero image.
5. ARCHITECTURE.md, FHIR_INTEGRATION.md, APPEAL_EXAMPLES.md, DEMO_SCRIPT.md, CONTRIBUTING.md, SECURITY.md all present and link from README.
6. THIRD_PARTY_LICENSES.md lists every transitive dep.
7. No `// TODO`, `# FIXME`, or placeholder copy ("Lorem ipsum", "TBD") anywhere in the repo (`grep -r` audit).
8. Demo video script reads end-to-end in 2:55 ± 10s when read aloud at conversational pace.

## Out of scope

- The actual demo video recording — that's a separate task post-M6
- HIPAA compliance certification — see SECURITY.md disclaimer
- Synthea-generated population — 20 hand-crafted fixtures are more reliable than 1000 random ones for a demo
- Internationalization — English only

## Risks

- **Fixture realism**: a real clinician judging us will catch fake-looking FHIR. Run the fixtures past a clinical advisor (Dilip's network) for a sanity-check pass before final submission.
- **E2E flakiness**: Playwright tests against animated UI can flake. Use Playwright's `expect.toHaveText` with timeouts ≥ 5s, avoid `waitForTimeout`.
- **DEMO_SCRIPT timing**: practice run with actual recording before final take. The "Take 4 — Needs AI Review" segment is most likely to overrun.

## Sequence within this module

This module's tasks are mostly parallelizable, but a sane order:

1. Generate fixtures + policies (everything else depends on these)
2. Wire up E2E suite (proves the system works against fixtures)
3. Write ARCHITECTURE.md + FHIR_INTEGRATION.md (longest prose)
4. Build APPEAL_EXAMPLES.md (depends on fixtures + working appeal pipeline)
5. Demo state preloader + DEMO_SCRIPT.md
6. README rewrite + og-image (last, references everything else)
7. License audit + CHANGELOG (final cleanup)

## Model guidance

- Fixture generation: scripted (deterministic), no LLM
- Policy text: hand-written, derived from public payer summaries
- Appeal examples: real outputs from running M2-M3 against fixtures, then lightly polished
- Documentation prose: `gemini-3.1-pro` for first drafts, hand-edited for accuracy and voice
