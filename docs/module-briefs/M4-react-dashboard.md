# Module 4 — React Dashboard

## Purpose

Clinician-facing dashboard — the demo video's visual core. Dark medical-grade theme (deep navy/charcoal background, teal/cyan active states, amber warnings, red denials, green approvals). The PipelineView component is the "money shot": animated 5-stage pipeline (Extract → Rules → RAG → Decide → Done) showing real-time progress for an in-flight auth request.

**Backend dependency:** Modules 1-3 must be running. Frontend hits `/api/v1/auth-requests/*` (REST) and `/api/v1/ws/auth-requests/{id}` (WebSocket) on `localhost:8000`.

## Existing repo context

Backend has:
- `backend/api/routes/auth_requests.py` — POST/GET endpoints
- `backend/api/routes/appeals.py` — appeal CRUD
- `backend/api/websocket.py` — `/ws/auth-requests/{id}` event stream emitting `AuthEvent` rows in real time
- `backend/api/schemas.py` — Pydantic request/response models. OpenAPI auto-generates from these.

The repo currently has **no `frontend/` directory.** This module creates it from scratch.

## Files to create

All under `D:/SHADOW/prior-auth-pro/frontend/` unless otherwise noted.

### 1. Project scaffold

Initialize with:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss postcss autoprefixer @tailwindcss/forms
npx tailwindcss init -p
npm install @tanstack/react-query react-router-dom zustand
npm install framer-motion lucide-react
npm install -D @types/node
npm install class-variance-authority clsx tailwind-merge
# shadcn/ui scaffold
npx shadcn@latest init -d
npx shadcn@latest add button card badge input textarea select dialog tabs progress separator scroll-area toast
```

Generated: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tailwind.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`.

### 2. `frontend/tailwind.config.ts` — dark medical theme tokens

```ts
import type { Config } from "tailwindcss"

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Backgrounds
        bg: {
          primary: "#0a1220",   // deep navy
          secondary: "#0f1a2e", // panel
          tertiary: "#162338",  // raised card
        },
        // Text
        fg: {
          primary: "#e8edf5",
          secondary: "#9ba8be",
          muted: "#6b7a92",
        },
        // Accent
        accent: {
          DEFAULT: "#06b6d4",   // cyan-500 — active/links
          hover: "#0891b2",
          subtle: "#0c4a52",    // backgrounds for accent surfaces
        },
        // Status
        success: { DEFAULT: "#10b981", subtle: "#064e3b" }, // green
        warning: { DEFAULT: "#f59e0b", subtle: "#451a03" }, // amber
        danger:  { DEFAULT: "#ef4444", subtle: "#450a0a" }, // red
        review:  { DEFAULT: "#8b5cf6", subtle: "#2e1065" }, // purple — needs ai_review
        // Border
        border: { DEFAULT: "#243348", strong: "#3a4a64" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4,0,0.6,1) infinite",
        "shimmer": "shimmer 2s linear infinite",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
} satisfies Config
```

### 3. `frontend/src/index.css`

Tailwind directives + global CSS variables for shadcn/ui. Set `--background`, `--foreground`, etc. to match the token palette above. Default `body` to `bg-bg-primary text-fg-primary font-sans antialiased`.

### 4. `frontend/src/lib/api.ts` — typed client

Generated against backend OpenAPI. Use `openapi-typescript` to generate types, `openapi-fetch` for the client.

```bash
npm install -D openapi-typescript
npm install openapi-fetch
```

Add npm script: `"gen:api": "openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts"`.

```ts
import createClient from "openapi-fetch"
import type { paths } from "./api-types"

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE ?? "http://localhost:8000",
})

export const useAuthRequest = (id: number) => {
  return useQuery({
    queryKey: ["auth-request", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/auth-requests/{id}", {
        params: { path: { id } },
      })
      if (error) throw error
      return data
    },
  })
}
// Similar hooks for: list, create, getDecision, listAppeals, etc.
```

### 5. `frontend/src/lib/websocket.ts` — `useAuthRequestStream` hook

Subscribes to `/api/v1/ws/auth-requests/{id}`. Returns `{events: AuthEvent[], status: "connecting"|"open"|"closed"}`. Reconnect on disconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s).

```ts
export interface WSEvent {
  event_type: string  // "extraction.started", "rules.completed", "rag.searching", "decision.emitted", etc.
  payload: Record<string, any>
  ts: string
}

export function useAuthRequestStream(authRequestId: number) {
  const [events, setEvents] = useState<WSEvent[]>([])
  const [status, setStatus] = useState<"connecting"|"open"|"closed">("connecting")
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled = false
    let backoff = 1000

    const connect = () => {
      const ws = new WebSocket(
        `${import.meta.env.VITE_WS_BASE ?? "ws://localhost:8000"}/api/v1/ws/auth-requests/${authRequestId}`
      )
      wsRef.current = ws
      ws.onopen = () => { setStatus("open"); backoff = 1000 }
      ws.onmessage = (msg) => {
        const ev = JSON.parse(msg.data) as WSEvent
        setEvents((prev) => [...prev, ev])
      }
      ws.onclose = () => {
        setStatus("closed")
        if (!cancelled) {
          setTimeout(connect, backoff)
          backoff = Math.min(backoff * 2, 30000)
        }
      }
    }
    connect()
    return () => { cancelled = true; wsRef.current?.close() }
  }, [authRequestId])

  return { events, status }
}
```

### 6. `frontend/src/lib/cn.ts` — class-name helper

Standard shadcn `cn()` utility merging `clsx` + `tailwind-merge`.

### 7. `frontend/src/components/PipelineView.tsx` — THE money shot

5 stages: Extract, Rules, RAG, Decide, Persist. Each rendered as a node connected by edges. Uses `framer-motion` for the active-stage pulse and the data-flow animation along edges.

Visual states per stage:
- `pending` — grey, dim
- `active` — cyan, animated pulse + shimmer on edge to next stage
- `done` — green checkmark + dim cyan glow
- `error` — red, with the error message in a tooltip

Layout: horizontal flex on desktop, vertical stack on mobile.

```tsx
import { motion } from "framer-motion"
import { CheckCircle2, Loader2, AlertCircle, Circle } from "lucide-react"

const STAGES = [
  { id: "extraction", label: "Extract", desc: "FHIR → ClinicalContext" },
  { id: "rules",      label: "Rules",   desc: "Auto-decide if possible" },
  { id: "rag",        label: "RAG",     desc: "Find relevant guidelines" },
  { id: "decision",   label: "Decide",  desc: "Gemini reasons & emits" },
  { id: "persist",    label: "Persist", desc: "DB + audit event" },
] as const

type Status = "pending" | "active" | "done" | "error"

export function PipelineView({ events }: { events: WSEvent[] }) {
  // derive each stage's status from the event stream
  const status = useMemo(() => deriveStageStatus(events), [events])

  return (
    <div className="flex flex-col md:flex-row items-stretch gap-2 p-6 bg-bg-secondary rounded-xl border border-border">
      {STAGES.map((stage, idx) => (
        <Fragment key={stage.id}>
          <PipelineNode stage={stage} status={status[stage.id]} />
          {idx < STAGES.length - 1 && (
            <PipelineEdge active={status[stage.id] === "done" && status[STAGES[idx+1].id] === "active"} />
          )}
        </Fragment>
      ))}
    </div>
  )
}

function PipelineNode({ stage, status }: { stage: typeof STAGES[number], status: Status }) {
  const Icon = { pending: Circle, active: Loader2, done: CheckCircle2, error: AlertCircle }[status]
  const colorClass = {
    pending: "text-fg-muted border-border",
    active:  "text-accent border-accent animate-pulse-slow",
    done:    "text-success border-success/50",
    error:   "text-danger border-danger",
  }[status]

  return (
    <motion.div
      layout
      className={cn("flex-1 flex flex-col items-center gap-2 p-4 rounded-lg border-2 bg-bg-tertiary", colorClass)}
    >
      <Icon className={cn("w-8 h-8", status === "active" && "animate-spin")} />
      <div className="text-fg-primary font-medium">{stage.label}</div>
      <div className="text-fg-muted text-xs text-center">{stage.desc}</div>
    </motion.div>
  )
}

function PipelineEdge({ active }: { active: boolean }) {
  return (
    <div className="hidden md:flex items-center px-1">
      <div className={cn(
        "h-0.5 w-8 bg-gradient-to-r",
        active
          ? "from-success via-accent to-accent bg-[length:200%_100%] animate-shimmer"
          : "from-border to-border"
      )} />
    </div>
  )
}
```

`deriveStageStatus(events)` maps event_type → stage status. Helper in `lib/pipeline-status.ts`.

### 8. `frontend/src/components/ConfidenceQueues.tsx`

Three side-by-side columns: **Auto-Approved** (green tint), **Auto-Denied** (red tint), **Needs Review** (purple tint). Each column shows a count + scrollable list of recent decisions.

Click an item → opens `AuthRequestDetail` page.

Shows the live count via `useQuery` with a 5-second `refetchInterval`.

### 9. `frontend/src/components/ImpactWidget.tsx`

Top-of-dashboard hero stat: "**Today: 47 decisions in 4.2 min · saved 39.5 hours of clinician time**".

Computed from `/api/v1/stats/today` (backend returns `{decisions_count, total_seconds_elapsed, baseline_seconds_per_decision}`). Frontend computes saved hours = `(baseline_seconds_per_decision * decisions_count - total_seconds_elapsed) / 3600`.

Uses framer-motion `<motion.span>` to count up smoothly when value changes.

### 10. `frontend/src/components/BatchRunner.tsx`

Demo mode panel: "Run sample batch of 20 auth requests" button → triggers `POST /api/v1/demo/run-batch`. Shows live progress as each request completes (subscribes to a multi-stream channel `/ws/batch/{batch_id}`).

Designed to be the climax of the demo video.

### 11. `frontend/src/pages/Dashboard.tsx`

Layout:
```
┌──────────────────────────────────────────────────────────────┐
│  [Logo] PriorAuth Pro                 [User] [Settings]       │
├──────────────────────────────────────────────────────────────┤
│  ImpactWidget                                                 │
├──────────────────────────────────────────────────────────────┤
│  [Active: PipelineView for currently-processing request]     │
├──────────────────────────────────────────────────────────────┤
│  ConfidenceQueues  [Auto-Approved | Auto-Denied | Needs AI ] │
├──────────────────────────────────────────────────────────────┤
│  BatchRunner (collapsible, demo-only)                        │
└──────────────────────────────────────────────────────────────┘
```

### 12. `frontend/src/pages/AuthRequestDetail.tsx`

For a single auth_request_id:
- Header: patient name, payer, CPT codes, requested date
- PipelineView (live if still processing, frozen if done)
- Tabs: **Decision** | **Clinical Context** | **Guidelines Cited** | **Audit Trail** | **Raw FHIR**
- Decision tab: status badge, confidence bar, reasoning (markdown rendered), required documentation checklist
- Audit Trail tab: chronological list of every `AuthEvent` row

### 13. `frontend/src/pages/AppealEditor.tsx`

3-pane layout:
- **Left**: source data (denial reason, clinical summary, policy citations) — read-only
- **Center**: generated appeal letter (editable rich text — use `tiptap`)
- **Right**: revision history + LLM regeneration controls

Save button → `PUT /api/v1/appeals/{id}`. Submit button → `POST /api/v1/appeals/{id}/submit`.

### 14. `frontend/src/pages/Queue.tsx`

Table view of all auth requests. Filter by status, payer, date range. Sort by submitted_at, decision_at, confidence. Click row → AuthRequestDetail.

### 15. `frontend/src/App.tsx` + `frontend/src/main.tsx`

Router setup:
```tsx
import { createBrowserRouter, RouterProvider } from "react-router-dom"

const router = createBrowserRouter([
  { path: "/",               element: <Dashboard /> },
  { path: "/auth/:id",       element: <AuthRequestDetail /> },
  { path: "/appeal/:id",     element: <AppealEditor /> },
  { path: "/queue",          element: <Queue /> },
])
```

`main.tsx` wraps in `<QueryClientProvider>` + `<ToastProvider>` + applies the dark class on `<html>`.

### 16. Tests — `frontend/src/__tests__/`

Use `vitest` + `@testing-library/react` + `msw` for API mocking.

- `pipeline-view.test.tsx` — given a sequence of WSEvents, the right stages light up
- `confidence-queues.test.tsx` — renders 3 columns with counts
- `impact-widget.test.tsx` — count-up animation triggers on value change
- `auth-request-detail.test.tsx` — renders all tabs; switching works
- `api.test.ts` — typed client returns expected shapes
- `websocket.test.ts` — reconnect logic with mocked WebSocket

Add to `package.json`:
```json
"scripts": {
  "test": "vitest",
  "test:run": "vitest run",
  "lint": "eslint src --max-warnings 0",
  "build": "tsc -b && vite build"
}
```

### 17. `frontend/.env.example`

```
VITE_API_BASE=http://localhost:8000
VITE_WS_BASE=ws://localhost:8000
```

### 18. `frontend/README.md`

Quick-start: install, run dev, regenerate API types, run tests.

## Success criteria

1. `npm run build` succeeds (zero TS errors).
2. `npm run lint` clean.
3. `npm run test:run` passes all tests.
4. With backend running, `npm run dev` shows the dashboard at `localhost:5173`.
5. Submitting an auth request from the UI triggers PipelineView animation and ends with a decision card.
6. Dark theme is consistent — no white flashes, no light-mode leaks. All components render correctly without a system-light theme.
7. Responsive: dashboard usable on 1280×720 (demo recording resolution) and on mobile viewport.

## Out of scope

- User auth / multi-tenant — single-clinician demo
- Real-time collaboration on appeal editing — single-editor only
- Mobile native app — web responsive only
- Accessibility audit beyond WCAG AA contrast (audit is M6)

## Design language reference

- **Inspiration**: Linear (information density), Vercel dashboard (status semantics), Stripe (typographic hierarchy)
- **Avoid**: gradients-as-primary, glassmorphism, anything that looks like a Bootstrap admin template
- **Spacing**: 4/8/16/24/32 scale; generous internal padding; tight outer margins
- **Animation**: subtle, deterministic. Pipeline stages animate in when status changes. Numbers count up. No bouncing, no decorative motion.

## Model guidance

This module is hand-written code, not LLM-generated. Foundry generates scaffolds + initial component skeletons; Claude reviews + polishes during sync. PipelineView and ImpactWidget are the highest-value components — spend extra polish budget there.
