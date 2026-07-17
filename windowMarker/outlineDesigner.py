#!/usr/bin/env python3
"""
outlineDesigner.py -- Eigenstaendiges Tkinter-Tool zum PARAMETRISCHEN
Entwerfen von Platten-Umrissen (Footprint/Bodenplatte/Seitenteile o.ae.),
UNABHAENGIG von footprintScale.py -- kein Import von dort, keine
Auswirkung auf die echte Export-Pipeline. Dient nur dazu, eine Kontur
interaktiv zu entwerfen (Variablen -> Punkte -> Loecher -> Vorschau) und
das Ergebnis als JSON zu speichern, um es dann per Chat zu schicken und in
footprintScale.py uebernehmen zu lassen.

Konzept:
  - VARIABLEN: eine GEORDNETE Liste von (Name, Ausdruck). Jeder Ausdruck
    darf auf ALLE vorher definierten Variablen + Mathe-Funktionen (sin,
    cos, sqrt, pi, ...) zugreifen -- so lassen sich abgeleitete Werte
    (Zungen-Positionen, Luecken, Mittelpunkte, ...) direkt im Tool
    ausrechnen, ohne von Hand Zahlen einzutippen.
  - PUNKTE: die geordnete Liste der Aussenkontur-Punkte (x_expr, y_expr).
    Wird als GESCHLOSSENER Pfad gezeichnet (die Schliess-Strecke vom
    letzten zum ersten Punkt wird gestrichelt mit angezeigt). Jede Strecke
    zeigt ihre Laenge (mm) an der Mitte an.
  - LOECHER: eine Liste benannter Rechtecke (Label, x, y, w, h), alle als
    Ausdruecke -- fuer Zungen-Loecher/Schlitze etc.
  - Mehrere "Formen" (Tabs) gleichzeitig, z.B. footprint/bottom_plate/
    side_plate_outer/side_plate_inner -- Speichern/Laden schreibt ALLE
    Formen in eine JSON-Datei.

Start: `python outlineDesigner.py`
"""

from __future__ import annotations

import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import ezdxf
except ImportError:
    ezdxf = None


# ---------------------------------------------------------------------------
# Sicheres Auswerten von Ausdruecken: nur Mathe-Funktionen + die Variablen
# des jeweiligen Formulars im Scope, KEINE Builtins (kein Datei-/Systemzugriff
# -- das Tool ist lokal/persoenlich, aber es ist trotzdem kein Grund, eval()
# mit vollen Builtins laufen zu lassen).
# ---------------------------------------------------------------------------
_SAFE_FUNCS = {
    name: getattr(math, name)
    for name in ("sin", "cos", "tan", "asin", "acos", "atan", "atan2",
                 "sqrt", "floor", "ceil", "fabs", "hypot", "radians", "degrees")
}
_SAFE_FUNCS.update({"abs": abs, "min": min, "max": max, "round": round, "pi": math.pi})


def safe_eval(expr: str, env: dict) -> float:
    if expr is None or str(expr).strip() == "":
        return 0.0
    scope = dict(_SAFE_FUNCS)
    scope.update(env)
    return float(eval(str(expr), {"__builtins__": {}}, scope))  # noqa: S307 -- lokales Werkzeug, kein Sandboxing noetig


DEFAULT_VARIABLES = [
    ["width_mm", "75"],
    ["height_mm", "40"],
    ["thickness_mm", "11"],
]


class Form:
    """Eine benannte Kontur: geordnete Variablen, Aussenkontur-Punkte,
    rechteckige Loecher. Alles als Ausdruck (String), nicht als Zahl --
    ausgewertet ueber resolved_*()."""

    def __init__(self, name: str):
        self.name = name
        self.outline_is_cut = True
        self.variables: list[list[str]] = [row[:] for row in DEFAULT_VARIABLES]
        self.points: list[list[str]] = [["0", "0"]]
        self.holes: list[list[str]] = []  # [label, x, y, w, h]

    # -- Auswertung ---------------------------------------------------
    def env(self) -> dict:
        """Wertet die Variablenliste DER REIHE NACH aus -- jede darf auf
        alle vorherigen zugreifen. Ungueltige Ausdruecke werden zu NaN
        (bricht die Anzeige nicht ab, waehrend man tippt)."""
        out: dict = {}
        for name, expr in self.variables:
            if not name:
                continue
            try:
                out[name] = safe_eval(expr, out)
            except Exception:
                out[name] = float("nan")
        return out

    def resolved_points(self, env: dict | None = None) -> list[tuple[float, float]]:
        env = self.env() if env is None else env
        pts = []
        for xe, ye in self.points:
            try:
                x = safe_eval(xe, env)
            except Exception:
                x = float("nan")
            try:
                y = safe_eval(ye, env)
            except Exception:
                y = float("nan")
            pts.append((x, y))
        return pts

    def resolved_holes(self, env: dict | None = None) -> list[tuple[str, float, float, float, float]]:
        env = self.env() if env is None else env
        out = []
        for label, xe, ye, we, he in self.holes:
            vals = []
            for e in (xe, ye, we, he):
                try:
                    vals.append(safe_eval(e, env))
                except Exception:
                    vals.append(float("nan"))
            out.append((label, *vals))
        return out

    # -- Serialisierung -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "outline_is_cut": self.outline_is_cut,
            "variables": self.variables,
            "points": self.points,
            "holes": self.holes,
        }

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Form":
        f = cls(name)
        f.outline_is_cut = bool(d.get("outline_is_cut", True))
        f.variables = [list(row) for row in d.get("variables", DEFAULT_VARIABLES)]
        f.points = [list(row) for row in d.get("points", [["0", "0"]])]
        f.holes = [list(row) for row in d.get("holes", [])]
        return f


# ---------------------------------------------------------------------------
# Presets -- die 4 echten Teile aus footprintScale.py, als Ausdruecke
# nachgebaut (Stand: siehe dortige TONGUE_*/SLOT_*-Konstanten). Dient als
# START-Punkt zum Weiterbasteln, NICHT als Import von dort (bewusst
# eigenstaendig, damit dieses Tool ohne den Rest des Projekts laeuft).
# ---------------------------------------------------------------------------

def _footprint_preset() -> Form:
    f = Form("footprint")
    f.outline_is_cut = False  # nur Skizzenlinie, siehe get_footprint_points
    f.variables = [
        ["width_mm", "75"],
        ["height_mm", "40"],
        ["tongue_width", "5.10"],
        ["tongue_depth", "3.0"],
        ["undersize", "0.1"],
        ["hole_w", "tongue_width - undersize"],
        ["hole_d", "tongue_depth - undersize"],
        ["gap", "(width_mm - tongue_width*2) / 2"],
        ["h0x", "gap/2 + (tongue_width-hole_w)/2"],
        ["h1x", "gap/2 + tongue_width + gap + (tongue_width-hole_w)/2"],
        ["slot_y", "tongue_depth + (tongue_width-hole_w)/2"],
    ]
    f.points = [
        ["0", "0"],
        ["width_mm", "0"],
        ["width_mm", "height_mm"],
        ["0", "height_mm"],
    ]
    f.holes = [
        ["h_slot_left", "h0x", "0", "hole_w", "hole_d"],
        ["h_slot_right", "h1x", "0", "hole_w", "hole_d"],
        ["v_slot_left", "0", "slot_y", "hole_d", "hole_w"],
        ["v_slot_right", "width_mm - hole_d", "slot_y", "hole_d", "hole_w"],
    ]
    return f


def _bottom_plate_preset() -> Form:
    f = Form("bottom_plate")
    f.variables = [
        ["width_mm", "75"],
        ["thickness_mm", "11"],
        ["tongue_width", "5.10"],
        ["tongue_depth", "3.0"],
        ["undersize", "0.1"],
        ["gap", "(width_mm - tongue_width*2) / 2"],
        ["t0x", "gap/2"],
        ["t1x", "gap/2 + tongue_width + gap"],
        ["hole_w", "tongue_depth - undersize"],
        ["hole_h", "tongue_width - undersize"],
        ["hole_y", "(thickness_mm - hole_h)/2"],
        ["gap2", "(width_mm - tongue_depth*2) / 2"],
        ["h0x", "gap2/2 + (tongue_depth-hole_w)/2"],
        ["h1x", "gap2/2 + tongue_depth + gap2 + (tongue_depth-hole_w)/2"],
    ]
    f.points = [
        ["0", "0"],
        ["t0x", "0"],
        ["t0x", "-tongue_depth"],
        ["t0x + tongue_width", "-tongue_depth"],
        ["t0x + tongue_width", "0"],
        ["t1x", "0"],
        ["t1x", "-tongue_depth"],
        ["t1x + tongue_width", "-tongue_depth"],
        ["t1x + tongue_width", "0"],
        ["width_mm", "0"],
        ["width_mm", "thickness_mm"],
        ["0", "thickness_mm"],
    ]
    f.holes = [
        ["side_hole_left", "h0x", "hole_y", "hole_w", "hole_h"],
        ["side_hole_right", "h1x", "hole_y", "hole_w", "hole_h"],
    ]
    return f


def _side_plate_preset(name: str, inner: bool) -> Form:
    f = Form(name)
    f.variables = [
        ["height_mm", "40"],
        ["thickness_mm", "11"],
        ["tongue_width", "5.10"],
        ["tongue_depth", "3.0"],
        ["tongue_margin", "(thickness_mm - tongue_width) / 2"],
        ["bx0", "tongue_depth"],
        ["bx1", "tongue_depth + tongue_width"],
    ]
    if inner:
        f.variables += [
            ["inner_slot_width", "1.6"],
            ["slot_end_margin", "5.7"],
            ["slot_overlap", "0.5"],
            ["slot_right", "height_mm - slot_end_margin"],
            ["slot_left", "slot_right - inner_slot_width"],
            ["slot_top", "thickness_mm/2 + slot_overlap"],
        ]
        f.points = [
            ["0", "tongue_margin"],
            ["0", "tongue_margin + tongue_width"],
            ["tongue_depth", "tongue_margin + tongue_width"],
            ["tongue_depth", "thickness_mm"],
            ["slot_left", "thickness_mm"],
            ["slot_left", "slot_top"],
            ["slot_right", "slot_top"],
            ["slot_right", "thickness_mm"],
            ["height_mm", "thickness_mm"],
            ["height_mm", "0"],
            ["bx1", "0"],
            ["bx1", "-tongue_depth"],
            ["bx0", "-tongue_depth"],
            ["bx0", "0"],
            ["tongue_depth", "tongue_margin"],
        ]
    else:
        f.variables += [
            ["outer_slot_width", "5.0"],
            ["outer_slot_height", "7.0"],
            ["slot_left", "height_mm - outer_slot_width"],
        ]
        f.points = [
            ["0", "tongue_margin"],
            ["0", "tongue_margin + tongue_width"],
            ["tongue_depth", "tongue_margin + tongue_width"],
            ["tongue_depth", "thickness_mm"],
            ["height_mm", "thickness_mm"],
            ["height_mm", "outer_slot_height"],
            ["slot_left", "outer_slot_height"],
            ["slot_left", "0"],
            ["bx1", "0"],
            ["bx1", "-tongue_depth"],
            ["bx0", "-tongue_depth"],
            ["bx0", "0"],
            ["tongue_depth", "tongue_margin"],
        ]
    return f


def _point_segment_distance(px, py, p0, p1) -> float:
    """Abstand (px) vom Punkt (px,py) zur Strecke p0-p1 -- fuer's Erkennen,
    welche Kontur-Strecke am naechsten zu einem Mausklick liegt."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x0 + t * dx, y0 + t * dy
    return math.hypot(px - cx, py - cy)


def build_presets() -> dict[str, Form]:
    return {
        "footprint": _footprint_preset(),
        "bottom_plate": _bottom_plate_preset(),
        "side_plate_outer": _side_plate_preset("side_plate_outer", inner=False),
        "side_plate_inner": _side_plate_preset("side_plate_inner", inner=True),
    }


# ---------------------------------------------------------------------------
# Kleine Hilfsklasse: Treeview mit Inline-Edit per Doppelklick auf editierbare
# Spalten (per column-id-Liste angegeben). Ein Callback bekommt
# (row_index, column_id, new_text) und schreibt es ins Datenmodell zurueck.
# ---------------------------------------------------------------------------
class EditableTreeview(ttk.Treeview):
    def __init__(self, master, editable_cols: set[str], on_edit, **kwargs):
        super().__init__(master, **kwargs)
        self._editable_cols = editable_cols
        self._on_edit = on_edit
        self._editor: tk.Entry | None = None
        self.bind("<Double-1>", self._begin_edit)

    def _begin_edit(self, event):
        row_id = self.identify_row(event.y)
        col_id = self.identify_column(event.x)
        if not row_id or not col_id:
            return
        col_name = self.column(col_id, "id") or self.heading(col_id, "text")
        # identify_column liefert '#N' -- auf den echten Spaltennamen mappen
        cols = self["columns"]
        idx = int(col_id.replace("#", "")) - 1
        if idx < 0 or idx >= len(cols):
            return
        col_name = cols[idx]
        if col_name not in self._editable_cols:
            return
        bbox = self.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        value = self.set(row_id, col_name)
        self._destroy_editor()
        entry = tk.Entry(self)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def commit(_evt=None):
            new_val = entry.get()
            self._destroy_editor()
            row_index = self.index(row_id)
            self._on_edit(row_index, col_name, new_val)

        def cancel(_evt=None):
            self._destroy_editor()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)
        self._editor = entry

    def _destroy_editor(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None


# ---------------------------------------------------------------------------
# Eine Formular-Ansicht: Variablen/Punkte/Loecher-Tabellen links, Canvas-
# Vorschau rechts. Haelt eine Referenz auf sein Form-Objekt und schreibt
# Aenderungen direkt hinein.
# ---------------------------------------------------------------------------
class FormPanel(ttk.Frame):
    def __init__(self, master, form: Form):
        super().__init__(master)
        self.form = form
        self.px_per_mm = 6.0
        self.selected_seg_idx: int | None = None
        self.selected_point_idx: int | None = None
        self._suppress_tree_select = False
        self._build()
        self.refresh_all()

    # -- UI Aufbau --------------------------------------------------------
    def _build(self):
        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 8), pady=4)
        right = ttk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        # -- Variablen --
        ttk.Label(left, text="Variablen (Name = Ausdruck, der Reihe nach ausgewertet)",
                  font=("", 9, "bold")).pack(anchor="w")
        self.var_tree = EditableTreeview(
            left, editable_cols={"name", "expr"}, on_edit=self._edit_variable,
            columns=("name", "expr", "value"), show="headings", height=8, selectmode="browse")
        for c, w, t in (("name", 110, "Name"), ("expr", 150, "Ausdruck"), ("value", 80, "= Wert")):
            self.var_tree.heading(c, text=t)
            self.var_tree.column(c, width=w, anchor="w")
        self.var_tree.pack(fill=tk.X)
        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(2, 10))
        ttk.Button(btns, text="+ Variable", command=self._add_variable).pack(side=tk.LEFT)
        ttk.Button(btns, text="Loeschen", command=lambda: self._delete_selected(self.var_tree, self.form.variables)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="↑", width=3, command=lambda: self._move_selected(self.var_tree, self.form.variables, -1)).pack(side=tk.LEFT)
        ttk.Button(btns, text="↓", width=3, command=lambda: self._move_selected(self.var_tree, self.form.variables, 1)).pack(side=tk.LEFT)

        # -- Punkte (Aussenkontur) --
        top_row = ttk.Frame(left)
        top_row.pack(fill=tk.X)
        ttk.Label(top_row, text="Punkte (Aussenkontur, geschlossen)", font=("", 9, "bold")).pack(side=tk.LEFT)
        self.cut_var = tk.BooleanVar(value=self.form.outline_is_cut)
        ttk.Checkbutton(top_row, text="ist Schnitt (sonst Skizze)", variable=self.cut_var,
                        command=self._toggle_cut).pack(side=tk.RIGHT)
        self.pt_tree = EditableTreeview(
            left, editable_cols={"x", "y"}, on_edit=self._edit_point,
            columns=("idx", "x", "y", "xv", "yv", "seglen"), show="headings", height=10, selectmode="browse")
        for c, w, t in (("idx", 30, "#"), ("x", 90, "x"), ("y", 90, "y"),
                       ("xv", 60, "x="), ("yv", 60, "y="), ("seglen", 70, "Strecke→naechst")):
            self.pt_tree.heading(c, text=t)
            self.pt_tree.column(c, width=w, anchor="w")
        self.pt_tree.pack(fill=tk.X)
        self.pt_tree.bind("<<TreeviewSelect>>", self._on_pt_tree_select)
        btns2 = ttk.Frame(left)
        btns2.pack(fill=tk.X, pady=(2, 10))
        ttk.Button(btns2, text="+ Punkt", command=self._add_point).pack(side=tk.LEFT)
        ttk.Button(btns2, text="Loeschen", command=lambda: self._delete_selected(self.pt_tree, self.form.points)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns2, text="↑", width=3, command=lambda: self._move_selected(self.pt_tree, self.form.points, -1)).pack(side=tk.LEFT)
        ttk.Button(btns2, text="↓", width=3, command=lambda: self._move_selected(self.pt_tree, self.form.points, 1)).pack(side=tk.LEFT)

        # -- Loecher --
        ttk.Label(left, text="Loecher (Rechtecke: Label, x, y, Breite, Hoehe)", font=("", 9, "bold")).pack(anchor="w")
        self.hole_tree = EditableTreeview(
            left, editable_cols={"label", "x", "y", "w", "h"}, on_edit=self._edit_hole,
            columns=("label", "x", "y", "w", "h"), show="headings", height=6, selectmode="browse")
        for c, w, t in (("label", 100, "Label"), ("x", 80, "x"), ("y", 80, "y"), ("w", 70, "Breite"), ("h", 70, "Hoehe")):
            self.hole_tree.heading(c, text=t)
            self.hole_tree.column(c, width=w, anchor="w")
        self.hole_tree.pack(fill=tk.X)
        btns3 = ttk.Frame(left)
        btns3.pack(fill=tk.X, pady=2)
        ttk.Button(btns3, text="+ Loch", command=self._add_hole).pack(side=tk.LEFT)
        ttk.Button(btns3, text="Loeschen", command=lambda: self._delete_selected(self.hole_tree, self.form.holes)).pack(side=tk.LEFT, padx=4)

        # -- Canvas rechts --
        zoom_row = ttk.Frame(right)
        zoom_row.pack(fill=tk.X)
        ttk.Label(zoom_row, text="Zoom:").pack(side=tk.LEFT)
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self._zoom(0.8)).pack(side=tk.LEFT)
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self._zoom(1.25)).pack(side=tk.LEFT)
        self.mouse_pos_lbl = ttk.Label(zoom_row, text="x=-- y=-- mm")
        self.mouse_pos_lbl.pack(side=tk.RIGHT)

        self.seg_info_lbl = ttk.Label(right, text="Klick auf einen Punkt oder eine Linie fuer Details.",
                                      font=("Consolas", 9), foreground="#e8a24a")
        self.seg_info_lbl.pack(fill=tk.X, pady=(2, 4))

        self.canvas = tk.Canvas(right, background="#1b232c", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

    # -- Zoom --------------------------------------------------------------
    def _zoom(self, factor):
        self.px_per_mm = max(1.0, min(40.0, self.px_per_mm * factor))
        self.redraw()

    def _on_mouse_move(self, event):
        mm_x, mm_y = self._screen_to_mm(event.x, event.y)
        self.mouse_pos_lbl.config(text=f"x={mm_x:.2f} y={mm_y:.2f} mm")

    def _finite_points(self):
        pts = self.form.resolved_points(self.form.env())
        return [(x, y) for x, y in pts if x == x and y == y]

    def _on_canvas_click(self, event):
        finite_pts = self._finite_points()
        n = len(finite_pts)
        if n == 0:
            return
        screen_pts = [self._mm_to_screen(x, y) for x, y in finite_pts]

        # Naehe zu einem PUNKT hat Vorrang -- ein Punkt gehoert zu ZWEI
        # Strecken, ihn als "eine Linie" zu markieren waere irrefuehrend
        # (siehe _update_point_info: markiert nur den Punkt selbst).
        best_pt_idx, best_pt_dist = None, 10.0
        for i, (sx, sy) in enumerate(screen_pts):
            d = math.hypot(event.x - sx, event.y - sy)
            if d < best_pt_dist:
                best_pt_dist = d
                best_pt_idx = i
        if best_pt_idx is not None:
            self.selected_point_idx = best_pt_idx
            self.selected_seg_idx = None
            self._sync_tree_selection(best_pt_idx)
            self._update_point_info(finite_pts, best_pt_idx)
            self.redraw()
            return

        # Sonst: naechste STRECKE (nur wenn nicht direkt auf einem Punkt).
        best_idx, best_dist = None, 10.0
        if n >= 2:
            for i in range(n):
                d = _point_segment_distance(event.x, event.y, screen_pts[i], screen_pts[(i + 1) % n])
                if d < best_dist:
                    best_dist = d
                    best_idx = i
        self.selected_seg_idx = best_idx
        self.selected_point_idx = None
        self._sync_tree_selection(None)
        self._update_seg_info(finite_pts, best_idx)
        self.redraw()

    def _on_pt_tree_select(self, _evt=None):
        if self._suppress_tree_select:
            return
        sel = self.pt_tree.selection()
        if not sel:
            return
        idx = self.pt_tree.index(sel[0])
        finite_pts = self._finite_points()
        if idx >= len(finite_pts):
            return
        # Eine Tabellenzeile IST ein Punkt -- also nur den Punkt markieren,
        # nicht eine der beiden Strecken, die an ihm haengen.
        self.selected_point_idx = idx
        self.selected_seg_idx = None
        self._update_point_info(finite_pts, idx)
        self.redraw()

    def _sync_tree_selection(self, point_idx: int | None):
        self._suppress_tree_select = True
        try:
            children = self.pt_tree.get_children()
            if point_idx is not None and point_idx < len(children):
                item = children[point_idx]
                self.pt_tree.selection_set(item)
                self.pt_tree.see(item)
            else:
                self.pt_tree.selection_remove(*children)
        finally:
            self._suppress_tree_select = False

    def _update_point_info(self, finite_pts, idx: int | None):
        if idx is None or not finite_pts:
            self.seg_info_lbl.config(text="Klick auf einen Punkt oder eine Linie fuer Details.")
            return
        n = len(finite_pts)
        x, y = finite_pts[idx]
        px, py = finite_pts[(idx - 1) % n]
        nx, ny = finite_pts[(idx + 1) % n]
        len_in = math.hypot(x - px, y - py)
        len_out = math.hypot(nx - x, ny - y)
        self.seg_info_lbl.config(
            text=f"Punkt #{idx}: ({x:.2f}, {y:.2f})   "
                 f"← von #{(idx - 1) % n}: {len_in:.2f} mm   → zu #{(idx + 1) % n}: {len_out:.2f} mm")

    def _update_seg_info(self, finite_pts, seg_idx: int | None):
        if seg_idx is None or not finite_pts:
            self.seg_info_lbl.config(text="Klick auf einen Punkt oder eine Linie fuer Details.")
            return
        n = len(finite_pts)
        x0, y0 = finite_pts[seg_idx]
        x1, y1 = finite_pts[(seg_idx + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        closing = " (Schliess-Strecke)" if seg_idx == n - 1 else ""
        self.seg_info_lbl.config(
            text=f"Strecke #{seg_idx}{closing}: ({x0:.2f}, {y0:.2f}) → ({x1:.2f}, {y1:.2f})   "
                 f"dx={dx:.2f}  dy={dy:.2f}   Laenge={length:.2f} mm   Winkel={angle:.1f}°")

    # -- Variable-Tabelle ----------------------------------------------------
    def _add_variable(self):
        self.form.variables.append(["var", "0"])
        self.refresh_all()

    def _edit_variable(self, row_index, col_name, new_val):
        if row_index >= len(self.form.variables):
            return
        pos = {"name": 0, "expr": 1}[col_name]
        self.form.variables[row_index][pos] = new_val
        self.refresh_all()

    # -- Punkt-Tabelle --------------------------------------------------------
    def _add_point(self):
        self.form.points.append(["0", "0"])
        self.refresh_all()

    def _edit_point(self, row_index, col_name, new_val):
        if row_index >= len(self.form.points):
            return
        pos = {"x": 0, "y": 1}[col_name]
        self.form.points[row_index][pos] = new_val
        self.refresh_all()

    # -- Loch-Tabelle -----------------------------------------------------
    def _add_hole(self):
        self.form.holes.append([f"hole_{len(self.form.holes) + 1}", "0", "0", "5", "5"])
        self.refresh_all()

    def _edit_hole(self, row_index, col_name, new_val):
        if row_index >= len(self.form.holes):
            return
        pos = {"label": 0, "x": 1, "y": 2, "w": 3, "h": 4}[col_name]
        self.form.holes[row_index][pos] = new_val
        self.refresh_all()

    # -- generisch: loeschen/verschieben -----------------------------------
    def _delete_selected(self, tree, data_list):
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        if 0 <= idx < len(data_list):
            del data_list[idx]
        self.refresh_all()

    def _move_selected(self, tree, data_list, direction):
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        new_idx = idx + direction
        if 0 <= new_idx < len(data_list):
            data_list[idx], data_list[new_idx] = data_list[new_idx], data_list[idx]
        self.refresh_all()

    def _toggle_cut(self):
        self.form.outline_is_cut = self.cut_var.get()
        self.redraw()

    # -- Neu zeichnen / Tabellen fuellen --------------------------------------
    def refresh_all(self):
        env = self.form.env()

        self.var_tree.delete(*self.var_tree.get_children())
        for name, expr in self.form.variables:
            val = env.get(name, float("nan"))
            self.var_tree.insert("", tk.END, values=(name, expr, f"{val:.3f}" if val == val else "?"))

        pts = self.form.resolved_points(env)
        self.pt_tree.delete(*self.pt_tree.get_children())
        n = len(pts)
        for i, ((xe, ye), (xv, yv)) in enumerate(zip(self.form.points, pts)):
            if n >= 2:
                nxt = pts[(i + 1) % n]
                seglen = math.dist((xv, yv), nxt) if xv == xv and yv == yv else float("nan")
            else:
                seglen = float("nan")
            self.pt_tree.insert("", tk.END, values=(
                i, xe, ye,
                f"{xv:.2f}" if xv == xv else "?",
                f"{yv:.2f}" if yv == yv else "?",
                f"{seglen:.2f}" if seglen == seglen else "?"))

        holes = self.form.resolved_holes(env)
        self.hole_tree.delete(*self.hole_tree.get_children())
        for (label, xe, ye, we, he), (_, xv, yv, wv, hv) in zip(self.form.holes, holes):
            self.hole_tree.insert("", tk.END, values=(label, xe, ye, we, he))

        finite_pts = [(x, y) for x, y in pts if x == x and y == y]
        if self.selected_seg_idx is not None and self.selected_seg_idx >= len(finite_pts):
            self.selected_seg_idx = None
        if self.selected_point_idx is not None and self.selected_point_idx >= len(finite_pts):
            self.selected_point_idx = None
        if self.selected_point_idx is not None:
            self._sync_tree_selection(self.selected_point_idx)
            self._update_point_info(finite_pts, self.selected_point_idx)
        elif self.selected_seg_idx is not None:
            self._sync_tree_selection(None)
            self._update_seg_info(finite_pts, self.selected_seg_idx)
        else:
            self._sync_tree_selection(None)
            self._update_point_info(finite_pts, None)

        self.redraw()

    # -- Koordinaten-Mapping -------------------------------------------------
    def _mm_to_screen(self, x, y):
        return (self._ox + x * self.px_per_mm, self._oy - y * self.px_per_mm)

    def _screen_to_mm(self, sx, sy):
        if self.px_per_mm == 0:
            return 0.0, 0.0
        return ((sx - self._ox) / self.px_per_mm, (self._oy - sy) / self.px_per_mm)

    def redraw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 800
        h = c.winfo_height() or 600

        env = self.form.env()
        pts = self.form.resolved_points(env)
        holes = self.form.resolved_holes(env)

        finite_pts = [(x, y) for x, y in pts if x == x and y == y]
        all_x = [x for x, _ in finite_pts] + [x for _, x, _, ww, _ in holes if x == x] + [x + ww for _, x, _, ww, _ in holes if x == x and ww == ww]
        all_y = [y for _, y in finite_pts] + [y for _, _, y, _, hh in holes if y == y] + [y + hh for _, _, y, _, hh in holes if y == y and hh == hh]
        if not all_x or not all_y:
            all_x, all_y = [0, 10], [0, 10]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        margin_mm = 8
        bbox_w = max(max_x - min_x, 1) + margin_mm * 2
        bbox_h = max(max_y - min_y, 1) + margin_mm * 2
        fit_scale = min((w - 20) / bbox_w, (h - 20) / bbox_h) if bbox_w and bbox_h else 6.0
        if fit_scale > 0 and abs(self.px_per_mm - 6.0) < 1e-9:
            # nur beim allerersten Zeichnen automatisch einpassen, danach
            # bleibt der User-Zoom (px_per_mm) massgeblich
            pass
        self._ox = w / 2 - (min_x + max_x) / 2 * self.px_per_mm
        self._oy = h / 2 + (min_y + max_y) / 2 * self.px_per_mm

        self._draw_grid(w, h)

        # Loecher zuerst (unter der Kontur)
        for label, x, y, ww, hh in holes:
            if x != x or y != y or ww != ww or hh != hh:
                continue
            p0 = self._mm_to_screen(x, y)
            p1 = self._mm_to_screen(x + ww, y + hh)
            x0, y0 = min(p0[0], p1[0]), min(p0[1], p1[1])
            x1, y1 = max(p0[0], p1[0]), max(p0[1], p1[1])
            c.create_rectangle(x0, y0, x1, y1, fill="#e8a24a", stipple="gray50", outline="#e8a24a", width=1.5)
            c.create_text((x0 + x1) / 2, y0 - 8, text=f"{label} {ww:.2f}×{hh:.2f}",
                         fill="#e8a24a", font=("Consolas", 8), anchor="s")

        # Aussenkontur
        n = len(finite_pts)
        if n >= 2:
            color = "#7fd4d9" if self.form.outline_is_cut else "#8aa0ab"
            dash = () if self.form.outline_is_cut else (4, 3)
            screen_pts = [self._mm_to_screen(x, y) for x, y in finite_pts]
            for i in range(n):
                p0 = screen_pts[i]
                p1 = screen_pts[(i + 1) % n]
                is_closing = (i == n - 1)
                c.create_line(*p0, *p1, fill=color, width=2,
                             dash=(3, 3) if (is_closing or not self.form.outline_is_cut) else None)
                mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                seglen = math.dist(finite_pts[i], finite_pts[(i + 1) % n])
                c.create_text(mx, my - 9, text=f"{seglen:.2f}", fill="#c8d6dc", font=("Consolas", 8))
            for x, y in finite_pts:
                sx, sy = self._mm_to_screen(x, y)
                c.create_oval(sx - 2.5, sy - 2.5, sx + 2.5, sy + 2.5, fill="#f2765c", outline="")

            # Ausgewaehlte Strecke hervorheben (ueber allem anderen)
            if self.selected_seg_idx is not None and 0 <= self.selected_seg_idx < n:
                i = self.selected_seg_idx
                p0, p1 = screen_pts[i], screen_pts[(i + 1) % n]
                c.create_line(*p0, *p1, fill="#ffd166", width=4)
                for sx, sy in (p0, p1):
                    c.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, outline="#ffd166", width=2)

            # Ausgewaehlten PUNKT hervorheben -- NUR der Punkt (ein Ring),
            # keine der beiden angrenzenden Strecken, da ein Punkt zu ZWEI
            # Strecken gehoert und eine davon hervorzuheben irrefuehrend waere.
            if self.selected_point_idx is not None and 0 <= self.selected_point_idx < n:
                sx, sy = screen_pts[self.selected_point_idx]
                c.create_oval(sx - 7, sy - 7, sx + 7, sy + 7, outline="#ffd166", width=2.5)

        # Ursprung markieren
        ox, oy = self._mm_to_screen(0, 0)
        c.create_line(ox - 6, oy, ox + 6, oy, fill="#556472")
        c.create_line(ox, oy - 6, ox, oy + 6, fill="#556472")

    def _draw_grid(self, w, h):
        c = self.canvas
        step_mm = 5 if self.px_per_mm >= 4 else 10
        min_mm_x, _ = self._screen_to_mm(0, 0)
        max_mm_x, _ = self._screen_to_mm(w, 0)
        _, min_mm_y = self._screen_to_mm(0, h)
        _, max_mm_y = self._screen_to_mm(0, 0)
        x = math.floor(min_mm_x / step_mm) * step_mm
        while x <= max_mm_x:
            sx, _ = self._mm_to_screen(x, 0)
            c.create_line(sx, 0, sx, h, fill="#242f3a")
            x += step_mm
        y = math.floor(min_mm_y / step_mm) * step_mm
        while y <= max_mm_y:
            _, sy = self._mm_to_screen(0, y)
            c.create_line(0, sy, w, sy, fill="#242f3a")
            y += step_mm


# ---------------------------------------------------------------------------
# App: Notebook aus FormPanels + Toolbar (Neu/Umbenennen/Loeschen/Laden/
# Speichern/Presets/DXF-Export).
# ---------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Outline Designer")
        self.geometry("1280x820")
        self.forms: dict[str, Form] = {}
        self.panels: dict[str, FormPanel] = {}

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(toolbar, text="Presets laden (4 echte Teile)", command=self.load_presets).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="+ Neue Form", command=self.new_form).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(toolbar, text="Form umbenennen", command=self.rename_current_form).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Form loeschen", command=self.delete_current_form).pack(side=tk.LEFT, padx=4)
        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="JSON laden...", command=self.load_json).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="JSON speichern...", command=self.save_json).pack(side=tk.LEFT, padx=4)
        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="DXF-Vorschau exportieren (aktuelle Form)", command=self.export_dxf).pack(side=tk.LEFT)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        self.load_presets()

    # -- Form-Verwaltung -----------------------------------------------------
    def _add_form(self, form: Form):
        self.forms[form.name] = form
        panel = FormPanel(self.notebook, form)
        self.panels[form.name] = panel
        self.notebook.add(panel, text=form.name)
        self.notebook.select(panel)

    def _current_name(self) -> str | None:
        sel = self.notebook.select()
        if not sel:
            return None
        for name, panel in self.panels.items():
            if str(panel) == sel:
                return name
        return None

    def new_form(self):
        name = simpledialog.askstring("Neue Form", "Name der neuen Form:", parent=self)
        if not name:
            return
        if name in self.forms:
            messagebox.showerror("Fehler", f"Form '{name}' existiert schon.")
            return
        self._add_form(Form(name))

    def rename_current_form(self):
        old_name = self._current_name()
        if old_name is None:
            return
        new_name = simpledialog.askstring("Umbenennen", "Neuer Name:", initialvalue=old_name, parent=self)
        if not new_name or new_name == old_name or new_name in self.forms:
            return
        form = self.forms.pop(old_name)
        panel = self.panels.pop(old_name)
        form.name = new_name
        self.forms[new_name] = form
        self.panels[new_name] = panel
        self.notebook.tab(panel, text=new_name)

    def delete_current_form(self):
        name = self._current_name()
        if name is None:
            return
        if not messagebox.askyesno("Loeschen", f"Form '{name}' wirklich loeschen?"):
            return
        panel = self.panels.pop(name)
        self.forms.pop(name)
        self.notebook.forget(panel)

    def load_presets(self):
        for name in list(self.forms.keys()):
            self.panels.pop(name).destroy()
            self.forms.pop(name)
        for form in build_presets().values():
            self._add_form(form)

    # -- Speichern/Laden ------------------------------------------------------
    def save_json(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            title="Formen speichern als...")
        if not path:
            return
        data = {"forms": {name: form.to_dict() for name, form in self.forms.items()}}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Gespeichert", f"Geschrieben nach:\n{path}")

    def load_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], title="Formen laden...")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for name in list(self.forms.keys()):
            self.panels.pop(name).destroy()
            self.forms.pop(name)
        for name, d in data.get("forms", {}).items():
            self._add_form(Form.from_dict(name, d))

    # -- DXF-Vorschau -----------------------------------------------------
    def export_dxf(self):
        if ezdxf is None:
            messagebox.showerror("ezdxf fehlt", "pip install ezdxf, dann erneut versuchen.")
            return
        name = self._current_name()
        if name is None:
            return
        form = self.forms[name]
        env = form.env()
        pts = [(x, y) for x, y in form.resolved_points(env) if x == x and y == y]
        holes = [(x, y, w, h) for _, x, y, w, h in form.resolved_holes(env) if x == x and y == y and w == w and h == h]
        if len(pts) < 2:
            messagebox.showerror("Fehler", "Zu wenige gueltige Punkte.")
            return

        path = filedialog.asksaveasfilename(defaultextension=".dxf", filetypes=[("DXF", "*.dxf")],
                                            title="DXF speichern als...", initialfile=f"{name}.dxf")
        if not path:
            return

        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 4
        msp = doc.modelspace()
        for layer, color in (("OUTLINE", 1), ("PINS", 1), ("SKETCH", 8)):
            if layer not in doc.layers:
                doc.layers.add(layer, color=color)
        outline_layer = "OUTLINE" if form.outline_is_cut else "SKETCH"
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": outline_layer, "color": 1 if form.outline_is_cut else 8})
        for x, y, w, h in holes:
            rect = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            msp.add_lwpolyline(rect, close=True, dxfattribs={"layer": "PINS", "color": 1})
        doc.saveas(path)
        messagebox.showinfo("Exportiert", f"Geschrieben nach:\n{path}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
