"""Database access. Thin wrapper over psycopg 3.

Connections use dict rows so callers get column-name access. `init_db` applies the SQL
migrations in order and seeds the source rows.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import SQL_DIR, get_settings
from .models import RawItemDraft

# Sources seeded by init-db. kind: 'api' pulls automatically, 'manual' arrives via /clip.
SEED_SOURCES = [
    ("hn", "api"),
    ("reddit", "api"),
    ("freelancer", "api"),
    ("appstore", "api"),
    ("clip", "manual"),
]


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Yield a connection with dict rows. Commits on clean exit, rolls back on exception."""
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        yield conn


def init_db() -> None:
    """Apply schema + seed migrations, then upsert the known sources. Idempotent."""
    migrations = sorted(SQL_DIR.glob("*.sql"))
    with connect() as conn:
        for path in migrations:
            sql = path.read_text(encoding="utf-8")
            conn.execute(sql)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO source (slug, kind) VALUES (%s, %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                SEED_SOURCES,
            )
        conn.commit()


def source_id(conn: psycopg.Connection, slug: str) -> int:
    row = conn.execute("SELECT id FROM source WHERE slug = %s", (slug,)).fetchone()
    if row is None:
        raise KeyError(f"unknown source slug: {slug!r} (did you run `radar init-db`?)")
    return row["id"]


def insert_raw_item(conn: psycopg.Connection, source_id: int, draft: RawItemDraft) -> int | None:
    """Upsert one draft into raw_item. Returns the new id, or None if it already existed.

    Idempotent via UNIQUE (source_id, external_id) + ON CONFLICT DO NOTHING (spec §5). Shared
    by `radar ingest` and the manual /clip endpoint so clipped items flow through the identical
    downstream pipeline (embed → cluster → categorise → score).
    """
    row = conn.execute(
        """
        INSERT INTO raw_item
            (source_id, external_id, url, author, posted_at, title, body, metrics)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, external_id) DO NOTHING
        RETURNING id
        """,
        (
            source_id,
            draft.external_id,
            draft.url,
            draft.author,
            draft.posted_at,
            draft.title,
            draft.body,
            Json(draft.metrics),
        ),
    ).fetchone()
    return row["id"] if row else None
