# FinAlly

AI trading workstation served from one Docker container on port 8000.

## Run With Docker

Build and start the app:

```bash
docker build -t finally .
docker run -d --name finally -p 8000:8000 -v finally-data:/app/db finally
```

Open http://localhost:8000. The FastAPI backend serves both the static Next.js frontend and `/api/*` routes from the same origin.

The SQLite database is stored at `/app/db/finally.db` in the container. The `finally-data` Docker volume keeps it across container restarts.

Stop the app without deleting the database volume:

```bash
docker rm -f finally
```

## Start Scripts

macOS/Linux:

```bash
./scripts/start_mac.sh
./scripts/stop_mac.sh
```

Windows PowerShell:

```powershell
.\scripts\start_windows.ps1
.\scripts\stop_windows.ps1
```

The stop scripts are idempotent and keep the `finally-data` volume. Re-run a start script with `--build` to force an image rebuild.

## Docker Compose

The compose file is a convenience wrapper around the same single-container deployment:

```bash
docker compose up --build
docker compose down
```

## Environment

The app starts without a `.env` file by using the built-in market simulator. To configure optional API keys, create `.env` from the example:

```bash
cp .env.example .env
```

Supported variables:

```bash
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
MASSIVE_API_KEY=
LLM_MOCK=false
```
