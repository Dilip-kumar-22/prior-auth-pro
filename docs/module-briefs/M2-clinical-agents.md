# Module 2 — Clinical Agents Layer

## Purpose

Refactor Module 1's flat worker tasks into structured agent classes (`BaseAgent` → `ExtractionAgent` / `AuthAgent` / `AppealAgent`, with `OrchestratorAgent` as router). Externalize prompts to jinja2 templates. This creates the abstraction layer that Module 3 (ADK/A2A) will wrap.

**No behavior change** — tests for Module 1 must still pass. This module is purely a refactor + prompt externalization.

## Existing repo context

Module 1 (now committed) provides:
- `backend/worker/tasks.py` — flat `process_auth_request_task` and `generate_appeal_task`
- `backend/worker/llm_client.py` — `GeminiClient`, `generate_auth_decision`, `generate_appeal_letter`, prompt templates as module constants
- `backend/worker/schemas.py` — `ClinicalContext`, `AuthDecision`, `AppealContext`, `AppealLetter`

Everything from the baseline (api/, core/, engines/, fhir/, models/, migrations/) is present and unchanged.

## Files to create

### 1. `backend/agents/__init__.py`

Exports: `BaseAgent`, `OrchestratorAgent`, `ExtractionAgent`, `AuthAgent`, `AppealAgent`.

### 2. `backend/agents/base.py`

Abstract base class. ~120 LOC.

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar
import logging
import time
import jinja2
from pydantic import BaseModel

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


class BaseAgent(ABC, Generic[TIn, TOut]):
    """Abstract agent. Subclasses declare input/output types and implement _run()."""

    name: str
    prompt_template: str  # filename in backend/agents/prompts/
    model: str = "gemini-3.1-pro"

    def __init__(self):
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("backend/agents/prompts"),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.logger = logging.getLogger(f"agents.{self.name}")

    async def run(self, input: TIn) -> TOut:
        start = time.time()
        self._on_start(input)
        try:
            output = await self._run(input)
            self._on_complete(input, output, elapsed_ms=int((time.time() - start) * 1000))
            return output
        except Exception as e:
            self._on_error(input, e, elapsed_ms=int((time.time() - start) * 1000))
            raise

    @abstractmethod
    async def _run(self, input: TIn) -> TOut:
        """Subclass implements the actual logic."""

    def render_prompt(self, **vars) -> str:
        """Load and render the agent's jinja2 template."""
        tpl = self._jinja_env.get_template(self.prompt_template)
        return tpl.render(**vars)

    def _on_start(self, input): self.logger.info(f"{self.name} starting; input_type={type(input).__name__}")
    def _on_complete(self, input, output, elapsed_ms): self.logger.info(f"{self.name} complete in {elapsed_ms}ms")
    def _on_error(self, input, exc, elapsed_ms): self.logger.error(f"{self.name} failed after {elapsed_ms}ms: {exc!r}")
```

### 3. `backend/agents/prompts/extraction.md.j2`

Jinja2 template for FHIR → ClinicalContext extraction. Variables: `{{ fhir_bundle_json }}`. Outputs instructions to Gemini on how to extract structured clinical data.

### 4. `backend/agents/prompts/auth.md.j2`

Jinja2 template for auth decision. Variables: `{{ clinical }}` (ClinicalContext), `{{ guidelines }}` (list of guideline dicts from RAG). Should instruct Gemini to return a JSON matching the `AuthDecision` schema.

### 5. `backend/agents/prompts/appeal.md.j2`

Jinja2 template for appeal letter. Variables: `{{ denial_reason }}`, `{{ clinical_summary }}`, `{{ policy_citations }}`, `{{ patient_age }}`, `{{ primary_diagnosis_icd10 }}`.

### 6. `backend/agents/prompts/orchestrator.md.j2`

Jinja2 template for intent classification. Input: a single free-text message from the user/system. Output: JSON `{"intent": "auth_review" | "appeal_generation" | "clarification", "rationale": "..."}`.

### 7. `backend/agents/extraction.py`

~80 LOC.

```python
from agents.base import BaseAgent
from worker.schemas import ClinicalContext
from pydantic import BaseModel


class ExtractionInput(BaseModel):
    fhir_bundle_json: str  # serialized FHIR Bundle


class ExtractionAgent(BaseAgent[ExtractionInput, ClinicalContext]):
    name = "extraction"
    prompt_template = "extraction.md.j2"
    model = "gemini-3.1-flash"  # Fast extraction, no deep reasoning needed

    async def _run(self, input: ExtractionInput) -> ClinicalContext:
        from worker.llm_client import GeminiClient
        prompt = self.render_prompt(fhir_bundle_json=input.fhir_bundle_json)
        client = GeminiClient(api_key=..., model=self.model)
        return await client.generate_structured(prompt, ClinicalContext)
```

(Replace `api_key=...` with actual env-backed key loading.)

### 8. `backend/agents/auth.py`

~70 LOC.

```python
class AuthInput(BaseModel):
    clinical: ClinicalContext
    relevant_guidelines: list[dict]


class AuthAgent(BaseAgent[AuthInput, AuthDecision]):
    name = "auth"
    prompt_template = "auth.md.j2"
    model = "gemini-3.1-pro"

    async def _run(self, input: AuthInput) -> AuthDecision:
        prompt = self.render_prompt(
            clinical=input.clinical.model_dump(),
            guidelines=input.relevant_guidelines,
        )
        client = GeminiClient(api_key=..., model=self.model)
        return await client.generate_structured(prompt, AuthDecision)
```

### 9. `backend/agents/appeal.py`

Same pattern, input = `AppealContext`, output = `AppealLetter`.

### 10. `backend/agents/orchestrator.py`

~120 LOC. Intent classification + routing.

```python
from enum import Enum


class Intent(str, Enum):
    AUTH_REVIEW = "auth_review"
    APPEAL_GENERATION = "appeal_generation"
    CLARIFICATION = "clarification"


class OrchestratorInput(BaseModel):
    user_message: str
    auth_request_id: int | None = None
    appeal_id: int | None = None


class OrchestratorOutput(BaseModel):
    intent: Intent
    result: dict  # AuthDecision, AppealLetter, or clarification text


class OrchestratorAgent(BaseAgent[OrchestratorInput, OrchestratorOutput]):
    name = "orchestrator"
    prompt_template = "orchestrator.md.j2"
    model = "gemini-3.1-pro"

    async def _run(self, input: OrchestratorInput) -> OrchestratorOutput:
        # Step 1: classify intent
        prompt = self.render_prompt(user_message=input.user_message)
        client = GeminiClient(api_key=..., model=self.model)
        intent_result = await client.generate_structured(
            prompt, schema=IntentClassification  # simple BaseModel with {intent, rationale}
        )

        # Step 2: dispatch
        if intent_result.intent == Intent.AUTH_REVIEW and input.auth_request_id:
            # Full extract → rules → (rag) → auth pipeline
            decision = await self._run_auth_pipeline(input.auth_request_id)
            return OrchestratorOutput(intent=Intent.AUTH_REVIEW, result=decision.model_dump())
        elif intent_result.intent == Intent.APPEAL_GENERATION and input.appeal_id:
            letter = await AppealAgent().run(await self._load_appeal_context(input.appeal_id))
            return OrchestratorOutput(intent=Intent.APPEAL_GENERATION, result=letter.model_dump())
        else:
            return OrchestratorOutput(intent=Intent.CLARIFICATION, result={"message": intent_result.rationale})

    async def _run_auth_pipeline(self, auth_request_id: int) -> AuthDecision:
        """Full flow: load FHIR → extraction → rules → RAG (if needed) → auth agent."""
        # 1. Load AuthRequest, fetch FHIR bundle
        # 2. extraction_agent.run() -> ClinicalContext
        # 3. RulesEngine.evaluate() -> auto_approve / auto_deny / ai_review
        # 4. If ai_review: RagEngine.search() -> guidelines; AuthAgent.run() -> AuthDecision
        # 5. Persist Decision + AuthEvents (same logic as worker/tasks.py, just via agents)
```

### 11. Refactor worker/tasks.py — make thin

Replace body of `process_auth_request_task`:
```python
async def process_auth_request_task(ctx, auth_request_id: int) -> dict:
    from agents.orchestrator import OrchestratorAgent, OrchestratorInput
    orch = OrchestratorAgent()
    result = await orch.run(OrchestratorInput(
        user_message=f"Review auth request {auth_request_id}",
        auth_request_id=auth_request_id,
    ))
    return {"status": "processed", "intent": result.intent.value, "result": result.result}
```

Same for `generate_appeal_task`:
```python
async def generate_appeal_task(ctx, appeal_id: int) -> dict:
    from agents.appeal import AppealAgent
    from agents.orchestrator import OrchestratorAgent
    orch = OrchestratorAgent()
    # Load context from DB, run agent, persist. ~20 LOC.
```

All DB + WebSocket emission logic migrates into `OrchestratorAgent._run_auth_pipeline` and equivalent appeal method.

### 12. Tests — `backend/tests/test_agents/`

- `__init__.py`
- `test_base.py` — prompt loader finds template; `_on_start/_on_complete/_on_error` hooks fire in right order (use a minimal concrete subclass).
- `test_extraction.py` — canned FHIR Bundle string → mocked Gemini returns canned ClinicalContext → verify output.
- `test_auth.py` — ClinicalContext + guidelines → mocked Gemini returns canned AuthDecision → verify.
- `test_appeal.py` — AppealContext → mocked Gemini returns canned AppealLetter → verify.
- `test_orchestrator.py` — 3 scenarios:
  - Intent = auth_review, auth_request_id provided → runs full pipeline (mocked sub-agents), returns AuthDecision
  - Intent = appeal_generation, appeal_id provided → runs AppealAgent, returns AppealLetter
  - Intent = clarification → returns text only

### 13. Update llm_client.py — remove prompt constants

Since prompts now live in `agents/prompts/*.md.j2`, delete `AUTH_DECISION_PROMPT_TEMPLATE` and `APPEAL_LETTER_PROMPT_TEMPLATE` from `worker/llm_client.py`. Keep `generate_auth_decision` and `generate_appeal_letter` helpers for backwards-compatible calls from non-agent code — they now call the agents internally.

## Success criteria

1. **All Module 1 tests still pass unchanged.**
2. All new tests under `tests/test_agents/` pass.
3. `ruff check backend/agents/` clean.
4. Zero hardcoded prompt strings in any `.py` file — all prompts live in `.md.j2` templates.
5. `grep -r 'def run\|def _run\|class .*Agent' backend/agents/` shows 5 agent classes (Base + 4 concrete).
6. No behavior change: same auth_request_id with same clinical data produces same decision before/after refactor.

## Out of scope

- ADK/A2A protocol wrapper — Module 3
- New agent types (research agent, etc.) — not in this project
- Multi-LLM routing — not in this project

## Model guidance

Same as M1: `gemini-2.5-flash` for planning, `gemini-3.1-pro` default for sprint reasoning, fallback chain on 503.
