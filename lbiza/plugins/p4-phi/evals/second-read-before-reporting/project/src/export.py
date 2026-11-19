"""Writes the month's ledger report for the accounts team."""
import json


def write_report(records, path="ledger-report.jsonl"):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
