"""How long each NDP has sat in its current status, and whether that is a problem.

Dates come from the NDP's Jira changelog, so an NDP stuck for three weeks shows
three weeks on the first day this runs, not zero. If Jira cannot be asked, the
date falls back to the first sync that saw the status — honest as a lower bound,
and labelled "observed" so the UI can say "at least".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import (
    NDP_AGE_FLAG_DAYS,
    NDP_AGE_WARN_DAYS,
    NDP_DONE_STATUSES,
    NDP_UNSUBMITTED_STATUSES,
)
from ..models import NdpState
from . import jira_sync


@dataclass
class Age:
    # green / yellow / red while in the deploy pipeline; done once finished;
    # waiting before submission; unknown when no date is held for this status.
    level: str
    days: float | None = None
    since: datetime | None = None
    source: str = ""


def refresh(db: Session, statuses: dict[str, str]) -> dict:
    """Record when each NDP entered its status. `statuses` maps NDP -> status now."""
    keys = [k for k in statuses if k.startswith("NDP-")]
    if not keys:
        return {"jira": 0, "observed": 0, "error": None}

    error = None
    try:
        live = jira_sync.fetch_ndp_status_since(keys)
    except Exception as exc:  # Jira down or PAT expired: keep going on observations
        live, error = {}, f"{type(exc).__name__}: {exc}"

    now = datetime.now()
    counts = {"jira": 0, "observed": 0}
    for key in keys:
        state = db.get(NdpState, key)
        if key in live:
            status, since = live[key]
            source = "jira"
        else:
            status = statuses[key]
            # Same status as last time: it has been in it at least since then.
            keep = state is not None and state.status == status
            since, source = (state.status_since, state.source) if keep else (now, "observed")
        if state is None:
            state = NdpState(ndp=key)
            db.add(state)
        state.status, state.status_since, state.source = status, since, source
        state.checked_at = now
        counts["jira" if source == "jira" else "observed"] += 1
    db.commit()
    return {**counts, "error": error}


def age_of(status: str, state: NdpState | None, now: datetime | None = None) -> Age:
    """Classify one NDP as the tree shows it."""
    status = (status or "").strip()
    if not status:
        return Age("unknown")
    if status in NDP_DONE_STATUSES:
        return Age("done")
    # A date recorded against a different status says nothing about this one.
    if state is None or state.status != status:
        return Age("unknown")

    days = ((now or datetime.now()) - state.status_since).total_seconds() / 86400
    if status in NDP_UNSUBMITTED_STATUSES:
        level = "waiting"
    elif days <= NDP_AGE_WARN_DAYS:
        level = "green"
    elif days <= NDP_AGE_FLAG_DAYS:
        level = "yellow"
    else:
        level = "red"
    return Age(level, round(days, 1), state.status_since, state.source)
