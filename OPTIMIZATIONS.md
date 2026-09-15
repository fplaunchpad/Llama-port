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
for C++, `--no-default-features` for Rust, `MG_UNROLL=0` / `OCAMLFLAGS` for both OCaml
builds — so the numbers below can be reproduced instead of taken on trust.

One deliberate exception: the GC-poll section below also uses a hand-edited **binary**, in
which the poll instructions are overwritten with NOPs. That one is a *control*, not an
optimization — it exists precisely to show that the build switch beside it is not measuring
what it appears to. See [GC safepoint polls](#gc-safepoint-polls-the-cost-is-a-register-not-two-instructions).

---

## The measured matrix

19 variants, 9 interleaved rounds, `taskset`-pinned, one Linux environment. All nineteen
produce byte-identical output, so every difference is real work saved.

| variant | tok/s (median) | vs python | vs fastest |
|---|---:|---:|---:|
| `cpp_unroll` **(shipped)** | 827,692 | 124x | 100% |
| `rust_unroll` **(shipped)** | 743,395 | 111x | 90% |
| `rust_plain` | 694,644 | 104x | 84% |
| `cpp_plain` | 680,328 | 102x | 82% |
| `cpp_O2_plain` | 563,875 | 85x | 68% |
| `oxcaml_unsafe_sr_pollfree` ¹ ² | 551,619 | 83x | 67% |
| `oxcaml_unsafe_unroll_pollfree` ¹ | 516,513 | 77x | 62% |
| `oxcaml_unsafe_sr` ² | 502,065 | 75x | 61% |
| `ocaml_unsafe_sr` ² | 477,583 | 72x | 58% |
| `oxcaml_unsafe_unroll` **(shipped)** | 464,428 | 70x | 56% |
| `ocaml_unsafe_unroll` **(shipped)** | 429,932 | 64x | 52% |
| `oxcaml_safe_unroll` | 362,117 | 54x | 44% |
| `ocaml_safe_unroll` | 305,183 | 46x | 37% |
| `oxcaml_unsafe_plain_pollfree` ¹ | 303,572 | 46x | 37% |
| `oxcaml_unsafe_plain` | 288,609 | 43x | 35% |
| `oxcaml_safe_plain` | 179,853 | 27x | 22% |
| `ocaml_unsafe_plain` | 132,122 | 20x | 16% |
| `ocaml_safe_plain` | 128,517 | 19x | 16% |
| `python` | 6,672 | 1.0x | 1% |

¹ `_pollfree` drops the GC safepoint poll. **Not shippable** — nothing can preempt the
result — but it prices what the poll costs, and the answer is not what you would guess.
See [GC safepoint polls](#gc-safepoint-polls-the-cost-is-a-register-not-two-instructions).

² `_sr` carries the row offsets as running indices instead of recomputing `base + i`
(`MG_SR=1`). Fully shippable, and the only change here that closes a gap the *compiler*
should have closed. See
[strength reduction](#strength-reduction-by-hand-89-under-flambda2-108-under-ocaml-530-55-under-540).

Each step against the one before it, paired over the same rounds:

| language | step | delta | rounds won |
|---|---|---:|---|
| **C++** | `-O2` → `-O3` | **+18.9%** | 9/9 |
| | `-O3` → 4-way unroll | **+22.0%** | 9/9 |
| | *total* | **+46.8%** | |
| **Rust** | plain → 4-way unroll | **+5.2%** | 9/9 |
| | *total* | **+7.0%** | |
| **OxCaml** (flambda2) | bounds-checked → `-unsafe` | **+57.4%** | 9/9 |
| | `-unsafe` → 4-way unroll | **+58.4%** | 9/9 |
| | strength reduction (`MG_SR=1`) | **+8.9%** | 8/9 |
| | *total* | **+181.2%** | |
| **OCaml** (stock 5.3.0, closure) | bounds-checked → `-unsafe` | **+7.0%** | 9/9 |
| | `-unsafe` → 4-way unroll | **+207.3%** | 9/9 |
| | strength reduction (`MG_SR=1`) | **+10.8%** | 9/9 |
| | *total* | **+271.6%** | |

Three things worth pulling out of that table:

**Optimization effort decided the ranking, not the language.** Unoptimized, Rust (694,644)
beats C++ at `-O2` (563,875) and at `-O3` (680,328). Fully optimized, C++ leads by 11.3%.
Anyone benchmarking these two languages by writing the obvious loop and picking a flag would
have got whichever answer their flag chose for them.

**The slowest starting point had the most to gain.** Stock OCaml begins last of the compiled
ports at 19x Python and ends at 72x — the same switches that bought C++ 47% bought it 272%,
because its backend was leaving far more on the table.

**The two OCaml ladders end in the same place by completely different routes.** `-unsafe` is
worth +59% under flambda2 and +6% under closure; the unroll is worth +54% under flambda2 and
+221% under closure. Both finish within ~5% of each other. Neither switch is "worth" a fixed
amount — what each one buys depends entirely on what the other has already removed, and on
which compiler is reading the loop.

---

## The two OCaml compilers

`impl/ocaml` and `impl/oxcaml` are the **same source file**, held byte-identical outside the
header comment and two identity strings — `impl/ocaml/build.sh` diffs them and refuses to
build if they drift. Neither uses an OxCaml language extension: no modes, no unboxed types,
no locality annotations. So every difference below is the middle-end.

| kernel | safety | stock (closure) | OxCaml (flambda2) | flambda2 lead | rounds won |
|---|---|---:|---:|---:|---|
| plain | bounds-checked | 128,517 | 179,853 | **+43.7%** | 9/9 |
| plain | `-unsafe` | 132,122 | 288,609 | **+107.6%** | 9/9 |
| unrolled | bounds-checked | 305,183 | 362,117 | **+15.9%** | 8/9 |
| unrolled | `-unsafe` **(both shipped)** | 429,932 | 464,428 | +7.7% | 8/9 |

**flambda2's advantage is real, decisive, and almost entirely spent on code you have not
optimized yourself.** On the plain `-unsafe` kernel it is 2.1x ahead. On the shipped kernel
it is +7.7% at 8/9 rounds — real, but a fraction of the 2.1x it holds on the plain kernel,
and the figure has ranged from +2.3% to +7.7% across runs. The conclusion does not depend on
its exact size: by the time you have unrolled the kernel yourself, the better middle-end has
almost nothing left to find. The unroll and flambda2 are buying the same thing: four
independent accumulator
chains instead of one serial chain of dependent f64 adds. flambda2 finds them; the closure
backend does not. Write them out by hand and there is nothing left for the better compiler
to discover.

The region profiler agrees, and shows where what remains of that lead lives:

```bash
wsl -d Debian -- python3 tools/profile_regions.py --impls ocaml,oxcaml
```

On the shipped builds, flambda2 is ahead in `attn`, `qkv` and `embed` — the accumulation
loops that are still hand-written serial folds, never unrolled — and slightly *behind* in
`mlp`, `lm_head` and `sample`, which run through the unrolled `linear`. That is the same
story read at region granularity: flambda2 wins exactly where the source did not do the
work first.

**Caveat on the controlled variable.** The OxCaml switch pins a 5.2.0-based compiler
(`ocamlopt 5.2.0+ox`) and the stock one here is 5.3.0, so the two are a language minor
version apart. The middle-end dominates a 2.1x gap; it would not obviously dominate the
few-percent one.

---

## The most interesting result: unrolling, and what compilers actually do

The matrix multiply is a chain of *dependent* additions — each `acc += w*x` waits for the
previous one, roughly 4 cycles apiece. The escape is to compute four output rows at once so
the CPU has four independent chains to overlap. Each row still accumulates strictly left to
right, so the arithmetic and its order are unchanged, and the output hash never moved.

Doing this **by hand** is worth wildly different amounts:

| language | gain from 4-way manual unroll | rounds won | what it says about the compiler |
|---|---:|---|---|
| OCaml (stock 5.3.0, closure) | **+207.3%** | 9/9 | not interleaving output rows, and no way to ask it to |
| OCaml (OxCaml 5.2.0+ox, flambda2) | **+58.4%** | 9/9 | interleaving some, but far from fully |
| C++ (g++ 14.2/15.2 `-O3`) | **+22.0%** | 9/9 | interleaving partially |
| Rust (rustc 1.98 `--release`) | **+5.2%** | 9/9 | interleaving nearly fully |

That spread is a direct measurement of how much instruction-level parallelism each backend
was already extracting, and it is the single largest optimization in this project. Adding the
stock OCaml compiler stretched the spread to ~40x: the same three lines of source are worth
5% at one end of that table and 207% at the other.

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
| **D** 4-way unrolled `linear` | +4.8%, 7/9 rounds | real, but the smallest of the four backends |

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
| **4-way unrolled `linear`** | **+18.9%**, 9/9 rounds | **real, and large** |
| `-O2` → `-O3` | +13.2%, 8/9 rounds | fixes an unfair comparison, see below |

The `-O2`→`-O3` change was not an optimization so much as a **correction**: C++ was being
built at `-O2` while Rust used its release default of `opt-level 3`, which made Rust look
~20% faster than it was. That is benchmarking a flag, not a language.

---

## OCaml — both compilers

The two ports are one source file. Everything here applies to both binaries; where the
numbers differ, that is the middle-end and nothing else.

| change | OxCaml (flambda2) | stock (closure) | verdict |
|---|---:|---:|---|
| `-unsafe` on the plain kernel | **+59.2%**, 9/9 | **+6.2%**, 7/9 | real in both, wildly different sizes |
| **4-way unrolled `linear`** | **+54.3%**, 9/9 | **+220.5%**, 9/9 | real, and the largest single change in the project |
| **drop the GC safepoint poll** | **+11.4%**, 9/9 | — (no such flag) | real, but not for the reason it looks like |
| **strength-reduce `base + i`** | **+8.9%**, 8/9 | **+10.8%**, 9/9 (5.3.0) | real; the only shippable one here |
| *total, plain+checked → shipped* | **+140.7%** | **+236.1%** | |

**Unrolling.** Diagnosed by elimination: allocation was measured at 12.9 words per forward
pass with zero minor collections, ruling out float boxing, which left code generation.
flambda2 was interleaving output rows only partially, and the closure backend not at all.
See the section above for what happens to the compiler gap once this is applied.

### Bounds checks: what `-unsafe` actually costs

OCaml checks every `a.(i)` against the array length at run time, and this program is almost
entirely array indexing. `-unsafe` removes those checks — a real safety trade, putting the
binary at the same level C++ has by default, and worth contrasting with Rust, which reached
the same place *without* giving anything up because LLVM proved the indexes in range instead.

The benchmark builds all four corners so the trade can be priced rather than assumed, and the
answer depends on which kernel you are compiling:

| compiler | kernel | checked tok/s | `-unsafe` tok/s | cost of keeping checks | rounds |
|---|---|---:|---:|---:|---|
| OxCaml (flambda2) | plain | 179,853 | 288,609 | **−36.5%** | 0/9 |
| OxCaml (flambda2) | unrolled **(shipped)** | 362,117 | 464,428 | **−21.3%** | 0/9 |
| stock (closure) | plain | 128,517 | 132,122 | **−6.6%** | 0/9 |
| stock (closure) | unrolled **(shipped)** | 305,183 | 429,932 | **−25.6%** | 0/9 |

Read the two closure rows together, because they look contradictory and are not. On the plain
kernel the stock compiler is bottlenecked on a single serial chain of dependent f64 adds —
roughly 4 cycles each, with the rest of the pipeline idle. The bounds checks execute *in that
shadow*, on ports that had nothing to do anyway, and cost 5.8%. Unroll the loop, and the
four independent chains fill the pipeline; now the checks compete for real issue slots, and
the same checks cost 25.3%. **The price of a safety feature is not a property of the safety
feature.** It is a property of what else the machine had to do at that moment.

flambda2 shows the mirror image — it is *already* extracting parallelism on the plain kernel,
so the checks are expensive there (−37.6%) and get relatively cheaper once the hand unroll
takes over the scheduling (−19.8%).

A fully bounds-checked binary is one variable away, with identical output:

```bash
OCAMLFLAGS="-O3" bash impl/oxcaml/build.sh    # flambda2, checks on: ~20% slower
OCAMLFLAGS=""    bash impl/ocaml/build.sh     # stock, checks on: ~25% slower
```

Net across both switches: ~2.5x faster than the first working OCaml version, closing the gap
to C++ from 3.8x to ~1.8x.

### Why the OCaml kernel is ~1.8x C++: an instruction budget

The region profiler splits a forward pass seven ways and attributes the gap:

```bash
wsl -d Debian -- python3 tools/profile_regions.py --mode gen --rounds 5
```

On the shipped builds (gen, ns per forward pass; magnitudes anchored to the *uninstrumented*
binaries, so the counters only decide the split — instrumentation slows the two ports by
different amounts, and using its absolute times would bias every ratio):

| region | cpp ns | oxcaml ns | ox/cpp | **share of gap** | cpp ns/op | ox ns/op |
|---|---:|---:|---:|---:|---:|---:|
| mlp | 524 | 1076 | 2.05x | **+49%** | 0.24 | 0.50 |
| attn | 207 | 367 | 1.77x | +14% | 1.81 | 3.21 |
| qkv | 230 | 378 | 1.64x | +13% | 0.29 | 0.47 |
| lm_head | 105 | 201 | 1.91x | +8% | 0.24 | 0.47 |
| sample | 234 | 311 | 1.33x | +7% | 1.74 | 2.30 |
| wo | 66 | 126 | 1.90x | +5% | 0.26 | 0.49 |
| embed | 24 | 58 | 2.40x | +3% | 0.51 | 1.22 |
| **total** | **1390** | **2521** | **1.81x** | 100% | | |

**There is no pathological chunk.** The four regions that are pure `linear` — mlp, qkv,
lm_head, wo — sit at a nearly flat per-op ratio (C++ ~0.25 ns/op, OCaml ~0.48) and together
are **75% of the gap**. `mlp` dominates only because it holds 2144 of the ~3800 ops per
token. The bottleneck is one loop.

Two controls worth reading off the same table: `sample` is where the two are closest
(1.33x), because it is 27 glibc `exp` calls in both — where the work happens in shared C,
the language gap nearly vanishes. And `embed` has the worst *ratio* but 3% of the gap;
chasing it would be wasted effort.

Disassembling that loop, per 4 multiply-accumulates:

| per 4 MACs | C++ | OCaml | why |
|---|---:|---:|---|
| FP multiply + add | 8 | 8 | identical work |
| FP loads not folded into a multiply | 4 | 1 | OCaml folds them — **better** |
| integer address arithmetic | 1 | 8 | no interior pointers, no strength reduction |
| …of which a stack spill reload | 0 | 1 | `%r14`/`%r15` reserved, `%r11` sterilized by the poll |
| loop control | 2 | 3 | bottom test plus separate increment |
| GC safepoint poll | 0 | 2 | see below |
| unconditional back edge | 0 | 1 | poll-block layout |
| **total** | **15** | **23** | **1.53x** — measured 1.60x |

Both spend exactly 8 instructions on arithmetic. The whole deficit is integer bookkeeping,
and the largest line has a hard cause: **OCaml has no interior pointers.** C++ keeps four
`const double*` pointing into the middle of the weight array and advances all four rows with
one `addq $8`. OCaml cannot: its GC is precise and must find the header of the block any
pointer points into, and that header sits immediately *before* the data — so a pointer to
`&d[b0]` mid-array is not a representable value. Every access is `base + index`, re-derived
per row per iteration. (Tagging is *not* the cost, incidentally: `2n+1` is absorbed free by
x86's scale-4 addressing, `-4(%rbx,%rdi,4)`.) Part of this is the language and part is
flambda2 declining to strength-reduce the four bases into running induction variables.

**SIMD is not the answer, and I assumed it was.** The obvious reading of that table is that
GCC vectorizes and flambda2 does not — GCC does emit `mulpd`/`addpd`, packing two `i` values
across the four output rows, while OCaml emits only scalar `vmulsd`. Rebuilding C++ with
`-fno-tree-vectorize` tests it directly:

| build | tok/s | vs vectorized |
|---|---:|---:|
| `cpp_unroll` | 684,419 | 100% |
| `cpp_unroll -fno-tree-vectorize` (0 packed ops) | 642,286 | 94% |
| `oxcaml_unsafe_unroll` | 401,435 | 59% |

Vectorization is worth **6.2%**. Un-vectorized C++ is still **1.60x** ahead. So adding SIMD
to OCaml is the small win and the scalar bookkeeping is the big one — the opposite of the
intuition, and only measurement separates them. (C++ vectorizing at all here is legal
because it packs *across independent output rows*; the reduction inside a row is still
strictly left-to-right, which is why the hash never moves.)

### GC safepoint polls: the cost is a register, not two instructions

OCaml 5 emits a **safepoint poll** on every loop back edge it cannot prove terminates
quickly — two instructions comparing the allocation pointer against the domain's young
limit:

```
cmp  (%r14),%r15      ; young_ptr vs young_limit
jbe  <runtime>
```

It has to. A poll is the only point at which a pending signal can run, or at which a
multicore stop-the-world minor GC can catch every domain; a non-allocating loop with no
poll in it would block both indefinitely. The `linear` inner loop allocates nothing and
calls nothing, so without an inserted poll it would contain no safepoint at all.

It is priced two independent ways, because they bracket the answer:

```bash
wsl -d Debian -- bash tools/bench_polls.sh     # from the repo root
```

| | what it does | bound |
|---|---|---|
| `pollnop` | overwrites the poll instructions with NOPs **in the linked binary** (`tools/nop_polls.py`) — identical registers, schedule and layout | **lower** — a NOP still costs a decode slot |
| `pollfree` | recompiles with `ocamlopt -disable-poll-insertion` | **upper** — polls truly gone, but the compiler re-optimized around them |

15 interleaved rounds, `taskset`-pinned, all variants bit-identical output:

| variant | `pollnop` | `pollfree` |
|---|---:|---:|
| `oxcaml_unsafe_plain` | +2.5% (14/15) | +4.4% (13/15) |
| `oxcaml_unsafe_unroll` **(shipped)** | **+0.1%** (8/15) | **+15.2%** (14/15) |
| `ocaml_unsafe_plain` | +0.3% (8/15) | — ¹ |
| `ocaml_unsafe_unroll` **(shipped)** | −0.4% (6/15) | — ¹ |

¹ stock `ocamlopt` has no `-disable-poll-insertion`; it is an OxCaml flag. For that compiler
the binary patch is the only way to take this measurement at all.

The full matrix at the top of this file reproduces the effect independently, though its size
moves between runs: `+15.2%`, `+16.4%`, `+14.3%` and `+11.4%` on the unrolled kernel across
four separate runs. The plain kernel is consistently the *smaller* of the two (`+4.4%`,
`+9.5%`, `+7.5%`), which is the part the argument below rests on.

**Erasing every poll from the binary gains nothing. Recompiling without them gains 15%.**
That is not a contradiction, and the gap between the two columns is the entire result. The
NOP patch is the *more* aggressive removal — it erases all 853 poll sites including the ones
in the standard library, where the flag only removes the 190 in `main.ml` — and it still
gains nothing.

Two falsification tests, both built into the script, say the same thing. If a poll cost what
it executes, the two columns would agree; they differ by 15 points. And the plain kernel runs
its inner loop four times as often for the same arithmetic, so it executes ~4x the polls and
should gain ~4x — it gains *less*.

What actually changes is the register allocation. Disassembling `linear` both ways:

| | shipped | `pollfree` |
|---|---|---|
| `%r11` occurrences | **0** | **8** |
| stack spills | 1 | **0** |
| instructions in function | 102 | 91 |
| four row bases held in | `r9, r8, r12,` **`(%rsp)`** | `r9, r8, r12, r13` |

The compiler will not allocate anything to `%r11` across a poll, so the register is unusable
for the whole loop. That leaves eight allocatable registers for nine live values — four row
bases, index, bound, two array pointers, scratch — and one row base spills to the stack,
reloaded on *every iteration* (`mov (%rsp),%r10`).

**That spill is not the cost, though — and an earlier version of this section said it was.**
The obvious chain, *poll → `%r11` sterilized → spill → a load per iteration → ~15%*, is
testable directly: patch the two spill sites in the linked binary to use `%r11` instead of
the stack slot, changing nothing else. The result:

| | delta | rounds |
|---|---:|---|
| spilled base → `%r11`, binary edit | **+0.3%** | 7/11 — noise |
| poll instructions → NOPs, binary edit | **+0.1%** | 8/15 — noise |
| `-disable-poll-insertion` | **+16.4%** | 11/11 |

So it is not the two instructions, and it is not the spill either. Both were measured and
both came back empty; only recompiling without polls pays.

That experiment did settle one thing: the patched binary produces **bit-identical output**,
so a value *does* survive a poll in `%r11` — consistent with `caml_call_gc` saving it
(`mov %r11,0x58(%r15)`) before using it as scratch. flambda2's exclusion of `%r11` is
therefore more conservative than the runtime requires. It is just not where the time goes.

**What the 16% actually is remains unresolved.** The plausible remaining candidate is that
the poll splits the loop body into separate basic blocks and so constrains instruction
scheduling, rather than costing registers or instructions — but that is a hypothesis, not a
measurement, and it is recorded here as an open question rather than an explanation.

Three consequences worth keeping:

- **The plain kernel gains little (+4.4%) because it is not register-starved** — one
  accumulator and one base, with registers to spare, so whatever the poll costs the unrolled
  kernel, it has less of it to lose.
- **This is flambda2-only.** The stock compiler puts **zero** polls in `linear` (its hot loop
  is slow for a different reason: 161 instructions and 2 spills, i.e. worse allocation
  generally). So there is no stock-OCaml counterpart to chase.
- **Neither poll-free binary is shippable.** Without polls a long non-allocating loop is
  never preemptible: signals are delayed, and with more than one domain a stop-the-world
  minor GC hangs. Fine for this single-domain batch benchmark, and it changes no output —
  but it is a diagnostic, not a build you ship.

The useful reading is therefore **not** "disable polls for 15%" — that build is unshippable
and the mechanism is not understood well enough to design around. The shippable win in the
same loop came from somewhere else entirely: see the strength-reduction result below, which
is worth **+11.0%** with polls left in place, and stacks with poll removal to **+21.7%** —
proof that the two are independent causes.

### Strength reduction by hand: +8.9% under flambda2, +10.8% under OCaml 5.3.0, −5.5% under 5.4.0

flambda2 does not build a derived induction variable for `d.(b0 + i)` where `b0` is
loop-invariant, so it recomputes `b0 + i` with a `mov`/`add` pair per row per iteration —
8 instructions of the 23 in the loop. A six-line reproducer shows it is not register
pressure: in the *same* loop, `x.(i)` compiles to `vmulsd -4(%rbx,%rdx,4)` with zero address
arithmetic, because there `i` *is* the induction variable.

Doing it by hand — carrying four running indices and incrementing them, with the additions in
the same order over the same values — removes all 8 instructions *and* the spill:

| compiler | delta | rounds |
|---|---:|---|
| OxCaml 5.2.0+ox (flambda2) | **+8.9%** | 8/9 |
| stock ocamlopt **5.3.0** | **+10.8%** | 9/9 |
| stock ocamlopt **5.4.0** | **−5.5%** | 2/13 |

**The sign flips between two stock compiler releases**, which is worth more than the
speedup itself. A dedicated paired run — same source, same flags, same machine, interleaved,
only `ocamlopt` differing — puts it beyond doubt:

```
ocamlopt 5.3.0   +8.5%   13/13 rounds
ocamlopt 5.4.0   -5.5%    2/13 rounds
```

So "hand strength reduction helps OCaml" is not a portable statement; it is a statement about
a particular backend. `tools/bench_variants.sh` builds the stock variants with whatever
`ocamlopt` is on `PATH`, which on this machine is the Debian system compiler at 5.3.0 — set
`MG_OCAML_SWITCH` to pin something else. An earlier version of this section reported only the
5.4.0 number and called the change flambda2-specific; that was wrong, and it was wrong
because it generalized from one compiler build.

Worth flagging separately, and *not* established here: at baseline the 5.3.0 build also ran
materially faster than the 5.4.0 one (434,993 vs 323,395 tok/s). Those are differently
*built* compilers — a Debian system package against an opam-built switch — so this is not
evidence of an upstream regression between 5.3 and 5.4, and it is recorded only as something
that would need a controlled build to settle.

Even under flambda2 the instruction count barely moves (23 → ~22): the 8 address
recomputations and the spill go away, but flambda2 then spends three instructions shuffling
registers to increment the loop counter where one `add` would do. The win is real, but it
comes from removing a memory access, not from a shorter loop.

Because it helps two of the three backends and hurts the third, it ships as a build switch
rather than an edit to the shared source — the two OCaml ports are held byte-identical on
purpose:

```bash
MG_SR=1 bash impl/oxcaml/build.sh     # flambda2
MG_SR=1 bash impl/ocaml/build.sh      # stock
```

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

- **Get the OCaml `linear` loop back inside eight registers.** The poll measurement above
  shows the shipped kernel is exactly one register short, and pays a per-iteration stack
  reload for it. Two candidates, both of which keep the safepoint: a **2-way unroll** (two
  row bases live instead of four — trades one accumulator chain for the spill), and a
  **`cols`-specialized full unroll** for the two shapes that actually occur (16 and 64),
  which removes the live index and bound entirely and folds every offset into the addressing
  mode. Verified in isolation: given a constant offset from a runtime base, flambda2 emits
  `-4(%rsi,%rdi,4)`, `4(...)`, `12(...)` with *zero* address arithmetic.
- **Wider unrolling** (8-way) now that 4-way is known to pay, especially in OCaml.
- **The same treatment for the attention accumulation loops**, which are still scalar chains.
  The region profiler says these are exactly where flambda2 still beats the stock compiler on
  the shipped builds, which is the clearest available hint that they have headroom left.
- **Flatten the KV cache** into one allocation indexed by `layer*block_size*n_embd + slot*n_embd`.
- **`lm_head`'s 27 rows** leave a 3-row tail on the slow path after 4-way unrolling.

Roughly 20–30% of runtime is `exp` and `pow` calls the numerics contract *requires* (`pow` in
rmsnorm, `exp` in every softmax). That bounds any remaining win.

Profiling detail — where the cycles go per region — is in [PORTING.md section 7](PORTING.md).
