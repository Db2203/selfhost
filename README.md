# PhotoNest

A self-hosted photo library — like Google Photos, but the photos live on **your** hardware.
Index the photos on your machine, browse the unified library securely from any device, and
search it with natural language.

> **Privacy by design:** your photos never leave your hardware, and all AI runs locally.

## Why

Cloud photo services mean handing your memories to someone else's servers. PhotoNest keeps
everything on a machine you control (a laptop now, a NAS later) while still giving you the
things that make cloud galleries nice: cross-device access, fast browsing, face grouping,
and "show me photos of the beach" search.

## Features (roadmap)

- [x] Secure, authenticated access — per-device login, nothing served to anonymous clients
- [x] Index a local photo folder (EXIF, dates, dedup)
- [x] Fast web gallery (timeline, lightbox)
- [x] Natural-language search (CLIP embeddings + vector search)
- [x] Face recognition & people grouping
- [x] Android app with camera-roll backup
- [x] iOS app (same Expo app; runs via Expo Go, native build needs a Mac)
- [x] Scale-out storage (S3/MinIO) and remote access (Tailscale)

## Architecture

```
                       ┌─────────────┐
   Phone / PC ──TLS──▶ │ Reverse     │
   (authenticated)     │ proxy(Caddy)│
                       └──────┬──────┘
                              │
                       ┌──────▼──────┐      ┌──────────────┐
                       │  API        │◀────▶│ Postgres     │
                       │  (FastAPI)  │      │ + pgvector   │
                       └──────┬──────┘      └──────────────┘
                              │ jobs (Redis queue)
                       ┌──────▼──────┐      ┌──────────────┐
                       │  Worker(s)  │◀────▶│ Storage      │
                       │  index /    │      │ (local FS →  │
                       │  thumbs /   │      │  S3/MinIO)   │
                       │  embeddings │      └──────────────┘
                       └──────┬──────┘
                       ┌──────▼──────┐
                       │ ML service  │  (CLIP search, face recognition)
                       └─────────────┘
```

- **Central-server model:** the host is the source of truth; clients upload to it and browse
  the unified library. No peer-to-peer sync.
- **Stateless API + separate worker tier** so each scales independently.
- **Storage interface** so moving from local disk to a NAS or object store is a config change.

## Tech stack

| Layer    | Choice                                  |
|----------|-----------------------------------------|
| API      | Python · FastAPI                        |
| Database | PostgreSQL · pgvector                   |
| Web      | React · Vite · TypeScript               |
| Mobile   | React Native · Expo (Android → iOS)     |
| Jobs     | Redis-backed worker queue               |
| AI       | CLIP (search) · InsightFace (faces)     |

## Repository layout

```
server/   FastAPI backend, workers, migrations
web/      React web client
mobile/   React Native (Expo) app — Android first
```

## Quick start

```bash
cp .env.example .env        # set LIBRARY_DIR to your photo folder + real secrets
docker compose up -d --build
docker compose exec api alembic upgrade head          # apply db migrations
docker compose exec api python -m app.cli create-user <name>   # create your account
docker compose exec api python -m app.cli index <name>         # scan + thumbnail
```

Then open **https://localhost** (LAN: `https://<laptop-ip>`), accept the
locally-signed certificate, and log in. The API is served under `/api`
(health check: `curl -k https://localhost/api/health`).

For access from outside your home network, see
[docs/remote-access.md](./docs/remote-access.md) (Tailscale — no open ports).

There is deliberately no public signup — accounts are created on the server.
All API endpoints require a Bearer token from `POST /auth/login`; each login
registers a named device that can be listed and revoked in the Devices page.
Image bytes are fetched with short-lived HMAC-signed URLs, your photo folder
is mounted read-only, and originals are never copied or modified.

Caddy serves HTTPS on `https://localhost` with a locally-signed certificate
(`-k` skips the trust check; install Caddy's root CA to remove the warning).

## Status

Early development. See the roadmap above; releases are tagged per milestone.

## License

MIT — see [LICENSE](./LICENSE).
