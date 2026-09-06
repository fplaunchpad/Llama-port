#!/usr/bin/env bash
# Build the OxCaml port. Run inside WSL (or any Linux) with the OxCaml switch active.
#
#   wsl -d Debian -- bash impl/oxcaml/build.sh
#
# OxCaml targets linux-x86_64, so this binary does not run natively on Windows.
# Correctness is platform-independent (verified: the same source under g++ 14.2/glibc
# and g++ 15.2/UCRT produces bit-identical output), but SPEED comparisons must be run
# entirely inside one environment - see BENCHMARK.md section 5.
set -euo pipefail
cd "$(dirname "$0")"
eval "$(opam env --switch=5.2.0+ox 2>/dev/null)" || true
mkdir -p build
# intermediates into build/ so the source dir stays clean
ocamlopt -O3 -I +unix unix.cmxa main.ml -o build/microgpt_infer \
         -I build -intf-suffix .mli 2>&1
rm -f main.cmi main.cmx main.o build/main.cmi build/main.cmx build/main.o
echo "built impl/oxcaml/build/microgpt_infer"
