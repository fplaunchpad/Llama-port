#!/usr/bin/env bash
# Build the plain-OCaml port with the STOCK upstream compiler.
#
#   bash impl/ocaml/build.sh                          # shipped: -unsafe, unrolled
#   MG_UNROLL=0 bash impl/ocaml/build.sh              # plain linear
#   MG_SR=1 bash impl/ocaml/build.sh                  # unrolled + strength-reduced indices
#   OCAMLFLAGS="" bash impl/ocaml/build.sh            # keep array bounds checks
#   MG_OCAML_SWITCH=5.4.0 bash impl/ocaml/build.sh    # pick an opam switch
#   OUT=/tmp/x bash impl/ocaml/build.sh               # write the binary elsewhere
#
# This is the same program as impl/oxcaml, built by a different compiler. The source
# files are held byte-identical on purpose (see the assertion below), so the delta
# between the two binaries is the MIDDLE-END and nothing else: upstream ocamlopt uses
# the closure middle-end, OxCaml uses flambda2. -O3 is a flambda-only flag and simply
# does not apply here, which is itself part of the result.
#
# Compiler selection: MG_OCAML_SWITCH names an opam switch if you have one; otherwise
# whatever `ocamlopt` is on PATH is used as-is. Either way the script refuses to run
# if that compiler reports flambda2, because benchmarking OxCaml under the name
# "ocaml" would quietly make the comparison meaningless.
#
# Like impl/oxcaml/build.sh, the MG_UNROLL=0 variant is produced by substituting the
# plain form of linear() into a scratch copy of the source: OCaml has no conditional
# compilation without cppo, and selecting at run time would put a closure indirection
# in the hottest function in the program.
set -euo pipefail
cd "$(dirname "$0")"

if [ -n "${MG_OCAML_SWITCH:-}" ]; then
  eval "$(opam env --switch="$MG_OCAML_SWITCH" --set-switch 2>/dev/null)" || true
  hash -r    # bash caches the previous switch's ocamlopt otherwise
fi

OCAMLFLAGS="${OCAMLFLAGS--unsafe}"
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

if ocamlopt -config | grep -q '^flambda2: true'; then
  echo "refusing to build: $(command -v ocamlopt) is an OxCaml/flambda2 compiler." >&2
  echo "  This port exists to measure the STOCK compiler. Set MG_OCAML_SWITCH to a" >&2
  echo "  plain switch, or use impl/oxcaml/build.sh for the flambda2 build." >&2
  exit 1
fi

# The two OCaml sources must stay identical apart from the header comment and the two
# identity strings in the JSON report. If they drift, this stops being a compiler
# comparison and becomes a source comparison - without anyone noticing.
if [ "${MG_SKIP_SYNC_CHECK:-0}" != "1" ] && [ -f ../oxcaml/main.ml ]; then
  python3 - main.ml ../oxcaml/main.ml <<'PY'
import re, sys

def body(path):
    s = open(path, encoding="utf-8").read()
    s = s[s.index("(* ------------------------------------------------------------------ sha256 *)"):]
    s = re.sub(r'jstr w "(impl|build)" "[^"]*";', r'jstr w "\1" <identity>;', s)
    return s.splitlines()

a, b = body(sys.argv[1]), body(sys.argv[2])
if a != b:
    import difflib
    d = list(difflib.unified_diff(b, a, "impl/oxcaml/main.ml", "impl/ocaml/main.ml", lineterm=""))
    sys.stderr.write("\n".join(d[:40]) + "\n")
    sys.exit("impl/ocaml/main.ml has drifted from impl/oxcaml/main.ml; the two ports must\n"
             "stay byte-identical outside the header and the identity strings, or the\n"
             "ocaml-vs-oxcaml numbers stop measuring the compiler. Re-sync, or set\n"
             "MG_SKIP_SYNC_CHECK=1 if you really mean them to differ.")
PY
fi

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
  plain)    DESC="ocamlopt (closure, plain linear)" ;;
  sr)       DESC="ocamlopt (closure, strength-reduced linear)" ;;
  *)        DESC="ocamlopt (closure, unrolled linear)" ;;
esac
sed -i "s/ocamlopt (stock upstream); no fast-math equivalent exists in OCaml/$DESC/" "$WORK/main.ml"

ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
( cd "$WORK" && ocamlopt $OCAMLFLAGS -I +unix unix.cmxa main.ml -o "$ABS_OUT" )
echo "built $ABS_OUT  (ocamlopt $(ocamlopt -version), OCAMLFLAGS='$OCAMLFLAGS' kernel=$KERNEL)"
