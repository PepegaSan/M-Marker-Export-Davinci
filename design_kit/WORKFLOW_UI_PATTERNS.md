# Workflow & UI structure patterns (reference)

**`design_kit/` is reference-only** — do not rely on this folder in shipped repos. Copy what you need (e.g. `theme_palette.py` → project root) into the target app.

This document captures **interaction and layout patterns** used in the **Stash Metadaten Editor** (`app.py` in this repo). Copy the ideas into other tools that use the same **CustomTkinter + palette** (`theme_palette.py` beside your GUI) — they complement `DESIGN_PROMPT.md` (visual chrome) and `example_app.py` (live snippets).

---

## 1. Section cards (`CTkFrame` as “card”)

**Goal:** Break a tab into clear **zones** (search, results, loaded entity, global tools) instead of one long flat form.

**Pattern:**

- Outer tab frame: `grid_columnconfigure(0, weight=1)`; give the **scrollable / list** row `weight=1`.
- Each logical block is a `CTkFrame`:
  - `fg_color=p["panel_elev"]`
  - `corner_radius=10`
  - `border_width=1`
  - `border_color=p["border"]`
- **Padding:** `padx=10`, `pady=(8, 6)` between cards; inner `padx=8` / `pady` for controls.
- **Section title:** `CTkLabel` with `FONT_SECTION`, `text_color=p["text"]`, first row of the card.
- **Muted hints:** `FONT_HINT`, `text_color=p["muted"]`, `wraplength=780–920`, `justify="left"` under inputs.

**Theme sync:** In `_sync_palette()` / `_apply_palette()`, loop over card attribute names and `configure(fg_color=p["panel_elev"], border_color=p["border"])` so dark/light switches never leave stale greys.

---

## 2. Button hierarchy inside a card

**Rough rule:**

| Role | Variant | Notes |
|------|---------|--------|
| Main destructive / irreversible batch action | `danger_soft` | Red text, panel background — still rimmed. |
| Main positive commit (save, apply) | `primary_emphasis` | Bold 11 pt, cyan fill. |
| Secondary (open in browser, reload, search) | `ghost` | Same height family as others. |
| Backup / money path | `gold` | e.g. “Start backup” in the global strip. |

Keep **one** primary emphasis per dense row so the eye knows what commits state.

---

## 3. Enter key = submit (search / primary field)

**Goal:** Power users don’t have to click “Search” after typing.

**Pattern:**

```python
self.some_search_entry.bind("<Return>", self._on_some_search_return)

def _on_some_search_return(self, _event=None) -> str:
    self.run_search()
    return "break"  # suppress ding / extra propagation where needed
```

**Also:** Persist last query to `app_config.json` (e.g. `last_scene_search`, `last_batch_keyword`) in `_save_config` and restore in `_apply_config_to_widgets` so the app feels continuous across sessions.

---

## 4. List + selection workflow (scenes-style)

**Patterns that work well together:**

- **Single click:** select row + fill an ID field (optional **Shift** = select only, don’t overwrite the ID field).
- **Double click:** commit load / open detail.
- **Arrow keys + Enter** on an inner `tk.Text` (CustomTkinter `CTkTextbox._textbox`): navigate lines, Enter loads; **block** arbitrary typing / paste on that read-only list (`return "break"` for unhandled keys); allow **Tab**, **Escape**, **Ctrl+C**, **Ctrl+A**.
- **Right click:** context menu (open in app, open folder, **copy** id / path / URL).

**Implementation note:** Bind on the **inner** `tk.Text`, not only on `CTkTextbox`, for reliable `index("@x,y")`.

---

## 5. Dirty state for a text editor (tags-style)

**Goal:** User can see **unsaved** edits and get a confirm before switching context.

**Pattern:**

- Keep `_editor_snapshot = widget.get("1.0", "end-1c")` after each successful **load** or **save**.
- `_is_dirty()` ⇔ current body ≠ snapshot.
- **Badge:** small `CTkLabel` “Unsaved” with `text_color=p["gold"]`, `grid()` when dirty, `grid_remove()` when clean.
- **Before** loading another entity or reloading from server: if dirty, `messagebox.askyesno` with different copy for “same entity refresh” vs “switch entity”.
- **Escape** (optional): restore from snapshot after confirm.
- **Ctrl+S** (optional): `bind_all` only when the relevant tab is active to avoid surprising other tabs.

---

## 6. Tab open = optional auto-load (tags-style)

**Pattern:** Checkbox “When opening this tab, reload from server (only if no unsaved edits)” bound to config key `tags_autoload_on_nav`.

**On navigation:** If auto-load is on, scene exists, and **not** dirty → call load routine with `skip_dirty_check=True` so you don’t double-prompt.

---

## 7. Batch / destructive global actions (batch-style)

**Wording (avoid confusion):** In Stash there are two different ideas: (1) **detach** a tag from scenes — remove it from each scene’s **scene-tag list**; the **tag entry** can still exist in the library. (2) **Delete tag in Stash** — remove the **tag entity** from Stash (the UI should say so explicitly). Batch **detach** should use the **same scope** as batch **apply** (path filter + all matches vs selected list rows), not a separate hidden “whole library” path. The Tags tab “library” card should describe (2).

**Patterns:**

- **Confirm with counts:** Build the same candidate scene list as apply-tag, count scenes that still carry the tag, `askyesno`; if zero, `showinfo` and return.
- **Scope guard:** If “selected only” is checked but **no listbox selection**, warn and return — don’t silently apply to zero rows.
- **Case-insensitive tag resolution:** Resolve user/combo text to the canonical Stash tag key before comparing to scene tag names.
- **Results list:** After keyword filter search, show **empty hint** (no matches vs. idle hint before first search); **double-click** row → open entity in browser (same as context menu “open”).
- **Enter** in keyword field runs search; **save last keyword** to config.

---

## 8. Global replace vs delete (tags card)

**Pattern:** “Replace tag A with B on all scenes” as a **separate** block from delete: two combos + confirm + loop `scene_update` with new tag id set. Document in UI that **marker primary tags** (or other relations) may still reference the old tag until the user cleans them in Stash.

---

## 9. Internationalisation

All user-visible strings for these flows should go through **`tr()`** / `I18N` dicts (`de` / `en`) so status lines, empty hints, and confirm dialogs stay consistent when you add a third language later.

---

## 10. Checklist when starting a new tool from this kit

1. Copy `theme_palette.py` + wire `_pal` + `_apply_palette()`.
2. Decide **tab → cards** map; add card frames to `_sync_palette`.
3. For each **search** field that should feel instant: **Return** binding + optional config persistence.
4. For each **list that drives selection**: click / double-click / keyboard / context menu plan.
5. For any **multi-step edit buffer**: dirty badge + confirm on navigation + optional Esc / Ctrl+S.
6. For **batch or irreversible ops**: count → confirm → status + optional `showinfo` summary.

---

_End of workflow patterns reference._
