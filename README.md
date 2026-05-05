# js-analysis

A self-hosted pipeline for collecting JavaScript files from bug bounty targets, normalizing them, and scanning for secrets using gitleaks and trufflehog. Runs on a home server behind NordVPN (via gluetun) and sends findings to Discord or Slack via [projectdiscovery/notify](https://github.com/projectdiscovery/notify).

---

## How it works

```
waymore + katana          fetcher              normalizer
(passive + active)  →  (download JS,  →   (beautify, decode  →  gitleaks
  URL collection        source maps,        base64/hex,           +
                        dedup by hash)      flatten concat)    trufflehog
                                                                   ↓
                                                             SQLite DB
                                                             + notify
```

1. **Collect** — waymore pulls historical URLs from Wayback Machine / Common Crawl; katana actively crawls the live site and extracts JS references.
2. **Fetch** — downloads each JS file with rate limiting and jitter. Deduplicates by SHA-256 content hash so the same file served from multiple URLs is only processed once. Also tries to fetch `.js.map` source maps, which often contain original unminified source code.
3. **Normalize** — beautifies minified JS, decodes `atob()` base64 calls, unescapes hex sequences, and flattens string concatenation. This significantly improves detection quality for obfuscated secrets.
4. **Scan** — runs gitleaks (rule-based, fast) and trufflehog (entropy-based, better for unknown secrets) against the normalized files.
5. **Persist** — all findings go into a SQLite database. Duplicate findings are deduplicated; `first_seen` / `last_seen` timestamps track when secrets appear and disappear.
6. **Notify** — new high-entropy or high-value findings are sent through `notify` to Discord, Slack, or any supported provider.

Scans are incremental: on repeat runs only new or changed JS files are processed.

---

## Architecture

```
js-analysis/
├── Dockerfile                      multi-stage: Go tools + Python 3.11
├── docker-compose.yml              gluetun (NordVPN WireGuard) + worker + scheduler
├── config.yaml                     global settings (delays, thresholds, paths)
├── pipeline.py                     core orchestration logic
├── main.py                         CLI entry point
├── scheduler.py                    APScheduler-based cron runner
│
├── collectors/
│   ├── waymore.py                  passive URL collection
│   └── katana.py                   active crawl
│
├── fetcher/
│   └── downloader.py               threaded download, source map fetching
│
├── normalizer/
│   └── js_normalizer.py            JS deobfuscation
│
├── scanners/
│   ├── gitleaks_runner.py
│   ├── trufflehog_runner.py
│   └── notifier.py                 thin wrapper around notify CLI
│
├── db/
│   └── store.py                    SQLite adapter
│
├── jobs/
│   ├── job_manager.py              queue operations
│   └── worker.py                   polling worker loop
│
├── targets/                        one YAML file per bug bounty target
│   └── example-target.yaml
│
└── data/                           created at runtime (gitignored)
    ├── raw_js/                     downloaded JS files (keyed by SHA-256)
    ├── normalized_js/              temporary; cleaned after each scan
    ├── tmp/                        waymore output files
    └── findings.db                 SQLite database
```

---

## Prerequisites

### On the host machine

- Docker and Docker Compose (v2)
- A Mullvad subscription
- `wireguard-tools`, `curl`, `jq` (only needed to run `scripts/rotate_key.sh`)

### Mullvad account number

Your Mullvad account number is the 16-digit number shown at [mullvad.net/account](https://mullvad.net/account). No email or password — just the number.

---

## Installation

```bash
git clone <repo-url> js-analysis
cd js-analysis
```

### 1. Set up credentials

```bash
cp .env.example .env
```

Set your account number in `.env`:

```env
MULLVAD_ACCOUNT=0000000000000000
VPN_COUNTRY=Netherlands
```

Then generate and register a WireGuard key automatically:

```bash
bash scripts/rotate_key.sh
```

This generates a key pair locally, registers the public key with Mullvad's API, and writes `MULLVAD_WG_KEY` and `MULLVAD_WG_ADDR` back into `.env`. Run it any time you want to rotate the key.

### 2. Set up notification provider

```bash
cp notify-config.yaml.example notify-config.yaml
```

Edit `notify-config.yaml` with your Discord webhook (or Slack, Telegram, etc.):

```yaml
discord:
  - id: "js-secrets"
    discord_webhook_url: "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
    discord_username: "js-hunter"
    discord_format: "{{data}}"
    discord_webhook_type: "regular"
```

Full list of supported providers: [notify documentation](https://github.com/projectdiscovery/notify)

### 3. Add a target

```bash
cp targets/example-target.yaml targets/myprogram.yaml
```

Edit `targets/myprogram.yaml` (see [Target configuration](#target-configuration) below).

### 4. Build and start

```bash
docker compose up --build -d
```

This starts three containers:

| Container | Role |
|-----------|------|
| `gluetun` | NordVPN WireGuard tunnel — all outbound traffic routes through it |
| `js-worker` | Polls the job queue and runs pipelines |
| `js-scheduler` | Reads target files and enqueues jobs on their cron schedules |

---

## Usage

### Run a single target immediately

```bash
docker compose run --rm worker run targets/myprogram.yaml
```

Output example:

```
────────────── example.com ──────────────
Collecting JS URLs...
  waymore :   847 URLs
  katana  :   312 URLs
  total   :   934 (after dedup / filters)
Fetching JS files...
  fetched 412, new 312
Normalizing...
  normalized 318 files
Scanning...
  gitleaks   :    4 findings
  trufflehog :    7 findings
Done — 3 new findings.
```

### Start the full service (worker + scheduler)

```bash
docker compose up -d
```

The scheduler reads all `*.yaml` files in the `targets/` directory and registers cron jobs. The worker picks up jobs as they are enqueued.

### Manually enqueue a job

```bash
docker compose run --rm worker enqueue example.com targets/myprogram.yaml
```

### View live logs

```bash
# All containers
docker compose logs -f

# Worker only
docker compose logs -f worker

# Scheduler only
docker compose logs -f scheduler
```

### Stop everything

```bash
docker compose down
```

---

## Configuration

### `config.yaml` — global settings

```yaml
data_dir: data
reports_dir: reports

fetcher:
  delay: 1.5          # base delay between requests (seconds)
  jitter: 0.5         # random extra delay added to each request (0 to jitter)
  max_concurrent: 3   # parallel download threads
  timeout: 15         # per-request timeout
  max_content_mb: 10  # skip files larger than this

collectors:
  katana:
    depth: 2          # crawl depth (increase with care — can explode)
    timeout: 300      # max seconds katana is allowed to run per target
    js_crawl: true    # headless JS crawling; requires chromium (built into image)
  waymore:
    mode: U           # U = URLs only

scanners:
  min_entropy_notify: 3.5   # send notification if finding entropy >= this
  high_value_types:         # always notify regardless of entropy
    - aws
    - github
    - stripe
    - twilio
    - slack
    - sendgrid
    - jwt
    - private_key
    - google
```

**Tuning tips:**

- Lower `delay` + higher `max_concurrent` = faster, higher risk of triggering rate limits
- `katana.js_crawl: false` disables headless crawling, making katana much faster and less resource-intensive; useful for non-SPA targets
- Add secret types to `high_value_types` to always get notified for them regardless of entropy score

---

### Target configuration (`targets/*.yaml`)

Each bug bounty target gets its own YAML file.

```yaml
domain: example.com
program: "HackerOne - Example Program"

# Only collect URLs that contain at least one of these strings
scope:
  - "example.com"

# Skip URLs that contain any of these strings
exclude:
  - "cdn.example.com"
  - "static.third-party.com"

# Maximum number of JS URLs to process per run (controls scan time and disk use)
max_urls: 3000

# Katana crawl depth for this target (overrides global config)
crawl_depth: 2

# Standard 5-field cron: minute hour day month weekday
# This example runs nightly at 03:00
schedule: "0 3 * * *"

# Whether to send findings through notify for this target
notify: true
```

**Cron schedule examples:**

| Schedule | Meaning |
|----------|---------|
| `0 3 * * *` | Daily at 03:00 |
| `0 */6 * * *` | Every 6 hours |
| `0 3 * * 1` | Every Monday at 03:00 |
| `0 3 1 * *` | First day of each month at 03:00 |

**Adding multiple targets:**

```bash
cp targets/example-target.yaml targets/program-a.yaml
cp targets/example-target.yaml targets/program-b.yaml
# edit each file, then restart the scheduler
docker compose restart scheduler
```

---

### `notify-config.yaml` — notification providers

Mounted read-only into containers at `/root/.config/notify/provider-config.yaml`.

**Discord:**
```yaml
discord:
  - id: "js-secrets"
    discord_webhook_url: "https://discord.com/api/webhooks/ID/TOKEN"
    discord_username: "js-hunter"
    discord_format: "{{data}}"
    discord_webhook_type: "regular"
```

**Slack:**
```yaml
slack:
  - id: "js-secrets"
    slack_webhook_url: "https://hooks.slack.com/services/T/B/X"
    slack_username: "js-hunter"
    slack_format: "{{data}}"
```

**Telegram:**
```yaml
telegram:
  - id: "js-secrets"
    telegram_api_key: "YOUR_BOT_TOKEN"
    telegram_chat_id: "YOUR_CHAT_ID"
    telegram_format: "{{data}}"
```

---

## Viewing findings

Findings are stored in `data/findings.db` (SQLite). You can query it from the host:

```bash
# Install sqlite3 if needed: brew install sqlite3 / apt install sqlite3

sqlite3 data/findings.db

# All findings for a target
SELECT f.secret_type, f.detector, f.value, f.entropy, f.url, f.first_seen
FROM findings f
JOIN targets t ON t.id = f.target_id
WHERE t.domain = 'example.com'
ORDER BY f.entropy DESC;

# New findings from the last 24 hours
SELECT secret_type, detector, value, url, first_seen
FROM findings
WHERE first_seen >= datetime('now', '-1 day')
ORDER BY first_seen DESC;

# Findings by type across all targets
SELECT secret_type, COUNT(*) as count
FROM findings
GROUP BY secret_type
ORDER BY count DESC;

# High-entropy findings
SELECT secret_type, value, entropy, url
FROM findings
WHERE entropy >= 4.0
ORDER BY entropy DESC;
```

gitleaks CSV reports are also written to `reports/gitleaks_<domain>.csv` for each run.

---

## VPN configuration

All traffic from the `worker` and `scheduler` containers is routed through gluetun, which maintains a Mullvad WireGuard tunnel.

### Rotate the WireGuard key

Mullvad keys are stable (no device-slot eviction) but can be rotated at any time:

```bash
bash scripts/rotate_key.sh
docker compose restart gluetun
```

The script generates a new key pair locally, registers the public key with Mullvad's API, and updates `MULLVAD_WG_KEY` and `MULLVAD_WG_ADDR` in `.env` automatically. The private key is never sent to Mullvad.

### Change exit country

Edit `.env`:

```env
VPN_COUNTRY=United States
```

Then restart gluetun:

```bash
docker compose restart gluetun
```

### Verify VPN is active

```bash
docker compose exec worker curl -s https://ipinfo.io
```

The response should show a Mullvad exit IP, not your home IP. You can also verify at [mullvad.net/check](https://mullvad.net/check).

### Supported countries

Any country name supported by Mullvad works (e.g., `Germany`, `United States`, `Japan`, `Singapore`). For city-level selection, add to `docker-compose.yml`:

```yaml
environment:
  - SERVER_CITIES=Amsterdam
```

---

## Disk space

Raw JS files accumulate in `data/raw_js/`. Each file is stored once by its SHA-256 hash — deduplication prevents the same file from being stored multiple times across different targets or runs.

Normalized JS is temporary and is deleted after each scan. Only raw files and the SQLite database are kept long-term.

Monitor disk usage:

```bash
du -sh data/raw_js/
du -sh data/findings.db
```

To free space while keeping the database:

```bash
# Remove raw JS older than 30 days
find data/raw_js/ -name "*.js" -mtime +30 -delete
```

---

## Troubleshooting

### gluetun fails to connect

```bash
docker compose logs gluetun
```

Common causes:
- Invalid `NORDVPN_WG_KEY` in `.env` — regenerate from the NordVPN dashboard
- `SERVER_COUNTRIES` value doesn't match any NordVPN server — try `Netherlands` or `United States`

### katana finds no URLs

- Check `js_crawl: true` — headless crawling requires chromium (included in the image)
- Try lowering `crawl_depth` to `1` for large targets
- Verify the target is reachable: `docker compose run --rm worker curl -s https://example.com`

### waymore is slow or times out

waymore queries multiple external sources (Wayback Machine, Common Crawl) which can be slow. The collector uses a 600-second timeout and returns partial results if it times out. This is expected behavior.

### No notifications received

1. Verify `notify-config.yaml` exists and is correctly formatted
2. Test notify manually:
   ```bash
   docker compose run --rm worker sh -c 'echo "test message" | notify -silent'
   ```
3. Check that `notify: true` is set in the target YAML
4. Check that the finding meets the notification threshold (`min_entropy_notify` in `config.yaml`)

### Rescan a target from scratch

Delete the target's entry from the database to force all files to be re-fetched and re-scanned:

```bash
sqlite3 data/findings.db "DELETE FROM js_files WHERE target_id = (SELECT id FROM targets WHERE domain = 'example.com')"
```

---

## Tools included in the image

| Tool | Version | Purpose |
|------|---------|---------|
| [katana](https://github.com/projectdiscovery/katana) | latest | Active JS crawling |
| [waymore](https://github.com/xnl-h4ck3r/waymore) | latest | Passive historical URL collection |
| [gitleaks](https://github.com/gitleaks/gitleaks) | v8 | Rule-based secret detection |
| [trufflehog](https://github.com/trufflesecurity/trufflehog) | v3 | Entropy-based secret detection |
| [notify](https://github.com/projectdiscovery/notify) | latest | Multi-provider notifications |
| [gluetun](https://github.com/qdm12/gluetun) | latest | NordVPN WireGuard tunnel |
