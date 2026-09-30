# AGENT.md — running the variant benchmark

Instructions for an agent asked to run this repo's benchmark. Works on **Linux, macOS and
Windows**; the differences are called out where they matter.

---

## What this is

`microgpt` is a small character-level transformer. This repo ports its **inference** to
five languages — Python, C++, Rust, and OCaml compiled two ways — under a contract strict
enough that every port produces **byte-identical output**. That gate is what makes the
speed numbers mean anything: a variant that is faster but prints something different is a
bug, not an optimization.

The variant matrix goes further: it builds each port at several optimization levels
(`<language>_<optimization>`) and times them against each other, so the table shows how
much of the ranking comes from the language and how much from the effort spent on it.

## The command

```bash
bash tools/bench_variants.sh
```

Run it **from the repo root**. Everything is built into a temp directory; the repo is not
modified. Output is a Markdown table plus paired per-optimization deltas — capture it:

```bash
bash tools/bench_variants.sh 2>&1 | tee matrix.txt
```

**On Windows**, run it inside WSL (see below), not in PowerShell or Git Bash:

```powershell
wsl -d Debian -- bash tools/bench_variants.sh
```

## Before you run: get the machine quiet

Throughput is the measurement. Anything else using the CPU corrupts it, and the failure is
silent — you get plausible-looking numbers that are simply wrong.

- Close other work. No compiles, no test suites, no video calls.
- On a laptop, plug it in. Battery governors throttle sustained single-threaded load.
- If you just finished a build, **wait** for the load average to settle (Linux/macOS:
  `uptime`; want < 1.0) before starting.

The tell-tale of a contaminated run is a standard deviation that is a large fraction of the
median, and paired columns reading 5/9 or 6/9 instead of 9/9. If you see that, stop and
re-run on a quiet machine rather than reporting it.

## Prerequisites, and what you get without them

Every toolchain is optional. Missing ones are reported as `SKIPPED`/`FAILED` and the rest
of the matrix still runs — so **run it with whatever is installed first**, then add
toolchains if more coverage is wanted.

| toolchain | gives you | notes |
|---|---|---|
| `python3` | `python` | required — also drives the harness itself |
| `g++` (or `clang++` aliased) | `cpp_O2_plain`, `cpp_plain`, `cpp_unroll` | any C++20 compiler |
| `cargo` | `rust_plain`, `rust_unroll` | rustup; no crates needed |
| opam switch `5.2.0+ox` | the four `oxcaml_*` rows, plus `_sr` / `_pollfree` | **Linux x86-64 only** |
| any non-flambda2 `ocamlopt` on `PATH` | the four `ocaml_*` rows, plus `ocaml_unsafe_sr` | stock OCaml; works on macOS |
| custom-built compilers | the four `ox54_*` rows | see `compiler-patches/README.md`; optional |

**A minimal useful run needs only `python3` and `g++`.**

### Linux

Everything works natively. This is the reference platform.

### macOS

C++, Rust, Python and stock OCaml all work. Two differences:

- **OxCaml does not run on macOS** — it targets linux-x86-64. The `oxcaml_*` and `ox54_*`
  rows will be skipped. The `ocaml_*` rows still work via a normal opam switch.
- **No CPU pinning.** `taskset` is Linux-only and macOS exposes no shell equivalent. The
  script detects this, warns, and runs unpinned. Expect more variance; prefer the paired
  "faster in N/M rounds" columns over the absolute tok/s.

### Windows

The benchmark must run inside **WSL2**, not PowerShell or Git Bash. Comparing a
Windows-native binary against a WSL one measures the OS rather than the language, and the
OCaml ports cannot be built natively at all.

```powershell
wsl --install -d Debian          # if WSL is not set up yet
wsl -d Debian -- bash -c "sudo apt update && sudo apt install -y g++ python3 git"
wsl -d Debian -- bash tools/bench_variants.sh
```

Two Windows-specific traps when driving this from a shell:

- **Git Bash rewrites Unix paths.** `/tmp/foo` silently becomes `C:/Program Files/Git/tmp/foo`.
  Prefix with `MSYS_NO_PATHCONV=1`, or drive WSL from PowerShell instead.
- **PowerShell mangles embedded quotes** passed through `wsl.exe -- bash -c "..."`. For
  anything non-trivial, write a `.sh` file and run `wsl -d Debian -- bash that-file.sh`.

## How long it takes

Roughly **10–20 minutes** with all toolchains present: a couple of minutes of builds, then
23 variants × 9 rounds of timed runs. Tune with environment variables:

```bash
ROUNDS=15 bash tools/bench_variants.sh        # more rounds, tighter statistics
ROUNDS=3 BUDGET=0.2 bash tools/bench_variants.sh   # quick smoke test, do not quote these
MODES="gen ppl" bash tools/bench_variants.sh  # also run the perplexity path
PIN=-1 bash tools/bench_variants.sh           # disable pinning explicitly
```

## Reading the output

Three sections, in order.

**1. Correctness gate.** Every variant's output hash and perplexity. It must end with:

```
ALL IDENTICAL - differences below are real work saved
```

If it says `*** VARIANTS DISAGREE ***`, **stop**. Do not report timings — a variant is
miscompiling, and that is the finding. The expected values are
`0xae6c6ffbd8f5b02c` and `10.789614873329409`.

**2. The matrix.** Median tok/s per variant, with standard deviation and ratios.

**3. Paired deltas.** Each optimization against the step before it, on the same rounds,
with "faster in N/M rounds". **This is the part to trust.** A median difference with 9/9
rounds won is real; the same difference at 5/9 is noise. Quote these rather than
subtracting two numbers from the matrix.

## Rules for reporting

- **Never mix runs.** Numbers from two different invocations are not comparable — the
  machine's thermal and frequency state differs. Every figure you quote must come from one
  table.
- **Absolute tok/s are machine-specific.** Ratios and paired deltas travel; raw throughput
  does not.
- **`ox54_*` are a different compiler** (locally built 5.4.0+ox) from the `oxcaml_*` rows
  (the pinned 5.2.0+ox switch). Comparing across those two families is a compiler-version
  difference, not an optimization one. Only compare within a family.
- **`cpp_unroll` vectorizes; no OCaml variant does.** For a like-for-like scalar
  comparison, build C++ with `-fno-tree-vectorize` — worth about 7% to C++ here.
- Report what you measured. If a toolchain was missing and rows were skipped, say which.

## If something fails

| symptom | cause |
|---|---|
| `weights/microgpt.bin missing` | you are not in the repo root |
| every `oxcaml_*` says FAILED | no `5.2.0+ox` opam switch — expected off Linux |
| `ocaml_*` FAILED with "refusing to build" | the `ocamlopt` on `PATH` is a flambda2 build; set `MG_OCAML_SWITCH` to a stock switch |
| all `ox54_*` SKIPPED | the patched compilers are not built; see `compiler-patches/README.md`. Expected, and fine |
| huge standard deviations, paired columns near 50% | something else is using the CPU; re-run quiet |
| hangs on a build | a first Rust build can take several minutes; give it time before killing it |

## Deeper documentation

- `README.md` — what the project is and the headline results
- `BENCHMARK.md` — the contract every port implements: weight format, numerics rules, RNG, CLI
- `PORTING.md` — the twelve traps that bite when adding a port, plus golden values
- `OPTIMIZATIONS.md` — every optimization with before/after numbers, and what did not work
- `compiler-patches/README.md` — the two compiler passes and how to build them

Other tools, none needed for the matrix: `tools/bench_wsl.sh` (five shipped ports, one
Linux environment), `tools/profile_regions.py` (where the cycles go, per region),
`tools/track_opt.py` (A/B two binaries), `tools/bench_polls.sh` (cost of OCaml's GC polls).
