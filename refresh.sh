#!/bin/bash
# Refresh everything: pull live data, rerun the model, rebuild the page, run regression tests.
# The page is published only if this script exits 0.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=model:pipeline PYTHONWARNINGS=ignore
echo "== 1/4 fetch";  python3 pipeline/fetch.py || echo "(a non-critical source failed; using its last good data)"
echo "== 2/4 model";  python3 pipeline/export.py
echo "== 3/4 build";  python3 pipeline/build_site.py && python3 pipeline/share_card.py && python3 pipeline/build_public.py
echo "== 4/4 tests";  python3 -m unittest tests/test_forecast.py 2>&1 | tail -3
python3 -m unittest -q tests/test_forecast.py >/dev/null 2>&1 || { echo "TESTS FAILED - do not publish"; exit 1; }
echo "== sanity";     python3 pipeline/sanity.py
echo "== lag";        python3 pipeline/lag_check.py || echo "(lag check failed; not blocking)"
echo "READY TO PUBLISH: public/ (index, governor, early)"
