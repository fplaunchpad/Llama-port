#!/usr/bin/env python3
"""Build, check and time the variants of bench/variants.py.

    python3 bench/bench.py                          # every variant this machine can build
    python3 bench/bench.py --set headline           # headline | ablation | control | all
    python3 bench/bench.py --concept counted        # one concept, with what it is compared to
    python3 bench/bench.py --only cpp_novec,pr_counted
    python3 bench/bench.py --list                   # the registry as a Markdown table
    python3 bench/bench.py --show pr_counted        # the shell commands that build a variant
    python3 bench/bench.py --summarise report/data/run_w_gen.txt   # effects from saved data

Run from anywhere; paths are relative to the repository. Linux is the reference
platform; on macOS everything runs except the OxCaml builds (OxCaml targets
linux-x86_64) and the x86-only variants, which are reported as skipped. On Windows
run it inside WSL.

The protocol is the report's (Section 4): every variant must reproduce the reference
output before it is timed; each measurement is the best of REPEATS runs of BUDGET
seconds in a fresh process pinned with taskset; ROUNDS interleaved rounds measure
every variant once each; effects are paired medians within rounds. Run W used
SETTLE=300 --set all --rounds 21 --modes "gen ppl"; its raw files are in report/data/.

Environment knobs (same names as the earlier shell script, also CLI flags):
  ROUNDS (9)  REPEATS (3)  BUDGET (0.3)  SAMPLES (200)  MODES ("gen")  PIN (0; -1 off)
  OUTDIR (<tmp>/microgpt-bench)  and the compiler paths MG_OX54_* / MG_OX_PR.
"""
import argparse
import json
import os
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import variants as reg  # noqa: E402

GOLDEN_HASH = "0xae6c6ffbd8f5b02c"        # 200 samples, seed 1234, temperature 0.5
GOLDEN_PPL = "10.789614873329409"
SEED, TEMPERATURE = "1234", "0.5"


# ---------------------------------------------------------------- building
def env_with(extra):
    env = dict(os.environ)
    cargo_bin = os.path.join(reg.HOME, ".cargo", "bin")
    if os.path.isdir(cargo_bin) and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    env.update(extra)
    return env


def commands(v, out, display=False):
    """[(argv, extra_env)] that build variant v into out/<name>, or None for python.
    display=True gives the portable form printed by --show (env-var compiler paths)."""
    r, name = v["recipe"], v["name"]
    dst = os.path.join(out, name)
    k = r["kind"]
    if k == "cxx":
        return [(["g++"] + r["flags"].split() + ["-o", dst, "impl/cpp/infer.cpp"], {})]
    if k == "cargo":
        tgt = os.path.join(out, "rs_" + ("unroll" if r["unroll"] else "plain"))
        argv = ["cargo", "build", "--release", "--manifest-path", "impl/rust/Cargo.toml"]
        if not r["unroll"]:
            argv.insert(3, "--no-default-features")
        return [(argv, {"CARGO_TARGET_DIR": tgt}),
                (["cp", os.path.join(tgt, "release", "microgpt_infer"), dst], {})]
    if k == "ml":
        e = dict(r["env"], OUT=dst)
        if r["compiler"]:
            envname, path, _ = reg.COMPILERS[r["compiler"]]
            e["MG_OCAMLOPT"] = "$" + envname if display else path
        return [(["bash", r["script"]], e)]
    if k == "nop":
        py = "python3" if display else sys.executable
        return [([py, "tools/nop_polls.py", os.path.join(out, r["src"]), dst], {})]
    if k == "copy":
        return [(["cp", os.path.join(out, r["src"]), dst], {})]
    return None


def quote(s):
    """shlex.quote, but leave $VAR references expandable."""
    if s.startswith("$"):
        return '"' + s + '"'
    return shlex.quote(s)


def shell_line(argv, e):
    pre = " ".join(f"{k}={quote(val)}" for k, val in e.items())
    return (pre + " " if pre else "") + " ".join(quote(a) for a in argv)


def run_command(v, out):
    if v["recipe"]["kind"] == "python":
        return [sys.executable, os.path.join(ROOT, "impl", "python", "infer.py")]
    return [os.path.join(out, v["name"])]


def build(v, out, logdir):
    """Returns (ok, message)."""
    r = v["recipe"]
    if r["kind"] == "python":
        return True, ""
    if r["kind"] == "ml" and r["compiler"]:
        envname, path, _ = reg.COMPILERS[r["compiler"]]
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            return False, f"SKIPPED (no compiler at {path}; set {envname})"
    if r["kind"] in ("nop", "copy") and not os.path.exists(os.path.join(out, r["src"])):
        return False, f"SKIPPED ({r['src']} was not built)"
    log = os.path.join(logdir, v["name"] + ".log")
    with open(log, "w") as fh:
        for argv, e in commands(v, out):
            fh.write("$ " + shell_line(argv, e) + "\n")
            fh.flush()
            try:
                p = subprocess.run(argv, cwd=ROOT, env=env_with(e), stdout=fh,
                                   stderr=subprocess.STDOUT)
            except FileNotFoundError:
                return False, f"SKIPPED ({argv[0]} not found)"
            if p.returncode != 0:
                fh.flush()
                if "refusing to build" in open(log).read():  # toolchain absent, not a bug
                    return False, f"SKIPPED (no suitable compiler; see {log})"
                return False, f"FAILED (see {log})"
    return True, ""


# ---------------------------------------------------------------- running
def common_args(samples):
    return ["--weights", os.path.join(ROOT, "weights", "microgpt.bin"),
            "--data", os.path.join(ROOT, "data", "val.txt"),
            "--samples", str(samples), "--seed", SEED, "--temperature", TEMPERATURE,
            "--pin", "-1"]


def run_json(cmd, args, prefix=()):
    p = subprocess.run(list(prefix) + cmd + args, cwd=ROOT, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, text=True)
    return json.loads(p.stdout)


def gate(names, cmds, samples, out):
    """Every variant must produce the reference output. Returns the names that pass."""
    print("=== correctness: every variant must produce identical output ===")
    rows = []
    for n in names:
        try:
            r = run_json(cmds[n], common_args(samples) + ["--mode", "all", "--repeats", "1",
                                                          "--time-budget", "0.05"])
            rows.append((n, r["gen"]["output_fnv1a64"], repr(r["ppl"]["perplexity"])))
        except Exception as e:  # noqa: BLE001 - any failure is a failed gate
            rows.append((n, "ERROR", type(e).__name__))
    with open(os.path.join(out, "hashes.txt"), "w") as fh:
        for row in rows:
            fh.write(" ".join(row) + "\n")
    if samples == 200:
        want = (GOLDEN_HASH, GOLDEN_PPL)
    else:  # the hash depends on --samples; fall back to agreement with the majority
        tally = {}
        for _, h, p in rows:
            tally[(h, p)] = tally.get((h, p), 0) + 1
        want = max(tally, key=tally.get)
    ok = []
    for n, h, p in rows:
        good = (h, p) == want
        print(f"  {n:30s} {h}  ppl={p}{'' if good else '   <-- DIFFERS, not timed'}")
        if good:
            ok.append(n)
    bad = len(rows) - len(ok)
    print("\n  " + ("ALL IDENTICAL - differences below are real work saved" if not bad else
                    f"*** {bad} VARIANT(S) DISAGREE - excluded from timing ***"))
    if samples == 200:
        print(f"  reference: {GOLDEN_HASH}  ppl={GOLDEN_PPL}")
    print()
    return ok


def pinning(pin):
    if pin == -1:
        return [], "disabled (PIN=-1)"
    if shutil.which("taskset"):
        return ["taskset", "-c", str(pin)], f"taskset cpu {pin}"
    print("warning: taskset not found; running unpinned. Expect more variance; prefer the\n"
          "         paired 'rounds won' figures over absolute tokens/s.", file=sys.stderr)
    return [], "UNPINNED (no taskset on this platform)"


def time_mode(mode, names, cmds, a, out):
    prefix, how = pinning(a.pin)
    print(f"=== {mode}: {a.rounds} interleaved rounds, {how}, "
          f"best of {a.repeats} x {a.budget}s ===")
    path = os.path.join(out, f"t_{mode}.txt")
    args = common_args(a.samples) + ["--mode", mode, "--repeats", str(a.repeats),
                                     "--time-budget", str(a.budget)]
    with open(path, "w") as fh:
        for r in range(a.rounds):
            print(f"  round {r + 1}/{a.rounds}", file=sys.stderr, flush=True)
            for n in names:
                try:
                    tps = run_json(cmds[n], args, prefix)[mode]["tokens_per_sec_best"]
                except Exception:  # noqa: BLE001 - keep the rounds aligned
                    print(f"  {n}: run failed in round {r + 1}", file=sys.stderr)
                    tps = float("nan")
                fh.write(f"{n} {tps!r}\n")
                fh.flush()
    return path


# ---------------------------------------------------------------- summarising
def load(path):
    res = OrderedDict()
    for line in open(path):
        k, val = line.split()
        res.setdefault(reg.resolve(k), []).append(float(val))
    return res


def finite(xs):
    return [x for x in xs if x == x]  # drops NaN (a failed run)


def quart(xs):
    xs = finite(xs)
    if len(xs) < 2:
        return xs[0], xs[0], xs[0]
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def paired(res, prev, cur):
    """Per-round % change of cur over prev: (q1, median, q3, rounds won, rounds)."""
    d = finite([(c - p) / p * 100 for p, c in zip(res[prev], res[cur])])
    q1, m, q3 = quart(d)
    return q1, m, q3, sum(x > 0 for x in d), len(d)


def summarise(path, concepts=None):
    res = OrderedDict((k, v) for k, v in load(path).items() if finite(v))
    med = {k: statistics.median(finite(v)) for k, v in res.items()}
    nrounds = max(len(v) for v in res.values())
    print(f"--- {os.path.basename(path)}: {len(res)} variants x {nrounds} rounds ---\n")
    nov, py = med.get("cpp_novec"), med.get("python")
    print("| variant | group | tokens/s (median) | IQR | gap to cpp_novec | x python |")
    print("|---|---|---:|---:|---:|---:|")
    for k, v in res.items():
        q1, m, q3 = quart(v)
        grp = reg.BY_NAME[k]["group"] if k in reg.BY_NAME else "?"
        gap = f"{nov / m:.2f}x" if nov else "-"
        xpy = f"{m / py:.0f}x" if py else "-"
        print(f"| {k} | {grp} | {m:,.0f} | {(q3 - q1) / m * 100:.1f}% | {gap} | {xpy} |")
    print("\nEffects, by concept: paired median change of the second build over the first,")
    print("[interquartile range of the per-round change], rounds the second build won.")
    for key, title, where, pairs in reg.CONCEPTS:
        if concepts and key not in concepts:
            continue
        shown = [(lbl, a, b) for lbl, a, b in pairs if a in res and b in res]
        if not shown:
            continue
        print(f"\n  {title}   [{where}]")
        for lbl, a, b in shown:
            q1, m, q3, w, n = paired(res, a, b)
            print(f"    {lbl:52s} {a:>29s} -> {b:29s} {m:+6.1f}%  "
                  f"[{q1:+5.1f}, {q3:+5.1f}]  {w:2d}/{n}")
    print()


# ---------------------------------------------------------------- selection and CLI
def select(a):
    if a.only:
        names = [reg.resolve(n.strip()) for n in a.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in reg.BY_NAME]
        if unknown:
            sys.exit(f"unknown variant(s): {', '.join(unknown)} (see --list)")
        want = set(names)
    elif a.concept:
        keys = a.concept.split(",")
        bad = [k for k in keys if k not in reg.CONCEPT_KEYS]
        if bad:
            sys.exit(f"unknown concept(s): {', '.join(bad)}; one of {', '.join(reg.CONCEPT_KEYS)}")
        want = {v["name"] for v in reg.VARIANTS if v["concept"] in keys}
        for key, _, _, pairs in reg.CONCEPTS:  # and what they are compared against
            if key in keys:
                for _, x, y in pairs:
                    want |= {x, y}
        want |= {"cpp_novec"}
    elif a.set == "all":
        want = set(reg.BY_NAME)
    else:
        want = {v["name"] for v in reg.VARIANTS if v["group"] == a.set} | {"cpp_novec"}
    return [v["name"] for v in reg.VARIANTS if v["name"] in want]  # registry order


def with_deps(names):
    need = set(names)
    for n in names:
        r = reg.BY_NAME[n]["recipe"]
        if r["kind"] in ("nop", "copy"):
            need.add(r["src"])
    return [v["name"] for v in reg.VARIANTS if v["name"] in need]


def list_registry():
    print("| variant | group | concept | what it is | compiler | build |")
    print("|---|---|---|---|---|---|")
    for v in reg.VARIANTS:
        r = v["recipe"]
        if r["kind"] == "ml":
            comp = reg.COMPILERS[r["compiler"]][2] if r["compiler"] else (
                "OxCaml 5.2.0+ox" if "oxcaml" in r["script"] else "stock ocamlopt")
            env = dict(r["env"])
            if r["compiler"]:
                env["MG_OCAMLOPT"] = "$" + reg.COMPILERS[r["compiler"]][0]
            how = " ".join(f"{k}={val}" if " " not in val and val else f'{k}="{val}"'
                           for k, val in env.items())
            how = f"`{how} bash {r['script']}`"
        elif r["kind"] == "cxx":
            comp, how = "g++", f"`g++ {r['flags']}`"
        elif r["kind"] == "cargo":
            comp = "rustc"
            how = "`cargo build --release`" + ("" if r["unroll"] else " `--no-default-features`")
        elif r["kind"] == "nop":
            comp, how = "-", f"`tools/nop_polls.py` on `{r['src']}`"
        elif r["kind"] == "copy":
            comp, how = "-", f"copy of `{r['src']}`"
        else:
            comp, how = "CPython", "`python3 impl/python/infer.py`"
        print(f"| `{v['name']}` | {v['group']} | {v['concept']} | {v['desc']} | {comp} | {how} |")


def main():
    ev = os.environ.get
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--set", default="all", choices=["all", "headline", "ablation", "control"])
    g.add_argument("--concept", help="comma-separated: " + ", ".join(reg.CONCEPT_KEYS))
    g.add_argument("--only", help="comma-separated variant names")
    ap.add_argument("--rounds", type=int, default=int(ev("ROUNDS", 9)))
    ap.add_argument("--repeats", type=int, default=int(ev("REPEATS", 3)))
    ap.add_argument("--budget", type=float, default=float(ev("BUDGET", 0.3)))
    ap.add_argument("--samples", type=int, default=int(ev("SAMPLES", 200)))
    ap.add_argument("--modes", default=ev("MODES", "gen"), help='"gen", "ppl" or "gen ppl"')
    ap.add_argument("--pin", type=int, default=int(ev("PIN", 0)), help="-1 disables pinning")
    ap.add_argument("--out", default=ev("OUTDIR", os.path.join(tempfile.gettempdir(),
                                                               "microgpt-bench")))
    ap.add_argument("--build-only", action="store_true", help="build and check, no timing")
    ap.add_argument("--list", action="store_true", help="print the registry and exit")
    ap.add_argument("--show", metavar="NAME", help="print how a variant is built and exit")
    ap.add_argument("--summarise", nargs="+", metavar="FILE",
                    help="summarise saved raw files (e.g. report/data/run_w_gen.txt)")
    a = ap.parse_args()

    if a.list:
        return list_registry()
    if a.show:
        v = reg.BY_NAME.get(reg.resolve(a.show)) or sys.exit(f"unknown variant {a.show}")
        print(f"# {v['name']} ({v['group']}, {v['concept']}): {v['desc']}")
        r = v["recipe"]
        if r["kind"] == "ml" and r["compiler"]:
            envname, path, what = reg.COMPILERS[r["compiler"]]
            print(f"# compiler: {what}; ${envname} defaults to {path}")
        cmds = commands(v, "$OUT", display=True)
        for argv, e in cmds or [(["python3", "impl/python/infer.py"], {})]:
            print(shell_line(argv, e))
        return
    if a.summarise:
        concepts = a.concept.split(",") if a.concept else None
        for f in a.summarise:
            summarise(f, concepts)
        return

    names = select(a)
    out = os.path.abspath(a.out)
    marker = os.path.join(out, ".microgpt-bench")
    if os.path.isdir(out) and os.listdir(out):
        if not os.path.exists(marker):
            sys.exit(f"{out} exists and was not made by bench.py; choose another --out/OUTDIR")
        shutil.rmtree(out)
    logdir = os.path.join(out, "logs")
    os.makedirs(logdir, exist_ok=True)
    open(marker, "w").close()

    print(f"=== building {len(names)} variant(s) into {out} ===")
    built = []
    for n in with_deps(names):
        ok, msg = build(reg.BY_NAME[n], out, logdir)
        tag = "" if n in names else "  (dependency, not timed)"
        print(f"  {n:30s} {'ok' if ok else msg}{tag}")
        if ok and n in names:
            built.append(n)
    print()
    if not built:
        sys.exit("nothing built")

    cmds = {n: run_command(reg.BY_NAME[n], out) for n in built}
    passed = gate(built, cmds, a.samples, out)
    if a.build_only or not passed:
        return 0 if len(passed) == len(built) else 1

    settle = int(ev("SETTLE", 0))  # seconds idle after building, before timing
    if settle:
        print(f"=== settling {settle}s ===", flush=True)
        time.sleep(settle)

    for mode in a.modes.split():
        path = time_mode(mode, passed, cmds, a, out)
        summarise(path, a.concept.split(",") if a.concept else None)
    print(f"raw per-round data: {out}/t_<mode>.txt  (format of report/data/run_w_<mode>.txt)")
    return 0 if len(passed) == len(built) else 1


if __name__ == "__main__":
    sys.exit(main())
