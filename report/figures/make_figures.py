"""Generate every figure used by the UGRC 2 report.

Run:  python report/figures/make_figures.py   (writes report/figures/*.pdf)
      add --png to also write PNG previews next to the PDFs.

Every microgpt throughput figure reads run W directly (report/data/run_w_gen.txt,
through report/data/analyse.py), the single run all microgpt numbers in the report
come from, and shows only the report's core set of builds. Figures from other
experiments (region profiles, the width sweep, nx-oxcaml) name their run in a comment.
"""
import os
import statistics
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

OUT = os.path.dirname(os.path.abspath(__file__))
PNG = "--png" in sys.argv

sys.path.insert(0, os.path.join(OUT, "..", "data"))
import analyse  # noqa: E402

U = analyse.load("gen")
UM = {k: statistics.median(v) for k, v in U.items()}


def upair(prev, cur):
    """Paired change of cur over prev in run W: (median %, rounds won, rounds)."""
    _, m, _, w, n = analyse.paired(U, prev, cur)
    return m, w, n

# Validated categorical palette (dataviz reference instance, light mode).
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SURFACE = "#ffffff"

# Language identity is fixed across every figure.
LANG = {"C++": BLUE, "Rust": ORANGE, "OxCaml release": AQUA, "OCaml": YELLOW,
        "OxCaml PR": VIOLET, "Python": MUTED}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8.5,
    "axes.edgecolor": MUTED,
    "axes.linewidth": 0.6,
    "axes.labelcolor": INK2,
    "axes.titlesize": 9.5,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "hatch.linewidth": 0.8,
    "hatch.color": SURFACE,
    "pdf.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.04,
})


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".pdf"))
    if PNG:
        fig.savefig(os.path.join(OUT, name + ".png"), dpi=130)
    plt.close(fig)


def clean(ax, grid_axis="x"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def kfmt(v):
    return f"{v/1000:,.0f}k"


# --------------------------------------------------------------------------
# 1. The gap ladder (headline figure).
#    Run W. (a) source changes, then the poll-free compiler ladder. (b) PR compiler, polls on.
# --------------------------------------------------------------------------
def fig_gap_ladder():
    fair, vec = UM["cpp_novec"], UM["cpp_unroll"]
    panels = [
        ("(a) Source changes", [
            ("first\nport", "oxcaml_safe_plain", AQUA, False),
            ("-unsafe", "oxcaml_unsafe_plain", AQUA, False),
            ("+unroll", "oxcaml_unsafe_unroll", AQUA, False),
            ("+hand\ns.r.", "oxcaml_unsafe_sr", AQUA, False)]),
        ("(b) Pass ladder, pull-request compiler", [
            ("passes\noff", "pr_off", VIOLET, False),
            ("+counted\nloops", "pr_c_off", VIOLET, False),
            ("+s.r.", "pr_c_sr", VIOLET, False),
            ("+i.p.", "pr_c_ip", VIOLET, False),
            ("+inv.\nstr.", "pr_c_ivs", VIOLET, False),
            ("+LICM", "pr_counted", VIOLET, False),
            ("+SSE2\nkernel", "pr_simd_counted", VIOLET, True)]),
        ("(c) Stock OCaml", [
            ("first\nport", "ocaml_safe_plain", YELLOW, False),
            ("-unsafe,\nunroll,\nhand s.r.", "ocaml_unsafe_sr", YELLOW, False),
            ("ported\npasses,\ncounted", "ocaml_pr_counted", YELLOW, False)]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.4), sharey=True,
                             gridspec_kw={"width_ratios": [4, 7, 3], "wspace": 0.06})
    for ax, (title, steps) in zip(axes, panels):
        for x, (lab, k, c, extra) in enumerate(steps):
            v = UM[k]
            ax.bar(x, v / 1000, width=0.72, color=BLUE if extra else c, edgecolor=SURFACE,
                   linewidth=0.8)
            ax.text(x, v / 1000 + 10, f"{fair/v:.2f}x", ha="center", va="bottom",
                    fontsize=6.8, color=INK)
        ax.axhline(fair / 1000, color=INK2, linewidth=1.0, zorder=0)
        ax.axhline(vec / 1000, color=MUTED, linewidth=0.7, zorder=0)
        ax.set_xticks(range(len(steps)))
        ax.set_xticklabels([s[0] for s in steps], fontsize=5.9)
        ax.set_ylim(0, 1000)
        ax.set_title(title, loc="left", fontsize=8.2)
        clean(ax, "y")
    axes[0].set_ylabel("generated tokens / s (thousands)")
    axes[0].text(-0.4, vec / 1000 + 6, "C++ vectorised (cpp_unroll)", fontsize=6.4, color=INK2,
                 ha="left", va="bottom")
    axes[0].text(-0.4, fair / 1000 - 6, "C++ scalar (cpp_novec)", fontsize=6.4, color=INK2,
                 ha="left", va="top")
    handles = [Rectangle((0, 0), 1, 1, color=c) for c in (AQUA, VIOLET, BLUE, YELLOW)]
    fig.legend(handles, ["OxCaml 5.4.0-ox7 release", "pull-request compiler",
                         "PR compiler, SSE2 kernel", "stock OCaml 5.3.0 (+ ported passes)"],
               loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.07), fontsize=7)
    fig.text(0.5, -0.12, "Labels above bars: how many times faster the fair C++ baseline is. "
             "All panels: run W.", ha="center", fontsize=7, color=INK2)
    save(fig, "fig_gap_ladder")


# --------------------------------------------------------------------------
# 2. The core builds of run W (the report's core set; Python is omitted).
# --------------------------------------------------------------------------
CORE = [
    "cpp_plain", "cpp_unroll", "cpp_novec", "cpp_O2_plain", "cpp_novec_avx",
    "rust_plain", "rust_unroll", "python",
    "ocaml_safe_plain", "ocaml_unsafe_sr", "ocaml_pr_counted",
    "oxcaml_safe_plain", "oxcaml_unsafe_plain", "oxcaml_unsafe_unroll", "oxcaml_unsafe_sr",
    "pr_off", "pr_c_off", "pr_c_sr", "pr_c_ip", "pr_c_ivs", "pr_counted",
    "pr_simd_counted",
]
MATRIX_SKIP = {"python"}


def family(name):
    if name.startswith("cpp"):
        return "C++"
    if name.startswith("rust"):
        return "Rust"
    if name.startswith("ocaml"):
        return "OCaml"
    if name.startswith("pr_"):
        return "OxCaml PR"
    return "OxCaml release"


def fig_matrix():
    rows = sorted(((k, UM[k], family(k)) for k in CORE if k not in MATRIX_SKIP),
                  key=lambda r: -r[1])
    fair = UM["cpp_novec"]
    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    n = len(rows)
    for i, (name, v, fam) in enumerate(rows):
        y = n - 1 - i
        ax.barh(y, v / 1000, height=0.74, color=LANG[fam], edgecolor=SURFACE, linewidth=0.6)
        ax.text(v / 1000 + 6, y, f"{kfmt(v)}  ({v/fair:.0%})", va="center", fontsize=6.8, color=INK2)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in rows][::-1], fontsize=7, family="DejaVu Sans Mono")
    ax.axvline(fair / 1000, color=INK2, linewidth=0.9)
    ax.text(fair / 1000 + 4, n - 0.2, "cpp_novec", fontsize=7, color=INK2, va="bottom")
    ax.set_xlim(0, max(r[1] for r in rows) / 1000 * 1.22)
    ax.set_ylim(-0.7, n + 0.3)
    ax.set_xlabel("generated tokens / s (thousands); bracket = share of cpp_novec")
    clean(ax, "x")
    keys = ("C++", "Rust", "OxCaml release", "OxCaml PR", "OCaml")
    handles = [Rectangle((0, 0), 1, 1, color=LANG[k]) for k in keys]
    ax.legend(handles, ["C++ (g++ 14.2)", "Rust 1.98", "OxCaml 5.4.0-ox7 release",
                        "OxCaml pull-request compiler", "stock OCaml 5.3.0 (+ ported passes)"],
              loc="lower right", fontsize=7.2)
    save(fig, "fig_matrix")


# --------------------------------------------------------------------------
# 3. Value of the 4-way unroll per backend (run W, paired; core builds only).
# --------------------------------------------------------------------------
def fig_unroll():
    data = [("OxCaml 5.4.0-ox7 (flambda2)", "oxcaml_unsafe_plain", "oxcaml_unsafe_unroll", AQUA),
            ("C++ (g++ 14.2 -O3)", "cpp_plain", "cpp_unroll", BLUE),
            ("Rust 1.98 (--release)", "rust_plain", "rust_unroll", ORANGE)]
    data = [(lab,) + upair(a, b) + (c,) for lab, a, b, c in data]
    fig, ax = plt.subplots(figsize=(5.4, 1.5))
    for i, (lab, v, w, n, c) in enumerate(data):
        y = len(data) - 1 - i
        ax.barh(y, v, height=0.62, color=c)
        ax.text(v + 3, y, f"{v:+.1f}%  ({w}/{n})", va="center", fontsize=8, color=INK)
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels([d[0] for d in data][::-1])
    ax.set_xlim(min(0, min(d[1] for d in data) - 5), max(d[1] for d in data) * 1.25)
    ax.set_xlabel("throughput gain from the same 4-way unroll of linear (paired median, rounds won)")
    clean(ax, "x")
    save(fig, "fig_unroll")


# --------------------------------------------------------------------------
# 4. Region profiles against cpp_novec (data/profile_regions.log, a separate 7-round run
#    that predates the final rebase).
# --------------------------------------------------------------------------
def load_profile():
    """ns per forward pass by region, per build, from the region-profile log."""
    prof, cur = {}, None
    for line in open(os.path.join(OUT, "..", "data", "profile_regions.log")):
        if "region profile  (" in line:
            cur = line.split()[0].lower()
            prof[cur] = {}
        elif cur and line.split() and line.split()[0] in REGIONS and "%" in line:
            prof[cur][line.split()[0]] = float(line.split()[2].replace(",", ""))
        elif line.startswith("WHERE"):
            cur = None
    return prof


REGIONS = ["mlp", "attn", "qkv", "sample", "lm_head", "wo", "embed"]


def fig_regions():
    prof = load_profile()
    c = prof["cpp_novec"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.9), sharey=True, gridspec_kw={"wspace": 0.08})
    panels = [(axes[0], "oxcaml", "OxCaml 5.2.0+ox", AQUA, "(a) 5.2.0+ox release"),
              (axes[1], "ox54_ip", "str. red. + int. ptrs", VIOLET, "(b) + str. red. + int. ptrs"),
              (axes[2], "pr_counted", "PR compiler, counted loops", VIOLET, "(c) counted loops")]
    xmax = max(max(prof[k].values()) for _, k, *_ in panels) * 1.25
    for ax, key, lo, col, title in panels:
        o = prof[key]
        for i, r in enumerate(REGIONS):
            y = len(REGIONS) - 1 - i
            ax.barh(y + 0.19, c[r], height=0.36, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
            ax.barh(y - 0.19, o[r], height=0.36, color=col, edgecolor=SURFACE, linewidth=0.5,
                    hatch="////" if key == "ox54_ip" else None)
            ax.text(max(c[r], o[r]) + 12, y, f"{o[r]/c[r]:.2f}x", va="center", fontsize=6.8, color=INK)
        ax.set_yticks(range(len(REGIONS)))
        ax.set_yticklabels(REGIONS[::-1])
        ax.set_xlim(0, xmax)
        ax.set_xlabel("ns per forward pass")
        ax.set_title(title, loc="left", fontsize=8.2)
        clean(ax, "x")
    fig.legend([Rectangle((0, 0), 1, 1, color=BLUE), Rectangle((0, 0), 1, 1, color=AQUA),
                Rectangle((0, 0), 1, 1, facecolor=VIOLET, hatch="////", edgecolor=SURFACE),
                Rectangle((0, 0), 1, 1, color=VIOLET)],
               ["C++ scalar (cpp_novec)", "OxCaml 5.2.0+ox release",
                "str. red. + int. ptrs (no polls)", "PR compiler, counted loops"],
               loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.16), fontsize=7)
    save(fig, "fig_regions")


# --------------------------------------------------------------------------
# 5. Instruction budget of the hot loop, per 4 multiply-accumulates.
# --------------------------------------------------------------------------
def fig_budget():
    cats = ["FP multiply/add", "FP loads", "address arithmetic", "loop control", "GC poll", "extra jmp"]
    cols = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN]
    rows = [
        ("C++ scalar (cpp_novec)", [8, 4, 1, 2, 0, 0]),
        ("OxCaml 5.2.0+ox release", [8, 1, 8, 3, 2, 1]),
        ("+ SR pass, no polls", [8, 1, 5, 3, 0, 1]),
        ("+ SR + IP (or counted loops)", [8, 1, 0, 3, 0, 1]),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 2.1))
    for i, (lab, vals) in enumerate(rows):
        y = len(rows) - 1 - i
        left = 0
        for v, c in zip(vals, cols):
            if v:
                ax.barh(y, v, left=left, height=0.6, color=c, edgecolor=SURFACE, linewidth=1.2)
                if v >= 2:
                    ax.text(left + v / 2, y, str(v), ha="center", va="center", fontsize=7.2,
                            color=SURFACE if c in (BLUE, GREEN) else INK)
                left += v
        ax.text(left + 0.3, y, f"{left}", va="center", fontsize=8, color=INK, weight="bold")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows][::-1])
    ax.set_xlim(0, 25.5)
    ax.set_xlabel("instructions in the inner loop per 4 multiply-accumulates")
    ax.legend([Rectangle((0, 0), 1, 1, color=c) for c in cols], cats, ncol=3, fontsize=7,
              loc="upper center", bbox_to_anchor=(0.5, -0.32))
    clean(ax, "x")
    save(fig, "fig_budget")


# (The poll-pricing and poll/pass-interaction results use builds outside the core
#  set, so the report gives them in the text, from run W tokens, not as figures.)


# --------------------------------------------------------------------------
# 8. nx-oxcaml per-op speedup with -cmm-counted-loops (final "nest" build,
#    21 rounds, paired median, polls kept). Oct 14.
# --------------------------------------------------------------------------
def fig_nx_ops():
    E, R, M, S = "elementwise", "reduction", "matmul", "strided"
    rows = [
        ("add f32, 3,000", 2.89, E), ("add f64, 1,000", 2.88, E), ("mul f64, 1,000", 2.87, E),
        ("add i32, 32,768", 1.75, E), ("mul f64, 5,000", 1.74, E), ("add f64, 5,000", 1.73, E),
        ("mul f64, 32,768", 1.71, E), ("add f64, 32,768", 1.70, E), ("add f32, 32,768", 1.70, E),
        ("sum f64, 32,768", 1.34, R), ("add f64, transposed 181x181", 1.15, S),
        ("batched matmul f64, 8x64", 1.11, M), ("matmul i32, 128", 1.07, M),
        ("matmul f64, 64", 1.07, M), ("matmul f64, 128", 1.05, M), ("matmul f32, 128", 1.05, M),
        ("matmul f64, 256", 1.04, M), ("matmul f32, 256", 1.01, M), ("sum over axis, 256x128", 1.00, R),
    ]
    col = {E: AQUA, R: YELLOW, M: BLUE, S: VIOLET}
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    n = len(rows)
    for i, (lab, v, k) in enumerate(rows):
        y = n - 1 - i
        ax.barh(y, v - 1, left=1, height=0.68, color=col[k])
        ax.text(v + 0.03, y, f"{v:.2f}x", va="center", fontsize=7.2)
    ax.axvline(1, color=INK2, linewidth=0.9)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in rows][::-1], fontsize=7.4)
    ax.set_xlim(0.9, 3.2)
    ax.set_xlabel("speedup with -cmm-counted-loops (paired median of 21 rounds)")
    ax.legend([Rectangle((0, 0), 1, 1, color=col[k]) for k in (E, R, M, S)],
              ["elementwise (SIMD)", "reduction", "matrix multiply", "strided"], loc="lower right",
              fontsize=7.2)
    clean(ax, "x")
    save(fig, "fig_nx_ops")


# --------------------------------------------------------------------------
# 9. Poll-free interior pointers in nx-oxcaml: does the static change predict
#    the speedup? Out-of-sample run 2 (21 rounds), median and IQR per partition.
# --------------------------------------------------------------------------
def fig_nx_partition():
    parts = [("kernel code identical\n(control, n=12)", -0.24, -1.17, 0.02, MUTED),
             ("1-9 instructions fewer\n(n=24)", -0.17, -0.57, 0.39, MUTED),
             ("30-46 instructions fewer\n(n=42)", 22.41, 7.6, 29.8, VIOLET)]
    fig, ax = plt.subplots(figsize=(4.8, 2.1))
    for i, (lab, med, lo, hi, c) in enumerate(parts):
        y = len(parts) - 1 - i
        ax.barh(y, med, height=0.55, color=c)
        ax.plot([lo, hi], [y, y], color=INK, linewidth=1.0)
        ax.plot([lo, lo], [y - 0.12, y + 0.12], color=INK, linewidth=1.0)
        ax.plot([hi, hi], [y - 0.12, y + 0.12], color=INK, linewidth=1.0)
        ax.text(max(hi, med) + 1.0, y, f"{med:+.2f}%", va="center", fontsize=7.8)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_yticks(range(len(parts)))
    ax.set_yticklabels([p[0] for p in parts][::-1], fontsize=7.6)
    ax.set_xlim(-3, 38)
    ax.set_xlabel("speedup of nx-oxcaml kernels (median, whiskers = IQR)")
    clean(ax, "x")
    save(fig, "fig_nx_partition")


# --------------------------------------------------------------------------
# 10. The gap as the model widens (n_layer 1, n_head 4). Width-sweep run, 21 interleaved
#     rounds, 27 Oct (scratchpad R2_width). Median tok/s. Random-weight models at every width
#     (R16, E32..E256), plus the trained width-16 model shown as open markers.
# --------------------------------------------------------------------------
def fig_width():
    widths = [16, 32, 64, 128, 256]
    tok = {  # random weights at every width
        "cpp_novec": [692742, 277137, 84959, 23344, 5471],
        "cpp_unroll": [758233, 301266, 93044, 25591, 6142],
        "rust_unroll": [688547, 263828, 78908, 21666, 5338],
        "oxcaml_unsafe_unroll": [388587, 143936, 45754, 13294, 3292],
        "pr_all": [413465, 161463, 52904, 15433, 3782],
        "pr_counted": [486961, 210136, 67309, 20165, 4964],
    }
    trained16 = {"cpp_novec": 799241, "cpp_unroll": 881588, "rust_unroll": 769981,
                 "oxcaml_unsafe_unroll": 479732, "pr_all": 524783, "pr_counted": 643517}
    lines = [  # key, label, colour, style
        ("oxcaml_unsafe_unroll", "OxCaml 5.2.0+ox release", AQUA, "-"),
        ("pr_all", "patched, 4 passes", VIOLET, (0, (4, 2))),
        ("pr_counted", "patched, + counted loops", VIOLET, "-"),
        ("rust_unroll", "Rust", ORANGE, "-"),
        ("cpp_unroll", "C++ vectorised", BLUE, "-"),
    ]
    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    for lo, hi, lab in ((15, 22, "weights in L1"), (22, 181, "L2"), (181, 300, "L3")):
        ax.text((lo * hi) ** 0.5, 2.08, lab, ha="center", fontsize=7, color=INK2)
    for x in (22, 181):
        ax.axvline(x, color=GRID, linewidth=0.9, zorder=0)
    ax.axhline(1.0, color=INK2, linewidth=1.0, zorder=0, label="C++ scalar (cpp_novec) = 1")
    for key, lab, c, ls in lines:
        ys = [n / v for n, v in zip(tok["cpp_novec"], tok[key])]
        ax.plot(widths, ys, color=c, linestyle=ls, linewidth=2.0 if key == "pr_counted" else 1.4,
                marker="o", markersize=4.2, markeredgecolor=SURFACE, markeredgewidth=0.8, label=lab)
        t = trained16["cpp_novec"] / trained16[key]
        ax.plot([16], [t], marker="o", markersize=5.0, markerfacecolor=SURFACE, markeredgecolor=c,
                markeredgewidth=1.2, linestyle="none")
        if key in ("oxcaml_unsafe_unroll", "pr_counted"):
            ax.text(widths[-1] * 1.07, ys[-1], f"{ys[-1]:.2f}x", va="center", fontsize=7.2, color=INK)
            ax.text(widths[0] / 1.07, ys[0], f"{ys[0]:.2f}x", va="center", ha="right", fontsize=7.2, color=INK)
    ax.plot([], [], marker="o", markersize=5.0, markerfacecolor=SURFACE, markeredgecolor=INK2,
            linestyle="none", label="trained width-16 model")
    ax.set_xscale("log", base=2)
    ax.set_xticks(widths)
    ax.set_xticklabels([str(w) for w in widths])
    ax.set_xlim(11, 340)
    ax.set_ylim(0.85, 2.15)
    ax.set_xlabel("model width n_embd (weights: 34 KB, 116 KB, 429 KB, 1.6 MB, 6.4 MB)")
    ax.set_ylabel("times slower than cpp_novec")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7.2, handlelength=2.6)
    clean(ax, "y")
    save(fig, "fig_width")


# ==========================================================================
# Diagrams (drawn with matplotlib so they can be checked as images).
# ==========================================================================
def box(ax, x, y, w, h, text, fc="#f3f6fb", ec=BLUE, fs=7.5, bold=False, tc=INK, lw=0.9, style="round,pad=0.02,rounding_size=0.05"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style, fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc,
            weight="bold" if bold else "normal", linespacing=1.25)


def arrow(ax, x1, y1, x2, y2, color=INK2, lw=0.9, style="-|>", ms=8, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=ms,
                                 color=color, lw=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}"))


def canvas(w, h, xlim, ylim):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    return fig, ax


def diag_forward():
    """microgpt forward pass for one token, with multiply-accumulates per step."""
    fig, ax = canvas(7.2, 3.5, (0, 14.4), (0, 7.0))
    w, h = 3.0, 1.35
    row1 = [
        ("embedding:\nwte[tok] + wpe[pos],\nrmsnorm", "48 ops", 0.3),
        ("rmsnorm, then\nq, k, v = linear\n3 x (16x16)", "768 MAC", 3.95),
        ("append k, v\nto the KV cache", "", 7.6),
        ("4 heads: q.k / 2,\nsoftmax,\nsum of w.v", "32T MAC", 11.1),
    ]
    row2 = [
        ("linear wo (16x16)\n+ residual", "256 MAC", 11.1),
        ("rmsnorm, fc1 64x16,\nReLU, fc2 16x64,\n+ residual", "2,048 MAC", 7.6),
        ("lm_head 27x16,\ndivide by T,\nsoftmax, sample", "432 MAC", 3.95),
        ("next token\n(xorshift64* draw)", "", 0.3),
    ]
    y1, y2 = 4.75, 2.1
    for row, y in ((row1, y1), (row2, y2)):
        for i, (t, ops, x) in enumerate(row):
            hot = "linear" in t or "fc1" in t or "lm_head" in t
            box(ax, x, y, w, h, t, fc="#eef3fb" if hot else "#f6f6f4", ec=BLUE if hot else MUTED, fs=6.7)
            if ops:
                ax.text(x + w / 2, y - 0.08, ops, ha="center", va="top", fontsize=6.5,
                        color=BLUE if hot else INK2, weight="bold")
    for i in range(1, 4):
        arrow(ax, row1[i - 1][2] + w, y1 + h / 2, row1[i][2], y1 + h / 2)
        arrow(ax, row2[i - 1][2], y2 + h / 2, row2[i][2] + w, y2 + h / 2)
    arrow(ax, 11.1 + w / 2, y1, 11.1 + w / 2, y2 + h)
    ax.add_patch(Rectangle((3.8, 1.55), 10.45, 4.85, fill=False, ec=MUTED, lw=0.7, ls=(0, (3, 2))))
    ax.text(3.9, 6.52, "transformer block (n_layer = 1, n_embd = 16, n_head = 4, head_dim = 4)",
            fontsize=7, color=INK2)
    ax.text(7.2, 0.55,
            "Per token: 3,504 multiply-accumulates in linear (blue, about 97% of the arithmetic) and 32T in "
            "attention\n(T = current context length; mean 3.5 when generating names).",
            ha="center", fontsize=7.0, color=INK)
    save(fig, "diag_forward")


def diag_layout():
    """Why C++ can walk four row pointers and OCaml cannot."""
    fig, ax = canvas(7.2, 3.1, (0, 14.4), (0, 6.2))
    # C++ side
    ax.text(0.2, 5.85, "C++: four row pointers, one shared offset", fontsize=8, weight="bold", color=INK)
    x0, y0, cw = 0.4, 4.5, 0.42
    for r in range(4):
        for c in range(12):
            ax.add_patch(Rectangle((x0 + c * cw, y0 - r * 0.62), cw, 0.5, fc="#eef3fb", ec=BLUE, lw=0.5))
        ax.text(x0 - 0.15, y0 - r * 0.62 + 0.25, f"w{r}", ha="right", va="center", fontsize=7, color=BLUE)
        arrow(ax, x0 + 5 * cw + cw / 2, y0 - r * 0.62 + 0.95, x0 + 5 * cw + cw / 2, y0 - r * 0.62 + 0.52,
              color=BLUE, ms=6)
    ax.text(x0 + 5.5 * cw, y0 + 1.0, "w_k[i]: base_k + 8i", fontsize=6.8, color=BLUE, ha="center")
    ax.text(0.4, 1.75, "double* w1 = w.row(o+1);  ...  a1 += w1[i] * x[i];\n"
            "one  addq $8, %rax  advances all four rows", fontsize=6.8, color=INK2, family="DejaVu Sans Mono")
    # OCaml side
    ax.text(7.4, 5.85, "OCaml: one block, header first, index from the start", fontsize=8, weight="bold",
            color=INK)
    bx, by = 7.5, 4.3
    ax.add_patch(Rectangle((bx, by), 0.9, 0.6, fc="#fdeee6", ec=ORANGE, lw=0.8))
    ax.text(bx + 0.45, by + 0.3, "header", ha="center", va="center", fontsize=6.5, color=ORANGE)
    for c in range(13):
        ax.add_patch(Rectangle((bx + 0.9 + c * 0.42, by), 0.42, 0.6,
                               fc="#e9f7f1" if c // 4 % 2 == 0 else "#f6f6f4", ec=AQUA, lw=0.5))
    ax.text(bx + 0.9 + 6.5 * 0.42, by + 0.85, "float array d  (rows stored back to back)", fontsize=6.8,
            ha="center", color=INK2)
    arrow(ax, bx + 0.2, by - 0.75, bx + 0.2, by - 0.05, color=INK, ms=6)
    ax.text(bx + 0.25, by - 0.85, "the only pointer the GC accepts:\nit must find the header just before the data",
            fontsize=6.6, va="top", color=INK)
    tx = bx + 0.9 + 4 * 0.42 + 0.21
    arrow(ax, tx, by - 1.9, tx, by - 0.05, color=VIOLET, ms=6, ls=(0, (3, 2)))
    ax.text(tx + 0.12, by - 1.95, "interior pointer &d[b1]: no header in front of it.\n"
            "Legal only where no collection can happen\n(no allocation, call or poll in between).",
            fontsize=6.6, va="top", color=VIOLET)
    ax.text(7.5, 0.95, "d.(b1 + i) compiles to\n  mov b1,%r10 ; add i,%r10\n  vmulsd -8(%rbx,%r10,4),...",
            fontsize=6.6, color=INK2, family="DejaVu Sans Mono", va="top")
    ax.plot([7.1, 7.1], [0.3, 6.0], color=GRID, lw=0.8)
    save(fig, "diag_layout")


def diag_pipeline():
    """Where the new Cmm pass sits in the OxCaml backend."""
    fig, ax = canvas(7.2, 2.6, (-0.15, 14.45), (0, 5.2))
    w, h, y = 1.2, 1.5, 3.1
    stages = [("OCaml\nsource", 0.0), ("Lambda", 1.45), ("flambda2\nunboxing,\ninlining", 2.9),
              ("Cmm", 4.35)]
    for i, (t, x) in enumerate(stages):
        box(ax, x, y, w, h, t, fc="#f6f6f4", ec=MUTED, fs=6.8)
        if i:
            arrow(ax, stages[i - 1][1] + w, y + h / 2, x, y + h / 2)
    px, pw = 5.8, 3.4
    box(ax, px, y - 0.2, pw, h + 0.4, "new Cmm pass, per loop:\nLICM, interior pointers,\n"
        "strength reduction,\ninvariant strides",
        fc="#efedfb", ec=VIOLET, fs=6.6, lw=1.3)
    arrow(ax, 4.35 + w, y + h / 2, px, y + h / 2)
    rest = [("instruction\nselection", 9.6), ("Cfg_polling\ninserts\npolls", 11.15), ("regalloc,\nemit", 12.7)]
    for i, (t, x) in enumerate(rest):
        box(ax, x, y, 1.3, h, t, fc="#f6f6f4", ec=MUTED, fs=6.6)
    arrow(ax, px + pw, y + h / 2, 9.6, y + h / 2)
    arrow(ax, 10.9, y + h / 2, 11.15, y + h / 2)
    arrow(ax, 12.45, y + h / 2, 12.7, y + h / 2)
    ax.text(10.25, y - 0.25, "admits an Addr in a\nloop register only if\nno poll can occur",
            fontsize=6.2, ha="center", va="top", color=VIOLET)
    ax.text(13.35, y - 0.25, "'bad GC root' if an\nAddr is live at a\nsafepoint", fontsize=6.2,
            ha="center", va="top", color=RED)
    ax.text(7.2, 0.25, "A loop arrives in Cmm as Ccatch Recursive: handler parameters are the loop-carried "
            "values,\nexits are its edges, and Cmm has no assignment, so 'bound outside' means 'invariant'.",
            fontsize=6.6, ha="center", color=INK2)
    save(fig, "diag_pipeline")


def diag_ilp():
    """One dependent add chain vs four independent chains."""
    fig, ax = canvas(7.2, 2.2, (0, 31), (0, 7.6))
    ax.text(0, 7.2, "plain: one accumulator per row", fontsize=7.8, weight="bold")
    for k in range(6):
        ax.add_patch(Rectangle((1 + 4 * k, 5.6), 3.85, 0.9, fc="#e9f7f1", ec=AQUA, lw=0.7))
        ax.text(1 + 4 * k + 1.9, 6.05, f"acc += w{k}*x{k}", ha="center", va="center", fontsize=6.0)
    ax.text(26.5, 6.05, "1 MAC per\nadd latency", ha="left", va="center", fontsize=6.8, color=INK2)
    ax.text(0, 4.6, "4-way unroll: four rows, four independent chains", fontsize=7.8, weight="bold")
    for r in range(4):
        for k in range(6 if r == 0 else 5):
            ax.add_patch(Rectangle((1 + r + 4 * k, 3.3 - r * 0.78), 3.85, 0.66,
                                   fc=["#eef3fb", "#fdeee6", "#e9f7f1", "#fdf4dd"][r],
                                   ec=[BLUE, ORANGE, AQUA, YELLOW][r], lw=0.6))
        ax.text(0.85, 3.63 - r * 0.78, f"a{r}", ha="right", va="center", fontsize=6.8)
    ax.text(26.5, 2.5, "4 MACs per\nadd latency", ha="left", va="center", fontsize=6.8, color=INK2)
    ax.annotate("", xy=(25, 0.3), xytext=(1, 0.3), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=0.7))
    ax.text(13, 0.0, "time", ha="center", va="top", fontsize=6.8, color=INK2)
    save(fig, "diag_ilp")


def diag_counted():
    """A counted loop: entry check, poll-free fast copy, polled fallback, exit poll."""
    fig, ax = canvas(7.0, 3.0, (-0.9, 14.9), (0, 6))
    box(ax, 5.0, 4.9, 4.0, 0.85, "loop entry: is termination proved?\n(statically, or check B <= max - d + 1 once)",
        fc="#f6f6f4", ec=MUTED, fs=6.8)
    box(ax, 0.6, 2.3, 5.3, 1.7, "fast copy (poll-free)\nrow pointers hoisted or carried,\none shared index, no back-edge poll",
        fc="#efedfb", ec=VIOLET, fs=6.8, lw=1.2)
    box(ax, 8.1, 2.3, 5.3, 1.7, "fallback copy (original loop)\nlabels renamed, back-edge poll kept,\nno interior pointers",
        fc="#f6f6f4", ec=MUTED, fs=6.8)
    arrow(ax, 6.2, 4.9, 3.25, 4.0)
    arrow(ax, 7.8, 4.9, 10.75, 4.0)
    ax.text(3.9, 4.55, "proved", fontsize=6.8, color=VIOLET)
    ax.text(9.6, 4.55, "not proved", fontsize=6.8, color=INK2)
    arrow(ax, 1.4, 2.3, 1.4, 4.0, rad=-1.6, color=VIOLET)
    arrow(ax, 12.6, 2.3, 12.6, 4.0, rad=1.6, color=INK2)
    box(ax, 0.6, 0.55, 5.3, 0.95, "poll once on every exit\n(exit values computed before the poll)",
        fc="#fbeef3", ec=MAGENTA, fs=6.8)
    arrow(ax, 3.25, 2.3, 3.25, 1.5)
    box(ax, 5.6, 0.0, 2.8, 0.55, "continuation", fc="#f6f6f4", ec=MUTED, fs=6.8)
    arrow(ax, 5.9, 1.0, 6.4, 0.55)
    arrow(ax, 10.75, 2.3, 7.8, 0.55)
    save(fig, "diag_counted")


def diag_timeline():
    """Project timeline: what was tried, when, and the fair-baseline gap it reached."""
    fig, ax = canvas(7.2, 2.7, (-4, 104), (0, 30))
    ax.plot([2, 98], [15, 15], color=MUTED, lw=1.2)
    def g(k):
        return f"{UM['cpp_novec'] / UM[k]:.2f}x"
    # Gaps only where a core build of run W corresponds to the milestone.
    events = [
        (3, "Aug", "llama.cpp KV-cache\nexploration", None, MUTED),
        (13, "Aug 28-Sep 6", "ports, contract,\nunroll, -unsafe",
         f"{g('oxcaml_safe_plain')} -> {g('oxcaml_unsafe_unroll')}", BLUE),
        (24, "Sep 8-12", "region profile,\nSIMD test, polls", None, AQUA),
        (34, "Sep 15-16", "strength reduction\n(hand, then Cmm)", g("oxcaml_unsafe_sr"), AQUA),
        (44, "Sep 29", "interior pointers\n(prof's idea)", None, VIOLET),
        (54, "Oct 6-8", "invariant strides,\nLICM, residual hunt", None, VIOLET),
        (64, "Oct 12", "passes with\nsafepoints on; nx-oxcaml", None, VIOLET),
        (74, "Oct 13-20", "counted loops, nx,\nunchecked, PR #1", g("pr_counted"), VIOLET),
        (84, "Oct 20-21", "crypto study;\nexplicit SIMD", g("pr_simd_counted") + " (SSE2)", BLUE),
        (95, "Oct 22-31", "trip cap, rebase,\nfinal run W", None, VIOLET),
    ]
    for i, (x, date, what, gap, c) in enumerate(events):
        up = i % 2 == 0
        ax.plot([x], [15], marker="o", ms=5.5, color=c, mec=SURFACE, mew=1.2)
        ax.plot([x, x], [15, 19.5 if up else 10.5], color=c, lw=0.7)
        ty = 20 if up else 10
        ax.text(x, ty, f"{date}\n{what}", ha="center", va="bottom" if up else "top", fontsize=6.3,
                color=INK, linespacing=1.15)
        if gap:
            ax.text(x, 13.0 if up else 16.6, gap, ha="center", va="top" if up else "bottom", fontsize=6.5,
                    color=c, weight="bold")
    ax.text(50, 0.3, "Bold: scalar C++ (cpp_novec) throughput / throughput of the corresponding "
            "core build, both from run W.", ha="center", fontsize=6.5, color=INK2)
    save(fig, "diag_timeline")


if __name__ == "__main__":
    fig_gap_ladder()
    fig_matrix()
    fig_unroll()
    fig_regions()
    fig_budget()
    fig_nx_ops()
    fig_nx_partition()
    fig_width()
    diag_forward()
    diag_layout()
    diag_pipeline()
    diag_ilp()
    diag_counted()
    diag_timeline()
    print("figures written to", OUT)
