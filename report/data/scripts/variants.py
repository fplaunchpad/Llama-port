"""The variant registry: every build the report measures, in one table.

Each variant is one row: its name (as used in the report and in run W), its group,
the concept it belongs to, a one-line description, and the recipe that builds it.
`bench/bench.py` builds, checks and times whatever this file lists; nothing else
defines a variant.

Groups
  headline  the steps of the story: the reference builds and one build per
            optimisation, in the order the optimisations are applied
  ablation  the same build with one thing switched off or on, to price it
  control   builds that test the measurement itself, not an optimisation

Rows are listed in run W's measurement order (report/data/run_w_gen.txt), which
`bench.py` keeps, so a rerun interleaves the variants exactly as run W did.

Compilers. The OxCaml variants use one of these compiler families:
  oxcaml_*    the shipped OxCaml release, 5.4.0-ox7 (opam package
              oxcaml-compiler.5.4.0-ox7, built unpatched into ~/oxinstall-ox7;
              MG_OX_RELEASE overrides the path)
  oxcaml52_*  the same rows on the previous release, 5.2.0+ox (opam switch
              5.2.0+ox), kept to price the release upgrade
  ox54_*      5.4.0+ox built --enable-flambda2 (no safepoint polls), one compiler
              per pass of the pull request: base, +1, +1-2, +1-3, +1-4
  pr_*        the pull request (patches 1-8 plus the review series) rebased onto
              oxcaml main 327965f0e, built into ~/oxinstall-pr-latest and
              configured like the release (poll insertion on); flags select the passes
Paths default to ~/oxinstall-*/bin/ocamlopt.opt and are overridden with the
MG_OX_RELEASE / MG_OX54_* / MG_OX_PR environment variables (see
compiler-patches/README.md). To run the oxcaml_* rows on 5.2.0+ox instead, point
MG_OX_RELEASE at that switch's compiler:
    MG_OX_RELEASE=$(opam var --switch=5.2.0+ox prefix)/bin/ocamlopt.opt
A variant whose compiler is absent is skipped, so the rest still runs.

Run W (report/data/) measured both releases: the oxcaml_* rows on 5.4.0-ox7 and
the oxcaml52_* rows on 5.2.0+ox.
"""
import os

HOME = os.path.expanduser("~")

HEADLINE, ABLATION, CONTROL = "headline", "ablation", "control"

CXXFLAGS = "-std=c++20 -fno-fast-math -ffp-contract=off"

# Pass-selection flags of the pull-request compiler (compiler-patches/README.md).
PASSES_OFF = ("-no-cmm-strength-reduction -no-cmm-interior-pointers "
              "-no-cmm-invariant-strides -no-cmm-licm")


def compiler(env, default_dir):
    """An ocamlopt path, overridable by an environment variable."""
    return os.environ.get(env, os.path.join(HOME, default_dir, "bin", "ocamlopt.opt"))


COMPILERS = {
    "release":   ("MG_OX_RELEASE", compiler("MG_OX_RELEASE", "oxinstall-ox7"),
                  "OxCaml 5.4.0-ox7 release, polls on"),
    "ox54_base": ("MG_OX54_BASE", compiler("MG_OX54_BASE", "oxinstall-baseline"),
                  "5.4.0+ox, unpatched, no polls"),
    "ox54_sr":   ("MG_OX54_SR", compiler("MG_OX54_SR", "oxinstall-sr"),
                  "5.4.0+ox + patch 1, no polls"),
    "ox54_ip":   ("MG_OX54_IP", compiler("MG_OX54_IP", "oxinstall-ip"),
                  "5.4.0+ox + patches 1-2, no polls"),
    "ox54_ivs":  ("MG_OX54_IVS", compiler("MG_OX54_IVS", "oxinstall-ivs"),
                  "5.4.0+ox + patches 1-3, no polls"),
    "ox54_licm": ("MG_OX54_LICM", compiler("MG_OX54_LICM", "oxinstall-licm"),
                  "5.4.0+ox + patches 1-4, no polls"),
    "pr":        ("MG_OX_PR", compiler("MG_OX_PR", "oxinstall-pr-latest"),
                  "the PR rebased onto oxcaml main 327965f0e (patches 1-8 + review series), polls on"),
}


# ---------------------------------------------------------------- recipe helpers
# A recipe is a dict: "kind" plus what that kind needs. bench.py turns it into
# commands; `bench.py --show NAME` prints them as shell lines.

def cxx(flags, unroll=True):
    extra = "" if unroll else " -DMG_UNROLL=0"
    return dict(kind="cxx", flags=f"{flags} {CXXFLAGS}{extra}")


def cxx_after(opt, extra):  # flags after the common ones, as the earlier runs ordered them
    return dict(kind="cxx", flags=f"{opt} {CXXFLAGS} {extra}")


def cargo(unroll=True):
    return dict(kind="cargo", unroll=unroll)


def shipped(flags, unroll=1, sr=0, simd=0):
    """impl/oxcaml/build.sh with the shipped OxCaml release (5.4.0-ox7, MG_OX_RELEASE)."""
    return dict(kind="ml", script="impl/oxcaml/build.sh", compiler="release",
                env=dict(MG_UNROLL=str(unroll), MG_SR=str(sr), MG_SIMD=str(simd),
                         OCAMLFLAGS=flags))


def ox52(flags, unroll=1, sr=0, simd=0):
    """impl/oxcaml/build.sh with the previous release: the opam switch 5.2.0+ox,
    which build.sh selects itself when no compiler is named."""
    return dict(shipped(flags, unroll, sr, simd), compiler=None)


def stock(flags, unroll=1, sr=0):
    """impl/ocaml/build.sh with the stock compiler (ocamlopt on PATH, or MG_OCAML_SWITCH)."""
    return dict(kind="ml", script="impl/ocaml/build.sh", compiler=None,
                env=dict(MG_UNROLL=str(unroll), MG_SR=str(sr), OCAMLFLAGS=flags))


# Upstream OCaml 5.3.0 with the passes ported (scratchpad ocaml_port/patches),
# installed at ~/ocaml-pr-5.3; MG_OCAML_PR overrides its bin directory.
OCAML_PR_BIN = os.environ.get("MG_OCAML_PR", os.path.join(HOME, "ocaml-pr-5.3", "bin"))


def stock_pr(flags):
    """impl/ocaml/build.sh with the patched upstream 5.3.0 compiler, 4-row kernel."""
    return dict(kind="ml", script="impl/ocaml/build.sh", compiler=None,
                env=dict(MG_UNROLL="1", MG_SR="0", OCAMLFLAGS=flags,
                         PATH=OCAML_PR_BIN + os.pathsep + os.environ.get("PATH", "")))


def ox(comp, extra="", simd=0, unsafe=True):
    """impl/oxcaml/build.sh with a locally built 5.4.0+ox compiler, shipped kernel."""
    flags = "-O3 -unsafe" if unsafe else "-O3"
    flags = f"{flags} {extra}".strip()
    env = dict(MG_UNROLL="1", OCAMLFLAGS=flags)
    if simd:
        env["MG_SIMD"] = "1"
    return dict(kind="ml", script="impl/oxcaml/build.sh", compiler=comp, env=env)


def nop(src):
    """tools/nop_polls.py applied to another variant's linked binary."""
    return dict(kind="nop", src=src)


def copy(src):
    return dict(kind="copy", src=src)


def interp():
    return dict(kind="python")


def V(name, group, concept, desc, recipe):
    return dict(name=name, group=group, concept=concept, desc=desc, recipe=recipe)


# ---------------------------------------------------------------- the registry
VARIANTS = [
    # C++: g++ -O3, 4-row kernel. cpp_novec is the reference every gap is quoted against.
    V("cpp_O2_plain", CONTROL, "fairness",
      "C++ plain kernel at -O2 (prices matching Rust's opt-level 3)",
      cxx("-O2", unroll=False)),
    V("cpp_plain", ABLATION, "unroll",
      "C++ plain kernel, one accumulator per row",
      cxx("-O3", unroll=False)),
    V("cpp_unroll", HEADLINE, "ports",
      "C++ as shipped: 4-row kernel, auto-vectorised by GCC (vectorised baseline)",
      cxx("-O3")),
    V("cpp_novec", HEADLINE, "ports",
      "C++ 4-row kernel, -fno-tree-vectorize (scalar baseline, the main reference)",
      cxx_after("-O3", "-fno-tree-vectorize")),
    V("cpp_novec_avx", CONTROL, "fairness",
      "cpp_novec with VEX encoding (-mavx): is the SSE baseline flattering?",
      cxx_after("-O3", "-fno-tree-vectorize -mavx")),
    # Rust: the unroll is a Cargo feature, on by default.
    V("rust_plain", ABLATION, "unroll",
      "Rust plain kernel (--no-default-features)",
      cargo(unroll=False)),
    V("rust_unroll", HEADLINE, "ports",
      "Rust as shipped: 4-row kernel, bounds-checked",
      cargo()),
    # Shipped OxCaml (5.4.0-ox7): source-level optimisations, compiler unchanged.
    V("oxcaml_safe_plain", HEADLINE, "unsafe",
      "first OxCaml port: -O3, bounds checks, plain kernel",
      shipped("-O3", unroll=0)),
    V("oxcaml_safe_unroll", ABLATION, "unsafe",
      "4-row kernel with bounds checks kept",
      shipped("-O3")),
    V("oxcaml_unsafe_plain", HEADLINE, "unsafe",
      "-O3 -unsafe, plain kernel",
      shipped("-O3 -unsafe", unroll=0)),
    V("oxcaml_unsafe_unroll", HEADLINE, "unroll",
      "OxCaml as shipped: -O3 -unsafe, 4-row kernel",
      shipped("-O3 -unsafe")),
    V("oxcaml_unsafe_plain_pollnop", ABLATION, "polls",
      "oxcaml_unsafe_plain with every poll overwritten by NOPs in the binary",
      nop("oxcaml_unsafe_plain")),
    V("oxcaml_unsafe_unroll_pollnop", ABLATION, "polls",
      "oxcaml_unsafe_unroll with every poll overwritten by NOPs in the binary",
      nop("oxcaml_unsafe_unroll")),
    V("oxcaml_unsafe_plain_pollfree", ABLATION, "polls",
      "oxcaml_unsafe_plain built with -disable-poll-insertion",
      shipped("-O3 -unsafe -disable-poll-insertion", unroll=0)),
    V("oxcaml_unsafe_unroll_pollfree", ABLATION, "polls",
      "oxcaml_unsafe_unroll built with -disable-poll-insertion",
      shipped("-O3 -unsafe -disable-poll-insertion")),
    V("oxcaml_unsafe_sr", HEADLINE, "hand_sr",
      "4-row kernel with row indices carried by hand (MG_SR=1)",
      shipped("-O3 -unsafe", sr=1)),
    V("oxcaml_unsafe_sr_pollfree", ABLATION, "hand_sr",
      "oxcaml_unsafe_sr built with -disable-poll-insertion",
      shipped("-O3 -unsafe -disable-poll-insertion", sr=1)),
    V("oxcaml_unsafe_simd", HEADLINE, "simd",
      "explicit SSE2 kernel, two rows per vector (MG_SIMD=1)",
      shipped("-O3 -unsafe", simd=1)),
    # Stock OCaml 5.3.0 (closure middle end): the same source, the same switches.
    V("ocaml_safe_plain", ABLATION, "middle_end",
      "stock OCaml, bounds checks, plain kernel",
      stock("", unroll=0)),
    V("ocaml_safe_unroll", ABLATION, "middle_end",
      "stock OCaml, bounds checks, 4-row kernel",
      stock("")),
    V("ocaml_unsafe_plain", ABLATION, "middle_end",
      "stock OCaml, -unsafe, plain kernel",
      stock("-unsafe", unroll=0)),
    V("ocaml_unsafe_unroll", HEADLINE, "ports",
      "stock OCaml as shipped: -unsafe, 4-row kernel",
      stock("-unsafe")),
    V("ocaml_unsafe_sr", ABLATION, "hand_sr",
      "stock OCaml, row indices carried by hand (MG_SR=1)",
      stock("-unsafe", sr=1)),
    # The same passes ported to upstream OCaml 5.3.0 (closure middle end).
    V("ocaml_pr_off", ABLATION, "stock_passes",
      "patched OCaml 5.3.0, passes off (same code as stock 5.3.0)",
      stock_pr("-unsafe " + PASSES_OFF)),
    V("ocaml_pr_all", HEADLINE, "stock_passes",
      "patched OCaml 5.3.0, passes on (defaults); polls stay, so only strength reduction fires",
      stock_pr("-unsafe")),
    V("ocaml_pr_counted", HEADLINE, "stock_passes",
      "patched OCaml 5.3.0, passes on + -cmm-counted-loops",
      stock_pr("-unsafe -cmm-counted-loops")),
    # Compiler passes, one compiler per pass, all built without safepoint polls.
    V("ox54_base", HEADLINE, "pass_sr",
      "unpatched 5.4.0+ox (no polls), shipped source",
      ox("ox54_base")),
    V("ox54_sr", HEADLINE, "pass_sr",
      "+ strength reduction of derived induction variables (patch 1)",
      ox("ox54_sr")),
    V("ox54_ip_off", ABLATION, "pass_ip",
      "patch 1-2 compiler with -no-cmm-interior-pointers",
      ox("ox54_ip", "-no-cmm-interior-pointers")),
    V("ox54_ip", HEADLINE, "pass_ip",
      "+ interior pointers into array rows (patch 2)",
      ox("ox54_ip")),
    V("ox54_ivs_noptr", ABLATION, "pass_ivs",
      "patch 1-3 compiler with -no-cmm-carried-pointers (carry indices only)",
      ox("ox54_ivs", "-no-cmm-carried-pointers")),
    V("ox54_ivs", HEADLINE, "pass_ivs",
      "+ invariant-stride induction variables, carried pointers (patch 3)",
      ox("ox54_ivs")),
    V("ox54_licm", HEADLINE, "pass_licm",
      "+ register-neutral LICM (patch 4); declines on microgpt",
      ox("ox54_licm")),
    # The pull-request compiler, poll insertion on; flags select the configuration.
    V("pr_off", HEADLINE, "safepoints",
      "PR compiler, safepoints on, the four passes off",
      ox("pr", PASSES_OFF)),
    V("pr_all", HEADLINE, "safepoints",
      "PR compiler, safepoints on, the four passes on (default flags)",
      ox("pr")),
    V("pr_off_nopoll", ABLATION, "safepoints",
      "pr_off with -disable-poll-insertion",
      ox("pr", PASSES_OFF + " -disable-poll-insertion")),
    V("pr_nopoll", ABLATION, "safepoints",
      "pr_all with -disable-poll-insertion (no safepoints at all)",
      ox("pr", "-disable-poll-insertion")),
    # The pass ladder on the PR compiler: counted loops first, then one pass at a time.
    V("pr_c_off", HEADLINE, "pr_ladder",
      "PR compiler, -cmm-counted-loops, the four passes off",
      ox("pr", "-cmm-counted-loops " + PASSES_OFF)),
    V("pr_c_sr", HEADLINE, "pr_ladder",
      "+ strength reduction",
      ox("pr", "-cmm-counted-loops -no-cmm-interior-pointers -no-cmm-invariant-strides -no-cmm-licm")),
    V("pr_c_ip", HEADLINE, "pr_ladder",
      "+ interior pointers",
      ox("pr", "-cmm-counted-loops -no-cmm-invariant-strides -no-cmm-licm")),
    V("pr_c_ivs", HEADLINE, "pr_ladder",
      "+ invariant-stride induction variables (carried pointers)",
      ox("pr", "-cmm-counted-loops -no-cmm-licm")),
    V("pr_counted", HEADLINE, "counted",
      "pr_all + -cmm-counted-loops: proved-terminating loops poll on exit",
      ox("pr", "-cmm-counted-loops")),
    V("pr_counted_copy", CONTROL, "fairness",
      "byte-identical copy of pr_counted at another path (A/A control)",
      copy("pr_counted")),
    V("pr_counted_noptr", ABLATION, "counted",
      "pr_counted with interior and carried pointers off",
      ox("pr", "-cmm-counted-loops -no-cmm-interior-pointers -no-cmm-carried-pointers")),
    V("pr_unchecked", ABLATION, "counted",
      "pr_all + -cmm-unchecked-loops: no termination proof",
      ox("pr", "-cmm-unchecked-loops")),
    V("pr_safe_counted", ABLATION, "counted",
      "pr_counted with bounds checks kept (no -unsafe)",
      ox("pr", "-cmm-counted-loops", unsafe=False)),
    V("pr_simd_off", ABLATION, "simd",
      "SSE2 kernel, PR compiler, passes off",
      ox("pr", PASSES_OFF, simd=1)),
    V("pr_simd", HEADLINE, "simd",
      "SSE2 kernel, PR compiler, passes on",
      ox("pr", simd=1)),
    V("pr_simd_counted", ABLATION, "simd",
      "SSE2 kernel with -cmm-counted-loops",
      ox("pr", "-cmm-counted-loops", simd=1)),
    V("pr_simd_nopoll", ABLATION, "simd",
      "SSE2 kernel with -disable-poll-insertion",
      ox("pr", "-disable-poll-insertion", simd=1)),
    # The reference implementation.
    V("python", HEADLINE, "ports",
      "CPython reference port (impl/python/infer.py)",
      interp()),
]


def _on_ox52(v):
    """An oxcaml_* row rebuilt on the previous release, 5.2.0+ox, as oxcaml52_*."""
    r = v["recipe"]
    if r["kind"] == "nop":
        recipe = nop(r["src"].replace("oxcaml_", "oxcaml52_", 1))
    else:
        recipe = dict(r, compiler=None)  # no compiler: build.sh uses the 5.2.0+ox switch
    return V(v["name"].replace("oxcaml_", "oxcaml52_", 1), ABLATION, "release",
             v["desc"] + "; previous release 5.2.0+ox", recipe)


# The previous release: every oxcaml_* row again on 5.2.0+ox, after all other rows,
# as run W measured them.
VARIANTS += [_on_ox52(v) for v in VARIANTS if v["name"].startswith("oxcaml_")]

BY_NAME = {v["name"]: v for v in VARIANTS}

# Old names that still resolve. None of the run U names changed; this map is the
# place to add one if a variant is ever renamed, so the report's tooling keeps working.
ALIASES = {}


# ---------------------------------------------------------------- concepts
# Each concept: title, where it lives, and the paired comparisons that price it
# (base -> variant, measured within the same rounds). The comparisons are those the
# report quotes (report/data/analyse.py), grouped by concept.
CONCEPTS = [
    ("ports", "Ports and baselines",
     "impl/{python,cpp,rust,ocaml,oxcaml}; BENCHMARK.md is the contract", [
         ("GCC's auto-vectoriser on the C++ kernel", "cpp_novec", "cpp_unroll"),
         ("Rust against scalar C++", "cpp_novec", "rust_unroll"),
         ("shipped OxCaml against shipped stock OCaml", "ocaml_unsafe_unroll", "oxcaml_unsafe_unroll"),
     ]),
    ("fairness", "Measurement controls",
     "build flags only", [
         ("C++ -O3 over -O2 (plain kernel)", "cpp_O2_plain", "cpp_plain"),
         ("C++ scalar, VEX (-mavx) against SSE encoding", "cpp_novec", "cpp_novec_avx"),
         ("A/A: two byte-identical binaries", "pr_counted", "pr_counted_copy"),
     ]),
    ("unsafe", "Source level: -unsafe (no bounds checks)",
     "OCAMLFLAGS=-unsafe", [
         ("OxCaml, plain kernel", "oxcaml_safe_plain", "oxcaml_unsafe_plain"),
         ("OxCaml, 4-row kernel", "oxcaml_safe_unroll", "oxcaml_unsafe_unroll"),
         ("stock OCaml, plain kernel", "ocaml_safe_plain", "ocaml_unsafe_plain"),
         ("stock OCaml, 4-row kernel", "ocaml_safe_unroll", "ocaml_unsafe_unroll"),
     ]),
    ("unroll", "Source level: 4-row unrolled kernel",
     "MG_UNROLL (C++ -DMG_UNROLL, Rust feature `unroll`, OCaml build.sh)", [
         ("C++", "cpp_plain", "cpp_unroll"),
         ("Rust", "rust_plain", "rust_unroll"),
         ("OxCaml, -unsafe", "oxcaml_unsafe_plain", "oxcaml_unsafe_unroll"),
         ("OxCaml, bounds-checked", "oxcaml_safe_plain", "oxcaml_safe_unroll"),
         ("stock OCaml, -unsafe", "ocaml_unsafe_plain", "ocaml_unsafe_unroll"),
         ("stock OCaml, bounds-checked", "ocaml_safe_plain", "ocaml_safe_unroll"),
         ("Stage I total: first port to shipped OxCaml", "oxcaml_safe_plain", "oxcaml_unsafe_unroll"),
     ]),
    ("middle_end", "Same source, two compilers: flambda2 over closure",
     "impl/ocaml/main.ml == impl/oxcaml/main.ml (asserted by impl/ocaml/build.sh)", [
         ("plain, bounds-checked", "ocaml_safe_plain", "oxcaml_safe_plain"),
         ("plain, -unsafe", "ocaml_unsafe_plain", "oxcaml_unsafe_plain"),
         ("4-row, bounds-checked", "ocaml_safe_unroll", "oxcaml_safe_unroll"),
         ("4-row, -unsafe (shipped against shipped)", "ocaml_unsafe_unroll", "oxcaml_unsafe_unroll"),
     ]),
    ("hand_sr", "Source level: strength reduction by hand",
     "MG_SR=1 (impl/*/build.sh)", [
         ("OxCaml, shipped release", "oxcaml_unsafe_unroll", "oxcaml_unsafe_sr"),
         ("stock OCaml", "ocaml_unsafe_unroll", "ocaml_unsafe_sr"),
         ("OxCaml, polls also removed", "oxcaml_unsafe_sr", "oxcaml_unsafe_sr_pollfree"),
         ("OxCaml, both against shipped", "oxcaml_unsafe_unroll", "oxcaml_unsafe_sr_pollfree"),
         ("hand SR on top of removed polls", "oxcaml_unsafe_unroll_pollfree", "oxcaml_unsafe_sr_pollfree"),
     ]),
    ("polls", "Safepoint polls on the shipped compiler",
     "tools/nop_polls.py (binary NOP patch); -disable-poll-insertion", [
         ("NOP patch, plain kernel", "oxcaml_unsafe_plain", "oxcaml_unsafe_plain_pollnop"),
         ("flag, plain kernel", "oxcaml_unsafe_plain", "oxcaml_unsafe_plain_pollfree"),
         ("NOP patch, 4-row kernel", "oxcaml_unsafe_unroll", "oxcaml_unsafe_unroll_pollnop"),
         ("flag, 4-row kernel", "oxcaml_unsafe_unroll", "oxcaml_unsafe_unroll_pollfree"),
     ]),
    ("pass_sr", "Compiler pass: strength reduction (patch 1)",
     "-[no-]cmm-strength-reduction", [
         ("over unpatched 5.4.0+ox", "ox54_base", "ox54_sr"),
         ("unpatched 5.4.0+ox against the release without polls", "oxcaml_unsafe_unroll_pollfree", "ox54_base"),
         ("unpatched 5.4.0+ox against 5.2.0+ox without polls", "oxcaml52_unsafe_unroll_pollfree", "ox54_base"),
     ]),
    ("pass_ip", "Compiler pass: interior pointers (patch 2)",
     "-[no-]cmm-interior-pointers", [
         ("over strength reduction", "ox54_sr", "ox54_ip"),
         ("flag off -> on, same compiler", "ox54_ip_off", "ox54_ip"),
         ("flag off against the patch-1 compiler (identical code)", "ox54_sr", "ox54_ip_off"),
         ("patches 1-2 over unpatched", "ox54_base", "ox54_ip"),
     ]),
    ("pass_ivs", "Compiler pass: invariant-stride induction variables (patch 3)",
     "-[no-]cmm-invariant-strides, -[no-]cmm-carried-pointers", [
         ("over interior pointers", "ox54_ip", "ox54_ivs"),
         ("carried pointers against carried indices", "ox54_ivs_noptr", "ox54_ivs"),
     ]),
    ("pass_licm", "Compiler pass: register-neutral LICM (patch 4)",
     "-[no-]cmm-licm", [
         ("over invariant strides (declines: identical code)", "ox54_ivs", "ox54_licm"),
         ("all four passes over unpatched 5.4.0+ox", "ox54_base", "ox54_licm"),
         ("all four against the release without polls", "oxcaml_unsafe_unroll_pollfree", "ox54_licm"),
         ("all four against the release without polls, hand SR", "oxcaml_unsafe_sr_pollfree", "ox54_licm"),
     ]),
    ("safepoints", "The passes with safepoints on (PR compiler)",
     "release configuration: --enable-poll-insertion", [
         ("passes, safepoints on", "pr_off", "pr_all"),
         ("passes, no safepoints", "pr_off_nopoll", "pr_nopoll"),
         ("removing safepoints, passes off", "pr_off", "pr_off_nopoll"),
         ("removing safepoints, passes on", "pr_all", "pr_nopoll"),
         ("PR compiler without polls against the ladder", "ox54_licm", "pr_nopoll"),
         ("PR compiler, passes off, against unpatched ladder", "ox54_base", "pr_off_nopoll"),
         ("shipped release against PR compiler, passes off", "oxcaml_unsafe_unroll", "pr_off"),
     ]),
    ("counted", "Counted and unchecked loops (patches 6-8)",
     "-cmm-counted-loops, -cmm-unchecked-loops", [
         ("counted over the four passes", "pr_all", "pr_counted"),
         ("counted over passes off", "pr_off", "pr_counted"),
         ("counted over shipped OxCaml", "oxcaml_unsafe_unroll", "pr_counted"),
         ("pointer passes within counted mode", "pr_counted_noptr", "pr_counted"),
         ("counted without pointers against the four passes", "pr_all", "pr_counted_noptr"),
         ("no polls at all against counted", "pr_counted", "pr_nopoll"),
         ("poll-free ladder compiler against counted", "pr_counted", "ox54_licm"),
         ("unchecked against counted", "pr_counted", "pr_unchecked"),
         ("bounds checks kept, against counted", "pr_counted", "pr_safe_counted"),
         ("bounds checks kept, against shipped bounds-checked", "oxcaml_safe_unroll", "pr_safe_counted"),
     ]),
    ("stock_passes", "The passes on upstream OCaml 5.3.0",
     "patched 5.3.0 at ~/ocaml-pr-5.3 (MG_OCAML_PR)", [
         ("patched compiler, passes off, against stock", "ocaml_unsafe_unroll", "ocaml_pr_off"),
         ("passes on, polls kept", "ocaml_pr_off", "ocaml_pr_all"),
         ("counted over the passes", "ocaml_pr_all", "ocaml_pr_counted"),
         ("all of it over stock OCaml", "ocaml_unsafe_unroll", "ocaml_pr_counted"),
         ("OxCaml best against OCaml best", "ocaml_pr_counted", "pr_counted"),
     ]),
    ("pr_ladder", "The pass ladder on the PR compiler, counted loops on",
     "-cmm-counted-loops, then -[no-]cmm-{strength-reduction,interior-pointers,invariant-strides,licm}", [
         ("counted loops, passes off", "pr_off", "pr_c_off"),
         ("+ strength reduction", "pr_c_off", "pr_c_sr"),
         ("+ interior pointers", "pr_c_sr", "pr_c_ip"),
         ("+ invariant strides", "pr_c_ip", "pr_c_ivs"),
         ("+ LICM (all four passes)", "pr_c_ivs", "pr_counted"),
         ("whole ladder", "pr_off", "pr_counted"),
     ]),
    ("simd", "Explicit SIMD kernel",
     "MG_SIMD=1 (impl/oxcaml/build.sh, impl/oxcaml/simd_stubs.c)", [
         ("shipped release", "oxcaml_unsafe_unroll", "oxcaml_unsafe_simd"),
         ("5.2.0+ox", "oxcaml52_unsafe_unroll", "oxcaml52_unsafe_simd"),
         ("PR compiler, passes off", "pr_off", "pr_simd_off"),
         ("PR compiler, passes on", "pr_all", "pr_simd"),
         ("with counted loops", "pr_counted", "pr_simd_counted"),
         ("without polls", "pr_nopoll", "pr_simd_nopoll"),
         ("counted loops on top of SIMD", "pr_simd", "pr_simd_counted"),
     ]),
    ("release", "The release upgrade: 5.2.0+ox -> 5.4.0-ox7",
     "oxcaml52_* (opam switch 5.2.0+ox) against oxcaml_* (MG_OX_RELEASE)", [
         ("first port (bounds checks, plain kernel)", "oxcaml52_safe_plain", "oxcaml_safe_plain"),
         ("4-row kernel, bounds checks kept", "oxcaml52_safe_unroll", "oxcaml_safe_unroll"),
         ("plain kernel, -unsafe", "oxcaml52_unsafe_plain", "oxcaml_unsafe_plain"),
         ("shipped kernel (-unsafe, 4-row)", "oxcaml52_unsafe_unroll", "oxcaml_unsafe_unroll"),
         ("shipped kernel without polls", "oxcaml52_unsafe_unroll_pollfree", "oxcaml_unsafe_unroll_pollfree"),
         ("hand strength reduction", "oxcaml52_unsafe_sr", "oxcaml_unsafe_sr"),
         ("SSE2 kernel", "oxcaml52_unsafe_simd", "oxcaml_unsafe_simd"),
         ("5.2.0+ox against the PR compiler, passes off", "oxcaml52_unsafe_unroll", "pr_off"),
     ]),
]

CONCEPT_KEYS = [c[0] for c in CONCEPTS]

# The report's core set: the variants its main tables and figures show. Everything
# else in VARIANTS is a side result, quoted in the text where needed.
CORE = [
    "cpp_plain", "cpp_unroll", "cpp_novec", "cpp_O2_plain", "cpp_novec_avx",
    "rust_plain", "rust_unroll", "python",
    "ocaml_safe_plain", "ocaml_unsafe_sr", "ocaml_pr_counted",
    "oxcaml_safe_plain", "oxcaml_unsafe_plain", "oxcaml_unsafe_unroll", "oxcaml_unsafe_sr",
    "pr_off", "pr_c_off", "pr_c_sr", "pr_c_ip", "pr_c_ivs", "pr_counted",
    "pr_simd_counted",
]
# Giving up liveness: output stays correct, but loops can no longer be preempted.
LIVENESS = ["pr_unchecked", "pr_nopoll", "oxcaml_unsafe_unroll_pollfree"]


def resolve(name):
    return ALIASES.get(name, name)


def check():
    """Self-consistency: unique names, known concepts, comparisons name real variants."""
    names = [v["name"] for v in VARIANTS]
    assert len(names) == len(set(names)), "duplicate variant name"
    for v in VARIANTS:
        assert v["group"] in (HEADLINE, ABLATION, CONTROL), v
        assert v["concept"] in CONCEPT_KEYS, v
        r = v["recipe"]
        if r["kind"] in ("nop", "copy"):
            assert names.index(r["src"]) < names.index(v["name"]), f"{v['name']} before its source"
        if r["kind"] == "ml" and r["compiler"]:
            assert r["compiler"] in COMPILERS, v
    for _, _, _, pairs in CONCEPTS:
        for _, a, b in pairs:
            assert a in BY_NAME and b in BY_NAME, (a, b)
    return True


check()
