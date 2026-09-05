"""
Measure generation speed across builds, with a correctness guard.

Use this whenever you try an optimization, so before/after numbers are gathered the
same way every time. It interleaves the binaries (so machine drift hits them all
equally) and checks that every build produces the *same* generated text. A build
that is faster but produces different text is a bug, not an optimization.

  # compare any set of builds
  python tools/track_opt.py base=path/to/old.exe new=path/to/new.exe

  # compare the current C++ and Rust builds
  python tools/track_opt.py

It prints a markdown table row you can paste straight into OPTIMIZATIONS.md.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = ".exe" if os.name == "nt" else ""

# Fixed settings, so every measurement in OPTIMIZATIONS.md is comparable.
SETTINGS = dict(samples="200", temperature="0.5", seed="1234")

DEFAULTS = {
    "cpp": os.path.join(ROOT, "impl", "cpp", "build", "microgpt_infer" + EXE),
    "rust": os.path.join(ROOT, "impl", "rust", "target", "release", "microgpt_infer" + EXE),
}


def measure_once(binary, repeats, budget):
    cmd = [binary,
           "--weights", os.path.join(ROOT, "weights", "microgpt.bin"),
           "--data", os.path.join(ROOT, "data", "val.txt"),
           "--mode", "gen",
           "--samples", SETTINGS["samples"],
           "--temperature", SETTINGS["temperature"],
           "--seed", SETTINGS["seed"],
           "--repeats", str(repeats), "--time-budget", str(budget)]
    extra = {"creationflags": subprocess.HIGH_PRIORITY_CLASS} if os.name == "nt" else {}
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **extra)
    if p.returncode != 0:
        raise SystemExit(f"{binary} failed:\n{p.stderr[:800]}")
    g = json.loads(p.stdout)["gen"]
    return g["tokens_per_sec_best"], g["output_fnv1a64"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("builds", nargs="*", help="name=path pairs; defaults to the cpp and rust builds")
    ap.add_argument("--rounds", type=int, default=15, help="interleaved rounds (more = less noise)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--budget", type=float, default=0.25)
    args = ap.parse_args()

    if args.builds:
        bins = {}
        for pair in args.builds:
            name, _, path = pair.partition("=")
            if not path:
                raise SystemExit(f"expected name=path, got {pair!r}")
            bins[name] = path if os.path.isabs(path) else os.path.join(ROOT, path)
    else:
        bins = dict(DEFAULTS)
    for name, path in bins.items():
        if not os.path.exists(path):
            raise SystemExit(f"{name}: not built ({path})")

    # Interleave, so a machine that slows down mid-run penalizes every build equally.
    res = {k: [] for k in bins}
    hashes = {}
    for _ in range(args.rounds):
        for name, path in bins.items():
            tps, h = measure_once(path, args.repeats, args.budget)
            res[name].append(tps)
            hashes[name] = h

    ref = next(iter(bins))
    ref_med = statistics.median(res[ref])
    print(f"\n{args.rounds} interleaved rounds, "
          f"--samples {SETTINGS['samples']} --seed {SETTINGS['seed']} "
          f"--temperature {SETTINGS['temperature']}\n")
    print(f"| build | tok/s (median) | best | sd | vs {ref} | output |")
    print("|---|---:|---:|---:|---:|---|")
    for name, v in res.items():
        med = statistics.median(v)
        sd = statistics.stdev(v) if len(v) > 1 else 0.0
        delta = "reference" if name == ref else f"{(med/ref_med-1)*100:+.1f}%"
        ok = "identical" if hashes[name] == hashes[ref] else "**DIFFERENT**"
        print(f"| {name} | {med:,.0f} | {max(v):,.0f} | {sd:,.0f} | {delta} | {ok} |")

    uniq = set(hashes.values())
    if len(uniq) == 1:
        print(f"\nAll builds produced identical output ({hashes[ref]}).")
    else:
        print(f"\nWARNING: {len(uniq)} different output hashes - these builds are NOT equivalent:")
        for name, h in hashes.items():
            print(f"  {name:16s} {h}")
        return 1

    # Paired sign test against the reference: is any difference real, or just noise?
    if len(bins) > 1:
        print("\nPaired against the reference (noise on this class of machine is 5-8%,"
              "\nso treat anything under ~3% as unresolved without many rounds):")
        for name, v in res.items():
            if name == ref:
                continue
            pd = [(a - b) / b * 100 for a, b in zip(v, res[ref])]
            wins = sum(1 for x in pd if x > 0)
            print(f"  {name:16s} median {statistics.median(pd):+5.1f}%   faster in {wins}/{len(pd)} rounds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
