# Compiler passes: the Cmm loop optimisations

The compiler half of this project is one patch series on my OxCaml fork. The version
measured in the report (run W) is branch
[`ugrc2-rebased`](https://github.com/AadiSrivastava05/oxcaml/tree/ugrc2-rebased) at
commit `91acf6b7e9921529ac0d96506abcf6032f31ed4a`: `oxcaml/oxcaml` main at
`327965f0e72292605600a3c5d9a7bf50c59b345a` (30 October 2026) plus 24 patches, which are
also in [`report/data/pr-patches/`](../report/data/pr-patches/). Pull request
[AadiSrivastava05/oxcaml#1](https://github.com/AadiSrivastava05/oxcaml/pull/1) (branch
`interior-pointers`, based on main at `c52688875`, 15 September 2026) shows an earlier
revision: its eight commits correspond to the first eight patches of the series.

This directory holds patches 0001 to 0004 of that earlier revision, on `c52688875`. They
build the `ox54_*` ladder compilers, one compiler per pass.

All passes live in one new file, `backend/cmm_strength_reduction.ml`, and run on Cmm
before instruction selection. The other files they touch are the flag definitions
(`driver/oxcaml_args.ml`, `driver/oxcaml_flags.ml`), instruction selection
(`backend/cfg_selectgen.ml`, which must accept a derived pointer in a loop-carried
register) and poll placement (`backend/cfg/cfg_polling.ml`, `cfg_simplify.ml`, which must
leave a counted loop's back edge alone).

## One concept per patch

Patch numbers are those of [`report/data/pr-patches/`](../report/data/pr-patches/).

| patch | concept | flag (default) | measured by (variants, `bench/variants.py`) |
|---|---|---|---|
| 0001 | strength reduction of derived induction variables: carry `base + i` as a loop parameter | `-[no-]cmm-strength-reduction` (on) | `ox54_base` -> `ox54_sr`; `pr_c_off` -> `pr_c_sr` |
| 0002 | interior pointers: one hoisted row address (`Addr`) per array row, one shared index, in loops that cannot reach the GC | `-[no-]cmm-interior-pointers` (on) | `ox54_sr` -> `ox54_ip`; `ox54_ip_off` -> `ox54_ip`; `pr_c_sr` -> `pr_c_ip` |
| 0003 | invariant-stride induction variables: carry the row pointers across the row loop (stride `cols`, not a constant) | `-[no-]cmm-invariant-strides` (on); `-[no-]cmm-carried-pointers` (on) | `ox54_ip` -> `ox54_ivs`; `ox54_ivs_noptr` -> `ox54_ivs` |
| 0004 | loop-invariant code motion, register-neutral: hoists only where the operands die, so it declines on microgpt (identical code) | `-[no-]cmm-licm` (on) | `ox54_ivs` -> `ox54_licm` |
| 0005 | one gate for interior and carried pointers (per function, honouring `[@poll error]`); a cost model for LICM's hoists | no new flag | part of every `pr_*` build |
| 0006 | counted loops: a GC-free loop proved to terminate polls on its exits instead of its back edge, so the pointer passes apply with safepoints on; generalised address analysis (noalloc builtins, untagged vector indices) | `-cmm-counted-loops` (off); `-dcounted-loops` prints each decision | `pr_off` -> `pr_counted`; `pr_all` -> `pr_counted`; `pr_counted_noptr` -> `pr_counted` |
| 0007 | unchecked loops: the same without the termination proof (loss of liveness possible, opt-in) | `-cmm-unchecked-loops` (off) | `pr_counted` -> `pr_unchecked` |
| 0008 | unchecked loops can cost liveness only, never change a result; the `-no-cmm-*-pointers` flags apply inside counted loops | (as 0007) | `pr_unchecked`, `pr_counted_noptr` |
| 0009-0024 | follow-ups: caps on the analyses, `[@poll error]` handling, a loop dump, a trip cap, a size budget for versioned loops, tests, and adaptation to the 30 October main branch | `-dcmm-loops`; `-cmm-counted-loops-max-trips N` (off) | every `pr_*` build |

The four passes of patches 1 to 4 are on by default and switched off one at a time with
the `-no-` flags (for strength reduction and interior pointers, the report checks that
switching the pass off gives code byte-identical to the compiler without it). Counted and
unchecked loops are off unless asked for. With safepoints
on (the release configuration), interior and carried pointers can only form inside
counted or unchecked loops, because a derived pointer may not be live across a poll; the
backend's `bad GC root` check turns any mistake there into a compile-time error.

## The compiler configurations in run W

| family | source | configured with | install (default path) | variants |
|---|---|---|---|---|
| ladder | `c52688875` + patches 1..k of this directory, k = 0..4 | `--enable-flambda2` (no poll insertion) | `~/oxinstall-baseline`, `-sr`, `-ip`, `-ivs`, `-licm` | `ox54_*` |
| pull request | `327965f0e` + the 24 patches (commit `91acf6b`) | `--enable-middle-end=flambda2 --enable-stack-checks --enable-poll-insertion --enable-multidomain --disable-warn-error` | `~/oxinstall-pr-latest` | `pr_*` |
| release | opam package `oxcaml-compiler.5.4.0-ox7`, unpatched | as its opam recipe | `~/oxinstall-ox7` | `oxcaml_*` |

The ladder isolates each pass on unchanged source with no polls in any loop (report
Sections 8-10). The pull-request compiler is configured like the release, with a
poll on every loop back edge, and flags select the configuration (report Sections 11-15).
`ocamlopt -config` reports `poll_insertion: false` for the ladder and `true` for the
pull-request compiler. The `oxcaml52_*` variants use the previous release, opam switch
`5.2.0+ox`.

## Building a compiler

Linux x86-64 only. The bootstrap compiler must itself be an OxCaml 5.4 (the tree uses
labelled tuples, `Char.Ascii` and `Format.utf_8_scalar_width`); `dune >= 3.23.0` and
`menhir.20231231` come from an ordinary opam switch.

```bash
git clone https://github.com/oxcaml/oxcaml && cd oxcaml
# the pull-request compiler of run W
git remote add fork https://github.com/AadiSrivastava05/oxcaml
git fetch fork ugrc2-rebased && git checkout 91acf6b7e9921529ac0d96506abcf6032f31ed4a
#   or: git checkout -b pr 327965f0e72292605600a3c5d9a7bf50c59b345a
#       git am /path/to/llamaport/report/data/pr-patches/00*.patch
# ladder compiler k instead:
#   git checkout -b ladder c52688875424f836c3a4aa8d3c0f9840543a57e9
#   git am /path/to/llamaport/compiler-patches/000[1-k]-*.patch

export PATH=$HOME/oxinstall/bin:$HOME/.opam/5.4.0/bin:$PATH   # bootstrap OxCaml, then dune + menhir
tools/autogen
./configure --enable-middle-end=flambda2 --enable-stack-checks --enable-poll-insertion \
            --enable-multidomain --disable-warn-error --prefix="$HOME/oxinstall-pr-latest"
#   ladder: ./configure --enable-flambda2 --prefix="$HOME/oxinstall-sr"   (etc.)
make -j"$(nproc)" _install
```

## Pointing the benchmark at the compilers

`bench/bench.py` looks for the compilers at the paths above and skips the variants of
any it does not find. Other locations are set with:

```bash
export MG_OX_RELEASE=/path/to/5.4.0-ox7/bin/ocamlopt.opt   # oxcaml_*
export MG_OX54_BASE=/path/to/unpatched/bin/ocamlopt.opt   # ox54_base
export MG_OX54_SR=...     # patch 1         ox54_sr
export MG_OX54_IP=...     # patches 1-2     ox54_ip, ox54_ip_off
export MG_OX54_IVS=...    # patches 1-3     ox54_ivs, ox54_ivs_noptr
export MG_OX54_LICM=...   # patches 1-4     ox54_licm
export MG_OX_PR=...       # all 24 patches, poll insertion on: every pr_* variant
python3 bench/bench.py --concept pass_sr,pass_ip,pass_ivs,pass_licm,safepoints,counted
```

`python3 bench/bench.py --show pr_counted` prints the exact build command of a variant.

## Testing

Report Section 12 gives the full account. The upstream OxCaml test suite on the
pull-request compiler, configured as above (155 tests skipped in each mode): the
unpatched compiler and the default flags both pass 2,818 tests with no failures;
`-cmm-counted-loops`, forced onto every test through `OCAMLPARAM`, fails only the two
`[@poll error]` tests; `-cmm-unchecked-loops` fails 18 (16 that need a loop to reach a
safepoint to be preempted, 2 thread-local storage). Every microgpt build in run W
reproduces the reference output (hash `0xae6c6ffbd8f5b02c`, perplexity
`10.789614873329409`).
