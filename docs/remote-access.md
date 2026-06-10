# Remote access with Tailscale

PhotoNest should never be exposed by port-forwarding your router — that puts
a login page on the public internet. Use [Tailscale](https://tailscale.com):
a WireGuard mesh where only your own devices can reach the server, with no
open ports.

## Setup (~10 minutes)

1. **Install Tailscale on the laptop/NAS** that runs PhotoNest:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. **Install the Tailscale app** on your phone and any other devices, and log
   in to the same tailnet.

3. **Get a real HTTPS certificate** for the tailnet name (Tailscale issues
   Let's Encrypt certs for `<machine>.<tailnet>.ts.net`):

   ```bash
   sudo tailscale cert <machine>.<tailnet>.ts.net
   ```

4. **Point Caddy at the tailnet hostname.** In `caddy/Caddyfile`, replace the
   `localhost` site address with your `ts.net` name and remove `tls internal`
   (mount the cert + key into the container and reference them with a `tls`
   directive, or let Caddy fetch certs itself if you give it DNS access).

5. Open `https://<machine>.<tailnet>.ts.net` from anywhere. The mobile app
   accepts the same URL as its server address — with a real certificate, no
   CA install is needed on the phone.

## Why this beats port-forwarding

- Nothing is reachable from the public internet — the auth perimeter is your
  tailnet, *and then* PhotoNest's own login.
- Real certificates, so phones/browsers trust the connection out of the box.
- Works from any network (mobile data included) without dynamic-DNS hacks.
