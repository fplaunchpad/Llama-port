# UGRC 2 report

LaTeX source for the UGRC 2 report on porting microgpt and closing the OxCaml/C++ gap.

## Build

```
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

`latexmk -pdf main.tex` does the same. On Overleaf, upload this folder and compile `main.tex` with pdfLaTeX.
Packages used are all in TeX Live / MiKTeX: geometry, lmodern, amsmath, graphicx, booktabs, tabularx,
multirow, xcolor, enumitem, caption, subcaption, float, listings, fancyhdr, titlesec, microtype, hyperref.

## Figures

Every figure is a PDF in `figures/`, generated from the measured numbers by

```
python figures/make_figures.py          # add --png for previews
```

(requires matplotlib). Each plotting function names the benchmark run its numbers come from.

## Layout

- `main.tex`: preamble, title page, section list
- `sections/NN_*.tex`: one file per section, in story order
- `references.bib`: bibliography
