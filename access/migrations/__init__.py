"""Access schema migrations: plain .sql files, applied in filename order.
Every file must be safe to run more than once (IF NOT EXISTS etc.)."""

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent


def run_migrations(db):
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        with db.cursor() as cur:
            cur.execute(path.read_text())
