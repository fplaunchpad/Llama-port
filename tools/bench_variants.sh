#!/usr/bin/env bash
# Optimization-wise benchmark: every <language>_<optimization> variant, built and timed
# together in one Linux environment.
#
#   wsl -d Debian -- bash tools/bench_variants.sh     (run from the repo root)
#
# tools/bench_wsl.sh compares the five shipped ports against each other. This one opens
# each port up and compares its optimization levels, so the numbers in OPTIMIZATIONS.md
# can be re-measured rather than taken on trust.
#
# Both OCaml compilers get the full {safe, unsafe} x {plain, unrolled} grid rather than
# a single ladder. Two reasons: -unsafe and the unroll interact (the unrolled kernel has
# four times as many bounds checks to elide), and holding the source fixed across the
# two compilers turns the oxcaml-vs-ocaml rows into a clean flambda2-vs-closure figure.
#
# OxCaml additionally gets two *_pollfree builds, which drop the GC safepoint poll. Those
# are diagnostic, not shippable - see the comment on them below, and tools/bench_polls.sh
# for the full treatment of what a poll actually costs and why.
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
# The full 2x2: {safe, unsafe} x {plain, unrolled}. safe_unroll is not a step on the
# way to anything shipped - it is there so the cost of -unsafe can be read off at BOTH
# unroll levels. Bounds checks and the unroll are not independent: the unrolled kernel
# does four indexed loads per iteration instead of one, so it has four times as many
# checks to pay for, and the two effects have to be measured together to be believed.
MG_UNROLL=0 OCAMLFLAGS="-O3"         OUT="$OUT/oxcaml_safe_plain"     bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_safe_plain" || echo "  oxcaml_safe_plain FAILED"
MG_UNROLL=1 OCAMLFLAGS="-O3"         OUT="$OUT/oxcaml_safe_unroll"    bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_safe_unroll" || echo "  oxcaml_safe_unroll FAILED"
MG_UNROLL=0 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_plain"   bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_plain" || echo "  oxcaml_unsafe_plain FAILED"
MG_UNROLL=1 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_unroll"  bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_unroll (shipped)" || echo "  oxcaml_unsafe_unroll FAILED"

# ---- OxCaml : without GC safepoint polls -------------------------------------
# -disable-poll-insertion drops the back-edge poll that makes a long non-allocating
# loop preemptible. NOT shippable - without it, signals are delayed indefinitely and a
# multicore stop-the-world minor GC would hang - but it prices what the poll costs.
# The answer is not the two instructions it executes (tools/bench_polls.sh NOPs those
# out of the linked binary and gains nothing); it is that a value cannot live in %r11
# across a poll, which in the register-starved unrolled kernel forces a spill.
# Both kernels are built because only the unrolled one is short of registers.
# Stock ocamlopt has no equivalent flag, so there is no ocaml_* counterpart.
MG_UNROLL=0 OCAMLFLAGS="-O3 -unsafe -disable-poll-insertion" \
  OUT="$OUT/oxcaml_unsafe_plain_pollfree"  bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_plain_pollfree" || echo "  oxcaml_unsafe_plain_pollfree FAILED"
MG_UNROLL=1 OCAMLFLAGS="-O3 -unsafe -disable-poll-insertion" \
  OUT="$OUT/oxcaml_unsafe_unroll_pollfree" bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_unroll_pollfree" || echo "  oxcaml_unsafe_unroll_pollfree FAILED"

# ---- OCaml (stock upstream compiler) : the same 2x2 -------------------------
# Same source, closure middle-end instead of flambda2, and no -O3 to pass because the
# flag is flambda-only. Lining the two ladders up side by side shows which of the
# OxCaml numbers come from the language and which come from the compiler.
MG_UNROLL=0 OCAMLFLAGS=""        OUT="$OUT/ocaml_safe_plain"      bash impl/ocaml/build.sh >/dev/null 2>&1 \
  && echo "  ocaml_safe_plain" || echo "  ocaml_safe_plain FAILED"
MG_UNROLL=1 OCAMLFLAGS=""        OUT="$OUT/ocaml_safe_unroll"     bash impl/ocaml/build.sh >/dev/null 2>&1 \
  && echo "  ocaml_safe_unroll" || echo "  ocaml_safe_unroll FAILED"
MG_UNROLL=0 OCAMLFLAGS="-unsafe" OUT="$OUT/ocaml_unsafe_plain"    bash impl/ocaml/build.sh >/dev/null 2>&1 \
  && echo "  ocaml_unsafe_plain" || echo "  ocaml_unsafe_plain FAILED"
MG_UNROLL=1 OCAMLFLAGS="-unsafe" OUT="$OUT/ocaml_unsafe_unroll"   bash impl/ocaml/build.sh >/dev/null 2>&1 \
  && echo "  ocaml_unsafe_unroll  (shipped)" || echo "  ocaml_unsafe_unroll FAILED"

# ---- Both OCaml compilers : the hand strength reduction ---------------------
# Carries the four row offsets as running indices instead of rebuilding base + i per row
# per iteration, because flambda2 does not do that strength reduction itself. Identical
# arithmetic in identical order, so the output hash is unchanged. Built for BOTH compilers
# because it helps one and hurts the other, and that contrast is the result.
MG_SR=1 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_sr" bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_sr" || echo "  oxcaml_unsafe_sr FAILED"
MG_SR=1 OCAMLFLAGS="-unsafe"    OUT="$OUT/ocaml_unsafe_sr"  bash impl/ocaml/build.sh  >/dev/null 2>&1 \
  && echo "  ocaml_unsafe_sr" || echo "  ocaml_unsafe_sr FAILED"
# and strength reduction stacked with poll removal, which are independent causes
MG_SR=1 OCAMLFLAGS="-O3 -unsafe -disable-poll-insertion" \
  OUT="$OUT/oxcaml_unsafe_sr_pollfree" bash impl/oxcaml/build.sh >/dev/null 2>&1 \
  && echo "  oxcaml_unsafe_sr_pollfree" || echo "  oxcaml_unsafe_sr_pollfree FAILED"

echo "  python       (one variant; its only change was a correctness fix)"
echo

# name|command   (order sets the report order)
VARIANTS=()
for v in cpp_O2_plain cpp_plain cpp_unroll rust_plain rust_unroll \
         oxcaml_safe_plain oxcaml_safe_unroll oxcaml_unsafe_plain oxcaml_unsafe_unroll \
         oxcaml_unsafe_plain_pollfree oxcaml_unsafe_unroll_pollfree \
         oxcaml_unsafe_sr oxcaml_unsafe_sr_pollfree \
         ocaml_safe_plain ocaml_safe_unroll ocaml_unsafe_plain ocaml_unsafe_unroll \
         ocaml_unsafe_sr; do
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

W = max([len(k) for k in res] + [len("total")])

def paired(prev, cur):
    """median paired % change and how many rounds it won, or None if either is absent."""
    if prev not in res or cur not in res:
        return None
    pd = [(a - b) / b * 100 for a, b in zip(res[cur], res[prev])]
    return statistics.median(pd), sum(1 for x in pd if x > 0), len(pd)

# per-language optimization ladders, each step against the one before it
LADDERS = [
    ("C++",                    ["cpp_O2_plain", "cpp_plain", "cpp_unroll"]),
    ("Rust",                   ["rust_plain", "rust_unroll"]),
    ("OxCaml (flambda2)",      ["oxcaml_safe_plain", "oxcaml_unsafe_plain",
                                "oxcaml_unsafe_unroll"]),
    ("OCaml (stock, closure)", ["ocaml_safe_plain", "ocaml_unsafe_plain",
                                "ocaml_unsafe_unroll"]),
]
print("\neach optimization against the step before it (paired, same rounds):")
for lang, chain in LADDERS:
    chain = [c for c in chain if c in res]
    if len(chain) < 2:
        continue
    print(f"\n  {lang}")
    for prev, cur in zip(chain, chain[1:]):
        m, w, n = paired(prev, cur)
        print(f"    {prev:{W}s} -> {cur:{W}s} {m:+7.1f}%   faster in {w}/{n} rounds")
    tot = (med[chain[-1]] / med[chain[0]] - 1) * 100
    print(f"    {'total':{W}s}    {chain[0]} -> {chain[-1]}: {tot:+.1f}%")

# A ladder can only show one path through a 2x2, so the two OCaml grids get read off
# directly as well. The bounds-check rows are the ones that need both unroll levels:
# the unrolled kernel issues four indexed loads per iteration where the plain one
# issues one, so it has four times the checks to pay for and the cost of -unsafe is
# not the same number in the two columns.
EFFECTS = [
    ("cost of keeping bounds checks (no -unsafe)", [
        ("OxCaml, plain kernel",    "oxcaml_unsafe_plain",   "oxcaml_safe_plain"),
        ("OxCaml, unrolled kernel", "oxcaml_unsafe_unroll",  "oxcaml_safe_unroll"),
        ("OCaml,  plain kernel",    "ocaml_unsafe_plain",    "ocaml_safe_plain"),
        ("OCaml,  unrolled kernel", "ocaml_unsafe_unroll",   "ocaml_safe_unroll"),
    ]),
    ("value of the 4-way unroll, at each safety level", [
        ("OxCaml, -unsafe",         "oxcaml_unsafe_plain",   "oxcaml_unsafe_unroll"),
        ("OxCaml, bounds-checked",  "oxcaml_safe_plain",     "oxcaml_safe_unroll"),
        ("OCaml,  -unsafe",         "ocaml_unsafe_plain",    "ocaml_unsafe_unroll"),
        ("OCaml,  bounds-checked",  "ocaml_safe_plain",      "ocaml_safe_unroll"),
    ]),
    ("cost of the GC safepoint poll (OxCaml only - stock ocamlopt has no such flag)", [
        ("OxCaml, plain kernel",    "oxcaml_unsafe_plain",   "oxcaml_unsafe_plain_pollfree"),
        ("OxCaml, unrolled kernel", "oxcaml_unsafe_unroll",  "oxcaml_unsafe_unroll_pollfree"),
    ]),
    ("hand strength reduction of base + i (flambda2 will not do it)", [
        ("OxCaml",                  "oxcaml_unsafe_unroll",  "oxcaml_unsafe_sr"),
        ("OCaml (stock)",           "ocaml_unsafe_unroll",   "ocaml_unsafe_sr"),
        ("OxCaml, on top of it, polls removed too",
                                    "oxcaml_unsafe_sr",      "oxcaml_unsafe_sr_pollfree"),
        ("OxCaml, both together vs shipped",
                                    "oxcaml_unsafe_unroll",  "oxcaml_unsafe_sr_pollfree"),
    ]),
    ("flambda2 over the stock closure middle-end, same source", [
        ("plain, bounds-checked",   "ocaml_safe_plain",      "oxcaml_safe_plain"),
        ("unrolled, bounds-checked","ocaml_safe_unroll",     "oxcaml_safe_unroll"),
        ("plain, -unsafe",          "ocaml_unsafe_plain",    "oxcaml_unsafe_plain"),
        ("shipped vs shipped",      "ocaml_unsafe_unroll",   "oxcaml_unsafe_unroll"),
    ]),
]
LW = max(len(lbl) for _, rows in EFFECTS for lbl, _, _ in rows)
for title, rows in EFFECTS:
    shown = [(lbl, paired(b, t)) for lbl, b, t in rows]
    shown = [(lbl, r) for lbl, r in shown if r]
    if not shown:
        continue
    print(f"\n  {title}:")
    for lbl, (m, w, n) in shown:
        print(f"    {lbl:{LW}s} {m:+7.1f}%   faster in {w}/{n} rounds")
PY
  echo
done
