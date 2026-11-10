#!/usr/bin/env bash
# Run the test suite and commit only if it passes.
set -e
python -m pytest -q 2>&1 | tail -3
python -m pytest -q > /dev/null
git add -A
git commit -m "$1"
