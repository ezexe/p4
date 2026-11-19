#!/bin/bash
# Seeds the run's empty workspace with this case's project folder. `claude plugin eval` runs it only with --scaffold.
set -eu
cp -R "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/project/." .
