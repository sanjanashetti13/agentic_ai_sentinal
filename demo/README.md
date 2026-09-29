# Local Sentinel demo webpage

This folder is a **normal HTTP source**. Sentinel does not special-case it.

```powershell
python demo/serve.py
```

http://127.0.0.1:8765/

- `/` current page
- `/reset` September 20, 2026
- `/change` September 30, 2026
- `python demo/serve.py --set initial|changed`

End-to-end (API must be running, Groq key required for real agents):

```powershell
.\backend\.venv\Scripts\python.exe demo\run_e2e.py
```
