# PortPilot deployment runbook

Target: a single disposable Ubuntu 24.04 VM. **No other credentials live on this
host.** The API and worker run on the host (they drive the Docker CLI); Caddy and
a rootless BuildKit sidecar run in containers (`deploy/compose.yml`). The Docker
socket is **never** mounted into any container, including Caddy and BuildKit.

## 0. Provision the VM

- Ubuntu 24.04 LTS, a size with at least 2 vCPU / 4 GB RAM (sandbox containers need
  headroom on top of the API/worker).
- A DNS `A`/`AAAA` record for `api.<domain>` pointing at the VM's public IP, created
  before starting Caddy (it needs to answer an HTTP-01 challenge on port 80).
- **Firewall: only 80 and 443 open** to the internet. SSH (22) only from your own
  IP/VPN, nothing else. No inbound access to 8000 (the API's own port) or to
  BuildKit's 1234 — both are bound to `127.0.0.1` and reached only through Caddy or
  from the host itself.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   # restrict further with `from <your-ip>` if possible
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 1. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$(whoami)"
newgrp docker
docker version
```

## 2. A dedicated `portpilot` user

The systemd units run as this user, not root:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin portpilot
sudo usermod -aG docker portpilot   # the worker drives the Docker CLI
```

## 3. uv and the repo

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo mkdir -p /opt/portpilot
sudo chown "$(whoami)":"$(whoami)" /opt/portpilot
git clone <this-repo-url> /opt/portpilot
cd /opt/portpilot
uv sync --frozen
```

## 4. `.env`

Copy `.env.example` to `/opt/portpilot/.env` and fill in the secrets. **Never commit
it.** At minimum for production:

```bash
MONGODB_URI=mongodb+srv://...          # Atlas, this VM's IP allow-listed
MONGODB_DB=portpilot
OPENROUTER_API_KEY=...
VOYAGE_API_KEY=...
PORTPILOT_API_TOKEN=<32+ random bytes, e.g. `openssl rand -hex 32`>
PORTPILOT_CORS_ORIGINS=https://<your-vercel-domain>
SANDBOX_IMAGE=portpilot-sandbox:dev
BUILDKIT_ADDR=tcp://127.0.0.1:1234
PORTPILOT_MVP_STORE=atlas
```

`PORTPILOT_API_INSECURE_DEV` must **not** be set on this host — its absence is what
makes `create_app` refuse to start without `PORTPILOT_API_TOKEN`.

```bash
sudo chown portpilot:portpilot /opt/portpilot/.env
sudo chmod 600 /opt/portpilot/.env
```

## 5. Build the sandbox image and start BuildKit

BuildKit (the sidecar in `compose.yml`) must be up before you build the sandbox
image or run anything that calls `build_image`:

```bash
cd /opt/portpilot/deploy
PORTPILOT_DOMAIN=api.<domain> docker compose up -d buildkitd
```

Build the sandbox image the worker's `SandboxManager` uses for every run container:

```bash
cd /opt/portpilot
docker build -t portpilot-sandbox:dev -f docker/sandbox/Dockerfile .
```

Re-run this whenever `docker/sandbox/Dockerfile` changes; `portpilot-worker` picks up
the new image on its next restart (`Restart=always` on the systemd unit, or a manual
`sudo systemctl restart portpilot-worker`).

## 6. systemd units

```bash
sudo cp deploy/systemd/portpilot-api.service /etc/systemd/system/
sudo cp deploy/systemd/portpilot-worker.service /etc/systemd/system/
sudo mkdir -p /opt/portpilot/.venv   # uv sync already created this; just confirming
sudo systemctl daemon-reload
sudo systemctl enable --now portpilot-api portpilot-worker
sudo systemctl status portpilot-api portpilot-worker
```

Both units set `Restart=always`. For the worker, that restart *is* the resume
mechanism after a kill or OOM: the dead worker's lease expires
(`settings.lease_seconds`), and the worker systemd restarts it under reclaims the
run via `claim_run`, which resumes it per `docs/plan/MVP_PLAN.md` §3.7.

Logs:

```bash
journalctl -u portpilot-api -f
journalctl -u portpilot-worker -f
```

## 7. Caddy: automatic TLS

```bash
cd /opt/portpilot/deploy
PORTPILOT_DOMAIN=api.<domain> docker compose up -d caddy
```

Caddy requests and renews the certificate for `api.<domain>` automatically (HTTP-01,
ports 80/443 already opened in step 0) and reverse-proxies to the API on
`127.0.0.1:8000`. Check it:

```bash
curl https://api.<domain>/api/health
# {"ok":true,"version":"0.1.0"}
```

## 8. Vercel environment variables for `web/`

Set these as **server-side** env vars in the Vercel project settings (never
`NEXT_PUBLIC_*` — the client in `web/` never talks to the PortPilot API directly,
only through its own `/api/pp/*` proxy route):

| Variable | Value | Notes |
|---|---|---|
| `PORTPILOT_API_URL` | `https://api.<domain>` | No trailing slash needed either way. |
| `PORTPILOT_API_TOKEN` | same value as this VM's `PORTPILOT_API_TOKEN` | Server-only; the proxy attaches it as `Authorization: Bearer`. |
| `PORTPILOT_UI_PASSCODE` | a separate shared passcode for the UI itself | **Required** — see the security checklist below. Omitting it leaves the UI open to anyone with the URL. |
| `PORTPILOT_UI_SECRET` | `openssl rand -hex 32` (a different value than the API token) | Signs the UI's session cookie; required whenever `PORTPILOT_UI_PASSCODE` is set. |

Also set `PORTPILOT_CORS_ORIGINS` on the VM's `.env` to the exact Vercel production
domain (and any preview domains you want to allow), comma-separated.

## Security checklist

- [ ] Firewall: only 80 and 443 open to the internet (step 0).
- [ ] No credentials on this VM beyond `/opt/portpilot/.env` (Atlas URI, OpenRouter
      key, Voyage key, `PORTPILOT_API_TOKEN`) — no cloud provider keys, no SSH keys
      belonging to other systems, no `.aws`/`.kube` configs. Treat the VM as
      disposable: if it's compromised, destroy it and rebuild from this runbook.
- [ ] `.env` is `chmod 600`, owned by `portpilot:portpilot`, never committed.
- [ ] `PORTPILOT_API_INSECURE_DEV` is unset in production.
- [ ] `PORTPILOT_UI_PASSCODE` / `PORTPILOT_UI_SECRET` are set on Vercel — the API
      being behind a bearer token is not enough on its own, because the UI itself
      would otherwise be reachable by anyone with the URL, and the UI is what
      starts runs (which execute arbitrary repo code in sandboxes and spend your
      model/embedding credits).
- [ ] `PORTPILOT_CORS_ORIGINS` lists only the Vercel domain(s), not `*`.
- [ ] The Docker socket is not mounted into any container (`compose.yml` — verify
      with `docker inspect <container> | grep -i docker.sock` if in doubt).
- [ ] `config/cli_allowlist.yaml` is reviewed by a human before any change; the
      agent never gets write access to it.

### Token rotation procedure

`PORTPILOT_API_TOKEN` is the only credential the browser-facing side depends on
(via Vercel's `PORTPILOT_API_TOKEN`), so rotation is safe to do without downtime
if you accept one brief window where old and new tokens overlap:

1. Generate a new token: `openssl rand -hex 32`.
2. Update `/opt/portpilot/.env` on the VM with the new `PORTPILOT_API_TOKEN`.
3. `sudo systemctl restart portpilot-api` (the worker does not read `api_token` and
   does not need restarting).
4. Update the `PORTPILOT_API_TOKEN` Vercel env var to the same new value and
   redeploy (or use Vercel's env var "redeploy" action).
5. Confirm: `curl -H "Authorization: Bearer <new token>" https://api.<domain>/api/health`
   — this route ignores auth, so instead confirm against `GET /api/runs`.
6. There is no separate revocation step for the old token: once step 2/3 land, the
   old token is simply rejected by `hmac.compare_digest` on every subsequent
   request. Rotate immediately if the token is ever logged, committed, or exposed.

## Updating the code

```bash
cd /opt/portpilot
git fetch origin
git checkout <ref>
uv sync --frozen
sudo systemctl restart portpilot-api portpilot-worker
```

The worker restart interrupts any run mid-step; per §3.7 it resumes cleanly from
the last committed checkpoint on the next claim.
