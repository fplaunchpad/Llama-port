# Benchmark

Part A says how to run the benchmark and what it measures. Part B is the contract every
port implements, which is what makes all five produce bit-identical output.

# Part A: running the benchmark

## The command

```bash
python3 bench/bench.py              # every variant this machine can build
bash tools/bench_variants.sh        # the same run, under the original script name
```

Run it on a quiet machine (no compiles or other load; on a laptop, plugged in). It builds
every variant into a temporary directory, checks that each one reproduces the reference
output, then times them in interleaved rounds and prints, per concept, what each
optimisation is worth. The repository is not modified. To keep the output:

```bash
python3 bench/bench.py 2>&1 | tee matrix.txt
```

Useful selections and knobs (the environment variables work for both commands):

```bash
python3 bench/bench.py --set headline          # headline | ablation | control | all
python3 bench/bench.py --concept counted,simd  # these concepts and what they are compared to
python3 bench/bench.py --only cpp_novec,oxcaml_unsafe_unroll
python3 bench/bench.py --build-only            # build and check output, no timing
ROUNDS=3 BUDGET=0.2 python3 bench/bench.py     # quick smoke run; do not quote these numbers
MODES="gen ppl" python3 bench/bench.py         # also time the perplexity path
PIN=-1 python3 bench/bench.py                  # no CPU pinning
python3 bench/bench.py --list                  # the registry, with every build command
python3 bench/bench.py --show pr_counted       # how one variant is built
```

| knob | default | meaning |
|---|---|---|
| `ROUNDS` / `--rounds` | 9 | interleaved rounds; each measures every variant once |
| `REPEATS` / `--repeats` | 3 | timed passes per measurement, in one fresh process; the best is kept |
| `BUDGET` / `--budget` | 0.3 | seconds per timed pass |
| `SAMPLES` / `--samples` | 200 | names generated per pass (the reference hash assumes 200) |
| `MODES` / `--modes` | `gen` | `gen`, `ppl`, or `"gen ppl"` |
| `PIN` / `--pin` | 0 | logical CPU for `taskset`; `-1` disables pinning |
| `OUTDIR` / `--out` | `<tmp>/microgpt-bench` | binaries, build logs, `hashes.txt` and the raw `t_<mode>.txt` |

## Platforms and prerequisites

Every toolchain is optional; a variant whose toolchain or compiler is missing is reported
as `SKIPPED` or `FAILED` (with a build log) and the rest runs.

| toolchain | variants |
|---|---|
| `python3` (required; also runs the harness) | `python` |
| `g++` or clang as `g++` | `cpp_*` (`cpp_novec_avx` needs x86-64) |
| `cargo` | `rust_*` |
| a stock `ocamlopt` on `PATH`, or `MG_OCAML_SWITCH=<opam switch>` | `ocaml_*` |
| OxCaml 5.4.0-ox7, opam package `oxcaml-compiler.5.4.0-ox7` (Linux x86-64; `MG_OX_RELEASE`) | `oxcaml_*` (the `_pollnop` builds also need `objdump`) |
| opam switch `5.2.0+ox` (Linux x86-64) | `oxcaml52_*` |
| the locally built compilers of [compiler-patches/](compiler-patches/README.md) | `ox54_*`, `pr_*` |
| OCaml 5.3.0 with the passes ported (`MG_OCAML_PR`) | `ocaml_pr_*` |

**Linux** is the reference platform; everything runs. **macOS**: C++, Rust, Python and
stock OCaml run; OxCaml targets Linux x86-64, so the OxCaml variants are skipped (its build
script refuses a non-OxCaml compiler rather than mislabelling a stock build). macOS has no
`taskset`, so the run is unpinned: prefer the paired "rounds won" figures to absolute
tokens/s. **Windows**: run inside WSL (`wsl -d Debian -- python3 bench/bench.py`), where
the OCaml compilers live, so that every variant is timed in the same environment. From
Git Bash, prefix `MSYS_NO_PATHCONV=1` so Unix paths reach WSL unchanged.

## Reading the output

1. **Correctness gate.** Every variant's output hash and perplexity. With the default
   settings both must equal the reference, `0xae6c6ffbd8f5b02c` and `10.789614873329409`,
   and the gate ends with `ALL IDENTICAL`. A variant that differs is not timed and the
   command exits non-zero: a faster build with different output is a bug.
2. **The table.** Median tokens/s per variant, its interquartile range across rounds, the
   gap to scalar C++ (`cpp_novec` / variant) and the speed-up over Python.
3. **Effects by concept.** Each comparison from `bench/variants.py`: the median per-round
   change of the second build over the first, its interquartile range, and the rounds it
   won. These paired figures are the ones to quote: a difference that wins 20 of 21
   rounds is real, one that wins 11 is noise. Absolute tokens/s depend on the machine;
   ratios and paired effects travel.

Numbers from two invocations are not comparable (thermal and frequency state differ), so
every figure quoted together should come from one run.

## The variant registry

[`bench/variants.py`](bench/variants.py) is the single definition of every build: name,
group, concept, description and build recipe. The names are those of the report and of
run W, in run W's measurement order. Groups:

- **headline**: the reference builds and one build per optimisation step (25);
- **ablation**: a headline build with one thing switched off or on, to price it (34);
- **control**: builds that test the measurement rather than an optimisation (3).

| concept | headline | ablation | control |
|---|---|---|---|
| ports and baselines | `python`, `cpp_unroll`, `cpp_novec`, `rust_unroll`, `ocaml_unsafe_unroll` | | |
| `-unsafe` | `oxcaml_safe_plain`, `oxcaml_unsafe_plain` | `oxcaml_safe_unroll` | |
| 4-row unrolled kernel | `oxcaml_unsafe_unroll` | `cpp_plain`, `rust_plain` | |
| flambda2 against closure (same source) | | `ocaml_safe_plain`, `ocaml_safe_unroll`, `ocaml_unsafe_plain` | |
| strength reduction by hand (`MG_SR=1`) | `oxcaml_unsafe_sr` | `oxcaml_unsafe_sr_pollfree`, `ocaml_unsafe_sr` | |
| safepoint polls, release compiler | | `oxcaml_unsafe_{plain,unroll}_pollnop`, `oxcaml_unsafe_{plain,unroll}_pollfree` | |
| compiler pass: strength reduction | `ox54_base`, `ox54_sr` | | |
| compiler pass: interior pointers | `ox54_ip` | `ox54_ip_off` | |
| compiler pass: invariant strides | `ox54_ivs` | `ox54_ivs_noptr` | |
| compiler pass: LICM | `ox54_licm` | | |
| passes with safepoints on | `pr_off`, `pr_all` | `pr_off_nopoll`, `pr_nopoll` | |
| counted and unchecked loops | `pr_counted` | `pr_counted_noptr`, `pr_unchecked`, `pr_safe_counted` | |
| explicit SIMD (`MG_SIMD=1`) | `oxcaml_unsafe_simd`, `pr_simd` | `pr_simd_off`, `pr_simd_counted`, `pr_simd_nopoll` | |
| the pass ladder with counted loops | `pr_c_off`, `pr_c_sr`, `pr_c_ip`, `pr_c_ivs` | | |
| the passes on stock OCaml 5.3.0 | `ocaml_pr_all`, `ocaml_pr_counted` | `ocaml_pr_off` | |
| release upgrade, 5.2.0+ox to 5.4.0-ox7 | | every `oxcaml52_*` | |
| measurement controls | | | `cpp_O2_plain`, `cpp_novec_avx`, `pr_counted_copy` |

Name parts: language (`cpp`, `rust`, `ocaml` stock (`ocaml_pr` with the ported passes), `oxcaml` 5.4.0-ox7 release,
`oxcaml52` 5.2.0+ox release, `ox54`
ladder compilers built without polls, `pr` pull-request compiler with polls), then safety
(`safe` keeps bounds checks, `unsafe` uses `-unsafe`), kernel (`plain` or 4-row `unroll`)
and modifiers (`_sr` hand strength reduction, `_simd` SSE2 kernel, `_pollfree`
`-disable-poll-insertion`, `_pollnop` polls overwritten in the binary, `_nopoll` the same
flag on the PR compiler, `_off` passes off, `_c_` counted loops with the passes added one at a time, `_noptr` no interior or carried pointers).
`python3 bench/bench.py --list` prints every row with its build command. No variant has
been renamed; `ALIASES` in `bench/variants.py` is where an old name would map to a new one.

## Reproducing run W

Run W is the run behind every microgpt number in the report: 62 variants, 21 rounds, both
modes, pinned to CPU 0, in WSL Debian on an Intel Core Ultra 7 155H, with g++ 14.2,
rustc 1.98.1, stock OCaml 5.3.0 and a copy with the passes ported, OxCaml 5.4.0-ox7 and
5.2.0+ox, the ladder and pull-request compilers of
[compiler-patches/](compiler-patches/README.md) and CPython 3.13.5. The same run:

```bash
SETTLE=300 OUTDIR=/tmp/mgw python3 bench/bench.py --set all --rounds 21 --modes "gen ppl"
```

Its raw output, `/tmp/mgw/t_gen.txt` and `t_ppl.txt`, has the format of
`report/data/run_w_gen.txt` and `run_w_ppl.txt`; copying them there and following
`report/data/README.md` refreshes every number and figure in the report. To see run W's
effects without timing anything:

```bash
python3 bench/bench.py --summarise report/data/run_w_gen.txt report/data/run_w_ppl.txt
```

`bench/bench.py` runs the report's protocol (output gate with
`--mode all --repeats 1 --time-budget 0.05`; then per round and variant one fresh process,
`taskset -c 0`, `--repeats 3 --time-budget 0.3`, 200 samples, seed 1234, temperature 0.5).
One difference: a variant whose output differs is excluded from timing instead of being
flagged. The region profiles of report Figure 6 come from

```bash
python3 tools/profile_regions.py --rounds 7 --impls cpp,cpp_novec,oxcaml,ox54_ivs,ox54_ip,pr_counted
```

## The protocol, and why

Each rule addresses an effect of 1.5x to 3x on a hybrid laptop CPU, larger than most of
the differences being measured.

**Equal time, not equal work.** A process's throughput depends on how long it has been
running (the same forward pass measured 3,449 tokens/s in a 0.7 s workload and 1,601 in a
23 s one), so every measurement runs for the same `--time-budget` and reports a rate.

**Pinning.** A scheduler can move sustained single-threaded work to an efficiency core,
2-3x slower for scalar floating point. `taskset -c 0` keeps it on a performance core.

**One process per measurement.** Generation and perplexity run in separate processes:
in one process, whichever runs second is slower in every language.

**Best of N, interleaved rounds, paired deltas.** Interference only ever slows a run, so
the fastest repeat is kept. Each round measures every variant once, so slow drift affects
all of them alike, and an optimisation's effect is its median per-round change against the
build it modifies. Run W's A/A control (two byte-identical binaries) bounds the resolution
at about 3%.

**Cross-check.** Generation and perplexity run the same forward pass, so their throughputs
must agree within a variant; when they do not, the measurement is at fault.

This model is tiny (4,192 weights, all in L1), so the benchmark measures per-operation
overhead, not memory bandwidth. The format, contract and harness are shape-agnostic: a
wider model (`tools/train_export.py --n-embd 64 --n-layer 4`) runs unchanged.

# Part B: the contract

Five implementations of the same inference algorithm, measured on **token generation
speed** and **held-out perplexity**, loading **identical weights**. A port that follows
this contract can be added to `bench/run.py` and `bench/variants.py`; see
[PORTING.md](PORTING.md) for what goes wrong in practice.

## 1. There are no pretrained weights to download

`microgpt.py` is a from-scratch teaching file. Its "model" is 4,192 numbers produced by a
random init plus 1,000 Adam steps, and its architecture is bespoke (1 layer, `n_embd=16`,
`block_size=16`, 4 heads, vocab 27, rmsnorm instead of layernorm, no biases, ReLU instead of
GeLU). No checkpoint for it exists publicly, and no unrelated checkpoint is shape-compatible.

Training is a **one-time, deterministic, ~80 second** job:

```bash
python tools/train_export.py --steps 1000
```

`tools/train_export.py` is a faithful copy of microgpt.py's math, RNG call order and
optimizer, so it produces exactly the weights microgpt.py would hold when its own training
loop ends, and writes them to `weights/microgpt.bin`. All five implementations are
inference-only and read that file.

Checkpoint: 1,000 steps, train loss 3.37 -> 2.32, held-out perplexity 10.79 (uniform
baseline 27.0, unigram 17.00, bigram 12.33; `python tools/baselines.py`).

## 2. Weight file format: `microgpt-bin-v1`

Little-endian throughout. `weights/config.json` mirrors all of this in readable form,
including a sha256 and checksums for load verification.

| Offset | Type | Field |
|---|---|---|
| 0 | `char[4]` | magic `"MGPT"` |
| 4 | `u32` | format version (`1`) |
| 8 | `u32` | `n_layer` |
| 12 | `u32` | `n_embd` |
| 16 | `u32` | `block_size` |
| 20 | `u32` | `n_head` |
| 24 | `u32` | `vocab_size` |
| 28 | `u32` | `n_uchars` |
| 32 | `u8[n_uchars]` | vocabulary, ASCII, ascending; token id = index |
| … | `u8[]` | zero padding to the next multiple of 8 (`payload_offset`) |
| `payload_offset` | `f64[]` | all tensors, in the order below, row-major |

`bos_token_id == n_uchars` (there is no character for it), and `vocab_size == n_uchars + 1`.
`head_dim == n_embd / n_head`.

Tensor order: read them back-to-back in exactly this sequence, with `E = n_embd`,
`V = vocab_size`, `B = block_size`:

1. `wte` `[V][E]`
2. `wpe` `[B][E]`
3. `lm_head` `[V][E]`
4. then, for each layer `i` in `0..n_layer`:
   `attn_wq [E][E]`, `attn_wk [E][E]`, `attn_wv [E][E]`, `attn_wo [E][E]`,
   `mlp_fc1 [4E][E]`, `mlp_fc2 [E][4E]`

With the defaults that is 4,192 f64 values = 33,536 payload bytes, 33,600 total.

**Load check.** Sum all weights left-to-right in file order and compare against
`weights_sum` / `weights_abs_sum` in `config.json`. A port that gets these wrong has a
layout bug, and everything downstream is meaningless.

## 3. Numerics contract

All implementations compute in **f64** and apply operations in the same order, so that
perplexity agrees to the last digit rather than merely "close enough":

```
linear(x, W)[o]  = accumulate acc = 0.0; for i in 0..nin: acc += W[o][i] * x[i]
                   (ascending i, sequential, no reassociation, no FMA contraction)

rmsnorm(x)       = ms = (accumulate x[i]*x[i], ascending) / len(x)
                   scale = pow(ms + 1e-5, -0.5)      // pow, not 1/sqrt
                   out[i] = x[i] * scale

softmax(z)       = m = max(z)
                   e[i] = exp(z[i] - m)
                   total = accumulate e[i], ascending
                   out[i] = e[i] / total

attention        = logits[t] = (accumulate q_h[j]*k_h[t][j], ascending j) / pow(head_dim, 0.5)
                   weights   = softmax(logits)
                   out[j]    = accumulate weights[t]*v_h[t][j], ascending t

relu(x)          = x > 0.0 ? x : 0.0
                   (written this way round: `if x <= 0 { x = 0 }` looks equivalent but
                    leaves NaN untouched, where this maps NaN to 0.0)
temperature      = z[i] / temperature        // divide; do NOT precompute 1/temperature
```

Forward pass per token, matching `microgpt.py`:

```
x = wte[token] + wpe[pos]
x = rmsnorm(x)
for each layer:
    r = x;  x = rmsnorm(x)
    q,k,v = linear(x, wq), linear(x, wk), linear(x, wv)
    append k,v to this layer's KV cache
    per head: causal attention over the whole cache, concatenated
    x = linear(concat, wo);  x = x + r
    r = x;  x = rmsnorm(x)
    x = linear(x, fc1);  x = relu(x);  x = linear(x, fc2);  x = x + r
logits = linear(x, lm_head)
```

The 4-row unrolled kernels compute four output rows at once, each still summed in
ascending order, and the SSE2 kernel puts rows, not elements, in vector lanes; both are
the same arithmetic as `linear` above.

**Beware your language's `sum()`.** "Plain sequential accumulation" is a real constraint.
CPython has used Neumaier *compensated* summation for floats since 3.12, so
`sum(w*x for ...)` is more accurate than a running total: on this checkpoint it changes
**141 of 214** dot products and shifts `weights_sum` by 5e-15. The Python reference
therefore uses explicit `acc += ...` loops. Rust's `iter().sum::<f64>()` is a plain fold
and is fine; `f64::mul_add` is not, as it fuses. If a port's `weights_sum` does not match
`config.json` **exactly**, this is the first thing to suspect.

**Compiler flags: no fast-math, and matched optimisation levels.** `-ffast-math` /
`-Ofast` reassociate sums and break cross-language agreement. C++ is built with
`-O3 -fno-fast-math -ffp-contract=off`, Rust with plain `--release`. `-O3` rather than
`-O2` because Rust's release profile is `opt-level = 3`; in run W `-O3` is worth +15.3%
to C++ (`cpp_O2_plain` -> `cpp_plain`), so comparing `-O2` C++ with Rust measures the flag.

`tools/validate.py` checks the Python reference against microgpt.py's own autograd graph:
1.3e-13 largest relative logit difference (microgpt.py divides through a reciprocal), and
identical NLL to 15 digits.

## 4. RNG and sampling

Sampling must be reproducible across languages, so the benchmark defines its own generator
rather than using each language's stdlib. **xorshift64\***, all arithmetic wrapping mod 2^64:

```
init:  state = seed != 0 ? seed : 0x9E3779B97F4A7C15

next_u64():
    x = state
    x ^= x >> 12
    x ^= (x << 25)          // wrapping
    x ^= x >> 27
    state = x
    return x * 0x2545F4914F6CDD1D    // wrapping

next_f64():
    return (next_u64() >> 11) * (1.0 / 9007199254740992.0)   // 2^-53, in [0,1)
```

Rust: `<<` on `u64` is fine, but write `wrapping_mul` for the multiply. C++: `uint64_t`
arithmetic already wraps.

Sanity vector: seed `1234`; the first four `next_u64()` draws are reported in every
implementation's `check` output and must match.

Sampling from a probability vector:

```
sample(probs, rng):
    total = 0.0; cum[i] = (total += probs[i])      // ascending i
    u = rng.next_f64() * total
    for i in 0..n: if u < cum[i]: return i
    return n - 1
```

## 5. Tokenization and the two measurements

**Tokenizer.** A document is `[BOS] + one token per character + [BOS]`, matching how
microgpt.py trains. A character's token id is its index in the vocab string.

### Perplexity (`--mode ppl`)

Teacher-forced over `data/val.txt`: 2,000 documents the model never saw, since training
only consumed `docs[:1000]`. No temperature, no sampling.

```
for each doc:
    tokens = tokenize(doc)
    n = min(block_size, len(tokens) - 1)
    fresh KV cache
    for pos in 0..n:
        logits = forward(tokens[pos], pos, cache)
        nll   -= log(softmax(logits)[tokens[pos+1]])
        count += 1
perplexity = exp(nll / count)
```

The `min(block_size, …)` cap is microgpt.py's; with a 15-character longest name it never
truncates, so every token of every document is scored: `docs=2000, tokens=14307`.

### Generation speed (`--mode gen`)

```
for each of --samples samples:
    fresh KV cache; token = BOS
    for pos in 0..block_size:
        logits = forward(token, pos, cache)
        tokens_generated += 1
        token = sample(softmax(logits / temperature), rng)
        if token == BOS: break
        emit vocab[token]
```

The RNG is **re-seeded at the start of every repeat**, so all repeats do identical work and
produce identical text. `tokens_generated` counts forward passes; it is the numerator for
tokens/s.

Each implementation runs this in two parts:

1. a **deterministic pass** of exactly `--samples` samples, which produces the hash and the
   sample text, and warms the code paths; then
2. `--repeats` **timed passes**, each generating until `--time-budget` seconds have elapsed.

Perplexity works the same way: one full pass over the evaluation set for the number itself,
then time-budgeted passes cycling the corpus for the throughput measurement. Wall clock
covers the loop only; weight loading is reported separately as `load_seconds`.

## 6. CLI contract

Every implementation accepts the same flags, so the harnesses can drive them uniformly:

| Flag | Default | Meaning |
|---|---|---|
| `--weights PATH` | `weights/microgpt.bin` | weight file |
| `--data PATH` | `data/val.txt` | one document per line |
| `--mode all\|gen\|ppl\|check` | `all` | which measurements to run |
| `--samples N` | `1000` | generation samples |
| `--temperature F` | `0.5` | sampling temperature |
| `--seed N` | `1234` | RNG seed |
| `--repeats N` | `5` | timed repeats |
| `--time-budget F` | `2.0` | wall-clock seconds per timed repeat |
| `--pin N` | `0` | pin to this logical CPU (`-1` disables) |
| `--max-docs N` | `0` (all) | truncate the perplexity set |
| `--json PATH` | | also write the report to this file |

A port whose language has no affinity binding may report `"cpu_pin": "external (taskset)"`
and rely on being pinned from outside; both OCaml ports do, since OCaml's stdlib exposes
no `sched_setaffinity`. `bench/bench.py` passes `--pin -1` and pins every implementation
with `taskset`, so all of them get identical treatment.

The JSON report goes to stdout. Nothing else may be printed to stdout; diagnostics go to
stderr.

## 7. JSON report contract

```json
{
  "impl": "python",
  "mode": "all",
  "runtime": "CPython 3.14.3",
  "build": "interpreted (no numpy, plain f64 lists)",
  "weights_sha256": "9bf6ac86…",
  "config": { "n_layer": 1, "n_embd": 16, "num_weights": 4192, "…": "…" },
  "load_seconds": 0.0012,
  "cpu_pin": "cpu0",

  "check": {
    "logits_after_prompt": [27 f64],
    "first3_nll": 8.34…, "first3_tokens": 17,
    "rng_first4_u64": ["0x…", "0x…", "0x…", "0x…"],
    "weights_sum": 10.6213…, "weights_abs_sum": 516.1316…
  },
  "gen": {
    "samples": 1000, "tokens": 6021, "chars": 5021,
    "output_fnv1a64": "0x6fa78e6dddfddbcb",
    "first_samples": ["mana", "analen", "…"],
    "rates_per_repeat": [3301.2, 2870.4, …],
    "tokens_per_repeat": [3301, 2870, …],
    "seconds_per_repeat": [1.0, 1.0, …],
    "tokens_per_sec_best": 3301.2, "tokens_per_sec_median": 2954.1
  },
  "ppl": {
    "docs": 2000, "tokens": 14307,
    "nll_total": 34029.5…, "nll_per_token": 2.378584…,
    "perplexity": 10.7896…, "bits_per_token": 3.4316…,
    "full_pass_seconds": 4.69,
    "rates_per_repeat": [2120.3, …], "tokens_per_sec_best": 2120.3
  }
}
```

`output_fnv1a64` is FNV-1a 64 over the generated samples joined by `"\n"` (no trailing
newline), ASCII:

```
h = 0xCBF29CE484222325
for each byte b: h ^= b; h = h * 0x100000001B3   // wrapping
```

## 8. What counts as a correct port

Across every implementation:

- identical `weights_sha256` and `config`
- `weights_sum` / `weights_abs_sum` matching `config.json`
- `check.rng_first4_u64` identical: the RNG is right
- `ppl.perplexity` agreeing within **1e-9** relative (in practice: to the last digit)
- `gen.output_fnv1a64` identical: the ports generate the same text

The hash is the strong check: it can only match if the forward pass, the softmax, the
temperature division, the RNG and the sampling scan all agree. If perplexity matches but
the hash does not, the divergence is in sampling, not the model.

`gen.tokens`, `gen.output_fnv1a64` and `ppl.tokens` come from the deterministic passes,
never from the time-budgeted ones, so they stay comparable. `check.first3_nll` groups its
summation per document and then adds, as the perplexity path does: all five
implementations route it through their `score_doc` helper, because one running total over
every token is a different summation order.

The hash covers the whole generated corpus, so it changes with `--samples`,
`--temperature` and `--seed`; compare it only at identical settings. At the benchmark's
settings (200 samples, temperature 0.5, seed 1234) it is `0xae6c6ffbd8f5b02c`; PORTING.md
lists the values at the CLI defaults.

## 9. The cross-platform check harness

`bench/run.py` builds the five shipped ports with whatever toolchains are present and
checks the agreement rules above; it also runs natively on Windows (the OCaml ports
through WSL, for agreement only):

```bash
python tools/train_export.py --steps 1000     # once, ~80s, produces the weights
python tools/validate.py                      # plain-float forward vs microgpt.py autograd
python bench/run.py --build --check-only      # build every port, check agreement
python bench/run.py --impls python,cpp --repeats 9 --time-budget 1.0
```

Its timings are a quick look; the measured numbers come from `bench/bench.py`, which times
everything in one Linux environment, because a Windows-native binary timed against a
Linux one measures the operating system and libm as well as the language. Correctness is
portable: the same C++ source under g++ 15.2 / Windows UCRT and g++ 14.2 / Linux glibc
produces bit-identical output.
