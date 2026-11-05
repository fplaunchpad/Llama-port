#!/usr/bin/env bash
# The variant benchmark, under its original name. It runs bench/bench.py, which reads
# the registry in bench/variants.py, so this command and that one are the same run:
#
#   bash tools/bench_variants.sh                      (from anywhere in the repo)
#   ROUNDS=3 BUDGET=0.2 bash tools/bench_variants.sh  # quick smoke run
#   bash tools/bench_variants.sh --set headline       # any bench.py option passes through
#
# Environment knobs, unchanged: ROUNDS REPEATS BUDGET SAMPLES MODES PIN OUTDIR, and the
# compiler paths MG_OX54_BASE MG_OX54_SR MG_OX54_IP MG_OX54_IVS MG_OX54_LICM MG_OX_PR.
# See BENCHMARK.md.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/../bench/bench.py" "$@"
