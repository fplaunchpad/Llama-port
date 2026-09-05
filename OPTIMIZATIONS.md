# Optimization log — Rust port

Generation speed after each change. Every measurement uses identical settings
(`--mode gen --samples 200 --temperature 0.5 --seed 1234`) and every build is checked
against the same output hash `0xae6c6ffbd8f5b02c`.

**A build that is faster but produces different text is a bug, not an optimization.** All
five builds below produce byte-for-byte identical output, so the speed differences are real
work saved, not corners cut.

Measure a new change with:

```bash
python tools/track_opt.py old=path/to/before.exe new=path/to/after.exe --rounds 15
```

---

## Results

Each row is **baseline plus that one change** — not a cumulative chain, so don't read row 2
as "row 1 plus more". The last row is all three together, which is what shipped.

| build | tok/s (one session) | delta across 5 sessions | verdict |
|---|---:|---|---|
| baseline (first working port) | 541,908 | — | started 1.6% behind C++ |
| baseline + **A** (KV cache hoist) | 543,364 | +0.5, +1.6, +2.0, +2.3, +4.0% | **real, ~+2%** |
| baseline + **B** (chunked matrix walk) | 557,707 | +2.2, +2.9, +3.7, +4.0, +10.1% | **real, ~+3%** |
| baseline + **C** (precomputed constant) | 535,227 | −1.8, −0.7, +0.2, +1.3, +2.6% | **no measurable effect** |
| baseline + **A+B+C** (shipped) | 577,153 | +5.0, +5.6, +5.6, +7.5, +7.5% | **real, ~+6%** |

**Net effect:** Rust went from 1.6% behind C++ to 2.6% ahead of it on generation, measured
paired over 10 rounds. Perplexity throughput is +0.6%, which is a coin flip — call the two
languages tied.

### Why five sessions instead of one number

This machine (mobile hybrid CPU) has 5–8% run-to-run spread, and absolute throughput drifted
from ~600k to ~370k tok/s over one afternoon. Any single run can show a 3% effect that
reverses on the next run — **C did exactly that**, measuring +1.3% once and −1.8% the next
time. So each change was re-measured in five independent interleaved sessions, and is only
called real when the sign held in all five. Trust the combined +6%; treat the individual
attributions as ±3%.

---

## What each change actually was

### A — Don't re-find the shelf for every book

Attention reads from the KV cache, which was stored as a list of lists: `cache[layer][slot]`.
Reading one number meant: check the layer number is valid, follow a pointer to that layer's
array, check the slot is valid, then finally read. Four steps of bookkeeping for one number —
and the layer never changes inside the loop.

The fix grabs the layer's array **once**, before the loop starts, then reads plain numbers
out of it. Like fetching the right shelf once instead of walking back to the library
catalogue for every book.

The C++ port never had this problem: it took a raw pointer to the layer's array from the
start. This was Rust-specific catch-up.

### B — Prove it's safe once, not sixty-four times

The matrix multiply walks output rows: "compute row 0, write row 0; compute row 1, write row
1…". Written with explicit index numbers, Rust inserts a safety check on every single lookup
and every single write, asking "is this index actually inside the array?" — 16 to 64 times
per call, for indexes that obviously can't be out of range.

Rewriting the loop to walk the weights in fixed-size chunks and write through an iterator
lets Rust prove the indexes are valid **once**, up front, and skip all the per-row checks.
Identical arithmetic in identical order — just without re-proving safety on every step.

This is the classic Rust performance shape: the bounds checks are usually free because the
compiler eliminates them, but when it can't, you help it by expressing the loop so the
safety is structural rather than checked.

### C — Stop recomputing something that never changes

Attention divides by the square root of `head_dim`. `head_dim` is 4. The code was calling the
`pow` function to work out √4 = 2.0 once per layer per token — hundreds of thousands of times
to always get 2.0. Now it's computed once when the model loads.

**It made no measurable difference.** LLVM already recognises `pow(x, 0.5)` and rewrites it
as a `sqrt` instruction, so the "expensive" call was already cheap. Kept anyway because it
removes genuinely redundant work and reads more clearly — but it earns its place on clarity,
not speed. The same change was applied to the C++ port so neither language gets an unearned
advantage.

---

## Things that did not work

**`-C target-cpu=native` / `-march=native` made both languages slower** — Rust −9.8%, C++
−6.5%. The dot products are chains of dependent additions, and the contract forbids
reassociating them, so wider vector registers can't be used for the reduction at all. You get
the setup cost and, on some chips, a frequency drop, for no benefit. Measure before assuming
newer instructions help.

---

## Still on the table

Not done, roughly in order of expected value:

- **Flatten the KV cache** into one allocation indexed by `layer*block_size*n_embd + slot*n_embd`,
  removing the remaining pointer indirection that A only partly avoided.
- **Manually unroll `linear` across output rows** to expose more instruction-level
  parallelism. The dot products already run at ~1.4 cycles per multiply-add against a ~4
  cycle dependency chain, so the compiler is interleaving rows already — but more explicit
  unrolling might squeeze further.
- **Skip the logits→probs copy** in the scoring path.

Roughly 20–30% of runtime is `exp` and `pow` calls that the numerics contract *requires*
(`pow` in rmsnorm, `exp` in every softmax). That is a hard floor unless the contract changes.

Profiling detail, including where the cycles go per region, is in
[PORTING.md section 7](PORTING.md).
