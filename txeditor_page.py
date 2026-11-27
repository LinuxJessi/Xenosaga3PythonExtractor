"""txeditor_page.py — the translation editor page served at /editor.

One raw string, ``EDITOR_HTML``, with inline CSS and JS and no external
assets, in the same visual language as gui.py's INDEX_HTML (same :root
tokens, button classes and picker modal), laid out as a work tool:

* a numbered step strip (1 disc, 2 language setup + project, 3 translate,
  4 build) that always shows what to do next; step 2 opens the Language
  setup (translating from English or Japanese, into any language: the
  list, or "my language isn't listed" from a sample sentence; the font
  for letters the game lacks; a live "Try it" drawn in the game font);
* three columns: where in the game (category tree), the original lines
  of the selected group (a windowed list), and the translation editor
  for the highlighted line (original card, textarea, live check,
  automatic game-font preview);
* a build drawer at the bottom.

txserver.page_html() replaces ``__TX_TOKEN__`` (the per-launch CSRF token
sent back on every POST as X-TX-Token) and ``__TX_FAKE__`` before serving.

Rules kept by the script below:
* game text only ever reaches the DOM through textContent (helper ``h``),
  never innerHTML, because strings carry control bytes, ``<``, quotes, ...;
* the list draws only the rows in view (the two discs are ~104k rows, of
  which ~81k are hidden by default and fetched only when needed);
* no alert/confirm/prompt: every question is an in-page modal.

Keep this a raw string and never put three double quotes inside it.
"""

EDITOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XENOSAGA III · Translation editor</title>
<link rel="icon" href="data:,">
<style>
:root {
  --bg-deep:        #04070d;
  --bg-mid:         #0a1525;
  --bg-panel:       #0c1828;
  --bg-card:        #0e1c30;
  --bg-input:       #060d18;
  --border:         rgba(93, 213, 255, 0.16);
  --border-strong:  rgba(93, 213, 255, 0.38);
  --fg:             #d8e8f5;
  --muted:          #8aa4c4;   /* gui.py uses #6e8aab; lifted here so small text keeps >= 4.5:1 on cards */
  --accent:         #5dd5ff;
  --accent-warm:    #ff9d3a;
  --accent-glow:    rgba(93, 213, 255, 0.35);
  --ok:             #62ffa1;
  --warn:           #ffc15d;
  --err:            #ff6e7f;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
  --sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --serif: "Cormorant Garamond", "Cormorant", "Georgia", serif;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background:
    radial-gradient(ellipse 70% 50% at 50% 0%, rgba(93, 213, 255, 0.06) 0%, transparent 70%),
    linear-gradient(180deg, var(--bg-deep) 0%, #02040a 100%);
  background-color: var(--bg-deep);
  color: var(--fg);
  font-family: var(--sans);
  font-size: 13px; line-height: 1.45;
  overflow: hidden;
  display: flex; flex-direction: column;
}
body::before {
  content: '';
  position: fixed; inset: 0; pointer-events: none; z-index: 1000;
  background: repeating-linear-gradient(180deg,
    transparent 0, transparent 2px,
    rgba(255, 255, 255, 0.012) 2px, rgba(255, 255, 255, 0.012) 3px);
  mix-blend-mode: lighten;
}

/* ------------------------------------------------------------ header + steps */
header {
  padding: 8px 16px 10px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(10, 21, 37, 0.92) 0%, rgba(10, 21, 37, 0.55) 100%);
  position: relative; flex: none;
  display: flex; flex-direction: column; gap: 8px;
}
header::after {
  content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent) 50%, transparent);
  opacity: 0.5;
}
.hrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
header h1 {
  margin: 0; font-family: var(--serif);
  font-size: 19px; font-weight: 400; letter-spacing: 0.12em; text-transform: uppercase;
  white-space: nowrap;
}
header h1 .i { color: var(--accent-warm); font-style: italic; font-weight: 500; margin: 0 0.15em;
  text-shadow: 0 0 14px rgba(255, 157, 58, 0.5); }
header h1 .sep { color: var(--accent); opacity: 0.7; margin: 0 0.4em; font-weight: 300; }
header h1 .sub { font-family: var(--sans); font-size: 11.5px; letter-spacing: 0.3em; color: var(--muted);
  font-style: normal; font-weight: 500; }
a.back { color: var(--accent); text-decoration: none; font-size: 12px; letter-spacing: 0.06em;
  border: 1px solid var(--border); padding: 3px 10px; border-radius: 3px; white-space: nowrap; }
a.back:hover { background: rgba(93, 213, 255, 0.08); border-color: var(--accent); }
.spacer { flex: 1; }
.from { color: var(--muted); font-size: 12px; white-space: nowrap; }
.from b { color: var(--fg); font-weight: 600; }
.field { display: flex; align-items: center; gap: 6px; min-width: 0; }
.field > label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  white-space: nowrap; }
.field.grow { flex: 1 1 340px; }
input[type=text], input[type=search], select, textarea {
  background: var(--bg-input); color: var(--fg);
  border: 1px solid var(--border); border-radius: 3px; padding: 6px 8px;
  font: inherit; font-size: 12.5px; transition: border-color 0.15s, box-shadow 0.15s;
  min-width: 0;
}
input.path { font-family: var(--mono); font-size: 12px; flex: 1; }
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent-glow), 0 0 10px rgba(93, 213, 255, 0.18);
}
select option { background: var(--bg-mid); }
input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; margin: 0; flex: none; }
.saved { font-size: 11px; color: var(--muted); white-space: nowrap; }
.saved.dirty { color: var(--warn); }
.saved.bad { color: var(--err); }
.saved.good { color: var(--ok); }
#saved { cursor: pointer; }
.hbtn { margin-left: 8px; padding: 4px 10px; font-size: 11px; }
/* ---- backups ---- */
.bk-intro { color: var(--muted); font-size: 12.5px; margin: 0 0 12px; line-height: 1.45; }
.bk-cp { display: flex; gap: 8px; margin-bottom: 14px; }
.bk-cp input { flex: 1; }
.bk-list { max-height: 44vh; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
.bk-row { display: grid; grid-template-columns: 9.5em 7.5em minmax(0, 1fr) 6em auto; gap: 10px; align-items: center;
  padding: 7px 10px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
.bk-row:last-child { border-bottom: 0; }
.bk-row .k { font-size: 10.5px; padding: 1px 7px; border-radius: 9px; text-align: center; border: 1px solid var(--border); color: var(--muted); }
.bk-row .k.checkpoint { color: var(--accent-warm, #e9b56b); border-color: rgba(233, 181, 107, 0.45); }
.bk-row .k.before-restore { color: var(--accent); border-color: rgba(93, 213, 255, 0.4); }
.bk-row .lb { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bk-row .n { color: var(--muted); font-family: var(--mono); font-size: 11px; text-align: right; }
.bk-empty { padding: 16px; color: var(--muted); font-size: 12.5px; }
.bk-foot { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
.bk-foot .grow { flex: 1; }
#saved:hover { text-decoration: underline; }

#steps { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr) minmax(0, 0.85fr) minmax(0, 0.85fr); gap: 8px; }
.step { display: flex; align-items: center; gap: 10px; padding: 7px 10px; min-width: 0;
  border: 1px solid var(--border); border-radius: 5px; background: rgba(12, 24, 40, 0.55);
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s; }
.step .num { flex: none; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
  border: 1px solid var(--border-strong); color: var(--muted); font-weight: 700; font-size: 12px; }
.step.done .num { background: rgba(98, 255, 161, 0.14); border-color: var(--ok); color: var(--ok); }
.step.cur { border-color: var(--accent); background: rgba(93, 213, 255, 0.08);
  box-shadow: 0 0 0 1px var(--accent-glow), 0 0 22px rgba(93, 213, 255, 0.14); }
.step.cur .num { background: var(--accent); border-color: var(--accent); color: #02101e; }
.step .sb { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.step .t { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step.cur .t { color: var(--accent); }
.step .s { font-size: 12.5px; color: var(--fg); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step .s.dim { color: var(--muted); }
.step .act { flex: none; display: flex; align-items: center; gap: 5px; }
.step select { padding: 4px 6px; font-size: 12px; width: 112px; }
.step input[type=text] { padding: 4px 6px; font-size: 12px; width: 48px; }
.pbar { height: 3px; background: rgba(93, 213, 255, 0.12); border-radius: 2px; overflow: hidden; margin-top: 3px; }
.pbar i { display: block; height: 100%; background: var(--ok); width: 0; transition: width 0.3s; }

button {
  background: linear-gradient(180deg, #5dd5ff 0%, #3da8d8 100%);
  color: #02101e; border: 0;
  padding: 6px 13px; border-radius: 3px;
  font: inherit; font-weight: 600; font-size: 11.5px;
  letter-spacing: 0.1em; text-transform: uppercase;
  cursor: pointer; transition: filter 0.15s, transform 0.05s;
  box-shadow: 0 0 12px rgba(93, 213, 255, 0.25); white-space: nowrap;
}
button:hover { filter: brightness(1.15); }
button:active { transform: translateY(1px); }
button.ghost { background: transparent; color: var(--fg); border: 1px solid var(--border);
  font-weight: 500; box-shadow: none; }
button.ghost:hover { background: rgba(93, 213, 255, 0.08); border-color: var(--accent); }
button.pick { padding: 5px 10px; font-size: 11px; background: rgba(93, 213, 255, 0.12); color: var(--accent);
  border: 1px solid var(--border); box-shadow: none; font-weight: 500; }
button.pick:hover { background: rgba(93, 213, 255, 0.2); border-color: var(--accent); }
button.mini { padding: 2px 7px; font-size: 10.5px; letter-spacing: 0.06em; background: transparent;
  color: var(--muted); border: 1px solid var(--border); box-shadow: none; font-weight: 500; }
button.mini:hover { color: var(--accent); border-color: var(--accent); }
button.sm { padding: 4px 10px; font-size: 11px; }
button:disabled { opacity: 0.4; cursor: not-allowed; filter: none; }
code, kbd { background: rgba(93, 213, 255, 0.08); color: var(--accent); border-radius: 2px; padding: 1px 5px;
  font-family: var(--mono); font-size: 11.5px; }

.note { font-size: 12px; color: var(--warn); background: rgba(255, 193, 93, 0.07);
  border: 1px solid rgba(255, 193, 93, 0.25); border-radius: 3px; padding: 5px 10px; }
.note a { color: var(--accent); }
.note[hidden] { display: none; }

/* ------------------------------------------------------------ main: three columns */
main { flex: 1; min-height: 0; display: grid; grid-template-columns: 260px minmax(0, 38%) minmax(0, 1fr); }
#tree {
  border-right: 1px solid var(--border); overflow-y: auto; padding: 0 0 40px;
  background: linear-gradient(180deg, rgba(12, 24, 40, 0.85) 0%, rgba(8, 16, 28, 0.95) 100%);
}
#tree::-webkit-scrollbar, #list::-webkit-scrollbar, #edcol::-webkit-scrollbar { width: 10px; }
#tree::-webkit-scrollbar-thumb, #list::-webkit-scrollbar-thumb, #edcol::-webkit-scrollbar-thumb { background: rgba(93, 213, 255, 0.18); border-radius: 5px; }
.colhead { flex: none; display: flex; align-items: center; gap: 8px; padding: 0 12px; height: 38px;
  border-bottom: 1px solid var(--border); background: rgba(2, 5, 11, 0.3); }
.colhead h3 { margin: 0; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent);
  font-weight: 600; white-space: nowrap; }
.colhead .sub { color: var(--muted); font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
#tree .thead { position: sticky; top: 0; z-index: 2; background: #0b1726; margin-bottom: 4px; padding-bottom: 2px; }
.tn { display: grid; grid-template-columns: 14px 1fr auto; gap: 6px; align-items: center;
  padding: 4px 12px 4px 10px; cursor: pointer; user-select: none; border-left: 2px solid transparent; }
.tn:hover { background: rgba(93, 213, 255, 0.06); }
.tn.sel { background: rgba(93, 213, 255, 0.14); border-left-color: var(--accent); }
.tn .chev { color: var(--muted); font-size: 10px; transition: transform 0.15s; text-align: center; }
.tn.open .chev { transform: rotate(90deg); }
.tn .lbl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tn.cat .lbl { font-weight: 600; letter-spacing: 0.02em; white-space: normal; line-height: 1.3; }
.tn .lbl .hint { font-family: var(--sans); font-size: 11px; color: var(--muted); margin-left: 6px; }
.tn.sel .lbl .hint { color: #a8c8e4; }
.tn.grp { padding-left: 30px; font-size: 12px; }
.tn.grp .lbl { font-family: var(--mono); font-size: 11.5px; }
.tn .cnt { font-family: var(--mono); font-size: 10px; color: var(--muted); white-space: nowrap; }
.tn .cnt.done { color: var(--ok); }
.tn .bar { grid-column: 2 / 4; height: 2px; background: rgba(93, 213, 255, 0.1); border-radius: 1px; overflow: hidden; }
.tn .bar i { display: block; height: 100%; background: var(--accent); }
.tn.zero:not(.sel) .lbl, .tn.zero:not(.sel) .cnt { opacity: 0.5; }
.tn.more .lbl { color: var(--accent); font-family: var(--sans); font-style: italic; }
.tn.all { border-bottom: 1px solid var(--border); margin-bottom: 4px; padding-bottom: 7px; }
.tree-empty { padding: 20px 16px; color: var(--muted); font-size: 12.5px; }

/* middle: original lines */
#listcol { min-width: 0; min-height: 0; display: flex; flex-direction: column; border-right: 1px solid var(--border);
  background: rgba(6, 12, 22, 0.55); }
#listtools { flex: none; display: flex; gap: 6px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
#listtools input[type=search] { flex: 1; }
#listtools select { flex: none; }
#crumbbar { flex: none; display: flex; align-items: center; gap: 10px; padding: 6px 12px;
  border-bottom: 1px solid var(--border); font-size: 12px; color: var(--muted); }
#crumbbar .where { color: var(--fg); font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#crumbbar #rowcount { margin-left: auto; white-space: nowrap; font-family: var(--mono); font-size: 11px; }
#banner { margin: 8px 12px 0; flex: none; }
#list { flex: 1; min-height: 0; overflow-y: auto; position: relative; outline: none; }
#list:focus-visible { box-shadow: inset 0 0 0 1px var(--accent-glow); }
#lspacer { position: relative; width: 100%; }
.lr { position: absolute; left: 0; right: 0; height: 48px; display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto; gap: 9px; align-items: center;
  padding: 0 12px 0 9px; border-bottom: 1px solid rgba(93, 213, 255, 0.07);
  border-left: 3px solid transparent; cursor: pointer; }
.lr:hover { background: rgba(93, 213, 255, 0.05); }
.lr.sel { background: rgba(93, 213, 255, 0.15); border-left-color: var(--accent); }
.lr .tx { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.lr .l1 { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; }
.lr .l2 { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 11.5px; color: var(--muted); }
.lr .l2.has { color: #a8c8e4; }
.lr.lockd .l1 { color: var(--muted); }
.lr .cx { max-width: 15em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 11px;
  color: var(--accent-warm); text-align: right; }
.dot { width: 10px; height: 10px; border-radius: 50%; border: 1.5px solid #6e8aab; display: inline-block; flex: none; }
.dot.ok { background: var(--ok); border-color: var(--ok); }
.dot.draft { border-color: var(--ok); background: linear-gradient(90deg, var(--ok) 50%, transparent 50%); }
.dot.warn { background: var(--warn); border-color: var(--warn); }
.dot.err { background: var(--err); border-color: var(--err); }
.dot.lock { border-radius: 2px; border-color: rgba(255, 110, 127, 0.75); background: rgba(255, 110, 127, 0.18); }
.legend { flex: none; display: flex; flex-wrap: wrap; gap: 4px 12px; padding: 6px 12px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--muted); background: rgba(2, 5, 11, 0.35); }
.legend span { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.legend .keys { margin-left: auto; }

/* Bulk menu */
.menu-wrap { position: relative; margin-left: auto; }
.menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 50; min-width: 280px;
  background: linear-gradient(180deg, var(--bg-card) 0%, var(--bg-mid) 100%); border: 1px solid var(--border-strong);
  border-radius: 6px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.55), 0 0 30px rgba(93, 213, 255, 0.12); padding: 5px; }
.menu[hidden] { display: none; }
.menu .mi { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; width: 100%; text-align: left;
  background: transparent; color: var(--fg); border: 0; box-shadow: none; padding: 7px 10px; border-radius: 4px;
  text-transform: none; letter-spacing: 0; font-weight: 500; font-size: 12.5px; cursor: pointer; filter: none; }
.menu .mi small { color: var(--muted); font-size: 11px; font-weight: 400; }
.menu .mi:hover:not(:disabled) { background: rgba(93, 213, 255, 0.1); }
.menu .mi:disabled { opacity: 0.45; }
.menu label.mi { flex-direction: row; align-items: flex-start; gap: 9px; }
.menu label.mi > span { display: flex; flex-direction: column; gap: 1px; }
.menu label.mi input { margin-top: 2px; }
.menu .msep { height: 1px; background: var(--border); margin: 4px 6px; }

/* right: translation editor */
#edcol { min-width: 0; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 14px 18px 60px;
  background: linear-gradient(180deg, rgba(12, 24, 40, 0.5) 0%, rgba(4, 8, 15, 0.6) 100%); }
.card { background: linear-gradient(180deg, rgba(14, 28, 48, 0.9) 0%, rgba(10, 21, 37, 0.9) 100%);
  border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; }
.chead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.chead h3, .talabel { margin: 0; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.chead .grow { flex: 1; }
.origtext { font-size: 16px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; color: #eef6fc; }
/* long mails / database entries: the card scrolls on its own so the translation box stays on screen */
.origtext.clip { max-height: min(28vh, 220px); overflow-y: auto; padding-right: 6px;
  mask-image: linear-gradient(180deg, #000 85%, transparent); -webkit-mask-image: linear-gradient(180deg, #000 85%, transparent); }
.origtext.clip.end { mask-image: none; -webkit-mask-image: none; }
.origtext::-webkit-scrollbar { width: 8px; }
.origtext::-webkit-scrollbar-thumb { background: rgba(93, 213, 255, 0.22); border-radius: 4px; }
.origmore { margin-top: 4px; }
.toknote { margin-top: 6px; font-size: 11.5px; color: var(--muted); }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 3px 14px; margin: 10px 0 0; padding-top: 9px;
  border-top: 1px solid var(--border); font-size: 12px; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.facts .ctx { color: var(--accent-warm); font-weight: 600; }
.facts .idv { font-family: var(--mono); font-size: 11px; color: var(--muted); cursor: copy; }
.facts .idv:hover { color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 3px; }
.tag { font-size: 9.5px; padding: 1px 5px; border-radius: 2px; text-transform: uppercase; letter-spacing: 0.08em;
  font-weight: 600; background: rgba(138, 164, 196, 0.14); color: var(--muted); white-space: nowrap; }
.tag.tm { background: rgba(93, 213, 255, 0.16); color: var(--accent); }
.tag.draft { background: rgba(255, 193, 93, 0.14); color: var(--warn); }
.tag.lock { background: rgba(255, 110, 127, 0.14); color: var(--err); }
.tag.hide { background: rgba(138, 164, 196, 0.22); color: var(--fg); }
.tag.font { background: rgba(255, 157, 58, 0.14); color: var(--accent-warm); }
.tok { display: inline-block; font-family: var(--mono); font-size: 11px; line-height: 1.3;
  padding: 0 4px; margin: 0 1px; border-radius: 2px; vertical-align: 2px; user-select: all;
  background: rgba(255, 157, 58, 0.16); color: #ffc48a; border: 1px solid rgba(255, 157, 58, 0.3); }
.tok.tag2 { background: rgba(93, 213, 255, 0.12); color: #9ee6ff; border-color: rgba(93, 213, 255, 0.3); }
.tok.fmt { background: rgba(98, 255, 161, 0.1); color: #a9ffcb; border-color: rgba(98, 255, 161, 0.28); }
.nl { color: var(--muted); opacity: 0.8; font-size: 11px; user-select: none; }

.tlsec { margin-top: 14px; display: flex; flex-direction: column; gap: 7px; }
.talabel { color: var(--accent); font-size: 11.5px; display: flex; align-items: center; gap: 8px; }
textarea.tl { width: 100%; min-height: 110px; max-height: 50vh; resize: vertical; font-family: var(--sans);
  font-size: 16px; line-height: 1.6; padding: 10px 12px; white-space: pre-wrap; display: block;
  border-color: var(--border-strong); background: #050b15; }
textarea.tl.draft { border-color: rgba(255, 193, 93, 0.5); }
textarea.tl::placeholder { color: #6e8aab; }
.edbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.edbar .grow { flex: 1; }
.edbar .hint { color: var(--muted); font-size: 11px; }
.tmline { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: var(--fg); cursor: pointer;
  padding: 7px 10px; border-radius: 4px; background: rgba(93, 213, 255, 0.06); border: 1px solid var(--border); }
.tmline input { margin-top: 2px; }
.tmline .off { color: var(--muted); }
.noproj { font-size: 12px; color: var(--warn); background: rgba(255, 193, 93, 0.07);
  border: 1px solid rgba(255, 193, 93, 0.25); border-radius: 4px; padding: 7px 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.locked { padding: 12px 14px; border: 1px dashed rgba(255, 110, 127, 0.45); border-radius: 6px; margin-top: 14px; }
.locked h4 { margin: 0 0 4px; color: var(--err); font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; }
.locked p { margin: 4px 0 0; color: var(--muted); font-size: 12.5px; }
.locked p.why { color: var(--fg); }
.st { font-size: 11.5px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; min-height: 20px; }
.st .badge { font-size: 9.5px; padding: 1px 6px; border-radius: 2px; text-transform: uppercase;
  letter-spacing: 0.1em; font-weight: 700; }
.st .badge.ok { background: rgba(98, 255, 161, 0.16); color: var(--ok); }
.st .badge.warn { background: rgba(255, 193, 93, 0.16); color: var(--warn); }
.st .badge.err { background: rgba(255, 110, 127, 0.18); color: var(--err); }
.st .badge.wait { background: rgba(138, 164, 196, 0.14); color: var(--muted); }
.st .num { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.st .num.over { color: var(--err); }
.st .num.near { color: var(--warn); }
.st .dim { color: var(--muted); }
.msgs { font-size: 12px; margin: 0; padding-left: 16px; }
.msgs li.e { color: var(--err); }
.msgs li.w { color: var(--warn); }
.pvsec { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.pvsec h4 { margin: 0; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.pvsec h4 small { text-transform: none; letter-spacing: 0; font-weight: 400; }
.pv { background: #000; border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; overflow-x: auto; position: relative; }
.pv .more { font-size: 11px; color: var(--warn); margin-top: 3px; position: sticky; left: 0; }
.pv[hidden] { display: none; }
.pv img { display: block; image-rendering: pixelated; margin: 2px 0; cursor: zoom-in; }
.pv.zoom img { cursor: zoom-out; }
.pv .pvline { position: relative; width: max-content; }
.pv .guide { position: absolute; top: 0; bottom: 0; border-left: 1px dashed var(--err); pointer-events: none; }
.pv .cap { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.pv .cap b { color: var(--fg); font-weight: 600; }
.pv .cap.e { color: var(--muted); font-style: italic; }

/* empty states + how it works */
.empty { padding: 40px 20px; text-align: center; color: var(--muted); }
.guide-card { border: 1px solid var(--accent); border-radius: 6px; padding: 16px 18px; background: rgba(93, 213, 255, 0.06);
  box-shadow: 0 0 24px rgba(93, 213, 255, 0.1); display: flex; flex-direction: column; gap: 8px; }
.guide-card .k { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
.guide-card .big { font-size: 17px; line-height: 1.4; color: #eef6fc; }
.guide-card p { margin: 0; color: var(--muted); font-size: 12.5px; }
.guide-card .btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.list-empty { padding: 28px 18px; }
.howto { margin-top: 16px; }
.howto h3 { margin: 0 0 8px; font-family: var(--serif); font-weight: 500; font-size: 18px; letter-spacing: 0.06em; color: var(--fg); }
.howto ol { margin: 0; padding: 0; list-style: none; counter-reset: s; display: flex; flex-direction: column; gap: 9px; }
.howto li { counter-increment: s; display: grid; grid-template-columns: 26px 1fr; gap: 10px; align-items: start; font-size: 13px; color: var(--fg); }
.howto li::before { content: counter(s); width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
  border: 1px solid var(--border-strong); color: var(--accent); font-size: 11.5px; font-weight: 700; }
.howto li span { color: var(--muted); }
.howto .foot { margin-top: 12px; color: var(--muted); font-size: 12px; }

/* ------------------------------------------------------------ drawer */
#drawer { flex: none; border-top: 1px solid var(--border-strong);
  background: linear-gradient(180deg, rgba(12, 24, 40, 0.97) 0%, rgba(8, 16, 28, 0.99) 100%); }
#drawer .dhead { display: flex; align-items: center; gap: 10px; padding: 7px 18px; flex-wrap: wrap; }
#drawer h2 { margin: 0; font-family: var(--serif); font-size: 14px; font-weight: 500; color: var(--accent);
  text-transform: uppercase; letter-spacing: 0.22em; cursor: pointer; user-select: none; white-space: nowrap; }
#drawer .badge { font-size: 10px; padding: 2px 8px; border-radius: 2px; background: rgba(138, 164, 196, 0.14);
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; }
#drawer .badge.run { background: rgba(93, 213, 255, 0.18); color: var(--accent); }
#drawer .badge.ok { background: rgba(98, 255, 161, 0.18); color: var(--ok); }
#drawer .badge.err { background: rgba(255, 110, 127, 0.18); color: var(--err); }
#buildlog:empty::before { content: 'The build log appears here. Press Build to write patched copies of the discs; the retail images are only read.';
  color: var(--muted); font-family: var(--sans); font-style: italic; }
.blid { color: var(--accent); text-decoration: underline; cursor: pointer; }
.blid:hover { color: #fff; }
#buildok { display: none; margin: 0 18px 8px; padding: 10px 14px; border: 1px solid var(--ok); border-radius: 5px;
  background: rgba(98, 255, 161, 0.07); align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13px; }
#drawer.open #buildok.show { display: flex; }
#buildok b { color: var(--ok); }
#buildok code { font-size: 11.5px; overflow-wrap: anywhere; }
#buildlog { display: none; margin: 0; padding: 10px 18px; height: 220px; overflow-y: auto;
  background: #02050b; color: #b8d3eb; font-family: var(--mono); font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; border-top: 1px solid var(--border); }
#drawer.open #buildlog { display: block; }

/* ------------------------------------------------------------ modals (gui.py picker look) */
.modal[hidden] { display: none; }
.modal { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal-backdrop { position: absolute; inset: 0; background: rgba(2, 5, 11, 0.82); backdrop-filter: blur(4px);
  animation: fadeIn 0.15s ease-out; }
.modal-window { position: relative; z-index: 1;
  background: linear-gradient(180deg, var(--bg-card) 0%, var(--bg-mid) 100%);
  border: 1px solid var(--border-strong);
  box-shadow: 0 0 0 1px var(--border), 0 0 80px rgba(93, 213, 255, 0.18), 0 20px 60px rgba(0,0,0,0.5);
  border-radius: 8px; width: 760px; max-width: 92vw; height: 580px; max-height: 88vh;
  display: flex; flex-direction: column; animation: slideIn 0.18s ease-out; overflow: hidden; }
.modal-window.wide { width: 980px; height: 680px; }
.modal-window.small { height: auto; width: 620px; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideIn { from { opacity: 0; transform: translateY(-8px) scale(0.985); } to { opacity: 1; transform: none; } }
.modal-header { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px;
  background: linear-gradient(180deg, rgba(93, 213, 255, 0.04), transparent); }
.modal-header h2 { margin: 0; font-family: var(--serif); font-size: 18px; font-weight: 500; letter-spacing: 0.06em; }
.modal-header .x { margin-left: auto; background: transparent; border: 0; color: var(--muted); font-size: 22px;
  cursor: pointer; padding: 0 6px; box-shadow: none; text-transform: none; letter-spacing: 0; }
.modal-header .x:hover { color: var(--err); background: transparent; }
.modal-body { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 20px; display: flex; flex-direction: column; gap: 10px; }
.modal-body p { margin: 0; color: var(--muted); font-size: 12.5px; }
.modal-body textarea { width: 100%; flex: 1; min-height: 160px; font-family: var(--mono); font-size: 12px; resize: vertical; }
.modal-footer { padding: 12px 18px; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 10px;
  background: rgba(2, 5, 11, 0.3); }
.modal-footer .msg { flex: 1; min-width: 0; color: var(--muted); font-size: 12px; }
.modal-footer .msg.e { color: var(--err); }
.diff { display: grid; grid-template-columns: 44px minmax(0, 1fr) minmax(0, 1fr); gap: 0; font-size: 12px;
  border: 1px solid var(--border); border-radius: 3px; }
.diff > div { padding: 4px 8px; border-bottom: 1px solid rgba(93, 213, 255, 0.07); white-space: pre-wrap; word-break: break-word; }
.diff .n { font-family: var(--mono); color: var(--muted); }
.diff .h { color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; background: rgba(2,5,11,0.4); }
.diff .new { color: var(--ok); }
.diff .miss { color: var(--err); font-style: italic; }
.problems { font-family: var(--mono); font-size: 11.5px; color: var(--warn); margin: 0; padding-left: 16px; }

.fs-toolbar { padding: 12px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px;
  background: rgba(2, 5, 11, 0.3); }
.fs-crumb { flex: 1; overflow-x: auto; white-space: nowrap; font-family: var(--mono); font-size: 12px; }
.fs-crumb a { color: var(--accent); cursor: pointer; padding: 2px 4px; border-radius: 2px; }
.fs-crumb a:hover { background: rgba(93, 213, 255, 0.12); }
.fs-crumb .sep { color: var(--muted); margin: 0 2px; opacity: 0.6; }
.fs-list { flex: 1; overflow-y: auto; padding: 4px 6px; }
.fs-entry { display: flex; align-items: center; gap: 12px; padding: 7px 12px; cursor: pointer; border-radius: 3px; font-size: 13px; }
.fs-entry:hover { background: rgba(93, 213, 255, 0.08); }
.fs-entry.selected { background: rgba(93, 213, 255, 0.18); outline: 1px solid var(--accent); }
.fs-entry .icon { width: 18px; text-align: center; opacity: 0.85; font-size: 14px; }
.fs-entry .name { flex: 1; }
.fs-entry .size { margin-left: auto; color: var(--muted); font-size: 11px; font-family: var(--mono); }
.fs-empty { padding: 30px; text-align: center; color: var(--muted); font-size: 13px; }
.fs-roots { border-top: 1px solid var(--border); padding: 8px 18px; display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; align-items: center; }
.fs-roots span { color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-right: 4px; }
.fs-roots a, .fs-quick a { color: var(--accent); padding: 3px 8px; border-radius: 2px; border: 1px solid var(--border); cursor: pointer;
  font-family: var(--mono); font-size: 11px; white-space: nowrap; max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
.fs-roots a:hover, .fs-quick a:hover, .fs-quick a.selected { background: rgba(93, 213, 255, 0.12); border-color: var(--accent); }
.fs-quick { padding: 8px 18px; border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  background: rgba(93, 213, 255, 0.03); flex-shrink: 0; max-height: 42%; overflow-y: auto; }
.fs-quick[hidden] { display: none; }
.fs-quick span { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.fs-quick a.retail { color: var(--ok); border-color: rgba(98, 255, 161, 0.45); max-width: 100%; }
.fs-quick a.copy { color: var(--muted); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-quick a small { color: var(--muted); margin-left: 6px; font-size: 10.5px; }
.fs-quick .qrow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; width: 100%; }
.modal-error { padding: 8px 18px; color: var(--err); font-size: 12px; background: rgba(255, 110, 127, 0.06);
  border-bottom: 1px solid rgba(255, 110, 127, 0.2); }
.modal-error[hidden] { display: none; }
.sel-path { flex: 1; min-width: 0; color: var(--muted); font-size: 12px; font-family: var(--mono);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sel-path.has { color: var(--fg); }

.chk { display: flex; align-items: center; gap: 5px; color: var(--muted); font-size: 12px; white-space: nowrap; cursor: pointer; }

#toast { position: fixed; left: 50%; bottom: 70px; transform: translateX(-50%); z-index: 200;
  background: var(--bg-card); border: 1px solid var(--border-strong); color: var(--fg); padding: 8px 16px;
  border-radius: 4px; font-size: 12.5px; box-shadow: 0 0 30px rgba(93, 213, 255, 0.2);
  opacity: 0; pointer-events: none; transition: opacity 0.2s; max-width: 80vw; }
#toast.show { opacity: 1; }
#toast.e { border-color: var(--err); color: var(--err); }
.fs-path { display: flex; gap: 6px; padding: 8px 18px; border-bottom: 1px solid var(--border); }
.fs-path input { flex: 1; font-family: var(--mono); font-size: 12px; }

/* ------------------------------------------------------------ language setup */
.step.click { cursor: pointer; }
.step.click:hover { border-color: var(--border-strong); }
.modal-window.setup { width: 1180px; height: 90vh; max-width: 96vw; max-height: 94vh; }
.modal-window.setup .modal-body { padding: 12px 16px; gap: 12px; }
.su { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: start; }
.su-col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.su-sec { border: 1px solid var(--border); border-radius: 6px; padding: 11px 13px; background: rgba(6, 12, 22, 0.55);
  display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.su-sec h3 { margin: 0; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent);
  font-weight: 700; display: flex; gap: 8px; align-items: center; }
.su-sec h3 .n { width: 19px; height: 19px; border-radius: 50%; display: inline-grid; place-items: center; font-size: 10.5px;
  border: 1px solid var(--accent); letter-spacing: 0; }
.su-sec h3 .r { margin-left: auto; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--muted); font-size: 11.5px; }
.su-sec p, .su-sec .sm { margin: 0; color: var(--muted); font-size: 12px; }
.su-sec .okline { color: var(--ok); font-size: 12px; }
.su-sec .bad { color: var(--err); font-size: 12px; }
.su-sec .warnl { color: var(--warn); font-size: 12px; }
.srcopts { display: flex; gap: 8px; }
.opt { flex: 1; border: 1px solid var(--border); border-radius: 5px; padding: 8px 10px; cursor: pointer; display: flex; gap: 8px;
  align-items: flex-start; min-width: 0; background: rgba(2, 5, 11, 0.3); }
.opt:hover { border-color: var(--border-strong); }
.opt.on { border-color: var(--accent); background: rgba(93, 213, 255, 0.09); box-shadow: 0 0 0 1px var(--accent-glow); }
.opt input { margin-top: 2px; }
.opt b { display: block; font-size: 13px; color: var(--fg); }
.opt small { color: var(--muted); font-size: 11.5px; }
.row { display: flex; gap: 6px; align-items: center; min-width: 0; }
.row > input[type=text], .row > input[type=search] { flex: 1; }
.langlist { height: 252px; overflow-y: auto; border: 1px solid var(--border); border-radius: 4px; background: rgba(2, 5, 11, 0.35); }
.lg { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1px 10px; padding: 6px 10px; cursor: pointer;
  border-bottom: 1px solid rgba(93, 213, 255, 0.07); border-left: 3px solid transparent; align-items: center; }
.lg:hover { background: rgba(93, 213, 255, 0.05); }
.lg.on { background: rgba(93, 213, 255, 0.15); border-left-color: var(--accent); }
.lg .en { font-size: 15px; color: #eef6fc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lg .en small { font-size: 12px; color: var(--muted); margin-left: 6px; }
.lg .meta { grid-column: 1 / 3; font-size: 11px; color: var(--muted); }
.lg.mine { color: var(--accent); }
.lg.mine .en { color: var(--accent); font-size: 13.5px; }
.kb { font-size: 11px; padding: 2px 7px; border-radius: 3px; white-space: nowrap; font-weight: 600; }
.kb.ready { background: rgba(98, 255, 161, 0.13); color: var(--ok); }
.kb.extra { background: rgba(255, 193, 93, 0.14); color: var(--warn); }
.kb.ja { background: rgba(93, 213, 255, 0.14); color: var(--accent); }
.kb.new { background: rgba(255, 157, 58, 0.15); color: var(--accent-warm); }
.custom { border: 1px dashed var(--border-strong); border-radius: 5px; padding: 9px 11px; display: flex; flex-direction: column; gap: 7px; }
.custom textarea { min-height: 54px; font-size: 15px; font-family: var(--sans); resize: vertical; }
.chosen { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 7px 10px; border-radius: 4px;
  background: rgba(93, 213, 255, 0.07); border: 1px solid var(--border); }
.chosen .big { font-size: 17px; color: #eef6fc; }
.fontlist { display: flex; flex-direction: column; gap: 3px; max-height: 210px; overflow-y: auto; }
.fo { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 5px 8px;
  border: 1px solid transparent; border-radius: 4px; cursor: pointer; }
.fo:hover { background: rgba(93, 213, 255, 0.05); }
.fo.on { border-color: var(--accent); background: rgba(93, 213, 255, 0.1); }
.fo .fl { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fo .fp { font-size: 10.5px; color: var(--muted); font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
.fo .cv { font-size: 11px; color: var(--ok); white-space: nowrap; }
.fo .cv.part { color: var(--warn); }
.letters { font-size: 16px; letter-spacing: 0.08em; color: #eef6fc; overflow-wrap: anywhere; }
details.adv summary { cursor: pointer; color: var(--muted); font-size: 12px; }
details.adv .grid { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 10px; align-items: center; margin-top: 8px; font-size: 12px; }
details.adv input[type=number] { width: 80px; background: var(--bg-input); color: var(--fg); border: 1px solid var(--border); border-radius: 3px; padding: 4px 6px; font: inherit; }
.try textarea { min-height: 46px; font-size: 16px; font-family: var(--sans); resize: vertical; width: 100%; }
.trypv { background: #000; border: 1px solid var(--border); border-radius: 4px; padding: 8px; min-height: 60px; overflow-x: auto; }
.trypv img { display: block; image-rendering: pixelated; margin: 3px 0; }
.trypv.rtl img { margin-left: auto; }
.trypv .cap { font-size: 11px; color: var(--muted); margin-bottom: 5px; }
.meters { display: flex; flex-direction: column; gap: 6px; }
.meter { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 8px; align-items: center; font-size: 11.5px; }
.meter .mbar { height: 7px; background: rgba(93, 213, 255, 0.12); border-radius: 4px; overflow: hidden; }
.meter .mbar i { display: block; height: 100%; background: var(--accent); }
.meter .mbar i.hi { background: var(--warn); }
.meter .mbar i.full { background: var(--err); }
.meter .mv { font-family: var(--mono); color: var(--muted); }
/* Japanese as the source */
.lr .l2.en { color: #7f98b6; }
.lr .l1.noja { color: #b9cde0; }
.lr .l2.rtl, .lr .l1.rtl { direction: rtl; text-align: right; }
.refcard { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); }
.refcard .rl { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin-bottom: 3px; }
.refcard .origtext { font-size: 13px; color: #b9cde0; }
.origtext.ja { font-size: 19px; line-height: 1.7; }
.noja { font-size: 11.5px; color: var(--muted); font-style: italic; }
textarea.tl[dir=rtl] { text-align: right; }

@media (max-width: 1400px) { .legend .keys { display: none; } }
@media (max-width: 1180px) {
  main { grid-template-columns: 220px minmax(0, 40%) minmax(0, 1fr); }
  #steps { grid-template-columns: minmax(0, 1fr) minmax(0, 1.75fr) minmax(0, 0.8fr) auto; }
  #step4 .sb { display: none; }
  .legend { gap: 3px 9px; font-size: 10.5px; }
  .lr .cx { max-width: 11em; }
  .step { padding: 6px 8px; gap: 8px; }
}
@media (max-width: 980px) { .su { grid-template-columns: 1fr; } }
@media (max-width: 900px) {
  body { overflow: auto; }
  #steps { grid-template-columns: 1fr 1fr; }
  main { grid-template-columns: 1fr; grid-template-rows: 180px 360px auto; }
  #tree, #listcol { border-right: 0; border-bottom: 1px solid var(--border); }
  #edcol { overflow: visible; }
}


/* ---- language setup ---- */
.lgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 20px; }
@media (max-width: 860px) { .lgrid { grid-template-columns: 1fr; } }
.lcol h4, .lsec h4 { margin: 0 0 8px; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); }
.lsq { width: 100%; margin-bottom: 8px; }
.llist { max-height: 46vh; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
.lrow { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-rows: auto auto; gap: 1px 10px; width: 100%;
  text-align: left; padding: 8px 12px; background: transparent; border: 0; border-bottom: 1px solid var(--border);
  border-radius: 0; text-transform: none; letter-spacing: 0; color: inherit; box-shadow: none; font-weight: 400; }
.lrow:hover { background: rgba(93, 213, 255, 0.06); filter: none; }
.lrow.on { background: rgba(93, 213, 255, 0.16); box-shadow: inset 3px 0 0 var(--accent); }
.lrow .le { font-size: 15px; font-weight: 600; grid-column: 1; }
.lrow .ln2 { font-size: 11.5px; color: var(--muted); grid-column: 1; }
.lrow .lk { grid-column: 2; grid-row: 1 / 3; align-self: center; font-size: 10.5px; padding: 2px 7px; border-radius: 10px; white-space: nowrap;
  max-width: 15em; overflow: hidden; text-overflow: ellipsis; }
.lk.ready, .lk.auto { color: var(--ok); border: 1px solid rgba(80, 220, 140, 0.4); }
.lk.extra, .lk.ja { color: var(--accent); border: 1px solid rgba(93, 213, 255, 0.4); }
.lk.new { color: var(--accent-warm, #e9b56b); border: 1px solid rgba(233, 181, 107, 0.45); }
.lrow.other .le { color: var(--accent); font-weight: 500; }
.lhdr { position: sticky; top: 0; z-index: 1; padding: 6px 12px; font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--accent-warm, #e9b56b); background: #0d1b2c; border-bottom: 1px solid var(--border); }
.lnote { margin-top: 6px; font-size: 12px; color: var(--muted); line-height: 1.45; }
.lcustom[hidden], .lsec[hidden] { display: none !important; }
.lcustom { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.lcustom input, .lcustom textarea { width: 100%; }
.lrowf { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.lchosen { padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 14px; }
.lchosen .big { font-size: 17px; font-weight: 600; }
.lsec { margin-bottom: 16px; }
.frow { display: flex; justify-content: space-between; gap: 10px; width: 100%; padding: 7px 10px; margin-bottom: 4px; text-align: left;
  background: transparent; border: 1px solid var(--border); border-radius: 5px; text-transform: none; letter-spacing: 0; color: inherit; box-shadow: none; font-weight: 400; }
.frow.on { border-color: var(--accent); background: rgba(93, 213, 255, 0.12); }
.frow .fc { font-size: 11px; color: var(--muted); }
.frow .fc.ok { color: var(--ok); }
.ltry { margin-top: 8px; min-height: 40px; padding: 8px; background: #000; border-radius: 5px; display: flex; flex-direction: column; gap: 4px; overflow: auto; }
.ltry img { image-rendering: pixelated; max-width: 100%; align-self: flex-start; }
.lmsg { font-size: 12px; color: var(--muted); }
.lmsg.e { color: var(--err, #ff6b6b); }
.dim { color: var(--muted); font-size: 12px; }
.mono { font-family: var(--mono); font-size: 11.5px; }
/* ---- simple / advanced ---- */
body:not(.adv) .advonly { display: none !important; }
.advsw { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; color: var(--muted); font-size: 12px;
  letter-spacing: 0.06em; user-select: none; margin-right: 14px; }
.advsw input { position: absolute; opacity: 0; pointer-events: none; }
.advsw .trk { width: 30px; height: 16px; border-radius: 8px; background: rgba(93, 213, 255, 0.15); position: relative; transition: background 0.15s; }
.advsw .trk i { position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: var(--muted); transition: left 0.15s, background 0.15s; }
.advsw input:checked + .trk { background: rgba(93, 213, 255, 0.45); }
.advsw input:checked + .trk i { left: 16px; background: var(--accent); }
.advsw input:focus-visible + .trk { outline: 2px solid var(--accent); outline-offset: 2px; }
.advsw:hover { color: var(--text, #e6f1ff); }
/* ---- sidebar views ---- */
.tviews { display: flex; gap: 2px; margin: 0 10px 6px; padding: 2px; border: 1px solid var(--border); border-radius: 6px; }
.tviews button { flex: 1; padding: 5px 4px; font-size: 11.5px; letter-spacing: 0.04em; text-transform: none;
  background: transparent; border: 0; color: var(--muted); border-radius: 4px; box-shadow: none; }
.tviews button.on { background: rgba(93, 213, 255, 0.16); color: var(--accent); }
.tviews button:hover:not(.on) { color: var(--text, #e6f1ff); }
.tsec { padding: 12px 14px 4px; font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--accent-warm, #e9b56b); opacity: 0.9; }
.tn.cat .lbl .sm2 { display: block; font-weight: 400; font-size: 11px; color: var(--muted); letter-spacing: 0; }
.tn.spk .lbl { font-weight: 600; }
.tnote { padding: 4px 14px 8px; font-size: 11.5px; color: var(--muted); line-height: 1.4; }
</style>
</head>
<body>
<header>
  <div class="hrow">
    <h1><span>Xenosaga</span><span class="i"> III</span><span class="sep">·</span><span class="sub">TRANSLATION EDITOR</span></h1>
    <a class="back" href="/">&larr; Extractor cards</a>
    <span class="spacer"></span>
    <label class="advsw" title="Simple shows only what you need to translate. Advanced adds ids, fonts, byte limits, spreadsheets (TSV) and the hidden debug lines."><input type="checkbox" id="advanced"><span class="trk"><i></i></span><span>Advanced</span></label>
    <span class="from" id="fromlbl" title="What you translate from: the text of the discs you opened, or (USA discs) the Japanese of the Japan discs (step 2, Language setup)">Translating from <b>English</b> (this disc set)</span>
    <span class="saved" id="saved" title="Saves by itself 1.5 s after each edit. Click (or Ctrl/Cmd+S) to save now.">no project</span>
    <button class="sm ghost hbtn" id="btn-save" title="Save now (Ctrl/Cmd+S). Your work also saves by itself a moment after each change.">Save</button>
    <button class="sm ghost hbtn" id="btn-backups" title="Checkpoints, automatic backups, restore, and a copy to another place">Backups</button>
  </div>
  <div id="steps">
    <div class="step" id="step1">
      <span class="num">1</span>
      <div class="sb"><span class="t">Disc</span><span class="s dim" id="step1-s">either disc, as .iso</span></div>
      <div class="act"><button class="sm" id="btn-iso-pick" title="Pick an untouched Xenosaga Episode III disc image (.iso), Disc 1 or Disc 2: the other disc is found next to it. USA or Japan. The images are only ever read">Choose disc…</button></div>
    </div>
    <div class="step click" id="step2" title="Language setup: what you translate from, which language you translate into (any language), and the font for letters the game lacks. Click to open it.">
      <span class="num">2</span>
      <div class="sb"><span class="t">Language setup</span><span class="s dim" id="step2-s">into any language</span></div>
      <div class="act">
        <button class="sm" id="btn-setup" title="Open the Language setup">Set up…</button>
        <button class="sm ghost" id="btn-proj-new" title="Start a new translation project: the Language setup opens first, then the project file (a small .json next to the disc)">New</button>
        <button class="sm ghost" id="btn-proj-pick" title="Open a translation project you already have">Open…</button>
      </div>
    </div>
    <div class="step" id="step3">
      <span class="num">3</span>
      <div class="sb"><span class="t">Translate</span><span class="s dim" id="step3-s">type translations</span>
        <span class="pbar"><i id="step3-bar"></i></span></div>
    </div>
    <div class="step" id="step4">
      <span class="num">4</span>
      <div class="sb"><span class="t">Build discs</span><span class="s dim" id="step4-s">after step 2</span></div>
      <div class="act"><button class="sm" id="btn-build-open" title="Open the build drawer: write patched copies of the discs with your translations">Build…</button></div>
    </div>
  </div>
  <input type="hidden" id="iso"><input type="hidden" id="proj">
</header>

<main>
  <nav id="tree"><div class="colhead"><h3>Where in the game</h3></div><div class="tree-empty">Step 1: choose the disc (top left). The places in the game appear here.</div></nav>
  <section id="listcol">
    <div class="colhead">
      <h3>Original</h3><span class="sub" id="origsub">English · click a line to translate it</span>
      <div class="menu-wrap">
        <button class="ghost sm" id="btn-bulk" aria-haspopup="true" aria-expanded="false" title="Bulk tools: whole groups, spreadsheets, hidden lines, translation memory">Bulk ▾</button>
        <div class="menu" id="bulkmenu" hidden role="menu">
          <button class="mi" id="btn-copygrp" role="menuitem"><span>Copy group for translation</span><small>this group's untranslated lines, numbered, to the clipboard</small></button>
          <button class="mi" id="btn-pastegrp" role="menuitem"><span>Paste translations into group…</span><small>the numbered lines back, with a preview first</small></button>
          <div class="msep"></div>
          <button class="mi advonly" id="btn-tsv-in" role="menuitem"><span>Import TSV…</span><small>id · source · translation, from a spreadsheet</small></button>
          <button class="mi advonly" id="btn-tsv-out" role="menuitem"><span>Export TSV</span><small>the whole project as a spreadsheet file</small></button>
          <div class="msep"></div>
          <button class="mi" id="btn-cache" role="menuitem" title="Reading a disc set takes about half a minute, so the result is kept in this folder; nothing of your project is in it"><span>Clear the editor's cache</span><small id="cache-info">where the read disc text is kept</small></button>
          <div class="msep"></div>
          <label class="mi advonly" title="Hidden lines: debug prints, asset ids, file paths, printf formats, lines no script draws, and (USA discs) the Japanese strings left by the developers, which the player never sees."><input type="checkbox" id="showhidden"><span>Show hidden lines<small>debug text, incl. the disc's Japanese developer strings</small></span></label>
          <label class="mi" title="When you translate a line, untranslated lines with the identical original get the same text as a draft"><input type="checkbox" id="tm" checked><span>Translation memory<small>identical original lines share a translation</small></span></label>
        </div>
      </div>
    </div>
    <div id="listtools">
      <input type="search" id="search" placeholder="Search lines…" title="Searches every category: the original, your translation, the id and the speaker/context. Enter opens the first match.">
      <select id="filter" title="Show only">
        <option value="all">All lines</option>
        <option value="untranslated">Untranslated</option>
        <option value="translated">Translated</option>
        <option value="problems">Problems</option>
        <option value="errors">Errors only</option>
        <option value="warnings">Warnings only</option>
      </select>
    </div>
    <div class="note" id="banner" hidden></div>
    <div id="crumbbar"><span class="where" id="where">—</span><span id="rowcount"></span></div>
    <div id="list" tabindex="0" aria-label="Original lines"></div>
    <div class="legend">
      <span><i class="dot"></i>untranslated</span><span><i class="dot ok"></i>translated</span>
      <span><i class="dot draft"></i>draft</span><span><i class="dot warn"></i>warning</span>
      <span><i class="dot err"></i>error</span><span><i class="dot lock"></i>locked</span>
      <span class="keys"><kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> edit</span>
    </div>
  </section>
  <section id="edcol"></section>
</main>

<div id="drawer">
  <div class="dhead">
    <h2 id="drawer-toggle">Build ▸</h2>
    <span class="badge" id="build-badge">idle</span>
    <div class="field grow">
      <label for="out">Output folder</label>
      <input type="text" class="path" id="out" placeholder="a new folder next to the retail image: both patched discs are written into it">
    </div>
    <span id="build-sum" class="saved"></span>
    <label class="chk" title="Replace the patched images in the output folder if they already exist"><input type="checkbox" id="overwrite"> replace if it exists</label>
    <button class="ghost" id="btn-check" title="Run the build's own checks over the whole project (keywords, locks, every family's rules), without writing anything">Check project</button>
    <button id="btn-build">Build</button>
  </div>
  <div id="buildok" role="status"></div>
  <pre id="buildlog"></pre>
</div>

<!-- generic modal -->
<div class="modal" id="dlg" hidden>
  <div class="modal-backdrop" data-dlg-close></div>
  <div class="modal-window" id="dlg-win">
    <div class="modal-header"><h2 id="dlg-title"></h2><button type="button" class="x" data-dlg-close>×</button></div>
    <div class="modal-body" id="dlg-body"></div>
    <div class="modal-footer"><div class="msg" id="dlg-msg"></div><span id="dlg-btns"></span></div>
  </div>
</div>

<!-- file picker modal (same as gui.py, plus a typed-path box) -->
<div class="modal" id="fs-modal" hidden>
  <div class="modal-backdrop" data-fs-close></div>
  <div class="modal-window">
    <div class="modal-header"><h2 id="fs-title">Select…</h2><button type="button" class="x" data-fs-close>×</button></div>
    <div class="fs-toolbar"><button type="button" class="ghost" id="fs-up">↑ Up</button><div class="fs-crumb" id="fs-crumb"></div></div>
    <div class="fs-path"><input type="text" id="fs-path" placeholder="or type / paste a full path and press Enter"><button type="button" class="pick" id="fs-go">Go</button></div>
    <div class="modal-error" id="fs-error" hidden></div>
    <div class="fs-quick" id="fs-quick" hidden></div>
    <div class="fs-list" id="fs-list"></div>
    <div class="fs-roots" id="fs-roots"></div>
    <div class="modal-footer">
      <div class="sel-path" id="fs-sel">No selection</div>
      <button type="button" class="ghost" data-fs-close>Cancel</button>
      <button type="button" id="fs-select" disabled>Select</button>
    </div>
  </div>
</div>
<div id="toast"></div>

<script>
'use strict';
const TX_TOKEN = '__TX_TOKEN__';
const TX_FAKE = __TX_FAKE__;
const SPK_JA = __TX_SPEAKERS__;   // Japanese name box -> USA English (txspeakers.json, paired from the two discs)
const ROWH = 48;
const NL = '⏎';
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ state
const S = {
  iso: '', rid: '', rows: [], byId: new Map(), cats: [], notes: [],
  catIdx: new Map(), nodeRows: new Map(), srcIds: new Map(),
  proj: null, projPath: '', dirty: false, saving: false,
  sel: {cat: null, grp: null}, open: new Set(),
  filter: 'all', search: '', showHidden: false, tm: true,
  checks: new Map(), tmIds: new Set(), lastCopy: null, view: [], viewIdx: new Map(),
  total: 0, hidden: null, grpShow: new Map(), cur: null, pending: null, pvCache: new Map(),
  // step 2, Language setup (see "language" below)
  target: {code: 'fr', kind: 'script-hybrid', script: 'Latn', rtl: false},
  lang: {code: 'fr', name: 'French', endonym: 'Français', kind: 'script-hybrid', lacking: 'œŒŸ', ready: 'auto',
         font_auto: 'DejaVu Sans (comes with the kit)'},
  source: {id: 'en-usa'}, fontLabel: '', ja: null, jaMsg: '',
  adv: false, treeView: 'type', spk: [], spkShow: 60,
};
const GRP_STEP = 150;
let building = false;          // a build job is running: Build stays disabled
// the editor pane's live elements for the highlighted row
const E = {ta: null, st: null, pvO: null, pvT: null, tmBox: null, tags: null, gen: 0, zoom: false};

// ------------------------------------------------------------------ helpers
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) for (const k in props) {
    const v = props[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}
function store(k, v) { try { localStorage.setItem('xs3tx.' + k, JSON.stringify(v)); } catch (_) {} }
function recall(k, d) { try { const v = localStorage.getItem('xs3tx.' + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } }
let toastT = null;
function toast(msg, isErr) {
  const t = $('toast'); t.textContent = msg; t.className = 'show' + (isErr ? ' e' : '');
  t.style.bottom = (($('drawer') ? $('drawer').offsetHeight : 0) + 14) + 'px';   // never over the build log
  clearTimeout(toastT); toastT = setTimeout(() => { t.className = ''; }, isErr ? 5000 : 2200);
}
function fmtSize(b) {
  if (b < 1024) return b + ' B';
  const u = ['KB','MB','GB','TB']; let v = b / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 10 ? 0 : 1) + ' ' + u[i];
}
function fmtN(n) { return n.toLocaleString('en-US'); }
async function api(path, body) {
  const res = await fetch(path, {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-TX-Token': TX_TOKEN},
    body: JSON.stringify(body || {})});
  let j = null; try { j = await res.json(); } catch (_) {}
  if (!res.ok) { const e = new Error((j && j.error) || ('HTTP ' + res.status)); e.status = res.status; e.body = j; throw e; }
  return j;
}
async function getJson(path) {
  const res = await fetch(path);
  let j = null; try { j = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((j && j.error) || ('HTTP ' + res.status));
  return j;
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (_) {
    const ta = h('textarea', {style: 'position:fixed;left:-9999px;top:0'}); ta.value = text;
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove(); return ok;
  }
}
function dirname(p) { const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\')); return i >= 0 ? p.slice(0, i) : ''; }
function basename(p) { const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\')); return p.slice(i + 1); }
function joinp(d, f) { const sep = d.indexOf('\\') >= 0 && d.indexOf('/') < 0 ? '\\' : '/'; return d ? d.replace(/[\\/]$/, '') + sep + f : f; }
function stem(p) { return basename(p).replace(/\.[^.]+$/, ''); }
function flat(s) { return s.replace(/\n/g, ' ' + NL + ' '); }
// list rows: runs of raw control bytes shrink to one short marker
function listText(s) { return flat(s.replace(/(?:⟦[0-9A-Fa-f]{2}⟧)+/g, '⟦…⟧')); }
function plural(n, w) { return fmtN(n) + ' ' + w + (n === 1 ? '' : 's'); }

// protected tokens, same classes as txcodec.protected_tokens
const TOK_RE = /((?:⟦[0-9A-Fa-f]{2}⟧)+|<[^<>\n]{1,40}>|\$[a-z]+[0-9A-Fa-f,+\-]*;|\\(?:\d{1,3}|[A-Za-z])|%[-+0-9.]*[dsxXcb])/g;
function renderSrc(text) {
  const frag = document.createDocumentFragment();
  const parts = text.split(TOK_RE);
  parts.forEach((p, i) => {
    if (!p) return;
    if (i % 2) {
      const cls = p.startsWith('/[') ? 'tok tag2' : p.startsWith('%') || p.startsWith('\\') ? 'tok fmt' : 'tok';
      frag.appendChild(h('span', {class: cls, contenteditable: 'false', title: 'protected: keep it in the translation', text: p}));
    } else {
      const lines = p.split('\n');
      lines.forEach((ln, j) => {
        if (j) { frag.appendChild(h('span', {class: 'nl', text: NL})); frag.appendChild(document.createTextNode('\n')); }
        if (ln) frag.appendChild(document.createTextNode(ln));
      });
    }
  });
  return frag;
}
function hasTokens(text) { TOK_RE.lastIndex = 0; const m = TOK_RE.test(text); TOK_RE.lastIndex = 0; return m; }

// ------------------------------------------------------------------ language
// S.target  = what goes into project["target"] (txtarget.normalise_target keys:
//             code, kind, script, rtl, font, face, align, px, xscale, ...)
// S.lang    = how to show it: {code, name, endonym, kind, script_name, lacking, sample, custom}
// S.source  = {id: 'en-usa'} or {id: 'ja-jp', path: <a Japan disc ISO>}
const TARGET_KEYS = ['code', 'kind', 'script', 'language', 'rtl', 'font', 'face', 'px', 'baseline', 'xscale',
  'align', 'wrap', 'battle_font', 'battle_face', 'battle_px', 'battle_baseline', 'battle_xscale'];
function cleanTarget(t) {
  const o = {};
  for (const k of TARGET_KEYS) if (t && t[k] !== undefined && t[k] !== null && t[k] !== '') o[k] = t[k];
  return o;
}
function langCode() { return (S.target && S.target.code) || 'fr'; }
function langName() { return (S.lang && S.lang.name) || langCode(); }
function langLabel() { const l = S.lang || {}; return l.endonym || l.name || langCode(); }
// "ᏣᎳᎩ (Cherokee)" / "Français (French)" / "My language"
function langFull(l) {
  l = l || S.lang || {};
  if (l.endonym && l.name && l.endonym !== l.name) return l.endonym + ' (' + l.name + ')';
  return l.endonym || l.name || l.code || '?';
}
function isRtl() { return !!(S.target && S.target.rtl); }
function bcp47() {
  const c = (S.target && (S.target.language || S.target.code)) || '';
  return c && c !== 'other' ? c : '';
}
function srcIsJa() { return !!(S.source && S.source.id === 'ja-jp'); }
function srcName() { return srcIsJa() || S.display === 'jp' ? 'Japanese' : 'English'; }
// the language of the open discs' own text: English on the USA discs, Japanese on the Japan discs
function baseName() { return S.display === 'jp' ? 'Japanese' : 'English'; }
// plain words for what a language needs (the KIND badge)
function kindWords(p) {
  const k = (p && p.kind) || 'builtin';
  if (k === 'builtin') return ['ready', 'Ready — the game font already has every letter'];
  if (k === 'script-hybrid') {
    const lack = Array.from(new Set(Array.from(p.lacking || '')));
    const low = lack.filter(c => c.toLowerCase() === c);
    const show = (low.length ? low : lack).slice(0, 4).join(' ');
    // a few letters the disc lacks, and the kit's own font has them: nothing to choose
    if (p.ready === 'auto') return ['auto', 'Ready — ' + (lack.length || 'a few') + ' letter' + (lack.length === 1 ? '' : 's') +
            ' the game font lacks' + (show ? ' (' + show + (lack.length > 4 ? ' …' : '') + ')' : '') +
            ' are added from ' + (p.font_auto || 'the kit\'s font') + ' when you build'];
    return ['extra', 'Needs ' + (lack.length || 'a few') + ' extra letter' + (lack.length === 1 ? '' : 's') +
            (show ? ' (' + show + (lack.length > 4 ? ' …' : '') + ')' : '') + ' from a font file'];
  }
  if (k === 'japanese') return ['ja', 'Japanese — built in, rare kanji from a font'];
  return ['new', 'New script — letters drawn from a font file'];
}
function needsFont(t) { return !!t && t.kind && t.kind !== 'builtin'; }
// the few letters the game font lacks come from the kit's own font at build time: nothing to choose
function autoFont(lang) { return !!lang && lang.ready === 'auto'; }
function autoFontLabel() { return S.lang && S.lang.font_auto ? S.lang.font_auto : 'the kit\'s font'; }
function syncLangUi() {
  updateOutDefault(); updateSteps(); updateFromLabel();
  const lab = document.querySelector('.talabel .ln'); if (lab) lab.textContent = langLabel();
}
function updateFromLabel() {
  const f = $('fromlbl');
  f.replaceChildren('Translating from ', h('b', {text: srcName()}), srcIsJa() ? ' (Japan discs)' : ' (this disc set)',
    ' into ', h('b', {text: langLabel()}));
  $('origsub').textContent = (srcIsJa() ? 'Japanese, English beneath' : baseName()) + ' · click a line to translate it';
}
async function profileFor(code) {
  if (!code || code === 'other') return null;
  try {
    const j = await getJson('/tx/languages?q=' + encodeURIComponent(code) + (S.iso ? '&iso=' + encodeURIComponent(S.iso) : ''));
    const lc = code.toLowerCase();
    return (j.languages || []).find(p => (p.code || '').toLowerCase() === lc) || null;
  } catch (_) { return null; }
}
async function fontLabelOf(path, face) {
  if (!path) return '';
  try {
    const j = await api('/tx/font-info', {path});
    const f = (j.faces || [])[face || 0];
    return f ? f.label : basename(path);
  } catch (_) { return basename(path); }
}
// the project's language choice -> S.target / S.lang / S.source (old projects
// have only "language": their target is that language's profile)
async function setLangFromProject(proj) {
  const t = proj.target ? Object.assign({}, proj.target) : {code: proj.language || 'fr'};
  if (!t.code) t.code = proj.language || 'fr';
  const prof = await profileFor(t.code);
  S.target = t;
  S.lang = Object.assign({code: t.code, name: t.code, endonym: '', kind: t.kind || 'builtin'}, prof || {});
  if (proj.language_name) S.lang.name = proj.language_name;
  if (t.kind) S.lang.kind = t.kind;
  if (!prof) S.lang.custom = true;
  if (t.kind === undefined) S.target.kind = S.lang.kind;
  if (t.rtl === undefined && prof) S.target.rtl = !!prof.rtl;
  S.fontLabel = t.font ? await fontLabelOf(t.font, t.face || 0) : '';
  const src = proj.source && proj.source.id === 'ja-jp' ? {id: 'ja-jp', path: proj.source.path || ''} : {id: 'en-usa'};
  const changed = JSON.stringify(src) !== JSON.stringify(S.source);
  S.source = src;
  syncLangUi();
  if (changed) loadSource();
}
// After a disc is read: what the chosen language lacks depends on the disc (French
// lacks three letters on the USA discs, every accent on the Japan ones), so the
// language state is resolved again for it, not kept from the built-in USA default.
async function refreshLangForDisc(gen) {
  if (S.proj) { await setLangFromProject(S.proj); return; }
  if (S.lang.custom || !S.lang.code || S.lang.code === 'other') return;
  const prof = await profileFor(S.lang.code);
  if (!prof || gen !== catGen || S.proj) return;
  S.lang = Object.assign({}, S.lang, prof);
  S.target = Object.assign({}, S.target, {kind: prof.kind || S.target.kind, rtl: !!prof.rtl});
  if (prof.script) S.target.script = prof.script;
  syncLangUi();
}
// the language of a project is locked once it holds translated lines
function trCountDone() { return S.proj ? Object.values(S.proj.translations || {}).filter(t => t && t.text).length : 0; }
function langLocked() { return !!(S.proj && trCountDone() > 0); }
function lockKey(t, l) { t = t || {}; return t.code === 'other' || !t.code ? 'other:' + (t.language || (l && l.name) || '') : t.code; }
function applySetup(w, keepProject) {
  S.target = cleanTarget(w.target);
  S.lang = Object.assign({}, w.lang);
  S.fontLabel = w.fontLabel || '';
  const srcChanged = JSON.stringify(w.source) !== JSON.stringify(S.source);
  S.source = Object.assign({}, w.source);
  if (S.proj && !keepProject) {
    S.proj.target = cleanTarget(w.target);
    S.proj.language = S.target.code;
    if (S.lang.name) S.proj.language_name = S.lang.name;
    S.proj.source = srcIsJa() ? {id: 'ja-jp', path: S.source.path} : {id: 'en-usa'};
    markDirty();
  }
  syncLangUi();
  if (srcChanged) loadSource();
  renderEditor(); refreshView(false);
  if (S.proj) runAllChecks();
}

// ------------------------------------------------------------------ backups (txbackup)
// The project saves by itself; backups are extra dated copies in "<name> backups/"
// next to it: automatic ones (the server copies the file before a save replaces it,
// at most every 10 minutes), checkpoints the translator names ("End of disc 1"),
// and a "before restore" copy whenever a backup is restored.
function bkWhen(b) {
  const d = new Date(b.time * 1000), now = new Date();
  const t = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return 'today ' + t;
  if (d.toDateString() === y.toDateString()) return 'yesterday ' + t;
  return d.toLocaleDateString([], {month: 'short', day: 'numeric', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined}) + ' ' + t;
}
const BK_KIND = {auto: 'automatic', checkpoint: 'checkpoint', 'before-restore': 'before restore'};
// a label that says where the translator is: the place open on the left, and the count
function bkDefaultLabel() {
  const n = S.proj ? Object.keys(S.proj.translations).length : 0;
  const where = S.sel.cat ? nodeLabel(S.sel.cat) + (S.sel.grp ? ' ' + S.sel.grp : '') : '';
  return (where ? where + ' · ' : '') + fmtN(n) + ' lines';
}
async function openBackups() {
  if (!S.proj || !S.projPath) { toast('Create or open a project first (step 2)', true); return; }
  await flushSave();
  const label = h('input', {type: 'text', placeholder: 'Name it, e.g. Labyrinthos done', maxlength: 80});
  label.value = bkDefaultLabel();
  const list = h('div', {class: 'bk-list'}, h('div', {class: 'bk-empty', text: 'Loading…'}));
  const folderEl = h('span', {class: 'dim'});
  let folder = '';
  const paint = (backs) => {
    if (!backs.length) { list.replaceChildren(h('div', {class: 'bk-empty', text: 'No backups yet. The first automatic one is made the next time your work saves; or save a checkpoint above.'})); return; }
    list.replaceChildren(...backs.map(b => h('div', {class: 'bk-row'},
      h('span', {text: bkWhen(b), title: b.when}),
      h('span', {class: 'k ' + b.kind, text: BK_KIND[b.kind] || b.kind}),
      h('span', {class: 'lb', text: b.label || '', title: b.name}),
      h('span', {class: 'n', text: b.translations == null ? '?' : fmtN(b.translations) + ' lines'}),
      h('button', {class: 'mini', text: 'Restore…', onclick: () => confirmRestore(b)}))));
  };
  const call = async (body) => {
    const j = await api('/tx/backups', Object.assign({path: S.projPath}, body));
    if (j.folder) { folder = j.folder; folderEl.textContent = 'Kept in ' + basename(folder) + '/ next to the project'; }
    if (j.backups) paint(j.backups);
    return j;
  };
  const doCheckpoint = async () => {
    try {
      await flushSave();
      await call({action: 'checkpoint', label: label.value, project: S.proj});
      toast('Checkpoint saved: ' + (label.value || 'no name'));
      label.value = bkDefaultLabel();
    } catch (e) { toast(e.message, true); }
  };
  label.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doCheckpoint(); } });
  const confirmRestore = (b) => {
    const cur = Object.keys(S.proj.translations).length;
    dialog({title: 'Restore this backup?', small: true,
      body: [h('p', {text: 'Go back to the ' + (BK_KIND[b.kind] || b.kind) + ' backup from ' + bkWhen(b) + (b.label ? ' (“' + b.label + '”)' : '') +
                            ', with ' + (b.translations == null ? '?' : fmtN(b.translations)) + ' translated lines.'}),
             h('p', {class: 'dim', text: 'Your project as it is now (' + fmtN(cur) + ' lines) is kept first as a “before restore” backup, so you can come back to it.'})],
      onCancel: () => setTimeout(openBackups, 0),
      buttons: [{text: 'Restore', run: async (setMsg) => {
        try {
          if (!(await flushSave())) { setMsg('The project could not be saved first; nothing restored', true); return false; }
          const j = await api('/tx/backups', {path: S.projPath, action: 'restore', backup: b.path, mtime: S.projMtime});
          adoptProject(S.projPath, j.project, j.mtime);
          toast('Restored the backup from ' + bkWhen(b) + ' (' + fmtN(Object.keys(j.project.translations).length) + ' lines)');
          return true;
        } catch (e) { setMsg(e.message, true); return false; }
      }}]});
  };
  const saveCopy = () => openPicker({mode: 'dir', title: 'Folder for a copy of the project (a USB stick, a cloud folder…)',
    startPath: dirname(S.projPath), onChoose: async (d) => {
      const day = new Date().toISOString().slice(0, 10);
      let dest = joinp(d, stem(S.projPath) + ' copy ' + day + '.json');
      try {
        await flushSave();
        let j;
        try { j = await api('/tx/backups', {path: S.projPath, action: 'copy', dest, project: S.proj}); }
        catch (e) {
          if (!/already exists/.test(e.message)) throw e;
          dest = joinp(d, stem(S.projPath) + ' copy ' + day + ' ' + new Date().toTimeString().slice(0, 8).replace(/:/g, '') + '.json');
          j = await api('/tx/backups', {path: S.projPath, action: 'copy', dest, project: S.proj});
        }
        toast('Copy saved: ' + j.copy);
      } catch (e) { toast(e.message, true); }
    }});
  dialog({title: 'Backups · ' + basename(S.projPath), wide: true,
    body: [h('p', {class: 'bk-intro', text: 'Your work saves by itself a moment after every change. Backups are extra copies you can go back to: an automatic one every 10 minutes while you work, and checkpoints you name yourself, for example when you finish a part of the game.'}),
           h('div', {class: 'bk-cp'}, label, h('button', {class: 'sm', text: 'Save checkpoint', onclick: doCheckpoint})),
           list,
           h('div', {class: 'bk-foot'}, folderEl, h('span', {class: 'grow'}),
             h('button', {class: 'ghost sm', text: 'Copy folder path', onclick: async () => { if (folder && await copyText(folder)) toast('Copied ' + folder); }}),
             h('button', {class: 'ghost sm', text: 'Save a copy elsewhere…', onclick: saveCopy}))],
    buttons: [], cancelText: 'Close'});
  try { await call({action: 'list'}); } catch (e) { list.replaceChildren(h('div', {class: 'bk-empty', text: e.message})); }
  setTimeout(() => { label.focus(); label.select(); }, 0);
}

// ------------------------------------------------------------------ Language setup (step 2)
// One dialog: which language you translate into (a list of 47 plus "my language
// isn't listed"), the font for letters the game lacks (suggested automatically
// from the installed fonts; only when the language needs one), a try-it box drawn
// with the game's font, and (Advanced) the Japanese source and layout options.
// mode "new" ends in the new-project dialog; mode "edit" applies to the open project.
let _langList = null;
// what a language needs depends on the disc (French lacks three letters on the
// USA discs and every accent on the Japanese ones): the list is asked for THIS
// disc and kept per disc
let _langIso = null;
async function languageList() {
  const key = (S.iso || '') + '|' + (S.catRev || '');     // a disc replaced at the same path is another list
  if (_langList && _langIso === key) return _langList;
  const iso = S.iso || '';
  const j = await getJson('/tx/languages?q=' + (iso ? '&iso=' + encodeURIComponent(iso) : ''));
  if (key !== (S.iso || '') + '|' + (S.catRev || '')) return j.languages || [];   // another disc came in meanwhile
  _langList = j.languages || []; _langIso = key;
  S.shaping = j.shaping || {ok: true};
  return _langList;
}
async function openSetup({mode, prev}) {
  if (!S.rows.length && !TX_FAKE) { toast('Step 1 first: choose the disc', true); return; }
  let langs;
  try { langs = await languageList(); } catch (e) { toast('Could not load the language list: ' + e.message, true); return; }
  // working copy
  const w = {target: Object.assign({}, S.target), lang: Object.assign({}, S.lang), source: Object.assign({}, S.source),
             fontLabel: S.fontLabel || ''};
  // "new": the open project (if any) keeps its language; this is put back if the new project is not created
  if (mode === 'new' && !prev) prev = {target: Object.assign({}, S.target), lang: Object.assign({}, S.lang),
                                       source: Object.assign({}, S.source), fontLabel: S.fontLabel || ''};
  let fontsGen = 0, pvGen = 0, pvT = null;

  const q = h('input', {type: 'search', class: 'lsq', placeholder: 'Search ' + langs.length + ' languages: Cherokee, ᏣᎳᎩ, chr, Tifinagh, NZ…'});
  const list = h('div', {class: 'llist', role: 'listbox'});
  const custom = h('div', {class: 'lcustom', hidden: true});
  const fontSec = h('div', {class: 'lsec', hidden: true});
  const tryIn = h('input', {type: 'text', class: 'path', style: 'width:100%'});
  const tryOut = h('div', {class: 'ltry'});
  const chosen = h('div', {class: 'lchosen'});

  const pick = (p, keepFont) => {
    const prevCode = w.target.code;
    w.lang = Object.assign({}, p);
    const t = {code: p.code, kind: p.kind, script: p.script || undefined, rtl: !!p.rtl};
    if (p.custom) { t.language = p.code !== 'other' ? p.code : undefined; t.sample = p.sample; }
    if (keepFont || prevCode === p.code) { ['font', 'face', 'align'].forEach(k => { if (w.target[k] !== undefined) t[k] = w.target[k]; }); }
    else w.fontLabel = '';
    if (t.rtl && !t.align) t.align = 'right';
    w.target = t;
    if (!tryIn.dataset.touched) tryIn.value = p.sample || '';
    paintList(); paintChosen(); paintFont(); queueTry();
  };
  const SHORT = {ready: 'ready', auto: 'ready · a few letters added', extra: 'a few letters from a font', ja: 'built in + rare kanji', new: 'new script · font'};
  const badge = (p) => { const [cls, words] = kindWords(p); return h('span', {class: 'lk ' + cls, text: SHORT[cls] || words, title: words}); };
  const paintList = () => {
    const qq = q.value.trim().toLowerCase();
    const els = [];
    let lastReg = null, shown = 0;
    // A search lists the language whose own name, English name or code is the
    // query first, then names that start with it, then the rest (script name,
    // aliases, regions): "Arabic" shows Arabic above the languages written in
    // Arabic script instead of among them.
    const rank = (p) => {
      if (!qq) return 0;
      const names = [p.code, p.name, p.endonym].concat(p.aliases || []).filter(Boolean).map(x => x.toLowerCase());
      if (names.indexOf(qq) >= 0) return 0;
      if (names.some(x => x.startsWith(qq) || x.split(/[\s()\-]+/).some(wd => wd.startsWith(qq)))) return 1;   // "Egyptian Arabic"
      return 2;
    };
    const hits = [];
    langs.forEach((p, i) => {
      const hay = [p.code, p.name, p.endonym, p.script_name, (p.aliases || []).join(' '), (p.regions || []).join(' ')].join(' ').toLowerCase();
      if (qq && hay.indexOf(qq) < 0 && (p.regions || []).map(r => r.toLowerCase()).indexOf(qq) < 0) return;
      hits.push([rank(p), i, p]);
    });
    hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    for (const [score, , p] of hits) {
      const reg = qq ? (score < 2 ? 'best' : 'more') : (p.registry ? 'all' : 'top');
      if (reg !== lastReg) {
        els.push(h('div', {class: 'lhdr', text: {all: 'All languages, A–Z', top: 'Most asked for', best: 'Best matches', more: 'Also matches'}[reg]}));
        lastReg = reg;
      }
      shown++;
      const on = !w.lang.custom && w.lang.code === p.code;
      els.push(h('button', {class: 'lrow' + (on ? ' on' : ''), role: 'option', 'aria-selected': on ? 'true' : 'false',
        onclick: () => { custom.hidden = true; pick(p); }},
        h('span', {class: 'le', text: p.endonym || p.name, lang: p.code, dir: p.rtl ? 'rtl' : null}),
        h('span', {class: 'ln2', text: p.name + (p.script_name && p.script_name !== 'Latin' ? ' · ' + p.script_name : '')}),
        badge(p)));
    }
    if (!shown) els.push(h('div', {class: 'bk-empty', text: 'No language matches “' + q.value.trim() + '”. Try its own name, its English name, a code like chr, or a country code like NZ — or set it up below.'}));
    els.push(h('button', {class: 'lrow other' + (w.lang.custom ? ' on' : ''), onclick: () => { custom.hidden = false; paintList(); custom.querySelector('input').focus(); }},
      h('span', {class: 'le', text: 'My language isn\'t listed…'}),
      h('span', {class: 'ln2', text: 'any language: set it up from a sample sentence'}), h('span')));
    list.replaceChildren(...els);
  };
  // "my language isn't listed": name + sample sentence -> kind, script, direction
  const cName = h('input', {type: 'text', placeholder: 'Language name, e.g. Cherokee', value: w.lang.custom ? (w.lang.name || '') : ''});
  const cCode = h('input', {type: 'text', class: 'advonly', placeholder: 'code (optional), e.g. chr', style: 'max-width:12em', value: w.lang.custom && w.lang.code !== 'other' ? w.lang.code : ''});
  const cSample = h('textarea', {rows: 2, placeholder: 'Paste a sentence in your language, with its special letters (it decides which letters need a font)'});
  if (w.lang.custom) cSample.value = w.lang.sample || '';
  const cMsg = h('div', {class: 'lmsg'});
  const cGo = h('button', {class: 'sm', text: 'Use this language', onclick: async () => {
    if (!cName.value.trim() || !cSample.value.trim()) { cMsg.textContent = 'Give the name and a sample sentence.'; return; }
    cMsg.textContent = 'Looking at the letters…';
    try {
      const p = await api('/tx/custom-language', {name: cName.value.trim(), sample: cSample.value, code: cCode.value.trim(), iso: S.iso});
      if (!p.endonym) p.endonym = p.name;
      cMsg.textContent = ''; pick(p);
    } catch (e) { cMsg.textContent = e.message; }
  }});
  custom.append(h('div', {class: 'lrowf'}, cName, cCode), cSample, h('div', {class: 'lrowf'}, cGo, cMsg));
  if (w.lang.custom) custom.hidden = false;

  const paintChosen = () => {
    const [, words] = kindWords(w.lang);
    chosen.replaceChildren(...[h('span', {class: 'big', text: langFull(w.lang)}), h('span', {class: 'dim', text: ' · ' + words + (w.target.rtl ? ' · right to left' : '')}),
      w.lang.notes ? h('div', {class: 'lnote', text: w.lang.notes}) : null].filter(Boolean));
  };
  // the font for letters the game lacks: ranked by how many of the language's letters they draw
  const paintFont = async () => {
    if (!needsFont(w.target)) { fontSec.hidden = true; return; }
    fontSec.hidden = false;
    const gen = ++fontsGen;
    const head = h('h4', {text: 'Font for the new letters'});
    const why = h('p', {class: 'dim', text: w.target.kind === 'japanese'
      ? 'Kana and common kanji come from the game\'s own font. Rare kanji are drawn from this font when you build.'
      : w.target.kind === 'script-hybrid' ? 'The letters the game already has stay as they are. The few it lacks are drawn from this font when you build.'
      : 'Every letter of this language is drawn from this font when you build. Pick one that looks clear at small sizes.'});
    fontSec.replaceChildren(head, why, h('div', {class: 'dim', text: 'Finding installed fonts that have every letter… (the first time, reading every installed font takes up to half a minute)'}));
    if (S.shaping && !S.shaping.ok) fontSec.appendChild(h('div', {class: 'lmsg e', text: S.shaping.message}));
    let res;
    try { res = await api('/tx/fonts', {target: w.target, language: w.target.code, prefer: (w.lang.fonts || []).concat([w.lang.name || '', w.lang.script_name || '']),
                                       chars: '', iso: S.iso}); }   // the language's own letters; lines already typed are checked by the checker
    catch (e) { if (gen === fontsGen) fontSec.replaceChildren(head, why, h('div', {class: 'lmsg e', text: e.message})); return; }
    if (gen !== fontsGen) return;
    const fonts = res.fonts || [];
    w.noFontNeeded = !res.chars;
    if (!res.chars && !w.target.font) {
      fontSec.replaceChildren(head, why, h('div', {class: 'lmsg', text: 'No font needed for now: the game font has every letter used so far. If a translation uses a letter it lacks, the checker says so and you can choose a font here.'}));
      return;
    }
    const choose = (f) => { w.target.font = f.path; w.target.face = f.face || 0; if (!w.target.face) delete w.target.face; w.fontLabel = f.label; paintFont(); queueTry(); };
    // nothing chosen yet: take the best font that draws every letter. Not when the kit's own
    // font has the few letters the disc lacks: the build then takes them from it, the same on
    // every machine, and the project stays free of a font path of this one
    const autoNote = (!w.target.font && w.lang.ready === 'auto')
      ? h('div', {class: 'lmsg', text: 'Nothing to choose: the letters the game font lacks are added from ' + (w.lang.font_auto || 'the kit\'s font') +
          ' when you build. Pick a font below only if you want another look.'}) : null;
    if (!w.target.font && !autoNote && fonts.length && fonts[0].covers >= 1) { choose(fonts[0]); return; }
    const rows = fonts.slice(0, 6).map(f => {
      const on = w.target.font === f.path && (w.target.face || 0) === (f.face || 0);
      return h('button', {class: 'frow' + (on ? ' on' : ''), onclick: () => choose(f)},
        h('span', {class: 'fl', text: f.label}),
        h('span', {class: 'fc' + (f.covers >= 1 ? ' ok' : ''), text: f.covers >= 1 ? 'has every letter' : Math.round(f.covers * 100) + '% · lacks ' + f.missing.slice(0, 12)}));
    });
    const cur = w.target.font && !fonts.slice(0, 6).some(f => f.path === w.target.font)
      ? h('div', {class: 'frow on'}, h('span', {class: 'fl', text: w.fontLabel || basename(w.target.font)}), h('span', {class: 'fc', text: 'your file'})) : null;
    const browse = h('button', {class: 'ghost sm', text: 'Use a font file…', onclick: () => openPicker({mode: 'file', title: 'A font file (.ttf, .otf, .ttc)',
      startPath: w.target.font ? dirname(w.target.font) : '/Library/Fonts',
      onChoose: async (path) => {
        try { const fi = await api('/tx/font-info', {path, chars: res.chars || ''}); const f = fi.faces[0];
              choose({path: fi.path, face: 0, label: f.label}); }
        catch (e) { toast(e.message, true); }
      }})});
    fontSec.replaceChildren(head, why, ...(autoNote ? [autoNote] : []), ...(rows.length ? rows : [h('div', {class: 'lmsg e', text: 'No installed font has these letters. Install a Noto font for this script (fonts.google.com/noto), or use a font file.'})]),
      cur || h('span'), h('div', {class: 'lrowf'}, browse,
        w.target.rtl ? h('label', {class: 'chk advonly'}, h('input', {type: 'checkbox', checked: w.target.align === 'right' ? true : null,
          onchange: (e) => { w.target.align = e.target.checked ? 'right' : undefined; }}), ' right-align dialogue') : null));
  };
  // try it: drawn with the game's font (and the chosen font for new letters)
  const queueTry = () => { clearTimeout(pvT); pvT = setTimeout(runTry, 350); };
  const runTry = async () => {
    const gen = ++pvGen;
    const text = tryIn.value;
    if (!text.trim()) { tryOut.replaceChildren(h('span', {class: 'dim', text: 'Type a sentence above to see it in the game\'s font.'})); return; }
    let r;
    try { r = await api('/tx/target-preview', {iso: S.iso, target: w.target, text, face: 'font1'}); }
    catch (e) { if (gen === pvGen) tryOut.replaceChildren(h('div', {class: 'lmsg e', text: e.message})); return; }
    if (gen !== pvGen) return;
    const kids = [];
    if (r.error) kids.push(h('div', {class: 'lmsg' + (r.need_font ? '' : ' e'), text: r.error}));
    (r.pngs || []).forEach(u => kids.push(h('img', {src: u, alt: text})));
    tryOut.replaceChildren(...(kids.length ? kids : [h('span', {class: 'dim', text: '…'})]));
  };
  tryIn.addEventListener('input', () => { tryIn.dataset.touched = '1'; queueTry(); });

  // translate from (Advanced): English of the USA discs, or Japanese of the Japan discs
  const srcMsg = h('span', {class: 'dim'});
  const srcPath = h('span', {class: 'mono', text: w.source.path ? basename(w.source.path) : ''});
  const rEn = h('input', {type: 'radio', name: 'lsrc', checked: !srcIsJaW() ? true : null});
  const rJa = h('input', {type: 'radio', name: 'lsrc', checked: srcIsJaW() ? true : null});
  function srcIsJaW() { return w.source.id === 'ja-jp'; }
  const pickJaDisc = () => openPicker({mode: 'file', filter: 'iso', title: 'Xenosaga Episode III (Japan) .iso, either disc',
    startPath: dirname(S.iso), onChoose: async (path) => {
      const j = await getJson('/tx/identify-source?path=' + encodeURIComponent(path));
      srcMsg.textContent = j.message;
      if (j.ok) { w.source = {id: 'ja-jp', path: j.path}; srcPath.textContent = basename(j.path); rJa.checked = true; }
      else if (!w.source.path) rEn.checked = true;
    }});
  rEn.addEventListener('change', () => { w.source = {id: 'en-usa'}; });
  rJa.addEventListener('change', () => { if (w.source.path) w.source = {id: 'ja-jp', path: w.source.path}; else { rEn.checked = true; pickJaDisc(); } });
  if (S.display === 'jp') { rJa.disabled = true; srcMsg.textContent = 'These are the Japan discs: their own text is the Japanese. The Japanese source is for a project on the USA discs.'; }
  const srcSec = h('div', {class: 'lsec advonly'}, h('h4', {text: 'Translate from'}),
    h('label', {class: 'chk'}, rEn, S.display === 'jp' ? ' The text of the discs you opened (Japanese)' : ' The text of the discs you opened (English on the USA discs)'),
    h('label', {class: 'chk'}, rJa, ' Japanese (the Japan discs, for a project on the USA discs) ', srcPath, ' ',
      h('button', {class: 'mini', text: 'Choose disc…', onclick: (e) => { e.preventDefault(); pickJaDisc(); }})),
    srcMsg);

  const unlock = h('input', {type: 'checkbox'});
  const lockNote = (mode !== 'new' && langLocked()) ? h('div', {class: 'lnote', style: 'margin:0 0 8px'},
    '🔒 This project is in ' + langFull() + ' (' + fmtN(trCountDone()) + ' line(s) translated). Its language is locked; for another language press New and make a separate project.',
    h('label', {class: 'chk advonly', style: 'display:block;margin-top:6px'}, unlock,
      ' Change this project\'s language anyway (set up as the wrong one). A checkpoint backup is made first; lines already translated are not converted.')) : null;
  // a new query starts at the top of the list (the open list may be scrolled to the current language)
  q.addEventListener('input', () => { paintList(); list.scrollTop = 0; });
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const b = list.querySelector('.lrow'); if (b) b.click(); } });
  tryIn.value = w.lang.sample || '';
  paintList(); paintChosen(); paintFont(); queueTry();
  dialog({title: mode === 'new' ? 'Language setup · new project' : 'Language setup', wide: true,
    // New → Next → Back → Cancel: Next already showed the new language; the open project gets its own back
    onCancel: () => { if (mode === 'new' && prev && S.proj && JSON.stringify(cleanTarget(prev.target)) !== JSON.stringify(cleanTarget(S.target))) applySetup(prev, true); },
    body: [h('div', {class: 'lgrid'},
      h('div', {class: 'lcol'}, ...[h('h4', {text: 'Translate into'}), lockNote, q, list, custom].filter(Boolean)),
      h('div', {class: 'lcol'}, chosen, fontSec,
        h('div', {class: 'lsec'}, h('h4', {text: 'Try it'}), tryIn, tryOut,
          h('p', {class: 'dim', text: 'Drawn with the game\'s own font, as it will look after Build.'})),
        srcSec))],
    buttons: [{text: mode === 'new' ? 'Next: create the project ›' : 'Apply', run: async (setMsg) => {
      if (needsFont(w.target) && !w.target.font && !w.noFontNeeded && !autoFont(w.lang)) { setMsg('Choose a font for the new letters first', true); return false; }
      // One project = one language. Once lines are translated the language is
      // locked: another language is another project (New). Advanced can still
      // change it (a project set up as the wrong variant), after a checkpoint.
      if (mode !== 'new' && langLocked() && lockKey(w.target, w.lang) !== lockKey(S.target, S.lang)) {
        if (!(S.adv && unlock.checked)) {
          setMsg('This project already has ' + fmtN(trCountDone()) + ' translated line(s) in ' + langFull() + ', so its language is locked. ' +
                 'To translate into ' + langFull(w.lang) + ', close this and press New: each language gets its own project file. ' +
                 '(The font and options of ' + langFull() + ' can still be changed here.)', true);
          return false;
        }
        try {
          if (S.dirty && !(await saveProject()) && S.dirty) throw new Error('the project could not be saved');
          await api('/tx/backups', {path: S.projPath, action: 'checkpoint', label: 'before language change from ' + langFull(), project: S.proj});
        } catch (e) { setMsg('No checkpoint could be made, so the language was not changed: ' + e.message, true); return false; }
      }
      applySetup(w, mode === 'new');
      if (mode === 'new') setTimeout(() => newProjectDialog(prev), 0);
      else toast('Language: ' + langFull());
      return true;
    }}]});
  setTimeout(() => { const on = list.querySelector('.lrow.on'); if (on) on.scrollIntoView({block: 'center'}); q.focus(); }, 0);
}

// ------------------------------------------------------------------ Japanese source (txsource)
// GET /tx/source answers {state: running, log} until the alignment is done
// (about 12 s the first time, then cached), then {texts, partial, by_cat, stats}.
let srcGen = 0;
function jaOf(r) { return (S.ja && S.ja.texts[r.id]) || ''; }
async function loadSource() {
  const gen = ++srcGen;
  S.ja = null; S.jaMsg = '';
  S.rows.forEach(r => { r._lc = undefined; });
  if (!srcIsJa() || !S.iso || TX_FAKE) { updateBanner(); refreshView(false); renderEditor(); return; }
  if (!S.source.path) { S.jaMsg = 'Japanese source: choose a Japan disc in step 2 (Language setup).'; updateBanner(); return; }
  const url = '/tx/source?usa=' + encodeURIComponent(S.iso) + '&src=' + encodeURIComponent(S.source.path);
  const t0 = Date.now();
  for (;;) {
    let j;
    try { j = await getJson(url); }
    catch (e) { if (gen !== srcGen) return; S.jaMsg = 'Japanese source: ' + e.message; updateBanner(); return; }
    if (gen !== srcGen) return;
    if (j.state === 'running') {
      S.jaMsg = 'Reading the Japanese from the Japan discs… ' + Math.round((Date.now() - t0) / 1000) + ' s · ' + (j.log || '') +
        ' (about 10 s the first time; cached afterwards). Until then the list shows the English.';
      updateBanner(); await new Promise(res => setTimeout(res, 900)); continue;
    }
    if (j.state === 'error') { S.jaMsg = 'Japanese source not available: ' + j.error + ' — the list shows the English.'; updateBanner(); return; }
    S.ja = {texts: j.texts || {}, partial: new Set(j.partial || []), by_cat: j.by_cat || {}, stats: j.stats || {}};
    S.jaMsg = '';
    S.rows.forEach(r => { r._lc = undefined; });
    updateBanner(); refreshView(false); renderEditor(); updateSteps();
    toast('Japanese source ready: ' + jaSummary(S.ja));
    return;
  }
}
// "Japanese found for 99.6% of dialogue; database 28% …"
function jaSummary(ja) {
  const bc = ja.by_cat || {};
  const pct = (cats) => {
    let v = 0, a = 0;
    cats.forEach(c => { const x = bc[c]; if (x) { v += x.visible || 0; a += x.visible_aligned || 0; } });
    return v ? (100 * a / v) : null;
  };
  const f = (x) => x === null ? '—' : (x >= 99.95 ? '100' : x.toFixed(x >= 10 ? 1 : 1).replace(/\.0$/, '')) + '%';
  const dlg = pct(['Dialogue — event lines (voiced)', 'Dialogue — field boxes', 'Dialogue — townspeople',
                   'Dialogue — scenes', 'Dialogue — battle scenes']);
  const parts = ['Japanese found for ' + f(dlg) + ' of dialogue'];
  const more = [['Movie subtitles', 'movie subtitles'], ['Menu text', 'menus'], ['Battle names & descriptions', 'battle names'],
                ['Database & menu tables', 'database (not paired: its entries are sorted differently)']];
  more.forEach(([c, w]) => { const x = pct([c]); if (x !== null) parts.push(w + ' ' + f(x)); });
  return parts.join('; ') + ' — missing lines show the English';
}

// ------------------------------------------------------------------ catalog
// /tx/catalog sends column arrays (txcatalog.compact): part "main" = rows with
// no hide reason plus the tree, part "hidden" = the rest, fetched only when
// "show hidden" is on or the project has translations for rows not loaded yet.
const PERF = /perf/.test(location.hash);
function perf(msg) { if (PERF) console.log('[tx-perf] ' + msg); }
const DICT_FIELDS = ['fam', 'cat', 'grp', 'ctx', 'font', 'ctl', 'measure', 'face', 'lock', 'hide', 'use'];
function decodePart(p) {
  const out = new Array(p.n), c = p.col, d = p.dict;
  const dc = DICT_FIELDS.map(f => [f, c[f], d[f]]);
  for (let j = 0; j < p.n; j++) {
    const r = {id: c.id[j], src: c.src[j], ord: c.ord[j], px: c.px[j], lim: c.lim[j], dup: c.dup[j], _i: c.ix[j]};
    for (const [f, col, tab] of dc) r[f] = tab[col[j]];
    out[j] = r;
  }
  return out;
}
function indexRows(rows) {
  const grpIdx = new Map();
  S.cats.forEach(c => c.groups.forEach((g, j) => grpIdx.set(c.cat + '\u0000' + g.grp, j)));
  for (const r of rows) { r._g = grpIdx.get(r.cat + '\u0000' + r.grp) || 0; r._c = S.catIdx.get(r.cat) || 0; }
  rows.sort((a, b) => (a._c - b._c) || (a._g - b._g) || ((a.ord || 0) - (b.ord || 0)) || (a._i - b._i));
  S.rows = rows;
  S.byId = new Map();
  S.nodeRows = new Map(); S.srcIds = new Map();
  for (const r of rows) {
    S.byId.set(r.id, r);
    const kc = r.cat, kg = r.cat + '\u0000' + r.grp;
    let a = S.nodeRows.get(kc); if (!a) S.nodeRows.set(kc, a = []); a.push(r);
    let b = S.nodeRows.get(kg); if (!b) S.nodeRows.set(kg, b = []); b.push(r);
    if (!r.lock) { let s = S.srcIds.get(r.src); if (!s) S.srcIds.set(r.src, s = []); s.push(r.id); }
  }
}
let catGen = 0;
async function loadCatalog() {
  const iso = $('iso').value.trim();
  if (!iso && !TX_FAKE) { toast('Choose the retail ISO first', true); return; }
  const gen = ++catGen;
  $('tree').replaceChildren(treeHead(), h('div', {class: 'tree-empty', text: 'Reading every text family from the disc… (the first time takes a while; it is cached afterwards)'}));
  $('list').replaceChildren(h('div', {class: 'empty', text: 'Loading the disc…'}));
  $('step1-s').textContent = 'reading ' + basename(iso) + '…';
  const t0 = performance.now();
  let cat;
  try { cat = await getJson('/tx/catalog?part=main&iso=' + encodeURIComponent(iso)); }
  catch (e) {
    if (gen !== catGen) return;
    S.iso = ''; S.rows = []; S.byId = new Map(); S.rid = ''; S.display = '';
    $('tree').replaceChildren(treeHead(), h('div', {class: 'tree-empty', text: 'Could not read the catalog: ' + e.message}));
    $('list').replaceChildren(h('div', {class: 'list-empty'}, h('div', {class: 'guide-card'},
      h('span', {class: 'k', text: 'Step 1'}), h('span', {class: 'big', text: 'That file could not be read as a Xenosaga Episode III disc.'}),
      h('p', {text: e.message}),
      h('div', {class: 'btns'}, h('button', {text: 'Choose another disc…', onclick: pickIso})))));
    updateSteps();
    return;
  }
  if (gen !== catGen) return;
  const t1 = performance.now();
  S.iso = iso; store('iso', iso);
  S.rid = cat.retail_id || ''; S.notes = cat.notes || []; S.display = cat.display || ''; S.catRev = cat.rev || '';
  S.ridLone = cat.retail_lone || [];
  S.cats = cat.cats || []; S.total = cat.total || cat.n;
  // rows (and "All text") follow the sidebar's sections: story first, then menus, items, U.M.N., mini-games
  { const order = []; SECTIONS.forEach(([, cs]) => cs.forEach(([c]) => order.push(c)));
    const rank = (c) => { const i = order.indexOf(c); return i < 0 ? order.length : i; };
    S.catIdx = new Map(S.cats.map((c, i) => [c.cat, rank(c.cat) * 1000 + i])); }
  S.hidden = {loaded: cat.n >= S.total, promise: null};
  S.pvCache = new Map();
  indexRows(decodePart(cat));
  indexSpeakers();
  const t2 = performance.now();
  if (S.sel.cat && !S.catIdx.has(S.sel.cat) && !isSpkKey(S.sel.cat)) S.sel = {cat: null, grp: null};
  if (S.cur && !S.byId.has(S.cur)) S.cur = null;
  updateOutDefault();
  recomputeTm(); updateBanner(); renderTree(); refreshView(true); renderEditor(); updateSteps();
  const t3 = performance.now();
  perf('catalog main: ' + fmtN(cat.n) + ' of ' + fmtN(S.total) + ' rows; fetch+parse ' + (t1 - t0).toFixed(0) +
       ' ms, decode+index ' + (t2 - t1).toFixed(0) + ' ms, first render ' + (t3 - t2).toFixed(0) +
       ' ms; interactive at ' + t3.toFixed(0) + ' ms after navigation');
  if (S.showHidden || projectNeedsHidden()) loadHidden();
  refreshLangForDisc(gen).catch(() => {});
  if (S.proj) runAllChecks();
  if (srcIsJa()) loadSource();
}
function projectNeedsHidden() {
  if (!S.proj || !S.hidden || S.hidden.loaded) return false;
  for (const id in S.proj.translations) if (!S.byId.has(id)) return true;
  return false;
}
function loadHidden() {
  if (!S.hidden || S.hidden.loaded) return Promise.resolve();
  if (S.hidden.promise) return S.hidden.promise;
  const gen = catGen, iso = S.iso;
  $('rowcount').textContent = 'loading hidden lines…';
  S.hidden.promise = (async () => {
    const t0 = performance.now();
    let p;
    try { p = await getJson('/tx/catalog?part=hidden&iso=' + encodeURIComponent(iso)); }
    catch (e) { toast('Could not load the hidden lines: ' + e.message, true); S.hidden.promise = null; return; }
    if (gen !== catGen) return;
    if (p.rev && S.catRev && p.rev !== S.catRev) {   // the discs changed between the two parts: read them again
      S.hidden.promise = null; toast('The discs changed on disk since they were read: reading them again', true);
      loadCatalog(); return;
    }
    const t1 = performance.now();
    indexRows(S.rows.concat(decodePart(p)));
    indexSpeakers();
    S.hidden.loaded = true;
    recomputeTm(); renderTree(); refreshView(false); updateBuildSummary(); updateSteps();
    perf('catalog hidden: ' + fmtN(p.n) + ' rows; fetch+parse ' + (t1 - t0).toFixed(0) + ' ms, merge+render ' +
         (performance.now() - t1).toFixed(0) + ' ms');
    if (S.proj) runAllChecks();
  })();
  return S.hidden.promise;
}

function updateBanner() {
  const msgs = [];
  if (TX_FAKE) msgs.push('TX_FAKE=1: this is the built-in sample catalog, not your disc.');
  const real = S.notes.filter(n => n !== '(from cache)' && !(TX_FAKE && n.startsWith('TX_FAKE')));
  // Episode III: the first note says which discs the rows cover; it is a warning only for a lone disc
  const lone = real.filter(n => /^Xenosaga Episode III .* only:/.test(n));
  const rest = real.filter(n => !/^Xenosaga Episode III /.test(n));
  if (lone.length) msgs.push(lone[0]);
  if (rest.length) msgs.push('Catalog notes: ' + rest.join(' · '));
  let upgrade = null;
  if (S.proj && S.rid && S.proj.retail_id && S.proj.retail_id !== S.rid) {
    if ((S.ridLone || []).includes(S.proj.retail_id)) {
      // made while only one disc was found; the other one is next to it now
      msgs.push('This project was made while only one disc of this set was found. Both discs are found now: move the project to the pair to build both (your translations stay as they are).');
      upgrade = h('button', {class: 'sm', text: 'Use both discs', onclick: () => {
        if (!S.proj) return;
        S.proj.retail_id = S.rid; markDirty(); updateBanner(); toast('The project is now for both discs of this set');
      }});
    } else {
      msgs.push('This project was made for a different disc set (retail id ' + S.proj.retail_id.slice(0, 10) +
                '…, these discs are ' + S.rid.slice(0, 10) + '…). Pick the untouched retail discs it was started from, or the build will refuse it.');
    }
  }
  if (S.jaMsg) msgs.push(S.jaMsg);
  const b = $('banner'); b.hidden = !msgs.length; b.replaceChildren(msgs.join('  '));
  if (upgrade) b.append(' ', upgrade);
}

// ------------------------------------------------------------------ steps
function updateSteps() {
  const haveDisc = S.rows.length > 0, haveProj = !!S.proj;
  const cur = !haveDisc ? 1 : !haveProj ? 2 : 3;
  [1, 2, 3, 4].forEach(n => {
    const el = $('step' + n);
    const done = (n === 1 && haveDisc) || (n === 2 && haveProj);
    el.classList.toggle('done', done); el.classList.toggle('cur', n === cur);
    el.querySelector('.num').textContent = done ? '✓' : String(n);
  });
  const s1 = $('step1-s');
  if (haveDisc) { s1.textContent = S.iso ? basename(S.iso) : 'built-in sample catalog'; s1.title = S.iso; s1.className = 's'; }
  else if (!catGen) { s1.textContent = 'either disc, as .iso'; s1.title = ''; s1.className = 's dim'; }
  const ib = $('btn-iso-pick');
  ib.textContent = haveDisc ? 'Change' : 'Choose disc…'; ib.className = haveDisc ? 'sm ghost' : 'sm';
  const s2 = $('step2-s');
  // "English → ᏣᎳᎩ (Cherokee) · Plantagenet Cherokee"
  const chain = srcName() + ' → ' + langFull() + (S.fontLabel ? ' · ' + S.fontLabel : autoFont(S.lang) ? ' · ' + autoFontLabel() : needsFont(S.target) ? ' · no font yet' : '');
  if (haveProj) { s2.textContent = chain; s2.title = chain + '\nproject: ' + S.projPath + '\nclick to change the Language setup'; s2.className = 's'; }
  else { s2.textContent = 'any language · press New'; s2.title = 'New opens the Language setup: translate from English or Japanese into any language (the list, or your own from a sample sentence), then creates the project'; s2.className = 's dim'; }
  const nb = $('btn-proj-new');
  nb.className = haveProj ? 'sm ghost' : 'sm'; nb.disabled = !haveDisc && !TX_FAKE;
  $('btn-setup').className = 'sm ghost'; $('btn-setup').hidden = !haveProj;
  const s3 = $('step3-s');
  if (haveDisc) {
    const [d, t] = counts(S.rows);
    s3.textContent = fmtN(d) + ' / ' + fmtN(t) + ' lines'; s3.className = 's';
    s3.title = fmtN(d) + ' of ' + fmtN(t) + ' editable lines translated' + (S.showHidden ? ' (hidden lines included)' : '');
    $('step3-bar').style.width = (t ? (100 * d / t) : 0).toFixed(2) + '%';
  } else { s3.textContent = 'type translations'; s3.className = 's dim'; $('step3-bar').style.width = '0'; }
  $('btn-build-open').disabled = !haveProj;
  $('step4-s').textContent = haveProj ? 'patched copies' : 'after step 2';
  const bb = $('btn-build');
  bb.disabled = building || !haveDisc || !haveProj;
  bb.title = building ? 'a build is running' :
    !haveDisc ? 'Step 1 first: choose the disc' : !haveProj ? 'Step 2 first: press New (Language setup, then the project) or Open…' :
    'write patched copies of the discs with your translations';
}

// ------------------------------------------------------------------ translations
function trOf(id) { return S.proj && S.proj.translations[id]; }
function isVisibleRow(r) { return (S.adv && S.showHidden) || !r.hide; }
function counts(list) {
  let tot = 0, done = 0;
  for (const r of list) {
    if (r.lock || !isVisibleRow(r)) continue;
    tot++; if (trOf(r.id)) done++;
  }
  return [done, tot];
}
function recomputeTm() {
  S.tmIds = new Set();
  if (!S.proj) return;
  for (const [id, t] of Object.entries(S.proj.translations)) {
    if (t.state !== 'draft') continue;
    const r = S.byId.get(id); if (!r) continue;
    const sib = S.srcIds.get(r.src) || [];
    if (sib.some(o => o !== id && trOf(o) && trOf(o).state === 'done' && trOf(o).text === t.text)) S.tmIds.add(id);
  }
}
function setTr(id, text, state) {
  if (!S.proj) ensureProjectFirst();
  if (!S.proj) return;
  if (!text) { delete S.proj.translations[id]; S.checks.delete(id); }
  else S.proj.translations[id] = {text, state};
  if (state === 'done') S.tmIds.delete(id);
}
function propagateTm(id) {
  if (!S.tm) return [];
  const r = S.byId.get(id), t = trOf(id);
  if (!r || !t) return [];
  const changed = [];
  for (const o of S.srcIds.get(r.src) || []) {
    if (o === id) continue;
    const ot = trOf(o);
    if (!ot || S.tmIds.has(o)) {
      if (ot && ot.text === t.text) continue;
      S.proj.translations[o] = {text: t.text, state: 'draft'}; S.tmIds.add(o); changed.push(o);
    }
  }
  return changed;
}

// ------------------------------------------------------------------ tree
// The sidebar has three views over the same rows:
//   type    — the categories, sorted into a few sections with plain names
//   speaker — every dialogue line under the name in its name box
//   file    — the categories as the readers name them (the disc's own layout)
const SECTIONS = [
  ['Story', [
    ['Dialogue — event lines (voiced)', 'Voiced scene dialogue', 'the lines of the real-time scenes, each with its voice clip'],
    ['Dialogue — field boxes', 'Field dialogue', 'the text boxes of the field: party talk, signs, examinations'],
    ['Dialogue — townspeople', 'Townspeople', 'what people say when spoken to; a <k...> word is a keyword they wait for'],
    ['Choices', 'Choices', 'the options of a choice, one per line'],
    ['Narration boxes', 'Narration', null],
    ['System messages', 'System messages', 'boxes such as "You obtained..."'],
    ['Battle messages', 'Battle messages', 'the tutorial and event boxes of battles'],
    ['Battle banners', 'Battle banners', null],
    ['Scene text picked from a table', 'Scene text picked from a table', 'lines a script picks by number at run time'],
    ['Dialogue — scenes', 'Scene dialogue', 'every line with a speaker, in the field and in cutscenes'],
    ['Dialogue — battle scenes', 'Battle dialogue', 'what is said during battles'],
    ['Movie subtitles', 'Movie subtitles', 'the pre-rendered movies, each disc its own'],
    ['Event subtitles', 'Event subtitles', null],
    ['Battle voice subtitles', 'Battle voice subtitles', null],
    ['Story recap messages', 'Episode I & II recap', 'the summaries of the first two games'],
    ['Scene text without a speaker — scenes', 'Other scene text', 'choices, signs, system lines and the scripts\' own prints'],
    ['Scene text without a speaker — battle scenes', 'Other battle-scene text', null],
    ['Keywords townspeople wait for', 'Keywords (follow their line)', 'locked: a build writes each from the <k...> word of its line'],
    ['Debug prints', 'Debug prints (never shown)', 'what the scripts hand to the developers\' debug print'],
    ['Script identifiers', 'Script identifiers', 'labels, voice ids and file names the scripts use'],
    ['Unused strings', 'Unused strings', null]]],
  ['Menus & system', [
    ['Menu text', 'Menus, synopsis & system messages', null]]],
  ['Database, items & battle', [
    ['Database & menu tables', 'Database & menu tables', 'the encyclopedia, items, skills, segment files'],
    ['Battle names & descriptions', 'Battle names & descriptions', 'characters, enemies, attacks, items in battle']]],
  ['Mini-game', [
    ['HaKox mini-game', 'HaKox', null]]],
];
const CAT_NAME = new Map(), CAT_SUB = new Map();
SECTIONS.forEach(([, cs]) => cs.forEach(([c, n, sub]) => { CAT_NAME.set(c, n); if (sub) CAT_SUB.set(c, sub); }));
function catName(c) { return (S.treeView === 'file' || !c) ? c : (CAT_NAME.get(c) || c); }
const SPK_KEY = '\u0002spk\u0000';
function isSpkKey(k) { return !!k && k.startsWith(SPK_KEY); }
function spkOf(k) { return k.slice(SPK_KEY.length); }
function nodeLabel(cat) { return isSpkKey(cat) ? spkOf(cat) : catName(cat); }
function treeHead() {
  const v = (id, label, tip) => h('button', {class: S.treeView === id ? 'on' : '', text: label, title: tip,
    onclick: () => setTreeView(id)});
  return h('div', {class: 'thead'},
    h('div', {class: 'colhead'}, h('h3', {text: 'Where in the game'})),
    S.rows.length ? h('div', {class: 'tviews', role: 'tablist'},
      v('type', 'By type', 'Story, menus, database and battle text, the mini-game'),
      v('speaker', 'By speaker', 'Every dialogue line under the character who says it'),
      v('file', 'By file', 'The categories as the disc stores them')) : null);
}
function setTreeView(v) {
  if (S.treeView === v) return;
  S.treeView = v; store('treeView', v);
  if (isSpkKey(S.sel.cat) !== (v === 'speaker')) S.sel = {cat: null, grp: null};
  renderTree(); refreshView(true);
}
// Speakers: the name-box text of each dialogue line. Cutscenes often pass the
// Japanese name (【シオン】): it is shown under the English label the USA disc
// gives the same speaker (SPK_JA). Different spellings of one name in
// different case are one speaker, shown in the spelling used most.
function spkName(ctx) {
  let n = (ctx || '').trim().replace(/^【(.*)】$/, '$1');
  if (!n) return '';
  const k = n.normalize('NFKC').replace(/−/g, '-');
  return SPK_JA[k] || k;
}
function indexSpeakers() {
  const by = new Map(), spell = new Map();
  for (const r of S.rows) {
    if (r.fam !== 'sb' || !/^Dialogue/.test(r.cat)) continue;
    const n = spkName(r.ctx);
    const low = n.toLowerCase();
    let sp = spell.get(low); if (!sp) spell.set(low, sp = new Map());
    sp.set(n, (sp.get(n) || 0) + 1);
    let a = by.get(low); if (!a) by.set(low, a = []); a.push(r);
  }
  const official = new Set(Object.values(SPK_JA));
  S.spk = [];
  for (const [low, rows] of by) {
    const sp = [...spell.get(low).entries()].sort((a, b) => (official.has(b[0]) - official.has(a[0])) || (b[1] - a[1]));
    const name = low ? sp[0][0] : 'No name shown';
    const key = SPK_KEY + name;
    rows.sort((a, b) => (a._c - b._c) || (a._g - b._g) || ((a.ord || 0) - (b.ord || 0)) || (a._i - b._i));
    S.nodeRows.set(key, rows);
    const groups = [], seen = new Set();
    for (const r of rows) {
      const g = r.grp.split(' / ')[0];
      if (!seen.has(g)) { seen.add(g); groups.push(g); S.nodeRows.set(key + '\u0000' + g, []); }
      S.nodeRows.get(key + '\u0000' + g).push(r);
    }
    S.spk.push({key, name, n: rows.length, groups, none: !low});
  }
  S.spk.sort((a, b) => (a.none - b.none) || (b.n - a.n) || a.name.localeCompare(b.name));
}
let treeT = null;
function renderTreeSoon() { clearTimeout(treeT); treeT = setTimeout(() => { renderTree(); updateSteps(); }, 250); }
function renderTree() {
  const tree = $('tree');
  if (!S.rows.length) { tree.replaceChildren(treeHead(), h('div', {class: 'tree-empty', text: 'No rows in the catalog.'})); return; }
  const nodes = [treeHead()];
  const node = (cls, label, list, onclick, sel, chev, hint) => {
    const [d, t] = counts(list);
    const pct = t ? (100 * d / t) : 0;
    const full = label + (hint ? ' — ' + hint : '');
    return h('div', {class: 'tn ' + cls + (sel ? ' sel' : '') + (t ? '' : ' zero'), onclick,
      title: t ? full : full + ' (nothing editable: every line is locked' + (S.showHidden ? '' : ' or hidden') + ')'},
      h('span', {class: 'chev', text: chev || ''}), h('span', {class: 'lbl'}, label, hint ? h('span', {class: 'hint', text: hint}) : null),
      h('span', {class: 'cnt' + (t && d === t ? ' done' : ''), text: fmtN(d) + '/' + fmtN(t)}),
      h('span', {class: 'bar'}, h('i', {style: 'width:' + pct.toFixed(1) + '%'})));
  };
  nodes.push(node('all', 'All text', S.rows, () => selectNode(null, null), !S.sel.cat));
  if (S.treeView === 'speaker') { renderSpeakerNodes(nodes, node); }
  else {
    const byCat = new Map(S.cats.map(c => [c.cat, c]));
    const catNode = (c) => {
      const open = S.open.has(c.cat);
      const sub = S.treeView === 'type' ? CAT_SUB.get(c.cat) : null;
      const el = node('cat' + (open ? ' open' : ''), catName(c.cat), S.nodeRows.get(c.cat) || [],
        (e) => { if (e.target.classList.contains('chev') || (S.sel.cat === c.cat && !S.sel.grp)) toggleCat(c.cat); else { S.open.add(c.cat); selectNode(c.cat, null); } },
        S.sel.cat === c.cat && !S.sel.grp, '▶');
      if (sub) el.querySelector('.lbl').appendChild(h('span', {class: 'sm2', text: sub}));
      nodes.push(el);
      if (open) groupNodes(c);
    };
    const groupNodes = (c) => {
      // a category can have thousands of groups (cutscenes: 4,311 with hidden rows);
      // draw the first GRP_STEP and a "more" node, keeping the selected group visible
      const lim = S.grpShow.get(c.cat) || GRP_STEP;
      let shown = 0, more = 0;
      for (const g of c.groups) {
        const list = S.nodeRows.get(c.cat + '\u0000' + g.grp) || [];
        if (!list.length || (!S.showHidden && list.every(r => r.hide))) continue;
        const isSel = S.sel.cat === c.cat && S.sel.grp === g.grp;
        if (shown >= lim && !isSel) { more++; continue; }
        shown++;
        nodes.push(node('grp', g.grp, list, () => selectNode(c.cat, g.grp), isSel, null, groupHint(list)));
      }
      if (more) nodes.push(h('div', {class: 'tn grp more', title: 'draw more groups of ' + c.cat,
        onclick: () => { S.grpShow.set(c.cat, lim + 4 * GRP_STEP); renderTree(); }},
        h('span', {class: 'chev'}), h('span', {class: 'lbl', text: '+ ' + fmtN(more) + ' more groups…'}), h('span')));
    };
    if (S.treeView === 'file') S.cats.forEach(catNode);
    else {
      const placed = new Set();
      for (const [title, cs] of SECTIONS) {
        const here = cs.map(x => byCat.get(x[0])).filter(Boolean);
        if (!here.length) continue;
        nodes.push(h('div', {class: 'tsec', text: title}));
        here.forEach(c => { placed.add(c.cat); catNode(c); });
      }
      const rest = S.cats.filter(c => !placed.has(c.cat));
      if (rest.length) { nodes.push(h('div', {class: 'tsec', text: 'Other'})); rest.forEach(catNode); }
    }
  }
  const st = tree.scrollTop; tree.replaceChildren(...nodes); tree.scrollTop = st;
}
// a few words of what a group holds, next to its id (umn/0003, OV01 bltNameTbl…):
// a mail's subject, otherwise its first visible line
function groupHint(list) {
  const r = list.find(x => x.ctx === 'subject' && isVisibleRow(x)) ||
            list.find(x => !x.lock && isVisibleRow(x)) || list.find(isVisibleRow);
  if (!r) return '';
  const t = listText(r.src).replace(/⟦…⟧/g, '').trim();
  return t.length > 40 ? t.slice(0, 40) + '…' : t;
}
function renderSpeakerNodes(nodes, node) {
  nodes.push(h('div', {class: 'tnote', text: 'Every line of cutscene and field dialogue, under the name in its name box. Click a name to see all their lines; open it to go scene by scene.'}));
  let shown = 0;
  for (const sp of S.spk) {
    const list = S.nodeRows.get(sp.key) || [];
    if (!S.showHidden && list.every(r => r.hide)) continue;
    const isSel = S.sel.cat === sp.key;
    if (shown >= S.spkShow && !isSel) continue;
    shown++;
    const open = S.open.has(sp.key);
    nodes.push(node('cat spk' + (open ? ' open' : ''), sp.name, list,
      (e) => { if (e.target.classList.contains('chev') || (isSel && !S.sel.grp)) toggleCat(sp.key); else { S.open.add(sp.key); selectNode(sp.key, null); } },
      isSel && !S.sel.grp, '▶', sp.none ? 'narration, signs, system' : null));
    if (open) for (const g of sp.groups) {
      const gl = S.nodeRows.get(sp.key + '\u0000' + g) || [];
      if (!S.showHidden && gl.every(r => r.hide)) continue;
      nodes.push(node('grp', g, gl, () => selectNode(sp.key, g), isSel && S.sel.grp === g, null, groupHint(gl)));
    }
  }
  const left = S.spk.length - shown;
  if (left > 0) nodes.push(h('div', {class: 'tn grp more', onclick: () => { S.spkShow += 200; renderTree(); }},
    h('span', {class: 'chev'}), h('span', {class: 'lbl', text: '+ ' + fmtN(left) + ' more speakers…'}), h('span')));
}
function setAdvanced(on, quiet) {
  S.adv = !!on; $('advanced').checked = S.adv; document.body.classList.toggle('adv', S.adv);
  if (quiet) return;
  store('adv', S.adv);
  if (S.adv && S.showHidden && S.hidden && !S.hidden.loaded) loadHidden();
  if (S.rows.length) { renderTree(); refreshView(false); renderEditor(); updateBuildSummary(); }
}
function toggleCat(cat) { if (S.open.has(cat)) S.open.delete(cat); else S.open.add(cat); renderTree(); }
function selectNode(cat, grp) {
  const t0 = performance.now();
  S.sel = {cat, grp};
  if ($('search').value) { $('search').value = ''; S.search = ''; }
  renderTree(); refreshView(true);
  perf('select ' + (nodeLabel(cat) || 'All text') + (grp ? ' › ' + grp : '') + ': ' + fmtN(S.view.length) + ' rows in ' +
       (performance.now() - t0).toFixed(1) + ' ms');
  // highlight the first line still to do, so the editor shows something right away
  if (grp && S.view.length) {
    const first = S.view.find(r => !r.lock && !trOf(r.id)) || S.view.find(r => !r.lock) || S.view[0];
    selectRow(first.id, {focus: true});
  }
}

// ------------------------------------------------------------------ list (middle column)
function baseRows() {
  if (S.search) return S.rows;
  if (!S.sel.cat) return S.rows;
  return S.nodeRows.get(S.sel.grp ? S.sel.cat + '\u0000' + S.sel.grp : S.sel.cat) || [];
}
function passes(r) {
  if (!isVisibleRow(r)) return false;
  const t = trOf(r.id);
  switch (S.filter) {
    case 'untranslated': if (t || r.lock) return false; break;
    case 'translated': if (!t) return false; break;
    case 'problems': { const c = S.checks.get(r.id); if (!t || !c || !(c.errors.length || c.warnings.length)) return false; break; }
    case 'errors': { const c = S.checks.get(r.id); if (!t || !c || !c.errors.length) return false; break; }
    case 'warnings': { const c = S.checks.get(r.id); if (!t || !c || !c.warnings.length) return false; break; }
  }
  if (S.search) {
    const q = S.search;
    if (r._lc === undefined) r._lc = (r.src + '\u0001' + r.id + '\u0001' + (r.ctx || '') + '\u0001' + jaOf(r)).toLowerCase();
    if (r._lc.indexOf(q) < 0 && !(t && t.text.toLowerCase().indexOf(q) >= 0)) return false;
  }
  return true;
}
function refreshView(resetScroll) {
  S.view = baseRows().filter(passes);
  S.viewIdx = new Map();
  S.view.forEach((r, i) => S.viewIdx.set(r.id, i));
  const where = S.search ? 'Search “' + S.search + '” (all categories)' :
    !S.sel.cat ? 'All text' : S.sel.grp ? nodeLabel(S.sel.cat) + '  ›  ' + S.sel.grp : nodeLabel(S.sel.cat);
  $('where').textContent = where;
  $('rowcount').textContent = S.rows.length ? plural(S.view.length, 'line') : '';
  const grpOk = !!S.sel.grp && !S.search;
  $('btn-copygrp').disabled = $('btn-pastegrp').disabled = !grpOk;
  $('btn-copygrp').title = $('btn-pastegrp').title = grpOk ? '' : 'Pick one group on the left first (a map, a cutscene, a mail…)';
  if (resetScroll) $('list').scrollTop = 0;
  renderLines();
  // the highlighted line just got hidden (show hidden turned off): let it go
  const cr = S.cur && S.byId.get(S.cur);
  if (S.cur && (!cr || !isVisibleRow(cr))) { S.cur = null; renderEditor(); }
}
const lspacer = h('div', {id: 'lspacer'});
let winStart = -1, winEnd = -1;
function renderLines() {
  const L = $('list');
  if (!S.rows.length) { L.replaceChildren(listEmpty()); return; }
  if (!S.view.length) {
    L.replaceChildren(h('div', {class: 'empty'},
      h('div', {text: S.search ? 'No line matches “' + S.search + '”.' : S.filter !== 'all' ? 'No line here matches the filter.' : 'Nothing to show here.'}),
      S.filter !== 'all' ? h('div', {style: 'margin-top:10px'}, h('button', {class: 'ghost sm', text: 'Show all lines',
        onclick: () => { $('filter').value = 'all'; S.filter = 'all'; refreshView(true); }})) : null));
    winStart = winEnd = -1;
    return;
  }
  if (lspacer.parentNode !== L) L.replaceChildren(lspacer);
  lspacer.style.height = (S.view.length * ROWH) + 'px';
  renderWindow(true);
}
function renderWindow(force) {
  const L = $('list');
  if (lspacer.parentNode !== L) return;
  const top = L.scrollTop, hgt = L.clientHeight || 600;
  const start = Math.max(0, Math.floor(top / ROWH) - 6);
  const end = Math.min(S.view.length, Math.ceil((top + hgt) / ROWH) + 6);
  if (!force && start === winStart && end === winEnd) return;
  winStart = start; winEnd = end;
  const els = [];
  for (let i = start; i < end; i++) els.push(listRowEl(S.view[i], i));
  lspacer.replaceChildren(...els);
}
function statusOf(r) {
  if (r.lock) return ['lock', 'locked: ' + r.lock];
  const t = trOf(r.id);
  if (!t) {
    if (!S.proj && S.pending && S.pending[r.id]) return ['draft', 'typed, not saved yet: create a project (step 2)'];
    return ['', 'untranslated'];
  }
  const c = S.checks.get(r.id);
  if (c && c.errors.length) return ['err', 'error: ' + c.errors[0]];
  if (c && c.warnings.length) return ['warn', 'warning: ' + c.warnings[0]];
  if (t.state === 'draft') return ['draft', S.tmIds.has(r.id) ? 'draft from translation memory' : 'draft (imported or pasted): edit it to mark it done'];
  return ['ok', c ? 'translated, checks pass' : 'translated'];
}
function listRowEl(r, i) {
  const [st, why] = statusOf(r);
  const t = trOf(r.id);
  const tl = t ? t.text : (!S.proj && S.pending && S.pending[r.id]) || '';
  const showWhere = S.search || !S.sel.grp;
  const cx = S.adv ? [showWhere ? r.grp : '', r.ctx].filter(Boolean).join(' · ')
    : [showWhere && !isSpkKey(S.sel.cat) ? catName(r.cat) : '', simpleCtx(r)].filter(Boolean).join(' · ');
  const cxFull = catName(r.cat) + ' › ' + r.grp + (r.ctx ? ' · ' + r.ctx : '');
  // Japanese source: the Japanese line first, the English as the muted second
  // line (the translation takes that place once there is one)
  const ja = S.ja ? jaOf(r) : '';
  const l1 = ja ? listText(ja) : listText(r.src);
  let l2 = tl ? '→ ' + listText(tl) : r.lock ? 'locked · reference only' : r.hide ? 'hidden · ' + r.hide : '';
  let l2cls = tl ? ' has' + (isRtl() ? ' rtl' : '') : '';
  if (S.ja && !tl) {
    if (ja) { l2 = 'EN · ' + listText(r.src); l2cls = ' en'; }
    else if (!r.lock && !r.hide) { l2 = 'no Japanese for this line'; l2cls = ' en'; }
  }
  return h('div', {class: 'lr' + (r.id === S.cur ? ' sel' : '') + (r.lock ? ' lockd' : ''), 'data-i': i,
      style: 'top:' + (i * ROWH) + 'px'},
    h('i', {class: 'dot ' + st, title: why}),
    h('span', {class: 'tx'},
      h('span', {class: 'l1' + (S.ja && !ja ? ' noja' : ''), text: l1 || ' ', title: (ja || r.src).length > 60 ? (ja || r.src) : null,
        lang: ja ? 'ja' : 'en'}),
      l2 ? h('span', {class: 'l2' + l2cls, text: l2, lang: tl ? (bcp47() || null) : null}) : null),
    cx ? h('span', {class: 'cx', text: cx, title: cxFull}) : h('span'));
}
// Simple mode: who says the line, or which part of a mail; never symbol names
function simpleCtx(r) {
  if (r.fam === 'sb' && /^Dialogue/.test(r.cat)) return isSpkKey(S.sel.cat) ? '' : spkName(r.ctx);
  if (r.fam === 'sub' && r.ctx) return r.ctx;      // a subtitle's time, a recap message's number
  return '';
}
function repaintListRow(id) {
  const i = S.viewIdx.get(id);
  if (i === undefined || i < winStart || i >= winEnd) return;
  const old = lspacer.querySelector('.lr[data-i="' + i + '"]');
  if (old) old.replaceWith(listRowEl(S.view[i], i));
}
function ensureVisible(i) {
  const L = $('list'), y = i * ROWH;
  if (y < L.scrollTop) L.scrollTop = y;
  else if (y + ROWH > L.scrollTop + L.clientHeight) L.scrollTop = y + ROWH - L.clientHeight;
  renderWindow(false);
}
function selectRow(id, opts) {
  const o = opts || {};
  if (S.cur && S.cur !== id && E.ta && S.byId.get(S.cur)) onCommit(S.byId.get(S.cur));
  S.cur = id;
  lspacer.querySelectorAll('.lr.sel').forEach(e => e.classList.remove('sel'));
  const i = S.viewIdx.get(id);
  if (i !== undefined) {
    const el = lspacer.querySelector('.lr[data-i="' + i + '"]'); if (el) el.classList.add('sel');
    if (o.scroll !== false) ensureVisible(i);
  }
  renderEditor();
  if (o.focus) focusBox();
}
// focus the translation box and make sure it is on screen (a long original
// scrolls inside its own card, but a short pane can still hide the box)
function focusBox() {
  if (!E.ta) { $('list').focus({preventScroll: true}); return; }
  const ta = E.ta;
  ta.focus({preventScroll: true});
  requestAnimationFrame(() => { if (ta.isConnected) ta.scrollIntoView({block: 'nearest'}); });
}
function move(d, focus) {
  if (!S.view.length) return;
  let i = (S.cur && S.viewIdx.has(S.cur)) ? S.viewIdx.get(S.cur) + d : (d > 0 ? 0 : S.view.length - 1);
  i = Math.max(0, Math.min(S.view.length - 1, i));
  selectRow(S.view[i].id, {focus});
}
function pageRows() { return Math.max(1, Math.floor(($('list').clientHeight || 480) / ROWH) - 1); }
function listEmpty() {
  return h('div', {class: 'list-empty'}, h('div', {class: 'guide-card'},
    h('span', {class: 'k', text: 'Step 1'}),
    h('span', {class: 'big', text: 'Pick an untouched disc image: Disc 1 or Disc 2.'}),
    h('p', {text: 'Xenosaga Episode III – Also sprach Zarathustra (USA or Japan), as a .iso file. Keep both discs in one folder (or in folders side by side): the editor finds the other one and one project covers both. The images are only ever read; your translation goes into patched copies at the end.'}),
    h('div', {class: 'btns'}, h('button', {text: 'Choose disc…', onclick: pickIso}))));
}

// ------------------------------------------------------------------ editor (right column)
function faceOf(r) {
  const f = r.face || r.measure;
  return f === 'font0' ? 'font0' : 'font1';
}
function fontLabel(r) {
  if (r.font === 'note') return 'Never drawn by the game (a developers\' note or a script command): the text only has to fit its encoding';
  return 'The game font (font0.bin / font1.bin of this disc)';
}
function howTo() {
  return h('div', {class: 'howto'},
    h('h3', {text: 'How it works'}),
    h('ol', null,
      h('li', null, h('div', null, 'Choose what to translate on the left. ', h('span', {text: 'By type (story, menus, database, battle text…), by speaker (everything one character says), or by file.'}))),
      h('li', null, h('div', null, 'Click a line in the middle list. ', h('span', {text: 'Or move with ↑ ↓. The original appears here.'}))),
      h('li', null, h('div', null, 'Type the translation in the box under it. ', h('span', {text: 'It saves by itself. The checker and a preview in the game\'s own font update as you type. Ctrl/Cmd+Enter saves and goes to the next line.'}))),
      h('li', null, h('div', null, 'Press Build (step 4). ', h('span', {text: 'It writes patched copies of the discs into a folder. The original discs are never changed.'})))),
    h('p', {class: 'foot', text: 'Bulk ▾ above the list copies a whole group out for translating elsewhere and pastes it back. Switch on Advanced (top right) for ids, fonts, byte limits, spreadsheets (TSV) and hidden debug text.'}));
}
function editorEmpty() {
  const kids = [];
  if (!S.rows.length) {
    // the middle column carries the Step 1 card; here only the overview
  } else if (!S.proj) {
    kids.push(h('div', {class: 'guide-card'}, h('span', {class: 'k', text: 'Step 2'}),
      h('span', {class: 'big', text: 'Set up your language, then the project is created.'}),
      h('p', {text: 'Any language works: on the USA discs Spanish or Italian need nothing more; French (œ), Polish or Vietnamese borrow a few letters from a font; Cherokee, Arabic, Chinese or Hindi get every letter drawn from a font; a language that is not on the list is set up from a sample sentence. You can translate from the English (USA disc) or from the Japanese (the Japan discs).'}),
      h('div', {class: 'btns'},
        h('button', {text: 'Language setup & new project…', onclick: () => openSetup({mode: 'new'})}),
        h('button', {class: 'ghost', text: 'Open a project…', onclick: pickProject}))));
  } else {
    kids.push(h('div', {class: 'guide-card'}, h('span', {class: 'k', text: 'Step 3'}),
      h('span', {class: 'big', text: 'Pick a place on the left, then click a line in the middle list.'}),
      h('p', {text: 'You are translating ' + srcName() + ' into ' + langFull() + (S.fontLabel ? ' (letters the game lacks drawn from ' + S.fontLabel + ')' : '') +
        ' · ' + basename(S.projPath) + '. Step 2 changes the language setup.'})));
  }
  kids.push(howTo());
  return kids;
}
function renderEditor() {
  const ed = $('edcol');
  const r = S.cur && S.byId.get(S.cur);
  E.ta = E.st = E.pvO = E.pvT = E.tmBox = E.tags = null; E.gen++;
  if (!r) { ed.replaceChildren(...editorEmpty()); return; }
  const t = trOf(r.id);

  const chips = h('span', {class: 'chips'});
  if (r.font !== 'field') chips.appendChild(h('span', {class: 'tag font', text: r.font === 'battle' ? 'battle font' : r.font === 'note' ? 'never drawn' : 'ASCII only'}));
  if (r.dup) chips.appendChild(h('span', {class: 'tag', text: '×' + (r.dup + 1), title: r.dup + ' other line(s) have this exact original text'}));
  if (r.hide) chips.appendChild(h('span', {class: 'tag hide', text: 'hidden', title: 'hidden by default: ' + r.hide}));
  if (r.lock) chips.appendChild(h('span', {class: 'tag lock', text: 'locked'}));
  // the USA disc's game text is English; kana/kanji lines are leftovers from development
  const ja = JA_RE.test(r.src);
  if (ja && (S.display !== 'jp' || r.hide)) chips.appendChild(h('span', {class: 'tag hide', text: r.hide ? 'developer debug text' : 'Japanese',
    title: 'Japanese text' + (r.hide ? ' (developers\' text; players never see it)' : '')}));

  const lims = [];
  const dlg = r.fam === 'sb' && /^Dialogue/.test(r.cat);
  if (r.lim != null) lims.push('at most ' + fmtN(r.lim) + ' bytes (the game copies a page into a 16 KB work area without checking)');
  if (r.px) lims.push('width guide ' + r.px + ' px ' + (r.px === 426 ? '(a townsperson\'s balloon: the game does not wrap, and a wider line runs past the 512 px screen)' : '(the game does not wrap: a wider line makes its window wider than the 512 px screen)'));
  const facts = h('dl', {class: 'facts'},
    h('dt', {text: 'Where'}), h('dd', {text: catName(r.cat) + '  ›  ' + r.grp}),
    dlg && spkName(r.ctx) ? h('dt', {text: 'Speaker'}) : null, dlg && spkName(r.ctx) ? h('dd', {class: 'ctx', text: spkName(r.ctx) + (S.adv && spkName(r.ctx) !== r.ctx ? '  (' + r.ctx + ')' : '')}) : null,
    !dlg && r.ctx ? h('dt', {class: 'advonly', text: 'Context'}) : null, !dlg && r.ctx ? h('dd', {class: 'ctx advonly', text: r.ctx}) : null,
    h('dt', {class: 'advonly', text: 'Font'}), h('dd', {class: 'advonly', text: fontLabel(r)}),
    h('dt', {class: lims.length ? '' : 'advonly', text: 'Limits'}), h('dd', {class: lims.length ? '' : 'advonly', text: lims.length ? lims.join(' · ') : 'none known: no box width or buffer size is traced for this kind of text, so the text can grow; compare it with the original\'s length'}),
    r.hide && r.hide !== r.lock ? h('dt', {text: 'Hidden'}) : null, r.hide && r.hide !== r.lock ? h('dd', {text: r.hide}) : null,
    h('dt', {class: 'advonly', text: 'Id'}), h('dd', {class: 'advonly'}, h('span', {class: 'idv', text: r.id, title: 'click to copy the id',
      onclick: async () => { if (await copyText(r.id)) toast('Copied ' + r.id); }})));
  // Japanese source: the Japan disc's line large, the USA English beneath
  // as reference (the row, its codes and the build stay keyed to the USA disc)
  const jtext = S.ja ? jaOf(r) : '';
  const partial = !!(jtext && S.ja.partial.has(r.id));
  if (partial) chips.appendChild(h('span', {class: 'tag tm', text: 'whole message',
    title: 'The two builds time their subtitles differently, so this English cue shows the Japanese cue(s) on screen at the same time'}));
  const shown = jtext || r.src;
  const ot = h('div', {class: 'origtext clip' + (jtext ? ' ja' : ''), lang: jtext ? 'ja' : 'en'}, renderSrc(shown));
  const more = h('div', {class: 'origmore', hidden: true});
  const label = jtext ? 'Original · Japanese (Japan discs)' : 'Original · ' + (ja || S.display === 'jp' ? 'Japanese' : 'English');
  const orig = h('section', {class: 'card'},
    h('div', {class: 'chead'}, h('h3', {text: label}), chips, h('span', {class: 'grow'}),
      h('button', {class: 'mini', text: 'Copy original', title: 'copy the original as shown (codes included)',
        onclick: async () => { if (await copyText(shown)) toast('Original copied'); }})),
    ot, more,
    S.ja && !jtext && !ja ? h('div', {class: 'noja', text: 'no Japanese paired with this line: the English is shown'}) : null,
    jtext ? h('div', {class: 'refcard'}, h('div', {class: 'rl', text: 'English (USA) · reference'}),
      h('div', {class: 'origtext', lang: 'en'}, renderSrc(r.src))) : null,
    hasTokens(r.src) ? h('div', {class: 'toknote', text: 'The coloured chips are game codes (colours, pauses, names, numbers): keep each one in your translation' +
      (jtext ? ', as the English (USA) line has them.' : '.')}) : null,
    facts);

  const kids = [orig];
  requestAnimationFrame(() => clipOriginal(ot, more));
  if (r.lock) {
    kids.push(h('section', {class: 'locked'}, h('h4', {text: 'Locked — reference only'}),
      h('p', {class: 'why', text: r.lock}),
      h('p', {text: 'Changing this would break the game rather than translate it, so it has no translation box.'}),
      h('div', {class: 'edbar', style: 'margin-top:10px'}, navButtons(r))));
    ed.replaceChildren(...kids);
    ed.scrollTop = 0;
    return;
  }

  const ta = h('textarea', {id: 'ta', class: 'tl' + (t && t.state === 'draft' ? ' draft' : ''), spellcheck: 'true',
    lang: bcp47() || null, dir: isRtl() ? 'rtl' : 'auto', placeholder: 'Type the ' + langLabel() + ' translation here…'});
  ta.value = t ? t.text : (S.pending && S.pending[r.id]) || '';
  ta.addEventListener('input', () => onEdit(r, ta));
  ta.addEventListener('change', () => onCommit(r));
  ta.addEventListener('keydown', (e) => onTaKey(e, r));
  E.ta = ta;
  E.tags = h('span', {class: 'chips'});
  paintTags(r);
  E.st = h('div', {class: 'st'});
  const sec = h('section', {class: 'tlsec'},
    h('label', {class: 'talabel', for: 'ta'}, 'Translation — ', h('span', {class: 'ln', text: langLabel()}), E.tags),
    !S.proj ? h('div', {class: 'noproj'}, 'No project yet: what you type is kept and goes into the project when you create one.',
      h('button', {class: 'sm', text: 'New project…', onclick: () => openSetup({mode: 'new'})}),
      h('button', {class: 'sm ghost', text: 'Open…', onclick: pickProject})) : null,
    ta, E.st,
    h('div', {class: 'edbar'}, navButtons(r), h('span', {class: 'grow'}),
      h('button', {class: 'ghost sm', text: S.ja ? 'Use English' : 'Use original', title: 'start from the English text (keeps every code)', onclick: () => {
        ta.value = r.src; onEdit(r, ta); onCommit(r); ta.focus(); }}),
      h('button', {class: 'ghost sm', text: 'Clear', title: 'remove this translation', onclick: () => {
        ta.value = ''; onEdit(r, ta); ta.focus(); }})),
    h('div', {class: 'edbar'}, h('span', {class: 'hint', text: enterHint(r)})));
  E.tmBox = h('div');
  sec.appendChild(E.tmBox);
  paintTm(r);
  kids.push(sec);

  E.pvO = h('div', {class: 'pv', hidden: true}); E.pvT = h('div', {class: 'pv', hidden: true});
  kids.push(h('section', {class: 'pvsec'}, h('h4', null, 'Preview in the game ', h('small', {text: '· drawn with the game\'s own font' +
    (needsFont(S.target) ? (S.fontLabel ? ' and ' + S.fontLabel + ' for the new letters' : autoFont(S.lang) ? ' and ' + autoFontLabel() + ' for the few new letters' : ' (choose a font in step 2 for the new letters)') : '') +
    ' (click to zoom)'})), E.pvO, E.pvT));
  ed.replaceChildren(...kids);
  ed.scrollTop = 0;
  paintStatus(E.st, r);
  requestAnimationFrame(() => autoGrow(ta));
  renderPreviews();
}
const JA_RE = /[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]/;
// a long original (mail, database entry) scrolls inside its card, with a
// "Show all" toggle, so the translation box below it stays on screen
function clipOriginal(ot, more) {
  if (!ot.isConnected) return;
  const over = ot.scrollHeight > ot.clientHeight + 4;
  if (!over) { ot.classList.remove('clip'); more.hidden = true; return; }
  const cr = S.byId.get(S.cur) || {src: ''};
  const lines = ((S.ja && jaOf(cr)) || cr.src).split('\n').length;
  const btn = h('button', {class: 'mini', text: 'Show all (' + plural(lines, 'line') + ')'});
  btn.addEventListener('click', () => {
    const clipped = ot.classList.toggle('clip');
    btn.textContent = clipped ? 'Show all (' + plural(lines, 'line') + ')' : 'Show less';
  });
  ot.addEventListener('scroll', () => ot.classList.toggle('end', ot.scrollTop + ot.clientHeight >= ot.scrollHeight - 2));
  more.replaceChildren(btn); more.hidden = false;
}
function navButtons(r) {
  const i = S.viewIdx.get(r.id);
  return [h('button', {class: 'ghost sm', text: '‹ Prev', disabled: i === 0 || !S.view.length, title: 'previous line (Alt+↑)',
            onclick: () => { onCommit(r); move(-1, true); }}),
          h('button', {class: 'sm', text: 'Next ›', disabled: i !== undefined && i >= S.view.length - 1, title: 'next line (Ctrl/Cmd+Enter)',
            onclick: () => { onCommit(r); move(1, true); }})];
}
function paintTags(r) {
  if (!E.tags) return;
  const t = trOf(r.id);
  E.tags.replaceChildren();
  if (S.tmIds.has(r.id)) E.tags.appendChild(h('span', {class: 'tag tm', text: 'TM draft', title: 'filled from an identical original line. Drafts are built into the ISO like any translation; Accept (or any edit) marks it checked.'}));
  else if (t && t.state === 'draft') E.tags.appendChild(h('span', {class: 'tag draft', text: 'draft', title: 'imported, pasted or filled by translation memory. Drafts are built into the ISO like any translation; Accept (or any edit) marks it checked.'}));
  if (t && t.state === 'draft' && S.proj) E.tags.appendChild(h('button', {class: 'mini', type: 'button', text: 'Accept draft',
    title: 'mark this draft as checked by you (drafts are built into the ISO either way)',
    onclick: (e) => { e.preventDefault(); acceptDraft(r); }}));
  if (E.ta) E.ta.classList.toggle('draft', !!(t && t.state === 'draft'));
}
function copiesTxt(n) { return fmtN(n) + ' other cop' + (n === 1 ? 'y' : 'ies'); }
function acceptDraft(r) {
  const t = trOf(r.id); if (!t || t.state !== 'draft') return;
  setTr(r.id, t.text, 'done');
  markDirty(); repaintRow(r.id); paintTm(r); renderTreeSoon(); updateBuildSummary();
  toast('Draft accepted');
}
function paintTm(r) {
  if (!E.tmBox) return;
  const sib = (S.srcIds.get(r.src) || []).filter(o => o !== r.id);
  if (!sib.length) { E.tmBox.replaceChildren(); return; }
  const cur = E.ta ? E.ta.value : ((trOf(r.id) || {}).text || '');
  // what moving on would do, counted from the siblings as they are now
  let untr = 0, same = 0, tmOld = 0, own = 0;
  for (const o of sib) {
    const ot = trOf(o);
    if (!ot) untr++;
    else if (cur && ot.text === cur) same++;
    else if (S.tmIds.has(o)) tmOld++;
    else own++;
  }
  const parts = [];
  const english = S.display === 'jp' ? 'text' : JA_RE.test(r.src) ? 'text' : 'English';
  if (!S.tm) parts.push(h('span', {class: 'off', text: 'Same ' + english + ' appears ' + plural(sib.length, 'more time') + '; translation memory is off, so each keeps its own text.'}));
  else {
    const fill = untr + tmOld;
    if (cur && fill) parts.push(h('span', {text: copiesTxt(fill) + ' of this ' + english +
      ' will get this translation (as a draft) when you move on' + (tmOld ? ' (' + tmOld + ' replacing an earlier memory draft)' : '') + '. '}));
    else if (!cur && untr) parts.push(h('span', {text: 'Same ' + english + ' appears ' + plural(sib.length, 'more time') + ': type a translation and the ' + untr + ' untranslated one' + (untr === 1 ? '' : 's') + ' will get it as a draft. '}));
    if (same) parts.push(h('span', {text: copiesTxt(same) + ' already use' + (same === 1 ? 's' : '') + ' this translation. '}));
    if (own) parts.push(h('span', {class: 'off', text: own + ' with a different translation of ' + (own === 1 ? 'its' : 'their') + ' own keep' + (own === 1 ? 's' : '') + ' it.'}));
    if (!parts.length) parts.push(h('span', {text: 'Same ' + english + ' appears ' + plural(sib.length, 'more time') + '.'}));
  }
  const cb = h('input', {type: 'checkbox'}); cb.checked = S.tm;
  cb.addEventListener('change', () => { setTm(cb.checked); paintTm(r); });
  E.tmBox.replaceChildren(h('label', {class: 'tmline', title: 'translation memory: identical lines share a translation (also in Bulk ▾). Drafts are built into the ISO too.'}, cb,
    h('span', null, ...parts)));
}
function setTm(on) { S.tm = on; $('tm').checked = on; store('tm', on); }
function autoGrow(ta) {
  if (!ta.isConnected) return;
  ta.style.height = 'auto';
  ta.style.height = Math.max(110, ta.scrollHeight + 2) + 'px';
}
function paintStatus(st, r) {
  if (!st) return;
  const t = trOf(r.id);
  st.replaceChildren();
  if (!t) {
    const typed = !S.proj && S.pending && S.pending[r.id];
    st.appendChild(h('span', {class: 'dim', text: typed ? 'typed, not saved yet (no project): the checker starts once a project is open' : (S.proj ? 'Not translated yet. The checker runs as you type.' : 'Not translated yet. The checker runs as you type once a project is open (step 2).')}));
    if (r.lim != null) st.appendChild(h('span', {class: 'num', text: 'limit ' + r.lim + ' B'}));
    if (r.px) st.appendChild(h('span', {class: 'num', text: 'guide ' + r.px + ' px'}));
    return;
  }
  const c = S.checks.get(r.id);
  if (!c) { st.appendChild(h('span', {class: 'badge wait', text: 'checking'})); return; }
  const kind = c.errors.length ? 'err' : c.warnings.length ? 'warn' : 'ok';
  st.appendChild(h('span', {class: 'badge ' + kind, text: kind === 'err' ? 'error' : kind === 'warn' ? 'warning' : 'ok'}));
  if (c.nbytes != null) {
    const over = r.lim != null && c.nbytes > r.lim, near = r.lim != null && c.nbytes > r.lim * 0.9;
    st.appendChild(h('span', {class: 'num' + (over ? ' over' : near ? ' near' : ''),
      text: c.nbytes + (r.lim != null ? ' / ' + r.lim : '') + ' bytes'}));
  }
  if (c.px != null) {
    const over = r.px && c.px > r.px;
    st.appendChild(h('span', {class: 'num' + (over ? ' over' : ''), text: c.px + (r.px ? ' / ' + r.px : '') + ' px wide'}));
  }
  if (c.len_pct != null && c.len_pct !== 100) {
    st.appendChild(h('span', {class: 'num' + (c.len_pct > 150 ? ' near' : ''), text: c.len_pct + '% of the original\'s length',
      title: 'How long your text is when drawn, against the original (100% = the same). There is no fixed limit here, but text much longer than the original may not fit its box.'}));
  }
  if (c.wide && id_isCur(r.id)) {
    st.appendChild(h('button', {class: 'sm', text: 'Wrap to fit', title: 'Break the lines that are wider than the box at a space (Undo: Ctrl/Cmd+Z in the box)',
      onclick: () => wrapToFit(r)}));
  }
  const msgs = c.errors.map(m => h('li', {class: 'e', text: m})).concat(c.warnings.map(m => h('li', {class: 'w', text: m})));
  if (msgs.length) st.appendChild(h('ul', {class: 'msgs', style: 'flex-basis:100%'}, msgs));
}
function id_isCur(id) { return id === S.cur && !!E.ta; }
// "Wrap to fit": the server breaks the lines wider than the row's box at spaces
// (it measures with the game's font). Typed through execCommand where the
// browser has it, so the box's own undo takes it back.
async function wrapToFit(r) {
  const ta = E.ta; if (!ta || S.cur !== r.id) return;
  const before = ta.value;
  let res;
  try { res = await api('/tx/wrap', {id: r.id, text: before, iso: S.iso, target: cleanTarget(S.target), language: langCode()}); }
  catch (e) { toast('Could not wrap: ' + e.message, true); return; }
  if (S.cur !== r.id || ta !== E.ta || ta.value !== before) return;      // moved on or typed meanwhile
  if (!res.changed) { toast('Nothing to wrap: no space to break at'); return; }
  ta.focus(); ta.select();
  let done = false;
  try { done = document.execCommand('insertText', false, res.text); } catch (_) {}
  if (!done || ta.value !== res.text) ta.value = res.text;
  onEdit(r, ta);
}
// a row's data changed (check result, TM fill, merge): list row + editor if shown
function repaintRow(id) {
  repaintListRow(id);
  if (id !== S.cur) return;
  const r = S.byId.get(id), t = trOf(id);
  if (E.ta && document.activeElement !== E.ta) {
    const v = t ? t.text : '';
    if (E.ta.value !== v) { E.ta.value = v; autoGrow(E.ta); schedulePreview(); }
  }
  paintTags(r); paintStatus(E.st, r); paintTm(r);
}

// ------------------------------------------------------------------ editing
function onEdit(r, ta) {
  autoGrow(ta);
  if (!S.proj) {
    // keep what was typed; it goes into the project once one is created or opened
    S.pending = S.pending || {};
    S.pending[r.id] = ta.value;
    ensureProjectFirst();
    repaintListRow(r.id); paintStatus(E.st, r); paintTm(r); schedulePreview();
    return;
  }
  setTr(r.id, ta.value, 'done');
  S.checks.delete(r.id);
  paintTags(r); paintStatus(E.st, r); paintTm(r);
  queueCheck([r.id]);
  markDirty(); renderTreeSoon(); repaintListRow(r.id); schedulePreview();
}
function onCommit(r) {
  if (!r || !S.proj) return;
  const changed = propagateTm(r.id);
  if (changed.length) {
    changed.forEach(repaintRow); queueCheck(changed); markDirty(); renderTreeSoon();
    toast('Translation memory filled ' + changed.length + ' identical line' + (changed.length > 1 ? 's' : ''));
  }
}
// A line whose original has no line break: Enter confirms and moves on
// (Shift+Enter still breaks the line).
function singleLine(r) { return !/\n/.test(r.src); }
function enterHint(r) {
  return singleLine(r) ? 'Enter: save & next · Shift+Enter: line break · Alt+↑/↓: previous/next · Esc: back to the list'
    : 'Enter: line break · Ctrl/Cmd+Enter: save & next · Alt+↑/↓: previous/next · Esc: back to the list';
}
function onTaKey(e, r) {
  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.isComposing && e.keyCode !== 229 &&
      singleLine(r) && !e.shiftKey) {
    e.preventDefault(); onCommit(r); move(1, true);
  } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault(); onCommit(r); move(1, true);
  } else if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault(); onCommit(r); move(e.key === 'ArrowDown' ? 1 : -1, true);
  }
}

// ------------------------------------------------------------------ checks
let checkQ = new Set(), checkT = null;
function queueCheck(ids) { ids.forEach(i => checkQ.add(i)); clearTimeout(checkT); checkT = setTimeout(flushChecks, 350); }
async function flushChecks() {
  const ids = Array.from(checkQ); checkQ = new Set();
  for (let i = 0; i < ids.length; i += 400) {
    const items = ids.slice(i, i + 400).map(id => ({id, text: (trOf(id) || {}).text || ''})).filter(it => it.text);
    if (!items.length) continue;
    let res;
    try { res = await api('/tx/check', {items, iso: S.iso, target: cleanTarget(S.target), language: langCode()}); }
    catch (e) { toast('Check failed: ' + e.message, true); return; }
    for (const [id, c] of Object.entries(res.results || {})) {
      const cur = trOf(id);
      if (!cur || cur.text !== (items.find(it => it.id === id) || {}).text) continue;
      S.checks.set(id, c); repaintRow(id);
    }
  }
  updateBuildSummary();
  if (S.filter !== 'all' && S.filter !== 'untranslated' && S.filter !== 'translated') renderTreeSoon();
}
async function runAllChecks() {
  if (!S.proj || !S.rows.length) return;
  S.checks = new Map();
  const ids = Object.keys(S.proj.translations).filter(id => S.byId.has(id));
  ids.forEach(id => checkQ.add(id));
  await flushChecks();
  if (S.filter === 'problems' || S.filter === 'errors' || S.filter === 'warnings') refreshView(false);
}
function updateBuildSummary() {
  if (!S.proj) { $('build-sum').textContent = ''; return; }
  const {n, err, warn, drafts} = buildCounts();
  const s = $('build-sum');
  s.textContent = fmtN(n) + ' translated' + (drafts ? ' (' + fmtN(drafts) + ' draft' + (drafts === 1 ? '' : 's') + ', built too)' : '') +
    ' · ' + plural(err, 'error') + ' · ' + plural(warn, 'warning');
  s.className = 'saved' + (err ? ' bad' : '');
}
function buildCounts() {
  let n = 0, err = 0, warn = 0, drafts = 0;
  const errIds = [];
  for (const [id, t] of Object.entries(S.proj ? S.proj.translations : {})) {
    if (!S.byId.has(id)) continue;
    n++; if (t.state === 'draft') drafts++;
    const c = S.checks.get(id);
    if (c && c.errors.length) { err++; errIds.push(id); } else if (c && c.warnings.length) warn++;
  }
  return {n, err, warn, drafts, errIds};
}

// ------------------------------------------------------------------ preview (automatic)
let pvTimer = null;
function schedulePreview() { clearTimeout(pvTimer); pvTimer = setTimeout(renderPreviews, 400); }
async function fetchPreview(r, text) {
  try { return await api('/tx/preview', {id: r.id, text, iso: S.iso, target: cleanTarget(S.target), language: langCode()}); }
  catch (e) { return {error: e.message}; }
}
async function renderPreviews() {
  clearTimeout(pvTimer);
  const r = S.cur && S.byId.get(S.cur);
  if (!r || !E.pvO) return;
  const gen = E.gen, pvO = E.pvO, pvT = E.pvT;
  const text = E.ta ? E.ta.value : '';
  const key = S.iso + '\u0000' + r.id;
  let o = S.pvCache.get(key);
  if (!o) {
    if (pvO.hidden) { pvO.hidden = false; pvO.replaceChildren(h('div', {class: 'cap', text: 'rendering…'})); }
    o = await fetchPreview(r, r.src);
    if (!o.error || !/HTTP 5/.test(o.error)) S.pvCache.set(key, o);
    if (gen !== E.gen) return;
  }
  drawPreview(pvO, r, o, S.ja ? 'Original (English, USA discs)' : 'Original');
  if (o.error) { pvT.hidden = true; return; }   // no font preview for this string at all
  if (!text || text === r.src) { pvT.hidden = true; return; }
  if (pvT.hidden) { pvT.hidden = false; pvT.replaceChildren(h('div', {class: 'cap', text: 'rendering the translation…'})); }
  const res = await fetchPreview(r, text);
  if (gen !== E.gen || !E.ta || E.ta.value !== text) return;
  drawPreview(pvT, r, res, 'Translation');
}
function drawPreview(pv, r, res, label) {
  pv.hidden = false;
  if (res.error) { pv.replaceChildren(h('div', {class: 'cap e', text: label + ': ' + res.error})); return; }
  // the server draws at 2x. By default a preview is shrunk to fit the pane
  // (never enlarged past 1:1 game pixels), so the end of a long line is
  // always in sight; a click shows real size (or 2x when it already fits),
  // with a "scroll" hint when that is wider than the pane. The dashed line
  // is the box width when the row has one.
  const lines = (res.pngs || []).map(src => {
    const img = h('img', {src, alt: label + ' rendered with the game font'});
    img.addEventListener('load', () => { img.dataset.w = img.naturalWidth; layoutPv(pv, r); });
    img.addEventListener('click', () => { E.zoom = !E.zoom; layoutPv(E.pvO, r); layoutPv(E.pvT, r); });
    return h('div', {class: 'pvline'}, img, r.px ? h('span', {class: 'guide', title: 'box width ' + r.px + ' px'}) : null);
  });
  pv.replaceChildren(h('div', {class: 'cap'}, h('b', {text: label}),
      h('span', {class: 'advonly', text: ' · ' + (res.font_label ? res.font_label + ' (' + res.face + ')' : res.face)}),
      (r.px ? ' · dashed line = edge of the screen for this box' : '') +
      (res.warnings && res.warnings.length ? ' · ' + res.warnings.join('; ') : ''), h('span', {class: 'scale'})),
    ...lines, h('div', {class: 'more', hidden: true, text: 'scroll → to see the rest of the line'}));
}
function layoutPv(pv, r) {
  if (!pv || pv.hidden) return;
  const imgs = Array.from(pv.querySelectorAll('img'));
  if (!imgs.length || imgs.some(i => !i.dataset.w)) return;      // wait for every line
  const gw = Math.max(r.px || 0, ...imgs.map(i => i.dataset.w / 2));   // game pixels
  const fit = Math.min(1, Math.max(60, pv.clientWidth - 20) / gw);
  const k = E.zoom ? (fit < 1 ? 1 : 2) : fit;
  pv.classList.toggle('zoom', E.zoom);
  imgs.forEach(i => { i.style.width = (i.dataset.w / 2 * k) + 'px'; i.title = E.zoom ? 'click to fit the pane' : (fit < 1 ? 'click for real size' : 'click to zoom'); });
  pv.querySelectorAll('.guide').forEach(g => { g.style.left = (r.px * k) + 'px'; });
  const sc = pv.querySelector('.scale');
  if (sc) sc.textContent = k < 1 ? ' · shrunk to fit (' + Math.round(k * 100) + '%), click for real size' :
    k === 1 ? ' · 1:1 game pixels, click to zoom' : ' · 2× zoom, click to fit';
  const mo = pv.querySelector('.more');
  if (mo) mo.hidden = !(pv.scrollWidth > pv.clientWidth + 2);
}

// ------------------------------------------------------------------ project
let saveT = null;
function setSaved(text, cls) { const s = $('saved'); s.textContent = text; s.className = 'saved' + (cls ? ' ' + cls : ''); }
// Saving is owned by the project it started for: S.projGen counts project switches
// (adoptProject), S.rev counts edits. A save's reply only touches the project it was
// for, and the project is clean only when the revision it wrote is still the latest.
// Everything that leaves the project (Open, New, Restore, Build) waits on flushSave().
let savePromise = null;
function markDirty() {
  if (!S.proj) return;
  S.dirty = true; S.rev = (S.rev || 0) + 1; setSaved('unsaved', 'dirty');
  clearTimeout(saveT); saveT = setTimeout(saveProject, 1500);
}
// wait for the save in flight, then save what is still unsaved: true when the
// project on disk has every edit (or no project is open)
async function flushSave() {
  clearTimeout(saveT);
  for (let i = 0; i < 4; i++) {
    if (savePromise) { await savePromise.catch(() => {}); continue; }
    if (!S.proj || !S.dirty) return true;
    if (!(await saveProject()) && S.saveErr !== 'conflict') return !S.dirty;   // (a merged conflict saves on the next round)
  }
  return !S.dirty;
}
// the tag in default file names: the code ("FR", "ZH-HANS"), or a custom
// language's own name when it has no code
function langTag() {
  const c = langCode();
  if (c && c !== 'other') return c.toUpperCase();
  return ((S.lang && S.lang.name) || 'XX').replace(/[\\/:*?"<>|]+/g, '').trim() || 'XX';
}
function defaultProjPath() {
  const iso = $('iso').value.trim();
  return iso ? joinp(dirname(iso), stem(iso) + ' (' + langTag() + ').json') : '';
}
function ensureProjectFirst() {
  if (S.proj) return;
  if (S.askedNew) return;          // once is enough; the typing itself is kept in S.pending
  S.askedNew = true;
  toast('No project open yet: press New (step 2) to save your work. What you type is kept and goes into it.', true);
}
async function saveProject() {
  clearTimeout(saveT);
  if (!S.proj || !S.projPath) return false;
  if (savePromise) {             // one save at a time: the next one starts when this one has answered
    await savePromise.catch(() => {});
    return S.dirty ? saveProject() : true;
  }
  const gen = S.projGen, rev = S.rev || 0, path = S.projPath;
  const snapshot = JSON.parse(JSON.stringify(S.proj));
  S.saving = true; setSaved('saving…');
  savePromise = (async () => {
    try {
      const j = await api('/tx/project', {path, project: snapshot, iso: S.iso, mtime: S.projMtime});
      if (gen !== S.projGen) return true;          // another project was opened meanwhile: this reply is not its
      S.projMtime = j.mtime; S.base = snapshot.translations;
      if (j.backup) S.lastBackup = Date.now();
      if (j.backup_error) toast('Saved, but the automatic backup failed: ' + j.backup_error, true);
      S.saveErr = ''; S.saveRetry = 0; S.saveErrMsg = '';
      if ((S.rev || 0) === rev) {
        S.dirty = false;
        setSaved('saved ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}), 'good');
      } else { saveT = setTimeout(saveProject, 400); }   // edits made while saving: save again
      return true;
    } catch (e) {
      if (gen !== S.projGen) { toast('Saving ' + basename(path) + ' failed: ' + e.message, true); return false; }
      S.dirty = true;
      if (e.status === 409 && e.body && e.body.conflict) { S.saveErr = 'conflict'; mergeConflict(e.body); return false; }
      if (e.status === 409 && e.body && e.body.gone) { S.saveErr = 'gone'; setSaved('file gone', 'bad'); offerRecreate(path, gen); return false; }
      // a disk or connection fault: try again by itself, less and less often (5 s … 1 min)
      S.saveErr = 'fail'; setSaved('save failed', 'bad');
      if (S.saveErrMsg !== e.message) toast('Save failed: ' + e.message + ' (trying again by itself)', true);
      S.saveErrMsg = e.message;
      S.saveRetry = Math.min((S.saveRetry || 0) + 1, 4);
      clearTimeout(saveT); saveT = setTimeout(saveProject, [5000, 10000, 20000, 40000, 60000][S.saveRetry]);
      return false;
    }
  })();
  try { return await savePromise; } finally { savePromise = null; S.saving = false; }
}
// The project file was deleted or moved while it was open: it is not written
// back without asking (it may have been moved on purpose), but the work is not
// stuck either: save it again where it was, or keep a copy elsewhere (Backups).
let recreateOpen = false;
function offerRecreate(path, gen) {
  if (recreateOpen || gen !== S.projGen) return;
  recreateOpen = true;
  dialog({title: 'The project file is gone', small: true, onCancel: () => { recreateOpen = false; },
    cancelText: 'Not now',
    body: [h('p', {text: basename(path) + ' was deleted or moved since it was opened here, so your latest edits are only in this page. Save the project again where it was, or keep a copy somewhere else first (Backups → Save a copy elsewhere).'}),
           h('p', {class: 'hint', text: path})],
    buttons: [{text: 'Save it again here', run: async (setMsg) => {
      if (gen !== S.projGen) { recreateOpen = false; return true; }
      try {
        const rev = S.rev || 0, snapshot = JSON.parse(JSON.stringify(S.proj));
        const j = await api('/tx/project', {path, project: snapshot, iso: S.iso, create: true});
        if (gen === S.projGen) {
          S.projMtime = j.mtime; S.base = snapshot.translations; S.saveErr = '';
          if ((S.rev || 0) === rev) { S.dirty = false; setSaved('saved', 'good'); } else markDirty();
        }
        toast('Saved again: ' + basename(path));
        recreateOpen = false; return true;
      } catch (e) { setMsg(e.message, true); return false; }
    }}]});
}
// The file changed elsewhere (another tab, another program) since this tab
// loaded or saved it: take the file as it is now and put back on top only
// what THIS tab changed since then (S.base = the version it last had).
function mergeConflict(body) {
  const merged = JSON.parse(JSON.stringify(body.project));
  const ours = S.proj.translations, base = S.base || {};
  let n = 0;
  for (const id of new Set(Object.keys(ours).concat(Object.keys(base)))) {
    if (JSON.stringify(ours[id] || null) === JSON.stringify(base[id] || null)) continue;
    if (ours[id]) merged.translations[id] = ours[id]; else delete merged.translations[id];
    n++;
  }
  merged.language = S.proj.language;
  ['target', 'source', 'language_name'].forEach(k => { if (S.proj[k] !== undefined) merged[k] = S.proj[k]; });
  S.proj = merged; S.base = JSON.parse(JSON.stringify(body.project.translations)); S.projMtime = body.mtime;
  recomputeTm(); renderTree(); refreshView(false); runAllChecks(); updateBuildSummary(); updateSteps();
  if (S.cur) repaintRow(S.cur);
  toast(basename(S.projPath) + ' was changed elsewhere (another editor tab?). Merged: its translations are kept, ' +
        n + ' edit(s) from this tab go on top.', true);
  markDirty();
}
function adoptProject(path, proj, mtime) {
  // another project (New or Open): the output path and the "disc is ready" note
  // belonged to the previous one; the output goes back to this project's default
  if (path !== S.projPath) {
    delete $('out').dataset.touched;
    $('buildok').classList.remove('show'); $('buildok').replaceChildren();
    if (!building) setBuildBadge('idle');
  }
  S.projGen = (S.projGen || 0) + 1; clearTimeout(saveT);
  S.proj = proj; S.projPath = path; $('proj').value = path; store('proj', path);
  S.projMtime = mtime || null; S.base = JSON.parse(JSON.stringify(proj.translations || {}));
  if (!S.proj.retail_id && S.rid && S.rid !== 'fake') S.proj.retail_id = S.rid;
  // the language (target, font) resolves asynchronously; the checks must run
  // with it, not with the language that was open before
  const langReady = setLangFromProject(proj);
  // lines typed before any project was open
  const pending = Object.entries(S.pending || {}).filter(([, t]) => t);
  S.pending = null;
  pending.forEach(([id, t]) => setTr(id, t, 'done'));
  S.checks = new Map(); recomputeTm(); updateBanner(); updateOutDefault();
  setSaved('saved', 'good'); S.dirty = false;
  if (pending.length) { markDirty(); toast(pending.length + ' line(s) typed earlier added to ' + basename(path)); }
  renderTree(); refreshView(false); renderEditor(); updateBuildSummary(); updateSteps();
  langReady.catch(() => {}).then(() => { if (S.proj === proj) { updateOutDefault(); renderEditor(); runAllChecks().then(updateBuildSummary); } });
  if (projectNeedsHidden()) loadHidden();
}
async function openProject(path) {
  path = (path || '').trim();
  if (!path) { toast('Give a project path', true); return; }
  if (!(await flushSave())) { toast('Your edits to ' + basename(S.projPath) + ' could not be saved, so it stays open. Fix the save (Backups → Save a copy) first.', true); return; }
  try {
    const j = await getJson('/tx/project?path=' + encodeURIComponent(path));
    adoptProject(j.path, j.project, j.mtime);
    toast('Opened ' + basename(j.path) + ' (' + fmtN(Object.keys(j.project.translations).length) + ' translations)');
  } catch (e) { toast(e.message, true); }
}
// New: the Language setup first (openSetup mode "new"), then this: where the
// project file goes. It is created with the setup's language, target and source.
function newProjectDialog(prev) {
  if (!S.rows.length && !TX_FAKE) { toast('Step 1 first: choose the disc', true); return; }
  const inp = h('input', {type: 'text', class: 'path', style: 'width:100%'});
  inp.value = defaultProjPath();
  const browse = h('button', {class: 'pick', text: 'Browse folder', onclick: () => openPicker({mode: 'dir',
    startPath: dirname(inp.value) || dirname($('iso').value), title: 'Folder for the project file',
    onChoose: (d) => { inp.value = joinp(d, basename(inp.value) || ('translation (' + langTag() + ').json')); }})});
  dialog({title: 'New project · ' + srcName() + ' → ' + langFull(), small: true,
    body: [h('p', {text: 'From ' + (srcIsJa() ? 'the Japanese (Japan discs; rows stay keyed to the USA discs)' : 'the text of the discs you opened') + ' into ' + langFull() +
             (S.fontLabel ? ', new letters drawn from ' + S.fontLabel : '') + '. The project is a small JSON file that keeps only your translations and this language setup, keyed to this disc set.'}),
           h('div', {class: 'field'}, inp, browse),
           h('p', null, h('button', {class: 'mini', text: '‹ Back to the Language setup', onclick: () => { closeDialog(); openSetup({mode: 'new', prev}); }}))],
    onCancel: () => { if (prev && S.proj) applySetup(prev, true); },
    buttons: [{text: 'Create', run: async (setMsg) => {
      const p = inp.value.trim();
      if (!p) { setMsg('Give a path', true); return false; }
      try {
        const proj = {format: 1, language: langCode(), retail_id: S.rid && S.rid !== 'fake' ? S.rid : '', translations: {},
                      target: cleanTarget(S.target), language_name: (S.lang && S.lang.name) || '',
                      source: srcIsJa() ? {id: 'ja-jp', path: S.source.path} : {id: 'en-usa'}};
        if (!(await flushSave())) { setMsg('The open project could not be saved; it stays open (Backups → Save a copy)', true); return false; }
        const j = await api('/tx/project', {path: p, create: true, project: proj, iso: S.iso});
        adoptProject(j.path, j.project, j.mtime); toast('Created ' + basename(j.path));
        return true;
      } catch (e) { setMsg(e.message, true); return false; }
    }}]});
}

// ------------------------------------------------------------------ dialogs
let dlgCancel = null;
function dialog({title, body, buttons, wide, small, onCancel, cancelText}) {
  $('dlg-title').textContent = title;
  $('dlg-win').className = 'modal-window' + (wide ? ' wide' : '') + (small ? ' small' : '');
  $('dlg-body').replaceChildren(...body);
  const msg = $('dlg-msg'); msg.textContent = ''; msg.className = 'msg';
  const setMsg = (t, err) => { msg.textContent = t; msg.className = 'msg' + (err ? ' e' : ''); };
  dlgCancel = onCancel || null;
  const btns = [h('button', {class: 'ghost', text: cancelText || 'Cancel', onclick: cancelDialog})];
  for (const b of buttons || []) {
    const el = h('button', {class: b.ghost ? 'ghost' : '', text: b.text});
    el.addEventListener('click', async () => {
      el.disabled = true;
      try { if (await b.run(setMsg, el)) closeDialog(); } finally { el.disabled = false; }
    });
    btns.push(el);
  }
  $('dlg-btns').replaceChildren(...btns);
  $('dlg').hidden = false;
  const f = $('dlg-body').querySelector('textarea, input'); if (f) f.focus();
  return {setMsg};
}
function closeDialog() { dlgCancel = null; $('dlg').hidden = true; $('dlg-body').replaceChildren(); }
function cancelDialog() { const cb = dlgCancel; closeDialog(); if (cb) cb(); }
document.querySelectorAll('[data-dlg-close]').forEach(el => el.addEventListener('click', cancelDialog));

// ------------------------------------------------------------------ group copy / paste
function groupTargets() {
  const list = S.nodeRows.get(S.sel.cat + '\u0000' + S.sel.grp) || [];
  return list.filter(r => !r.lock && isVisibleRow(r) && !trOf(r.id));
}
async function copyGroup() {
  if (!S.sel.grp) return;
  const rows = groupTargets();
  if (!rows.length) { toast('Nothing untranslated in this group'); return; }
  try {
    // Japanese source: the translator gets the Japanese line where there is one
    const j = await api('/tx/group', {op: 'format', language: langName(), items: rows.map((r, i) => [i + 1, (S.ja && jaOf(r)) || r.src])});
    S.lastCopy = {key: S.sel.cat + '\u0000' + S.sel.grp, ids: rows.map(r => r.id)};
    if (await copyText(j.text)) toast('Copied ' + rows.length + ' numbered lines from ' + S.sel.grp);
    else toast('The browser refused clipboard access', true);
  } catch (e) { toast(e.message, true); }
}
function pasteGroup() {
  if (!S.sel.grp) return;
  if (!S.proj) { ensureProjectFirst(); return; }
  const key = S.sel.cat + '\u0000' + S.sel.grp;
  const ids = (S.lastCopy && S.lastCopy.key === key) ? S.lastCopy.ids : groupTargets().map(r => r.id);
  const ta = h('textarea', {placeholder: '[1] première ligne\n[2] deuxième ligne ⏎ suite…'});
  const prev = h('div');
  let parsed = null;
  const doParse = async (setMsg) => {
    const j = await api('/tx/group', {op: 'parse', text: ta.value});
    parsed = j.items;
    const grid = h('div', {class: 'diff'}, h('div', {class: 'n h', text: '#'}), h('div', {class: 'h', text: 'source'}), h('div', {class: 'h', text: 'gets'}));
    let n = 0, miss = 0;
    ids.forEach((id, i) => {
      const r = S.byId.get(id), v = parsed[String(i + 1)];
      if (v !== undefined && v !== '') n++; else miss++;
      grid.append(h('div', {class: 'n', text: String(i + 1)}), h('div', {text: r.src}),
        v ? h('div', {class: 'new', text: v}) : h('div', {class: 'miss', text: '— no line —'}));
    });
    const extra = Object.keys(parsed).filter(k => +k < 1 || +k > ids.length);
    prev.replaceChildren(grid);
    const notes = (j.notes || []).concat(extra.length ? ['numbers with no row: ' + extra.join(', ')] : []);
    setMsg(n + ' of ' + ids.length + ' rows get a translation' + (miss ? ', ' + miss + ' missing' : '') +
      (notes.length ? ' · ' + notes.join(' · ') : ''), !!(extra.length || (j.notes || []).length));
    return n;
  };
  dialog({title: 'Paste translations into ' + S.sel.grp, wide: true,
    body: [h('p', {text: 'Paste the numbered lines back exactly as the translator returned them. ' + ids.length +
      ' rows are expected, numbered as copied. Line breaks are written ⏎. Rows get the text as drafts; nothing is saved until you press Apply.'}),
      ta, prev],
    buttons: [
      {text: 'Preview', ghost: true, run: async (setMsg) => { try { await doParse(setMsg); } catch (e) { setMsg(e.message, true); } return false; }},
      {text: 'Apply', run: async (setMsg) => {
        // always the box as it is now: fixes typed after Preview must count
        try { await doParse(setMsg); } catch (e) { setMsg(e.message, true); return false; }
        const touched = [];
        ids.forEach((id, i) => { const v = parsed[String(i + 1)]; if (v) { setTr(id, v, 'draft'); touched.push(id); } });
        if (!touched.length) { setMsg('Nothing to apply', true); return false; }
        const more = [];
        touched.forEach(id => more.push(...propagateTm(id)));
        S.lastCopy = null;
        queueCheck(touched.concat(more)); markDirty(); renderTree(); refreshView(false); updateSteps();
        if (S.cur) repaintRow(S.cur);
        toast('Applied ' + touched.length + ' lines' + (more.length ? ' (+' + more.length + ' by translation memory)' : ''));
        return true;
      }}]});
}

// ------------------------------------------------------------------ TSV
function importTsv() {
  if (!S.proj) { ensureProjectFirst(); return; }
  const file = h('input', {type: 'file', accept: '.tsv,.txt,text/tab-separated-values,text/plain'});
  const ta = h('textarea', {placeholder: 'id<TAB>source<TAB>translation — or choose a file above'});
  file.addEventListener('change', () => {
    const f = file.files[0]; if (!f) return;
    const rd = new FileReader(); rd.onload = () => { ta.value = rd.result; }; rd.readAsText(f, 'utf-8');
  });
  const probs = h('ul', {class: 'problems'});
  // two steps: Check reads the file and says what it would do (the server only computes,
  // it saves nothing); Import applies exactly that, after a checkpoint when lines are replaced
  let ready = null;
  ta.addEventListener('input', () => { ready = null; if (goBtn) goBtn.textContent = 'Check'; });
  file.addEventListener('change', () => { ready = null; if (goBtn) goBtn.textContent = 'Check'; });
  let goBtn = null;
  dialog({title: 'Import TSV', wide: true,
    body: [h('p', {text: 'Three tab-separated columns: id, source, translation (\\n \\t \\\\ escapes). Empty translations are skipped, so importing never clears work. Imported rows become drafts. Check first shows what would change; nothing is changed until Import.'}),
      file, ta, probs],
    buttons: [{text: 'Check', run: async (setMsg, el) => {
      goBtn = el;
      if (!ta.value.trim()) { setMsg('Nothing to import', true); return false; }
      if (ready && (ready.gen !== S.projGen || ready.rev !== (S.rev || 0))) {
        ready = null; setMsg('The project changed since the check (an edit, or a merge from another tab): checking again…');
      }
      if (ready && ready.gen === S.projGen) {
        const {j, replaced} = ready;
        if (replaced) {
          try {
            if (!(await flushSave())) throw new Error('the project could not be saved');
            if (ready.rev !== (S.rev || 0)) { ready = null; el.textContent = 'Check'; setMsg('The project changed while saving (a merge from another tab): press Check again', true); return false; }
            await api('/tx/backups', {path: S.projPath, action: 'checkpoint', label: 'before TSV import', project: S.proj});
          } catch (e) { setMsg('No checkpoint could be made, so nothing was imported: ' + e.message, true); return false; }
        }
        S.proj = j.project; recomputeTm(); markDirty(); renderTree(); refreshView(false); runAllChecks(); updateSteps();
        if (S.cur) repaintRow(S.cur);
        toast('Imported ' + fmtN(j.applied) + ' rows' + (replaced ? ' (checkpoint "before TSV import" made first)' : ''));
        return true;
      }
      try {
        const j = await api('/tx/import-tsv', {tsv: ta.value, project: S.proj, iso: S.iso});
        const before = S.proj.translations || {}, after = j.project.translations || {};
        let added = 0, replaced = 0;
        for (const [id, t] of Object.entries(after)) {
          const b = before[id];
          if (!b) added++;
          else if (b.text !== t.text) replaced++;
        }
        probs.replaceChildren(...(j.problems || []).slice(0, 200).map(p => h('li', {text: p})));
        if (!added && !replaced) { setMsg('Nothing would change' + ((j.problems || []).length ? ': see the notes below' : ''), true); return false; }
        ready = {j, replaced, gen: S.projGen, rev: S.rev || 0};
        el.textContent = 'Import ' + fmtN(added + replaced) + ' rows';
        setMsg(fmtN(added) + ' new · ' + fmtN(replaced) + ' replacing your translation' + (replaced ? ' (a checkpoint is made first)' : '') +
               ((j.problems || []).length ? ' · ' + j.problems.length + ' skipped or noted below' : '') + '. Press Import to apply.', false);
        return false;
      } catch (e) { setMsg(e.message, true); return false; }
    }}]});
}
async function exportTsv() {
  if (!S.proj || !S.projPath) { ensureProjectFirst(); return; }
  if (!(await flushSave())) return;
  // fetched first, so a refusal (a project of another disc set) is a message, not a downloaded error page
  let blob;
  try {
    const r = await fetch('/tx/export-tsv?path=' + encodeURIComponent(S.projPath) + '&iso=' + encodeURIComponent(S.iso),
                          {headers: {'X-TX-Token': TX_TOKEN}});
    if (!r.ok) { let m = await r.text(); try { m = JSON.parse(m).error || m; } catch (_) {} throw new Error(m); }
    blob = await r.blob();
  } catch (e) { toast('Export failed: ' + e.message, true); return; }
  const url = URL.createObjectURL(blob);
  const a = h('a', {href: url, download: stem(S.projPath) + '.tsv'});
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ------------------------------------------------------------------ bulk menu
function openBulk() { $('bulkmenu').hidden = false; $('btn-bulk').setAttribute('aria-expanded', 'true'); showCache(); }
// the cache: where it is and how big (GET /tx/cache); a second click within 6 s clears it
let cacheArm = 0;
function mb(n) { return (n / 1e6).toFixed(n < 1e7 ? 1 : 0) + ' MB'; }
async function showCache() {
  const el = $('cache-info'); cacheArm = 0;
  try { const c = await getJson('/tx/cache'); el.textContent = mb(c.bytes) + ' in ' + c.path; el.title = c.path; }
  catch (e) { el.textContent = 'could not be read: ' + e.message; }
}
$('btn-cache').addEventListener('click', async (e) => {
  e.stopPropagation();
  const el = $('cache-info');
  if (Date.now() - cacheArm > 6000) { cacheArm = Date.now(); el.textContent = 'click again to delete it (your projects are not in it)'; return; }
  cacheArm = 0;
  try { const r = await api('/tx/cache/clear', {}); el.textContent = 'cleared: ' + r.removed + ' file(s), ' + mb(r.bytes); toast('Cache cleared (' + mb(r.bytes) + ')' + (r.note ? ': ' + r.note : '')); }
  catch (err) { toast('Could not clear the cache: ' + err.message, true); }
});
$('bulkmenu').addEventListener('focusout', (e) => { if (!$('bulkmenu').hidden && e.relatedTarget && !e.relatedTarget.closest('.menu-wrap')) closeBulk(); });
function closeBulk() { $('bulkmenu').hidden = true; $('btn-bulk').setAttribute('aria-expanded', 'false'); }
$('btn-bulk').addEventListener('click', (e) => { e.stopPropagation(); if ($('bulkmenu').hidden) openBulk(); else closeBulk(); });
document.addEventListener('click', (e) => { if (!$('bulkmenu').hidden && !e.target.closest('.menu-wrap')) closeBulk(); });

// ------------------------------------------------------------------ build
let buildES = null;
function updateOutDefault() {
  const out = $('out');
  if (out.dataset.touched === '1') return;
  const iso = $('iso').value.trim();
  out.value = iso ? joinp(dirname(iso), 'Translated (' + langTag() + ')') : '';      // a folder: both discs go into it
}
function setBuildBadge(s) { const b = $('build-badge'); b.className = 'badge' + (s && s !== 'idle' ? ' ' + s : ''); b.textContent = s || 'idle'; }
// one log line; ids of this disc's lines become links to them
const LOG_ID_RE = /\b((?:sb|mnu|bat|sub):[^\s,;'"()]+)/g;
function blog(line) {
  const l = $('buildlog');
  let last = 0, m;
  LOG_ID_RE.lastIndex = 0;
  while ((m = LOG_ID_RE.exec(line))) {
    let id = m[1];
    while (id && !S.byId.has(id) && /[:.]$/.test(id)) id = id.slice(0, -1);
    if (!S.byId.has(id)) continue;
    if (m.index > last) l.appendChild(document.createTextNode(line.slice(last, m.index)));
    l.appendChild(h('span', {class: 'blid', text: id, title: 'show this line', onclick: () => jumpTo(id)}));
    last = m.index + id.length;
  }
  l.appendChild(document.createTextNode(line.slice(last) + '\n'));
  l.scrollTop = l.scrollHeight;
}
// show one line wherever it is: its group, filter off, hidden lines on if needed
async function jumpTo(id) {
  const r = S.byId.get(id); if (!r) return;
  if (r.hide && !S.showHidden) { $('showhidden').checked = true; S.showHidden = true; store('showHidden', true); renderTree(); }
  if (S.filter !== 'all' && !passes(r)) { $('filter').value = 'all'; S.filter = 'all'; }
  S.open.add(r.cat);
  selectNode(r.cat, r.grp);
  selectRow(id, {focus: true});
}
function setBuilding(on) { building = on; updateSteps(); }
function showBuildOk(out, label) {
  const box = $('buildok');
  box.replaceChildren(h('b', {text: '✓ Your ' + (label || langLabel()) + ' discs are ready'}), h('code', {text: out}),
    h('button', {class: 'mini', text: 'Copy path', onclick: async () => { if (await copyText(out)) toast('Path copied'); }}),
    h('span', {class: 'saved', text: 'The patched disc images are in this folder, under their original names. Boot them in PCSX2. The retail images were only read.'}));
  box.classList.add('show');
}
let buildFor = null;     // the project a running build was started for
// The build's own checks over the whole saved project (POST /tx/preflight): the
// per-line checker sees one line; this sees keyword links, locks and every
// family's rules together. Errors go into the checker's results, so the
// "errors" filter lists them. -> the result, or null when it could not run.
// the errors the last whole-project check added to rows (S.checks), so the next
// one replaces them instead of piling up: a line fixed elsewhere (a keyword
// link, an object's size) is not kept as an error
let pfAdded = new Map();
function clearPreflightErrors() {
  for (const [id, errs] of pfAdded) {
    const c = S.checks.get(id);
    if (!c) continue;
    const left = (c.errors || []).filter(e => !errs.includes(e));
    S.checks.set(id, Object.assign({}, c, {errors: left, ok: !left.length}));
  }
  pfAdded = new Map();
}
async function checkProject() {
  if (!(await flushSave())) { toast('The project could not be saved; not checked', true); return null; }
  const gen = S.projGen;
  let pf;
  try { pf = await api('/tx/preflight', {project: S.proj, iso: S.iso}); }
  catch (e) { toast('The whole-project check could not run: ' + e.message, true); return null; }
  if (gen !== S.projGen) return null;
  clearPreflightErrors();
  const ids = Object.keys(pf.errors || {});
  for (const id of ids) {
    const c = Object.assign({}, S.checks.get(id) || {}, {ok: false});
    const had = new Set(c.errors || []);
    c.errors = Array.from(new Set((c.errors || []).concat(pf.errors[id])));
    S.checks.set(id, c);
    pfAdded.set(id, pf.errors[id].filter(e => !had.has(e)));
  }
  if (!ids.length) { updateBuildSummary(); renderTree(); refreshView(false); if (S.cur) repaintRow(S.cur); }
  if (ids.length || (!pf.ok && (pf.notes || []).length)) {
    updateBuildSummary(); renderTree(); refreshView(false); if (S.cur) repaintRow(S.cur);
    dialog({title: ids.length ? plural(ids.length, 'translation') + ' the build would refuse' : 'The project cannot be built as it is', wide: !!ids.length,
      body: [h('p', {text: 'From the build\'s own checks over the whole project. Nothing was written.'}),
             ...(pf.notes || []).map(n => h('p', {text: n})),
             h('ul', {class: 'problems'}, ...ids.slice(0, 60).map(id => h('li', null,
               h('span', {class: 'blid', text: id, title: 'show this line', onclick: () => { closeDialog(); jumpTo(id); }}),
               ' — ' + pf.errors[id].join('; ')))),
             ids.length > 60 ? h('p', {class: 'dim', text: '… and ' + (ids.length - 60) + ' more: the "errors" filter lists them all.'}) : null].filter(Boolean),
      buttons: ids.length ? [{text: 'Show them', run: async () => {
        $('search').value = ''; S.search = ''; $('filter').value = 'errors'; S.filter = 'errors';
        S.sel = {cat: null, grp: null}; renderTree(); refreshView(true);
        if (S.view.length) selectRow(S.view[0].id, {focus: true});
        return true; }}] : []});
  }
  return pf;
}
function buildDone(status, out) {
  setBuilding(false);
  const mine = !buildFor || buildFor.path === S.projPath;   // (Restore or re-opening keeps it the same project)
  setBuildBadge(!mine ? 'idle' : status === 'ok' ? 'ok' : 'err');
  if (!mine) toast('Build of ' + buildFor.proj + (status === 'ok' ? ' finished: ' + out : ' failed — see the log'), status !== 'ok');
  else if (status === 'ok') { showBuildOk(out, buildFor && buildFor.label); toast('Build finished: ' + basename(out)); }
  else toast('Build failed — see the log above', true);
}
function waitJobEnd(jobId, out) {
  const poll = () => fetch('/job/' + jobId).then(r => r.json()).then(j => {
    if (j.status === 'running') { setTimeout(poll, 2000); return; }
    buildDone(j.status, out);
  }).catch(() => setTimeout(poll, 4000));
  poll();
}
function openDrawer() { $('drawer').classList.add('open'); $('drawer-toggle').textContent = 'Build ▾'; }
async function runBuild(force) {
  if (building) return;
  const out = $('out').value.trim(), iso = S.iso;      // the disc whose rows are loaded, not a path still being read
  if (!S.rows.length || !iso) { toast('Step 1 first: choose the disc', true); return; }
  if (!S.proj || !S.projPath) { toast('Step 2 first: choose the language and press New (or Open…)', true); return; }
  if (!out) { toast('Give an output folder', true); return; }
  if (out === iso) { toast('The output must be a new folder; the retail images are never written', true); return; }
  if (force !== true) clearPreflightErrors();     // (the whole-project check below finds them again if they still apply)
  const bc = buildCounts();
  if (bc.err && force !== true) {
    // the build refuses translations with errors: say so before it spends time
    const one = bc.err === 1;
    dialog({title: plural(bc.err, 'line') + (one ? ' has' : ' have') + ' an error', small: true,
      body: [h('p', {text: 'The build refuses translations the checker marks as errors (too long, a missing game code, a letter the font cannot draw…) and writes nothing. ' +
               'Fix ' + (one ? 'it' : 'them') + ' first, or build anyway to see the build\'s own report.'}),
             h('p', {text: 'First: ' + bc.errIds[0] + ' — ' + ((S.checks.get(bc.errIds[0]) || {errors: ['']}).errors[0] || '')})],
      buttons: [
        {text: 'Build anyway', ghost: true, run: async () => { setTimeout(() => runBuild(true), 0); return true; }},
        {text: one ? 'Show it' : 'Show them', run: async () => {
          $('search').value = ''; S.search = ''; $('filter').value = 'errors'; S.filter = 'errors';
          S.sel = {cat: null, grp: null}; renderTree(); refreshView(true);
          if (S.view.length) selectRow(S.view[0].id, {focus: true});
          return true; }}]});
    return;
  }
  setBuilding(true);
  $('buildok').classList.remove('show');
  const gen = S.projGen;
  if (!(await flushSave())) { setBuilding(false); toast('The project could not be saved, so nothing was built', true); return; }
  if (force !== true) {                 // the whole-project check first: a refusal costs seconds, not a build
    const pf = await checkProject();
    if (!pf) {                          // it could not run, or another project was opened meanwhile
      setBuilding(false);
      if (gen === S.projGen) toast('Nothing was built: the whole-project check did not finish', true);
      return;
    }
    if (!pf.ok) { setBuilding(false); return; }
  }
  if (gen !== S.projGen) { setBuilding(false); toast('Another project was opened before the build started; nothing was built', true); return; }
  buildFor = {gen: S.projGen, path: S.projPath, label: langLabel(), proj: basename(S.projPath)};
  openDrawer();
  if (buildES) buildES.close();
  $('buildlog').textContent = '';
  setBuildBadge('run');
  const form = new URLSearchParams({project: S.projPath, retail: iso, out,
    overwrite: $('overwrite').checked ? 'on' : ''});
  try {
    const res = await fetch('/run/tx-build', {method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-TX-Token': TX_TOKEN}, body: form.toString()});
    if (!res.ok) {
      const t = await res.text(); let m = t; try { const j = JSON.parse(t); if (j && j.error) m = j.error; } catch (_) {}
      throw new Error(m);
    }
    const {job_id} = await res.json();
    const es = new EventSource('/stream/' + job_id); buildES = es;
    es.onmessage = (e) => {
      if (e.data === '__eof__') {
        es.close();
        fetch('/job/' + job_id).then(r => r.json()).then(j => buildDone(j.status, out))
          .catch(() => waitJobEnd(job_id, out));
      } else blog(e.data);
    };
    // a dropped stream is not the end of the build: keep Build disabled until
    // /job says the job has finished
    es.onerror = () => { es.close(); waitJobEnd(job_id, out); };
  } catch (e) {
    setBuilding(false); setBuildBadge('err'); blog('[error] ' + e.message);
  }
}

// ------------------------------------------------------------------ picker (gui.py's, unchanged in behaviour)
let _detectedIsos = [];
let _detecting = true;     // /tx/detect still running (it opens every .iso nearby; seconds on a cold start)
const fsModal = $('fs-modal'), fsTitle = $('fs-title'), fsCrumb = $('fs-crumb'), fsList = $('fs-list'),
      fsRoots = $('fs-roots'), fsError = $('fs-error'), fsQuick = $('fs-quick'), fsSel = $('fs-sel'),
      fsSelectBtn = $('fs-select'), fsUp = $('fs-up');
const fsState = {mode: 'file', filter: null, current: null, parent: null, selected: null, onChoose: null};
function _pickSel(p) { fsState.selected = p; fsSel.classList.add('has'); fsSel.textContent = p; fsSelectBtn.disabled = false; }
// _detectedIsos: [{path, retail}] from /tx/detect, Xenosaga Episode III
// images only, the untouched retail image(s) first
function _renderQuickPick() {
  const isos = fsState.filter === 'iso' ? _detectedIsos : [];
  if (fsState.filter === 'iso' && _detecting && !isos.length) {
    fsQuick.hidden = false;
    fsQuick.replaceChildren(h('div', {class: 'qrow'}, h('span', {text: 'Looking for Xenosaga III discs nearby…'})));
    return;
  }
  if (!isos.length) { fsQuick.hidden = true; return; }
  fsQuick.hidden = false;
  const names = new Map();
  isos.forEach(d => { const k = basename(d.path); names.set(k, (names.get(k) || []).concat([d.path])); });
  // two copies with one name: say which folder (the parent, or one level up when the parents match too)
  const where = (p) => {
    const same = names.get(basename(p));
    if (same.length < 2) return '';
    const par = (q) => basename(dirname(q));
    const uniq = new Set(same.map(par)).size === same.length;
    return '  (in ' + (uniq ? par(p) : basename(dirname(dirname(p)))) + ')';
  };
  const link = (d) => {
    const nm = basename(d.path);
    const proto = /prototype/i.test(d.build || '');
    const label = (d.retail && !proto ? '✓ ' : '') + nm + (d.retail ? where(d.path) : '  (in ' + basename(dirname(d.path)) + ')');
    const a = h('a', {class: d.retail && !proto ? 'retail' : 'copy', text: label,
      title: d.path + (d.build ? '\n' + d.build + ' build' : '') + (proto ? '\nthe press prototype: it can be read, but a translation is meant for the retail discs'
        : d.retail ? '\na retail disc: its executables and file index match a retail build (a same-size change inside a file would not show). Translate from this one'
        : d.retail === false ? '\nits executables or file index differ from every retail build (a translated or modded copy): not for translating from'
        : '\nnot checked (the disc check did not run): it may be retail or a changed copy')});
    if (d.build && d.retail) a.appendChild(h('small', {text: d.build}));
    a.addEventListener('click', () => { fsQuick.querySelectorAll('a').forEach(x => x.classList.remove('selected')); a.classList.add('selected'); _pickSel(d.path); });
    a.addEventListener('dblclick', () => { fsState.selected = d.path; chooseAndClose(); });
    return a;
  };
  const isProto = (d) => /prototype/i.test(d.build || '');
  const ret = isos.filter(d => d.retail && !isProto(d)), other = isos.filter(d => d.retail === false || (d.retail && isProto(d)));
  const unchecked = isos.filter(d => d.retail == null);
  fsQuick.replaceChildren(
    ret.length ? h('div', {class: 'qrow'}, h('span', {text: 'Retail discs found:'}), ...ret.map(link)) :
      h('div', {class: 'qrow'}, h('span', {text: 'No retail Xenosaga III disc found nearby: browse to it below'})),
    other.length ? h('div', {class: 'qrow'}, h('span', {text: 'Prototype and changed copies (not for translating from):'}), ...other.map(link)) : null,
    unchecked.length ? h('div', {class: 'qrow'}, h('span', {text: 'Disc images not checked:'}), ...unchecked.map(link)) : null);
}
function openPicker({mode, filter, startPath, title, onChoose}) {
  Object.assign(fsState, {mode, filter: filter || null, current: null, parent: null, selected: null, onChoose});
  fsTitle.textContent = title || (mode === 'dir' ? 'Select a folder' : 'Select a file');
  fsSel.classList.remove('has'); fsSel.textContent = 'No selection';
  fsSelectBtn.disabled = mode === 'file'; fsError.hidden = true;
  _renderQuickPick(); fsModal.hidden = false; loadDir(startPath || '');
}
function closePicker() { fsModal.hidden = true; fsState.onChoose = null; }
async function loadDir(path) {
  fsError.hidden = true;
  try {
    const qs = new URLSearchParams(); if (path) qs.set('path', path); if (fsState.filter) qs.set('filter', fsState.filter);
    const res = await fetch('/browse-fs?' + qs.toString());
    if (!res.ok) { fsError.hidden = false; fsError.textContent = 'Cannot read directory.'; return; }
    const data = await res.json();
    if (data.error) { fsError.hidden = false; fsError.textContent = data.error; }
    fsState.current = data.path; fsState.parent = data.parent; fsState.selected = null;
    if (fsState.mode === 'dir') _pickSel(data.path);
    else { fsSel.classList.remove('has'); fsSel.textContent = 'No selection'; fsSelectBtn.disabled = true; }
    fsUp.disabled = !data.parent;
    renderCrumb(data.path); renderList(data.entries || []); renderRoots(data.roots || []);
  } catch (err) { fsError.hidden = false; fsError.textContent = 'Error loading directory: ' + err.message; }
}
function renderCrumb(fullPath) {
  const win = fullPath.indexOf('\\') >= 0 && fullPath.indexOf('/') < 0;
  let parts = win ? fullPath.split('\\').filter(Boolean) : ['/'].concat(fullPath.split('/').filter(Boolean));
  if (win && parts.length && /^[A-Z]:$/i.test(parts[0])) parts[0] += '\\';
  let acc = '';
  const kids = [];
  parts.forEach((p, i) => {
    if (!win) acc = i === 0 ? '/' : (acc.endsWith('/') ? acc : acc + '/') + p;
    else acc = i === 0 ? p : acc + (acc.endsWith('\\') ? '' : '\\') + p;
    const target = acc;
    kids.push(h('a', {text: p, onclick: () => loadDir(target)}));
    if (i < parts.length - 1 && !(i === 0 && !win)) kids.push(h('span', {class: 'sep', text: '/'}));
  });
  fsCrumb.replaceChildren(...kids);
}
function renderList(entries) {
  if (!entries.length) { fsList.replaceChildren(h('div', {class: 'fs-empty', text: '(empty' + (fsState.filter ? ' — no .' + fsState.filter + ' files here' : '') + ')'})); return; }
  fsList.replaceChildren(...entries.map(e => {
    const el = h('div', {class: 'fs-entry'}, h('span', {class: 'icon', text: e.type === 'dir' ? '📁' : '📄'}),
      h('span', {class: 'name', text: e.name}), e.type === 'file' ? h('span', {class: 'size', text: fmtSize(e.size)}) : null);
    el.addEventListener('click', () => {
      if (e.type === 'dir') loadDir(e.path);
      else if (fsState.mode === 'file') { fsList.querySelectorAll('.fs-entry.selected').forEach(x => x.classList.remove('selected')); el.classList.add('selected'); _pickSel(e.path); }
    });
    el.addEventListener('dblclick', () => { if (e.type !== 'dir' && fsState.mode === 'file') { fsState.selected = e.path; chooseAndClose(); } });
    return el;
  }));
}
function renderRoots(roots) {
  fsRoots.replaceChildren(h('span', {text: 'Roots:'}), ...roots.map(r => h('a', {text: r, onclick: () => loadDir(r)})));
}
function chooseAndClose() { if (!fsState.selected) return; const cb = fsState.onChoose, sel = fsState.selected; closePicker(); if (cb) cb(sel); }
fsUp.addEventListener('click', () => { if (fsState.parent) loadDir(fsState.parent); });
fsSelectBtn.addEventListener('click', chooseAndClose);
document.querySelectorAll('[data-fs-close]').forEach(el => el.addEventListener('click', closePicker));


// typed / pasted path in the picker: a file of the wanted kind is chosen at
// once, anything else is opened as a folder
function fsGo() {
  const p = $('fs-path').value.trim();
  if (!p) return;
  const ext = fsState.filter ? new RegExp('\\.' + fsState.filter + '$', 'i') : null;
  if (fsState.mode === 'file' && ext && ext.test(p)) { fsState.selected = p; chooseAndClose(); return; }
  loadDir(p);
}
$('fs-go').addEventListener('click', fsGo);
$('fs-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); fsGo(); } });
function pickIso() {
  $('fs-path').value = '';
  openPicker({mode: 'file', filter: 'iso', title: 'Step 1 · an untouched Xenosaga III disc image (.iso), either disc',
    startPath: dirname($('iso').value), onChoose: (p) => { $('iso').value = p; updateOutDefault(); loadCatalog(); }});
}
function pickProject() {
  $('fs-path').value = '';
  openPicker({mode: 'file', filter: 'json', title: 'Open a translation project (.json)',
    startPath: dirname($('proj').value || $('iso').value), onChoose: (p) => openProject(p)});
}

// ------------------------------------------------------------------ wiring
$('btn-iso-pick').addEventListener('click', pickIso);
$('btn-proj-pick').addEventListener('click', pickProject);
$('btn-proj-new').addEventListener('click', () => openSetup({mode: 'new'}));
$('btn-setup').addEventListener('click', (e) => { e.stopPropagation(); openSetup({mode: S.proj ? 'edit' : 'new'}); });
// clicking anywhere on step 2 (not its buttons) opens the Language setup
$('step2').addEventListener('click', (e) => {
  if (e.target.closest('button')) return;
  if (!S.rows.length && !TX_FAKE) { toast('Step 1 first: choose the disc (the preview uses its fonts)', true); return; }
  openSetup({mode: S.proj ? 'edit' : 'new'});
});
$('btn-save').addEventListener('click', async () => {
  if (!S.proj) { openSetup({mode: 'new'}); return; }
  if (await saveProject()) toast('Saved');
});
$('btn-backups').addEventListener('click', openBackups);
$('saved').addEventListener('click', async () => {
  if (!S.proj) { openSetup({mode: 'new'}); return; }
  if (await saveProject()) toast('Saved');
});
let searchT = null;
function applySearch() {
  clearTimeout(searchT); searchT = null;
  const q = $('search').value.trim().toLowerCase();
  if (q === S.search) return;
  const t0 = performance.now();
  S.search = q; refreshView(true);
  perf('search "' + S.search + '": ' + fmtN(S.view.length) + ' of ' + fmtN(S.rows.length) + ' rows in ' +
       (performance.now() - t0).toFixed(1) + ' ms');
}
$('search').addEventListener('input', () => { clearTimeout(searchT); searchT = setTimeout(applySearch, 200); });
$('search').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.isComposing) return;
  e.preventDefault(); applySearch();
  if (S.view.length) selectRow(S.view[0].id, {focus: true});
});
$('filter').addEventListener('change', () => { S.filter = $('filter').value; refreshView(true); });
$('showhidden').addEventListener('change', () => {
  S.showHidden = $('showhidden').checked; store('showHidden', S.showHidden);
  if (S.showHidden && S.hidden && !S.hidden.loaded) { loadHidden(); return; }
  renderTree(); refreshView(false); updateSteps(); });
$('tm').addEventListener('change', () => { setTm($('tm').checked); const r = S.cur && S.byId.get(S.cur); if (r) paintTm(r); });
$('btn-copygrp').addEventListener('click', () => { closeBulk(); copyGroup(); });
$('btn-pastegrp').addEventListener('click', () => { closeBulk(); pasteGroup(); });
$('btn-tsv-in').addEventListener('click', () => { closeBulk(); importTsv(); });
$('btn-tsv-out').addEventListener('click', () => { closeBulk(); exportTsv(); });
$('list').addEventListener('scroll', () => requestAnimationFrame(() => renderWindow(false)));
$('list').addEventListener('click', (e) => {
  const el = e.target.closest('.lr'); if (!el) return;
  const r = S.view[+el.dataset.i]; if (r) selectRow(r.id, {focus: true, scroll: false});
});
window.addEventListener('resize', () => {
  renderWindow(true);
  const r = S.cur && S.byId.get(S.cur); if (r) { layoutPv(E.pvO, r); layoutPv(E.pvT, r); }
});
$('drawer-toggle').addEventListener('click', () => { const d = $('drawer'); d.classList.toggle('open');
  $('drawer-toggle').textContent = d.classList.contains('open') ? 'Build ▾' : 'Build ▸'; });
$('btn-build-open').addEventListener('click', () => { openDrawer(); $('out').focus(); });
$('btn-build').addEventListener('click', () => runBuild());
$('btn-check').addEventListener('click', async () => {
  if (!S.proj || !S.iso) { toast('Open the discs and a project first', true); return; }
  const b = $('btn-check'); b.disabled = true;
  const label = b.textContent; b.textContent = 'Checking…';
  b.title = 'The first check after opening the discs reads them (about 25 s); later ones are quick';
  try {
    const pf = await checkProject();
    if (pf && pf.ok) toast('Whole project checked: ' + fmtN(pf.edits) + ' translation(s), ' +
      (pf.script ? 'nothing refused so far (lines with new letters are checked by the build itself)' : 'nothing the build would refuse') +
      (pf.notes.length ? ' · ' + pf.notes.join(' · ') : ''));
  } finally { b.disabled = false; b.textContent = label; b.title = 'Run the build\'s own checks over the whole project (keywords, locks, every family\'s rules), without writing anything'; }
});
$('out').addEventListener('input', () => { $('out').dataset.touched = '1'; });
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
    e.preventDefault(); if (S.proj) saveProject().then(ok => { if (ok) toast('Saved'); });
    return;
  }
  const modal = !fsModal.hidden || !$('dlg').hidden;
  if (e.key === 'Escape') {
    if (!fsModal.hidden) { closePicker(); return; }
    if (!$('dlg').hidden) { cancelDialog(); return; }
    if (!$('bulkmenu').hidden) { closeBulk(); $('btn-bulk').focus(); return; }
    const a = document.activeElement;
    if (a && (a === E.ta || a.id === 'search' || a.id === 'filter')) { e.preventDefault(); a.blur(); $('list').focus({preventScroll: true}); }
    return;
  }
  if (modal) return;
  if (!$('bulkmenu').hidden) {
    // the open menu owns the arrow keys: step through its items, never the list
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      const items = Array.from($('bulkmenu').querySelectorAll('.mi')).filter(m => !m.disabled)
        .map(m => m.tagName === 'LABEL' ? m.querySelector('input') : m);
      if (!items.length) return;
      const at = items.indexOf(document.activeElement);
      const i = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 :
        at < 0 ? (e.key === 'ArrowDown' ? 0 : items.length - 1) : (at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[i].focus();
    }
    return;
  }
  const tg = e.target;
  if (tg && tg.id === 'search' && e.key === 'ArrowDown') {
    // run a search still waiting on its debounce first, so the move happens in the results
    e.preventDefault(); applySearch(); $('list').focus({preventScroll: true});
    if (S.view.length) selectRow(S.cur && S.viewIdx.has(S.cur) ? S.cur : S.view[0].id, {focus: false});
    return;
  }
  const typing = tg && (tg.tagName === 'TEXTAREA' || tg.tagName === 'INPUT' || tg.tagName === 'SELECT' || tg.isContentEditable);
  if (typing || e.ctrlKey || e.metaKey || e.altKey || !S.rows.length) return;
  const nav = {ArrowDown: 1, ArrowUp: -1, PageDown: pageRows(), PageUp: -pageRows()};
  if (e.key in nav) { e.preventDefault(); $('list').focus({preventScroll: true}); move(nav[e.key], false); return; }
  if (e.key === 'Home' || e.key === 'End') {
    if (!S.view.length) return;
    e.preventDefault(); $('list').focus({preventScroll: true});
    selectRow(S.view[e.key === 'Home' ? 0 : S.view.length - 1].id, {focus: false}); return;
  }
  if (e.key === 'Enter' && tg.tagName !== 'BUTTON' && tg.tagName !== 'A' && !tg.closest('.menu')) {
    // the line open on the right is not in this list (a new search or filter): take the first listed one
    e.preventDefault();
    if (!S.cur || !S.viewIdx.has(S.cur)) { if (S.view.length) selectRow(S.view[0].id, {focus: true}); return; }
    focusBox();
  }
});
window.addEventListener('beforeunload', (e) => { if (S.dirty) { saveProject(); e.preventDefault(); e.returnValue = ''; } });

// ------------------------------------------------------------------ boot
(async () => {
  S.tm = recall('tm', true); $('tm').checked = S.tm;
  S.treeView = recall('treeView', 'type'); if (!['type', 'speaker', 'file'].includes(S.treeView)) S.treeView = 'type';
  setAdvanced(recall('adv', false), true);
  $('advanced').addEventListener('change', () => setAdvanced($('advanced').checked));
  S.showHidden = recall('showHidden', false); $('showhidden').checked = S.showHidden;
  syncLangUi(); refreshView(true); renderEditor();
  languageList().catch(() => {});   // starts the server's font index early, so the setup's font list is ready
  // disc detection runs beside the rest of the start-up (it does not hold up a
  // recalled disc's catalog); a picker opened meanwhile fills in when it ends
  (async () => {
    try { _detectedIsos = (await getJson('/tx/detect')).discs || []; }
    catch (_) {
      try { _detectedIsos = ((await getJson('/detect')).isos || []).map(p => ({path: p, retail: null})); } catch (_) {}
    }
    _detecting = false;
    if (!fsModal.hidden) _renderQuickPick();
  })();
  // /editor?iso=PATH&project=PATH opens straight into that disc and project
  const qp = new URLSearchParams(location.search);
  const iso = qp.get('iso') || recall('iso', '') || '';
  $('iso').value = iso;
  updateOutDefault();
  if (iso || TX_FAKE) await loadCatalog();
  else updateBanner();
  const pp = qp.get('project') || recall('proj', '');
  if (pp) { $('proj').value = pp; await openProject(pp); }
  updateSteps();
})();
</script>
</body>
</html>
"""
