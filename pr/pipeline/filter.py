"""Noise filtering.

"Filtering matters more than fetching" (spec §5). Drop job ads, self-promo, recruiter spam
and memes before they reach the embed/cluster stages. This is a cheap keyword heuristic — not
an LLM — run at ingest time. It errs toward keeping items; the triage cap handles volume.
"""

from __future__ import annotations

import re

from ..models import RawItemDraft

MIN_BODY_CHARS = 30

# Substrings that mark an item as noise. Matched case-insensitively against title+body.
_NOISE_SUBSTRINGS = [
    # hiring / recruiter spam
    "[hiring]",
    "[for hire]",
    "we're hiring",
    "we are hiring",
    "now hiring",
    "job opening",
    "apply now",
    "send your resume",
    "send your cv",
    "salary range",
    # self-promo / launches
    "show hn",
    "i built",
    "i made",
    "i've built",
    "i just launched",
    "check out my",
    "check out our",
    "my new app",
    "my startup",
    "sign up now",
    "use my referral",
    "discount code",
    "affiliate",
    # low-signal / memes
    "meme",
    "just for fun",
    "upvote if",
]

# Word-boundary patterns for short tokens that would false-match as substrings.
_NOISE_PATTERNS = [
    re.compile(r"\bhiring\b", re.IGNORECASE),
    re.compile(r"\bgiveaway\b", re.IGNORECASE),
]


def is_noise(draft: RawItemDraft) -> bool:
    text = draft.searchable_text()
    if len(text) < MIN_BODY_CHARS:
        return True
    lowered = text.lower()
    if any(sub in lowered for sub in _NOISE_SUBSTRINGS):
        return True
    if any(p.search(text) for p in _NOISE_PATTERNS):
        return True
    return False


def keep(drafts: list[RawItemDraft]) -> list[RawItemDraft]:
    """Return only the drafts that survive the noise filter."""
    return [d for d in drafts if not is_noise(d)]
