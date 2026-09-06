#!/usr/bin/env bash
# Build the OxCaml port. Run inside WSL (or any Linux) with the OxCaml switch active.
#
#   bash impl/oxcaml/build.sh                       # shipped: -O3 -unsafe, unrolled
#   MG_UNROLL=0 bash impl/oxcaml/build.sh           # plain linear
#   OCAMLFLAGS="-O3" bash impl/oxcaml/build.sh      # keep array bounds checks
#   OUT=/tmp/x bash impl/oxcaml/build.sh            # write the binary elsewhere
#
# OxCaml targets linux-x86_64, so this binary does not run natively on Windows.
# Correctness is platform-independent (verified: the same C++ source under g++ 14.2/glibc
# and g++ 15.2/UCRT produces bit-identical output), but SPEED comparisons must be run
# entirely inside one environment - see BENCHMARK.md section 5.
#
# OCaml has no standard conditional-compilation story without cppo, so the unrolled and
# plain forms of linear() cannot both live in the source behind a #ifdef. Selecting at
# run time would add a closure indirection to the hottest function in the program, which
# would contaminate exactly the measurement this switch exists to make. So the plain form
# is substituted in here, with an assertion that fails loudly if the source moves.
set -euo pipefail
cd "$(dirname "$0")"
eval "$(opam env --switch=5.2.0+ox 2>/dev/null)" || true

OCAMLFLAGS="${OCAMLFLAGS:--O3 -unsafe}"
MG_UNROLL="${MG_UNROLL:-1}"
OUT="${OUT:-build/microgpt_infer}"
mkdir -p "$(dirname "$OUT")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp main.ml "$WORK/main.ml"

if [ "$MG_UNROLL" = "0" ]; then
  python3 - "$WORK/main.ml" <<'PY'
import sys
p = sys.argv[1]
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
open(p, "w").write(s[:start] + plain + s[end:])
PY
  # keep the JSON self-describing
  sed -i 's/ocamlopt -O3 (flambda2); no fast-math equivalent exists in OCaml/ocamlopt (flambda2, plain linear)/' "$WORK/main.ml"
else
  sed -i 's/ocamlopt -O3 (flambda2); no fast-math equivalent exists in OCaml/ocamlopt (flambda2, unrolled linear)/' "$WORK/main.ml"
fi

ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
( cd "$WORK" && ocamlopt $OCAMLFLAGS -I +unix unix.cmxa main.ml -o "$ABS_OUT" )
echo "built $ABS_OUT  (OCAMLFLAGS='$OCAMLFLAGS' MG_UNROLL=$MG_UNROLL)"
