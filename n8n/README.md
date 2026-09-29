# n8n in Sentinel

**n8n is orchestration, not an AI agent.**

n8n decides **when** to check. FastAPI + Strands agents decide **what the page means**.

Demo interval: **every 10 seconds**.

## Target workflow

```
Schedule Trigger (every 10 seconds)
    -> GET /api/monitors
    -> keep enabled WEBSITE monitors (skip Gmail, skip disabled)
    -> POST /api/monitors/{id}/check for each remaining monitor
```

Creating a website monitor does **not** run a check. The next 10-second n8n cycle should baseline it. If the UI stays on “Waiting for scheduled check”, n8n is not reaching FastAPI — open http://localhost:5678 and confirm **Sentinel scheduled checks** is **Active**.

A failure checking monitor A does not skip B or C.

Import `n8n/sentinel-scheduled-checks.json` and **activate** it.

The POST check node continues if one monitor fails so other enabled monitors still run. Timeout is 180 seconds because a Groq + webpage check can take longer than n8n's default.

## Docker (required for this project)

FastAPI on the Windows/macOS host must be reached at:

`http://host.docker.internal:8000`

FastAPI must listen on **all interfaces**:

```powershell
cd backend
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

`127.0.0.1` only is not visible from the n8n container.

```powershell
cd n8n
docker compose up -d
.\ensure-workflow.ps1
```

Then open http://localhost:5678 and confirm **Sentinel scheduled checks** is **Active**.

If GET /api/monitors fails from n8n, the execution history will show the HTTP error. Typical causes:

- FastAPI is not running on port 8000
- FastAPI was started without `--host 0.0.0.0`
- the workflow still uses `localhost:8000` instead of `host.docker.internal:8000`
- Linux Docker is missing `extra_hosts`

## Local n8n without Docker

```powershell
npx n8n
```

If n8n is not in Docker, change the HTTP URLs to `http://127.0.0.1:8000`.

Do not put Groq or WhatsApp reasoning inside n8n. Alerts are persisted by FastAPI and shown in the Sentinel UI.
