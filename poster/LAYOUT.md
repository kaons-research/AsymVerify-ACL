# AsymVerify Poster: Layout and Sizing Specification

> **Superseded.** This spec describes an earlier design iteration (Times, stat-card
> bands). The shipped poster is `poster.tex`: Gemini beamerposter theme, Lato, A0
> portrait, rows = Task Overview + Key Insight | task figures / goose strip,
> full-width architecture, Results | Analysis, conclusion. Treat `poster.tex` as the
> source of truth; the palette and figure-iteration protocol below still apply.

Single source of truth for geometry, type, color, and section naming. The poster is the
sole presentation artifact, so it is detailed and self-contained. Aesthetic register:
orthodox ACL academic poster, Times (newtx), purple/lavender identity.

## Page and grid
- Page: A0 portrait, 841 x 1189 mm.
- Margins: 22 mm all sides. Live area: 797 x 1145 mm.
- Inter-band gutter: 10 mm (7 gutters = 70 mm).
- Two-column bands: column width 390 mm, column gutter 17 mm.

## Vertical budget (bands, top to bottom)
| # | Band | Height (mm) |
|---|------|------------:|
| 0 | Header (logos, title, summary line) | 148 |
| 1 | Headline stats (4 cards) + leaderboard line | 90 |
| 2 | Task and Motivation  \|  Error Analysis | 141 |
| 3 | Method (cascade + 3 pass cards) | 165 |
| 4 | Experimental Setup (slim strip) | 42 |
| 5 | Error Coverage + Ablation  \|  Cross-Model + Inference Cost | 222 |
| 6 | Embedding-Space Analysis  \|  Qualitative Example | 175 |
| 7 | Conclusion + reproducibility + QR | 92 |

Sum bands 1075 + gutters 70 + margins 44 = 1189 mm exactly.

## Section titles (orthodox, accurate; no witty/meta phrasing)
- Band 2 left: **Task and Motivation**
- Band 2 right: **Error Analysis**
- Band 3: **Method**  (subtitle: confidence-gated asymmetric verification)
- Band 4: **Experimental Setup**
- Band 5 L-top: **Error Coverage by Verification Direction**
- Band 5 L-bottom: **Ablation Study**
- Band 5 R-top: **Cross-Model Replication**
- Band 5 R-bottom: **Inference Cost**
- Band 6 left: **Embedding-Space Analysis**
- Band 6 right: **Qualitative Example**
- Band 7: **Conclusion**
- Header summary line (factual, not an imperative slogan):
  "A confidence-gated cascade applies asymmetric verification only to low-confidence
  predictions; both verifiers correct through the Ambivalent class."

## Figures (standalone PDFs in figures/, embedded by width/height)
| File | Content | Embed | Aspect (w:h) |
|------|---------|------:|-------------:|
| fig_cascade.pdf | QA -> P1 -> gate(c>=tau) -> Output; low-conf routes to P2 (CR/CNR->AMB) and P3 (AMB->CR) | width 470 mm | ~3.75 : 1 |
| fig_funnel.pdf  | CR & CNR funnel into the AMB hub: CR<->AMB 84%, CNR<->AMB 13%, CR<->CNR 3% dashed | width 360 mm | ~3.6 : 1 |
| fig_errordir.pdf| horizontal stacked bar: P2-aligned 63.2% / P3-aligned 28.9% / outside 7.9% | width 360 mm | ~9 : 1 |
| fig_cost.pdf    | two vertical bars: AsymVerify 457 vs all-passes 924 (49.5%) | width 150 mm | ~1.6 : 1 |
| umap.pdf (have) | reused UMAP scatter | height 115 mm | ~1 : 1 |

Figure label text must be legible at the embed size (verify by rendering near final scale).
All figures \input figures/common.tex so palette and font match exactly.

## Logos
- assets/acl-logo.png  (have, 1200x230, official ACL 2026 wordmark)
- assets/semeval.*     (SemEval-2026 / CLARITY, sourced by logo agent)
- assets/kaons.pdf     (typeset K-star mark, built by logo agent)
- Header is a LIGHT band so the dark logos read; footer is the deep-purple band with
  white text, white QR tiles, and a typeset white K-star (no raster logos on dark).

## Type scale (Times / newtx; absolute pt for hero, relative for body)
- Title 90 pt bold; subtitle 36 pt; header summary 28 pt; task line 30 pt; author 26 pt.
- Card titles 34 pt bold; body 26 pt; tables 24 pt; captions 22 pt.
- Stat numerals 56 pt bold; stat captions 22 pt; conclusion 30 pt.
- beamerposter scale tuned so body \normalsize is ~26 pt.

## Color usage
- Brand chrome (title, rules, card title bars, footer) purple/lavender.
- Pass triad indigo/rose/emerald only inside the cascade and the class chips; always paired
  with a label or shape (colorblind-safe). AMB is the brand purple hub.
- gold reserved for the 2nd-place medal only.

## Build and iteration protocol
- Figures: pdflatex each standalone -> render PNG with ghostscript (gs -r110) -> inspect ->
  iterate until no overlaps and labels are crisp.
- Poster: pdflatex via latexmk -> render proof (gs -r45) -> inspect -> tune to zero overflow
  with a small slack, balanced columns, and consistent gutters.
- Verify final: page is exactly 841 x 1189 mm; fonts embedded; figures vector; numbers match
  paper/main.tex.
