# Copy-paste prompt: apply the shared graphite/cyan CustomTkinter design to another project

Paste everything below the line into a new assistant thread. Attach your target project’s GUI file(s) and (if you have them) `theme_palette.py` / screenshots.

---

**Role:** You are editing an existing **Python + CustomTkinter** desktop app. Apply the same **visual language** as the reference design in this repo: dark graphite background, elevated panels, cyan “primary” actions, bordered buttons, Segoe-based typography, optional sidebar navigation.

**Reference materials (read and follow):**

1. **Palette** — two dicts `PALETTE_DARK` and `PALETTE_LIGHT` with at least these keys (hex strings):  
   `bg`, `panel`, `panel_elev`, `border`, `text`, `muted`, `cyan`, `cyan_dim`, `cyan_hover`, `gold`, `gold_dim`, `stop`, `btn_rim`, `primary_border`.  
   Copy the exact values into a **`theme_palette.py` in the target project’s root** (next to the main GUI file). Treat `design_kit/` as **reference-only** — it is not uploaded with shipping repos; only the copied root file is required at runtime.

2. **Root window:** `ctk.CTk(fg_color=p["bg"])` and `self._pal: dict[str, str]` that switches between dark/light copies of the palette when the user chooses appearance (`ctk.set_appearance_mode`, then re-assign `self._pal`, then update widget `fg_color` / `text_color` from `_pal`).

   **Mandatory theme-switch pattern (most common bug source):** CustomTkinter does **not** repaint existing widgets when appearance changes. Every palette-driven widget must be:
   1. **stored** as an instance attribute (`self._foo = ctk.CTk…`, no throwaway `.grid(...)` chains that discard the reference),
   2. **reconfigured** inside a single `_apply_palette()` method that is the *only* place reading `self._pal`,
   3. **called** from both `__init__` (first paint) and the appearance callback.

   Rebuild button kwargs via `self._button_kw(variant)` inside `_apply_palette()` — reusing stale kwargs leaves cyan borders/hover colours from the wrong palette. `CTkSegmentedButton` needs `fg_color` + `selected_color` + `selected_hover_color` + `unselected_color` + `unselected_hover_color` + `text_color` explicitly reapplied.

3. **Typography (Windows):**

   - App title: `("Segoe UI Black", 18)` — `text_color=p["text"]`
   - Body / status: `("Segoe UI", 14)` — muted lines use `p["muted"]`
   - Small UI: `("Segoe UI", 12)`
   - Section headings: `("Segoe UI Semibold", 15)`
   - Hints: `("Segoe UI", 11)` with `p["muted"]`
   - Default **action** button label font: `("Segoe UI Black", 10)`; **primary emphasis** rows may use `("Segoe UI Black", 11)`
   - Sidebar nav: `("Segoe UI Semibold", 10)` idle; active nav can use `("Segoe UI Black", 10)`

4. **Geometry constants:** `BTN_RADIUS = 10`, compact toolbar button height **36** (`BTN_HEIGHT_COMPACT`), top bar height visually ~52–56 px.

5. **`CTkButton` styling — critical rules:**

   - Central helper `_button_kw(variant, *, height=..., font=..., width=...)` returns a **dict** merged into `CTkButton(..., **kw)`. Never pass the same key twice (e.g. do not set `corner_radius` on the button **and** inside `_button_kw`).
   - Every button: `corner_radius=BTN_RADIUS`, `border_width=2`, `border_color=p["btn_rim"]`, explicit `height`, explicit `font` per variant.
   - **Variants to implement (names can match this repo’s `_button_kw` conventions):**
     - `ghost` — `fg_color=panel_elev`, `hover_color=border`, `text=text`
     - `primary` — `fg_color=cyan_dim`, `hover_color=cyan`, `text=text`, `border_color=primary_border`
     - `primary_emphasis` — same as primary but `font=("Segoe UI Black", 11)` (main “blue” actions)
     - `gold` / `success` / `danger_soft` if the app has undo / confirm / destructive actions (use distinct colors, still rimmed)
     - `nav_idle` / `nav_active` for sidebar tabs (active: cyan_dim fill, cyan border, bold font)
   - **Settings / icon gear:** one kwargs dict only — do **not** merge two dicts that both set `corner_radius` / `font` (causes `TypeError`).

6. **Layout pattern (recommended):**

   - `grid_rowconfigure(1, weight=1)` on root; **row 0** = full-width **top bar** `CTkFrame` with `fg_color=panel`, `corner_radius=0`: title (col 0), status `StringVar` (col 1, sticky ew), primary actions + gear (col 2–3).
   - **Row 1** = **body** `CTkFrame` with `fg_color=bg`: **column 0** narrow **sidebar** `CTkFrame` (`fg_color=panel`, `corner_radius=14`, `border_width=1`, `border_color=border`), **column 1** main **content** frame with `fg_color=panel`, inner `corner_radius=10`, border.
   - Bottom optional strip for “Save” / global actions with `panel_elev` background.

7. **`CTkEntry` / `CTkOptionMenu` / checkboxes:** use palette-driven `fg_color`, `border_color`, `text_color`, `button_color` consistent with panels; option menus: `fg_color=panel_elev`, `button_color=cyan_dim`, `button_hover_color=cyan`.

   **`CTkSwitch` — two reusable patterns (see `example_app.py`):**

   *Always* configure the switch in `_apply_palette()` with:

   ```python
   switch_kw = dict(
       text_color=p["text"],
       progress_color=p["cyan"],        # ON-track accent
       button_color=p["panel"],         # thumb (both states)
       button_hover_color=p["panel_elev"],
       fg_color=p["panel_elev"],        # OFF-track colour
   )
   widget.configure(**switch_kw)
   ```

   1. **Simple switch row** — one `CTkSwitch` + a one-line `p["muted"]`
      hint label below it. Use when the option is a pure on/off with no
      follow-up parameters. The hint describes *what happens in each
      state*, so users don't need a tooltip or modal.

   2. **Advanced switch row (foldable sub-options)** — a `CTkSwitch` on
      the left, an `Advanced ▾` ghost button on the right, a muted hint
      line below both, and a pre-built but *un-gridded* options
      `CTkFrame` (`fg_color=panel_elev`, `corner_radius=8`,
      `border_width=1`, `border_color=border`) that is `grid(...)` /
      `grid_forget()` toggled by a `_toggle_advanced()` method. The
      caret on the button flips between `▾` and `▴` so users see fold
      direction at a glance. Entries inside the sub-frame use
      `fg_color=panel` (one level less elevated than the container) +
      `border_color=border` + `text_color=text`; unit labels + hint
      labels on the same row use `FONT_UI_SM` / `FONT_HINT` with
      `p["muted"]`. Keep numeric state as `StringVar` and parse to
      float only at submit time — `DoubleVar` rejects mid-edit empty
      strings.

   Pipeline logic reads the switch's current state at *submit time*, not
   via a `trace_add` on the `BooleanVar` — flipping a switch should
   stage intent, not fire side effects, which also makes the
   _"Advanced ▾"_ panel safe to open while the pipeline is running.

8. **`ttk.Treeview`:** CustomTkinter does not skin Treeview — add a small `_apply_ttk_treeview_style()` that sets `ttk.Style` for `Treeview` / `Treeview.Heading` using `_pal` so lists match dark/light.

9. **Performance / UX (if the app has large lists or filters):**

   - Debounce filter text → tree rebuild (~500 ms after last keystroke).
   - Long exports / subprocess / ffprobe: run on a **background thread**, marshal UI updates with `root.after(0, ...)`.
   - Treeview: insert rows in batches; optional B1-drag range select with edge auto-scroll.

10. **PyInstaller (if shipping .exe):** `collect_all("customtkinter")`; bundle `locales/` and `themes/` if present; `console=False` and windowed bootloader for GUI-only apps.

11. **Workflow & information architecture (optional but recommended for data-heavy tools):**  
    Beyond colours, plan **cards**, **keyboard paths**, and **safe batch actions**:
    - **Section cards:** Use nested `CTkFrame` blocks with `fg_color=panel_elev`, `corner_radius≈10`, `border_width=1`, `border_color=border`, and a `FONT_SECTION` title per block. Re-apply card colours in the same `_apply_palette()` / `_sync_palette()` pass as the root window.
    - **Enter = submit:** Bind `<Return>` on primary search fields to the same handler as the “Search” button; return `"break"` when you want to suppress default behaviour. Persist last search strings in JSON config when it improves daily use.
    - **List UX:** Single-click vs double-click; optional Shift modifier; inner `Text` bindings for read-only lists; context menu for copy / open external; double-click to open in browser where applicable.
    - **Dirty editor:** Compare editor text to a snapshot after load/save; show a gold “Unsaved” badge; confirm before context switches that would discard edits; optional Esc revert and Ctrl+S when scoped to the active tab.
    - **Batch / destructive ops:** Pre-count affected rows, `askyesno` with the count, block “selected only” when selection is empty, resolve domain keys case-insensitively before compare.
    - **i18n:** Route strings through a small `tr()` / dict map so hints and confirms stay translatable.

    **Reference:** `design_kit/WORKFLOW_UI_PATTERNS.md` in this repo expands each bullet with examples and a starter checklist for new tools.

**Task for this codebase:**  
Inspect the attached GUI module(s). Introduce `theme_palette.py` (or import it), add `_pal` + appearance sync, refactor buttons to use `_button_kw` variants, align frames/typography with the rules above, and fix any duplicate-keyword widget errors. Keep **behaviour and public APIs** unchanged unless a colour callback is required. Prefer **small, reviewable diffs**.

**Done when:** The app visually matches the reference (dark graphite + cyan primary + rimmed buttons + sidebar/top bar rhythm), light mode remains readable, every `CTkSwitch` and any foldable `Advanced ▾` panels pick up both palettes via `_apply_palette()`, and there are no regressions in layout or events.

---

_End of prompt block._
