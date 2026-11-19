# Runbook

The export runs from the scheduler on the first working day of the month.
A failed run is started again by hand with `python src/export.py`.
The accounts team is told in the team channel once the report is in the shared folder.
