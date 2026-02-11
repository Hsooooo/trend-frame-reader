# Repository Guidelines

## Project Structure & Module Organization
- `app/` contains the FastAPI application.
- `app/main.py` wires routes, startup/shutdown hooks, CORS, and admin token checks.
- `app/routers/` defines API endpoints (`health`, `feeds`, `feedback`, `bookmarks`).
- `app/services/` contains ingestion, ranking, feed generation, and seed sync logic.
- `app/models.py`, `app/schemas.py`, `app/db.py`, and `app/config.py` hold data models, API schemas, DB setup, and settings.
- `scripts/bootstrap.sh` sets up a local virtualenv and dependencies.
- `docker-compose.yml` and `Dockerfile` provide containerized local development.

## Build, Test, and Development Commands
- `docker compose up --build`: start API + Postgres with containerized setup.
- `bash scripts/bootstrap.sh`: create `.venv` and install dependencies.
- `source .venv/bin/activate && uvicorn app.main:app --reload`: run API locally.
- `python3 -m compileall app`: quick syntax check across the codebase.
- `curl -H "Authorization: Bearer <ADMIN_TOKEN>" -X POST http://localhost:8000/admin/run-ingestion`: run ingestion manually.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and explicit type hints where practical.
- Use `snake_case` for functions/variables, `PascalCase` for classes, and short, descriptive module names.
- Keep router handlers thin; place business logic in `app/services/`.
- Prefer SQLAlchemy query composition already used in routers/services over raw SQL.

## Testing Guidelines
- No formal test suite exists yet; contributions should add tests under `tests/` using `pytest`.
- Name files `test_<feature>.py` and test functions `test_<behavior>()`.
- For API behavior, prioritize endpoint-level tests for `/feeds/today`, `/feedback`, and admin routes.
- Run tests with `pytest` once tests are added.

## Commit & Pull Request Guidelines
- Follow Conventional Commits, as seen in history: `feat: ...`, `fix: ...`, `revert: ...`.
- Keep commits scoped to one logical change.
- PRs should include:
  - clear problem/solution summary,
  - any env/config updates (`.env.example`, `README.md`),
  - API examples for changed endpoints (request/response snippets).

## Documentation Update Policy
- Record change history and work logs under `~/Personal/brain-dumpster/topics/trend-frame-reader/`.
- When code changes, deployments, or operational issue responses happen, update project docs in that directory first.
- Preferred docs to keep current: `CHANGELOG`, `IMPLEMENTATION-log`, and `DEPLOYMENT`.

## Security & Configuration Tips
- Never commit `.env` or real secrets; update `.env.example` when adding new settings.
- Set a strong `ADMIN_TOKEN`; all `/admin/*` endpoints depend on it.
- Restrict `CORS_ALLOWED_ORIGINS` to trusted frontend origins.
