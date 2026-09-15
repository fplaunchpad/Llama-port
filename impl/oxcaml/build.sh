#!/usr/bin/env bash
# Build the OxCaml port. Run inside WSL (or any Linux) with the OxCaml switch active.
#
#   bash impl/oxcaml/build.sh                       # shipped: -O3 -unsafe, unrolled
#   MG_UNROLL=0 bash impl/oxcaml/build.sh           # plain linear
#   MG_SR=1 bash impl/oxcaml/build.sh               # unrolled + strength-reduced indices
#   OCAMLFLAGS="-O3" bash impl/oxcaml/build.sh      # keep array bounds checks
#   OUT=/tmp/x bash impl/oxcaml/build.sh            # write the binary elsewhere
#
# OxCaml targets linux-x86_64, so this binary does not run natively on Windows.
# Correctness is platform-independent (verified: the same C++ source under g++ 14.2/glibc
# and g++ 15.2/UCRT produces bit-identical output), but SPEED comparisons must be run
# entirely inside one environment - see BENCHMARK.md section 5.
#
# OCaml has no standard conditional-compilation story without cppo, so the three forms of
# linear() cannot live in the source behind a #ifdef. Selecting at run time would add a
# closure indirection to the hottest function in the program, which would contaminate
# exactly the measurement these switches exist to make. So the alternate form is
# substituted in here, with an assertion that fails loudly if the source moves.
#
# MG_SR carries the four row offsets as running indices instead of recomputing base + i
# per row per iteration. Same values added in the same order, so the output is unchanged;
# it exists because flambda2 does not do that strength reduction itself. Worth +11% under
# flambda2 and -5% under the stock compiler, which is why it is a switch and not an edit
# to the shared source - see OPTIMIZATIONS.md.
set -euo pipefail
cd "$(dirname "$0")"
eval "$(opam env --switch=5.2.0+ox 2>/dev/null)" || true

OCAMLFLAGS="${OCAMLFLAGS:--O3 -unsafe}"
MG_UNROLL="${MG_UNROLL:-1}"
MG_SR="${MG_SR:-0}"
OUT="${OUT:-build/microgpt_infer}"
mkdir -p "$(dirname "$OUT")"

if [ "$MG_SR" = "1" ] && [ "$MG_UNROLL" = "0" ]; then
  echo "MG_SR=1 strength-reduces the UNROLLED kernel; MG_UNROLL=0 selects the plain one." >&2
  echo "  Pick one." >&2
  exit 1
fi

KERNEL=unrolled
[ "$MG_UNROLL" = "0" ] && KERNEL=plain
[ "$MG_SR" = "1" ] && KERNEL=sr

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp main.ml "$WORK/main.ml"

if [ "$KERNEL" != "unrolled" ]; then
  python3 - "$WORK/main.ml" "$KERNEL" <<'PY'
import sys
p, kernel = sys.argv[1], sys.argv[2]
s = open(p).read()
start = s.index("let linear (x : float array) (w : mat) (out : float array) =")
end = s.index("let rmsnorm_scale (x : float array) n =")
assert "while !o + 4 <= rows do" in s[start:end], "unrolled linear not where expected"

plain = '''let linear (x : float array) (w : mat) (out : float array) =
  for o = 0 to w.rows - 1 do
    let base = o * w.cols in
    let rec go i acc =
      if i >= w.cols then acc else go (i + 1) (acc +. (w.d.(base + i) *. x.(i)))
    in
    out.(o) <- go 0 0.0
  done

'''

# Identical arithmetic to the shipped kernel, in identical order - the only change is
# that b_k + i is carried rather than rebuilt. The output hash must not move.
sr = '''let linear (x : float array) (w : mat) (out : float array) =
  let cols = w.cols and rows = w.rows and d = w.d in
  let o = ref 0 in
  while !o + 4 <= rows do
    let b0 = !o * cols in
    let j0 = ref b0 in
    let j1 = ref (b0 + cols) in
    let j2 = ref (b0 + (2 * cols)) in
    let j3 = ref (b0 + (3 * cols)) in
    let a0 = ref 0.0 and a1 = ref 0.0 and a2 = ref 0.0 and a3 = ref 0.0 in
    for i = 0 to cols - 1 do
      let xi = x.(i) in
      a0 := !a0 +. (d.(!j0) *. xi);
      a1 := !a1 +. (d.(!j1) *. xi);
      a2 := !a2 +. (d.(!j2) *. xi);
      a3 := !a3 +. (d.(!j3) *. xi);
      incr j0;
      incr j1;
      incr j2;
      incr j3
    done;
    out.(!o) <- !a0;
    out.(!o + 1) <- !a1;
    out.(!o + 2) <- !a2;
    out.(!o + 3) <- !a3;
    o := !o + 4
  done;
  while !o < rows do
    let base = !o * cols in
    let acc = ref 0.0 in
    for i = 0 to cols - 1 do
      acc := !acc +. (d.(base + i) *. x.(i))
    done;
    out.(!o) <- !acc;
    incr o
  done

'''
open(p, "w").write(s[:start] + (plain if kernel == "plain" else sr) + s[end:])
PY
fi

# keep the JSON self-describing
case "$KERNEL" in
  plain)    DESC="ocamlopt (flambda2, plain linear)" ;;
  sr)       DESC="ocamlopt (flambda2, strength-reduced linear)" ;;
  *)        DESC="ocamlopt (flambda2, unrolled linear)" ;;
esac
sed -i "s/ocamlopt -O3 (flambda2); no fast-math equivalent exists in OCaml/$DESC/" "$WORK/main.ml"

ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
( cd "$WORK" && ocamlopt $OCAMLFLAGS -I +unix unix.cmxa main.ml -o "$ABS_OUT" )
echo "built $ABS_OUT  (OCAMLFLAGS='$OCAMLFLAGS' kernel=$KERNEL)"
