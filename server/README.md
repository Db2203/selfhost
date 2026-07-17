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
  indexer.py  library scan: hash, EXIF, dedup → asset rows
  worker.py   arq worker entrypoint (background jobs)
migrations/   Alembic migrations (run: alembic upgrade head)
tests/        pytest suite
```

## Run locally (without Docker)

Works on machines that can't run the compose stack (e.g. no virtualization).
Python 3.11+ (the ML pins need it); any local Redis-compatible server — on
Windows, [Memurai](https://www.memurai.com/) Developer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
```

Point `.env` at local services — SQLite is fine for dev (search then ranks
in Python instead of pgvector; CI still covers the Postgres path):

```
DATABASE_URL=sqlite+aiosqlite:///./data/dev.db
REDIS_URL=redis://127.0.0.1:6379/0
STORAGE_ROOT=./data/storage
LIBRARY_ROOT=./data/library
```

```bash
python -m alembic upgrade head            # -m so alembic can import app/
uvicorn app.main:app --reload
python -m arq app.worker.WorkerSettings   # second terminal
```

The web dev server reaches the native API with
`API_PROXY=http://127.0.0.1:8000 npm run dev` (from `web/`).

## Test & lint

```bash
pytest -q
ruff check .
```

The full stack (Postgres, Redis, Caddy) runs via `docker compose up` from the repo root.
