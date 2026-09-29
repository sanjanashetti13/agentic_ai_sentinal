# Sentinel

Autonomous personal digital monitoring agent.

**MANY SPECIALIST AGENTS • DETERMINISTIC HASHING • CONTINUOUS AWARENESS**

Sentinel uses **multiple specialized AI agents coordinated by a Supervisor Agent**.

**n8n is orchestration, not an AI agent.**

## 1. Project overview

Sentinel lets a person express a natural-language monitoring goal such as:

> Keep track of this website and tell me if the application deadline changes.

The system watches a digital source, detects whether content actually changed, decides whether that change matters for the goal, and recommends or records an action.

## 2. Problem statement

Important digital changes are easy to miss: deadlines move, registration opens, a process quietly updates. Checking pages by hand does not scale, and naive keyword scrapers cannot judge what matters for *this* user's goal.

## 3. Why Sentinel

Sentinel separates three concerns that are often mixed together:

- **Deterministic change detection** (normalized SHA-256 hashes)
- **Goal-aware AI reasoning** (specialist Strands agents)
- **Deterministic orchestration** (n8n schedules and routes HTTP calls)

The AI never replaces hash comparison. Hash comparison never pretends to understand the user's goal.

## 4. Multi-agent architecture

Sentinel uses multiple cooperating AWS Strands agents. They communicate through structured Pydantic models (`AgentTask`, `MonitoringObservation`, `ChangeAnalysis`, `ActionDecision`, `SupervisorResult`).

```
                         SENTINEL
                            |
                     Supervisor Agent
                            |
          +-----------------+----------------+
          |                 |                |
          v                 v                v
   Monitoring Agent   Analysis Agent    Action Agent
          |                 |                |
          v                 v                v
    Source tools       Goal-aware       Alert/action
                       reasoning        decision
```

n8n is **not** one of these agents.

| Layer | What it is |
| --- | --- |
| **AI agents** | Supervisor, Monitoring, Analysis, Action (AWS Strands) |
| **LLM** | Groq (optional Ollama fallback) |
| **API** | FastAPI |
| **UI** | React control center |
| **Database** | SQLite |
| **Tools** | `check_webpage` (MVP) |
| **Orchestration** | n8n — scheduling and HTTP routing, not an AI agent |

## 5. Agent responsibilities

| Agent | Responsibility |
| --- | --- |
| **Supervisor** | Understand the goal at a high level, invoke specialists, synthesize the final structured result. It does not fetch pages or replace hash comparison. |
| **Monitoring Agent** | A real AWS Strands agent with Groq. It **must** call `check_webpage`, then return a structured observation: goal-relevant facts and excerpt taken only from the tool result. It does not hash, does not decide whether the page changed, and does not create alerts. |
| **Analysis Agent** | After a hash-detected change, decide whether it is meaningful for the natural-language goal. No keyword branching such as `if "deadline" in goal`. |
| **Action Agent** | Decide `ignore`, `create_alert`, `notify_user`, or `request_approval`. Enforces human-in-the-loop safety. |

## 6. Role of AWS Strands

AWS Strands Agents SDK is the agent framework. Each specialist is a real `Agent` with its own system prompt and tools. The Supervisor uses specialist agents as tools (`agent.as_tool()`).

## 7. Role of Groq

Groq is the default LLM provider (OpenAI-compatible Chat Completions). The default model is `openai/gpt-oss-20b`. `llama-3.3-70b-versatile` is enterprise-only on Groq.

Ollama is an optional local fallback when `MODEL_PROVIDER=ollama` and `OLLAMA_MODEL` are set. It is not required.

## 8. Role of n8n

n8n schedules monitor checks every **10 seconds** and routes HTTP calls to FastAPI. It must not contain AI reasoning. From Docker it must call FastAPI at `http://host.docker.internal:8000`. FastAPI must listen on `0.0.0.0:8000` so the container can reach it.

## 9. Tool architecture

Source access is modular. The MVP fully supports **webpage monitoring** via `check_webpage`:

- URL validation (`http`/`https` only)
- Fast default path: HTTPX fetch + BeautifulSoup readable-text extraction
- Playwright browser fallback **only** when the HTTP response is an empty/JS application shell
- Cleaning of scripts, styles, navigation, and identifiable cookie banners
- Whitespace / relative-time normalization (dates, prices, and status copy are kept)
- SHA-256 content hashing of the cleaned text (deterministic source of truth)
- Structured errors for 4xx/5xx, timeouts, DNS/network failures, CAPTCHA, auth, bot challenges, and paywalls

Playwright does not run for every request. It never clicks, fills forms, or bypasses CAPTCHA, OTP, login, paywalls, or bot protection.

**Demo/test source:** `http://127.0.0.1:8765/` (local HTML files in `demo/pages`). Deterministic regression fixture.

**Real external source:** any public `http(s)` URL. Probe it with the command below. Results are live fetches, not faked.

Email, APIs, files, and additional browser workflows remain extension points. They are not fake integrations.

## 10. Memory / state

SQLite stores monitors, observations, alerts, and action history. The store interface is small so PostgreSQL can replace it later. There is no vector database in the MVP. Page snapshots are clipped (8,000 characters) and are not returned in API responses.

## 11. Human-in-the-loop

Sentinel stops for security and consequential actions:

- CAPTCHA → `blocked_requires_user` (never bypassed)
- OTP → `blocked_requires_user` (never bypassed)
- Login / HTTP 401–403 → `authentication_required`
- Consequential external action → `approval_required`

Human-loop states: `no_action`, `notification`, `approval_required`, `blocked_requires_user`.

The control center explains these as:

- Notification: Sentinel can notify you.
- Approval required: User approval required before taking this action.
- Blocked: User intervention required because authentication/CAPTCHA/OTP is needed.

Sentinel does not bypass security.

## 12. Security limitations

- Never commit `.env`.
- Groq, WhatsApp, and other secrets stay on the backend.
- The frontend talks only to FastAPI.
- Sentinel will not bypass CAPTCHA, OTP, or authentication.
- External pages can lie, go down, or rate-limit. Hashing detects change; it does not prove truth.
- WhatsApp Cloud API is optional, credential-gated, and not claimed to be free or unlimited.

## 13. Setup instructions

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Set `GROQ_API_KEY` in `backend/.env`.

Optional browser fallback (needed only for JavaScript-heavy pages):

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\playwright.exe install chromium
```

### Frontend

```powershell
cd frontend
copy .env.example .env
npm install
```

## 14. Environment variables

Backend (`backend/.env.example`):

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Required to run specialist agents |
| `GROQ_MODEL` | Default `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Groq OpenAI-compatible endpoint |
| `MODEL_PROVIDER` | `groq` (default) or `ollama` |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | Optional local fallback |
| `DATABASE_PATH` | SQLite file |
| `REQUEST_TIMEOUT_SECONDS` | HTTP fetch timeout (default 15) |
| `ENABLE_BROWSER_FALLBACK` | Use Playwright only for JS shells (default true) |
| `BROWSER_TIMEOUT_SECONDS` | Playwright timeout (default 20) |
| `MIN_READABLE_CHARS` | Below this, a JS shell may trigger the browser path |
| `WHATSAPP_ACCESS_TOKEN` | Optional Cloud API token |
| `WHATSAPP_PHONE_NUMBER_ID` | Optional sender id |
| `WHATSAPP_RECIPIENT_PHONE` | Optional recipient |
| `NOTIFICATION_CHANNEL` | Default `whatsapp` |

Frontend:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | FastAPI origin, default `http://localhost:8000` |

## 15. Running the backend

From `backend`:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health: http://127.0.0.1:8000/health

## 16. Running the frontend

```powershell
cd frontend
npm run dev
```

UI: http://localhost:5173

The control center talks only to FastAPI. It never receives Groq or WhatsApp credentials.

| Page | What it shows |
| --- | --- |
| **Dashboard** | Live monitor counts, pending alerts, last checked source, latest agent activity |
| **Monitors** | Create, enable/disable, Check Now, details, agent trace |
| **Alerts** | Pending, acknowledged, and dismissed alerts with HITL state |
| **History** | Chronological checks with change status, action, and alert id |

Agent activity lists the four specialists (Supervisor, Monitoring, Analysis, Action) with a short result. Internal chain-of-thought is not shown.

n8n is labeled **Automation / Orchestration**, not an agent.

## 17. Running n8n

Docker (recommended if n8n already runs in a container):

```powershell
cd n8n
docker compose up -d
.\ensure-workflow.ps1
```

Or without Docker:

```powershell
npx n8n
```

Open http://localhost:5678 and confirm **Sentinel scheduled checks** is **Active**. The schedule is every **10 seconds**. Docker n8n must use `http://host.docker.internal:8000`, not `localhost:8000`. FastAPI must be started with `--host 0.0.0.0`.

If n8n cannot reach FastAPI, the failed HTTP request appears in n8n's execution history. The dashboard also shows scheduler status from `GET /api/status`.

## Real-world webpage probe

This calls `check_webpage` against a live public URL. It does not use Groq and does not invent content.

```powershell
cd backend
.\.venv\Scripts\python.exe run.py probe --url https://example.com
```

`--no-browser` disables the Playwright fallback. The JSON output includes `fetch_method` (`http` or `browser`), `final_url`, `content_hash`, and a short text preview. Raw HTML is not printed.

Create a monitor for the same URL in the control center if you want the full agent workflow.

## End-to-End Demo

This is the supported **controlled** demonstration path. The demo webpage is a local test source (`demo/pages`), not a stand-in for the public web. Monitoring logic does not special-case it.

Use the demo for deterministic regression. Use `run.py probe` or a monitor whose URL is a real website for external pages.

Roles:

- **n8n** = deterministic orchestration
- **Strands** = multi-agent framework
- **Groq** = LLM provider
- **Supervisor** = coordinator
- **Monitoring** = source observation
- **Analysis** = goal-aware relevance reasoning
- **Action** = action/notification decision

### Commands

Terminal 1 — API:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Terminal 2 — demo webpage (deadline September 20, 2026):

```powershell
.\backend\.venv\Scripts\python.exe demo\serve.py --serve
```

The page is http://127.0.0.1:8765/

Terminal 3 — control center:

```powershell
cd frontend
npm run dev
```

### Manual demo (from the web interface)

1. Start backend.
2. Start demo webpage.
3. Open the control center. Use **Use demo values** or create a monitor:
   - Goal: `Tell me if the application deadline changes.`
   - URL: `http://127.0.0.1:8765/`
4. Run **Check Now**. Result should be **baseline**. Analysis and Action are skipped.
5. Change the demo webpage:

```powershell
.\backend\.venv\Scripts\python.exe demo\serve.py --set changed
```

   Deadline is now September 30, 2026. Keep the server running, or start it again with `--serve`.
6. Run **Check Now** again. Expected: `changed`, `meaningful_change = true`, `action_required = true`, `action_type = notify_user`.
7. Open **Alerts**. The pending alert should be visible.
8. Open monitor details. Agent activity should list Supervisor, Monitoring, Analysis, and Action.
9. Hash comparison is the source of truth for `changed`. Agents do not replace it.
10. n8n can later `GET /api/alerts?status=pending` then `POST /api/alerts/{id}/notify` (orchestration only).
11. WhatsApp is optional and out of scope unless credentials are configured separately. Do not claim a message was sent.

Automated (real agents, not faked):

```powershell
.\backend\.venv\Scripts\python.exe demo\run_e2e.py
```

Requires the API running and `GROQ_API_KEY`. The script starts the demo page, creates a monitor, runs baseline, switches the page, runs the changed check, retrieves the alert, and exercises notification.

Switch helpers:

```powershell
python demo/serve.py --set initial
python demo/serve.py --set changed
```

Or, while the server is running, open `/reset` or `/change`.

## 18. Running tests

Use the backend virtualenv. A system-wide `pytest` will fail with `No module named 'strands'`.

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest
```

Frontend typecheck/build:

```powershell
cd frontend
npm run build
```

Live Groq tests are marked `integration` and skip unless `GROQ_API_KEY` is set.

## 19. Example monitoring flow

1. User creates a monitor: goal + URL.
2. `POST /api/monitors/{id}/check` runs.
3. Monitoring Agent uses `check_webpage`.
4. Hash comparison classifies `baseline`, `unchanged`, or `changed`.
5. Baseline and unchanged skip Analysis and Action agents.
6. Changed checks invoke Analysis. Action runs only when the change is meaningful or a human-loop block (CAPTCHA/login/OTP) is present.
7. If `meaningful_change` and `action_required` and the Action Agent does not ignore, an alert is stored.
8. Notification service sends WhatsApp only when credentials are configured.
9. n8n can later `GET /api/alerts?status=pending` and `POST /api/alerts/{id}/notify`.

## 20. Example agent interaction

```
user goal + URL + previous excerpt
    -> Monitoring Agent (Strands + Groq, must call check_webpage)
    -> HTTPX + BeautifulSoup, Playwright only for JS shells
    -> normalized readable text + SHA-256 (tool, not LLM)
    -> deterministic hash compare (baseline / unchanged / changed)
    -> Analysis Agent only if the hash changed (is this meaningful?)
    -> Action Agent only if meaningful or a human-loop block is present
    -> Supervisor structured result
    -> SQLite alert + action history
```

The Monitoring Agent answers: **what is currently on the page that matters for this goal?**

The hash answers: **did the normalized source representation change?**

The Analysis Agent answers: **does that change matter?**

The Action Agent answers: **what should Sentinel do?**

## 21. Future source integrations

Clean extension points, not implemented as fakes:

- email
- APIs
- files
- browser-based sources (Playwright only when genuinely necessary)

## API

Preserve:

- `POST /api/monitors`
- `GET /api/monitors`
- `GET /api/monitors/{id}` (includes observation history)
- `PATCH /api/monitors/{id}`
- `DELETE /api/monitors/{id}`
- `POST /api/monitors/{id}/check`

Alerts:

- `GET /api/alerts`
- `GET /api/alerts?status=pending`
- `GET /api/alerts/{alert_id}`
- `PATCH /api/alerts/{alert_id}`
- `POST /api/alerts/{alert_id}/notify`

## Security

Never commit `.env`. Copy `.env.example` and keep secrets local. The frontend never receives Groq or WhatsApp credentials.
