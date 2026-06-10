# web

React + Vite + TypeScript client for PhotoNest: login, infinite-scroll photo
timeline, lightbox, and device management.

In production the app is built into the Caddy image (`caddy/Dockerfile`) and
served at `https://localhost`, with the API under `/api`.

## Develop

```bash
npm install
npm run dev      # proxies /api to the compose stack (https://localhost)
```

## Check & build

```bash
npm run lint
npm run build
```
