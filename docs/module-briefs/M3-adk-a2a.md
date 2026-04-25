# Module 3 — Google ADK + A2A Protocol Integration

## Purpose

Wrap Module 2's `OrchestratorAgent` in Google ADK + the A2A (Agent-to-Agent) protocol so that Prompt Opinion Marketplace and other A2A clients can discover and invoke this agent over JSON-RPC 2.0.

**This is the hackathon's non-negotiable technical requirement.**

## Existing repo context

Module 2 (committed) provides:
- `backend/agents/orchestrator.py` → `OrchestratorAgent` — entry point for all reasoning
- `backend/agents/{base,extraction,auth,appeal}.py`
- `backend/worker/schemas.py` — Pydantic models

FastAPI app is at `backend/api/main.py` — already running with routes and websocket.

## Files to create

### 1. `backend/adk/__init__.py`

### 2. `backend/adk/server.py`

Wires A2A endpoints into FastAPI. ~150 LOC.

```python
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from adk.handlers import A2AHandlers

router = APIRouter()
_handlers = A2AHandlers()


@router.post("/a2a")
async def a2a_endpoint(request: Request):
    """JSON-RPC 2.0 endpoint for A2A protocol."""
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    req_id = body.get("id")

    try:
        if method == "message/send":
            result = await _handlers.handle_send(params)
        elif method == "message/stream":
            return StreamingResponse(
                _handlers.handle_stream(params),
                media_type="text/event-stream",
            )
        elif method == "tasks/get":
            result = await _handlers.handle_get(params)
        elif method == "tasks/cancel":
            result = await _handlers.handle_cancel(params)
        elif method == "tasks/list":
            result = await _handlers.handle_list(params)
        else:
            return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": req_id}
        return {"jsonrpc": "2.0", "result": result, "id": req_id}
    except A2AError as e:
        return {"jsonrpc": "2.0", "error": {"code": e.code, "message": e.message, "data": e.data}, "id": req_id}


@router.get("/.well-known/agent-card.json")
async def agent_card():
    from adk.agent_card import build_agent_card
    return build_agent_card()
```

Register this router in `backend/api/main.py` via `app.include_router(adk.server.router)`. Do NOT duplicate any existing routes.

### 3. `backend/adk/handlers.py`

Implements the five A2A methods. ~350 LOC.

```python
import uuid
from adk.fhir_context import decode_fhir_context
from adk.task_store import TaskStore   # in-memory or DB-backed
from agents.orchestrator import OrchestratorAgent, OrchestratorInput


class A2AError(Exception):
    def __init__(self, code, message, data=None):
        self.code = code
        self.message = message
        self.data = data


class A2AHandlers:
    def __init__(self):
        self.tasks = TaskStore()
        self.orchestrator = OrchestratorAgent()

    async def handle_send(self, params: dict) -> dict:
        message = params.get("message")
        if not message:
            raise A2AError(-32602, "Missing 'message' param")

        # Decode FHIR context from message.metadata
        fhir_context = decode_fhir_context(message.get("metadata", {}))

        # Create task
        task_id = str(uuid.uuid4())
        context_id = message.get("contextId") or str(uuid.uuid4())
        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {"state": "TASK_STATE_SUBMITTED", "timestamp": now_iso()},
            "history": [message],
            "artifacts": [],
            "metadata": {},
        }
        self.tasks.save(task)

        # Extract user text from parts
        user_text = " ".join(p.get("text", "") for p in message.get("parts", []) if "text" in p)

        # Dispatch to orchestrator
        task["status"] = {"state": "TASK_STATE_WORKING", "timestamp": now_iso()}
        self.tasks.save(task)

        try:
            result = await self.orchestrator.run(OrchestratorInput(
                user_message=user_text,
                auth_request_id=fhir_context.get("auth_request_id"),
                appeal_id=fhir_context.get("appeal_id"),
            ))
            # Add result as an artifact
            task["artifacts"].append({
                "artifactId": str(uuid.uuid4()),
                "name": f"{result.intent.value}_result",
                "parts": [{"data": result.result, "mediaType": "application/json"}],
            })
            task["status"] = {"state": "TASK_STATE_COMPLETED", "timestamp": now_iso()}
        except Exception as e:
            task["status"] = {"state": "TASK_STATE_FAILED", "timestamp": now_iso()}
            task["metadata"]["error"] = repr(e)
            self.tasks.save(task)
            raise A2AError(-32000, f"Agent execution failed: {e}")

        self.tasks.save(task)
        return task

    async def handle_stream(self, params: dict):
        """Server-Sent Events stream. Yield StreamResponse events as SSE data lines."""
        # Same init as handle_send, but:
        # 1. yield initial Task SSE event
        # 2. As orchestrator runs, emit TaskStatusUpdateEvent on state changes
        # 3. Emit TaskArtifactUpdateEvent per artifact
        # 4. Final TaskStatusUpdateEvent with terminal state
        # Format: `data: {json}\n\n`
        ...

    async def handle_get(self, params: dict) -> dict:
        task_id = params.get("id")
        task = self.tasks.get(task_id)
        if not task:
            raise A2AError(-32000, "TaskNotFoundError", {"taskId": task_id})
        history_length = params.get("historyLength")
        if history_length is not None:
            task = dict(task)
            task["history"] = task["history"][-history_length:] if history_length > 0 else []
        return task

    async def handle_cancel(self, params: dict) -> dict:
        task_id = params.get("id")
        task = self.tasks.get(task_id)
        if not task:
            raise A2AError(-32000, "TaskNotFoundError")
        terminal = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}
        if task["status"]["state"] in terminal:
            raise A2AError(-32000, "TaskNotCancelableError")
        task["status"] = {"state": "TASK_STATE_CANCELED", "timestamp": now_iso()}
        self.tasks.save(task)
        return task

    async def handle_list(self, params: dict) -> dict:
        context_id = params.get("contextId")
        status_filter = params.get("status")
        page_size = min(params.get("pageSize", 50), 100)
        tasks = self.tasks.list(context_id=context_id, status=status_filter, limit=page_size)
        return {"tasks": tasks, "nextPageToken": "", "pageSize": page_size, "totalSize": len(tasks)}
```

### 4. `backend/adk/task_store.py`

Simple persistence layer for A2A tasks. ~80 LOC.

Option 1: In-memory dict (simplest, loses state on restart — acceptable for hackathon demo).
Option 2: SQLAlchemy-backed using a new `A2ATask` model. If time permits, do Option 2.

Recommend: **Option 1 for M3, flag as TODO for M5/M6.** The core flow through OrchestratorAgent already persists `AuthRequest`/`Decision`/`Appeal` to Postgres — A2A tasks are just the protocol-layer wrapper.

### 5. `backend/adk/agent_card.py`

Builds the AgentCard served at `/.well-known/agent-card.json`. ~100 LOC.

```python
def build_agent_card() -> dict:
    return {
        "name": "PriorAuth Pro",
        "description": "AI-powered prior authorization agent. Reviews clinical context, applies payer rules, cites guidelines, and generates appeal letters for denials.",
        "version": "1.0.0",
        "provider": {
            "name": "S-CORP",
            "url": "https://github.com/Dilip-kumar-22/prior-auth-pro",
        },
        "supportedInterfaces": [
            {
                "url": "http://localhost:8000/a2a",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            },
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json", "text/markdown"],
        "skills": [
            {
                "id": "review-prior-auth",
                "name": "Review Prior Authorization Request",
                "description": "Evaluate a prior authorization request: extract clinical context from FHIR, apply payer rules, retrieve relevant guidelines, and return an approve/deny/pend decision with reasoning.",
                "tags": ["healthcare", "prior-authorization", "clinical-decision-support"],
                "examples": [
                    "Review the prior auth request for patient 12345 — CPT 70551 with ICD G35.",
                    "Process auth request id 42 with the attached FHIR bundle.",
                ],
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["application/json"],
            },
            {
                "id": "generate-appeal-letter",
                "name": "Generate Appeal Letter",
                "description": "Draft a structured appeal letter for a denied prior authorization, citing clinical evidence and policy references.",
                "tags": ["healthcare", "appeals", "clinical-writing"],
                "examples": [
                    "Generate an appeal for denied auth request 17.",
                    "Draft appeal letter for appeal id 3 with clinical justification.",
                ],
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["text/markdown", "application/json"],
            },
        ],
        "tags": ["healthcare", "ai-agents", "fhir", "prior-authorization", "hackathon"],
        "securitySchemes": {},  # Public demo, no auth in v1
    }
```

### 6. `backend/adk/fhir_context.py`

Extracts FHIR Bundle or references from A2A message metadata. ~60 LOC.

A2A messages may carry FHIR context in `message.metadata`:
- `metadata.fhir_context.auth_request_id` (int) — link to existing AuthRequest
- `metadata.fhir_context.appeal_id` (int) — link to Appeal
- `metadata.fhir_context.bundle` (dict) — inline FHIR Bundle JSON (optional)

```python
def decode_fhir_context(metadata: dict) -> dict:
    fhir = metadata.get("fhir_context") or {}
    return {
        "auth_request_id": fhir.get("auth_request_id"),
        "appeal_id": fhir.get("appeal_id"),
        "bundle": fhir.get("bundle"),
    }
```

### 7. `backend/prompt-opinion-manifest.yaml`

Publishing manifest (Prompt Opinion reads this):

```yaml
name: prior-auth-pro
version: 1.0.0
display_name: PriorAuth Pro
description: |
  AI-powered prior authorization agent for healthcare. Reviews clinical context
  from FHIR bundles, applies payer rules, retrieves relevant guidelines via RAG,
  returns approve/deny/pend decisions with reasoning, and generates appeal letters.
agent_card_url: http://localhost:8000/.well-known/agent-card.json
a2a_endpoint_url: http://localhost:8000/a2a
categories:
  - healthcare
  - clinical-decision-support
  - prior-authorization
tags:
  - fhir
  - a2a-protocol
  - gemini
repository: https://github.com/Dilip-kumar-22/prior-auth-pro
license: MIT
```

### 8. Tests — `backend/tests/test_adk/`

- `__init__.py`
- `test_handlers.py`:
  - `test_send_returns_completed_task` — POST valid message/send, mock OrchestratorAgent to return canned OrchestratorOutput, assert response is a Task with status COMPLETED + artifact present.
  - `test_send_missing_message_param` — returns error -32602.
  - `test_get_returns_task` — send → get → same task_id returned.
  - `test_get_nonexistent_task` — returns TaskNotFoundError.
  - `test_cancel_in_progress_task` — cancel returns CANCELED state.
  - `test_cancel_terminal_task` — returns TaskNotCancelableError.
  - `test_list_filters_by_context_id`.
- `test_agent_card.py`:
  - `test_card_has_required_fields` — all A2A-required fields present (name, description, supportedInterfaces, capabilities, defaultInputModes, defaultOutputModes).
  - `test_card_skills_valid` — each skill has id, name, description.
  - `test_card_served_at_well_known_path` — GET `/.well-known/agent-card.json` returns 200 + JSON matching builder output.
- `test_streaming.py`:
  - `test_stream_yields_sse_events` — POST message/stream, consume SSE stream, assert first event is Task, subsequent events are TaskStatusUpdateEvent, final is terminal state.
- `test_fhir_context.py`:
  - `test_decode_with_auth_request_id`, `test_decode_empty_metadata`, `test_decode_with_inline_bundle`.

## External specifications — reference for Foundry

**IMPORTANT:** These specs define the wire format. Foundry must match them exactly.

### A2A Protocol — JSON-RPC method signatures

```
### message/send
Request params:
{
  "message": Message (required),
  "configuration": SendMessageConfiguration (optional),
  "metadata": object (optional)
}

Response: Task or Message

Errors: ContentTypeNotSupportedError, UnsupportedOperationError, TaskNotFoundError

### message/stream (Server-Sent Events)
Request params: same as message/send
Stream response: first event is Task or Message; subsequent events are
  TaskStatusUpdateEvent or TaskArtifactUpdateEvent; stream closes at terminal state.

### tasks/get
Request params:
{
  "id": string (required),
  "historyLength": integer (optional)
}
Response: Task
Errors: TaskNotFoundError

### tasks/cancel
Request params: {"id": string (required), "metadata": object (optional)}
Response: Task (with CANCELED status)
Errors: TaskNotCancelableError, TaskNotFoundError

### tasks/list
Request params:
{
  "contextId": string (optional),
  "status": TaskState (optional),
  "pageSize": integer (optional, default 50, max 100),
  "pageToken": string (optional),
  "historyLength": integer (optional),
  "includeArtifacts": boolean (optional, default false)
}
Response: {tasks: Task[], nextPageToken, pageSize, totalSize}
```

### Task object

```
Task {
  id: string,
  contextId: string (optional),
  status: TaskStatus,
  artifacts: Artifact[] (optional),
  history: Message[] (optional),
  metadata: object (optional)
}

TaskStatus {
  state: TaskState,
  timestamp: ISO-8601 string,
  message: string (optional)
}

TaskState enum:
  TASK_STATE_UNSPECIFIED
  TASK_STATE_SUBMITTED       (initial)
  TASK_STATE_WORKING         (initial or during processing)
  TASK_STATE_COMPLETED       (TERMINAL)
  TASK_STATE_FAILED          (TERMINAL)
  TASK_STATE_CANCELED        (TERMINAL)
  TASK_STATE_REJECTED        (TERMINAL)
  TASK_STATE_INPUT_REQUIRED  (INTERRUPTED — allows additional messages)
  TASK_STATE_AUTH_REQUIRED   (INTERRUPTED)

Terminal states reject new messages with UnsupportedOperationError.
```

### Message object

```
Message {
  messageId: string (required, UUID),
  contextId: string (optional),
  taskId: string (optional),
  role: Role (required),
  parts: Part[] (required, non-empty),
  metadata: object (optional),
  extensions: string[] (optional),
  referenceTaskIds: string[] (optional)
}

Role enum:
  ROLE_USER     (client to server)
  ROLE_AGENT    (server to client)
```

### Part object (OneOf)

Exactly one of `text`, `raw`, `url`, `data` must be set:

```
Part {
  text: string (OneOf),
  raw: bytes (OneOf, base64 in JSON),
  url: string (OneOf),
  data: any (OneOf),
  metadata: object (optional),
  filename: string (optional),
  mediaType: string (optional)   // MIME type
}
```

### Artifact object

```
Artifact {
  artifactId: string (required, unique per task),
  name: string (optional),
  description: string (optional),
  parts: Part[] (required, non-empty),
  metadata: object (optional),
  extensions: string[] (optional)
}
```

### Streaming event types

```
TaskStatusUpdateEvent {
  taskId: string,
  contextId: string,
  status: TaskStatus,
  metadata: object (optional)
}

TaskArtifactUpdateEvent {
  taskId: string,
  contextId: string,
  artifact: Artifact,
  append: boolean (optional),
  lastChunk: boolean (optional),
  metadata: object (optional)
}
```

### A2A error codes (map to custom JSON-RPC -32000 range)

- `TaskNotFoundError` — task id does not exist
- `TaskNotCancelableError` — task in terminal/non-cancelable state
- `PushNotificationNotSupportedError`
- `UnsupportedOperationError`
- `ContentTypeNotSupportedError`
- `InvalidAgentResponseError`
- `VersionNotSupportedError`

Standard JSON-RPC errors also used:
- `-32602 Invalid params` for validation failures
- `-32601 Method not found`
- `-32603 Internal error`

### A2A AgentCard schema

Required fields: `name`, `description`, `supportedInterfaces`, `capabilities`, `defaultInputModes`, `defaultOutputModes`.

Optional: `provider`, `skills`, `securitySchemes`, `security`, `extensions`, `version`, `icon`, `tags`.

```
AgentCard {
  name: string (required),
  description: string (required),
  version: string (optional, recommended),
  provider: {name: string, url: string} (optional),
  supportedInterfaces: [{url, protocolBinding, protocolVersion}] (required),
  capabilities: {streaming: bool, pushNotifications: bool, extendedAgentCard: bool} (required),
  defaultInputModes: string[] (required, MIME types),
  defaultOutputModes: string[] (required, MIME types),
  skills: [{id, name, description, tags, examples, inputModes, outputModes}] (optional),
  securitySchemes: {<name>: {type: apiKey|http|oauth2|openIdConnect|mutualTls, ...}} (optional),
  security: [{<schemeName>: [<scope>]}] (optional),
  tags: string[] (optional),
  icon: string (optional, URL),
  extensions: [{uri, description, required}] (optional)
}
```

## Success criteria

1. `curl -X POST http://localhost:8000/a2a -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"message/send","params":{"message":{"messageId":"'$(uuidgen)'","role":"ROLE_USER","parts":[{"text":"Review auth for CPT 70551 with ICD G35"}]}},"id":1}'` returns a valid JSON-RPC response with `result.status.state == "TASK_STATE_COMPLETED"`.
2. `curl http://localhost:8000/.well-known/agent-card.json | python -m json.tool` returns valid JSON with all A2A required fields.
3. All tests in `backend/tests/test_adk/` pass.
4. `ruff check backend/adk/` clean.
5. No regression — all tests from M1 + M2 still pass.

## Out of scope

- Actual Prompt Opinion Marketplace publishing (manual step post-build)
- Push notification support (listed as `false` in capabilities)
- mTLS / OAuth auth (v1 is public-demo)
- Persisting A2A tasks across restarts (Option 1 in-memory store — flag for post-hackathon)

## Model guidance

Same as previous modules: `gemini-2.5-flash` for planning, `gemini-3.1-pro` default for sprints, fallback chain on 503.
