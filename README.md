# llamaport

[Karpathy's microgpt](microgpt.py) ported to **C++, Rust, OxCaml and plain OCaml**,
benchmarked against the Python original on **token generation speed** and **held-out
perplexity**.

All five implementations load the same weights and produce **bit-identical output** — the
same perplexity to the last digit, and byte-for-byte identical generated text. The speed
differences are therefore real work saved, not corners cut.

```
python  mana analen aris sanar anan jaria lielia gahela anare alica
cpp     mana analen aris sanar anan jaria lielia gahela anare alica
rust    mana analen aris sanar anan jaria lielia gahela anare alica
oxcaml  mana analen aris sanar anan jaria lielia gahela anare alica
ocaml   mana analen aris sanar anan jaria lielia gahela anare alica
```

The last two are the same OCaml source compiled twice — by Jane Street's OxCaml variant and
by the stock upstream compiler — so that one row of the table is a **compiler** measurement
with the language held fixed.

## Results

All five built with matched optimization levels and timed in one Linux environment,
pinned with `taskset`, 9 interleaved rounds:

| impl | runtime | gen tok/s | vs Python | perplexity |
|---|---|---:|---:|---|
| **cpp** | g++ 14.2 `-O3` | 732,253 | **115x** | 10.789614873329409 |
| **rust** | rustc 1.98.1 `--release` | 671,684 | **106x** | 10.789614873329409 |
| **oxcaml** | ocamlopt 5.2.0+ox `-O3 -unsafe` (flambda2) | 407,168 | **64x** | 10.789614873329409 |
| **ocaml** | ocamlopt 5.3.0 `-unsafe` (closure) | 402,971 | **64x** | 10.789614873329409 |
| **python** | CPython 3.13.5 | 6,348 | 1.0x | 10.789614873329409 |

For context on the model's quality: uniform guessing scores 27.0 perplexity, a bigram count
table 12.33, and this model 10.79.

## Quick start

There are **no pretrained weights to download** — none exist for this architecture. Training
is a one-time ~80 second job, and nothing ever trains again:

```bash
python tools/train_export.py --steps 1000      # writes weights/microgpt.bin
python bench/run.py --build                    # build + verify + benchmark
```

The full uniform benchmark, including the two OCaml builds (which need Linux):

```bash
wsl -d Debian -- bash tools/bench_wsl.sh          # from the repo root
```

And the optimization-wise matrix — every `<language>_<optimization>` variant, built from
real build switches and timed together:

```bash
wsl -d Debian -- bash tools/bench_variants.sh     # from the repo root
```

## What you can actually reproduce

The five ports need different toolchains, so here is the honest picture:

| you have | you can run |
|---|---|
| **Python 3.12+ only** (no packages) | the reference port, the full correctness suite against it, the perplexity baselines, and training |
| **+ a C++ compiler** | the C++ port and a real two-way speed comparison |
| **+ Rust** (`rustup`) | the three-way comparison |
| **+ OCaml** (any stock opam switch, or a distro `ocamlopt`) | the four-way comparison |
| **+ OxCaml** (opam switch `5.2.0+ox`, Linux x86-64) | all five, and `tools/bench_variants.sh` |

**OxCaml is the awkward one.** It is a Jane Street compiler variant installed through a
dedicated opam switch and it targets linux-x86-64, so on Windows it needs WSL. The plain
OCaml port is far easier — any `ocamlopt` will do, including the one in your distro's
packages — but it is built under WSL here anyway, so that the two OCaml rows are timed in
the same environment and stay comparable to each other. If you have neither, everything else
still works: `bench/run.py` and `tools/test_shapes.py` skip any implementation they cannot
find and tell you so, rather than failing.

Nothing here needs a GPU, a network connection (after the first run downloads the corpus, and
`input.txt` is committed so even that is optional), or any third-party library. Every port is
dependency-free by design.

Two notes on the numbers. Speed figures come from *this* machine (Core Ultra 7 155H, a mobile
hybrid CPU) and will differ on yours; the **ratios** are the portable part. And correctness is
platform-independent — verified by building the same C++ source under Windows UCRT and Linux
glibc and getting bit-identical output — so the golden values in
[PORTING.md](PORTING.md) should reproduce exactly for you even though the timings will not.

## Layout

| path | what |
|---|---|
| [microgpt.py](microgpt.py) | the original, untouched — trains and infers in pure Python |
| [impl/python/infer.py](impl/python/infer.py) | reference port: plain floats, no autograd, no numpy (480 lines) |
| [impl/cpp/infer.cpp](impl/cpp/infer.cpp) | C++ port, no dependencies (821 lines) |
| [impl/rust/src/main.rs](impl/rust/src/main.rs) | Rust port, no crates (1,074 lines) |
| [impl/oxcaml/main.ml](impl/oxcaml/main.ml) | OCaml port, stdlib only (782 lines) — built by OxCaml, flambda2 |
| [impl/ocaml/main.ml](impl/ocaml/main.ml) | the same source, built by the stock compiler; `build.sh` asserts they stay in sync |
| [bench/run.py](bench/run.py) | harness: builds, runs, enforces agreement, prints the table |
| [tools/bench_wsl.sh](tools/bench_wsl.sh) | uniform benchmark, everything in one Linux environment |
| [tools/bench_variants.sh](tools/bench_variants.sh) | optimization-wise matrix, every variant of every port |
| [tools/profile_regions.py](tools/profile_regions.py) | region profiler: where the cycles go, and where each port loses |
| [tools/bench_polls.sh](tools/bench_polls.sh) | prices OCaml's GC safepoint polls, two independent ways |
| [tools/nop_polls.py](tools/nop_polls.py) | overwrites GC polls with NOPs in a linked binary (diagnostic only) |
| [tools/train_export.py](tools/train_export.py) | trains microgpt and exports the weight file |

Every port is dependency-free on purpose — each hand-rolls its own SHA-256, RNG and JSON
writer. Pulling in libraries would compare libraries instead of languages.

## Docs

- **[BENCHMARK.md](BENCHMARK.md)** — the contract. Weight file format, the numerics rules,
  the RNG, the CLI and JSON shape. Read this to add a port.
- **[PORTING.md](PORTING.md)** — what actually goes wrong. Twelve traps, ranked by how likely
  they are to bite, plus golden reference values to check against.
- **[OPTIMIZATIONS.md](OPTIMIZATIONS.md)** — every optimization to every port, with
  before/after numbers and what didn't work.

## Verification

Correctness is checked, not assumed:

```bash
python bench/run.py --check-only    # 10 assertions across every implementation
python tools/test_shapes.py         # agreement across 4 model shapes, incl. multi-layer
python tools/validate.py            # reference vs microgpt.py's own autograd graph
python tools/test_harness.py        # 14 tests that the correctness gate catches bugs
python tools/baselines.py           # perplexity vs unigram/bigram baselines
```

The strong check is an FNV-1a hash of the generated text: it can only match if the forward
pass, softmax, temperature division, RNG *and* sampling scan all agree. Seven real defects
were caught this way, two of which had already survived a full green benchmark run.

## Four findings worth knowing

**Agreeing outputs are not proof of a correct port.** Two genuine bugs produced identical
output anyway, because the divergences never flipped a discrete sampling decision. Verify the
arithmetic, not just the answer.

**Your language's `sum()` is probably not a plain running total.** CPython ≥3.12 uses Neumaier
compensated summation for floats, so the Python reference was computing different arithmetic
from the compiled ports — 141 of 214 dot products differed. It hid under a 1e-12 tolerance
for an entire round of benchmarking.

**Compilers do less instruction-level parallelism than you'd assume.** Unrolling the matrix
multiply four ways by hand is worth +221% under stock OCaml, +54% under OxCaml, +19% in C++
and +5% in Rust — a direct measure of how much each backend was already extracting. That
single change flipped the ranking between C++ and Rust.

**A better compiler and a better loop buy the same thing, and you only get paid once.** On
the plain kernel, OxCaml's flambda2 is **2.1x** faster than the stock OCaml compiler on
byte-identical source. On the hand-unrolled kernel that lead collapses to a few percent,
winning only 6 of 9 rounds — indistinguishable from noise. The unroll hands the closure
backend the instruction-level parallelism flambda2 was finding on its own, and the advanced
compiler has nothing left to add. Which of those two numbers you quote decides whether
flambda2 looks transformative or irrelevant.

**A GC safepoint poll can cost a register rather than an instruction.** Dropping OCaml's
back-edge poll is worth **+14.3%** on the shipped OxCaml build — but overwriting the very
same poll instructions with NOPs in the linked binary is worth **+0.1%**. The cost is not
what the poll executes; it is that no value may live in `%r11` across one, which in the
register-starved unrolled kernel forces a stack spill reloaded every iteration.
