"""Generate the benchmark script of run U from the repository's tools/bench_variants.sh.

    python3 report/data/make_bench.py tools/bench_variants.sh tools/bench_unified.sh
    OUTDIR=/tmp/mgu MODES="gen ppl" ROUNDS=21 PIN=0 bash tools/bench_unified.sh

It keeps every variant of bench_variants.sh up to the compiler ladder, replaces the
ox54p_* rows with the pull-request compiler (MG_OX_PR, default ~/oxinstall-fix), and adds
the pr_* configurations, the NOP-patched poll builds, an A/A copy of pr_counted, a
bounds-checked counted build and an AVX-encoded scalar C++ build. Variants whose compiler
or instruction set is missing fail to build and are skipped, so the same script runs on
an ARM machine (no SSE2 kernel, no NOP patch, no AVX build).
"""
import sys, re
src = open(sys.argv[1]).read()
a = src.index("# The ladder on a normally configured compiler")
b = src.index("# name|command")
block = r'''# ---- unified run: PR compiler (poll insertion on), flags select the configuration ----
FIX="${MG_OX_PR:-$HOME/oxinstall-fix/bin/ocamlopt.opt}"
OFF="-no-cmm-strength-reduction -no-cmm-interior-pointers -no-cmm-invariant-strides -no-cmm-licm"
build_ox54 pr_off            "$FIX" "$OFF"
build_ox54 pr_all            "$FIX" ""
build_ox54 pr_off_nopoll     "$FIX" "$OFF -disable-poll-insertion"
build_ox54 pr_nopoll         "$FIX" "-disable-poll-insertion"
build_ox54 pr_counted        "$FIX" "-cmm-counted-loops"
build_ox54 pr_counted_noptr  "$FIX" "-cmm-counted-loops -no-cmm-interior-pointers -no-cmm-carried-pointers"
build_ox54 pr_unchecked      "$FIX" "-cmm-unchecked-loops"
build_simd pr_simd_off       "$FIX" "$OFF"
build_simd pr_simd           "$FIX" ""
build_simd pr_simd_counted   "$FIX" "-cmm-counted-loops"
build_simd pr_simd_nopoll    "$FIX" "-disable-poll-insertion"
# bounds-checked build with counted loops (no -unsafe)
[ -x "$FIX" ] && MG_OCAMLOPT="$FIX" MG_UNROLL=1 OCAMLFLAGS="-O3 -cmm-counted-loops" OUT="$OUT/pr_safe_counted" \
  bash impl/oxcaml/build.sh >/dev/null 2>&1 && echo "  pr_safe_counted" || echo "  pr_safe_counted FAILED"
# A/A control: a byte-identical copy of pr_counted at another path
cp "$OUT/pr_counted" "$OUT/pr_counted_copy" && echo "  pr_counted_copy (A/A control)"
# C++ baseline with VEX encoding (AVX, no FMA contraction, vectoriser off)
g++ -O3 $CXXFLAGS_COMMON -fno-tree-vectorize -mavx -o "$OUT/cpp_novec_avx" impl/cpp/infer.cpp 2>/dev/null \
  && echo "  cpp_novec_avx" || echo "  cpp_novec_avx FAILED"
# polls overwritten by NOPs in the linked shipped binaries (same layout, same registers)
for bb in oxcaml_unsafe_plain oxcaml_unsafe_unroll; do
  python3 tools/nop_polls.py "$OUT/$bb" "$OUT/${bb}_pollnop" >/dev/null 2>&1 && echo "  ${bb}_pollnop" || echo "  ${bb}_pollnop FAILED"
done

# SIMD against the pinned 5.2.0+ox switch as well
MG_UNROLL=1 MG_SIMD=1 OCAMLFLAGS="-O3 -unsafe" OUT="$OUT/oxcaml_unsafe_simd" bash impl/oxcaml/build.sh >/dev/null 2>&1 && echo "  oxcaml_unsafe_simd" || echo "  oxcaml_unsafe_simd FAILED"
echo

'''
src = src[:a] + block + src[b:]
src = re.sub(r'for v in cpp_O2_plain.*?; do', '''for v in cpp_O2_plain cpp_plain cpp_unroll cpp_novec cpp_novec_avx rust_plain rust_unroll \
         oxcaml_safe_plain oxcaml_safe_unroll oxcaml_unsafe_plain oxcaml_unsafe_unroll \
         oxcaml_unsafe_plain_pollnop oxcaml_unsafe_unroll_pollnop \
         oxcaml_unsafe_plain_pollfree oxcaml_unsafe_unroll_pollfree \
         oxcaml_unsafe_sr oxcaml_unsafe_sr_pollfree oxcaml_unsafe_simd \
         ocaml_safe_plain ocaml_safe_unroll ocaml_unsafe_plain ocaml_unsafe_unroll ocaml_unsafe_sr \
         ox54_base ox54_sr ox54_ip_off ox54_ip ox54_ivs_noptr ox54_ivs ox54_licm \
         pr_off pr_all pr_off_nopoll pr_nopoll pr_counted pr_counted_copy pr_counted_noptr pr_unchecked \
         pr_safe_counted pr_simd_off pr_simd pr_simd_counted pr_simd_nopoll; do''', src, flags=re.S)
src = src.replace('OUT=/tmp/mgv\n', 'OUT=${OUTDIR:-/tmp/mgu}\n')
open(sys.argv[2], "w").write(src)
