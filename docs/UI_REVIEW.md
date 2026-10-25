# UI review — Eurostat Assistant web app

A pass over the reference web app frontend (`frontend/static/`), covering the shell, the hero,
the composer, the About and Development dialogs, and both themes at desktop and mobile
widths. The design system itself is strong: consistent tokens, a coherent editorial
serif + mono pairing, real focus-visible styles, a `prefers-reduced-motion` block, and
accessible names on the icon-only controls. The notes below are refinements, not a
rebuild.

## Changes applied in this pass

Three fixes are already committed to `frontend/static/`:

### 1. The intended fonts were never loaded

`--font-text` (IBM Plex Serif) and `--font-mono` (IBM Plex Mono) drive every heading and
body run in `styles.css:33-34`, but nothing imported them. On any machine without IBM
Plex installed — i.e. almost every visitor — the app silently fell back to Georgia and
Menlo, so the design never rendered as drawn.

Fix: a `preconnect` + Google Fonts `<link>` in `index.html` loads Plex Mono (400/500/600/700)
and Plex Serif (400/600/700) with `display=swap`. The CSS stacks are unchanged, so the
old fallbacks still apply if the request fails. See the follow-up recommendation on
self-hosting.

### 2. The topbar overflowed and clipped a control on mobile

At 375 px the topbar row (`New investigation` title + four utility buttons) was wider than
the shell, so the rightmost button — Download log — was pushed off the right edge and half
clipped. The title's flex column was not allowed to shrink, so the button cluster absorbed
the overflow.

Fix (in the `max-width: 760px` block of `styles.css`): the title identity is now
`flex: 1 1 auto; min-width: 0`, the button cluster is `flex: 0 0 auto`, the row gap tightens
to `--space-3`, and the title `max-width` is `100%` so it ellipsizes instead of forcing
overflow. Verified: the row now fits and every control stays on-screen.

### 3. No mobile browser-chrome color

Added `<meta name="theme-color">` (light and dark variants) so the mobile browser address
bar matches the app background instead of a default white/grey.

> Note: `styles.css` is cache-busted with `?v=`; the query was bumped to `20260821-1`.
> Bump it again on future CSS edits.

## Recommended next (roughly prioritized)

### High value

- **Self-host the fonts (and pin the chart libraries locally).** The app's own Development
  panel sells a privacy and boundedness story ("history stays in this browser"), yet the
  page now depends on Google Fonts and on three Vega scripts from jsDelivr
  (`index.html:517-519`). That means: it breaks in an air-gapped or offline deploy, it leaks
  visitor IPs to two third parties, and the CDN scripts carry no Subresource Integrity hash.
  For a reference app shipped with a `Dockerfile`, vendoring `woff2` files under
  `frontend/static/fonts/` with `@font-face`, and vendoring or SRI-pinning the Vega bundle, closes all
  three gaps. This supersedes the Google Fonts link added above.
- **Reduce swap layout shift.** With `display=swap` the serif headline reflows when Plex
  Serif arrives. Add `size-adjust` / `ascent-override` metrics to a fallback `@font-face`
  (or an `@font-face` over Georgia) so the fallback occupies the same box as Plex.

### Medium value

- **Add a skip link.** There is no "skip to composer/content" link (`grep` for `skip` in
  `index.html` returns nothing). A visually-hidden-until-focus link as the first body child
  lets keyboard users bypass the sidebar and topbar to reach the query field.
- **Audit faint-text contrast.** `--color-text-faint` (`#a8a8a0` on the `#f5f5f0` light
  background) is roughly 2.3:1 — below WCAG AA (4.5:1) for text. It is used for meta/labels
  in seven places; confirm none of them carry information a low-vision user needs, or darken
  the token.
- **Confirm one `<h1>` per view.** The lock screen, hero, and Development page each declare
  an `<h1>`. They are mutually exclusive at runtime, so this is likely fine, but worth a
  quick check with an accessibility tree that only one is exposed at a time.

### Low value / polish

- **Keyboard-shortcut affordance.** The composer supports submit-on-enter; a small muted
  hint ("↵ to ask · ⇧↵ for newline") near the send button would surface it.
- **`theme-color` on toggle.** The two `<meta name="theme-color">` tags follow the OS
  preference via `media`. If a user overrides the theme with the in-app toggle, the address
  bar won't follow. `theme.js` could update the tag on toggle for full fidelity.

## How this was verified

Server run locally (`uv run uvicorn app.main:app`) with placeholder credentials; the shell,
both dialogs, both themes, and the mobile/desktop breakpoints were inspected in a browser.
Font load and topbar fit were confirmed programmatically (`document.fonts.check(...)` true
for both families; topbar `scrollWidth === clientWidth` at 375 px with the download control
inside the viewport).
