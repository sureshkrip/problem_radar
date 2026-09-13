"""Lightweight data carriers shared across sources and the pipeline.

These are transport structures, not an ORM. The database is the source of truth; these just
move rows in and out cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawItemDraft:
    """A candidate item produced by a source, before it is written to `raw_item`.

    `external_id` must be stable per source so that re-ingesting is idempotent
    (the DB has UNIQUE (source_id, external_id)).
    """

    external_id: str
    body: str
    title: str | None = None
    url: str | None = None
    author: str | None = None
    posted_at: datetime | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        """Title + body, used for noise filtering and (later) embedding."""
        return f"{self.title or ''}\n{self.body}".strip()
