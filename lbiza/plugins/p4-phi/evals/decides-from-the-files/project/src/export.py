"""Writes the month's ledger report for the accounts team."""
import os

from formats import WRITERS


def write_report(records, path):
    WRITERS[os.environ["LEDGER_REPORT_FORMAT"]](records, path)
