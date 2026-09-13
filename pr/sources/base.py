"""Source interface.

A Source knows how to fetch candidate items from one external signal source and yield them
as `RawItemDraft`s. Clients accept an injected `httpx.Client` so tests can drive them against
recorded fixtures with no network (spec §13).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime

import httpx

from ..models import RawItemDraft


class Source(ABC):
    #: matches the `source.slug` column and the CLI `--source` value.
    slug: str

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Callers may inject a client (tests, connection reuse). Otherwise each source
        # builds its own with a sane timeout and its required headers.
        self._client = client

    @abstractmethod
    def fetch(self, since: datetime) -> Iterator[RawItemDraft]:
        """Yield candidate items posted at or after `since`.

        Idempotency is the caller's job (upsert on external_id); this only needs to yield.
        """
        raise NotImplementedError
