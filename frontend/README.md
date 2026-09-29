# Sentinel frontend

React control center for the Sentinel monitoring API.

The UI does not call Groq, Strands, or n8n. It only talks to FastAPI.

## Setup

```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```

The Vite app runs at [http://localhost:5173](http://localhost:5173) and expects the backend at `VITE_API_BASE_URL` (default `http://localhost:8000`).

## Pages

- **Dashboard** — live API counts, pending alerts, last checked monitor, latest agent activity
- **Monitors** — create, enable/disable, Check Now, details, agent trace
- **Alerts** — pending / acknowledged / dismissed, human-in-the-loop state
- **History** — chronological checks with action and alert id

n8n is shown as automation / orchestration, not as an AI agent.

See the repository README for the full demo walkthrough.
