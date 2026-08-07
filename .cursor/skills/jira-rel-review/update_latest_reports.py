#!/usr/bin/env python3
"""
Generate or update the three fixed quarter reports under Report/AR_GL, Report/AR,
and Report/GL.  Updates existing workbooks in place and preserves user-filled
columns (Developer, UAT ETA, PROD ETA, Comments).

Usage:
  py jira-rel-review/update_latest_reports.py
  py jira-rel-review/update_latest_reports.py --quarter 2026Q3
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from export_regions import (  # noqa: E402
    build_report_workbook,
    load_config,
    report_output_path,
    save_report_workbook,
)

REPORT_SPECS = [
    ("AR_GL", ["TDS-AR", "TDS-GL", "TDS-AR+GL"]),
    ("AR", ["TDS-AR"]),
    ("GL", ["TDS-GL"]),
]


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Update latest AR/GL quarter reports in place.")
    parser.add_argument("--quarter", default=cfg.get("default_quarter", "2026Q3"))
    args = parser.parse_args()

    results = []
    for kind, domain_labels in REPORT_SPECS:
        out_path = report_output_path(kind, args.quarter)
        print(f"\n=== {kind} -> {out_path} ===", file=sys.stderr)
        combo_data, summary_rows = build_report_workbook(args.quarter, domain_labels=domain_labels)
        updated_at = datetime.now()
        save_report_workbook(combo_data, out_path, summary_rows, updated_at, args.quarter,
                             include_tree=True)
        results.append((kind, out_path, len(summary_rows), updated_at))

    print("\n--- Done ---")
    for kind, path, n_sheets, ts in results:
        print(f"  {kind}: {path}  ({n_sheets} combo sheet(s), updated {ts.strftime('%m/%d/%Y %I:%M:%S %p')})")


if __name__ == "__main__":
    main()
