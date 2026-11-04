# Deploy ReviewCrew to Vercel

This guide deploys the React website and FastAPI API from the project folder with the Vercel CLI. Neon Postgres stores reviews and chats. Reviews run inline on Vercel, so a Redis server or Celery worker is not required for the hosted demo.

## 1. Create a Neon project

1. Create a project at [Neon](https://neon.com/).
2. Open the project and choose **Connect**.
3. Select the `neondb` database and the owner role, enable **Pooled connection**, and copy the connection URL.
4. Keep the URL private. If it has appeared in a screenshot or chat, reset the role password and copy a fresh pooled URL.

## 2. Prepare Python and create the database tables

Open PowerShell in the project folder. The following creates the root virtual environment and installs the backend packages if you do not already have them:

```powershell
py -m venv .venv
& ".\.venv\Scripts\python.exe" -m ensurepip --upgrade
& ".\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
```

Set `DATABASE_URL` to the **URL value only**. Use single quotes, keep the command on one line, and do not paste `.env` comments or `DATABASE_URL_POOLED=`:

```powershell
$env:DATABASE_URL = 'PASTE_THE_NEW_NEON_POOLED_URL_HERE'
Push-Location backend
& "..\.venv\Scripts\python.exe" -m alembic upgrade head
Pop-Location
```

The migration output should say `PostgresqlImpl` and finish without an error. If it reports a password authentication failure, reset the Neon role password, copy a fresh connection URL, and set it again. When the migration succeeds, remove the temporary value from this PowerShell window:

```powershell
Remove-Item Env:DATABASE_URL
```

## 3. Link this folder to Vercel

Make sure PowerShell is in the folder containing `vercel.toml`:

```powershell
Get-Location
Test-Path .\vercel.toml
```

The second command must print `True`. Then link the project:

```powershell
npm install -g vercel@latest
vercel login
vercel link
```

Choose the existing Vercel project if you already created one. Do this from the app folder, not its parent folder.

## 4. Add production environment variables

In Vercel, open the project → **Settings → Environment Variables**. Add each entry for **Production**:

| Name | Value |
| --- | --- |
| `DATABASE_URL` | The new Neon pooled URL |
| `OPENROUTER_API_KEY` | An OpenRouter API key |
| `CELERY_TASK_ALWAYS_EAGER` | `true` |
| `OPENAI_TIMEOUT_SECONDS` | `45` |
| `ENVIRONMENT` | `production` |

Do not prefix secrets with `VITE_`; frontend variables are visible in a browser. Keep `.env` files out of Git.

## 5. Deploy

From the folder containing `vercel.toml`, run:

```powershell
vercel --prod
```

Vercel prints the production website URL after it completes.

## 6. Check the deployment

1. Open the production URL and submit a small code review.
2. Try a short chat follow-up.
3. Open `https://YOUR-SITE.vercel.app/health`. In inline mode, Redis should be reported as not required.

Environment-variable changes apply to a new deployment, so run `vercel --prod` again after changing them.

## Public demo considerations

The app currently has no sign-in. Visitors with the URL share the same workspace and can use the configured model key. Keep the URL within your hackathon audience, set a spending limit on your OpenRouter key, and rotate the key if it is exposed. Review AI suggestions before applying them.
