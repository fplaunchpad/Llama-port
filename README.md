# llamaport

[Karpathy's microgpt](microgpt.py) ported to **C++, Rust and OxCaml**, benchmarked against
the Python original on **token generation speed** and **held-out perplexity**.

All four implementations load the same weights and produce **bit-identical output** — the
same perplexity to the last digit, and byte-for-byte identical generated text. The speed
differences are therefore real work saved, not corners cut.

```
python  mana analen aris sanar anan jaria lielia gahela anare alica
cpp     mana analen aris sanar anan jaria lielia gahela anare alica
rust    mana analen aris sanar anan jaria lielia gahela anare alica
oxcaml  mana analen aris sanar anan jaria lielia gahela anare alica
```

## Results

All four built with matched optimization levels and timed in one Linux environment,
pinned with `taskset`, 11 interleaved rounds:

| impl | runtime | gen tok/s | vs Python | perplexity |
|---|---|---:|---:|---|
| **cpp** | g++ 14.2 `-O3` | 745,823 | **121x** | 10.789614873329409 |
| **rust** | rustc 1.98.1 `--release` | 654,331 | **106x** | 10.789614873329409 |
| **oxcaml** | ocamlopt 5.2.0+ox `-O3 -unsafe` | 320,632 | **52x** | 10.789614873329409 |
| **python** | CPython 3.13.5 | 6,179 | 1.0x | 10.789614873329409 |

For context on the model's quality: uniform guessing scores 27.0 perplexity, a bigram count
table 12.33, and this model 10.79.

## Quick start

There are **no pretrained weights to download** — none exist for this architecture. Training
is a one-time ~80 second job, and nothing ever trains again:

```bash
python tools/train_export.py --steps 1000      # writes weights/microgpt.bin
python bench/run.py --build                    # build + verify + benchmark
```

The full uniform benchmark, including OxCaml (which needs Linux):

```bash
wsl -d Debian -- bash tools/bench_wsl.sh          # from the repo root
```

And the optimization-wise matrix — every `<language>_<optimization>` variant, built from
real build switches and timed together:

```bash
wsl -d Debian -- bash tools/bench_variants.sh     # from the repo root
```

## What you can actually reproduce

The four ports need different toolchains, so here is the honest picture:

| you have | you can run |
|---|---|
| **Python 3.12+ only** (no packages) | the reference port, the full correctness suite against it, the perplexity baselines, and training |
| **+ a C++ compiler** | the C++ port and a real two-way speed comparison |
| **+ Rust** (`rustup`) | the three-way comparison |
| **+ OxCaml** (opam switch `5.2.0+ox`, Linux x86-64) | all four, and `tools/bench_variants.sh` |

**OxCaml is the awkward one.** It is a Jane Street compiler variant installed through a
dedicated opam switch and it targets linux-x86-64, so on Windows it needs WSL. If you do not
have it, everything else still works — `bench/run.py` and `tools/test_shapes.py` skip any
implementation they cannot find and tell you so, rather than failing.

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
| [impl/oxcaml/main.ml](impl/oxcaml/main.ml) | OCaml/OxCaml port, stdlib only (767 lines) |
| [bench/run.py](bench/run.py) | harness: builds, runs, enforces agreement, prints the table |
| [tools/bench_wsl.sh](tools/bench_wsl.sh) | uniform benchmark, everything in one Linux environment |
| [tools/bench_variants.sh](tools/bench_variants.sh) | optimization-wise matrix, every variant of every port |
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

## Three findings worth knowing

**Agreeing outputs are not proof of a correct port.** Two genuine bugs produced identical
output anyway, because the divergences never flipped a discrete sampling decision. Verify the
arithmetic, not just the answer.

**Your language's `sum()` is probably not a plain running total.** CPython ≥3.12 uses Neumaier
compensated summation for floats, so the Python reference was computing different arithmetic
from the compiled ports — 141 of 214 dot products differed. It hid under a 1e-12 tolerance
for an entire round of benchmarking.

**Compilers do less instruction-level parallelism than you'd assume.** Unrolling the matrix
multiply four ways by hand is worth +61% in OCaml, +21.6% in C++ and +5.1% in Rust — a direct
measure of how much each backend was already extracting. That single change flipped the
ranking between C++ and Rust.
