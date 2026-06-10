# server

FastAPI backend for PhotoNest: authentication, the asset API, and the background workers
that index photos, generate thumbnails, and compute AI embeddings.

## Layout

```
app/
  main.py     FastAPI app factory + /health
  config.py   environment-driven settings (pydantic-settings)
  db.py       async engine + session dependency
  models.py   SQLAlchemy models (users, devices, assets, thumbnails)
  storage/    Storage interface + local-filesystem backend
  worker.py   arq worker entrypoint (background jobs)
migrations/   Alembic migrations (run: alembic upgrade head)
tests/        pytest suite
```

## Run locally (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Test & lint

```bash
pytest -q
ruff check .
```

The full stack (Postgres, Redis, Caddy) runs via `docker compose up` from the repo root.
