#!/usr/bin/env python3
"""
Overwrite OCaml's GC safepoint polls with NOPs, in an already-linked binary.

    python3 tools/nop_polls.py IN OUT [--only camlMain]

Why in-binary rather than a compiler flag
-----------------------------------------
`ocamlopt -disable-poll-insertion` also exists, and tools/bench_polls.sh runs it as a
cross-check. But it lets the compiler re-optimise everything downstream: different
register allocation, different scheduling, different code layout. That measures
"polls removed PLUS whatever the compiler then did differently".

Patching the linked binary holds all of that fixed. Same registers, same schedule,
same layout, same instruction addresses - only the poll is gone. That is the
controlled experiment; the flag is the corroborating one. They bracket the answer:

  binary NOP patch      lower bound: NOPs still occupy decode slots and ROB entries
  -disable-poll-insertion  upper bound: poll gone entirely, but codegen also moved

What a poll looks like, and why this is safe
--------------------------------------------
OCaml's amd64 backend reserves %r15 for the allocation pointer (young_ptr) and %r14
for the domain state pointer, whose first field is young_limit. Two sequences use
them, and telling them apart is the whole safety argument:

    SAFEPOINT POLL                  ALLOCATION
    cmp  (%r14),%r15                sub  $N,%r15        <- reserves N bytes first
    jbe  <handler>                  cmp  (%r14),%r15
                                    jb   <handler>

The condition code is the discriminator: polls use `jbe`, allocations use `jb`.
This tool patches ONLY the `jbe` form. NOPing an allocation check would remove the
heap-exhaustion test and corrupt memory silently rather than fail loudly, so the
tool asserts the allocation-site count is byte-for-byte unchanged afterwards.

Removing polls is safe for THIS program because a poll only provides preemption:
a point at which a pending signal can run, or at which a stop-the-world minor GC
can collect every domain. The benchmark is single-domain and installs no signal
handlers, and allocation checks are left intact, so the heap still grows and
collects correctly. It is NOT safe in general - never ship a binary patched this way.
"""

import argparse
import re
import shutil
import subprocess
import sys

# Intel-recommended multi-byte NOPs, indexed by length.
NOPS = {
    1: b"\x90",
    2: b"\x66\x90",
    3: b"\x0f\x1f\x00",
    4: b"\x0f\x1f\x40\x00",
    5: b"\x0f\x1f\x44\x00\x00",
    6: b"\x66\x0f\x1f\x44\x00\x00",
    7: b"\x0f\x1f\x80\x00\x00\x00\x00",
    8: b"\x0f\x1f\x84\x00\x00\x00\x00\x00",
    9: b"\x66\x0f\x1f\x84\x00\x00\x00\x00\x00",
}

INSN = re.compile(r"^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$")
FUNC = re.compile(r"^[0-9a-f]+ <(.+)>:$")


def nop_bytes(n):
    out = b""
    while n > 0:
        take = min(n, 9)
        out += NOPS[take]
        n -= take
    return out


def disasm(path):
    """[(vaddr, raw_bytes, text, enclosing_function)] for every instruction in .text."""
    p = subprocess.run(["objdump", "-d", path], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"objdump failed on {path}: {p.stderr[:400]}")
    out, func = [], "?"
    for line in p.stdout.splitlines():
        f = FUNC.match(line)
        if f:
            func = f.group(1)
            continue
        m = INSN.match(line)
        if m:
            out.append((int(m.group(1), 16),
                        bytes.fromhex(m.group(2).replace(" ", "")),
                        m.group(3).strip(), func))
    return out


def find_sites(insns):
    """Poll sites (cmp+jbe) and allocation sites (cmp+jb), as (vaddr, length, func)."""
    polls, allocs = [], []
    for i in range(len(insns) - 1):
        va, raw, text, func = insns[i]
        parts = text.split()
        # objdump pads the mnemonic, so compare on split tokens rather than raw text
        if parts[0] != "cmp" or "".join(parts[1:]) != "(%r14),%r15":
            continue
        nva, nraw, ntext, nfunc = insns[i + 1]
        if nva != va + len(raw) or nfunc != func:
            continue
        op = ntext.split()[0]
        if op == "jbe":
            polls.append((va, len(raw) + len(nraw), func))
        elif op == "jb":
            allocs.append((va, len(raw) + len(nraw), func))
    return polls, allocs


def sections(path):
    p = subprocess.run(["objdump", "-h", path], capture_output=True, text=True)
    secs = []
    for line in p.stdout.splitlines():
        m = re.match(r"\s*\d+\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)",
                     line)
        if m:
            secs.append((m.group(1), int(m.group(3), 16), int(m.group(2), 16),
                         int(m.group(5), 16)))   # name, vma, size, file offset
    return secs


def vaddr_to_off(secs, va):
    for _, vma, size, off in secs:
        if vma <= va < vma + size:
            return off + (va - vma)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--only", default="",
                    help="only patch polls in functions whose name starts with this "
                         "(e.g. camlMain); default patches every poll in the binary")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    insns = disasm(args.inp)
    polls, allocs = find_sites(insns)
    if not polls:
        sys.exit(f"{args.inp}: found no safepoint polls - already patched, or built "
                 f"with -disable-poll-insertion?")

    targets = [p for p in polls if not args.only or p[2].startswith(args.only)]
    secs = sections(args.inp)

    shutil.copyfile(args.inp, args.out)
    with open(args.out, "r+b") as f:
        for va, length, _ in targets:
            off = vaddr_to_off(secs, va)
            if off is None:
                sys.exit(f"vaddr {va:#x} is in no mapped section")
            f.seek(off)
            f.write(nop_bytes(length))
    shutil.copymode(args.inp, args.out)

    # Verify against the patched binary itself, not against intent.
    after_polls, after_allocs = find_sites(disasm(args.out))
    remaining = [p for p in after_polls if not args.only or p[2].startswith(args.only)]
    if remaining:
        sys.exit(f"FAILED: {len(remaining)} polls survived the patch")
    if len(after_allocs) != len(allocs):
        sys.exit(f"FAILED: allocation sites changed {len(allocs)} -> {len(after_allocs)}. "
                 f"An allocation check was damaged; the binary is unsafe. Aborting.")

    if not args.quiet:
        from collections import Counter
        hot = Counter(f for _, _, f in targets)
        print(f"patched {len(targets)} of {len(polls)} safepoint polls "
              f"({len(polls) - len(targets)} left alone)")
        print(f"allocation checks preserved: {len(after_allocs)} (unchanged)")
        print("  top functions by polls removed:")
        for name, n in hot.most_common(6):
            print(f"    {n:4d}  {name}")


if __name__ == "__main__":
    main()
