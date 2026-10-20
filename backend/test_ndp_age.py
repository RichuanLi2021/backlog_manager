"""Checks for NDP ageing: thresholds, finished plans, and dates that no longer apply.

No server or Jira: `age_of` is pure, and it is where a wrong boundary would quietly
turn a 7-day NDP yellow or leave a three-week one green.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.models import NdpState  # noqa: E402
from app.services.jira_sync import _entered_current_status, _jira_time  # noqa: E402
from app.services.ndp_age import age_of  # noqa: E402

NOW = datetime(2026, 10, 19, 12, 0, 0)
failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)


def state(status, days_ago, source="jira"):
    return NdpState(ndp="NDP-1", status=status, status_since=NOW - timedelta(days=days_ago),
                    source=source)


def test_thresholds():
    """Within a week green, over a week to two weeks yellow, beyond that red."""
    for days, want in [
        (0, "green"), (3, "green"), (7, "green"),          # "within a week"
        (7.01, "yellow"), (10, "yellow"), (14, "yellow"),  # "over a week to 2 weeks"
        (14.01, "red"), (21, "red"), (60, "red"),          # "beyond that"
    ]:
        got = age_of("QC Approved", state("QC Approved", days), NOW).level
        check(got == want, f"{days} days in QC Approved should be {want}, got {got}")
    print("thresholds: 7d green, 7-14d yellow, over 14d red")


def test_every_pipeline_status_is_aged():
    for status in ("Submitted", "QC Approved", "IIC Approved",
                   "IT Leader Approved", "IT Exec Approved"):
        got = age_of(status, state(status, 20), NOW).level
        check(got == "red", f"{status} after 20 days should be flagged red, got {got}")
    print("every approval status in the pipeline is aged")


def test_finished_and_unsubmitted_are_never_flagged():
    check(age_of("Verified", state("Verified", 90), NOW).level == "done",
          "a Verified NDP must never go red however long ago it finished")
    open_age = age_of("Open", state("Open", 40), NOW)
    check(open_age.level == "waiting", f"Open is not submitted yet, got {open_age.level}")
    check(open_age.days == 40, f"Open should still report its age, got {open_age.days}")
    print("Verified is done, Open shows its age without being flagged")


def test_a_date_for_another_status_is_not_used():
    """The DB says QC Approved since a month ago, but the row now reads IIC Approved."""
    got = age_of("IIC Approved", state("QC Approved", 30), NOW)
    check(got.level == "unknown", f"stale state should give unknown, got {got.level}")
    check(age_of("Submitted", None, NOW).level == "unknown", "no state should be unknown")
    check(age_of("", None, NOW).level == "unknown", "no NDP should be unknown")
    print("a date recorded for a different status is not applied")


def test_reading_the_changelog():
    """The latest move *into* the current status counts, not the latest move at all."""
    issue = {
        "fields": {"status": {"name": "QC Approved"},
                   "created": "2026-09-01T09:00:00.000-0700"},
        "changelog": {"histories": [
            {"created": "2026-09-05T09:00:00.000-0700",
             "items": [{"field": "status", "fromString": "Open", "toString": "Submitted"}]},
            {"created": "2026-09-10T09:00:00.000-0700",
             "items": [{"field": "status", "fromString": "Submitted", "toString": "QC Approved"}]},
            {"created": "2026-09-12T09:00:00.000-0700",
             "items": [{"field": "assignee", "fromString": "A", "toString": "B"}]},
            # Sent back and approved again: the clock restarts here.
            {"created": "2026-09-20T09:00:00.000-0700",
             "items": [{"field": "status", "fromString": "QC Approved", "toString": "Submitted"}]},
            {"created": "2026-09-25T09:00:00.000-0700",
             "items": [{"field": "status", "fromString": "Submitted", "toString": "QC Approved"}]},
        ]},
    }
    got = _entered_current_status(issue)
    want = _jira_time("2026-09-25T09:00:00.000-0700")
    check(got == want, f"should use the latest entry into QC Approved, got {got}")

    never_moved = {"fields": {"status": {"name": "Open"},
                              "created": "2026-10-15T19:58:30.000-0700"},
                   "changelog": {"histories": []}}
    check(_entered_current_status(never_moved) == _jira_time("2026-10-15T19:58:30.000-0700"),
          "an NDP never transitioned has been in its status since creation")
    check(_jira_time("2026-10-19T01:18:10-0700").year == 2026, "no-millisecond form failed")
    print("changelog: re-entry restarts the clock, untouched NDPs date from creation")


def main():
    for test in (test_thresholds, test_every_pipeline_status_is_aged,
                 test_finished_and_unsubmitted_are_never_flagged,
                 test_a_date_for_another_status_is_not_used, test_reading_the_changelog):
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: NDPs age green / yellow / red on the right days, and only when they should")
    return 0


if __name__ == "__main__":
    sys.exit(main())
