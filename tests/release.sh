#!/bin/sh
# Runs before every release: the full test suite with warnings as errors, and one version string.
set -e
cd "$(dirname "$0")/.."
python3 -X dev -W error -m unittest discover -s . -p 'test_*.py'
v=$(python3 -c 'import loud_fail; print(loud_fail.__version__)')
grep -q "^## $v " CHANGELOG.md || { echo "CHANGELOG.md has no $v section"; exit 1; }
echo "release checks passed for $v"
