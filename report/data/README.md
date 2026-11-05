# Run W: the data behind every microgpt number in the report

- `run_w_gen.txt`, `run_w_ppl.txt`: raw per-round throughput (variant, tokens/s), 62 builds x 21 rounds, 31 Oct 2026.
  Built and timed with the benchmark entry point `bench/bench.py` and its variant registry `bench/variants.py`
  (OxCaml 5.4.0-ox7 release, the pull request rebased on OxCaml main, stock OCaml 5.3.0 and its port).
- `scripts/bench.py`, `scripts/variants.py`: copies of the benchmark entry point and variant registry that built and
  timed run W (they run from `bench/` in the repository).
- `pr-patches/`: the 24 patches of the pull-request compiler, applied with `git am` to OxCaml main
  `327965f0e72292605600a3c5d9a7bf50c59b345a` (`BASE_COMMIT.txt`).
  Applied, they are commit `91acf6b7e9921529ac0d96506abcf6032f31ed4a` of
  https://github.com/AadiSrivastava05/oxcaml/tree/ugrc2-rebased.
- `profile_regions.log`: region profiles from an earlier, separate profiling session (Figure 6).
- `bench_unified.sh`, `make_bench.py`: the scripts of the earlier unified run; kept for reference.
- `analyse.py`: medians, interquartile ranges and paired comparisons.
- `templates/`: the report sections with number tokens (`@P{a,b}@` etc., see `fill.py`).

To refresh every number after a new run:

    cp report/data/templates/*.tex report/sections/
    python report/data/fill.py report/sections/*.tex
    python report/figures/make_figures.py

Edit text in `templates/`, not in `sections/`, so that a refill does not lose the edit.
Sentences whose wording depends on a value's size or sign (§7, §8, §12, §13, §15) need re-reading after a refill.
