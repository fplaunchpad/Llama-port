#!/usr/bin/env bash
# Build the OxCaml port. Run inside WSL (or any Linux) with the OxCaml switch active.
#
#   bash impl/oxcaml/build.sh                       # shipped: -O3 -unsafe, unrolled
#   MG_UNROLL=0 bash impl/oxcaml/build.sh           # plain linear
#   MG_SR=1 bash impl/oxcaml/build.sh               # unrolled + strength-reduced indices
#   MG_SIMD=1 bash impl/oxcaml/build.sh             # unrolled + SSE2, two rows per vector
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
# MG_SIMD pairs the four rows into two SSE2 vectors, so lane 0 accumulates row o and
# lane 1 row o+1. Each lane adds the same products in the same order as the scalar
# kernel, so the output is bit-identical - what is saved is FP port pressure, four
# packed multiply-adds per iteration instead of eight scalar ones. The intrinsics are
# [@@builtin] externals, which the native compiler expands inline; simd_stubs.c exists
# only so the linker has a symbol for the closure that still carries their address.
#
# MG_SR carries the four row offsets as running indices instead of recomputing base + i
# per row per iteration. Same values added in the same order, so the output is unchanged;
# it exists because flambda2 does not do that strength reduction itself. It is a switch
# rather than an edit to the shared source so that the compiler pass that does the same
# thing (compiler-patches/, patch 1) can be measured on the unmodified source. The
# measured effect of every switch is in README.md.
set -euo pipefail
cd "$(dirname "$0")"

# MG_OCAMLOPT names an ocamlopt binary directly, for benchmarking a locally built
# compiler against the opam one. Without it the pinned 5.2.0+ox switch is used, and
# that switch selection is silent - so anything measuring a modified compiler MUST set
# this, or it will quietly build every "variant" with 5.2.0+ox and compare a binary
# against itself.
MG_OCAMLOPT="${MG_OCAMLOPT:-}"
if [ -n "$MG_OCAMLOPT" ]; then
  [ -x "$MG_OCAMLOPT" ] || { echo "MG_OCAMLOPT=$MG_OCAMLOPT is not executable" >&2; exit 1; }
  OCAMLOPT="$MG_OCAMLOPT"
else
  eval "$(opam env --switch=5.2.0+ox 2>/dev/null)" || true
  OCAMLOPT=ocamlopt
fi

# The mirror of impl/ocaml/build.sh's check: without the 5.2.0+ox switch the line above
# falls through to whatever ocamlopt is on PATH, which on a machine without OxCaml is the
# stock compiler. It accepts -O3, so the build would succeed and an "oxcaml" row would
# quietly measure stock OCaml.
if ! "$OCAMLOPT" -config 2>/dev/null | grep -q '^flambda2: true'; then
  echo "refusing to build: $(command -v "$OCAMLOPT" || echo "$OCAMLOPT") is not an OxCaml (flambda2) compiler." >&2
  echo "  Install the opam switch 5.2.0+ox (Linux x86-64), or point MG_OCAMLOPT at an" >&2
  echo "  OxCaml ocamlopt. The stock-compiler build of the same source is impl/ocaml/build.sh." >&2
  exit 1
fi

OCAMLFLAGS="${OCAMLFLAGS:--O3 -unsafe}"
MG_UNROLL="${MG_UNROLL:-1}"
MG_SR="${MG_SR:-0}"
MG_SIMD="${MG_SIMD:-0}"
OUT="${OUT:-build/microgpt_infer}"
mkdir -p "$(dirname "$OUT")"

if [ "$MG_SR" = "1" ] && [ "$MG_UNROLL" = "0" ]; then
  echo "MG_SR=1 strength-reduces the UNROLLED kernel; MG_UNROLL=0 selects the plain one." >&2
  echo "  Pick one." >&2
  exit 1
fi
if [ "$MG_SIMD" = "1" ] && [ "$MG_UNROLL" = "0" ]; then
  echo "MG_SIMD=1 vectorizes the UNROLLED kernel; MG_UNROLL=0 selects the plain one." >&2
  echo "  Pick one." >&2
  exit 1
fi
if [ "$MG_SIMD" = "1" ] && [ "$MG_SR" = "1" ]; then
  echo "MG_SIMD=1 already carries its row indices; MG_SR=1 is the scalar form of that." >&2
  echo "  Pick one." >&2
  exit 1
fi

KERNEL=unrolled
[ "$MG_UNROLL" = "0" ] && KERNEL=plain
[ "$MG_SR" = "1" ] && KERNEL=sr
[ "$MG_SIMD" = "1" ] && KERNEL=simd

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp main.ml "$WORK/main.ml"
cp simd_stubs.c "$WORK/simd_stubs.c"

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
# Two rows per vector. Lane 0 accumulates row o and lane 1 row o+1, each adding the
# same products in the same order as the scalar kernel, so every lane reproduces that
# row's sum exactly and the output hash must not move. The intrinsics are declared
# here rather than imported: ocaml_simd is a separate opam package, and the six
# primitives this needs are builtins the compiler expands inline.
simd = '''external unbox : float -> float# = "%unbox_float"
external box : float# -> float = "%box_float"

module F = struct
  type t = float64x2#

  external add : t -> t -> t
    = "caml_sse2_unreachable" "caml_sse2_float64x2_add"
    [@@noalloc] [@@unboxed] [@@builtin]

  external mul : t -> t -> t
    = "caml_sse2_unreachable" "caml_sse2_float64x2_mul"
    [@@noalloc] [@@unboxed] [@@builtin]

  external low_of : float# -> t
    = "caml_sse2_unreachable" "caml_float64x2_low_of_float"
    [@@noalloc] [@@builtin]

  external low_to : t -> float#
    = "caml_sse2_unreachable" "caml_float64x2_low_to_float"
    [@@noalloc] [@@builtin]

  external low_64_to_high_64 : t -> t -> t
    = "caml_sse2_unreachable" "caml_sse_vec128_low_64_to_high_64"
    [@@noalloc] [@@unboxed] [@@builtin]

  external high_64_to_low_64 : t -> t -> t
    = "caml_sse2_unreachable" "caml_sse_vec128_high_64_to_low_64"
    [@@noalloc] [@@unboxed] [@@builtin]

  (* [pair a b] puts a in the low lane and b in the high one. *)
  let[@inline always] pair a b = low_64_to_high_64 (low_of a) (low_of b)
  let[@inline always] lo v = box (low_to v)
  let[@inline always] hi v = box (low_to (high_64_to_low_64 v v))
end

let linear (x : float array) (w : mat) (out : float array) =
  let cols = w.cols and rows = w.rows and d = w.d in
  let o = ref 0 in
  while !o + 4 <= rows do
    let b0 = !o * cols in
    let b1 = b0 + cols and b2 = b0 + (2 * cols) and b3 = b0 + (3 * cols) in
    let rec go i (v01 : float64x2#) (v23 : float64x2#) =
      if i >= cols
      then #(v01, v23)
      else
        let xi = unbox x.(i) in
        let xv = F.pair xi xi in
        let r01 = F.pair (unbox d.(b0 + i)) (unbox d.(b1 + i)) in
        let r23 = F.pair (unbox d.(b2 + i)) (unbox d.(b3 + i)) in
        go (i + 1) (F.add v01 (F.mul r01 xv)) (F.add v23 (F.mul r23 xv))
    in
    let z = F.pair (unbox 0.0) (unbox 0.0) in
    let #(v01, v23) = go 0 z z in
    out.(!o) <- F.lo v01;
    out.(!o + 1) <- F.hi v01;
    out.(!o + 2) <- F.lo v23;
    out.(!o + 3) <- F.hi v23;
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

body = {"plain": plain, "sr": sr, "simd": simd}[kernel]
open(p, "w").write(s[:start] + body + s[end:])
PY
fi

# keep the JSON self-describing. Done in python, not `sed -i`: that flag takes a
# mandatory backup suffix on BSD/macOS and none on GNU, so no single spelling works
# on both, and the failure is silent corruption of the file rather than an error.
case "$KERNEL" in
  plain)    DESC="ocamlopt (flambda2, plain linear)" ;;
  sr)       DESC="ocamlopt (flambda2, strength-reduced linear)" ;;
  simd)     DESC="ocamlopt (flambda2, SSE2 linear)" ;;
  *)        DESC="ocamlopt (flambda2, unrolled linear)" ;;
esac
python3 - "$WORK/main.ml" "$DESC" <<'PY'
import sys
path, desc = sys.argv[1], sys.argv[2]
old = "ocamlopt -O3 (flambda2); no fast-math equivalent exists in OCaml"
s = open(path, encoding="utf-8").read()
assert old in s, "runtime identity string not found; impl/oxcaml/main.ml moved"
open(path, "w", encoding="utf-8").write(s.replace(old, desc))
PY

ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
# The stubs are linked only into the SIMD build: they are six empty functions, but
# adding them everywhere would change code layout in every other variant for nothing.
STUBS=()
[ "$KERNEL" = "simd" ] && STUBS=(simd_stubs.c)
( cd "$WORK" && "$OCAMLOPT" $OCAMLFLAGS -I +unix unix.cmxa "${STUBS[@]}" main.ml -o "$ABS_OUT" )
echo "built $ABS_OUT  (ocamlopt $("$OCAMLOPT" -version), OCAMLFLAGS='$OCAMLFLAGS' kernel=$KERNEL)"
