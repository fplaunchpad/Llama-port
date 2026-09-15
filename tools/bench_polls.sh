#!/usr/bin/env bash
# What do OCaml's GC safepoint polls cost this program?
#
#   wsl -d Debian -- bash tools/bench_polls.sh     (run from the repo root)
#
# Each OCaml variant is measured three ways, all producing identical output:
#
#   baseline   as shipped
#   pollnop    the SAME binary with every poll overwritten by a NOP
#              (tools/nop_polls.py; identical registers, schedule and layout)
#   pollfree   recompiled with ocamlopt -disable-poll-insertion
#              (polls truly gone, but the compiler also re-optimised around them)
#
# The two removal methods bracket the answer. nopoll is a LOWER bound - a NOP still
# occupies a decode slot and a ROB entry, so some of the poll's cost survives it.
# pollflag is an UPPER bound - it removes the instructions outright, but the register
# allocator and scheduler were free to change other things too. If the two agree, the
# number is solid; if they diverge, the truth is between them and the script says so.
#
# Both kernels are measured on purpose. The plain kernel runs its inner loop
# rows*cols times per linear() call; the 4-way unrolled kernel runs it rows*cols/4
# times, so it executes about a quarter as many back-edge polls for the same
# arithmetic. Poll removal should therefore help the plain kernel roughly four times
# as much. That prediction is a built-in check that this is measuring polls and not
# something else - the script prints the ratio so it can be read off.
#
# cpp_unroll is included only as the target being chased, so the remaining gap can be
# quoted after polls are taken out of the picture.
#
# Env knobs: PIN (default 0, -1 disables), ROUNDS, REPEATS, BUDGET, SAMPLES, MODES.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT=/tmp/mgpolls
rm -rf "$OUT" && mkdir -p "$OUT"

PIN="${PIN:-0}"
ROUNDS="${ROUNDS:-9}"
REPEATS="${REPEATS:-3}"
BUDGET="${BUDGET:-0.3}"
SAMPLES="${SAMPLES:-200}"
MODES="${MODES:-gen}"
OCAML_SWITCH="${MG_OCAML_SWITCH:-5.4.0}"
if [ "$PIN" = "-1" ]; then TASKSET=(); else TASKSET=(taskset -c "$PIN"); fi

echo "=== building ==="
g++ -O3 -std=c++20 -fno-fast-math -ffp-contract=off -o "$OUT/cpp_unroll" impl/cpp/infer.cpp \
  2>/dev/null && echo "  cpp_unroll (reference)" || echo "  cpp_unroll FAILED"

# base_name : builder : unroll : extra ocamlopt flags
build_ocaml () {   # $1=name $2=script $3=MG_UNROLL $4=flags $5=switch-env
  local name="$1" script="$2" unroll="$3" flags="$4"
  if env $5 MG_UNROLL="$unroll" OCAMLFLAGS="$flags" OUT="$OUT/$name" \
       bash "$script" >/dev/null 2>&1; then
    echo "  $name"
  else
    echo "  $name FAILED"
  fi
}

for kernel in plain unroll; do
  u=1; [ "$kernel" = plain ] && u=0
  build_ocaml "oxcaml_unsafe_${kernel}"          impl/oxcaml/build.sh "$u" "-O3 -unsafe" ""
  build_ocaml "oxcaml_unsafe_${kernel}_pollfree" impl/oxcaml/build.sh "$u" \
              "-O3 -unsafe -disable-poll-insertion" ""
  build_ocaml "ocaml_unsafe_${kernel}"           impl/ocaml/build.sh  "$u" "-unsafe" \
              "MG_OCAML_SWITCH=$OCAML_SWITCH"
  build_ocaml "ocaml_unsafe_${kernel}_pollfree"  impl/ocaml/build.sh  "$u" \
              "-unsafe -disable-poll-insertion" "MG_OCAML_SWITCH=$OCAML_SWITCH"
done

echo
echo "=== patching polls out of the linked binaries ==="
for b in oxcaml_unsafe_plain oxcaml_unsafe_unroll ocaml_unsafe_plain ocaml_unsafe_unroll; do
  if [ -x "$OUT/$b" ]; then
    echo "  $b:"
    python3 tools/nop_polls.py "$OUT/$b" "$OUT/${b}_pollnop" 2>&1 | sed 's/^/    /'
  fi
done
echo

# Sanity-check that the removals really happened rather than being silently ignored.
# Total poll SITES is the less interesting number - most sit in cold code (formatting,
# model loading) and never run. What predicts the speedup is how many sit in the two
# functions that run millions of times, so both are reported.
# The two compilers name symbols differently - OxCaml emits camlMain__linear_14_79_code,
# stock ocamlopt emits camlMain.linear_1014 - so both spellings have to be matched or the
# stock column silently reads zero.
#
# Spill traffic in linear() is reported alongside, because that turns out to be the thing
# that actually moves: see the analysis at the end of the run.
echo "=== poll sites, and spill traffic in linear(), per binary ==="
printf "  %-38s %7s %9s %8s\n" "binary" "polls" "in hot fn" "spills"
for f in "$OUT"/*; do
  [ -x "$f" ] && [ ! -d "$f" ] || continue
  objdump -d "$f" 2>/dev/null | awk -v name="$(basename "$f")" '
    /^[0-9a-f]+ <.*>:$/ { f=$2; gsub(/[<>:]/,"",f); inlin = (f ~ /caml(Main__|Main\.)linear/) }
    inlin && /mov.*\(%rsp\),/ { spill++ }
    /cmp[ \t]+\(%r14\),%r15/ { pend=1; pf=f; next }
    pend==1 { if ($0 ~ /jbe/) { tot++
                if (pf ~ /caml(Main__|Main\.)(linear|forward)/) hot++ } ; pend=0 }
    END { printf "  %-38s %7d %9d %8d\n", name, tot, hot, spill }'
done
echo
echo "  Note: stock ocamlopt has no -disable-poll-insertion flag (it is OxCaml-only),"
echo "  so the *_pollfree row is absent for ocaml_*. For that compiler the binary patch"
echo "  is the only way to get this measurement at all."
echo

VARIANTS=()
for v in cpp_unroll \
         oxcaml_unsafe_plain  oxcaml_unsafe_plain_pollnop  oxcaml_unsafe_plain_pollfree \
         oxcaml_unsafe_unroll oxcaml_unsafe_unroll_pollnop oxcaml_unsafe_unroll_pollfree \
         ocaml_unsafe_plain   ocaml_unsafe_plain_pollnop   ocaml_unsafe_plain_pollfree \
         ocaml_unsafe_unroll  ocaml_unsafe_unroll_pollnop  ocaml_unsafe_unroll_pollfree; do
  [ -x "$OUT/$v" ] && VARIANTS+=("$v|$OUT/$v")
done

COMMON=(--weights "$ROOT/weights/microgpt.bin" --data "$ROOT/data/val.txt"
        --samples "$SAMPLES" --seed 1234 --temperature 0.5 --pin -1)

echo "=== correctness: every variant must produce identical output ==="
: > "$OUT/hashes.txt"
for e in "${VARIANTS[@]}"; do
  n="${e%%|*}"; c="${e#*|}"
  $c "${COMMON[@]}" --mode all --repeats 1 --time-budget 0.05 2>/dev/null > "$OUT/$n.json"
  python3 - "$n" "$OUT/$n.json" "$OUT/hashes.txt" <<'PY'
import json, sys
name, path, hp = sys.argv[1:4]
try:
    r = json.load(open(path))
except Exception as e:
    print(f"  {name:32s} FAILED to produce JSON ({e})"); raise SystemExit
open(hp, "a").write(f"{name} {r['gen']['output_fnv1a64']} {r['ppl']['perplexity']!r} "
                    f"{r['check']['first3_nll']!r}\n")
PY
done
python3 - "$OUT/hashes.txt" <<'PY'
import sys
rows = [l.split() for l in open(sys.argv[1])]
for r in rows:
    print(f"  {r[0]:32s} {r[1]}  ppl={r[2]}")
ok = len({r[1] for r in rows}) == 1 and len({r[2] for r in rows}) == 1 \
     and len({r[3] for r in rows}) == 1
print("\n  " + ("ALL IDENTICAL - differences below are real work saved" if ok else
                "*** VARIANTS DISAGREE - do not rank these ***"))
sys.exit(0 if ok else 1)
PY
if [ $? -ne 0 ]; then
  echo "refusing to report timings for variants that disagree." >&2
  exit 1
fi
echo

for MODE in $MODES; do
  echo "=== $MODE: $ROUNDS interleaved rounds, taskset cpu $PIN, budget ${BUDGET}s ==="
  : > "$OUT/t_$MODE.txt"
  for ((r=0; r<ROUNDS; r++)); do
    for e in "${VARIANTS[@]}"; do
      n="${e%%|*}"; c="${e#*|}"
      tps=$("${TASKSET[@]}" $c "${COMMON[@]}" --mode "$MODE" --repeats "$REPEATS" \
              --time-budget "$BUDGET" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin)['$MODE']['tokens_per_sec_best'])")
      echo "$n $tps" >> "$OUT/t_$MODE.txt"
    done
  done

  python3 - "$OUT/t_$MODE.txt" <<'PY'
import statistics, sys
from collections import OrderedDict
res = OrderedDict()
for line in open(sys.argv[1]):
    k, v = line.split()
    res.setdefault(k, []).append(float(v))
med = {k: statistics.median(v) for k, v in res.items()}
cpp = med.get("cpp_unroll")

print("| variant | tok/s (median) | sd | vs cpp_unroll |")
print("|---|---:|---:|---:|")
for k, v in res.items():
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    gap = f"{cpp/med[k]:.2f}x slower" if cpp and k != "cpp_unroll" else "-"
    print(f"| {k} | {med[k]:,.0f} | {sd:,.0f} | {gap} |")

def paired(base, cur):
    if base not in res or cur not in res:
        return None
    pd = [(a - b) / b * 100 for a, b in zip(res[cur], res[base])]
    return statistics.median(pd), sum(1 for x in pd if x > 0), len(pd)

print("\n\nCOST OF GC SAFEPOINT POLLS (paired against each variant's own baseline)")
print("-" * 78)
print(f"  {'variant':28s} {'NOP patch':>16s} {'-disable-poll':>16s}")
print(f"  {'':28s} {'(lower bound)':>16s} {'(upper bound)':>16s}")
gains = {}
for base in ["oxcaml_unsafe_plain", "oxcaml_unsafe_unroll",
             "ocaml_unsafe_plain", "ocaml_unsafe_unroll"]:
    a, b = paired(base, base + "_pollnop"), paired(base, base + "_pollfree")
    if not a and not b:
        continue
    gains[base] = (a[0] if a else None, b[0] if b else None)
    fa = f"{a[0]:+.1f}% ({a[1]}/{a[2]})" if a else "-"
    fb = f"{b[0]:+.1f}% ({b[1]}/{b[2]})" if b else "-"
    print(f"  {base:28s} {fa:>16s} {fb:>16s}")

print("\n  (percentages are median paired speedup, and rounds won out of rounds run)")

# Falsification test. If the cost of a poll were the two instructions it executes,
# then (a) the NOP patch and the flag would agree, and (b) the plain kernel - which
# runs its inner loop 4x more often, so executes ~4x the back-edge polls - would gain
# about 4x what the unrolled kernel gains. Both predictions are checked here, and when
# they fail the cost is not execution: it is what the poll does to register allocation.
print("\n\nIS THE COST THE INSTRUCTIONS, OR THE CONSTRAINT?")
print("-" * 78)
print("  Prediction A: if polls cost what they execute, NOP patch == flag.")
for base, (a, b) in gains.items():
    if a is None or b is None:
        continue
    verdict = "agree" if abs(a - b) < 2.0 else "DISAGREE -> cost is not the instructions"
    print(f"    {base:28s} NOP {a:+5.1f}%  vs  flag {b:+5.1f}%   {verdict}")
print("\n  Prediction B: the plain kernel executes ~4x the polls, so should gain ~4x.")
for comp in ["oxcaml", "ocaml"]:
    p, u = gains.get(f"{comp}_unsafe_plain"), gains.get(f"{comp}_unsafe_unroll")
    if not p or not u:
        continue
    for idx, label in ((0, "NOP patch"), (1, "-disable-poll")):
        if p[idx] is None or u[idx] is None:
            continue
        ratio = f"{p[idx]/u[idx]:.1f}x" if abs(u[idx]) > 0.5 else "n/a (both ~0)"
        note = "" if abs(u[idx]) <= 0.5 else (
            "  as predicted" if 2.0 <= p[idx] / u[idx] <= 8.0
            else "  PREDICTION FAILS -> not driven by how often polls run")
        print(f"    {comp:6s} {label:14s} plain {p[idx]:+5.1f}%  unrolled {u[idx]:+5.1f}%"
              f"   ratio {ratio}{note}")

print("\n\nHOW MUCH OF THE GAP TO C++ DO POLLS EXPLAIN?")
print("-" * 78)
if cpp:
    for base in ["oxcaml_unsafe_unroll", "ocaml_unsafe_unroll",
                 "oxcaml_unsafe_plain", "ocaml_unsafe_plain"]:
        if base not in med:
            continue
        before = cpp / med[base]
        line = f"  {base:28s} {before:.2f}x slower than cpp"
        for suf, lbl in (("_pollnop", "NOP"), ("_pollfree", "flag")):
            if base + suf in med:
                after = cpp / med[base + suf]
                closed = (before - after) / (before - 1) * 100 if before > 1 else 0.0
                line += f"  ->  {after:.2f}x [{lbl}, {closed:.0f}% of gap closed]"
        print(line)
PY
  echo
done
