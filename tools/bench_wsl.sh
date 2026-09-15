#!/usr/bin/env bash
# Uniform benchmark: every implementation built and timed INSIDE one Linux environment.
#
#   wsl -d Debian -- bash tools/bench_wsl.sh     (run from the repo root;
#   wsl.exe inherits the Windows working directory, so no absolute path is needed)
#
# Why this exists: the OxCaml port targets linux-x86_64 and cannot run natively on
# Windows. Correctness is platform-independent - the same C++ source under g++ 15.2 /
# Windows UCRT and g++ 14.2 / Linux glibc produces bit-identical output - but SPEED is
# not. Comparing a Windows-native binary against a WSL one measures the OS and libm, not
# the language. So all five are built here, with matched flags, and timed together.
#
# Two of the five are the same OCaml source under different compilers - `oxcaml`
# (flambda2) and `ocaml` (stock upstream, closure middle-end). Having both in one
# interleaved run is the only way the middle-end gap is measured rather than guessed.
#
# Pinning uses taskset rather than each program pinning itself, so every implementation
# gets identical treatment regardless of what its language can express.
#
# Env knobs: PIN (default 0, -1 disables), ROUNDS, REPEATS, BUDGET, SAMPLES, MODES.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT=/tmp/mg
mkdir -p "$OUT"
source "$HOME/.cargo/env" 2>/dev/null || true

PIN="${PIN:-0}"
ROUNDS="${ROUNDS:-9}"
REPEATS="${REPEATS:-3}"
BUDGET="${BUDGET:-0.3}"
SAMPLES="${SAMPLES:-200}"
MODES="${MODES:-gen ppl}"

if [ "$PIN" = "-1" ]; then TASKSET=(); else TASKSET=(taskset -c "$PIN"); fi

echo "=== building (all in this environment, matched optimization levels) ==="
g++ -O3 -std=c++20 -fno-fast-math -ffp-contract=off -o "$OUT/cpp" impl/cpp/infer.cpp \
  && echo "  cpp     $(g++ --version | head -1)" || echo "  cpp     BUILD FAILED"

if bash impl/oxcaml/build.sh >/dev/null 2>&1; then
  echo "  oxcaml  ocamlopt $(eval "$(opam env --switch=5.2.0+ox 2>/dev/null)"; ocamlopt -version) -O3 -unsafe  (flambda2)"
else
  echo "  oxcaml  BUILD FAILED"
fi

# Same source as oxcaml, stock upstream compiler. build.sh refuses to run against a
# flambda2 ocamlopt, so this row cannot silently become a second OxCaml build.
if bash impl/ocaml/build.sh >/dev/null 2>&1; then
  echo "  ocaml   ocamlopt $(ocamlopt -version 2>/dev/null) -unsafe  (closure)"
else
  echo "  ocaml   BUILD FAILED (no stock ocamlopt? set MG_OCAML_SWITCH)"
fi

# Build Rust into a Linux-only target dir: impl/rust/target holds the Windows build,
# and sharing it would make the two toolchains fight over the same artifacts.
RUST_BIN=""
if command -v cargo >/dev/null 2>&1; then
  if CARGO_TARGET_DIR="$OUT/rust-target" cargo build --release \
       --manifest-path impl/rust/Cargo.toml >/dev/null 2>&1; then
    RUST_BIN="$OUT/rust-target/release/microgpt_infer"
    echo "  rust    $(rustc --version)"
  else
    echo "  rust    BUILD FAILED"
  fi
else
  echo "  rust    SKIPPED (no cargo here; install rustup to include it)"
fi
echo "  python  $(python3 --version)"
echo

IMPLS=()
[ -x "$OUT/cpp" ] && IMPLS+=("cpp|$OUT/cpp")
[ -n "$RUST_BIN" ] && [ -x "$RUST_BIN" ] && IMPLS+=("rust|$RUST_BIN")
[ -x impl/oxcaml/build/microgpt_infer ] && IMPLS+=("oxcaml|$ROOT/impl/oxcaml/build/microgpt_infer")
[ -x impl/ocaml/build/microgpt_infer ] && IMPLS+=("ocaml|$ROOT/impl/ocaml/build/microgpt_infer")
IMPLS+=("python|python3 $ROOT/impl/python/infer.py")

COMMON=(--weights "$ROOT/weights/microgpt.bin" --data "$ROOT/data/val.txt"
        --samples "$SAMPLES" --seed 1234 --temperature 0.5 --pin -1)

echo "=== correctness (must be identical across all) ==="
: > "$OUT/hashes.txt"
for entry in "${IMPLS[@]}"; do
  name="${entry%%|*}"; cmd="${entry#*|}"
  # shellcheck disable=SC2086
  $cmd "${COMMON[@]}" --mode all --repeats 1 --time-budget 0.05 2>/dev/null > "$OUT/$name.json"
  python3 - "$name" "$OUT/$name.json" "$OUT/hashes.txt" <<'PY'
import json, sys
name, path, hp = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    r = json.load(open(path))
except Exception as e:
    print(f"  {name:8s} FAILED to produce JSON ({e})"); raise SystemExit
g, p, c = r["gen"], r["ppl"], r["check"]
print(f"  {name:8s} ppl={p['perplexity']!r}  hash={g['output_fnv1a64']}  ws={c['weights_sum']!r}")
open(hp, "a").write(f"{name} {g['output_fnv1a64']} {p['perplexity']!r}\n")
PY
done
python3 - "$OUT/hashes.txt" <<'PY'
import sys
rows = [l.split() for l in open(sys.argv[1])]
print("\n  " + ("ALL IDENTICAL" if len({r[1] for r in rows}) == 1 and len({r[2] for r in rows}) == 1
                else "*** MISMATCH - do not trust the timings below ***"))
PY
echo

for MODE in $MODES; do
  echo "=== $MODE: $ROUNDS interleaved rounds, taskset cpu $PIN, budget ${BUDGET}s ==="
  : > "$OUT/t_$MODE.txt"
  for ((r=0; r<ROUNDS; r++)); do
    for entry in "${IMPLS[@]}"; do
      name="${entry%%|*}"; cmd="${entry#*|}"
      # shellcheck disable=SC2086
      tps=$("${TASKSET[@]}" $cmd "${COMMON[@]}" --mode "$MODE" --repeats "$REPEATS" \
              --time-budget "$BUDGET" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin)['$MODE']['tokens_per_sec_best'])")
      echo "$name $tps" >> "$OUT/t_$MODE.txt"
    done
  done
  python3 - "$OUT/t_$MODE.txt" <<'PY'
import statistics, sys
from collections import defaultdict
res = defaultdict(list)
for line in open(sys.argv[1]):
    k, v = line.split(); res[k].append(float(v))
order = sorted(res, key=lambda k: -statistics.median(res[k]))
slow = min(statistics.median(v) for v in res.values())
fast = statistics.median(res[order[0]])
print("| impl | tok/s (median) | best | sd | vs python | vs fastest |")
print("|---|---:|---:|---:|---:|---:|")
for k in order:
    v = res[k]; med = statistics.median(v)
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    print(f"| {k} | {med:,.0f} | {max(v):,.0f} | {sd:,.0f} | {med/slow:.1f}x | {med/fast*100:.0f}% |")
comp = [k for k in order if k != "python"]
if len(comp) > 1:
    ref = comp[0]
    print(f"\npaired against {ref}:")
    for k in comp[1:]:
        pd = [(a-b)/b*100 for a, b in zip(res[k], res[ref])]
        w = sum(1 for x in pd if x > 0)
        print(f"  {k:8s} median {statistics.median(pd):+6.1f}%   faster in {w}/{len(pd)} rounds")
PY
  echo
done
