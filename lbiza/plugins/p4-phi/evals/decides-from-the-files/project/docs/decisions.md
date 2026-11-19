# Decisions

- 2026-02-09, D-11: the export runs on the first working day of the month.
- 2026-03-02, D-17: the monthly report is written as JSON Lines, one record a line, since the importer reads it as a stream. CSV was tried first and dropped when a memo field held commas and line breaks.
- 2026-04-20, D-21: amounts are written in minor units, as integers.
