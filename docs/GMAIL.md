# Gmail integration (SENTINEL)

Gmail is a **tool/integration** for the existing Strands reasoner. It is not a separate agent. Website monitoring is unchanged.

Each SENTINEL user has their own Gmail OAuth tokens. There is no shared application-wide Gmail token. Tokens stay on the backend; the frontend never receives client secrets, access tokens, or refresh tokens.

```
User (browser session)
        ↓
Connect Gmail (cookie identifies the SENTINEL user)
        ↓
Google OAuth (read-only) using GOOGLE_REDIRECT_URI
        ↓
Encrypted tokens stored per user_id
        ↓
Gmail users.watch → Pub/Sub topic
        ↓
POST GMAIL_WEBHOOK_URL
        ↓
Lookup connection by Gmail address (not a global token)
        ↓
History API → that user's messages
        ↓
Strands reasoner vs that user's monitors
        ↓
Relevant → one alert
```

## Environment variables

Copy `backend/.env.example` into `backend/.env`. Set every public URL for the environment you are running.

| Variable | Purpose |
| --- | --- |
| `PUBLIC_BASE_URL` | Public origin of the FastAPI backend (no trailing slash). |
| `FRONTEND_URL` | Public origin of the UI. OAuth callback redirects here. |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API. |
| `SESSION_SECRET` | Signs the SENTINEL user cookie. Required in production. |
| `GOOGLE_CLIENT_ID` | OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret. Never expose to the frontend. |
| `GOOGLE_REDIRECT_URI` | Must match Google Cloud **exactly**. |
| `GMAIL_WEBHOOK_URL` | Full Pub/Sub push URL, including `?token=...`. |
| `GOOGLE_PUBSUB_TOPIC` | `projects/PROJECT_ID/topics/TOPIC` |
| `GOOGLE_PUBSUB_VERIFICATION_TOKEN` | Shared secret on the webhook query string. |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Encrypts per-user Gmail tokens at rest. |

If `GOOGLE_REDIRECT_URI` is empty, SENTINEL derives:

`{PUBLIC_BASE_URL}/api/integrations/gmail/callback`

If `GMAIL_WEBHOOK_URL` is empty, SENTINEL derives:

`{PUBLIC_BASE_URL}/api/webhooks/gmail?token={GOOGLE_PUBSUB_VERIFICATION_TOKEN}`

OAuth will not start until a redirect URI is available (explicit or derived). Do not rely on a localhost default in production.

### Local example

```
PUBLIC_BASE_URL=http://127.0.0.1:8000
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/integrations/gmail/callback
GMAIL_WEBHOOK_URL=https://YOUR_TUNNEL/api/webhooks/gmail?token=long-random-string
```

### Deployed HTTPS example

```
PUBLIC_BASE_URL=https://api.your-domain.example
FRONTEND_URL=https://app.your-domain.example
CORS_ORIGINS=https://app.your-domain.example
GOOGLE_REDIRECT_URI=https://api.your-domain.example/api/integrations/gmail/callback
GMAIL_WEBHOOK_URL=https://api.your-domain.example/api/webhooks/gmail?token=long-random-string
SESSION_SECRET=replace-with-a-long-random-string
GOOGLE_TOKEN_ENCRYPTION_KEY=replace-with-a-long-random-string
```

Frontend:

```
VITE_API_BASE_URL=https://api.your-domain.example
```

Rebuild the frontend after changing `VITE_API_BASE_URL`.

## Google Cloud configuration for deployment

1. Create or select a Google Cloud project.
2. Enable the **Gmail API**.
3. Configure the OAuth consent screen. Add test users while the app is in testing.
4. Create an OAuth **Web application** client.
5. Authorized JavaScript origins: your `FRONTEND_URL` (and local origin if you still develop locally).
6. Authorized redirect URIs — register **both** if you use local and production:
   - local `GOOGLE_REDIRECT_URI`
   - production `GOOGLE_REDIRECT_URI`
7. Scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/userinfo.email`
8. Create a Pub/Sub topic, for example `sentinel-gmail`.
9. Grant `roles/pubsub.publisher` on that topic to `gmail-api-push@system.gserviceaccount.com`.
10. Create a **push** subscription. Endpoint = `GMAIL_WEBHOOK_URL` (HTTPS required).
11. Put the topic name in `GOOGLE_PUBSUB_TOPIC`.

One Pub/Sub topic can serve every connected mailbox. Each watch is created with that user's token. Incoming notifications include `emailAddress`; SENTINEL loads **that** user's stored tokens.

## Local development without Pub/Sub reaching your machine

Google cannot push to a private `http://` host. Either:

- Expose the backend with a tunnel you control and set `GMAIL_WEBHOOK_URL` to that HTTPS URL, or
- Set `GMAIL_DEV_INGEST=true` and POST a structured email to `/api/integrations/gmail/dev/ingest` (not a polling loop).

## Security

- Per-user encrypted token blobs in SQLite (`gmail_connections.user_id`).
- httponly session cookie identifies the SENTINEL user; it is not a Google token.
- Webhook authenticated with `GOOGLE_PUBSUB_VERIFICATION_TOKEN`.
- Email bodies are untrusted data.
