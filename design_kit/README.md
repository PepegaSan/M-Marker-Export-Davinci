# Design kit — CustomTkinter chrome reference

## Reference only — not part of shipping repos

**Dieser Ordner `design_kit/` ist ausschließlich Referenz** (Beispiele, Prompts, Muster). Er wird **nicht** mit dem eigentlichen Projekt hochgeladen, versioniert oder verteilt, wenn das Ziel-Repo schlank bleiben soll.

**Was du stattdessen tust:** Alles, was die laufende App wirklich braucht, **ins Projekt-Hauptverzeichnis** (neben die Haupt-GUI-Datei, z. B. `transcript.py`) legen — typischerweise mindestens **`theme_palette.py`** plus die im Zielprojekt eingebaute Logik (`self._pal`, `_apply_ui_palette` / `_button_kw`, …). Die Dateien hier dienen nur zum **Ablesen, Kopieren und für KI-/Editor-Anhänge**; sie sind keine Laufzeit-Abhängigkeit.

---

This folder is meant to be **copied or attached** when you want another tool (or another repo) to adopt the same **dark/light palette, typography, and button chrome** as the reference layout this project uses — **without** checking `design_kit/` into that repo.

## What to copy into a new project

| Item | Purpose |
|------|---------|
| `theme_palette.py` | `PALETTE_DARK` / `PALETTE_LIGHT` hex dicts; your app keeps `self._pal` and swaps on appearance change. |
| `example_app.py` | Minimal runnable window: top bar, sidebar sample, primary button, segmented appearance toggle. |
| `DESIGN_PROMPT.md` | Long **copy-paste prompt** for an AI assistant (or checklist for you) to restyle an existing GUI. |
| `WORKFLOW_UI_PATTERNS.md` | **Workflow & structure** reference: section cards, Enter-to-search, dirty badges, batch confirms, list UX — patterns extracted from the Stash metadata editor. |

**Optional (full widget-theme parity):**

- Copy a CustomTkinter JSON theme (for example `themes/blue_soft.json` if your main app ships one) and load it with CustomTkinter’s JSON theme API if you tune widget defaults beyond the palette dict.
- Reuse shared helpers from your main app if available (`_button_kw`, `_label`, `ttk.Treeview` styling, debounced filter rebuilds, etc.).

## Toggle-row patterns (CTkSwitch)

`example_app.py` ships two reusable toggle patterns that you can lift
straight into another tool — they mirror common “toggle + hint” and “toggle + expandable options” rows:

1. **Simple switch row** — one `CTkSwitch` + a muted hint line beneath.
   Use for pure on/off options that don't need further parameters.
2. **Advanced switch row** — a `CTkSwitch` on the left, an
   `Advanced ▾` ghost button on the right, a muted hint line, and a
   `grid_forget()`-toggled sub-frame that holds parameter entries with
   unit labels. The caret flips to `▴` when expanded.

Both are themed in `_apply_palette()` via a single `switch_kw` dict so
they follow dark ↔ light mode flawlessly — see `DESIGN_PROMPT.md`
section 7 for the exact `CTkSwitch` palette mapping.

## Workflow patterns (cards, Enter, batch safety)

`example_app.py` now includes a small **two-card strip** (search + results stub)
above the switch demos: elevated `CTkFrame` cards, muted hint line, **Enter**
runs the fake search — same structural ideas as the metadata tool.

For the **full checklist** (dirty state, double-click lists, confirm-before-global-delete, config keys, i18n), read **`WORKFLOW_UI_PATTERNS.md`** and paste it into new-tool specs or AI threads together with `DESIGN_PROMPT.md`.

## Try the example

```bash
cd design_kit
pip install customtkinter
python example_app.py
```

## For Cursor / another chat

Open **`DESIGN_PROMPT.md`** (and optionally **`WORKFLOW_UI_PATTERNS.md`**), copy the blocks into a new conversation together with your other project’s main GUI file(s).
