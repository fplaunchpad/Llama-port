# Optimization log

Every optimization to every port, with before/after numbers.

Two rules, applied without exception:

1. **Identical output or it doesn't count.** Every build below produces byte-for-byte
   identical generated text (hash `0xae6c6ffbd8f5b02c` at `--samples 200`) and bit-identical
   perplexity. A build that is faster but produces different text is a bug, not an
   optimization.
2. **Whatever helps one language is tried on all of them.** Otherwise the benchmark measures
   how much effort each port received, not the language.

Measure a change with:

```bash
python tools/track_opt.py old=path/to/before.exe new=path/to/after.exe --rounds 15
```

Or re-measure **every** optimization of **every** port in one interleaved run:

```bash
wsl -d Debian -- bash tools/bench_variants.sh     # from the repo root
```

Each optimization is a real build switch, not a patch applied by hand — `-DMG_UNROLL=0`
for C++, `--no-default-features` for Rust, `MG_UNROLL=0` / `OCAMLFLAGS` for OxCaml — so
the numbers below can be reproduced instead of taken on trust.

---

## The measured matrix

9 variants, 11 interleaved rounds, `taskset`-pinned, one Linux environment. All nine
produce byte-identical output, so every difference is real work saved.

| variant | tok/s (median) | vs python | vs fastest |
|---|---:|---:|---:|
| `cpp_unroll` **(shipped)** | 877,892 | 129x | 100% |
| `rust_unroll` **(shipped)** | 759,910 | 112x | 87% |
| `cpp_plain` | 709,273 | 104x | 81% |
| `rust_plain` | 689,804 | 101x | 79% |
| `cpp_O2_plain` | 612,057 | 90x | 70% |
| `oxcaml_unsafe_unroll` **(shipped)** | 478,996 | 70x | 55% |
| `oxcaml_unsafe_plain` | 305,831 | 45x | 35% |
| `oxcaml_safe_plain` | 184,437 | 27x | 21% |
| `python` | 6,805 | 1.0x | 1% |

Each step against the one before it, paired over the same rounds:

| language | step | delta | rounds won |
|---|---|---:|---|
| **C++** | `-O2` → `-O3` | **+16.3%** | 11/11 |
| | `-O3` → 4-way unroll | **+21.7%** | 11/11 |
| | *total* | **+43.4%** | |
| **Rust** | plain → 4-way unroll | **+6.7%** | 11/11 |
| | *total* | **+10.2%** | |
| **OxCaml** | bounds-checked → `-unsafe` | **+61.5%** | 11/11 |
| | `-unsafe` → 4-way unroll | **+57.5%** | 11/11 |
| | *total* | **+159.7%** | |

Two things worth pulling out of that table:

**Optimization effort decided the ranking, not the language.** Unoptimized, Rust (689,804)
beats C++ at `-O2` (612,057) and is within 3% of C++ at `-O3`. Fully optimized, C++ leads by
16%. Anyone benchmarking these two languages by writing the obvious loop and picking a flag
would have got whichever answer their flag chose for them.

**The slowest starting point had the most to gain.** OxCaml begins last at 27x Python and
ends at 70x — the same two optimizations that bought C++ 43% bought OCaml 160%, because its
backend was leaving far more on the table.

---

## The most interesting result: unrolling, and what compilers actually do

The matrix multiply is a chain of *dependent* additions — each `acc += w*x` waits for the
previous one, roughly 4 cycles apiece. The escape is to compute four output rows at once so
the CPU has four independent chains to overlap. Each row still accumulates strictly left to
right, so the arithmetic and its order are unchanged, and the output hash never moved.

Doing this **by hand** is worth wildly different amounts:

| language | gain from 4-way manual unroll | rounds won | what it says about the compiler |
|---|---:|---|---|
| OCaml (OxCaml, flambda2) | **+61%** | 7/7 | not interleaving output rows at all |
| C++ (g++ 14.2/15.2 `-O3`) | **+21.6%** | 9/9 | interleaving partially |
| Rust (rustc 1.98 `--release`) | **+5.1%** | 8/9 | interleaving nearly fully |

That spread is a direct measurement of how much instruction-level parallelism each backend
was already extracting, and it is the single largest optimization in this project.

**I got this wrong first.** Earlier versions of these docs claimed GCC and LLVM already did
this and that the kernels were "near the practical floor" — asserted from a cycles-per-op
estimate, never measured. Testing it because OCaml needed it, then applying it to the others
for fairness, is what exposed the error. It also **flipped the ranking**: Rust led C++ by
2.6% before, and trails by ~4-10% after, because C++ had more headroom left.

---

## Rust

| change | delta | verdict |
|---|---|---|
| **A** hoist KV cache slices out of attention inner loops | +0.5 … +4.0% over 5 sessions | real, ~+2% |
| **B** walk `linear` in fixed-size chunks instead of by index | +2.2 … +10.1% over 5 sessions | real, ~+3% |
| **C** precompute the constant attention scale | −1.8 … +2.6%, sign flips | **no measurable effect** |
| A+B+C combined | +5.0 … +7.5% over 5 sessions | real, ~+6% |
| **D** 4-way unrolled `linear` | +5.1%, 8/9 rounds | real |

**A — don't re-find the shelf for every book.** The KV cache was a list of lists,
`cache[layer][slot]`. Reading one number meant checking the layer index, following a pointer
to that layer's array, checking the slot index, then reading — four steps of bookkeeping per
number, for a layer that never changes inside the loop. Now the layer's array is taken once,
before the loop. The C++ port never had this problem; it used a raw pointer from the start.

**B — prove it's safe once, not sixty-four times.** Indexing output rows by number makes Rust
insert a bounds check on every lookup and every write, 16–64 times per call, for indexes that
cannot be out of range. Walking the weights in fixed-size chunks lets the compiler prove
validity once, up front. (Superseded by D, which restructures the same loop again.)

**C — stop recomputing a constant.** `√head_dim` was computed once per layer per token,
always returning 2.0. Now computed at load. **No measurable speedup** — LLVM already rewrites
`pow(x, 0.5)` as `sqrt`. Kept for clarity, not speed. Applied to C++ too, so neither language
gets an unearned advantage.

---

## C++

| change | delta | verdict |
|---|---|---|
| precompute the constant attention scale | not separately measurable | parity with Rust's C |
| **4-way unrolled `linear`** | **+21.6%**, 9/9 rounds | **real, and large** |
| `-O2` → `-O3` | +20% | fixes an unfair comparison, see below |

The `-O2`→`-O3` change was not an optimization so much as a **correction**: C++ was being
built at `-O2` while Rust used its release default of `opt-level 3`, which made Rust look
~20% faster than it was. That is benchmarking a flag, not a language.

---

## OxCaml

| change | delta | verdict |
|---|---|---|
| `-O3 -unsafe` | **+60.1%**, 7/7 rounds | real |
| **4-way unrolled `linear`** | **+61.1%**, 7/7 rounds | real |

Net ~2.6x faster than the first working version, closing the gap to C++ from 3.8x to ~1.8x.

**Bounds checks (`-unsafe`), +60%.** OCaml checks every `a.(i)` against the array length at
run time, and this program is almost entirely array indexing. This is a real safety trade —
the same level C++ has by default, but note the contrast with Rust, which reached the same
place *without* giving anything up because the compiler proved the indexes in range instead.
A bounds-checked binary is one variable away, with identical output:

```bash
OCAMLFLAGS="-O3" bash impl/oxcaml/build.sh   # ~60% slower
```

**Unrolling, +61%.** Diagnosed by elimination: allocation was measured at 12.9 words per
forward pass with zero minor collections, ruling out float boxing, which left code
generation. flambda2 was not interleaving output rows at all.

---

## Python

One change, and it was a **correctness fix that also happened to be faster**: replacing
`sum(genexp)` with explicit `acc += ...` loops. CPython ≥3.12 applies Neumaier compensated
summation to floats, so the reference was computing *different arithmetic* from the compiled
ports — 141 of 214 dot products differed. Removing the compensation made Python **faster**,
because compensated summation does extra work per element. See PORTING.md trap 1.

That correction also cut the headline speedup claim from ~142x to ~102x, since the earlier
figure had Python doing arithmetic the other ports never did.

---

## Things that did not work

**`-C target-cpu=native` / `-march=native` made both languages slower** — Rust −9.8%, C++
−6.5%. The dot products are chains of dependent additions and the contract forbids
reassociating them, so wider vector registers cannot be used for the reduction at all. You
pay the setup cost, and on some chips a frequency drop, for nothing.

---

## Still on the table

- **Wider unrolling** (8-way) now that 4-way is known to pay, especially in OCaml.
- **The same treatment for the attention accumulation loops**, which are still scalar chains.
- **Flatten the KV cache** into one allocation indexed by `layer*block_size*n_embd + slot*n_embd`.
- **`lm_head`'s 27 rows** leave a 3-row tail on the slow path after 4-way unrolling.

Roughly 20–30% of runtime is `exp` and `pow` calls the numerics contract *requires* (`pow` in
rmsnorm, `exp` in every softmax). That bounds any remaining win.

Profiling detail — where the cycles go per region — is in [PORTING.md section 7](PORTING.md).
