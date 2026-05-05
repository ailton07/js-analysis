import sqlite3
from contextlib import contextmanager
from pathlib import Path

_db_path: Path = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS targets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain      TEXT NOT NULL UNIQUE,
                program     TEXT,
                config_path TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS js_files (
                hash        TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                source      TEXT,
                target_id   INTEGER,
                size_bytes  INTEGER,
                fetched_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );

            CREATE TABLE IF NOT EXISTS findings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id   INTEGER,
                file_hash   TEXT,
                url         TEXT,
                detector    TEXT,
                secret_type TEXT,
                value       TEXT,
                entropy     REAL,
                line        INTEGER,
                first_seen  TEXT DEFAULT (datetime('now')),
                last_seen   TEXT DEFAULT (datetime('now')),
                UNIQUE(file_hash, detector, value),
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                target_domain TEXT NOT NULL,
                config_path   TEXT,
                status        TEXT DEFAULT 'pending',
                created_at    TEXT DEFAULT (datetime('now')),
                started_at    TEXT,
                finished_at   TEXT,
                error         TEXT
            );
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Targets

def get_or_create_target(domain: str, program: str, config_path: str) -> int:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO targets (domain, program, config_path) VALUES (?, ?, ?)",
            (domain, program, config_path),
        )
        row = conn.execute(
            "SELECT id FROM targets WHERE domain = ?", (domain,)
        ).fetchone()
        return row["id"]


# JS files

def is_hash_known(file_hash: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM js_files WHERE hash = ?", (file_hash,)
        ).fetchone()
        return row is not None


def save_js_file(
    file_hash: str, url: str, source: str, target_id: int, size_bytes: int
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO js_files (hash, url, source, target_id, size_bytes)
               VALUES (?, ?, ?, ?, ?)""",
            (file_hash, url, source, target_id, size_bytes),
        )


def get_url_for_hash(file_hash: str) -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT url FROM js_files WHERE hash = ?", (file_hash,)
        ).fetchone()
        return row["url"] if row else ""


# Findings

def save_finding(finding: dict) -> bool:
    """Upserts a finding. Returns True if it is new."""
    with _conn() as conn:
        try:
            conn.execute(
                """INSERT INTO findings
                   (target_id, file_hash, url, detector, secret_type, value, entropy, line)
                   VALUES (:target_id, :file_hash, :url, :detector, :secret_type,
                           :value, :entropy, :line)""",
                finding,
            )
            return True
        except sqlite3.IntegrityError:
            conn.execute(
                """UPDATE findings SET last_seen = datetime('now')
                   WHERE file_hash = ? AND detector = ? AND value = ?""",
                (finding["file_hash"], finding["detector"], finding["value"]),
            )
            return False


# Jobs

def enqueue_job(target_domain: str, config_path: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (target_domain, config_path) VALUES (?, ?)",
            (target_domain, config_path),
        )
        return cur.lastrowid


def next_pending_job() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def update_job(job_id: int, status: str, error: str = None) -> None:
    with _conn() as conn:
        if status == "running":
            conn.execute(
                "UPDATE jobs SET status = ?, started_at = datetime('now') WHERE id = ?",
                (status, job_id),
            )
        else:
            conn.execute(
                """UPDATE jobs SET status = ?, finished_at = datetime('now'), error = ?
                   WHERE id = ?""",
                (status, error, job_id),
            )
