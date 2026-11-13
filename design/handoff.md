<!-- MANUAL HANDOFF -->
<!-- MANUAL TAKES PRIORITY OVER THE GENERATED HANDOFF -->
Read the readme.md.

The design here is handcrafted and agreed upon, changing it or not following it without a good reason is WRONG.

<!-- GENERATED HANDOFF -->
# Aicepeak Paper & Glass · Design-Übergabe

Nov 13, 2026 · @Felix

## The idea

Aicepeak looks like two materials: **paper** for everything deterministic, **glass** for everything that floats above it. One element never mixes the two.

- **Paper** is the page: square, flat, no shadow, hairline borders. Extracted line items, numbers, tables, tabs, KPI tiles, project tiles and the review button are paper. It reads like a well-set financial report.
- **Glass** is the tooling: the top bar, the AI assistant and the sign-in card. It is frosted, rounded and floats `16px` in from the screen edges. It is matte: no gloss, no rim light (only the sign-in card carries a 1 px top highlight).
- **Paper runs under glass.** The blue signal band and one soft blue glow sit behind the assistant. Without them glass looks like a grey box, so glass never sits on an empty ground.
- **One colour, one meaning.** Signal blue is AI and signals, amber is an open question (Rückfrage), green and red are signed deltas. If a colour appears for a second reason, one of the two changes.
- **Quiet by default.** Text is set in sentence case, never all-caps. Emphasis comes from a block of colour (the active tab, the most recent project), not from weight or size.

## What is in the export

The export lives flat in `design/` and works in two ways: plain CSS for any stack, or ready React 18 components. Open `reference.html` first. It shows every token and component and switches between light and dark.

| Path (in `design/`) | What | Use it for |
| --- | --- | --- |
| `tokens.css` | Every token as a CSS custom property, light and dark, plus the text-style classes | Any stack. Set `data-theme="light"` or `"dark"` on `<html>` |
| `components.css` | Component styles, class prefix `pg-` | Markup built by hand or by the React components |
| `aicepeak-paper-glass.js` | React components on `window.AicepeakPaperGlass`, no build step | React apps |
| `aicepeak-paper-glass.d.ts` | Props of every component, with notes | Reference while building |
| `tokens.json` | Source of the tokens, with a usage note for each | Generating tokens for other platforms |
| `aicepeak-mark.png` | The Aicepeak mark, 767 × 822 px source, shared with `login/` | Top bar (26 px), sign-in card (32 px); always size it in CSS |
| `login/` | Clickable sign-in prototype, see `login/handoff.md` | The sign-in flow |

`reference.html` loads React and ReactDOM 18.3.1 (UMD, pinned) from unpkg; there is no local `vendor/` folder.

Load order: the Google Fonts link for Russo One, Inter and JetBrains Mono, then `tokens.css`, then `components.css`, then (for React) React, ReactDOM and the component script.

The source of truth stays the design system artifact "Aicepeak Paper & Glass". This export is a snapshot from 13.11.2026.

## Colour

Each colour has one job. Every value comes from a token, so components never branch on the theme. Dark keeps the same structure with near-black paper and light ink.

| Role | Token | Light | Dark | Used for |
| --- | --- | --- | --- | --- |
| Page | `paper` | #F3F2EE | #151514 | The ground under everything |
| Structure | `paper-sunken` / `paper-column` | #E9E8E3 / #ECEBE6 | #1E1E1C / #232321 | Table heads, inactive tabs, tiles / highlighted columns, hover |
| Lines | `line` / `line-soft` | #C9C7C1 / #DAD8D3 | #3A3936 / #2C2B29 | Every paper border / row dividers, unlit dots |
| Text | `ink` / `ink-muted` / `ink-subtle` | #161616 / #5C5B57 / #6A6965 | #ECEBE7 / #A3A19B / #8E8C87 | Primary / secondary and labels / placeholders |
| Selection | `selection` | #161616 | #3A3936 | The active tab. In dark a grey block: white is for high emphasis only |
| AI and signals | `signal` | #4C9BF0 | #5AA6F5 | Signal band, lit dots, assistant dot, send button, title full stop, running status, most recent project |
| Open question | `review` / `review-ink` | #A9661C / #8A4F10 | #D19A4A / #E6B26B | Rückfrage tags, the review button |
| Deltas | `positive` / `negative` | #2F6B42 / #A3452E | #6FBF8A / #E58A72 | Signed numbers (+640, −164); `negative` also for negative project marks |
| Links | `link` | #1F6AC4 | #7DB6F7 | Text links, focus ring |
| Sign-in button | `button-neutral` | #C9C7C1 | #3A3936 | A quiet grey instead of black or white |

Rules that hold the palette together:

- **Never hard-code a colour**, not even an icon: use `currentColor` with a token.
- **White and black blocks are high emphasis.** In dark only the user's own chat bubble is light.
- **Signal is never decoration.** If something blue does not mean "AI" or "signal", it gets another colour.
- **Deltas always carry a sign**, so colour is never the only cue. Status never uses green or red.

## Type, spacing and shape

Three typefaces, each with one job: **Russo One** for titles, **Inter** for reading and numbers, **JetBrains Mono** for machine-like meta. Everything is in sentence case, including buttons and column heads.

| Style | Face | Size / weight | Used for |
| --- | --- | --- | --- |
| `page-title` | Russo One | 40 px / 400 | Once per screen, full stop in signal |
| `sign-in-title` | Russo One | 48 px / 400 | The sign-in card |
| `panel-title` | Russo One | 17 px / 400 | Glass panel headings |
| `section-title` | Inter | 17 px / 600 | Table and section titles, tile titles |
| `search-input` | Inter | 20 px / 600 | The search in a table head |
| `kpi-value` / `tile-value` | Inter | 22 px / 500, 17 px / 500 | Figures, tabular numbers |
| `body` / `body-strong` | Inter | 14 px / 400, 600 | Cells, nav, messages / highlighted columns, totals |
| `small` | Inter | 13 px / 400 | Descriptions, chips |
| `label` / `eyebrow` / `label-sm` | JetBrains Mono | 12 px, 12 px +0.06em, 11 px | Meta lines, column heads, status / line above the title / sources |

**Numbers** use tabular figures, a space as thousands separator (42 800), a true minus (−14 400) and a sign on every delta (+640, ±0). The unit is given once per block (`T€ · gerundet`), not in every cell.

**Spacing** runs on 4, 8, 12, 16, 20, 24 and 40 px. Glass floats 16 px from the screen edges. Paper content starts 18 px right of the bar's edge and 40 px below it, and paper blocks stack 24 px apart.

**Shape.** Paper is always square (0 px). Glass surfaces have 20 px corners, controls inside glass 12 px, chat bubbles 14 px. The sign-in card has 28 px corners and a 16 px button.

**Sizes.** Controls are 40 px high (never below, for touch), tabs 48 px, table rows 54 px, the top bar 64 px, the assistant 380 px wide and the table search 72 px.

## Glass

There are three kinds of glass. A screen uses one style for its top bar and assistant together.

| Kind | Fill (light / dark) | Backdrop filter | Where |
| --- | --- | --- | --- |
| Standard | rgba(250,250,247,.6) / rgba(36,36,34,.6) | `blur(22px) saturate(140%)` | Default top bar and assistant |
| Airy | rgba(246,245,242,.65) / as standard | light: `blur(24px) saturate(170%) brightness(1.08)` | Screens where blue sits behind the glass; controls inside are solid white without border or shadow (dark: no border) |
| Sign-in card | rgba(238,236,232,.74) / rgba(20,21,24,.78) | `blur(28px) saturate(160%)` | Only the sign-in, in the middle of the screen, with a 1 px top highlight and a deep drop shadow |

What keeps glass reading as glass:

- **Something behind it.** The signal band runs to the right screen edge under the assistant, and one blurred blue glow (520 px, 45 %) sits behind it. On an empty ground glass looks like a grey box.
- **Never tint it.** Airy glass keeps the paper tone; only the blur changes. Tinting it white or blue makes it read as a card.
- **No filter or transform on an ancestor.** `backdrop-filter` stops working inside an element that has a `filter` or `transform`. That is why the app layer behind the sign-in drops both once signed in.
- **Hairlines, not shadows, for definition.** Outline `glass-line`, dividers `glass-divider` (14 %), hover `glass-hover` (white 75 % in light, 14 % in dark).

## Screens and components

Every screen has the same frame: the glass top bar across the top, the assistant on the right, and paper content beneath. The three screens of A1 differ only in what is on the paper.

| Screen | Order on paper, top to bottom | Components |
| --- | --- | --- |
| Forecast (positions list) | Title block with status and review button → report tabs → KPI strip (signal band to the screen edge) → line-item table | `GlassBar`, `PageHeader`, `Tabs`, `KpiStrip`, `DataTable` with `LineItemName`, `DotMatrix`, `Delta`, `TopicsLink`, `StatusTag`; `AssistantPanel` open |
| Projects overview | Title block with "Neues Projekt" → "Weiterarbeiten" (last three projects, newest on signal) → status tabs with counts → projects table with search in its head → archive link | `PageHeader`, `ProjectTiles` / `ProjectTile`, `Tabs`, `DataTable` with `search`, `ProjectMark`, `StatusTag`; `AssistantPanel` rolled up |
| Sign-in | The real app behind, zoomed to 0.83 and blurred, a veil over it, the card in the middle | `SignInCard`, `.pg-veil` |

Two dot graphics, never mixed up:

- **DotMatrix** (forecast table): one line item's course over four periods. Each column lights from the bottom, scaled to the item's own range. One colour.
- **ProjectMark** (projects): a fixed 4×4 shape generated from the project ID, so people recognise a project before reading. The EBITDA result fills it on a log scale (10 k€ none, 10 M€ all), blue when positive, red when negative. Every dot is off, half or full.

Status has three forms, always with words: an amber outlined tag for open questions, a quiet check for "Geprüft", and a blue dot while an import runs.

## Motion

Motion explains a change of layer and never decorates. There are two curves: `cubic-bezier(0.16, 1, 0.3, 1)` for things arriving, and `cubic-bezier(0.32, 0.72, 0, 1)` for sheets.

| Moment | What moves | Duration | Delay |
| --- | --- | --- | --- |
| Sign-in | App zooms 0.83 → 1 and sharpens from 16 px blur | 1200 ms | – |
| Sign-in | Veil fades out | 900 ms | – |
| Sign-in | Card fades, grows to 1.08, blurs 6 px, then leaves | 520–700 ms | removed after 700 ms |
| Assistant opens | Sheet rolls down to full height | 640 ms | – |
| Assistant opens | Content fades in, slides 12 px | 360 ms | 240 ms |
| Assistant opens | Page content makes room | 560 ms | 5000 ms, on purpose: the sheet covers the content for a while |
| Assistant closes | Content fades out, sheet rolls up, page returns | 160 / 640 / 560 ms | page after 160 ms |

With reduced motion turned on, every transition is off.

## Writing, icons and accessibility

**Writing.** The interface is German, formal *Sie*, short and factual: "Eine Position öffnen, um Verlauf, Quellen und Themen zu sehen." Meta lines join facts with " · " ("Entwurf · Version 04 · 2 Rückfragen"). The assistant answers in full sentences, sets the topics in bold and ends with its sources in small mono.

**Icons.** Inline SVG, stroke only, 1.6 px stroke (1.8–2 px at 14–16 px), `currentColor`, 18–20 px inside controls. Simple geometric shapes, no icon font, no emoji. The set: documents, positions, topics, bell, chat, search, close, send, arrow, plus, chevron, sign-out, status, check, link. Every icon-only button has an `aria-label`.

**Accessibility.**

- Text pairs meet 4.5:1 on their grounds; each token's note in `tokens.json` gives the ratio.
- Focus is a solid 2 px `link` outline with a 2 px offset on every interactive element.
- Touch targets are never below 40 px.
- Known gaps, kept as designed: blue dots on light paper (2.6:1), hairline borders (about 1.5:1), the project mark's half dots and the meta text on the blue tile (3.7:1 in light). Each is covered by an `aria-label` or by the same fact appearing elsewhere.

## Open points

- [ ] **Projects overview in light.** It exists only in dark on the canvas so far. The components use tokens, so light works, but no one has reviewed it as a screen.
- [ ] **Hover on glass.** It is defined (`glass-hover`), but the login prototype keeps it off, as on the canvas. Decide whether screens show it.
- [ ] **Fonts** load from Google Fonts. Self-host Russo One, Inter and JetBrains Mono for production or offline use.
