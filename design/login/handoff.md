<!-- MANUALLY WRITTEN -->
<!-- THIS HAS PRIORITY OVER THE GENERATED HANDOFF -->
This folder contains the design for the login.

It has been agreed upon.

There is an animation, that keeps the background blurred, and zoomed out (0.95).
When the signin was successful the animation will fade out the blur and zoom, like the iPhone Duo opening animation.

That is wanted, and specified.

The actual page in the background is just a placeholder and needs to be specified in the actual use of the Login.

<!-- GENERATED HANDOFF -->
# Aicepeak Login · Übergabe

Nov 13, 2026 · @Felix

## Overview

This is a clickable prototype of the Aicepeak sign-in, built from the frame "Login · interaktiv" on the Aicepeak App design canvas. It is plain HTML, CSS and JavaScript with no build step and no dependencies.

What it does:

- **Sign-in**: a glass card sits over the app, which is zoomed out and blurred behind it. "Mit Microsoft anmelden" shows "Anmeldung läuft …" for 650 ms, then the card fades and grows away while the app zooms in and sharpens.
- **Assistant**: after sign-in, the assistant bar at the top right rolls down into a full-height glass sheet. The main content only makes room for it after 5 s, so the sheet deliberately overlaps the content for a while.
- **Sign-out**: the exit icon in the menu bar returns to the sign-in state.
- **Light and dark**: both themes are built in. The page follows the system setting unless the URL forces one.

## File structure

The folder `design/login/` has three source files; the logo is shared with the design system one level up. Markup, styling and behaviour are kept strictly apart.

| File | What lives there | Edit it to … |
| --- | --- | --- |
| `index.html` | All markup: menu bar, assistant sheet, projects table, veil and sign-in card. Example data is written directly into the table rows. | change copy, add or remove rows, change icons |
| `styles.css` | Theme tokens for light and dark, all component styles, and every animation as a CSS transition keyed off the state attributes. | change colours, spacing, glass, timings |
| `app.js` | The state machine (sign-in, sign-out, assistant), the theme choice and the settings in `CONFIG`. About 110 lines, no libraries. | change behaviour, delays, labels |
| `../aicepeak-mark.png` | The Aicepeak mark, 767 × 822 px (shown at 26 and 32 px wide; `styles.css` sets the width, height follows). | swap the logo (keep it sized in CSS) |

The CSS file is ordered top to bottom: tokens, base, app layer, glass and menu bar, assistant, main content and table, veil and sign-in card, reduced motion.

## How it works

The whole UI state is three data attributes on `#app`. JavaScript only flips them, and CSS does all the animating. To change a look or a motion, you edit CSS. To change when something happens, you edit `app.js`.

| Attribute | Values | Set by |
| --- | --- | --- |
| `data-theme` | `light`, `dark` | `?theme=` in the URL, otherwise the system setting |
| `data-phase` | `out` → `auth` → `in` | sign-in button (`out` → `auth`), timer after 650 ms (`auth` → `in`), sign-out icon (back to `out`) |
| `data-assistant` | `closed`, `open` | assistant bar; only works while signed in, and sign-out closes it |

**Theming.** Each theme sets the same custom properties (`--paper`, `--ink`, `--glass`, `--card-bg`, `--btn-bg` …) under `.app[data-theme="light"]` and `.app[data-theme="dark"]`. Components only use the variables, so a new colour goes into both theme blocks.

**Timings**, all in `styles.css` unless noted:

| What | Duration | Delay | Easing |
| --- | --- | --- | --- |
| Auth wait ("Anmeldung läuft …") | 650 ms | – | `app.js`: `CONFIG.authDelayMs` |
| App zooms in and sharpens | 1200 ms | – | `--ease-out` |
| Veil fades | 900 ms | – | ease |
| Sign-in card fades, grows to 1.08, blurs 6 px | 520–700 ms | hidden after 700 ms | `--ease-out` |
| Assistant sheet rolls down or up | 640 ms | – | `--ease-sheet` |
| Assistant content fades in | 360 ms | 240 ms | ease |
| Assistant content fades out | 160 ms | – | ease |
| Main content makes room for the sheet | 560 ms | 5000 ms (`--main-delay`) | `--ease-sheet` |
| Main content returns on close | 560 ms | 160 ms | `--ease-sheet` |

**Accessibility.** While signed out, the blurred app is `inert`, so keyboard focus stays on the card. The closed assistant content is `inert` too. With reduced motion turned on in the system, all transitions are switched off.

## Running and editing

Open `index.html` directly in a browser. No server and no build are needed. For live reload while editing, any static server works; serve `design/` (not `design/login/`) so the shared logo at `../aicepeak-mark.png` resolves, e.g. `npx serve design` and open `/login/`.

- **Force a theme**: add `?theme=light` or `?theme=dark` to the address.
- **Drive it from the console**: `AicepeakLogin.setTheme('light')`, `AicepeakLogin.signIn()`, `AicepeakLogin.toggleAssistant()`, `AicepeakLogin.signOut()`.

Common edits:

| Change | Where |
| --- | --- |
| Zoom and blur of the app behind the card | `app.js` → `CONFIG.zoom` (0.83), `CONFIG.blurPx` (16) |
| Auth wait and button labels | `app.js` → `CONFIG.authDelayMs`, `CONFIG.labels` |
| How long the open sheet overlaps the content | `styles.css` → `--main-delay` (5000ms) |
| Accent colour | `styles.css` → `--accent` in each theme block |
| Glass tint and blur | `styles.css` → `--glass`, `--glass-blur` in each theme block |
| Projects in the table | `index.html` → copy a `.table__row`; status classes are `status--review`, `status--done`, `status--running` |
| Assistant messages and suggestions | `index.html` → `.assistant__messages`, `.chips` |

## Design rules to keep

The prototype follows the Aicepeak "Paper & Glass" language. Changes should stay inside it.

- **Paper for data, glass for tools.** Content (title, table) sits on square, flat paper with 1 px lines. Only the menu bar, the assistant and the sign-in card are frosted glass with rounded corners.
- **Glass needs something behind it.** The blue glow at the top right is what makes the glass read as glass. Remove it and the bars look flat.
- **No filter or transform above glass.** `backdrop-filter` stops working when an ancestor has a `filter` or `transform`. That is why the signed-in app layer sets both to `none`. Keep it that way when adding effects.
- **Signal blue means AI or signals**: the assistant dot, the running status, the full stops in titles and the action arrows. Amber marks open questions (Rückfragen).
- **Type**: Russo One for titles, Inter for body text, JetBrains Mono for labels and metadata. No all-caps text.
- **Sign-in button**: grey, not white or black. It uses the selection grey of each theme (`#3A3936` dark, `#C9C7C1` light); white is reserved for high emphasis.

## Open points and limits

- **No real authentication.** "Mit Microsoft anmelden" only plays the animation. Hooking up Microsoft Entra ID would replace the timer in `signIn()` with the real redirect or popup.
- **Example data.** Projects, statuses and assistant messages are placeholders written into the HTML. The table still uses the earlier columns (Dokumente, Positionen, Stand), not the newer projects overview with the dot marks.
- **Prototype links and buttons go nowhere**: navigation, row links, chips, search, "Neues Projekt" and the message composer.
- **Fonts load from Google Fonts**, so offline the page falls back to system fonts.
- **No hover on glass buttons**, the same as in the design canvas. A ready rule to turn it on is commented in `styles.css`.
- **Desktop only.** The layout is built for 1440 × 900 and needs at least 760 px of height. The table scrolls sideways below 820 px.
