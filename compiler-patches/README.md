# Compiler patches

Two optimization passes added to the OxCaml compiler (`github.com/oxcaml/oxcaml`, the
flambda-backend fork of OCaml). They are **optional** — the benchmark matrix runs without
them and simply omits four rows.

| patch | what it does | measured |
|---|---|---|
| `0001-Strength-reduce-derived-induction-variables-in-Cmm-loops` | carries `base + i` in a loop parameter instead of rebuilding it every iteration | **+11.4%**, 9/9 rounds |
| `0002-Form-interior-pointers-into-array-rows-in-loops-that-cannot-reach-the-GC` | hoists an interior (`Addr`) pointer per array row so four rows share one index register | **+10.7%**, 9/9 rounds |

Together: **+23.9%** over the unpatched compiler, on identical source, with byte-identical
program output. Both are behind flags (`-no-cmm-strength-reduction`,
`-no-cmm-interior-pointers`) so each can be switched off for an A/B on one binary.

Why they exist: flambda2 has no loop optimizations at all — no strength reduction, no
LICM, no induction-variable analysis. OCaml also forbids interior pointers in general,
because its precise GC must find a block's header from any pointer it scans and the header
sits immediately before the data. Patch 2 forms them only in loops that provably contain
no safepoint, where no collection can occur and so nothing is ever scanned.

## Applying

Both apply on upstream commit `c52688875424f836c3a4aa8d3c0f9840543a57e9`
(`main`, 2026-09-15). Patch 2 applies on top of patch 1.

```bash
git clone https://github.com/oxcaml/oxcaml
cd oxcaml
git checkout -b patched c52688875424f836c3a4aa8d3c0f9840543a57e9
git am /path/to/llamaport/compiler-patches/0001-*.patch
git am /path/to/llamaport/compiler-patches/0002-*.patch
```

## Building

Linux x86-64 only — OxCaml does not target macOS or native Windows. Needs a bootstrap
OCaml 5.4.0 on `PATH`, plus `menhir.20231231` and `dune >= 3.23.0` (and
`ocamlformat.0.29.0` if you intend to run `make check-fmt`).

```bash
eval "$(opam env --switch=5.4.0 --set-switch)"
tools/autogen                       # exits 1 on autoconf warnings; still writes configure
./configure --enable-flambda2 --prefix="$HOME/oxinstall-patched"
make -j"$(nproc)" _install          # _install, not install
```

Expect roughly 35 minutes for a first build.

## Pointing the benchmark at them

`tools/bench_variants.sh` reads three optional paths. Set whichever you have:

```bash
export MG_OX54_BASE=$HOME/oxinstall-baseline/bin/ocamlopt.opt   # pristine, no patches
export MG_OX54_SR=$HOME/oxinstall-sr/bin/ocamlopt.opt           # patch 1 only
export MG_OX54_IP=$HOME/oxinstall-patched/bin/ocamlopt.opt      # patches 1 + 2
bash tools/bench_variants.sh
```

To get all four `ox54_*` rows you need three builds: unpatched, patch 1, patches 1+2. The
fourth row (`ox54_ip_off`) is the patches-1+2 compiler run with
`-no-cmm-interior-pointers`, which reproduces the patch-1 compiler exactly — that is what
makes the interior-pointer comparison single-variable.

## Status

Not upstreamed, not submitted. Patch 2 currently only fires when GC polls are disabled
(`-disable-poll-insertion`, or a build configured `poll_insertion: false`), because a poll
on a loop's back edge is itself a safepoint. In a stock build no loop is poll-free, so it
would not fire. Making it useful by default needs either strip-mining the loop so the
poll-free region is bounded, or derived-pointer tracking in frame tables.
