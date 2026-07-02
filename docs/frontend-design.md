# BSP Agent Console — Frontend Design System

Source of truth for the review/approval frontend. Style direction: **Light Pro**
(Vercel / Linear light aesthetic) with dashboard typography, for an internal
developer/ops tool. **Not** a consumer/e-commerce or playful style.

## Product

Internal control console for the Jetson BSP repair agent. Two jobs:
1. **Pending list** — see every run waiting at `human_review`.
2. **Run detail** — read the issue, the code review, and the proposed diff, then
   **approve** (commits + pushes) or **reject** (sends feedback, retries).

Audience: engineers. Optimize for information density, fast scanning, and reading
unified diffs — not marketing polish.

## Style

Clean light mode, professional, minimal — Vercel / Linear aesthetic. White surfaces,
crisp 1px borders, generous whitespace, rounded corners (8px), one indigo accent plus
a green approve action. Avoid: dark backgrounds, neon, decorative gradients, large
hero type, emoji icons, hover effects that shift layout, and low-contrast/invisible
light-mode borders or gray text lighter than slate-600.

## Color tokens

```text
--bg            #F8FAFC   slate-50    app background
--surface       #FFFFFF   white       panels / cards
--border        #E2E8F0   slate-200   1px borders, dividers (must stay visible)
--surface-hover #F1F5F9   slate-100   row / card hover
--text          #0F172A   slate-900   primary text
--text-muted    #475569   slate-600   secondary text, labels (do NOT go lighter)
--accent        #4F46E5   indigo-600  links, focus ring, run_id, primary buttons
--approve       #16A34A   green-600   approve action / published
--danger        #DC2626   red-600     reject action / publish_failed
--warn          #D97706   amber-600   needs_human / review warning
--diff-add-bg   rgba(22,163,74,0.10)  diff "+" lines
--diff-del-bg   rgba(220,38,38,0.10)  diff "-" lines
```

Status badge mapping (code_review decision): `pass`→green, `needs_human`→amber,
`reject`→red. On the light background use tinted pill badges (e.g. green-50 fill +
green-700 text + green-200 border). Badges always carry a **text label**, never
color alone.

## Typography

```text
UI text:  'Fira Sans', system-ui, sans-serif
Code/diff/run_id/changed-files: 'Fira Code', ui-monospace, monospace
```
Body ≥ 16px, line-height 1.5 for prose. Diffs use Fira Code, preserve whitespace.

## Layout

- App shell: slim top bar (`BSP Agent Console`, run count), main content max-w-6xl,
  consistent 16/24px spacing, z-index scale 10/20/30/50.
- **Pending list**: one row/card per run → `run_id` (mono, accent), GitLab issue #,
  code_review badge, changed-files count, attempt no. Whole row clickable
  (cursor-pointer, hover = surface-hover). Empty state: "No runs waiting for approval."
- **Run detail**: header (run_id + stage badge) · Issue panel · Code Review panel
  (decision badge + findings + required_changes) · Diff viewer (mono, +/- line
  tints) · sticky action bar: **Approve** (green) and **Reject** (red → reveals
  feedback textarea, submit disabled until non-empty).

## UX rules (must-have)

- **Approve is slow** (it commits + pushes synchronously). The button MUST show a
  loading state and be disabled during the request; show the result (published
  branch) or the error (409 message) afterward. Same for Reject.
- Errors render near the action that caused them, with the server's message.
- Loading: skeleton/spinner while fetching; reserve space (no content jump).
- Accessibility: visible focus rings (accent), `aria-label` on icon-only buttons,
  4.5:1+ contrast, color never the only signal, respect `prefers-reduced-motion`.
- Transitions: 150–300ms color/opacity only; never width/height; no layout-shift hover.
- Icons: SVG only (Lucide/Heroicons), consistent 24×24, no emoji.

## Stack

React + Vite + TypeScript. Container/presentational split (containers fetch, views
render). A small API client for the ADR-0007 endpoints. Single dark theme (no theme
toggle needed in phase 1). Served as a static build by nginx in docker-compose.

## API (ADR-0007)

```text
GET  /api/runs                     -> pending list
GET  /api/runs/{run_id}            -> {issue, code_review, diff, changed_files, ...}
POST /api/runs/{run_id}/approve    -> {stage, published_branch, changed_files}
POST /api/runs/{run_id}/reject     -> body {feedback}
```
Base URL from `VITE_API_BASE` (default `http://localhost:8080`).
