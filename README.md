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

- [ ] Secure, authenticated access — per-device login, nothing served to anonymous clients
- [ ] Index a local photo folder (EXIF, dates, dedup)
- [ ] Fast web gallery (timeline, lightbox)
- [ ] Natural-language search (CLIP embeddings + vector search)
- [ ] Face recognition & people grouping
- [ ] Android app with camera-roll auto-backup
- [ ] iOS app
- [ ] Scale-out storage (S3/MinIO) and remote access

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
mobile/   React Native app (added later)
```

## Quick start

```bash
cp .env.example .env        # then edit the placeholder secrets
docker compose up -d --build
curl -k https://localhost/health
```

Caddy serves HTTPS on `https://localhost` with a locally-signed certificate
(`-k` skips the trust check; install Caddy's root CA to remove the warning).

## Status

Early development. See the roadmap above; releases are tagged per milestone.

## License

MIT — see [LICENSE](./LICENSE).
