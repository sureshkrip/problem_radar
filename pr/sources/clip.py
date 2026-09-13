"""Manual capture ("clip") — for sources that cannot be scraped (Upwork, G2, Capterra; spec §2).

There is no `fetch()`: clips arrive one at a time through `POST /clip` (the web app) carrying
`{source_label, url, text, notes}`. `build_draft` turns that into a RawItemDraft that is written
to the `clip` source and then flows through the identical embed → cluster → categorise → score
pipeline as every other raw_item — clipped items are not special-cased downstream.

`external_id` is a content hash of (url + text) so re-clipping the same selection is idempotent
(the raw_item UNIQUE (source_id, external_id) then no-ops).
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from ..models import RawItemDraft


def build_draft(
    *,
    source_label: str,
    url: str | None,
    text: str,
    notes: str | None = None,
    title: str | None = None,
    posted_at: datetime | None = None,
) -> RawItemDraft:
    """Build a RawItemDraft from a manual capture. `text` is the selection / pasted body."""
    body = text.strip()
    digest = hashlib.sha256(f"{url or ''}\n{body}".encode()).hexdigest()[:32]
    return RawItemDraft(
        external_id=digest,
        body=body,
        title=title or (source_label or None),
        url=url or None,
        author=None,
        posted_at=posted_at,
        metrics={
            "source_label": source_label,
            "notes": notes or None,
            "manual": True,
        },
    )
