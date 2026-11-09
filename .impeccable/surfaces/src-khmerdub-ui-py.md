---
version: 1
slug: "src-khmerdub-ui-py"
primary_target: "src/khmerdub/ui.py"
related_targets: []
---

# Khmer Dub studio (web app)

Scope: the whole Gradio web app (src/khmerdub/ui.py): Upload, Settings, Review, Blur, Export, Batch, Help. Visitor mode: Operate.

Audience and job: Khmer creators dubbing one ~1-hour Chinese episode at a time for Facebook, YouTube and TikTok; long waits, then careful line-by-line review. English-first labels with Khmer hints. Constraints: Gradio 6 components stay standard and working; styling only through theme, CSS and HTML blocks; must hold in the user's light or dark system theme.

Memorable moment: the episode weft band on Review, where the whole episode reads as one woven strip of dyed line blocks.

## Direction contract

THESIS: The episode is woven line by line; every dialogue line is a weft thread the creator dyes in Khmer. Refuses the category default: a grey/dark editor shell with one blue accent, gradient hero banner and rounded pill chips.

OWN-WORLD: Hol silk dyes on an indigo-dyed shell. Indigo ground (#12163a to #1b2147) owns the whole app in both system themes; raw-silk text (#f1e8d6); lac red (#b02a3c) = Sreymom; dyed sky-indigo (#5d7fe0) = Piseth; turmeric (#e2a128) = the current line, the primary action and the active step; jade (#2c8a6c) = done; undyed thread stripe = not reviewed. Square corners, 1px hairline rules, flat fills, no gradients, no glow. Kantumruy Pro for UI and Khmer; Moul only for the Khmer wordmark.

STORY: The creator sees where they are in the five steps, how much of the episode is translated, checked and voiced, and which line they are on; they fix a line, hear it, and move to the next without losing their place.

FIRST VIEWPORT: Left 232px indigo step rail: wordmark "Khmer Dub" with Moul "ឌប់ខ្មែរ", numbered steps 1–5 (done = jade square tick, active = turmeric left bar), Batch and Help below. Top header row: project name, length, counts (lines, Khmer, checked, voiced) as numbers on hairline rules. Review: full-width weft band (48px, block width = line duration, coloured by voice, current line turmeric), then the line table on the left and the line editor on the right with the Khmer line at specimen scale (about 36px) and Save & next in turmeric.

FORM: Hol Silk, rank 4 of the grounded list (karaoke VCD, dubbed-drama broadcast graphics, bilingual shop signs, hol silk, riel banknotes, school exercise books, palm-leaf manuscripts); seed:e850ca074243527b. Raises: specimen-scale Khmer (variable-font-specimen); current line owns the editor, next line waiting (vertical feed); states as precise marks on hairlines, no rounded chrome (centre-rail edition); block width = duration (star atlas); one strict 8px grid (Crouwel grid). Signature move: the episode weft band.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
