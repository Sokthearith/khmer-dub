---
name: Khmer Dub
description: A local Chinese-to-Khmer dubbing studio dyed like hol silk on an indigo shell.
colors:
  turmeric: "#e8a62a"
  turmeric-light: "#f2b94a"
  turmeric-ink: "#1a1203"
  lac: "#c9384d"
  lac-text: "#f07386"
  on-lac: "#ffffff"
  sky-indigo: "#5f80e6"
  sky-text: "#93abff"
  error-ground: "#2c1230"
  error-text: "#ffc2cb"
  jade: "#3aa883"
  indigo-ground: "#10143a"
  indigo-panel: "#161b45"
  indigo-panel-alt: "#141943"
  indigo-rail: "#1b2147"
  indigo-raised: "#262e5e"
  rule: "#343c74"
  rule-light: "#4a5290"
  raw-silk: "#f1e8d6"
  silk-muted: "#bdbdd6"
  silk-faint: "#9396bb"
typography:
  display:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "34px"
    fontWeight: 500
    lineHeight: 1.75
  display-compact:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "30px"
    fontWeight: 500
    lineHeight: 1.75
  display-small:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "24px"
    fontWeight: 500
    lineHeight: 1.75
  wordmark:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  wordmark-khmer:
    fontFamily: "KD Moul, Moul, serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  headline:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "22px"
    fontWeight: 600
  title:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "19px"
    fontWeight: 600
    fontFeature: "tnum"
  khmer-line:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.7
  button:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "16px"
    fontWeight: 600
  nav:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "15px"
    fontWeight: 500
  body:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "15px"
    fontWeight: 400
  hint:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  caption:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    fontFeature: "tnum"
  label:
    fontFamily: "KD Kantumruy, Kantumruy Pro, KD Noto Khmer, Noto Sans Khmer, ui-sans-serif, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    letterSpacing: "0.05em"
  mono:
    fontFamily: "ui-monospace, monospace"
rounded:
  none: "0px"
spacing:
  "0.5": "4px"
  "1": "8px"
  "1.5": "12px"
  "2": "16px"
  "3": "24px"
  "4": "32px"
components:
  button-primary:
    backgroundColor: "{colors.turmeric}"
    textColor: "{colors.turmeric-ink}"
    rounded: "{rounded.none}"
  button-primary-hover:
    backgroundColor: "{colors.turmeric-light}"
    textColor: "{colors.turmeric-ink}"
    rounded: "{rounded.none}"
  button-secondary:
    backgroundColor: "{colors.indigo-rail}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  button-secondary-hover:
    backgroundColor: "{colors.indigo-raised}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  button-action:
    typography: "{typography.button}"
    height: "52px"
    rounded: "{rounded.none}"
  block:
    backgroundColor: "{colors.indigo-panel}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  input:
    backgroundColor: "{colors.indigo-ground}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  choice-chip:
    backgroundColor: "{colors.indigo-rail}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  choice-chip-selected:
    backgroundColor: "{colors.indigo-raised}"
    textColor: "{colors.raw-silk}"
    rounded: "{rounded.none}"
  checkbox-selected:
    backgroundColor: "{colors.turmeric}"
    rounded: "{rounded.none}"
  rail:
    backgroundColor: "{colors.indigo-rail}"
    width: "232px"
  rail-step:
    textColor: "{colors.silk-muted}"
    typography: "{typography.nav}"
    height: "48px"
    padding: "12px 21px"
  rail-step-active:
    backgroundColor: "{colors.indigo-raised}"
    textColor: "{colors.raw-silk}"
    typography: "{typography.nav}"
    height: "48px"
  rail-step-number:
    textColor: "{colors.silk-muted}"
    size: "24px"
    rounded: "{rounded.none}"
  rail-step-number-active:
    textColor: "{colors.turmeric}"
    size: "24px"
    rounded: "{rounded.none}"
  rail-step-number-done:
    backgroundColor: "{colors.jade}"
    textColor: "{colors.indigo-ground}"
    size: "24px"
    rounded: "{rounded.none}"
  rail-step-number-active-done:
    backgroundColor: "{colors.turmeric}"
    textColor: "{colors.turmeric-ink}"
    size: "24px"
    rounded: "{rounded.none}"
  header:
    backgroundColor: "{colors.indigo-ground}"
    textColor: "{colors.raw-silk}"
    height: "80px"
  header-mark:
    backgroundColor: "{colors.indigo-rail}"
    width: "232px"
    padding: "16px 24px"
  header-count:
    textColor: "{colors.raw-silk}"
    typography: "{typography.title}"
    padding: "0 20px"
  header-count-complete:
    textColor: "{colors.jade}"
    typography: "{typography.title}"
  shuttle:
    backgroundColor: "{colors.turmeric}"
    height: "2px"
    width: "22%"
  weft-band:
    backgroundColor: "{colors.indigo-ground}"
    height: "48px"
    rounded: "{rounded.none}"
  weft-block-sreymom:
    backgroundColor: "{colors.lac}"
  weft-block-piseth:
    backgroundColor: "{colors.sky-indigo}"
  weft-block-current:
    backgroundColor: "{colors.turmeric}"
  specimen-field:
    backgroundColor: "{colors.indigo-ground}"
    textColor: "{colors.raw-silk}"
    typography: "{typography.display}"
    rounded: "{rounded.none}"
  voice-chip-sreymom-selected:
    backgroundColor: "{colors.lac}"
    rounded: "{rounded.none}"
  voice-chip-piseth-selected:
    backgroundColor: "{colors.sky-indigo}"
    textColor: "{colors.indigo-ground}"
    rounded: "{rounded.none}"
  table-row-current:
    backgroundColor: "{colors.indigo-raised}"
  table-number-current:
    backgroundColor: "{colors.turmeric}"
    textColor: "{colors.turmeric-ink}"
---

# Design System: Khmer Dub

## Overview

**Creative North Star: "Hol Silk"**

Khmer Dub is a studio for weaving one episode at a time. The whole app is an indigo-dyed cloth, and everything that means something is a dye laid into it: turmeric marks where the creator is and what to press next, lac red is Sreymom, dyed sky-indigo is Piseth, jade is done. Nothing else carries colour. Every dialogue line is a weft thread, and on Review the whole episode is drawn as one woven band whose blocks are as wide as the lines are long.

The density is a working tool's, built for sessions that last hours: a fixed step rail on the left, a header that reads the project's counts as numbers on hairline rules, and work areas made of flat indigo panels divided by 1px rules. Corners are square, surfaces are flat, and depth comes from four close steps of indigo. Khmer is set larger and brighter than anything beside it, up to a 34px specimen in the line editor, because Khmer is the product.

The world refuses the category default for media tools: a grey or near-black editor shell with one blue accent, gradient banners, rounded pill chips and soft shadows. It keeps the same indigo cloth whether the user's system theme is light or dark.

**Key Characteristics:**
- An indigo-dyed shell in both system themes; four indigo steps do the work shadows usually do.
- Four dyes, four meanings: turmeric = here and next, lac = Sreymom, sky-indigo = Piseth, jade = done.
- Square corners and 1px hairlines everywhere; flat fills; stripes only where they read as thread.
- Khmer at specimen scale; Chinese always muted and smaller.
- The episode weft band is the signature: one block per line, block width = line duration.
- One motion: a turmeric shuttle thread crossing under the header while a job runs.

## Colors

Hol silk dyes on indigo: a deep blue-violet cloth, raw-silk text, and four saturated dyes that each mean exactly one thing. The tokens map one-to-one to the palette constants at the top of `src/khmerdub/ui.py`, and `hol_theme()` feeds the same values to every Gradio theme variable.

### Primary
- **Turmeric** (#e8a62a, `TUR`): "You are here; do this next." The current line (its weft block and its table number cell), the active rail step's 3px bar and number square, the one primary button in an action row, checked checkboxes, slider fill, the 2px focus outline, links, the text caret, the header shuttle, the working-status text, the time estimate, and user-drawn blur boxes on the frame.
- **Turmeric Light** (#f2b94a, `TUR_L`): hover for primary buttons and links only.
- **Turmeric Ink** (#1a1203, `TUR_INK`): text on any turmeric fill (8.76:1), and the text colour of selections.

### Secondary
The voice dyes. A voice keeps its dye everywhere it appears.
- **Lac Red** (#c9384d, `LAC`): Sreymom. Her weft blocks, her key swatch, the selected Sreymom voice chip, and the border of error toasts. A fill for marks, not a ground for body text.
- **Lac Text** (#f07386, `LAC_T`): Sreymom's name as text on indigo (the table's Voice column, 5.88:1 on panel) and the error icon.
- **Sky-Indigo** (#5f80e6, `SKY`): Piseth. His weft blocks, his key swatch, and the selected Piseth voice chip, which carries indigo-ground text (4.83:1).
- **Sky Text** (#93abff, `SKY_T`): Piseth's name as text on indigo (7.45:1 on panel).
- **Error Ground** (#2c1230) and **Error Text** (#ffc2cb): Gradio's error toasts and modals, edged in lac. Errors always arrive as words, so the shared lac never reads as a bare Sreymom mark.

### Tertiary
- **Jade** (#3aa883, `JADE`): done. Filled step-number squares, checked line numbers in the table (weight 600), header count numerals once the count is complete (every line in Khmer, every line checked, video ready), and the automatically found blur boxes drawn on the frame ("green boxes" in the copy).

### Neutral
- **Indigo Ground** (#10143a, `GROUND`): the page, the header, every input and textarea (sunk below its panel), the weft band's ground, code blocks, the scrollbar track.
- **Indigo Panel** (#161b45, `PANEL`): Gradio blocks and panels, even table rows.
- **Indigo Panel Alt** (#141943): odd table rows. The stripe is meant to be barely there.
- **Indigo Rail** (#1b2147, `RAIL`): the step rail, the wordmark cell, secondary buttons, unselected choice chips.
- **Indigo Raised** (#262e5e, `RAISED`): hover, the active rail step, the current table row, selected choice chips, and an empty Khmer cell in the table (marking a line not yet translated).
- **Rule** (#343c74, `RULE`): every 1px hairline: block borders, header and rail edges, facts rows, count dividers, group-heading underlines, table borders, the footer rule.
- **Rule Light** (#4a5290, `RULE_L`): step-number square outlines, checkbox outlines, the scrollbar thumb, the dashed next-line rule, and the raw-thread stripe.
- **Raw Silk** (#f1e8d6, `SILK`): primary text and the Khmer specimen; also the 1px ring around the current weft block.
- **Silk Muted** (#bdbdd6, `SILK_2`): secondary text: field labels, hints, metadata, rail labels at rest, and all Chinese source text.
- **Silk Faint** (#9396bb, `SILK_3`): the Khmer hints in the rail, placeholders, Gradio info text, and user blur boxes outside their time range.

### Named Rules
**The Dye Rule.** Every hue is a meaning: turmeric = here and next, lac = Sreymom, sky-indigo = Piseth, jade = done. An element with none of these meanings stays indigo and silk.

**The One Thread Rule.** Turmeric marks one place at a time: one current line, one active step, one primary button per action row.

**The Same Cloth Rule.** The indigo shell holds in light and dark system themes alike. Every Gradio theme variable is set to the same value as its `_dark` twin, and `color-scheme` is forced to dark.

## Typography

**Display Font:** Kantumruy Pro (variable 100–900, bundled and served as "KD Kantumruy"), with Noto Sans Khmer (bundled as "KD Noto Khmer"), then ui-sans-serif
**Body Font:** Kantumruy Pro, the same stack: one family for Latin and Khmer UI
**Label/Mono Font:** Moul (bundled as "KD Moul") for the Khmer wordmark only; ui-monospace for the log and code

**Character:** Kantumruy Pro draws Khmer and Latin with one weight and rhythm, so the English labels and their Khmer hints read as a single voice. Moul, the ornamental Khmer display face, appears once, as a turmeric seal under the wordmark. Chinese has no bundled face; it renders in the system CJK font and is always muted.

### Hierarchy
- **Display / Specimen** (500, 34px, 1.75): the Khmer line being edited. It drops to 30px when the viewport is 960px tall or less, and to 24px below 900px wide. The tall line-height leaves room for Khmer stacked vowels and subscript consonants.
- **Headline** (600, 22px): step titles ("Review"), followed by the step's Khmer word at 15px/400 in silk-muted, 12px to the right. The project name in the header is 21px/600. The wordmark "Khmer Dub" is 22px/700 at -0.01em and 1.1 line-height, with the Moul "ឌប់ខ្មែរ" beneath it at 13px in turmeric.
- **Title** (600, 19px, tabular): the header count numerals.
- **Khmer Line** (400, 17px, 1.7): the Khmer column of the line table. The next-line preview under the editor is 18px/500/1.7 in silk-muted.
- **Body** (400, 15px): facts values, table cells, messages; rail step labels at weight 500. Chinese is 15px silk-muted in the table and 16px silk-muted in the editor's Chinese field.
- **Hint** (400, 14px): step descriptions, field hints, header metadata ("0:36 · 1280×720"), and the working status in the header.
- **Caption** (400, 13px, tabular): the weft band's header line, the line head ("Line 4 of 8 · 0:14.1 → 0:17.0"), facts labels, and "Next · line 5".
- **Label** (400, 12px, +0.05em, uppercase): header count labels, settings group headings (with a hairline beneath), and table column headers. It always names the content directly beneath it.
- **Button** (600, 16px): the 52px action-row buttons. Other buttons keep Gradio's default size.

### Named Rules
**The Khmer Is Larger Rule.** Wherever Khmer sits beside Chinese or English, it is the bigger, brighter line: a 34px silk specimen over a 16px muted Chinese field in the editor, 17px Khmer beside 15px muted Chinese in the table.

**The Seal Rule.** Moul appears only as the Khmer wordmark (13px, turmeric). It is never used for headings, buttons or body text.

**The Tabular Rule.** Times, counts, line numbers, sizes and estimates use tabular numerals.

## Layout

The app is full-bleed: no max-width, no outer padding. A header row sits on top: a 232px wordmark cell on indigo-rail, then a fluid project cell, at least 80px tall, with a 1px rule beneath. Below it, the 232px step rail (filling the viewport height) sits beside a fluid work area padded 32px at the top and sides and 56px at the bottom.

Every step page has the same anatomy: the headline with its Khmer word and a 14px hint line, the content, and then an action row 24px below with 12px gaps and equal-width buttons, primary first.

- **Review:** the weft band spans the work area with 24px beneath it. Below it, the line table (3 parts, at least 560px) sits beside the line editor (2 parts, at least 320px). Table columns are #, Time, Chinese, Khmer and Voice at 7 / 9 / 28 / 42 / 14 %. The table is at most 620px tall, with its own scroll that follows the current line.
- **Upload and Blur:** a 3:2 split, with the tool on the left and the preview or facts on the right.
- **Settings:** a row of preset chips, then two columns of fields under uppercase group headings. Rarely used options sit in a "More options" accordion.

Spacing runs on a 4px base with 8px beats: 4, 8, 12, 16, 24, 32 (the spacing tokens). Observed outside the scale: 20px (count cell padding, phone work-area padding), 56px (bottom of the work area), and 21px rail step padding, which adds to the 3px state bar to make 24.

Responsive behaviour:
- **900px wide or less:** the rail becomes a strip under the header. Steps sit in a row (wrapping on phones), the active step takes a 3px turmeric underline instead of the left bar, the rail's Khmer hints are hidden, and Cut, Batch and Help split off behind a 1px left rule. Header cells tighten (12px/16px padding, 12px count padding) and the work area pads 20px, 16px, 40px. On Review the line editor moves above the table, the table viewport caps at 360px, the specimen drops to 24px, and the weft header stacks with its key wrapping. The shuttle spans the full header.
- **600px wide or less:** the header stacks: a wordmark row (Latin and Moul on one baseline, rule beneath), then the project name and the counts at full width. Tables scroll sideways at a 640px minimum.
- **960px tall or less:** the specimen drops to 30px so the editor and Save and next stay in the first viewport.

**The Shared Column Rule.** The wordmark cell and the rail are the same 232px column, and the shuttle starts at its edge. Anything added to the left edge aligns to it.

## Elevation & Depth

The system is flat. Every Gradio shadow variable is set to `none`, and buttons neither lift nor move on hover or press. Depth is tonal: four indigo steps, ground (#10143a), panel (#161b45), rail (#1b2147) and raised (#262e5e), plus 1px rules. Inputs sink to ground inside their panel; hover, the active step and the current row rise to raised. The only rings are the 2px turmeric focus outline (2px offset) and the 1px silk outline around the current weft block.

### Shadow Vocabulary
None. No shadow tokens exist.

### Named Rules
**The Flat Cloth Rule.** No shadow, glow, blur or lift. To bring something forward, step it one indigo tone up; to make a field, step it down to ground.

## Shapes

Everything is square: 0px radius on every surface, including Gradio's own blocks, buttons, chips, inputs, accordions and tables (the theme uses `radius_none`). Edges are 1px hairlines in rule. The only heavier strokes carry state: the 3px turmeric bar on the active rail step (left edge on desktop, bottom edge when narrow), the 2px focus outline, and the 2px shuttle. The one dashed line is the 1px rule-light dash above the next-line preview, the thread waiting its turn.

Squares recur as marks: 24px step-number squares, 10px weft-key swatches, flat weft blocks. The only patterned fills are hard-stop stripes that read as thread: 1px dark horizontal threads on a 3px pitch over every weft block, 1px rule-light vertical stripes on a 3px pitch for lines with no Khmer yet, and the split lac/sky swatch in the weft key.

### Named Rules
**The Square Thread Rule.** No radius, no pills, no circles of our own; the only round shape is Gradio's native radio dot.

## Components

### Buttons
Flat, square, and plainly labelled with their action.
- **Shape:** square (0px) and borderless as rendered: the fill is the shape.
- **Primary:** turmeric fill, turmeric-ink text; hover turmeric-light. No shadow, no movement. One per action row.
- **Secondary:** indigo-rail fill, raw-silk text; hover indigo-raised. It sits one indigo tone above the ground.
- **Action row:** 52px tall, 16px/600, 12px gaps, 24px above; primary first ("Continue to settings", then "Do everything automatically").
- **Focus:** 2px turmeric outline at 2px offset, applied globally.

### Chips
Gradio radio choices rendered as square chips.
- **Style:** borderless square fills: indigo-rail with raw-silk text inside the indigo-panel block; the native radio dot fills turmeric when selected.
- **State:** hover and selected both step up to indigo-raised; the turmeric dot is what tells selected apart.
- **Voice chips (line editor):** the selected Sreymom chip fills with lac and uses on-lac (white) text; the selected Piseth chip fills with sky-indigo and uses indigo-ground text. The selected dot turns raw silk.

### Cards / Containers
Gradio blocks are the only containers; there are no cards.
- **Corner Style:** square (0px).
- **Background:** indigo-panel (#161b45).
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px rule. Block labels in silk-muted, info text in silk-faint.
- **Internal Padding:** Gradio's default `spacing_md`.

### Inputs / Fields
- **Style:** a borderless indigo-ground fill sunk into its indigo-panel block, square. Placeholder silk-faint; caret turmeric.
- **Focus:** the global 2px turmeric outline; no glow, no fill change. The theme also sets field borders (rule, rule-light on hover, turmeric on focus), but Gradio 6 draws them at zero width, so the outline and the sunk fill carry the state.
- **Checkbox and slider:** the checkbox sits on ground with a rule-light outline and fills turmeric when checked; the slider fill is turmeric.
- **Error:** Gradio's error surfaces use error-ground, a lac border and error-text.

### Navigation
The step rail: a numbered sequence, because the workflow order is information.
- **Rail:** 232px, indigo-rail, 1px rule on the right, 16px top and 24px bottom padding.
- **Step:** 48px tall, 15px/500 silk-muted label, 12px × 21px padding behind a transparent 3px left bar. A 24px square on the left holds the step number (12px/600, tabular) inside a 1px rule-light outline; the step's Khmer word sits at the far right in 12px silk-faint.
- **Hover:** indigo-raised fill, raw-silk label.
- **Active:** indigo-raised fill, raw-silk label, turmeric left bar, turmeric number and outline.
- **Done:** the number square fills jade with an indigo-ground numeral. Active and done together: turmeric fill, turmeric-ink numeral.
- **Extras (Cut, Batch, Help):** no number square; labels indent to align with the step labels; set apart by 24px and a 1px rule above.
- **Narrow screens:** see Layout. The rail becomes a strip with a 3px turmeric underline on the active step.

### Header and Shuttle
- **Wordmark cell:** 232px on indigo-rail with a 1px rule on its right: "Khmer Dub" over the Moul "ឌប់ខ្មែរ".
- **Project cell:** the project name (21px/600), then metadata at 14px silk-muted, then the working status in turmeric while a job runs.
- **Counts:** pushed right. Each count is a cell with 20px side padding and a 1px rule on its left: a 12px uppercase label over a 19px/600 tabular numeral. A complete count turns its numeral jade. The Video count reads "ready" or "not yet".
- **Empty state:** "No video open. Start with Upload." at 15px silk-muted.
- **Shuttle:** while a job runs, a 2px turmeric thread (22% wide) slides along the header's bottom rule from the rail's edge, 2.4s `cubic-bezier(.16,1,.3,1)`, alternating. Under reduced motion it becomes a still, full-width thread at 60% opacity. It is the system's only animation.

### Weft Band
The signature. The whole episode as one woven strip.
- **Band:** 48px tall, full width of the work area, indigo-ground with a 1px rule border, 24px below it.
- **Blocks:** one per line, `flex-grow` = the line's duration in seconds (minimum 0.15), so block width is line length. Silence between lines is empty ground at its true length.
- **Dye:** Sreymom lines lac, Piseth lines sky-indigo. Every block carries 1px dark horizontal threads on a 3px pitch.
- **States:** a line not yet checked fades to 42% opacity; a line with no Khmer yet is raw thread (1px rule-light stripes on a 3px pitch); the current line is solid turmeric with a 1px silk ring, raised above its neighbours.
- **Head and key:** a 13px line above ("Episode · 8 lines · 1 checked · block width = line length") with a key of 10px square swatches on the right. The raw-thread entry appears only while some line lacks Khmer.
- **Tooltip:** each block's title gives its number, start time and the start of its Khmer.
- **Empty:** the bare ground band with "The episode appears here after Settings → Start."

### Khmer Line Editor
The current line owns the editor; the next line waits below.
- **Line head:** 13px silk-muted tabular ("Line 4 of 8 · 0:14.1 → 0:17.0 · checked").
- **Chinese:** a read-only field at 16px in silk-muted.
- **Khmer specimen:** a textarea at 34px/500/1.75 in raw silk on ground (30px on short viewports, 24px on narrow ones).
- **Voice:** two voice chips (see Chips).
- **Buttons:** Play original and Play Khmer; then Previous, Save and Save and next (primary, double width).
- **Next line:** a 1px dashed rule-light line, 12px gap, "Next · line 5" at 13px, then the next line's Khmer at 18px/500/1.7 in silk-muted ("Last line" at the end).

### Line Table
- **Header:** 12px uppercase, +0.05em, silk-muted.
- **Rows:** 15px tabular on alternating panel and panel-alt, line-height 1.6. Chinese in silk-muted; Khmer at 17px/1.7; Voice as text in lac-text or sky-text; a checked line's number in jade (600); an empty Khmer cell filled indigo-raised.
- **Current row:** the whole row in indigo-raised; its number cell solid turmeric with turmeric-ink 600.
- **Scroll:** the table scrolls itself to keep the current line about a third of the way down.

### Facts List
The project facts on Upload, set as a definition list on hairlines.
- A 140px term column and a fluid value column, 1px rule above and under every row, 10px vertical padding.
- Terms at 13px silk-muted; values at 15px tabular raw silk; the time estimate in turmeric (600).

### Frame Overlays
Drawn into the video frame on Blur, in the same dyes.
- Automatically found text: 2px jade boxes.
- The user's boxes: 3px turmeric, or silk-faint outside their time range.
- The first corner of a new box: a turmeric cross.

## Do's and Don'ts

### Do:
- **Do** keep the indigo ground (#10143a) in both light and dark system themes; set every Gradio theme variable and its `_dark` twin to the same value.
- **Do** reserve turmeric (#e8a62a) for "here and next": the current line, the active step, one primary button per action row, focus, links, caret and selection.
- **Do** keep each voice in its dye everywhere it appears: lac (#c9384d) for Sreymom, sky-indigo (#5f80e6) for Piseth, with lac-text (#f07386) and sky-text (#93abff) when the name is set as text on indigo.
- **Do** mark done in jade (#3aa883) only: step squares, checked line numbers, complete counts, found blur boxes.
- **Do** draw episode-length data as weft: block width = duration, silence as empty ground, unchecked at 42% opacity, untranslated as raw-thread stripes, current in turmeric with a 1px silk ring.
- **Do** set Khmer larger and brighter than the Chinese or English beside it: specimen 34px/500/1.75 (30px at 960px tall or less, 24px below 900px wide), table Khmer 17px/1.7, next line 18px.
- **Do** pair each step title with its Khmer word (15px silk-muted) and each rail step with a 12px Khmer hint.
- **Do** divide with 1px rule (#343c74) hairlines and indigo tone steps, with 0px radius everywhere.
- **Do** use tabular numerals for times, counts, line numbers, sizes and estimates.
- **Do** keep motion to the shuttle: one 2px turmeric thread, 2.4s `cubic-bezier(.16,1,.3,1)`, still under reduced motion.

### Don't:
- **Don't** round anything: no pills, no rounded blocks, no rounded buttons.
- **Don't** add shadows, glows, blurs or hover lift; every Gradio shadow variable stays `none`.
- **Don't** use smooth or decorative gradients, and never gradient text. The only gradients allowed are hard-stop stripes that read as thread: weft texture, the raw-thread stripe, the split key swatch.
- **Don't** use turmeric as decoration, or for two primary actions in one row.
- **Don't** use lac or sky-indigo for anything but their voice; lac's error family appears only in worded error toasts.
- **Don't** set body-size raw-silk text on a lac fill: it measures 4.15:1. Text on lac uses on-lac (#ffffff, 5.1:1), as the selected Sreymom chip does.
- **Don't** put silk-faint (#9396bb) text on indigo-raised (#262e5e): it measures 4.48:1. Keep it on ground, panel or rail; on the active or hovered rail step the Khmer hint switches to silk-muted.
- **Don't** use Moul for anything but the Khmer wordmark.
- **Don't** extend the 3px coloured bar beyond the active rail step; cards, alerts and table rows take no coloured side bars.
- **Don't** put a small uppercase label above a step title or the project name; the 12px tracked label names a count, a settings group or a table column, never a heading.
- **Don't** let Chinese outrank Khmer in size or brightness; Chinese is always silk-muted.
