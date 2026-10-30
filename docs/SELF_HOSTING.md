# Self-Hosting Orca

Orca is local-first by default — no external API calls for chat unless you
explicitly opt into a cloud teacher model for distillation. This guide
covers running it yourself, from a laptop to a real deployment.

## Quick start (local, single-user)

```bash
git clone https://github.com/Guruprasath-Annadurai/Orneur.git
cd Orneur
uv pip install -e .

# Install Ollama and pull a model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b   # or your preferred model

orca serve
```

Opens on `http://localhost:7337`. Data lives at `~/.orca` by default (SQLite,
ChromaDB, memory files, audit log). No cloud dependency, no account with a
third party required to run this.

## Configuration

Copy `.env.example` to `.env` and fill in only what you need — most fields
are optional:

```bash
cp .env.example .env
```

Key variables:
- `ORCA_LICENSE_SECRET` — required before generating/verifying license keys at scale
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` — only if you're taking payments
- `ORCA_DATABASE_URL` — set this to switch from SQLite to Postgres (needed for multi-instance deployments — see below)
- `ORCA_REDIS_URL` — set this to enable cross-instance session continuity (also multi-instance only)
- `NVIDIA_API_KEY` — only if using a cloud teacher model for distillation (`orca/train/distill.py`), never used for live chat

**Do not set `ORCA_HOME` to a value with an unexpanded `~`** — see the
comment in `.env.example` for why (a real bug this project found and fixed
in its own testing: `~` doesn't auto-expand in every code path that reads
environment variables, and a raw `~/.orca` string can silently redirect all
your data to the wrong location).

## Scaling beyond one instance

Single-instance/local deployments work fine on SQLite with in-memory
sessions — this is the default and requires no extra setup.

Once you're running multiple API instances behind a load balancer, two
things need to move from "in-process" to "shared":

1. **Database**: set `ORCA_DATABASE_URL=postgresql://...` — see
   `docker-compose.yml` for a ready-to-use Postgres service definition.
   Migrate existing SQLite data with `orca/auth/migrate_to_postgres.py`.
2. **Sessions**: set `ORCA_REDIS_URL=redis://...` — without this, a
   user's conversation continuity breaks if their next request lands on a
   different instance than the one that handled their last message.

## Docker / docker-compose

```bash
docker compose up -d
```

Brings up Ollama, the Orca API, and (if uncommented in `docker-compose.yml`)
Postgres and Redis. See the comments in that file — Postgres/Redis services
are opt-in, commented out by default, since most deployments don't need
them.

## Fly.io deployment

```bash
./scripts/deploy_fly.sh
```

See `fly.toml` and `Dockerfile.fly`. This deploys a single-instance
configuration to Fly.io's platform. Note: as of this writing, this
deployment path has been built and configured but not verified against a
live Fly.io environment — treat it as a documented starting point, test it
yourself before depending on it for a real launch.

## Backups

Zero backup automation exists unless you set it up. Run manually or via
cron:

```
orca data-backup keygen /secure/place/orneur-backup.key     # once; YOU keep this key, never next to the data or the backups
orca data-backup create /backups/orneur-$(date +%F).orbk --key-file /secure/place/orneur-backup.key
orca data-backup verify  /backups/orneur-2026-01-01.orbk --key-file /secure/place/orneur-backup.key
orca data-backup export-deletions /offhost/deletions-$(date +%F).json --key-file ...   # keep off this host
orca data-backup restore /backups/orneur-2026-01-01.orbk --key-file ... --overwrite    # server stopped; refuses without deletion history
```

The earlier plaintext `orca backup` / `orca restore` commands are **retired** (L02-B6): they wrote unencrypted copies of the accounts database and restored them without
consulting deletion history. Existing plaintext backups: see
`docs/orneur/landmarks/landmark-02/b6-backup-privacy/B6_LEGACY_MIGRATION.md`. Limits and the founder decisions still open (key custody, backup retention, off-host anchoring):
`docs/orneur/landmarks/landmark-02/b6-backup-privacy/B6_BACKUP_PRIVACY_REPORT.md`. Postgres is not covered by `orca data-backup`; use your database's own
tooling with the same encryption and deletion-history care.

## Monitoring

- `GET /metrics` — Prometheus exposition format, no auth (standard scrape
  convention — put a firewall/reverse-proxy rule in front of this port if
  it's internet-reachable)
- `GET /api/admin/metrics` — JSON snapshot, requires admin auth

Both are in-memory, single-instance metrics — see `orca/serve/metrics.py`
docstring for the honest scope of what this does and doesn't cover for
multi-instance deployments.

## Model training / fine-tuning

Orca ships with a fine-tuning pipeline for three variants (nano/core/ultra),
but training a real checkpoint requires a real GPU (an H100-class card is
what this project's own testing targeted — see `orca/train/variants.py`
for exact VRAM requirements per variant). See `orca/train/` for the full
pipeline: data seeding, fine-tuning, evaluation, red-teaming, and
distillation from a teacher model.
