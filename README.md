# js-analysis

A self-hosted pipeline for collecting JavaScript files from bug bounty targets, normalizing them, and scanning for secrets using gitleaks and trufflehog. Runs on a home server behind Mullvad VPN (via gluetun) and sends findings to Discord or Slack via [projectdiscovery/notify](https://github.com/projectdiscovery/notify).

---

## Prerequisites

- Docker and Docker Compose (v2)
- A Mullvad subscription — account number from [mullvad.net/account](https://mullvad.net/account)
- `wireguard-tools`, `curl`, `jq` on the host (only needed for `scripts/rotate_key.sh`)

---

## Installation

```bash
git clone <repo-url> js-analysis
cd js-analysis
```

### 1. Set up VPN credentials

```bash
cp .env.example .env
```

#### Option A — from a downloaded config bundle (recommended)

1. Log in to [mullvad.net/account](https://mullvad.net/account)
2. Go to **WireGuard configuration**
3. Select your device, choose **All countries**, Linux platform, and download the zip
4. Extract the zip — every `.conf` file inside shares the same `PrivateKey` and `Address`
5. Open any `.conf` file and copy two values into `.env`:

```ini
[Interface]
PrivateKey = <your key>       → MULLVAD_WG_KEY
Address = 10.x.x.x/32,...    → MULLVAD_WG_ADDR  (IPv4 only, before the comma)
```

`.env` result:

```env
MULLVAD_WG_KEY=<PrivateKey value>
MULLVAD_WG_ADDR=10.x.x.x/32
MULLVAD_ACCOUNT=<your 16-digit account number>
VPN_COUNTRY=Netherlands
```

> Keep the downloaded zip outside the project directory or delete it after copying — it contains your private key.

#### Option B — generate a new key via script

Requires `wireguard-tools`, `curl`, and `jq` on the host:

```bash
echo "MULLVAD_ACCOUNT=0000000000000000" >> .env
bash scripts/rotate_key.sh
```

Generates a key pair locally, registers the public key with Mullvad's API, and writes `MULLVAD_WG_KEY` and `MULLVAD_WG_ADDR` into `.env` automatically.

### 2. Set up notification provider

```bash
cp notify-config.yaml.example notify-config.yaml
```

Edit `notify-config.yaml` with your webhook:

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

Set `enabled: true` and fill in the domain, scope, and schedule. See [Target configuration](#target-configuration) below.

### 4. Build and start

```bash
docker compose up --build -d
```

| Container | Role |
|-----------|------|
| `gluetun` | Mullvad WireGuard tunnel — all outbound traffic routes through it |
| `js-worker` | Polls the job queue and runs pipelines |
| `js-scheduler` | Reads target files and enqueues jobs on their cron schedules |

---

## Usage

### One-shot scan (run once, no schedule)

Set `schedule: ~` in the target YAML, then run:

```bash
docker compose run --rm worker run targets/myprogram.yaml
```

The full service does not need to be running. Executes the pipeline once and exits.

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

### Recurring scan (scheduled)

Set a cron schedule in the target YAML and start the full service:

```bash
docker compose up -d
```

The scheduler registers cron jobs for every enabled target with a `schedule` field. Targets with `schedule: ~` are listed as `one-shot` in the scheduler log and never auto-enqueued.

### Manually enqueue a job

```bash
docker compose run --rm worker enqueue example.com targets/myprogram.yaml
```

### View live logs

```bash
docker compose logs -f           # all containers
docker compose logs -f worker
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
  jitter: 0.5         # random extra delay added per request
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
  min_entropy_notify: 3.5   # notify if finding entropy >= this
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
- Lower `delay` + higher `max_concurrent` = faster but higher risk of rate limiting
- `katana.js_crawl: false` disables headless crawling — much faster for non-SPA targets
- Add types to `high_value_types` to always notify for them regardless of entropy

---

### Target configuration (`targets/*.yaml`)

Each bug bounty target gets its own YAML file. Copy `example-target.yaml` to get started.

```yaml
enabled: true           # false = template/disabled, skipped by scheduler and pipeline

domain: example.com
program: "HackerOne - Example Program"

# Only collect URLs containing at least one of these strings
scope:
  - "example.com"

# Skip URLs containing any of these strings
exclude:
  - "cdn.example.com"
  - "static.third-party.com"

crawl_depth: 2
max_urls: 3000

# schedule: ~               → one-shot: run manually, never auto-enqueued
# schedule: "0 3 * * *"    → recurring nightly at 03:00
# schedule: "0 */6 * * *"  → recurring every 6 hours
schedule: ~

# Send findings through notify
notify: true

# Send pipeline progress through notify at each stage (collect / fetch / scan / done)
verbose: false
```

**`enabled`** — set to `false` to disable a target entirely. The scheduler will skip it and the pipeline will refuse to run it. `example-target.yaml` ships with `enabled: false` so it is never accidentally executed.

**`schedule`** — omit or set to `~` for one-shot targets. Standard 5-field cron when recurring:

| Schedule | Meaning |
|----------|---------|
| `0 3 * * *` | Daily at 03:00 |
| `0 */6 * * *` | Every 6 hours |
| `0 3 * * 1` | Every Monday at 03:00 |
| `0 3 1 * *` | First day of each month at 03:00 |

**`notify`** — sends new findings through the notify CLI. Only fires for findings that exceed `min_entropy_notify` or match a `high_value_types` entry.

**`verbose`** — sends pipeline progress through notify at each stage: scan started, URLs collected, files fetched, normalizing, scanning, and final finding count. Useful for monitoring long-running scans from your phone.

**Adding multiple targets:**

```bash
cp targets/example-target.yaml targets/program-a.yaml
cp targets/example-target.yaml targets/program-b.yaml
# set enabled: true in each, then restart the scheduler
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

Findings are stored in `data/findings.db` (SQLite):

```bash
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

All traffic from the `worker` and `scheduler` containers routes through gluetun, which maintains a Mullvad WireGuard tunnel.

### Rotate the WireGuard key

```bash
bash scripts/rotate_key.sh
docker compose restart gluetun
```

Generates a new key pair locally, registers the public key with Mullvad's API, and updates `MULLVAD_WG_KEY` and `MULLVAD_WG_ADDR` in `.env`. The private key is never sent to Mullvad.

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

Any Mullvad country name works (e.g., `Germany`, `United States`, `Japan`, `Singapore`). For city-level selection, add to `docker-compose.yml`:

```yaml
environment:
  - SERVER_CITIES=Amsterdam
```

---

## Disk space

Raw JS files accumulate in `data/raw_js/`, stored once per unique SHA-256 content hash. Normalized JS is temporary and deleted after each scan.

```bash
du -sh data/raw_js/
du -sh data/findings.db

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
- Invalid `MULLVAD_WG_KEY` — regenerate from [mullvad.net/account](https://mullvad.net/account) or run `bash scripts/rotate_key.sh`
- Invalid `MULLVAD_WG_ADDR` — must be the IPv4 address (`10.x.x.x/32`) from the WireGuard config, not the IPv6
- `SERVER_COUNTRIES` value doesn't match a Mullvad country — try `Netherlands` or `United States`

### katana finds no URLs

- Check `js_crawl: true` — headless crawling requires chromium (included in the image)
- Try lowering `crawl_depth` to `1` for large targets
- Verify the target is reachable: `docker compose run --rm worker curl -s https://example.com`

### waymore is slow or times out

waymore queries Wayback Machine and Common Crawl, which can be slow. The collector uses a 600-second timeout and returns partial results on timeout. This is expected.

### No notifications received

1. Verify `notify-config.yaml` exists and is correctly formatted
2. Test notify manually:
   ```bash
   docker compose run --rm worker sh -c 'echo "test message" | notify -silent'
   ```
3. Check that `notify: true` is set in the target YAML
4. Check that findings exceed the threshold in `config.yaml` (`min_entropy_notify`, `high_value_types`)
5. For progress messages, check that `verbose: true` is set in the target YAML

### Target is skipped by the scheduler

- Check that `enabled: true` is set in the target YAML (`example-target.yaml` ships with `enabled: false`)
- Check that `schedule` is set to a valid cron string — targets with `schedule: ~` are one-shot and never auto-enqueued

### Rescan a target from scratch

```bash
sqlite3 data/findings.db \
  "DELETE FROM js_files WHERE target_id = (SELECT id FROM targets WHERE domain = 'example.com')"
```

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
2. **Fetch** — downloads each JS file with rate limiting and jitter. Deduplicates by SHA-256 content hash so the same file served from multiple URLs is processed only once. Also fetches `.js.map` source maps, which often contain original unminified source with secrets.
3. **Normalize** — beautifies minified JS, decodes `atob()` base64 calls, unescapes hex sequences, and flattens string concatenation. This significantly improves detection quality for obfuscated secrets.
4. **Scan** — runs gitleaks (rule-based, fast) and trufflehog (entropy-based, better for unknown secrets) against the normalized files.
5. **Persist** — findings go into SQLite. Duplicates are deduplicated; `first_seen` / `last_seen` timestamps track when secrets appear and disappear across runs.
6. **Notify** — new findings that exceed the entropy threshold or match a high-value type are sent through `notify`. When `verbose: true`, pipeline progress is also sent at each stage.

Scans are incremental: on repeat runs only new or changed JS files are processed.

---

## Architecture

```
js-analysis/
├── Dockerfile                      multi-stage: Go tools + Python 3.11 + chromium
├── docker-compose.yml              gluetun (Mullvad WireGuard) + worker + scheduler
├── config.yaml                     global settings (delays, thresholds, paths)
├── pipeline.py                     core orchestration logic
├── scheduler.py                    APScheduler-based cron runner
├── main.py                         CLI entry point
├── scripts/
│   └── rotate_key.sh               Mullvad WireGuard key rotation via API
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
│   └── notifier.py                 findings + progress via notify CLI
│
├── db/
│   └── store.py                    SQLite adapter
│
├── jobs/
│   ├── job_manager.py              queue operations
│   └── worker.py                   polling worker loop
│
├── targets/                        one YAML per bug bounty target
│   └── example-target.yaml         template (enabled: false — never executed)
│
└── data/                           created at runtime (gitignored)
    ├── raw_js/                     JS files keyed by SHA-256 hash
    ├── normalized_js/              temporary — deleted after each scan
    ├── tmp/                        waymore output
    └── findings.db                 SQLite database
```

---

## Tools included in the image

| Tool | Version | Purpose |
|------|---------|---------|
| [katana](https://github.com/projectdiscovery/katana) | latest | Active JS crawling |
| [waymore](https://github.com/xnl-h4ck3r/waymore) | latest | Passive historical URL collection |
| [gitleaks](https://github.com/gitleaks/gitleaks) | v8 | Rule-based secret detection |
| [trufflehog](https://github.com/trufflesecurity/trufflehog) | v3 | Entropy-based secret detection |
| [notify](https://github.com/projectdiscovery/notify) | latest | Multi-provider notifications (findings + progress) |
| [gluetun](https://github.com/qdm12/gluetun) | latest | Mullvad WireGuard VPN tunnel |
