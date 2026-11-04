# Contributing to ReviewCrew

Thanks for helping improve ReviewCrew. Start with the [project README](README.md) for the feature overview and local setup. The [system map](docs/diagrams/system-map.svg) shows how the pieces fit together.

## Where to make a change

- `backend/app/routers/` — HTTP endpoints and request handling
- `backend/app/services/` — review logic, static checks, metrics, and test generation
- `backend/app/tasks/` — review pipeline orchestration
- `backend/app/models.py` and `backend/alembic/` — database models and migrations
- `frontend/src/pages/` — chat, review detail, and settings screens
- `frontend/src/components/` — reusable interface components
- `frontend/src/lib/` — API calls, streaming chat, formatting, and theme

## Development checks

From the project folder, install dependencies if needed:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
Set-Location frontend
npm ci
```

Then run the checks:

```powershell
Set-Location ..
& ".\.venv\Scripts\python.exe" -m pytest backend\tests
Set-Location frontend
npm run build
```

## Guidelines

- Keep API and UI behavior clear, and update the README when setup or user-facing behavior changes.
- Use the existing React components and design tokens; keep the interface readable in both light and dark themes.
- Never put credentials in source code, logs, screenshots, or examples. Use environment variables and keep `.env` files private.
- Keep findings tied to the relevant changed lines where possible, and distinguish deterministic checks from model-generated findings.
- Add or update focused tests when changing behavior.
- Use small, descriptive commits, for example `fix: handle empty diff input` or `docs: clarify Vercel setup`.
