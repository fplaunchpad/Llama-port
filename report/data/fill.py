r"""Replace number tokens in the report sources with values from run W.

    python report/data/fill.py [--check] FILE...

Tokens (a, b, k are variant names; generation mode unless the token ends in p):
  @P{a,b}@   paired change of b over a, with rounds won:   $+12.5\%$ (19/21)
  @D{a,b}@   paired change only:                          $+12.5\%$
  @A{a,b}@   its magnitude, no sign:                      12.5\%
  @W{a,b}@   rounds b won:                                19/21
  @X{a,b}@   paired median as a ratio:                    $1.22\times$
  @I{a,b}@   interquartile range of the per-round change: $[+9.9, +14.9]\%$
  @G{k}@     gap to scalar C++, cpp_novec / k:            $1.22\times$
  @GU{k}@    gap to vectorised C++, cpp_unroll / k:       $1.29\times$
  @T{k}@     median tokens/s:                             625,928
  @Y{k}@     k / python:                                  $93\times$
  @R{a,b}@   ratio of medians a / b:                      $1.05\times$
  @Pp{..}@, @Dp{..}@, @Tp{..}@, @Gp{..}@  the same in scoring mode.
--check prints every token with its value and changes nothing.
"""
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyse  # noqa: E402

DATA = {m: analyse.load(m) for m in ("gen", "ppl")
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"run_w_{m}.txt"))}
MED = {m: {k: statistics.median(v) for k, v in r.items()} for m, r in DATA.items()}
TOK = re.compile(r"@(P|D|A|W|I|X|G|GU|T|Y|R)(p?)\{([^}]*)\}@")


def sgn(x):
    return f"+{x:.1f}" if x >= 0 else f"-{-x:.1f}"


def value(kind, mode, args):
    res, med = DATA[mode], MED[mode]
    a = [s.strip() for s in args.split(",")]
    if kind == "X":
        return f"${1 + analyse.paired(res, a[0], a[1])[1] / 100:.2f}\\times$"
    if kind in ("P", "D", "A", "W", "I"):
        q1, m, q3, w, n = analyse.paired(res, a[0], a[1])
        return {"P": f"${sgn(m)}\\%$ ({w}/{n})", "D": f"${sgn(m)}\\%$", "A": f"{abs(m):.1f}\\%",
                "W": f"{w}/{n}", "I": f"$[{sgn(q1)}, {sgn(q3)}]\\%$"}[kind]
    if kind == "G":
        return f"${med['cpp_novec'] / med[a[0]]:.2f}\\times$"
    if kind == "GU":
        return f"${med['cpp_unroll'] / med[a[0]]:.2f}\\times$"
    if kind == "T":
        return f"{med[a[0]]:,.0f}"
    if kind == "Y":
        return f"${med[a[0]] / med['python']:.0f}\\times$"
    if kind == "R":
        return f"${med[a[0]] / med[a[1]]:.2f}\\times$"
    raise ValueError(kind)


def sub(m):
    kind, p, args = m.group(1), m.group(2), m.group(3)
    return value(kind, "ppl" if p else "gen", args)


def main():
    check = "--check" in sys.argv
    for path in [a for a in sys.argv[1:] if a != "--check"]:
        s = open(path, encoding="utf-8").read()
        if check:
            for m in TOK.finditer(s):
                print(f"{os.path.basename(path)}: {m.group(0)} -> {sub(m)}")
            continue
        out = TOK.sub(sub, s)
        if out != s:
            open(path, "w", encoding="utf-8", newline="\n").write(out)
            print("filled", path)


if __name__ == "__main__":
    main()
