# Task: implement induction-variable strength reduction in flambda2

Hand this file to a fresh session. It is self-contained.

**Goal.** Make flambda2 strength-reduce `a.(base + i)` in loops, so that the index is
carried rather than recomputed. Produce a **commit-ready minimal change** on a local
branch. **Do not open a PR. Do not push.** Then verify it against the benchmark that
found the gap.

---

## 1. The finding you are implementing a fix for

flambda2 does not create a *derived induction variable* for `base + i` when `base` is
loop-invariant and `i` is the loop counter. It rebuilds the sum with a `mov`/`add` pair
on every iteration, for every such access.

Minimal reproducer — note the control is **inside the same loop**, so register pressure,
scheduling and everything else are held constant:

```ocaml
(* repro.ml *)
let f (d : float array) (x : float array) b0 cols =
  let a = ref 0.0 in
  for i = 0 to cols - 1 do
    a := !a +. (d.(b0 + i) *. x.(i))
  done; !a
```

```
$ ocamlopt -O3 -unsafe -S repro.ml
```

Current output (the loop body):

```asm
        movl    $1, %edx                     ; i := 0  (OCaml ints are tagged 2n+1)
.L109:
        movq    %rdi, %rcx                   ; <-- reload loop-INVARIANT b0
        addq    %rdx, %rcx                   ; <-- recompute b0 + i, every iteration
        vmovsd  -8(%rax,%rcx,4), %xmm1       ; d.(b0+i)   costs 2 extra instructions
        vmulsd  -4(%rbx,%rdx,4), %xmm1, %xmm1 ; x.(i)     costs 0 — i IS the IV
        vaddsd  %xmm1, %xmm0, %xmm0
        cmpq    %rsi, %rdx
        je      .L118
        addq    $2, %rdx                     ; i++  (tagged stride 2)
        cmpq    (%r14), %r15                 ; GC safepoint poll
        jbe     .L126
        jmp     .L109
```

Wanted output:

```asm
        leaq    (%rdi,%rdx), %rcx            ; preheader: j := b0 + i0, once
.L109:
        vmovsd  -8(%rax,%rcx,4), %xmm1       ; d.(j) — no arithmetic
        vmulsd  -4(%rbx,%rdx,4), %xmm1, %xmm1
        vaddsd  %xmm1, %xmm0, %xmm0
        ...
        addq    $2, %rdx                     ; i++
        addq    $2, %rcx                     ; j++   <-- the derived IV
```

Two instructions per access per iteration become one, and the one that remains is off the
multiply's dependency chain.

**Note what is NOT the problem, so you do not chase it:**

- **Not integer tagging.** OCaml's `2n+1` is absorbed free by scaled-index addressing:
  `4*(2n+1) = 8n+4`, so `-4(%rbx,%rdx,4)` *is* `base + 8n` exactly. The tag costs nothing.
- **Not register pressure.** The reproducer above has registers to spare and still does it.
- **Not `-unsafe`.** It happens with and without bounds checks.

## 2. Why this matters in OCaml specifically

A C/C++ port never writes the index form: it hoists a `const double*` and walks it, so
there is no arithmetic to eliminate. OCaml **cannot** do that — its GC is precise and must
find a heap block's header from any pointer it scans, and the header sits immediately
*before* the data, so a pointer into the middle of an array is not a representable value.
The index form is therefore forced by the language, and then the compiler declines to
optimize what the language obliged the programmer to write.

## 3. Verified: no such pass exists today

Checked at `github.com/oxcaml/oxcaml` HEAD (2026-09-15, `VERSION 5.4.0+ox`):

- flambda2's own `middle_end/flambda2/docs/encyclopaedia.md` ("Encyclopædia of
  Optimizations", its reference of every middle-end transformation) lists CPS conversion,
  canonicalization, unboxing, variant unboxing, match optimizations, and five
  interprocedural passes. **Zero** occurrences of *loop*, *induction*, *index*,
  *strength*, *arithmetic* or *algebraic* in 629 lines.
- **29,035 commits**: 0 mentioning "induction", 0 mentioning "strength reduction".
- No LICM, GVN, reassociation, loop unrolling, unswitching or code motion passes exist.
- Backend pipeline (`backend/asmgen.ml`) is cleanup, not optimization: CSE → polls →
  comballoc → deadcode → prologue → regalloc → stack checks → block merge → layout.
  `Cfg_cse` is documented as value numbering **over basic blocks** — local, and the wrong
  tool anyway, since `b0 + i` differs every iteration and so is never redundant.
- `backend/cfg/cfg_loop_infos.ml` **already computes back edges, loop membership and loop
  headers** — but its only consumers are register allocation, GC poll placement, prologue
  insertion and stack checks. No transformation pass consumes it.

The one `strength reduction` comment in the tree (`lambda/translprim.ml:1809`) is about
specializing a primitive by result type — unrelated. `loopify` converts self-recursive
functions into loops — a different transformation.

## 4. Where to implement it

**Strongly consider flambda2 rather than the backend.** In flambda2 a loop is a
*recursive continuation* and its induction variable is a *continuation parameter*, so
adding a derived IV is adding a parameter — and the machinery for that already exists:

- `middle_end/flambda2/simplify/one_recursive_handler.mli`
  — a loop: `{ params : Bound_parameters.t; handler : Flambda.Expr.t; is_cold : bool }`
- `middle_end/flambda2/simplify/continuation_extra_params_and_args.mli`
  — adds extra parameters and their per-call-site arguments. Critically it already has

  ```ocaml
  module Extra_arg : sig
    type t =
      | Already_in_scope of Simple.t
      | New_let_binding of Variable.t * Flambda_primitive.t
      ...
  ```

  `New_let_binding` lets an extra argument be a *newly computed primitive* at each call
  site. That is precisely a derived IV: extra param `j`, with extra arg `b0 + i0` at the
  loop entry and `j + 1` at the back edge. This mechanism is already used for unboxing.
- `middle_end/flambda2/simplify/simplify_apply_cont_expr.ml` — where the back edge is
  simplified.
- `middle_end/flambda2/simplify/apply_cont_rewrite.ml` — rewriting call sites.

The backend (`Cfg_loop_infos` + a new CFG pass) is the alternative, but the backend has no
SSA form, which makes the analysis materially harder. Use your judgement; justify whichever
you pick in the commit message.

**Minimal viable scope.** A fully general IV framework is out of scope. It is acceptable
and preferred to handle the narrow, high-value shape first:

> inside a loop whose parameter `i` has a known constant stride, an expression
> `invariant + i` used as an array index

and leave anything else untouched. Document precisely what is and is not covered.

## 5. Correctness bar

This must not change program semantics. In particular:

- **Integer overflow.** `b0 + i` is tagged-int arithmetic that wraps. The carried `j` must
  wrap identically. Do not introduce a transformation valid only for non-overflowing values.
- **The derived IV must not be computed where the original was not.** If the loop body may
  exit before the access, hoisting the *addition* is fine (it is pure), but be sure you are
  not hoisting anything effectful or trapping.
- **Bounds checks.** Without `-unsafe`, `a.(b0+i)` also performs a bounds check. The
  transformation must keep it, and keep it checking the same value.
- `make check-fmt` must pass — CI requires `middle_end/flambda2/` and `backend/cfg/` to be
  formatted. Run `make fmt`.

## 6. Build

```bash
cd ~/oxsrc                     # existing clone, but it is shallow + blobless:
git fetch --unshallow          #   make it a full clone before building
# needs a bootstrap OCaml 5.4.0 on PATH, plus dune and menhir at required versions.
# opam switch 5.4.0 exists on this machine:
eval "$(opam env --switch=5.4.0 --set-switch)"
./configure --enable-flambda2 --prefix=$HOME/oxinstall
make -j"$(nproc)"
```

`make hacking` starts dune in polling mode and rebuilds only the compiler — much faster
for iterating. See `HACKING.md`.

Expect the first full build to take a long time. If the build is broken for environmental
reasons (missing dune/menhir version, bootstrap failure), **say so and stop** — do not
fake a result.

## 7. Tests

```bash
make test                # synonym for runtest-upstream: the whole testsuite
make check-fmt           # formatting gate that CI enforces
```

To run part of it, see "Running only part of the upstream testsuite" in `HACKING.md`.
Report the pass/fail delta against a clean build of the same tree — a handful of
pre-existing failures is normal, so **establish the baseline first**, then compare.

## 8. Verification against the microgpt benchmark

The benchmark that found this lives at `/mnt/d/projects/llamaport`. It runs five language
ports of the same transformer inference kernel under a strict bit-identical-output gate.

Build the port with your patched compiler and check three things.

**(a) Output must be bit-identical.** Any change here means the transformation is wrong:

```
hash = 0xae6c6ffbd8f5b02c
ppl  = 10.789614873329409
```

**(b) The speedup should appear without the hand workaround.** The benchmark already has a
hand-written version of exactly this transformation, behind `MG_SR=1`. Measured with the
*stock* compiler:

| build | tok/s | delta |
|---|---:|---|
| `MG_SR=0` (as written) | 464,428 | — |
| `MG_SR=1` (hand strength-reduced) | 502,065 | **+8.9%**, 8/9 rounds |

With your patched compiler, **`MG_SR=0` should move up toward the `MG_SR=1` number**.

**(c) The two should converge.** This is the real proof. If the compiler now does the
transformation itself, then `MG_SR=1` has nothing left to add, so `MG_SR=0` and `MG_SR=1`
should land within noise of each other. A large remaining gap means the pass is not firing
on the real kernel — investigate with `ocamlopt -S` on `impl/oxcaml/main.ml` and confirm
the `mov`/`add` pairs are gone from `camlMain__linear`.

How to run it (inside WSL/Linux, from the repo root):

```bash
cd /mnt/d/projects/llamaport
# point the build at your patched compiler, then:
MG_SR=0 OUT=/tmp/sr0 bash impl/oxcaml/build.sh
MG_SR=1 OUT=/tmp/sr1 bash impl/oxcaml/build.sh
for v in /tmp/sr0 /tmp/sr1; do
  $v --weights "$PWD/weights/microgpt.bin" --data "$PWD/data/val.txt" \
     --samples 200 --seed 1234 --temperature 0.5 --pin -1 \
     --mode all --repeats 1 --time-budget 0.05 | python3 -c \
     "import json,sys; r=json.load(sys.stdin); print(r['gen']['output_fnv1a64'], r['ppl']['perplexity'])"
done
```

For timings use interleaved rounds under `taskset`, never one run each —
`tools/bench_variants.sh` in that repo shows the methodology, and `tools/track_opt.py`
compares two binaries directly.

## 9. Deliverable

- A local branch with **one commit** (or a small, clean series) containing the minimal
  change. Commit message should state the transformation, where it was implemented and
  why there rather than the alternative, and what is deliberately out of scope.
- **No PR, no push.**
- A short report covering: what you changed; the before/after assembly for the §1
  reproducer; testsuite baseline vs after; and the three benchmark checks from §8.

## 10. Honesty requirements

This is genuine compiler work in a codebase with no existing loop-optimization
infrastructure, and it may not be completable. That is an acceptable outcome; a fabricated
one is not.

- If you cannot build the compiler, say so and stop.
- If the pass proves larger than a minimal change, say so, and hand back the analysis plus
  whatever partial work stands on its own.
- Never report a benchmark number you did not measure, and never report a test as passing
  that you did not run.
- If the output hash changes, the transformation is **wrong** — do not rationalize it,
  report it.
