# llamaport

[microgpt](microgpt.py), a GPT small enough to read in one sitting (34 KB of weights),
ported to **C++, Rust, OCaml and OxCaml**, and then the question of why the OCaml ports
are slower than C++, answered and mostly closed.

All five ports load the same weights and produce **identical output**: perplexity
`10.789614873329409` on the held-out names, and generated text whose FNV-1a hash is
`0xae6c6ffbd8f5b02c` (200 samples, seed 1234, temperature 0.5). Every speed difference
below is therefore work saved, not corners cut.

OxCaml then gets faster in two steps: **source-level** changes to the OCaml program, and
**compiler passes** added to OxCaml itself (one pull request). The write-up is the report
in [`report/`](report/); every microgpt number in it comes from one benchmark run, *run W*
(62 builds, 21 interleaved rounds, 31 October 2026, raw data in
[`report/data/`](report/data/)).

## Results at a glance

Run W, generation mode, median tokens/s over 21 rounds. The gap is scalar C++
(`cpp_novec`) throughput over the build's; every build has identical output. OxCaml rows
use `-unsafe` unless marked bounds-checked.

| stage | build (variant) | tokens/s | gap to scalar C++ |
|---|---|---:|---:|
| reference | C++, auto-vectorised (`cpp_unroll`) | 772,261 | 0.93x |
| reference | **C++, scalar (`cpp_novec`)** | 716,505 | 1.00x |
| reference | Rust, bounds-checked (`rust_unroll`) | 703,295 | 1.02x |
| reference | stock OCaml 5.3.0 (`ocaml_unsafe_unroll`) | 411,667 | 1.74x |
| reference | Python (`python`) | 6,479 | 111x |
| start | first OxCaml port, bounds-checked (`oxcaml_safe_plain`) | 170,978 | 4.19x |
| source level | `-unsafe` + 4-row kernel (`oxcaml_unsafe_unroll`) | 433,992 | 1.65x |
| compiler, no safepoints | four Cmm passes (`ox54_licm`) | 573,694 | 1.25x |
| compiler, safepoints on | four passes (`pr_all`) | 475,483 | 1.51x |
| compiler, safepoints on | **+ counted loops (`pr_counted`)** | 553,383 | **1.29x** |
| SIMD | + SSE2 kernel (`pr_simd_counted`) | 567,161 | 1.26x |
| bounds checks kept | release, 4-row kernel (`oxcaml_safe_unroll`) | 348,459 | 2.06x |
| bounds checks kept | PR compiler, counted loops (`pr_safe_counted`) | 292,970 | 2.45x |

Source-level work took OxCaml from 4.19x to 1.65x behind scalar C++ on the 5.4.0-ox7
release; the compiler work took the scalar kernel to 1.29x on a compiler that keeps its
GC safepoints (+30.2% over the same compiler with the passes off, 21/21), and an explicit
SSE2 kernel to 1.26x. With bounds checks kept the pull request is 14.9% slower than the
release (1/21).

## Where things are

```
microgpt.py            the original (training and inference, pure Python)
weights/ data/         the trained weights and the evaluation splits
impl/                  the five ports
  python/infer.py        reference port, explicit loops, no NumPy
  cpp/infer.cpp          C++   (switch: -DMG_UNROLL)
  rust/                  Rust  (switch: Cargo feature `unroll`)
  ocaml/                 one OCaml program, built by the stock compiler ...
  oxcaml/                ... and by OxCaml (switches: MG_UNROLL, MG_SR, MG_SIMD, OCAMLFLAGS)
compiler-patches/      the compiler passes: patches, configurations and build steps
bench/
  variants.py            THE VARIANT REGISTRY: every build, its group and its concept
  bench.py               the benchmark: build, check output, time, summarise per concept
  run.py                 quick cross-platform check of the five shipped ports
tools/                 correctness checks, the poll NOP patcher, the region profiler
report/                the report (LaTeX), with run W's data and scripts in report/data/
BENCHMARK.md           how to run the benchmark, and the numerical contract
PORTING.md             how to add a port without breaking bit-exactness
```

Every optimisation is a **build switch**, never a source edit, so each one can be built
with and without it. Each concept below names its switch, the variants that measure it,
and its effect in run W as a paired median over the 21 rounds with the number of rounds
won. `python3 bench/bench.py --show <variant>` prints the exact build command, and
`python3 bench/bench.py --summarise report/data/run_w_gen.txt` recomputes every effect
from the raw data.

## 1. The ports

One plain-float Python reference ([`impl/python/infer.py`](impl/python/infer.py),
validated against microgpt's own autograd to `1.3e-13`) specifies four compiled ports.
No port uses a library: each hand-rolls its RNG, hash and JSON writer, so the comparison
is between languages. The ports agree exactly because [BENCHMARK.md](BENCHMARK.md)
pins every operation whose result could differ (summation order, `pow` instead of
`1/sqrt`, no FMA, a portable xorshift64* RNG); [PORTING.md](PORTING.md) lists the idioms
that break it.

`impl/ocaml/main.ml` and `impl/oxcaml/main.ml` are the same program (the build asserts it)
and use no OxCaml extensions, so the `ocaml_*` and `oxcaml_*` rows differ only in the
compiler: stock 5.3.0 (closure middle end) against the OxCaml 5.4.0-ox7 release
(flambda2).

**Baselines.** `cpp_novec` (C++ `-O3`, vectoriser off) runs the same four scalar chains
as the OCaml kernel and is the reference every gap is quoted against. `cpp_unroll`, the
shipped C++ build, is auto-vectorised by GCC: +9.5% over scalar (21/21). Rust
(`rust_unroll`, bounds-checked) is 1.02x behind scalar C++.

## 2. Source-level optimisations

On the OxCaml 5.4.0-ox7 release, compiler unchanged.

| optimisation | switch | without -> with | effect |
|---|---|---|---|
| no bounds checks | `OCAMLFLAGS=-O3 -unsafe` | `oxcaml_safe_plain` -> `oxcaml_unsafe_plain` | +61.6% (21/21) |
| | | `oxcaml_safe_unroll` -> `oxcaml_unsafe_unroll` | +25.4% (21/21) |
| 4-row unrolled kernel: four independent accumulators, one load of `x.(i)` per four rows | `MG_UNROLL=1` (default) | `oxcaml_unsafe_plain` -> `oxcaml_unsafe_unroll` | +56.4% (21/21) |
| strength reduction by hand: carry the four row indices | `MG_SR=1` | `oxcaml_unsafe_unroll` -> `oxcaml_unsafe_sr` | +10.3% (21/21) |

The same unroll gives C++ +20.4%, Rust +5.8% and stock OCaml +210.6%: its value depends
on how well each compiler's plain loop already ran. On the plain kernel flambda2 is
+108.5% faster than the closure middle end (`ocaml_unsafe_plain` -> `oxcaml_unsafe_plain`);
on the unrolled kernel the two are close (+4.2%, 15/21). Bounds checks cost OxCaml much
more than stock OCaml on the plain kernel (+61.6% against +10.0% for `-unsafe`).

The shipped OxCaml build is `oxcaml_unsafe_unroll` (`-O3 -unsafe`, 4-row kernel). Hand
strength reduction stays a switch: it shows what the compiler pass of section 3 should
achieve, on source the pass does not need changed.

**Where the remaining gap is.** The region profiler (`tools/profile_regions.py`, report
Figure 6) puts three quarters of it in the four regions dominated by `linear`, whose inner
loop OxCaml 5.2.0+ox compiled to 23 instructions per four multiply-adds against C++'s 15.
The difference is integer bookkeeping: OCaml rebuilds `base + i` for every row on every
iteration (it has no interior pointers), one row base is spilled, and a GC safepoint poll
sits on the back edge.

## 3. Compiler passes

Four passes over Cmm, in `backend/cmm_strength_reduction.ml` of the OxCaml pull request
([`compiler-patches/`](compiler-patches/README.md)). Measured on a ladder of 5.4.0+ox
compilers, each adding one pass, all built without safepoint polls, on the unchanged
shipped source (`-O3 -unsafe`, 4-row kernel).

| pass | patch, flag | without -> with | effect |
|---|---|---|---|
| strength reduction of derived induction variables: `base + i` becomes a loop parameter | 1, `-cmm-strength-reduction` | `ox54_base` -> `ox54_sr` | +13.3% (21/21) |
| interior pointers into array rows: one hoisted address per row, one shared index, in loops that cannot reach the GC | 2, `-cmm-interior-pointers` | `ox54_sr` -> `ox54_ip` | +12.8% (21/21) |
| | | `ox54_ip_off` -> `ox54_ip` (flag only) | +12.8% (21/21) |
| invariant-stride induction variables: the row pointers are carried across the row loop, whose stride `cols` is invariant but not constant | 3, `-cmm-invariant-strides` | `ox54_ip` -> `ox54_ivs` | +4.2% (15/21) |
| carried pointers rather than carried indices | 3, `-cmm-carried-pointers` | `ox54_ivs_noptr` -> `ox54_ivs` | +31.3% (21/21) |
| loop-invariant code motion, register-neutral: hoists only where the operands die | 4, `-cmm-licm` | `ox54_ivs` -> `ox54_licm` | -1.4% (5/21): declines on microgpt, identical code |
| **all four** | | `ox54_base` -> `ox54_licm` | **+31.3% (21/21)** |

With strength reduction and interior pointers the inner loop is 13 instructions per four
multiply-adds, against C++'s 15, and the four passes take the gap from 1.61x to 1.25x.
Carrying indices instead of pointers keeps nine values live and spills in the hot loop,
hence `-no-cmm-carried-pointers` is slower than not applying patch 3 at all. The
unpatched ladder compiler is level with the 5.4.0-ox7 release without polls (+0.1%,
11/21), so against what OxCaml already offers the four passes are worth +31.0%
(`oxcaml_unsafe_unroll_pollfree` -> `ox54_licm`, 21/21).

## 4. Safepoints and counted loops

OxCaml puts a GC poll on every loop back edge, so that a long non-allocating loop can be
interrupted for a signal or a stop-the-world collection.

**What a poll costs** (5.4.0-ox7, 4-row kernel). Overwriting every poll with NOPs in the
linked binary (`tools/nop_polls.py`; `oxcaml_unsafe_unroll_pollnop`) gains +3.9% (19/21);
recompiling with `-disable-poll-insertion` (`oxcaml_unsafe_unroll_pollfree`) gains +4.3%
(14/21). The poll's own cost is small; its real cost is that it stops the pointer passes.

**The passes with safepoints on.** The pull-request compiler is configured like the
release (poll insertion on); flags select the passes. A derived pointer cannot be live
across a poll, so with a poll on every back edge interior and carried pointers cannot form.

| | passes off | four passes | gain from the passes |
|---|---:|---:|---:|
| safepoints on (`pr_off`, `pr_all`) | 1.69x | 1.51x | +10.2% (21/21) |
| no safepoints (`pr_off_nopoll`, `pr_nopoll`) | 1.61x | 1.24x | +28.9% (21/21) |

**Counted loops** (patch 6, `-cmm-counted-loops`). A GC-free loop that provably
terminates, under an exact rule for 64-bit wrapping arithmetic, drops its back-edge poll
and polls once on each exit; where termination is not decided at compile time, one entry
check selects a poll-free copy or the original. Inside such a loop the pointer passes run.

| comparison | without -> with | effect |
|---|---|---|
| the passes with counted loops over passes off | `pr_off` -> `pr_counted` | +30.2% (21/21) |
| counted loops over the four passes | `pr_all` -> `pr_counted` | +16.6% (21/21) |
| counted loops over shipped OxCaml | `oxcaml_unsafe_unroll` -> `pr_counted` | +29.2% (21/21) |
| the pointer passes within counted mode | `pr_counted_noptr` -> `pr_counted` | +13.3% (21/21) |
| no polls at all, against counted | `pr_counted` -> `pr_nopoll` | +1.2% (13/21) |
| unchecked loops (patches 7-8, no termination proof), against counted | `pr_counted` -> `pr_unchecked` | +3.3% (17/21) |
| counted with bounds checks kept, against shipped bounds-checked | `oxcaml_safe_unroll` -> `pr_safe_counted` | -14.9% (1/21) |

Counted loops keep safepoints and are about as fast as removing them, within the run's
resolution (two byte-identical binaries differ by +0.6%, interquartile range
[-0.2, +2.9]%). The cost is latency: another domain waits for a counted loop's exit poll,
which an optional trip cap (`-cmm-counted-loops-max-trips N`) bounds in iterations.
Unchecked loops gain little more and can cost liveness, so they stay opt-in. With bounds
checks kept, the extra live indices make the allocator spill the row pointers, so
`pr_safe_counted` is slower than the release; declining interior pointers where a check
keeps the index live is the missing piece for safe OCaml.

## 5. Explicit SIMD

`MG_SIMD=1` substitutes an SSE2 kernel ([`impl/oxcaml/build.sh`](impl/oxcaml/build.sh),
link stubs in [`impl/oxcaml/simd_stubs.c`](impl/oxcaml/simd_stubs.c)) that puts rows in
vector lanes, two rows per register, so each lane adds the same products in the same
order as the scalar kernel and the output stays bit-identical.

| configuration | scalar -> SSE2 | effect |
|---|---|---|
| OxCaml 5.4.0-ox7 release | `oxcaml_unsafe_unroll` -> `oxcaml_unsafe_simd` | +4.1% (16/21) |
| OxCaml 5.2.0+ox release | `oxcaml52_unsafe_unroll` -> `oxcaml52_unsafe_simd` | +17.1% (21/21) |
| PR compiler, passes off | `pr_off` -> `pr_simd_off` | +15.7% (19/21) |
| PR compiler, safepoints on, passes on | `pr_all` -> `pr_simd` | +0.9% (12/21) |
| PR compiler, counted loops | `pr_counted` -> `pr_simd_counted` | +5.2% (18/21) |
| PR compiler, no polls | `pr_nopoll` -> `pr_simd_nopoll` | +1.8% (14/21) |

SIMD helps most where the passes cannot act. With them it adds little: both remove the
same integer bookkeeping, so the two overlap.

## Measurement controls

| control | builds | result |
|---|---|---|
| matched optimisation level (Rust uses opt-level 3) | `cpp_O2_plain` -> `cpp_plain` | `-O3` +15.3% (21/21) |
| is the SSE-encoded C++ baseline flattering? | `cpp_novec` -> `cpp_novec_avx` | VEX encoding -5.9% (2/21): no, SSE is the harder target |
| resolution of the run (A/A) | `pr_counted` -> `pr_counted_copy` | +0.6%, IQR [-0.2, +2.9]% |

## Running it

```bash
python3 bench/bench.py --set headline     # Linux; ~5 min with every toolchain present
bash tools/bench_variants.sh              # every variant (the same command as before)
python3 bench/bench.py --concept counted  # one concept and what it is compared against
python3 bench/bench.py --summarise report/data/run_w_gen.txt   # run W's effects, no timing
```

Toolchains are optional: a variant whose compiler is missing is skipped. With only
`python3` and `g++` the C++ and Python rows run; OxCaml needs Linux x86-64.
[BENCHMARK.md](BENCHMARK.md) covers prerequisites, the measurement protocol, how to
reproduce run W exactly, and the numerical contract. Correctness checks, independent of
timing:

```bash
python3 tools/validate.py       # reference port against microgpt.py's autograd
python3 bench/run.py --build --check-only   # the five shipped ports agree exactly
python3 tools/test_shapes.py    # agreement on four model shapes, including multi-layer
python3 tools/test_harness.py   # the agreement gate rejects broken reports
python3 tools/baselines.py      # perplexity against unigram and bigram models
```

There are no pretrained weights for this architecture; `weights/microgpt.bin` is the
output of `python3 tools/train_export.py --steps 1000` (deterministic, about 80 s).
