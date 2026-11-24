"""Backlogs left out of every report, decided by the release they belong to."""
import re

from ..config import EXCLUDED_RELEASE_TITLES

_PATTERNS = [re.compile(r"\s*" + p, re.IGNORECASE) for p in EXCLUDED_RELEASE_TITLES]


def excluded_release(title: str | None) -> bool:
    return any(p.match(title or "") for p in _PATTERNS)
