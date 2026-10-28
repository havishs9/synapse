# Synapse UI design plan

Follows spec 01 section 2.11. Familiar chat layout, calmer than typical LLM apps, one memorable element.

## The memorable element

Every specialist gets **its own color and a two-letter monogram** (e.g. "PC" for Procurement Categorizer), assigned at build time from 8 accessible hues. It appears in exactly three places: the sidebar dot, the specialist panel header, and its result markers (label chips, compare-mode column rule). The main model stays neutral grey. When a build finishes, the winning Pareto dot pulses once and the pane turns into the specialist panel with the monogram: the only deliberate motion.

## Color tokens (CSS variables, `frontend/src/styles/tokens.css`)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F6F7F9` | `#1C1D21` | app background |
| `--surface` | `#FFFFFF` | `#232429` | chat column, panes |
| `--surface-2` | `#EEF0F3` | `#2A2B31` | sidebar, inputs, user bubbles |
| `--border` | `#DADDE3` | `#383A41` | thin borders (no shadows on cards) |
| `--ink` | `#16181D` | `#E8E9EC` | primary text |
| `--ink-2` | `#4A4F5A` | `#A9ADB6` | secondary text (AA on both surfaces) |
| `--ink-3` | `#6B7180` | `#8A8F99` | tertiary, captions (AA large / UI) |
| `--accent` | `#16181D` | `#E8E9EC` | primary buttons are ink-on-surface, not colored |
| `--danger` | `#B42318` | `#F97066` | errors |
| `--ok` | `#067647` | `#47CD89` | passed gate |
| `--focus` | `#2F6FDE` | `#7AA5F0` | focus ring |

Specialist palette (identity only): `#2F6FDE`, `#0E8F6E`, `#C2410C`, `#7C3AED`, `#B4235A`, `#0F766E`, `#A16207`, `#4338CA`. Each passes 4.5:1 for white monogram text; in dark mode the same hue is used for the dot and a 12% tint for chips.

Ladder-rung palette (Pareto dots only, kept separate from specialist colors): rung 1 rules/classic `#64748B` slate, rung 2 embeddings `#0891B2` cyan, rung 3 prompted LLMs `#D97706` amber, cascade H `#DB2777` pink, Nemotron baseline: black/white star.

## Type

- Interface: **IBM Plex Sans** (400, 500, 600). **IBM Plex Mono** only for log lines, record text, code and API snippets.
- One scale: 12 / 13 / 14 (body) / 16 / 20 / 24. Line height 1.5 body, 1.3 headings. Sentence case everywhere; no all-caps labels, no eyebrow labels.

## Layout

- **Sidebar** (240px, collapsible; drawer under 768px): "New chat", recent chats, "Specialists" list with color dots. Footer: theme toggle. Nothing else.
- **Main chat**: centered column, max 720px. Composer pinned to the bottom with an attach button, `Cmd/Ctrl+Enter` to send, stop button while streaming. Empty state: one sentence + three example chips.
- **Right pane**: opens when a build starts (training view), becomes the specialist panel when it finishes. Draggable divider; close collapses it to the sidebar entry. Under 1024px, chat and pane become two tabs.
- **Specialist panel header**: monogram, name, version, and exactly three actions: **Compare**, **Report**, **Use**. Report opens a drawer over the pane; Use opens a centered dialog. One overlay at a time; `Esc` closes.

## Components

Thin 1px borders, 8px radius, no drop shadows on cards or tables. Buttons: primary = ink background with surface text; secondary = bordered. No gradients, no arrows in button text. Tables use row borders only.

## Training view

Narration feed (agent label, elapsed time, running spend; click to expand the JSON file), live Pareto scatter (x: cost per 1M predictions, log scale; y: target metric; dots by rung; eliminated dots fade; frontier line; Nemotron star; target line), then agent lanes, tournament bracket and budget meter as secondary panels.

## Motion and accessibility

Functional transitions only (120–180ms). The single pulse on build completion. `prefers-reduced-motion` disables both. Visible focus rings on every control; WCAG AA contrast; keyboard: `Cmd/Ctrl+K` switcher, `Cmd/Ctrl+Enter` send, `Esc` closes overlays.
