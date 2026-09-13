from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pr.cli import parse_since


def test_parse_since_units():
    now = datetime.now(UTC)
    assert (now - parse_since("2d")) - timedelta(days=2) < timedelta(seconds=5)
    assert (now - parse_since("12h")) - timedelta(hours=12) < timedelta(seconds=5)
    assert (now - parse_since("30m")) - timedelta(minutes=30) < timedelta(seconds=5)
    assert (now - parse_since("1w")) - timedelta(weeks=1) < timedelta(seconds=5)


def test_parse_since_rejects_garbage():
    import typer

    with pytest.raises(typer.BadParameter):
        parse_since("soon")
