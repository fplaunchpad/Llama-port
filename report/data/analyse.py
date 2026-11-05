"""Summarise the unified benchmark run (run W) that every microgpt number in the report comes from.

    python report/data/analyse.py [gen|ppl]

Input: run_w_<mode>.txt, one line per measurement ("variant tokens_per_s"), written in round
order by the benchmark script (21 interleaved rounds, each value the best of 3 repeats of
0.3 s in a fresh process, pinned with taskset -c 0).
Output: per-variant median and interquartile range, ratios to the C++ baselines, and the
paired comparisons the report quotes (median per-round change, IQR, rounds won).
"""
import os
import statistics
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))


def load(mode="gen"):
    res = OrderedDict()
    for line in open(os.path.join(HERE, f"run_w_{mode}.txt")):
        k, v = line.split()
        res.setdefault(k, []).append(float(v))
    return res


def quart(xs):
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def paired(res, prev, cur):
    """Per-round % change of cur over prev: (q1, median, q3, wins, n)."""
    d = [(c - p) / p * 100 for p, c in zip(res[prev], res[cur])]
    q1, m, q3 = quart(d)
    return q1, m, q3, sum(x > 0 for x in d), len(d)


PAIRS = [
    # source level
    ("cpp_O2_plain", "cpp_plain"), ("cpp_novec", "cpp_unroll"), ("cpp_novec", "cpp_novec_avx"),
    ("cpp_plain", "cpp_unroll"), ("rust_plain", "rust_unroll"),
    ("oxcaml_unsafe_plain", "oxcaml_unsafe_unroll"), ("oxcaml_safe_plain", "oxcaml_safe_unroll"),
    ("ocaml_unsafe_plain", "ocaml_unsafe_unroll"), ("ocaml_safe_plain", "ocaml_safe_unroll"),
    ("oxcaml_safe_plain", "oxcaml_unsafe_plain"), ("oxcaml_safe_unroll", "oxcaml_unsafe_unroll"),
    ("ocaml_safe_plain", "ocaml_unsafe_plain"), ("ocaml_safe_unroll", "ocaml_unsafe_unroll"),
    ("ocaml_safe_plain", "oxcaml_safe_plain"), ("ocaml_unsafe_plain", "oxcaml_unsafe_plain"),
    ("ocaml_safe_unroll", "oxcaml_safe_unroll"), ("ocaml_unsafe_unroll", "oxcaml_unsafe_unroll"),
    ("oxcaml_safe_plain", "oxcaml_unsafe_unroll"),
    # polls on the shipped compiler
    ("oxcaml_unsafe_plain", "oxcaml_unsafe_plain_pollnop"),
    ("oxcaml_unsafe_plain", "oxcaml_unsafe_plain_pollfree"),
    ("oxcaml_unsafe_unroll", "oxcaml_unsafe_unroll_pollnop"),
    ("oxcaml_unsafe_unroll", "oxcaml_unsafe_unroll_pollfree"),
    # strength reduction by hand
    ("oxcaml_unsafe_unroll", "oxcaml_unsafe_sr"), ("oxcaml_unsafe_sr", "oxcaml_unsafe_sr_pollfree"),
    ("oxcaml_unsafe_unroll", "oxcaml_unsafe_sr_pollfree"),
    ("oxcaml_unsafe_unroll_pollfree", "oxcaml_unsafe_sr_pollfree"),
    ("ocaml_unsafe_unroll", "ocaml_unsafe_sr"),
    # compiler ladder (compilers built without poll insertion)
    ("oxcaml_unsafe_unroll_pollfree", "ox54_base"),
    ("ox54_base", "ox54_sr"), ("ox54_sr", "ox54_ip"), ("ox54_ip_off", "ox54_ip"),
    ("ox54_sr", "ox54_ip_off"), ("ox54_base", "ox54_ip"),
    ("ox54_ip", "ox54_ivs"), ("ox54_ivs_noptr", "ox54_ivs"), ("ox54_ivs", "ox54_licm"),
    ("ox54_base", "ox54_licm"), ("oxcaml_unsafe_unroll_pollfree", "ox54_licm"),
    ("oxcaml_unsafe_sr_pollfree", "ox54_licm"),
    # pull-request compiler (poll insertion on)
    ("pr_off", "pr_all"), ("pr_off_nopoll", "pr_nopoll"),
    ("pr_off", "pr_off_nopoll"), ("pr_all", "pr_nopoll"), ("ox54_licm", "pr_nopoll"),
    ("ox54_base", "pr_off_nopoll"), ("oxcaml_unsafe_unroll", "pr_off"),
    ("pr_all", "pr_counted"), ("pr_off", "pr_counted"), ("pr_counted_noptr", "pr_counted"),
    ("pr_all", "pr_counted_noptr"),
    ("pr_counted", "pr_unchecked"), ("pr_counted", "pr_nopoll"), ("pr_counted", "ox54_licm"),
    ("oxcaml_unsafe_unroll", "pr_counted"), ("pr_counted", "pr_counted_copy"),
    ("pr_counted", "pr_safe_counted"), ("oxcaml_safe_unroll", "pr_safe_counted"),
    # SIMD kernel
    ("oxcaml_unsafe_unroll", "oxcaml_unsafe_simd"), ("pr_off", "pr_simd_off"),
    ("pr_all", "pr_simd"), ("pr_counted", "pr_simd_counted"), ("pr_nopoll", "pr_simd_nopoll"),
    ("pr_simd", "pr_simd_counted"),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "gen"
    res = load(mode)
    med = {k: statistics.median(v) for k, v in res.items()}
    nov, unr = med["cpp_novec"], med["cpp_unroll"]
    py = med.get("python")
    print(f"run W, mode {mode}: {len(res)} variants x {len(next(iter(res.values())))} rounds\n")
    print(f"{'variant':32s} {'median':>10s} {'q1':>10s} {'q3':>10s} {'IQR%':>6s} "
          f"{'novec/x':>8s} {'unroll/x':>8s} {'x/python':>8s}")
    for k, v in sorted(res.items(), key=lambda kv: -med[kv[0]]):
        q1, m, q3 = quart(v)
        print(f"{k:32s} {m:10,.0f} {q1:10,.0f} {q3:10,.0f} {(q3-q1)/m*100:6.1f} "
              f"{nov/m:8.3f} {unr/m:8.3f} {m/py if py else 0:8.1f}")
    print("\npaired: prev -> cur   median [q1, q3] of per-round % change, rounds cur won")
    for a, b in PAIRS:
        if a in res and b in res:
            q1, m, q3, w, n = paired(res, a, b)
            print(f"  {a:30s} -> {b:30s} {m:+7.1f}%  [{q1:+6.1f}, {q3:+6.1f}]  {w:2d}/{n}")


if __name__ == "__main__":
    main()
