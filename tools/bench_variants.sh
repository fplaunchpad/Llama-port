#!/usr/bin/env bash
# Optimization-wise benchmark: every <language>_<optimization> variant, built and timed
# together in one Linux environment.
#
#   wsl -d Debian -- bash tools/bench_variants.sh     (run from the repo root)
#
# tools/bench_wsl.sh compares the four shipped ports against each other. This one opens
# each port up and compares its optimization levels, so the numbers in OPTIMIZATIONS.md
# can be re-measured rather than taken on trust.
#
# Every variant must produce byte-identical output. A variant that does not is a bug,
# and the script says so instead of quietly ranking it.
#
# Env knobs: PIN (default 0, -1 disables), ROUNDS, REPEATS, BUDGET, SAMPLES, MODES.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT=/tmp/mgv
rm -rf "$OUT" && mkdir -p "$OUT"
source "$HOME/.cargo/env" 2>/dev/null || true

PIN="${PIN:-0}"
ROUNDS="${ROUNDS:-9}"
REPEATS="${REPEATS:-3}"
BUDGET="${BUDGET:-0.3}"
SAMPLES="${SAMPLES:-200}"
MODES="${MODES:-gen}"
if [ "$PIN" = "-1" ]; then TASKSET=(); else TASKSET=(taskset -c "$PIN"); fi

CXXFLAGS_COMMON="-std=c++20 -fno-fast-math -ffp-contract=off"

echo "=== building variants ==="

# ---- C++ : optimization level, and the 4-way unroll -------------------------
g++ -O2 $CXXFLAGS_COMMON -DMG_UNROLL=0 -o "$OUT/cpp_O2_plain"  impl/cpp/infer.cpp 2>/dev/null \
  && echo "  cpp_O2_plain" || echo "  cpp_O2_plain FAILED"
g++ -O3 $CXXFLAGS_COMMON -DMG_UNROLL=0 -o "$OUT/cpp_plain"     impl/cpp/infer.cpp 2>/dev/null \
  && echo "  cpp_plain" || echo "  cpp_plain FAILED"
g++ -O3 $CXXFLAGS_COMMON                -o "$OUT/cpp_unroll"   impl/cpp/infer.cpp 2>/dev/null \
  && echo "  cpp_unroll   (shipped)" || echo "  cpp_unroll FAILED"

# ---- Rust : the unroll feature ---------------------------------------------
if command -v cargo >/dev/null 2>&1; then
  CARGO_TARGET_DIR="$OUT/rs_plain" cargo build --release --no-default-features \
      --manifest-path impl/rust/Cargo.toml >/dev/null 2>&1 \
    && cp "$OUT/rs_plain/release/microgpt_infer" "$OUT/rust_plain" && echo "  rust_plain" \
    || echo "  rust_plain FAILED"
  CARGO_TARGET_DIR="$OUT/rs_unroll" cargo build --release \
      --manifest-path impl/rust/Cargo.toml >/dev/null 2>&1 \
    && cp "$OUT/rs_unroll/release/microgpt_infer" "$OUT/rust_unroll" && echo "  rust_unroll  (shipped)" \
    || echo "  rust_unroll FAILED"
else
  echo "  rust SKIPPED (no cargo here)"
fi

# ---- OxCaml : bounds checks, and the 4-way unroll ---------------------------
MG_UNROLL=0 OCAMLFLAGS="-O3"         OUT="$OUT/oxcaml_safe_plain"     bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_safe_plain" || echo "  oxcaml_safe_plain FAILED"
MG_UNROLL=0 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_plain"   bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_plain" || echo "  oxcaml_unsafe_plain FAILED"
MG_UNROLL=1 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_unroll"  bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_unroll (shipped)" || echo "  oxcaml_unsafe_unroll FAILED"

echo "  python       (one variant; its only change was a correctness fix)"
echo

# name|command   (order sets the report order)
VARIANTS=()
for v in cpp_O2_plain cpp_plain cpp_unroll rust_plain rust_unroll \
         oxcaml_safe_plain oxcaml_unsafe_plain oxcaml_unsafe_unroll; do
  [ -x "$OUT/$v" ] && VARIANTS+=("$v|$OUT/$v")
done
VARIANTS+=("python|python3 $ROOT/impl/python/infer.py")

COMMON=(--weights "$ROOT/weights/microgpt.bin" --data "$ROOT/data/val.txt"
        --samples "$SAMPLES" --seed 1234 --temperature 0.5 --pin -1)

echo "=== correctness: every variant must produce identical output ==="
: > "$OUT/hashes.txt"
for e in "${VARIANTS[@]}"; do
  n="${e%%|*}"; c="${e#*|}"
  # shellcheck disable=SC2086
  $c "${COMMON[@]}" --mode all --repeats 1 --time-budget 0.05 2>/dev/null > "$OUT/$n.json"
  python3 - "$n" "$OUT/$n.json" "$OUT/hashes.txt" <<'PY'
import json, sys
name, path, hp = sys.argv[1:4]
try:
    r = json.load(open(path))
except Exception as e:
    print(f"  {name:22s} FAILED to produce JSON ({e})"); raise SystemExit
g, p = r["gen"], r["ppl"]
open(hp, "a").write(f"{name} {g['output_fnv1a64']} {p['perplexity']!r}\n")
PY
done
python3 - "$OUT/hashes.txt" <<'PY'
import sys
rows = [l.split() for l in open(sys.argv[1])]
hs, ps = {r[1] for r in rows}, {r[2] for r in rows}
for r in rows:
    print(f"  {r[0]:22s} {r[1]}  ppl={r[2]}")
print("\n  " + ("ALL IDENTICAL - differences below are real work saved"
                if len(hs) == 1 and len(ps) == 1 else
                "*** VARIANTS DISAGREE - do not rank these ***"))
PY
echo

for MODE in $MODES; do
  echo "=== $MODE: $ROUNDS interleaved rounds, taskset cpu $PIN, budget ${BUDGET}s ==="
  : > "$OUT/t_$MODE.txt"
  for ((r=0; r<ROUNDS; r++)); do
    for e in "${VARIANTS[@]}"; do
      n="${e%%|*}"; c="${e#*|}"
      # shellcheck disable=SC2086
      tps=$("${TASKSET[@]}" $c "${COMMON[@]}" --mode "$MODE" --repeats "$REPEATS" \
              --time-budget "$BUDGET" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin)['$MODE']['tokens_per_sec_best'])")
      echo "$n $tps" >> "$OUT/t_$MODE.txt"
    done
  done

  python3 - "$OUT/t_$MODE.txt" <<'PY'
import statistics, sys
from collections import defaultdict, OrderedDict
res = OrderedDict()
for line in open(sys.argv[1]):
    k, v = line.split()
    res.setdefault(k, []).append(float(v))

med = {k: statistics.median(v) for k, v in res.items()}
slowest = min(med.values())
fastest = max(med.values())

print("| variant | tok/s (median) | best | sd | vs python | vs fastest |")
print("|---|---:|---:|---:|---:|---:|")
for k, v in res.items():
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    print(f"| {k} | {med[k]:,.0f} | {max(v):,.0f} | {sd:,.0f} | "
          f"{med[k]/slowest:.1f}x | {med[k]/fastest*100:.0f}% |")

# per-language optimization ladders, each step against the one before it
LADDERS = [
    ("C++",    ["cpp_O2_plain", "cpp_plain", "cpp_unroll"]),
    ("Rust",   ["rust_plain", "rust_unroll"]),
    ("OxCaml", ["oxcaml_safe_plain", "oxcaml_unsafe_plain", "oxcaml_unsafe_unroll"]),
]
print("\neach optimization against the step before it (paired, same rounds):")
for lang, chain in LADDERS:
    chain = [c for c in chain if c in res]
    if len(chain) < 2:
        continue
    print(f"\n  {lang}")
    for prev, cur in zip(chain, chain[1:]):
        pd = [(a - b) / b * 100 for a, b in zip(res[cur], res[prev])]
        w = sum(1 for x in pd if x > 0)
        print(f"    {prev:22s} -> {cur:22s} {statistics.median(pd):+7.1f}%   "
              f"faster in {w}/{len(pd)} rounds")
    tot = (med[chain[-1]] / med[chain[0]] - 1) * 100
    print(f"    {'total':22s}    {chain[0]} -> {chain[-1]}: {tot:+.1f}%")
PY
  echo
done
