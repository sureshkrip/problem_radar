"""Source clients: one module per external signal source."""

from __future__ import annotations

from .appstore import AppStoreSource
from .base import Source
from .freelancer import FreelancerSource
from .hn import HackerNewsSource
from .reddit import RedditSource

# Registry of API sources available to `radar ingest`. The 'clip' source is manual (spec §2):
# items arrive through POST /clip, not a fetch(), so it is intentionally not in the registry.
REGISTRY: dict[str, type[Source]] = {
    "hn": HackerNewsSource,
    "reddit": RedditSource,
    "freelancer": FreelancerSource,
    "appstore": AppStoreSource,
}

__all__ = [
    "Source",
    "HackerNewsSource",
    "RedditSource",
    "FreelancerSource",
    "AppStoreSource",
    "REGISTRY",
]
