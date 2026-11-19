"""The writers a ledger report can take."""
import csv
import json


def write_csv(records, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        out = csv.DictWriter(f, fieldnames=sorted(records[0]))
        out.writeheader()
        out.writerows(records)


def write_jsonl(records, path):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


WRITERS = {"csv": write_csv, "jsonl": write_jsonl}
