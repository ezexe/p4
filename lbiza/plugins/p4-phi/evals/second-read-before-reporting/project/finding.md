# Finding: why the export of 2026-11-02 failed

The export failed because the disk was full.
`logs/export.log` shows the write error at 02:14, and `src/export.py` checks no free space before it writes.
