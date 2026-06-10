# mobile

React Native (Expo) app for PhotoNest: log in to your server, browse and
search the unified library, and back up the phone's camera roll.

## Run on a device

```bash
npm install
npx expo start        # scan the QR code with Expo Go on Android
```

Sign in with your server's URL (e.g. `https://192.168.1.20` on your LAN) and
your PhotoNest account.

### HTTPS note (important)

The server uses a locally-signed certificate by default. Android will refuse
it until you either:

- install Caddy's root CA on the phone (get it from the `caddy-data` volume:
  `.../pki/authorities/local/root.crt`), or
- put the server behind Tailscale with a real certificate (recommended for
  remote access anyway — see the project README).

## Backup

The Backup tab uploads camera-roll photos to `POST /assets/upload`. The
server deduplicates by content hash, so re-running a backup never creates
duplicates. Uploaded photos go through the same thumbnail/search/face
pipeline as indexed ones.

## Checks

```bash
npm run typecheck
```
