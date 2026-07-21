#!/usr/bin/env python3
"""
Window Tool
Ein Werkzeug: Bild reinziehen -> OpenAI markiert Fenster -> rot/gruen-Masken
werden erzeugt -> per Klick Glasscheiben (Flutfuellung) und Fensterrahmen
auswaehlen -> JSON (Fensterrahmen) + SVG (Glasscheiben) werden automatisch
gespeichert. Startet standardmaessig mit der Haeuserliste aus public/houses
(je EIN Unterordner pro Haus, siehe DEFAULT_HOUSES_DIR).

Abhaengigkeiten: siehe requirements.txt
"""

import json
import queue
import re
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    print("Fehler: Pillow fehlt.  Bitte: pip install Pillow")
    sys.exit(1)

try:
    import cv2
    import numpy as np
except ImportError:
    print("Fehler: opencv-python/numpy fehlen.  Bitte: pip install opencv-python numpy")
    sys.exit(1)

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except ImportError:
    _DND = False

from calcImages import (
    OPENAI_PROMPT, OPENAI_MODEL, GreenParams,
    get_annotated, _extract_color_mask, _states_dir,
    prep_wall, flood_region, grow_rect_through_wall,
)
import pdfHouse

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.pdf'}
# Jedes Haus liegt in seinem EIGENEN Unterordner (public/houses/<name>/<name>.EXT
# + <name>.json usw.) -- siehe _sync_houses_json fuer den Autosync von
# houses.json und ledBatchEditor.App._export_project fuer die Export-Seite
# dieser Struktur.
DEFAULT_HOUSES_DIR = Path(__file__).resolve().parent.parent / 'public' / 'houses'
# Zwei-Ebenen-PDF: Bild-Ebene ("Bild") + Kontur/Scheiben-Ebene, wird beim
# Speichern als <name>.panes.pdf neben dem Quell-PDF abgelegt -- zaehlt selbst
# NICHT als eigenes Haus (siehe _fill_tree-Ausschluss).
EXCLUDE_SUFFIXES = ('._annotated.png', '._redmask.png', '._greenmask.png', '.panes.pdf')

# Klicks, die mehr als diesen Anteil der Bildflaeche fluten, gelten als
# "kein geschlossener Bereich" und werden verworfen.
MAX_FILL_AREA_FRACTION = 0.6

# Eine echte, rechteckige Fenster-/Scheiben-Flaeche ist fast vollstaendig
# gefuellt (Pixelzahl nahe an der Flaeche ihrer Bounding-Box). Eine
# Flutfuellung, die stattdessen um mehrere Fenster herum in den Hintergrund
# entkommt, hat eine deutlich niedrigere Fuellrate relativ zu ihrer (dann
# sehr grossen, unregelmaessigen) Bounding-Box. Diese Pruefung ist robuster
# als MAX_FILL_AREA_FRACTION allein: bei geringer Fensterdichte im Bild kann
# der Hintergrund zufaellig knapp UNTER dem Flaechen-Limit bleiben, obwohl er
# eindeutig kein einzelnes Fenster ist.
MIN_FILL_RATIO = 0.85

C = {
    'bg':       '#1e293b',
    'bg_dark':  '#0f172a',
    'bg_panel': '#1f2937',
    'border':   '#334155',
    'text':     '#e2e8f0',
    'muted':    '#94a3b8',
    'dim':      '#6b7280',
    'blue':     '#3b82f6',
    'blue_dim': '#1d4ed8',
    'blue_sel': '#1e3a5f',
    'green':    '#22c55e',
    'red':      '#f87171',
}


# ─────────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Misc | None = None, parent: tk.Misc | None = None,
                 is_active=None):
        """
        root/parent: Ohne Argumente laeuft das Tool als eigenes Fenster.
        In der kombinierten Tab-Ansicht (siehe _launch_combined) wird ein
        gemeinsames `root` und ein Tab-Frame als `parent` uebergeben;
        `is_active` meldet dann, ob dieser Tab gerade sichtbar ist (damit
        Tastatur-Kuerzel nicht im inaktiven Tab ausgefuehrt werden).
        """
        if root is None:
            Root = TkinterDnD.Tk if _DND else tk.Tk
            root = Root()
            root.title("Window Tool")
            root.geometry("1300x760")
            root.minsize(800, 500)
            root.configure(bg=C['bg'])
        self.root = root
        self.container = parent if parent is not None else root
        self._is_active = is_active if is_active is not None else (lambda: True)

        # Anzeige-Einstellungen (linkes Panel)
        self.show_color = tk.BooleanVar(master=root, value=False)  # Foto farbig statt grau
        self.show_wins  = tk.BooleanVar(master=root, value=True)   # gelbe Fenster-Rechtecke
        self.show_panes = tk.BooleanVar(master=root, value=True)   # blaue Glasscheiben-Rechtecke

        # State
        self.img_orig: Image.Image | None = None
        self.img_path: Path | None = None
        self.json_path: Path | None = None
        self.svg_path: Path | None = None
        self.dir_path: Path | None = None
        self.wins: list[dict] = []      # [{'x','y','w','h'}, ...]  -> JSON (Fensterrahmen)
        self.panes: list[dict] = []     # [{'x','y','w','h'}, ...]  -> SVG  (Glasscheiben)
        self.sel_idx = -1
        self._cards: list[dict] = []    # parallel zu self.wins: Widget-Referenzen der Liste

        # Bei PDF-Quellen (siehe pdfHouse.py): die von Hand nachgezeichnete
        # Gebaeude-Kontur, in Bild-Pixel-Koordinaten -- rein visuelle
        # Referenz-Ebene, IMMER sichtbar, NICHT editierbar (kein Klick-
        # Handling dafuer). Bei JPG/PNG-Quellen bleibt sie leer.
        self.outline_polylines: list = []
        self._outline_items: list = []  # Canvas-Line-Item-IDs, parallel zu outline_polylines

        # Fenstererkennung (rot/gruen Wandmasken aus der OpenAI-Annotation)
        self.red_wall = None
        self.green_wall = None
        self._detecting = False
        self._detect_queue: queue.Queue = queue.Queue()
        self._batch_running = False   # Positionen einfuegen / Raster-Scan laeuft gerade
        self._batch_queue: queue.Queue = queue.Queue()
        self._status_after = None     # laufender Auto-Ausblenden-Timer der Statuszeile

        # Viewport
        self.zoom = 1.0
        self.off_x = 0.0
        self.off_y = 0.0

        # Interaction
        self._space = False
        self._pan_ref: tuple | None = None
        self._draw_a: tuple | None = None
        self._draw_b: tuple | None = None

        # Bild-Cache: gepufferter (etwas groesserer als sichtbarer) Bildausschnitt,
        # damit Panning/Verschieben nicht bei jedem Mausereignis neu zuschneidet+skaliert.
        # _display_img ist das Bild, das tatsaechlich zugeschnitten/skaliert wird:
        # ohne Overlay einfach img_orig, mit Overlay EINMALIG (bei der Erkennung,
        # nicht bei jedem Render) hineingeblendet -- ein RGBA-Overlay separat pro
        # Zoomschritt zu skalieren ist auf grossen Fotos sehr teuer und profitiert
        # ausserdem nicht von PILs reducing_gap-Beschleunigung (siehe _poll_detect).
        self._display_img: Image.Image | None = None
        self._overlay_pil: Image.Image | None = None   # RGBA-Linien der Erkennung (gelb/blau)
        self._cache_tk: ImageTk.PhotoImage | None = None
        self._render_cache: dict | None = None   # {'zoom','x0','y0','x1','y1'} des gepufferten Bereichs
        self._render_pending = False

        # Persistente Canvas-Items: werden per coords()/itemconfig() aktualisiert statt
        # bei jedem Render geloescht+neu erstellt zu werden (sonst sehr langsam bei
        # vielen markierten Fenstern/Scheiben, siehe _redraw_windows/_redraw_panes).
        self._img_item: int | None = None
        self._img_state: tuple | None = None
        self._win_items: list[dict] = []   # parallel zu self.wins: [{'rect': id, 'text': id, 'state'}, ...]
        self._pane_items: list[dict] = []  # parallel zu self.panes: [{'id','state'}, ...]
        self._preview_id: int | None = None

        self._save_after = None

        self._style()
        self._build()
        self._bind()
        self._open_default_folder()

    # ── Style ──────────────────────────────────────────────────────────────

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.', background=C['bg'], foreground=C['text'], font=('Segoe UI', 9))
        s.configure('TFrame', background=C['bg'])
        s.configure('TNotebook', background=C['bg_dark'], borderwidth=0)
        s.configure('TNotebook.Tab', background=C['bg_panel'], foreground=C['muted'],
                    padding=(16, 7), borderwidth=0)
        s.map('TNotebook.Tab',
              background=[('selected', C['bg'])],
              foreground=[('selected', C['text'])])
        s.configure('TLabel', background=C['bg'], foreground=C['text'])
        s.configure('TButton', background=C['border'], foreground=C['text'],
                    relief='flat', borderwidth=0, padding=(7, 3), focuscolor='none')
        s.map('TButton',
              background=[('active', '#475569'), ('pressed', '#64748b')],
              relief=[('active', 'flat')])
        s.configure('TScrollbar', background=C['border'], troughcolor=C['bg_dark'],
                    arrowcolor=C['muted'], borderwidth=0, relief='flat')
        s.configure('Treeview', background=C['bg_dark'], foreground=C['text'],
                    fieldbackground=C['bg_dark'], borderwidth=0, rowheight=22)
        s.configure('Treeview.Heading', background=C['bg'], foreground=C['muted'],
                    font=('Segoe UI', 8), relief='flat')
        s.map('Treeview',
              background=[('selected', '#1e40af')],
              foreground=[('selected', 'white')])

    # ── Build UI ───────────────────────────────────────────────────────────

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────
        tb = tk.Frame(self.container, bg=C['bg_dark'], height=44)
        tb.pack(side='top', fill='x')
        tb.pack_propagate(False)

        ttk.Button(tb, text='Haus öffnen',   command=self._open_file).pack(side='left', padx=(8, 2), pady=6)
        ttk.Button(tb, text='Ordner öffnen', command=self._open_folder).pack(side='left', padx=2, pady=6)
        tk.Frame(tb, bg=C['border'], width=1).pack(side='left', fill='y', padx=8, pady=8)

        self._v_name = tk.StringVar(value='Kein Bild geöffnet')
        tk.Label(tb, textvariable=self._v_name, bg=C['bg_dark'],
                 fg=C['muted'], font=('Segoe UI', 9)).pack(side='left')

        self._v_status = tk.StringVar()
        self._lbl_status = tk.Label(tb, textvariable=self._v_status,
                                    bg=C['bg_dark'], font=('Segoe UI', 9))
        self._lbl_status.pack(side='left', padx=8)

        tk.Frame(tb, bg=C['border'], width=1).pack(side='right', fill='y', padx=8, pady=8)
        ttk.Button(tb, text='Anpassen', command=self._fit).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' + ',      command=self._zoom_in).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' − ',      command=self._zoom_out).pack(side='right', padx=2, pady=6)
        tk.Label(tb, text='Zoom:', bg=C['bg_dark'],
                 fg=C['dim'], font=('Segoe UI', 9)).pack(side='right', padx=(0, 2))

        # ── Main ─────────────────────────────────────────────────────────
        main = tk.Frame(self.container, bg=C['bg'])
        main.pack(fill='both', expand=True)

        # Left panel
        left = tk.Frame(main, bg=C['bg'], width=234)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)

        lh = tk.Frame(left, bg=C['bg_dark'], height=32)
        lh.pack(fill='x')
        lh.pack_propagate(False)
        tk.Label(lh, text='Fenster', bg=C['bg_dark'], fg=C['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8, pady=6)
        self._v_count = tk.StringVar(value='0')
        tk.Label(lh, textvariable=self._v_count, bg=C['border'], fg=C['muted'],
                 font=('Segoe UI', 8), padx=4).pack(side='right', padx=6, pady=8)

        tk.Frame(left, bg=C['border'], height=1).pack(fill='x')

        help_txt = ('Klick = Glasscheibe per Flutfuellung\n'
                    'Ziehen = Fenster von Hand zeichnen\n'
                    'Rechtsklick = Scheibe/Fenster entfernen')
        tk.Label(left, text=help_txt, bg=C['bg'], fg=C['dim'],
                 font=('Segoe UI', 8), justify='left').pack(fill='x', padx=8, pady=6)
        tk.Frame(left, bg=C['border'], height=1).pack(fill='x')

        # Anzeige-Einstellungen
        opts = tk.Frame(left, bg=C['bg'])
        opts.pack(fill='x', padx=6, pady=4)
        tk.Label(opts, text='Anzeige', bg=C['bg'], fg=C['muted'],
                 font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=2)

        def _chk(text, var, command):
            tk.Checkbutton(opts, text=text, variable=var, command=command,
                           bg=C['bg'], fg=C['text'], selectcolor=C['bg_dark'],
                           activebackground=C['bg'], activeforeground=C['text'],
                           font=('Segoe UI', 9), anchor='w',
                           highlightthickness=0, bd=0).pack(fill='x', padx=2)

        _chk('Farbe anzeigen',       self.show_color, self._update_display_img)
        _chk('Fenster anzeigen',     self.show_wins,  self._request_render)
        _chk('Glasscheiben anzeigen', self.show_panes, self._request_render)
        tk.Frame(left, bg=C['border'], height=1).pack(fill='x')

        # Scrollable window list
        wrap = tk.Frame(left, bg=C['bg'])
        wrap.pack(fill='both', expand=True)
        self._lcanvas = tk.Canvas(wrap, bg=C['bg'], highlightthickness=0)
        lsb = ttk.Scrollbar(wrap, orient='vertical', command=self._lcanvas.yview)
        self._list_frame = tk.Frame(self._lcanvas, bg=C['bg'])
        self._list_frame.bind('<Configure>',
            lambda e: self._lcanvas.configure(scrollregion=self._lcanvas.bbox('all')))
        self._lcanvas.create_window((0, 0), window=self._list_frame, anchor='nw', tags='f')
        self._lcanvas.configure(yscrollcommand=lsb.set)
        self._lcanvas.bind('<Configure>',
            lambda e: self._lcanvas.itemconfig('f', width=e.width))
        self._lcanvas.bind('<MouseWheel>',
            lambda e: self._lcanvas.yview_scroll(-(e.delta // 120), 'units'))
        self._lcanvas.pack(side='left', fill='both', expand=True)
        lsb.pack(side='right', fill='y')

        # Divider
        tk.Frame(main, bg=C['border'], width=1).pack(side='left', fill='y')

        # Canvas
        self.cv = tk.Canvas(main, bg=C['bg_dark'], highlightthickness=0, cursor='crosshair')
        self.cv.pack(side='left', fill='both', expand=True)

        # Schwebendes Werkzeug-Panel oben rechts UEBER dem Canvas (statt in
        # der oberen Toolbar) -- bei schmalerem Fenster wurden die Fenster-
        # Erkennungs-Buttons dort abgeschnitten. place() mit relx/rely haelt
        # das Panel automatisch in der Ecke (kein <Configure>-Binding
        # noetig). Als Kind DES Canvas liegt es automatisch ueber allem, was
        # der Canvas zeichnet, bleibt aber normal klickbar.
        tools_panel = tk.Frame(self.cv, bg=C['bg_panel'], bd=1, relief='solid')
        tools_panel.place(relx=1.0, rely=0.0, x=-10, y=10, anchor='ne')

        def _tool_action(text, command):
            btn = ttk.Button(tools_panel, text=text, command=command, takefocus=0)
            btn.pack(fill='x', padx=2, pady=1)
            return btn

        self._btn_detect_new = _tool_action('Fenster erkennen', lambda: self._detect_windows())
        self._btn_detect = _tool_action('Fenster neu erkennen', lambda: self._detect_windows(force=True))
        self._btn_recolor = _tool_action('Neu einfärben (S/W → OpenAI)',
                                         lambda: self._detect_windows(force=True, grayscale=True))
        _tool_action('Positionen einfügen', self._open_paste_dialog)
        _tool_action('Raster-Scan', self._open_grid_dialog)

        # Right panel (Ordner)
        self._rsep = tk.Frame(main, bg=C['border'], width=1)
        self._rpanel = tk.Frame(main, bg=C['bg'], width=244)
        self._rpanel.pack_propagate(False)

        rh = tk.Frame(self._rpanel, bg=C['bg_dark'], height=32)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        self._lbl_folder = tk.Label(rh, text='Ordner', bg=C['bg_dark'], fg=C['text'],
                                    font=('Segoe UI', 9, 'bold'))
        self._lbl_folder.pack(side='left', padx=8, pady=6)
        tk.Frame(self._rpanel, bg=C['border'], height=1).pack(fill='x')

        tw = tk.Frame(self._rpanel, bg=C['bg'])
        tw.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tw, selectmode='browse', show='tree')
        tsb = ttk.Scrollbar(tw, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        tsb.pack(side='right', fill='y')

        self._render_cv()
        self._render_list()

    # ── Bindings ──────────────────────────────────────────────────────────

    def _bind(self):
        # add='+': im Tab-Verbund teilen sich mehrere Apps dasselbe root --
        # ohne '+' wuerde die zweite App die Tastatur-Bindings der ersten ersetzen.
        self.root.bind('<KeyPress-space>',   self._kb_space_dn, add='+')
        self.root.bind('<KeyRelease-space>', self._kb_space_up, add='+')
        self.root.bind('<Delete>',           self._kb_del,      add='+')
        self.root.bind('<BackSpace>',        self._kb_del,      add='+')
        self.root.bind('<Escape>',           self._kb_esc,      add='+')

        self.cv.bind('<ButtonPress-1>',   self._cv_dn)
        self.cv.bind('<B1-Motion>',       self._cv_mv)
        self.cv.bind('<ButtonRelease-1>', self._cv_up)
        self.cv.bind('<ButtonPress-3>',   self._cv_right_click)
        self.cv.bind('<ButtonPress-2>',   self._pan_dn)
        self.cv.bind('<B2-Motion>',       self._pan_mv)
        self.cv.bind('<ButtonRelease-2>', self._pan_up)
        self.cv.bind('<MouseWheel>',      self._scroll)
        self.cv.bind('<Configure>',       lambda _: self._request_render())

        self.tree.bind('<ButtonRelease-1>',  self._tree_click)
        self.tree.bind('<<TreeviewOpen>>',   self._tree_open)

        if _DND and hasattr(self.cv, 'drop_target_register'):
            try:
                self.cv.drop_target_register(DND_FILES)
                self.cv.dnd_bind('<<Drop>>', self._dnd_drop)
            except Exception:
                pass  # root ohne DnD-Unterstuetzung (z.B. extern erstellt)

    # ── Canvas rendering ──────────────────────────────────────────────────

    def _render_cv(self):
        """
        Aktualisiert die Canvas-Anzeige. Statt bei jedem Aufruf alles zu loeschen
        und neu zu zeichnen, werden persistente Canvas-Items wiederverwendet und
        nur per coords()/itemconfig() aktualisiert -- das ist deutlich billiger
        als delete+create, vor allem bei vielen markierten Fenstern/Scheiben.
        Teure Arbeit (PIL-Crop/Resize des Bildausschnitts) passiert weiterhin nur,
        wenn sich Zoom oder Sichtbereich tatsaechlich geaendert haben (_redraw_image).
        """
        W = self.cv.winfo_width()  or 800
        H = self.cv.winfo_height() or 600

        if not self.img_orig:
            self.cv.delete('all')
            self._img_item = self._preview_id = None
            self._img_state = None
            self._win_items = []
            self._pane_items = []
            self._outline_items = []
            self.cv.create_text(W // 2, H // 2,
                text='Bild per Drag & Drop ablegen\noder "Bild öffnen" klicken',
                fill=C['dim'], font=('Segoe UI', 12), justify='center')
            return

        self._redraw_image(W, H)
        self._redraw_outline()
        self._redraw_windows()
        self._redraw_panes()
        self._update_preview()

        # Stapelreihenfolge sicherstellen (billig: ein Tcl-Aufruf pro Ebene,
        # unabhaengig von der Anzahl Items). outlinelayer bewusst UNTER den
        # Marker-Ebenen -- reine Referenz, die Fenster-/Scheiben-Markierungen
        # sollen weiterhin klar erkennbar obenauf liegen.
        self.cv.tag_raise('outlinelayer')
        self.cv.tag_raise('winlayer')
        self.cv.tag_raise('panelayer')
        self.cv.tag_raise('previewlayer')

    def _redraw_outline(self):
        """Zeichnet die aus dem PDF importierte Gebaeude-Kontur (siehe
        pdfHouse.load_pdf_house) als feste Referenz-Ebene -- rein visuell,
        OHNE Klick-Handling: die eigentliche Fenster-/Scheiben-Markierung
        arbeitet weiterhin per Flutfuellung auf den Bildpixeln, nicht per
        Canvas-Item-Hit-Test, daher kann dieses Overlay gar nicht "editiert"
        werden. Bei JPG/PNG-Quellen ist outline_polylines leer -> keine Linien."""
        while len(self._outline_items) < len(self.outline_polylines):
            self._outline_items.append(
                self.cv.create_line(0, 0, 0, 0, fill='#f97316', width=2,
                                    dash=(5, 3), tags='outlinelayer'))
        while len(self._outline_items) > len(self.outline_polylines):
            self.cv.delete(self._outline_items.pop())

        for item_id, pts in zip(self._outline_items, self.outline_polylines):
            flat = []
            for ix, iy in pts:
                flat.append(self.off_x + ix * self.zoom)
                flat.append(self.off_y + iy * self.zoom)
            if len(flat) >= 4:
                self.cv.coords(item_id, *flat)

    def _redraw_image(self, W: int, H: int):
        # Nur den sichtbaren Ausschnitt zuschneiden und skalieren – sonst wird beim
        # Reinzoomen das GESAMTE Originalbild auf die Zoom-Aufloesung hochskaliert
        # (bei grossen Fotos + hohem Zoom extrem langsam).
        #
        # Zusaetzlich wird ein Puffer-Rand mitgerendert und zwischengespeichert:
        # Panning / Fenster verschieben loest sonst auf JEDEM Mausereignis ein
        # erneutes Zuschneiden+Skalieren aus (sehr langsam). Solange sich der
        # sichtbare Bereich innerhalb des gepufferten Bereichs bewegt, wird das
        # bereits berechnete Bild nur neu positioniert statt neu berechnet.
        src = self._display_img if self._display_img is not None else self.img_orig
        iw, ih = src.width, src.height
        vx0 = max(0.0, -self.off_x / self.zoom)
        vy0 = max(0.0, -self.off_y / self.zoom)
        vx1 = min(float(iw), (W - self.off_x) / self.zoom)
        vy1 = min(float(ih), (H - self.off_y) / self.zoom)

        cache = self._render_cache
        needs_recompute = (
            vx1 > vx0 and vy1 > vy0 and (
                cache is None or
                cache['zoom'] != self.zoom or
                cache.get('src') is not src or
                vx0 < cache['x0'] or vy0 < cache['y0'] or
                vx1 > cache['x1'] or vy1 > cache['y1']
            )
        )

        if needs_recompute:
            pad_x = (vx1 - vx0) * 0.5
            pad_y = (vy1 - vy0) * 0.5
            rx0 = max(0, int(vx0 - pad_x))
            ry0 = max(0, int(vy0 - pad_y))
            rx1 = min(iw, int(vx1 + pad_x) + 1)
            ry1 = min(ih, int(vy1 + pad_y) + 1)

            method = Image.LANCZOS if self.zoom < 1 else Image.NEAREST
            out_w = max(1, round((rx1 - rx0) * self.zoom))
            out_h = max(1, round((ry1 - ry0) * self.zoom))

            # reducing_gap: laesst PIL bei starkem Verkleinern (herausgezoomt) erst
            # billig grob vorverkleinern und erst danach den teuren Filter (LANCZOS)
            # anwenden -- bei grossen Fotos ca. 3x schneller, ohne sichtbaren
            # Qualitaetsverlust. Das Overlay wird NICHT hier pro Zoomschritt separat
            # skaliert (RGBA-Bilder profitieren nicht von reducing_gap und waeren
            # doppelt so teuer) -- stattdessen ist es bereits einmalig in
            # _display_img eingeblendet (siehe _poll_detect).
            crop = src.crop((rx0, ry0, rx1, ry1))
            self._cache_tk = ImageTk.PhotoImage(
                crop.resize((out_w, out_h), method, reducing_gap=2.0))

            self._render_cache = {'zoom': self.zoom, 'x0': rx0, 'y0': ry0, 'x1': rx1, 'y1': ry1, 'src': src}
            cache = self._render_cache

        if cache is None or self._cache_tk is None:
            return

        screen_x = int(self.off_x + cache['x0'] * self.zoom)
        screen_y = int(self.off_y + cache['y0'] * self.zoom)

        img_state = (screen_x, screen_y, id(self._cache_tk))
        if self._img_item is None:
            self._img_item = self.cv.create_image(screen_x, screen_y,
                image=self._cache_tk, anchor='nw', tags='imglayer')
            self._img_state = img_state
        elif img_state != self._img_state:
            self.cv.coords(self._img_item, screen_x, screen_y)
            self.cv.itemconfig(self._img_item, image=self._cache_tk)
            self._img_state = img_state

    def _redraw_windows(self):
        visible = self.show_wins.get()
        self.cv.itemconfigure('winlayer', state='normal' if visible else 'hidden')
        if not visible:
            # Solange ausgeblendet keine Coord-Updates -- die gespeicherten
            # Item-Zustaende bleiben "alt" und werden beim Wiedereinblenden
            # automatisch als veraltet erkannt und aktualisiert.
            return
        while len(self._win_items) < len(self.wins):
            rect_id = self.cv.create_rectangle(0, 0, 1, 1, tags='winlayer')
            text_id = self.cv.create_text(0, 0, anchor='nw', tags='winlayer')
            self._win_items.append({'rect': rect_id, 'text': text_id, 'state': None})
        while len(self._win_items) > len(self.wins):
            items = self._win_items.pop()
            self.cv.delete(items['rect'])
            self.cv.delete(items['text'])

        for i, w in enumerate(self.wins):
            sel = (i == self.sel_idx)
            x1 = self.off_x + w['x'] * self.zoom
            y1 = self.off_y + w['y'] * self.zoom
            x2 = x1 + w['w'] * self.zoom
            y2 = y1 + w['h'] * self.zoom
            fs = max(7, min(int(10 * self.zoom), 14))

            # Nur tatsaechlich an den Canvas melden, wenn sich fuer DIESES Item
            # etwas geaendert hat -- sonst wuerde jedes _render_cv() (z.B. nach
            # dem Bearbeiten eines einzelnen Fensters) wieder ALLE Items per
            # Tcl-Aufruf aktualisieren, obwohl nur eines sich veraendert hat.
            state = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), sel, fs)
            items = self._win_items[i]
            if items['state'] == state:
                continue
            items['state'] = state

            self.cv.coords(items['rect'], x1, y1, x2, y2)
            self.cv.itemconfig(items['rect'],
                fill='#713f12' if sel else '#854d0e',
                stipple='gray25',
                outline='#fde047' if sel else '#eab308',
                width=2 if sel else 1)

            self.cv.coords(items['text'], x1 + 3, y1 + 2)
            self.cv.itemconfig(items['text'],
                text=str(i + 1),
                fill='#fef08a' if sel else '#fde047',
                font=('Segoe UI', fs, 'bold'))

    def _redraw_panes(self):
        visible = self.show_panes.get()
        self.cv.itemconfigure('panelayer', state='normal' if visible else 'hidden')
        if not visible:
            return
        while len(self._pane_items) < len(self.panes):
            self._pane_items.append({
                'id': self.cv.create_rectangle(0, 0, 1, 1, outline='#60a5fa', width=1, tags='panelayer'),
                'state': None,
            })
        while len(self._pane_items) > len(self.panes):
            self.cv.delete(self._pane_items.pop()['id'])

        for i, c in enumerate(self.panes):
            x1 = self.off_x + c['x'] * self.zoom
            y1 = self.off_y + c['y'] * self.zoom
            x2 = x1 + c['w'] * self.zoom
            y2 = y1 + c['h'] * self.zoom

            state = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
            item = self._pane_items[i]
            if item['state'] == state:
                continue
            item['state'] = state
            self.cv.coords(item['id'], x1, y1, x2, y2)

    def _update_preview(self):
        """Zeichnet/aktualisiert das gelbe Vorschau-Rechteck beim Ziehen eines
        manuellen Fensters. Nutzt ein persistentes Canvas-Item (coords statt
        delete+recreate), damit Ziehen bei vielen markierten Fenstern nicht laggt."""
        if not (self._draw_a and self._draw_b):
            if self._preview_id is not None:
                self.cv.delete(self._preview_id)
                self._preview_id = None
            return
        ax, ay = self._draw_a
        bx, by = self._draw_b
        x1 = self.off_x + min(ax, bx) * self.zoom
        y1 = self.off_y + min(ay, by) * self.zoom
        x2 = self.off_x + max(ax, bx) * self.zoom
        y2 = self.off_y + max(ay, by) * self.zoom
        if self._preview_id is None:
            self._preview_id = self.cv.create_rectangle(x1, y1, x2, y2,
                outline='#fbbf24', fill='#451a03',
                stipple='gray12', dash=(4, 3), width=1, tags='previewlayer')
        else:
            self.cv.coords(self._preview_id, x1, y1, x2, y2)

    def _s2i(self, cx, cy):
        """Screen → Image coords."""
        return (cx - self.off_x) / self.zoom, (cy - self.off_y) / self.zoom

    def _fit(self):
        if not self.img_orig:
            return
        W = self.cv.winfo_width()  or 800
        H = self.cv.winfo_height() or 600
        pad = 24
        self.zoom = min((W - pad*2) / self.img_orig.width,
                        (H - pad*2) / self.img_orig.height, 1.0)
        self.off_x = (W - self.img_orig.width  * self.zoom) / 2
        self.off_y = (H - self.img_orig.height * self.zoom) / 2
        self._render_cv()

    # ── Canvas mouse ──────────────────────────────────────────────────────

    def _cv_dn(self, e):
        if not self.img_orig:
            return
        if self._space:
            self._pan_ref = (e.x - self.off_x, e.y - self.off_y)
            self.cv.configure(cursor='fleur')
            return
        ix, iy = self._s2i(e.x, e.y)
        self._draw_a = (ix, iy)
        self._draw_b = (ix, iy)

    def _cv_mv(self, e):
        if not self.img_orig:
            return
        if self._pan_ref:
            new_off_x = e.x - self._pan_ref[0]
            new_off_y = e.y - self._pan_ref[1]
            self._pan_by(new_off_x - self.off_x, new_off_y - self.off_y)
        elif self._draw_a:
            self._draw_b = self._s2i(e.x, e.y)
            self._update_preview()

    def _cv_up(self, e):
        if self._pan_ref:
            self._pan_ref = None
            self.cv.configure(cursor='crosshair')
            return
        if self._draw_a:
            ix, iy = self._s2i(e.x, e.y)
            ax, ay = self._draw_a
            x = round(min(ax, ix));  y = round(min(ay, iy))
            w = round(abs(ix - ax)); h = round(abs(iy - ay))
            if w > 2 and h > 2:
                # Manuell gezogenes Fenster-Rechteck
                old_sel = self.sel_idx
                self.wins.append({'x': x, 'y': y, 'w': w, 'h': h})
                self.sel_idx = len(self.wins) - 1
                self._append_card(self.sel_idx, old_sel)
                self._schedule_save()
            elif self.red_wall is not None and self.green_wall is not None:
                # Einfacher Klick: Flutfuellung fuer Glasscheibe (INNERE Kante) + Fensterrahmen
                self._flood_click(round(ax), round(ay), grow=False)
            self._draw_a = self._draw_b = None
            self._render_cv()

    def _cv_right_click(self, e):
        if not self.img_orig:
            return
        ix, iy = self._s2i(e.x, e.y)

        # Ausgeblendete Ebenen sind auch nicht anklickbar.
        if self.show_panes.get():
            for i in range(len(self.panes) - 1, -1, -1):
                c = self.panes[i]
                if c['x'] <= ix <= c['x'] + c['w'] and c['y'] <= iy <= c['y'] + c['h']:
                    self.panes.pop(i)
                    self._schedule_save()
                    self._render_cv()
                    return

        if self.show_wins.get():
            for i in range(len(self.wins) - 1, -1, -1):
                w = self.wins[i]
                if w['x'] <= ix <= w['x'] + w['w'] and w['y'] <= iy <= w['y'] + w['h']:
                    self._select_window(i)
                    return

        if self.red_wall is not None and self.green_wall is not None:
            # Kein Treffer: Flutfuellung mit AEUSSERER Kante (durch die rote Linie hindurch)
            self._flood_click(round(ix), round(iy), grow=True)
            self._render_cv()

    def _pan_by(self, dx: float, dy: float):
        """Verschiebt die Ansicht um (dx, dy). Solange der neue Sichtbereich noch
        innerhalb des gepufferten Bildausschnitts liegt, wird nur `canvas.move`
        auf alle vorhandenen Items angewendet statt alles neu zu zeichnen – bei
        vielen markierten Fenstern/Scheiben ist ein voller Redraw bei JEDER
        Mausbewegung extrem langsam."""
        if dx == 0 and dy == 0:
            return
        self.off_x += dx
        self.off_y += dy

        cache = self._render_cache
        if cache is not None and self.img_orig is not None:
            W = self.cv.winfo_width()  or 800
            H = self.cv.winfo_height() or 600
            vx0 = max(0.0, -self.off_x / self.zoom)
            vy0 = max(0.0, -self.off_y / self.zoom)
            vx1 = min(float(self.img_orig.width),  (W - self.off_x) / self.zoom)
            vy1 = min(float(self.img_orig.height), (H - self.off_y) / self.zoom)
            if vx0 < cache['x0'] or vy0 < cache['y0'] or vx1 > cache['x1'] or vy1 > cache['y1']:
                self._render_cv()
                return

        self.cv.move('all', dx, dy)

    def _pan_dn(self, e):
        self._pan_ref = (e.x - self.off_x, e.y - self.off_y)
        self.cv.configure(cursor='fleur')

    def _pan_mv(self, e):
        if self._pan_ref:
            new_off_x = e.x - self._pan_ref[0]
            new_off_y = e.y - self._pan_ref[1]
            self._pan_by(new_off_x - self.off_x, new_off_y - self.off_y)

    def _pan_up(self, _e):
        self._pan_ref = None
        self.cv.configure(cursor='crosshair')

    def _scroll(self, e):
        if not self.img_orig:
            return
        f = 1.1 if e.delta > 0 else 1 / 1.1
        nz = max(0.02, min(32.0, self.zoom * f))
        self.off_x = e.x - (e.x - self.off_x) * (nz / self.zoom)
        self.off_y = e.y - (e.y - self.off_y) * (nz / self.zoom)
        self.zoom = nz
        self._request_render()

    def _zoom_in(self):
        if not self.img_orig:
            return
        self._zoom_center(1.25)

    def _zoom_out(self):
        if not self.img_orig:
            return
        self._zoom_center(1 / 1.25)

    def _zoom_center(self, f):
        W = self.cv.winfo_width()  / 2
        H = self.cv.winfo_height() / 2
        nz = max(0.02, min(32.0, self.zoom * f))
        self.off_x = W - (W - self.off_x) * (nz / self.zoom)
        self.off_y = H - (H - self.off_y) * (nz / self.zoom)
        self.zoom = nz
        self._request_render()

    def _request_render(self):
        """Buendelt mehrere schnell aufeinanderfolgende Render-Anfragen (z.B. ein
        schneller Mausrad-Scroll-Burst oder <Configure>-Spam beim Verschieben/
        Vergroessern des Fensters) zu einem einzigen tatsaechlichen Redraw."""
        if self._render_pending:
            return
        self._render_pending = True
        self.root.after_idle(self._flush_render)

    def _flush_render(self):
        self._render_pending = False
        self._render_cv()

    # ── Flutfuellung (Fenster/Scheiben per Klick) ──────────────────────────

    @staticmethod
    def _rect_contains_any_pane_center(rect: tuple, panes: list) -> bool:
        """True, wenn mindestens eine Scheibe aus `panes` (per Mittelpunkt) in
        `rect` (x,y,w,h) liegt. Verhindert, dass ein Klick in eine Fuge/Sprosse
        ZWISCHEN bereits erkannten Scheiben faelschlich das GANZE Fenster als
        weitere, ueberlappende Scheibe anlegt -- der Fallback 'ganzes Fenster
        = Scheibe' gilt nur fuer WIRKLICH unterteilungslose Fenster."""
        rx, ry, rw, rh = rect
        for p in panes:
            cx, cy = p['x'] + p['w'] / 2, p['y'] + p['h'] / 2
            if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
                return True
        return False

    @staticmethod
    def _region_bbox_if_valid(region: np.ndarray, area_limit: float) -> tuple | None:
        """Bounding-Box (x, y, w, h) von `region`, aber nur wenn die Region
        plausibel ein einzelnes, geschlossenes Rechteck ist: weder zu gross
        (Gesamtflaeche) noch zu 'duenn' relativ zu ihrer Bounding-Box (Fuellrate
        >= MIN_FILL_RATIO). Eine Flutfuellung, die um mehrere Objekte herum in
        den Hintergrund entkommt, hat eine viel groessere, unregelmaessige
        Bounding-Box mit niedriger Fuellrate -- selbst wenn ihre reine
        Pixelzahl (zufaellig) noch unter area_limit liegt."""
        total = region.sum()
        if total == 0 or total > area_limit:
            return None
        ys, xs = np.where(region)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        bbox_area = (x1 - x0) * (y1 - y0)
        if bbox_area == 0 or (total / bbox_area) < MIN_FILL_RATIO:
            return None
        return (x0, y0, x1 - x0, y1 - y0)

    @staticmethod
    def _rects_overlap(a: dict, b: dict) -> bool:
        """True bei echter Ueberlappung (nur an der Kante beruehrende Rechtecke
        zaehlen NICHT als Ueberlappung -- benachbarte Glasscheiben teilen sich
        oft exakt eine Sprosse/Kante)."""
        return (a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and
                a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h'])

    @staticmethod
    def _iou(a: dict, b: dict) -> float:
        ax1, ay1, ax2, ay2 = a['x'], a['y'], a['x'] + a['w'], a['y'] + a['h']
        bx1, by1, bx2, by2 = b['x'], b['y'], b['x'] + b['w'], b['y'] + b['h']
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = a['w'] * a['h'] + b['w'] * b['h'] - inter
        return inter / union if union > 0 else 0.0

    @classmethod
    def _find_window_in(cls, rect: tuple, wins: list) -> dict | None:
        """Bereits erfassten Fensterrahmen in `wins` finden, der zu `rect` gehoert
        (verhindert doppelte Fenster-Eintraege)."""
        gx, gy, gw, gh = rect
        gcx, gcy = gx + gw / 2, gy + gh / 2
        cand = {'x': gx, 'y': gy, 'w': gw, 'h': gh}
        for win in wins:
            if win['x'] <= gcx <= win['x'] + win['w'] and win['y'] <= gcy <= win['y'] + win['h']:
                return win
        # Fallback: Mittelpunkt liegt (z.B. durch leicht abweichende Flutfuellung)
        # knapp ausserhalb, das Rechteck ist aber praktisch dasselbe Fenster.
        for win in wins:
            if cls._iou(win, cand) > 0.7:
                return win
        return None

    def _try_flood(self, ix: int, iy: int, grow: bool, wins: list, panes: list,
                   red_wall=None, green_wall=None, allow_window_fallback: bool = True):
        """
        Reine Berechnung eines Flutfuellungs-Klicks -- KEIN Tk, daher auch aus
        Worker-Threads (Raster-Scan) nutzbar. Prueft Ueberlappung/Duplikate gegen
        die uebergebenen Listen.

        allow_window_fallback: bei einem gezielten Einzelklick (True) gilt ein
        Fenster ohne lokale Glaskante als unterteilungslos und wird ganz als
        Scheibe uebernommen. Beim automatisierten Raster-Scan/Positionen-
        Einfuegen (False) waere das kontraproduktiv: der allererste Raster-
        Punkt in einem Fenster liegt oft im Rahmen-Rand VOR den eigentlichen
        Scheiben (die dort erst noch folgen wuerden) -- der Fallback wuerde
        dann verfrueht das GANZE Fenster als eine grosse Scheibe anlegen und
        so die spaeter gefundenen, echten (kleineren) Einzelscheiben per
        Ueberlappungs-Pruefung blockieren.
        """
        red_wall = self.red_wall if red_wall is None else red_wall
        green_wall = self.green_wall if green_wall is None else green_wall
        W, H = self.img_orig.width, self.img_orig.height
        if not (0 <= ix < W and 0 <= iy < H):
            return None, None, 'Position ausserhalb des Bildes'
        area_limit = MAX_FILL_AREA_FRACTION * W * H

        # Fensterrahmen (gelb) zuerst ermitteln -- wird sowohl im Normalfall als
        # auch als Fallback benoetigt, falls es keine (sinnvolle) Glaskante gibt.
        # _region_bbox_if_valid prueft NICHT nur die Gesamtflaeche (die kann bei
        # geringer Fensterdichte im Bild zufaellig knapp unters Limit fallen,
        # obwohl es eindeutig der Hintergrund ist), sondern auch die Fuellrate
        # relativ zur Bounding-Box -- ein echtes Fenster ist fast vollstaendig
        # gefuellt, eine in den Hintergrund entkommene Flutfuellung dagegen nicht.
        win_region = flood_region(green_wall, (ix, iy))
        win_rect = self._region_bbox_if_valid(win_region, area_limit) if win_region is not None else None
        if win_rect is None:
            return None, None, 'Kein Fensterrahmen (gelb) an dieser Stelle gefunden'

        pane_region = flood_region(red_wall, (ix, iy))
        if pane_region is None:
            # Klick liegt exakt auf einer Glaskanten-Linie -- hier GIBT es also
            # tatsaechlich Sprossen, nur die Klickposition ist mehrdeutig.
            # Anders als beim "keine Glaskante vorhanden"-Fall unten (siehe
            # naechster Block) NICHT auf das ganze Fenster ausweichen, sondern
            # einen praeziseren Klick verlangen.
            return None, None, 'Klick liegt auf einer Glaskanten-Linie (blau)'

        pane_rect = self._region_bbox_if_valid(pane_region, area_limit)
        if pane_rect is None or pane_rect[2] < 2 or pane_rect[3] < 2:
            if not allow_window_fallback:
                # Automatisierter Raster-Scan/Positionen-Einfuegen: keinen
                # verfruehten Fallback anwenden (siehe Docstring) -- einfach
                # ablehnen, genau wie vor dieser Funktion.
                return None, None, 'Kein geschlossener Glasflaechen-Bereich gefunden'
            if self._rect_contains_any_pane_center(win_rect, panes):
                # Dieses Fenster hat (an anderer Stelle) bereits eine echte
                # Scheibe -- der Klick liegt vermutlich nur in einer Fuge/
                # Sprosse dazwischen. NICHT das ganze Fenster als weitere,
                # ueberlappende Scheibe anlegen (wuerde die bestehenden echten
                # Scheiben nur ueberlagern/blockieren), sondern ablehnen.
                return None, None, 'Kein geschlossener Glasflaechen-Bereich gefunden'
            # Keine gueltige, geschlossene Glaskante gefunden UND dieses
            # Fenster hat noch gar keine eigene Scheibe -- es ist offenbar
            # unterteilungslos. Dann gilt das ganze (gelbe) Fenster selbst als
            # Glasflaeche: es wird als Fenster UND als Scheibe gespeichert.
            px, py, pw, ph = win_rect
        else:
            px, py, pw, ph = pane_rect
            if grow:
                # Rechteck ueber die rote Linie hinaus wachsen lassen, bis es an
                # deren Aussenkante wieder transparent wird, statt knapp davor
                # aufzuhoeren.
                px, py, pw, ph = grow_rect_through_wall((px, py, pw, ph), red_wall)

        pane = {'x': int(px), 'y': int(py), 'w': int(pw), 'h': int(ph)}

        # Glasscheiben duerfen sich nicht ueberlappen (verhindert auch Duplikate:
        # ein identisches Rechteck ueberlappt sich immer selbst).
        if any(self._rects_overlap(pane, existing) for existing in panes):
            return None, None, 'Glasscheibe ueberlappt eine bestehende – ignoriert'

        window = self._find_window_in(win_rect, wins)
        is_new = window is None
        if is_new:
            wx, wy, ww, wh = win_rect
            window = {'x': wx, 'y': wy, 'w': ww, 'h': wh}
        return pane, window, is_new

    def _flood_click(self, ix: int, iy: int, grow: bool = False):
        """
        grow=False (normaler Klick): innere Kante der roten Linie (enges Rechteck).
        grow=True  (Rechtsklick):    aeussere Kante -- waechst durch die rote Linie
                                     hindurch, bis sie wieder transparent wird.
        """
        if self.red_wall is None or self.green_wall is None:
            # Erkennung laeuft nicht mehr automatisch beim Laden -- ohne
            # red_wall/green_wall wuerde flood_region() sonst abstuerzen.
            self._status('⚠ Bitte zuerst Fenster erkennen lassen (OpenAI)', C['red'])
            return
        pane, window, extra = self._try_flood(int(ix), int(iy), grow, self.wins, self.panes)
        if pane is None:
            self._status(f'⚠ {extra}', C['red'])
            return
        if extra:  # neues Fenster
            old_sel = self.sel_idx
            self.wins.append(window)
            self.sel_idx = len(self.wins) - 1
            self._append_card(self.sel_idx, old_sel)

        self.panes.append(pane)
        self._status(f'✓ Scheibe hinzugefuegt ({len(self.panes)} gesamt)', C['green'])
        self._schedule_save()

    # ── Positionen einfügen (z.B. aus CSV) ─────────────────────────────────

    @staticmethod
    def _parse_points(text: str) -> list[tuple[int, int]]:
        """Extrahiert (x, y)-Paare aus beliebigem Text: eine Position pro Zeile,
        Zahlen durch Komma/Tab/Leerzeichen getrennt. Nicht-numerische Zeilen
        (z.B. eine CSV-Kopfzeile 'x,y') werden uebersprungen."""
        pts = []
        for line in text.splitlines():
            nums = re.findall(r'-?\d+\.?\d*', line)
            if len(nums) >= 2:
                try:
                    x, y = float(nums[0]), float(nums[1])
                except ValueError:
                    continue
                pts.append((round(x), round(y)))
        return pts

    def _open_paste_dialog(self):
        if not self.img_orig:
            self._status('⚠ Bitte zuerst ein Bild öffnen', C['red'])
            return
        if self._batch_running:
            self._status('⚠ Es laeuft bereits ein Scan', C['red'])
            return

        win = tk.Toplevel(self.root)
        win.title('Positionen einfügen')
        win.configure(bg=C['bg'])
        win.geometry('420x420')
        win.transient(self.root)

        tk.Label(win, text='x,y Positionen einfügen (eine pro Zeile, z.B. aus CSV):',
                bg=C['bg'], fg=C['text'], font=('Segoe UI', 9)).pack(anchor='w', padx=10, pady=(10, 4))

        txt = tk.Text(win, bg=C['bg_dark'], fg=C['text'], insertbackground='white',
                     relief='flat', font=('Courier New', 9), wrap='none')
        txt.pack(fill='both', expand=True, padx=10, pady=(0, 8))
        txt.focus_set()

        btns = tk.Frame(win, bg=C['bg'])
        btns.pack(fill='x', padx=10, pady=(0, 10))

        def apply_():
            pts = self._parse_points(txt.get('1.0', 'end'))
            win.destroy()
            self._apply_points(pts)

        ttk.Button(btns, text='Übernehmen', command=apply_).pack(side='right', padx=(4, 0))
        ttk.Button(btns, text='Abbrechen', command=win.destroy).pack(side='right')

    def _apply_points(self, pts: list[tuple[int, int]]):
        """Verarbeitet viele Positionen (Raster-Scan / eingefuegte Liste) in einem
        Hintergrund-Thread: die Flutfuellungen sind reine NumPy/OpenCV-Arbeit ohne
        Tk und blockieren so nicht die Oberflaeche. Ergebnisse und Fortschritt
        kommen ueber eine Queue zurueck in den UI-Thread (_poll_batch)."""
        if not pts:
            self._status('⚠ Keine gueltigen Positionen erkannt', C['red'])
            return
        if self.red_wall is None or self.green_wall is None:
            self._status('⚠ Bitte zuerst Fenster erkennen lassen (OpenAI)', C['red'])
            return
        if self._batch_running:
            return
        self._batch_running = True
        self._btn_detect_new.configure(state='disabled')
        self._btn_detect.configure(state='disabled')
        self._btn_recolor.configure(state='disabled')
        self._status(f'⏳ Scan gestartet ({len(pts)} Positionen) ...', C['blue'], sticky=True)

        # Schnappschuesse: der Worker prueft gegen Kopien und darf die echten
        # Listen/Masken nicht anfassen (die UI koennte sie waehrenddessen lesen).
        wins_copy = [dict(w) for w in self.wins]
        panes_copy = [dict(p) for p in self.panes]
        threading.Thread(
            target=self._batch_worker,
            args=(pts, wins_copy, panes_copy, self.red_wall, self.green_wall),
            daemon=True).start()
        self.root.after(100, self._poll_batch)

    def _batch_worker(self, pts, wins, panes, red_wall, green_wall):
        new_wins, new_panes = [], []
        skipped = 0
        total = len(pts)
        try:
            for i, (x, y) in enumerate(pts):
                pane, window, extra = self._try_flood(
                    int(x), int(y), False, wins, panes, red_wall, green_wall,
                    allow_window_fallback=False)
                if pane is None:
                    skipped += 1
                else:
                    if extra:  # neues Fenster
                        wins.append(window)
                        new_wins.append(window)
                    panes.append(pane)
                    new_panes.append(pane)
                if (i + 1) % 25 == 0:
                    self._batch_queue.put(('progress', i + 1, total, len(new_panes)))
            self._batch_queue.put(('done', new_wins, new_panes, skipped, total))
        except Exception as ex:
            self._batch_queue.put(('error', str(ex)))

    def _poll_batch(self):
        try:
            while True:
                msg = self._batch_queue.get_nowait()
                if msg[0] == 'progress':
                    _, done, total, found = msg
                    self._status(f'⏳ Scan: {done}/{total} Positionen, {found} Scheiben gefunden',
                                C['blue'], sticky=True)
                elif msg[0] == 'error':
                    self._finish_batch()
                    self._status(f'⚠ Scan-Fehler: {msg[1]}', C['red'])
                    return
                else:  # done
                    _, new_wins, new_panes, skipped, total = msg
                    self._finish_batch()
                    for w in new_wins:
                        old_sel = self.sel_idx
                        self.wins.append(w)
                        self.sel_idx = len(self.wins) - 1
                        self._append_card(self.sel_idx, old_sel)
                    self.panes.extend(new_panes)
                    self._render_cv()
                    self._status(
                        f'✓ {len(new_panes)} Scheiben ({len(new_wins)} neue Fenster) aus '
                        f'{total} Positionen, {skipped} uebersprungen', C['green'])
                    self._schedule_save()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_batch)

    def _finish_batch(self):
        self._batch_running = False
        self._btn_detect_new.configure(state='normal')
        self._btn_detect.configure(state='normal')
        self._btn_recolor.configure(state='normal')

    # ── Raster-Scan (automatisch an einem x/y-Raster "klicken") ────────────

    def _open_grid_dialog(self):
        if not self.img_orig:
            self._status('⚠ Bitte zuerst ein Bild öffnen', C['red'])
            return
        if self.red_wall is None or self.green_wall is None:
            self._status('⚠ Bitte zuerst Fenster erkennen lassen (OpenAI)', C['red'])
            return
        if self._batch_running:
            self._status('⚠ Es laeuft bereits ein Scan', C['red'])
            return

        win = tk.Toplevel(self.root)
        win.title('Raster-Scan')
        win.configure(bg=C['bg'])
        win.transient(self.root)

        tk.Label(win, text='Rasterabstand in Pixeln (Bildkoordinaten):',
                bg=C['bg'], fg=C['text'], font=('Segoe UI', 9)).pack(anchor='w', padx=10, pady=(10, 4))

        var = tk.StringVar(value='50')
        ent = tk.Entry(win, textvariable=var, bg=C['bg_dark'], fg=C['text'],
                      insertbackground='white', relief='flat', font=('Courier New', 10),
                      highlightthickness=1, highlightbackground=C['border'], highlightcolor=C['blue'])
        ent.pack(fill='x', padx=10, pady=(0, 4))
        ent.focus_set()
        ent.select_range(0, 'end')

        n_x = max(1, self.img_orig.width // 50)
        n_y = max(1, self.img_orig.height // 50)
        tk.Label(win, text=f'Bild: {self.img_orig.width}×{self.img_orig.height} px  '
                           f'(z.B. bei 50px ≈ {n_x}×{n_y} Positionen)',
                bg=C['bg'], fg=C['dim'], font=('Segoe UI', 8)).pack(anchor='w', padx=10, pady=(0, 10))

        btns = tk.Frame(win, bg=C['bg'])
        btns.pack(fill='x', padx=10, pady=(0, 10))

        def apply_():
            try:
                step = max(4, int(var.get()))
            except ValueError:
                step = 50
            win.destroy()
            self._run_grid_scan(step)

        ttk.Button(btns, text='Start', command=apply_).pack(side='right', padx=(4, 0))
        ttk.Button(btns, text='Abbrechen', command=win.destroy).pack(side='right')
        ent.bind('<Return>', lambda _: apply_())

    def _run_grid_scan(self, step: int):
        """Klickt (per Flutfuellung) an jeder Position eines gleichmaessigen
        x/y-Rasters ueber das ganze Bild -- automatisches "Anklicken" aller
        Fenster/Scheiben statt von Hand. Nutzt dieselbe Duplikat-/Ueberlappungs-
        Pruefung wie ein einzelner Klick."""
        W, H = self.img_orig.width, self.img_orig.height
        pts = [(x, y) for y in range(step // 2, H, step) for x in range(step // 2, W, step)]
        self._apply_points(pts)

    # ── Keyboard ──────────────────────────────────────────────────────────

    def _kb_space_dn(self, e):
        if not self._is_active() or isinstance(e.widget, tk.Entry):
            return
        self._space = True
        if self.img_orig and not self._pan_ref:
            self.cv.configure(cursor='hand2')

    def _kb_space_up(self, _e):
        if not self._is_active():
            return
        self._space = False
        if not self._pan_ref:
            self.cv.configure(cursor='crosshair')

    def _kb_del(self, e):
        if not self._is_active() or isinstance(e.widget, tk.Entry):
            return
        if 0 <= self.sel_idx < len(self.wins):
            self._remove_window(self.sel_idx)

    def _kb_esc(self, _e):
        if not self._is_active():
            return
        if self._draw_a:
            self._draw_a = self._draw_b = None
            self._render_cv()
        else:
            self.sel_idx = -1
            self._render_list()
            self._render_cv()

    # ── OpenAI-Fenstererkennung ─────────────────────────────────────────────

    def _detect_windows(self, force: bool = False, grayscale: bool = False):
        if not self.img_path or self._detecting:
            return
        self._detecting = True
        msg = ('⏳ Wird in Graustufen umgewandelt und an OpenAI gesendet ...' if grayscale
               else '⏳ OpenAI: Fenster werden erkannt ...')
        # sticky=True: OpenAI-Bildgenerierung kann leicht 1-3 Minuten dauern --
        # ohne sticky verschwand diese Meldung nach den ueblichen 3s automatisch
        # wieder, obwohl der Aufruf noch lief (siehe _status-Docstring).
        self._status(msg, C['blue'], sticky=True)
        self._btn_detect_new.configure(state='disabled')
        self._btn_detect.configure(state='disabled')
        self._btn_recolor.configure(state='disabled')
        # Bei PDF-Quellen kann OpenCV die Datei nicht selbst einlesen (cv2
        # kennt kein PDF) -- das bereits extrahierte Foto wird stattdessen
        # direkt mitgegeben. Als Kopie, damit der Hintergrund-Thread nicht auf
        # dasselbe PIL-Objekt zugreift, das der Hauptthread evtl. gleichzeitig
        # neu zuweist (neues Bild waehrend die Erkennung noch laeuft).
        preloaded = self.img_orig.copy() if self.img_path.suffix.lower() == '.pdf' else None
        threading.Thread(target=self._detect_worker,
                         args=(self.img_path, force, grayscale, preloaded), daemon=True).start()
        self.root.after(200, self._poll_detect)

    def _detect_worker(self, path: Path, force: bool, grayscale: bool, preloaded_img=None):
        try:
            if path.suffix.lower() == '.pdf':
                if preloaded_img is None:
                    raise RuntimeError('Kein extrahiertes Bild fuer die Erkennung vorhanden')
                rgb = np.array(preloaded_img.convert('RGB'))
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            else:
                bgr = cv2.imread(str(path))
                if bgr is None:
                    raise RuntimeError('Bild konnte von OpenCV nicht gelesen werden')
            if grayscale:
                # Explizit in Schwarz-Weiss wandeln, bevor es zur Einfaerbung an
                # OpenAI geht (verhindert, dass vorhandene Farben im Foto mit den
                # rot/gruenen Markierungslinien verwechselt werden koennen).
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            annotated = get_annotated(path, bgr, OPENAI_PROMPT, force=force, model=OPENAI_MODEL)
            p = GreenParams()
            red_wall = prep_wall(_extract_color_mask(annotated, True, p.green_thresh) > 0)
            green_wall = prep_wall(_extract_color_mask(annotated, False, p.green_thresh) > 0)

            # Rot-/Gruenbilder als eigene Dateien ablegen (wie extractWindows.py)
            # -- im 'states'-Unterordner neben der Eingabedatei (siehe
            # calcImages._states_dir), nicht direkt daneben.
            states_dir = _states_dir(path)
            cv2.imwrite(str(states_dir / (path.stem + '._redmask.png')),
                       (red_wall * 255).astype('uint8'))
            cv2.imwrite(str(states_dir / (path.stem + '._greenmask.png')),
                       (green_wall * 255).astype('uint8'))

            # Overlay-Linien (gelb: Fensterrahmen, blau: Glaskanten) als RGBA-Ebene
            # vorbereiten. Das Einblenden ins Anzeigebild passiert EINMALIG in
            # _update_display_img (abhaengig von der "Farbe anzeigen"-Einstellung),
            # nicht pro Zoomschritt -- eine separate RGBA-Ebene pro Render waere
            # doppelt so teuer und profitiert nicht von PILs reducing_gap.
            overlay = np.zeros((red_wall.shape[0], red_wall.shape[1], 4), dtype=np.uint8)
            overlay[green_wall] = (250, 204, 21, 150)   # gelb: Fensterrahmen
            overlay[red_wall]   = (96, 165, 250, 170)   # blau: Glasscheiben-Linien
            overlay_pil = Image.fromarray(overlay, mode='RGBA')

            self._detect_queue.put(('ok', path, red_wall, green_wall, overlay_pil))
        except Exception as ex:
            self._detect_queue.put(('error', path, str(ex)))

    def _poll_detect(self):
        try:
            kind, path, *rest = self._detect_queue.get_nowait()
        except queue.Empty:
            self.root.after(200, self._poll_detect)
            return

        self._detecting = False
        self._btn_detect_new.configure(state='normal')
        self._btn_detect.configure(state='normal')
        self._btn_recolor.configure(state='normal')

        if path != self.img_path:
            # Bild wurde inzwischen gewechselt -> Ergebnis verwerfen. Die
            # sticky "wird erkannt..."-Meldung fuer das ALTE Bild muss aber
            # trotzdem geraeumt werden, sonst bliebe sie (jetzt, wo sie
            # sticky ist) fuer immer stehen.
            self._status('')
            return

        if kind == 'error':
            self._status(f'⚠ OpenAI-Fehler: {rest[0]}', C['red'])
            return

        self.red_wall, self.green_wall, self._overlay_pil = rest
        self._update_display_img()
        self._status('✓ Fenster erkannt – klicken zum Markieren', C['green'])

    def _update_display_img(self):
        """Baut das Anzeigebild neu auf: Foto grau (Standard) oder farbig
        ("Farbe anzeigen"), plus die Erkennungs-Overlay-Linien (gelb/blau),
        sofern die Erkennung schon gelaufen ist. Einmalige Arbeit pro Umschalten/
        Erkennung -- NICHT pro Zoomschritt."""
        if self.img_orig is None:
            self._display_img = None
            return
        if self.show_color.get():
            base = self.img_orig.convert('RGB')
        else:
            base = self.img_orig.convert('L').convert('RGB')
        if self._overlay_pil is not None:
            base = Image.alpha_composite(base.convert('RGBA'), self._overlay_pil).convert('RGB')
        self._display_img = base
        self._render_cache = None  # Anzeigebild hat sich geaendert -> neu berechnen
        self._request_render()

    # ── File operations ───────────────────────────────────────────────────

    @staticmethod
    def _resolve_house_file(folder: Path) -> Path | None:
        """Sucht DIREKT in `folder` (nicht rekursiv) nach der zu ihr
        gehoerenden Bild-/PDF-Datei: zuerst die Datei, deren Name (ohne
        Endung) mit dem Ordnernamen uebereinstimmt (die Haus-Ordner-
        Konvention public/houses/<name>/<name>.EXT, siehe
        DEFAULT_HOUSES_DIR); findet sich keine (z.B. ein aelterer/loser
        Ordner ohne diese Konvention), aber GENAU EINE Bilddatei direkt im
        Ordner, gilt ersatzweise die. None, wenn nichts passt -- z.B. ein
        SAMMELORDNER mit mehreren Haeusern als Unterordner (dort liegt keine
        einzelne Bild-/PDF-Datei direkt drin, sondern erst eine Ebene
        tiefer je Haus-Unterordner)."""
        try:
            candidates = sorted(
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS
                and not f.name.startswith('.') and not f.name.endswith(EXCLUDE_SUFFIXES)
            )
        except OSError:
            return None
        match = next((f for f in candidates if f.stem == folder.name), None)
        if match is None and len(candidates) == 1:
            match = candidates[0]
        return match

    def _open_file(self):
        """Oeffnet ein Haus ueber seinen ORDNER, nicht ueber die Datei darin
        -- man waehlt also z.B. den Ordner "house1" selbst statt erst
        hineinzuklicken und dort "house1.pdf" auszuwaehlen (siehe
        _resolve_house_file)."""
        p = filedialog.askdirectory(title='Haus-Ordner öffnen')
        if not p:
            return
        folder = Path(p)
        match = self._resolve_house_file(folder)
        if match is None:
            messagebox.showinfo('Öffnen',
                f'Im Ordner "{folder.name}" wurde keine passende Bild-/PDF-Datei gefunden.')
            return
        self._load(match)

    def _open_default_folder(self):
        if DEFAULT_HOUSES_DIR.is_dir():
            self._use_folder(DEFAULT_HOUSES_DIR)

    def _open_folder(self):
        p = filedialog.askdirectory(title='Ordner öffnen')
        if p:
            self._use_folder(Path(p))

    def _use_folder(self, path: Path):
        """Baut die Ordner-BAUM-Ansicht rechts auf (zum Durchsuchen mehrerer
        Haeuser). Ist `path` selbst schon ein einzelnes Haus (enthaelt
        DIREKT eine passende Bild-/PDF-Datei, siehe _resolve_house_file --
        z.B. wenn man ueber "Ordner öffnen" direkt "house1" statt des
        Sammelordners "houses" ausgewaehlt hat), wird diese Datei
        AUTOMATISCH mitgeladen -- man muss sie dann nicht zusaetzlich noch
        im Baum anklicken."""
        self.dir_path = path
        self._lbl_folder.configure(text=self.dir_path.name)
        self._rsep.pack(side='right', fill='y')
        self._rpanel.pack(side='right', fill='y')
        self._fill_tree()
        self._sync_houses_json()
        match = self._resolve_house_file(path)
        if match is not None:
            self._load(match)

    def _sync_houses_json(self):
        """Haelt public/houses/images.json aktuell (Liste aller Haus-
        Unterordnernamen dort -- ein Haus zaehlt, wenn sein Unterordner eine
        Bilddatei <name>.EXT mit demselben Namen wie der Ordner enthaelt) --
        wird von der Website gelesen (siehe src/main.ts) und muss NICHT mehr
        von Hand gepflegt werden. Laeuft bei jedem Ordner-Wechsel/Speichern;
        betrifft ausdruecklich immer DEFAULT_HOUSES_DIR, unabhaengig davon,
        welchen Ordner der Baum gerade anzeigt (man kann durchaus anderswo
        browsen)."""
        if not DEFAULT_HOUSES_DIR.is_dir():
            return
        try:
            names = sorted(
                sub.name for sub in DEFAULT_HOUSES_DIR.iterdir()
                if sub.is_dir() and not sub.name.startswith('.')
                and any(f.suffix.lower() in IMAGE_EXTS and f.stem == sub.name
                       and not f.name.endswith(EXCLUDE_SUFFIXES)
                       for f in sub.iterdir())
            )
            (DEFAULT_HOUSES_DIR / 'images.json').write_text(
                json.dumps({'images': names}, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass  # images.json ist ein bequemer Autosync, kein kritischer Pfad

    def _load(self, path: Path):
        if self._batch_running:
            self._status('⚠ Bitte zuerst den laufenden Scan abwarten', C['red'])
            return
        outline_polylines: list = []
        try:
            if path.suffix.lower() == '.pdf':
                # Zwei-Ebenen-Haus-PDF (siehe pdfHouse.py): Bild + von Hand
                # nachgezeichnete Kontur werden getrennt extrahiert.
                im, outline_polylines = pdfHouse.load_pdf_house(path)
            else:
                # Alter Workflow (JPG/PNG/...) bleibt als Fallback nutzbar --
                # keine Kontur-Referenzebene fuer diese Bilder.
                im = Image.open(path)
                im.load()
        except Exception as ex:
            self._status(f'⚠ Ladefehler: {ex}', C['red'])
            return

        if im.mode not in ('RGB', 'RGBA', 'L'):
            im = im.convert('RGBA')

        self.img_orig     = im
        self.img_path     = path
        self.json_path    = path.with_suffix('.json')
        self.svg_path     = _states_dir(path) / (path.stem + '.svg')
        self.outline_polylines = outline_polylines
        self.wins         = []
        self.sel_idx      = -1
        self.red_wall     = None
        self.green_wall   = None
        self._overlay_pil = None
        # Anzeigebild aufbauen (grau oder farbig, je nach Einstellung links)
        self._update_display_img()
        self._img_state = None

        self._v_name.set(f'{path.name}   ({im.width} × {im.height} px)')

        data = {}
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding='utf-8'))
                self.wins = data.get('windows', [])
            except Exception:
                data = {}
        # Glasscheiben: bevorzugt aus dem JSON ('glassPanes' -- wird seit dieser
        # Version dort UND in der SVG gespeichert); bei aelteren Dateien ohne
        # dieses Feld Fallback auf das Parsen der SVG. Rechtecke, die exakt
        # einem Fensterrahmen entsprechen, stammen aus der "Fenster ohne
        # Scheiben = Glasflaeche"-Regel (siehe _svg_rects) und sind keine
        # echten, manuell geklickten Scheiben -- nicht als solche
        # zurueckimportieren (sonst wuerden sie bei jedem Laden dupliziert).
        raw_panes = data['glassPanes'] if 'glassPanes' in data else self._load_panes_from_svg(self.svg_path)
        self.panes = [p for p in raw_panes if p not in self.wins]

        self._fit()
        self._render_list()
        if self.dir_path:
            self._fill_tree()
        self._sync_houses_json()
        # Erkennung laeuft bewusst NICHT mehr automatisch beim Laden -- erst
        # auf Klick auf "Fenster erkennen"/"Fenster neu erkennen" (spart
        # unnoetige OpenAI-Aufrufe, wenn man ein Bild nur ansehen will).

    @staticmethod
    def _load_panes_from_svg(svg_path: Path) -> list[dict]:
        if not svg_path.exists():
            return []
        try:
            text = svg_path.read_text(encoding='utf-8')
        except Exception:
            return []
        panes = []
        for m in re.finditer(
            r'<rect x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"', text):
            x, y, w, h = map(int, m.groups())
            panes.append({'x': x, 'y': y, 'w': w, 'h': h})
        return panes

    def _schedule_save(self):
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(400, self._save)

    def _save(self):
        if not self.img_orig:
            return
        if not self.json_path:
            p = filedialog.asksaveasfilename(
                title='JSON speichern',
                defaultextension='.json',
                initialfile=(self.img_path.stem + '.json') if self.img_path else 'unbenannt.json',
                filetypes=[('JSON', '*.json')]
            )
            if not p:
                return
            self.json_path = Path(p)
            self.svg_path = _states_dir(self.json_path) / (self.json_path.stem + '.svg')

        # Bestehendes JSON einlesen und nur 'name'/'windows' aktualisieren --
        # der LED-Batch-Editor (anderer Tab, teilt sich dieselbe Datei) schreibt
        # dort zusaetzlich 'dpi'/'ledBatches'/'chainOrder'/... hinein; ein
        # kompletter Ueberschreiben-mit-nur-2-Feldern wuerde das bei jedem
        # Speichern hier wieder loeschen.
        data = {}
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding='utf-8'))
            except Exception:
                data = {}
        data['name'] = self.img_path.stem if self.img_path else 'unbenannt'
        data['windows'] = self.wins
        # Glasscheiben zusaetzlich zur SVG auch im JSON ablegen (gleicher Inhalt
        # wie die SVG-Ausgabe: Scheiben + Fenster ohne eigene Scheiben, die dann
        # selbst als Glasflaeche zaehlen -- siehe _svg_rects).
        data['glassPanes'] = self._svg_rects()
        try:
            self.json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            self._save_svg()
            self._save_panes_pdf()
            self._status('✓ Gespeichert', C['green'])
            if self.dir_path:
                self._fill_tree()
            self._sync_houses_json()
        except Exception as ex:
            self._status(f'⚠ {ex}', C['red'])

    def _window_has_panes(self, win: dict) -> bool:
        """True, wenn mindestens eine Glasscheibe (per Mittelpunkt) in diesem
        Fensterrahmen liegt."""
        for c in self.panes:
            cx, cy = c['x'] + c['w'] / 2, c['y'] + c['h'] / 2
            if win['x'] <= cx <= win['x'] + win['w'] and win['y'] <= cy <= win['y'] + win['h']:
                return True
        return False

    def _svg_rects(self) -> list[dict]:
        """Alle Rechtecke fuer die SVG-Ausgabe: die Glasscheiben, plus jedes
        Fenster OHNE Scheiben (z.B. ein grosses Fenster, das komplett aus Glas
        besteht) -- das zaehlt dann selbst als Glasflaeche."""
        rects = list(self.panes)
        rects += [w for w in self.wins if not self._window_has_panes(w)]
        return rects

    def _save_svg(self):
        if not self.img_orig or not self.svg_path:
            return
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'width="{self.img_orig.width}" height="{self.img_orig.height}" '
                 f'viewBox="0 0 {self.img_orig.width} {self.img_orig.height}">']
        for c in self._svg_rects():
            parts.append(
                f'  <rect x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" '
                f'fill="none" stroke="red" stroke-width="2"/>')
        parts.append('</svg>')
        self.svg_path.write_text('\n'.join(parts), encoding='utf-8')

    def _save_panes_pdf(self):
        """Nur fuer PDF-Quellen (siehe pdfHouse.py): schreibt <name>.panes.pdf
        in den 'states'-Unterordner neben dem Quell-PDF (siehe _states_dir)
        -- ein neues Zwei-Ebenen-PDF mit einer "Bild"-Ebene (das Foto) und
        einer "Kontur+Scheiben"-Ebene (die importierte Gebaeude-Kontur plus
        die markierten Glasscheiben-Rechtecke). Bei JPG/PNG-Quellen passiert
        nichts (dort gibt es keine Kontur/kein Ausgangs-PDF, dafuer bleibt
        die bisherige SVG-Ausgabe massgeblich)."""
        if not self.img_orig or not self.img_path or self.img_path.suffix.lower() != '.pdf':
            return
        out_path = _states_dir(self.img_path) / (self.img_path.stem + '.panes.pdf')
        try:
            pdfHouse.save_marked_pdf(out_path, self.img_orig, self.outline_polylines, self._svg_rects())
        except Exception as ex:
            self._status(f'⚠ Scheiben-PDF: {ex}', C['red'])

    def _status(self, text, color=C['text'], sticky: bool = False):
        """sticky=True: Meldung bleibt stehen, bis die naechste kommt (fuer
        Fortschrittsanzeigen). Der bisherige Auto-Ausblenden-Timer wird immer
        abgebrochen -- sonst loescht ein alter Timer eine neuere Meldung
        (deshalb 'verschwand' der Raster-Scan-Fortschritt frueher nach 3s)."""
        if self._status_after is not None:
            self.root.after_cancel(self._status_after)
            self._status_after = None
        self._v_status.set(text)
        self._lbl_status.configure(fg=color)
        if not sticky:
            self._status_after = self.root.after(3000, lambda: self._v_status.set(''))

    # ── Window list ───────────────────────────────────────────────────────

    def _render_list(self):
        """Baut die GESAMTE Fensterliste neu auf. Das erstellt fuer jedes Fenster
        ~15 echte Tk-Widgets -- bei vielen Fenstern spuerbar teuer (siehe
        _append_card/_select_window fuer die billigen Pfade fuer den Normalfall:
        ein Fenster hinzufuegen bzw. die Auswahl aendern)."""
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._cards: list[dict] = []
        self._v_count.set(str(len(self.wins)))

        if not self.wins:
            msg = ('Bild wird analysiert oder\nauf dem Bild klicken/ziehen'
                   if self.img_orig else 'Kein Bild geöffnet')
            tk.Label(self._list_frame, text=msg, bg=C['bg'], fg=C['dim'],
                     font=('Segoe UI', 9), justify='center').pack(pady=24)
            return

        for i, w in enumerate(self.wins):
            self._add_card(i, w)

        self._scroll_to_selected()

    def _append_card(self, idx: int, old_sel: int = -1):
        """Fuegt EIN Karten-Widget fuer das neu hinzugefuegte self.wins[idx] an,
        ohne die restliche Liste anzufassen (viel billiger als _render_list bei
        vielen bereits markierten Fenstern). Der zuvor ausgewaehlte Eintrag wird
        nur umgestylt, nicht neu aufgebaut."""
        self._v_count.set(str(len(self.wins)))
        if idx == 0:
            # Liste war leer (Platzhalter-Text) -> einmalig komplett aufbauen
            self._render_list()
            return
        self._add_card(idx, self.wins[idx])
        self._restyle_card(old_sel)
        self._scroll_to_selected()

    def _select_window(self, idx: int):
        """Waehlt ein Fenster aus, ohne die Liste neu aufzubauen -- nur die
        betroffenen zwei Karten (alt/neu) werden umgestylt."""
        if idx == self.sel_idx:
            return
        old = self.sel_idx
        self.sel_idx = idx
        self._restyle_card(old)
        self._restyle_card(idx)
        self._scroll_to_selected()
        self._render_cv()

    def _restyle_card(self, idx: int):
        if not (0 <= idx < len(self._cards)):
            return
        sel = (idx == self.sel_idx)
        BG = C['blue_sel'] if sel else C['bg_panel']
        BD = C['blue']     if sel else C['border']
        card = self._cards[idx]
        card['outer'].configure(bg=BD)
        card['inner'].configure(bg=BG)
        card['head'].configure(bg=BG)
        card['grid'].configure(bg=BG)
        card['lbl_num'].configure(bg=BG)
        card['btn_del'].configure(bg=BG)
        for cell, lbl_widget in card['cells']:
            cell.configure(bg=BG)
            lbl_widget.configure(bg=BG)

    def _scroll_to_selected(self):
        if 0 <= self.sel_idx < len(self.wins):
            self.root.after(10, lambda: self._lcanvas.yview_moveto(
                self.sel_idx / max(len(self.wins), 1)))

    def _add_card(self, idx: int, w: dict):
        sel = (idx == self.sel_idx)
        BG = C['blue_sel'] if sel else C['bg_panel']
        BD = C['blue']     if sel else C['border']

        outer = tk.Frame(self._list_frame, bg=BD, padx=1, pady=1)
        outer.pack(fill='x', padx=4, pady=2)
        inner = tk.Frame(outer, bg=BG, padx=6, pady=5)
        inner.pack(fill='x')

        head = tk.Frame(inner, bg=BG)
        head.pack(fill='x')
        lbl_num = tk.Label(head, text=f'#{idx + 1}', bg=BG, fg='#60a5fa',
                           font=('Segoe UI', 9, 'bold'))
        lbl_num.pack(side='left')
        btn_del = tk.Button(head, text='✕', bg=BG, fg=C['dim'], relief='flat', bd=0,
                  activebackground='#450a0a', activeforeground='#f87171',
                  font=('Segoe UI', 9), command=lambda i=idx: self._remove_window(i))
        btn_del.pack(side='right')

        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill='x', pady=(3, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        cells = []
        for n, (field, lbl) in enumerate([('x', 'X'), ('y', 'Y'), ('w', 'B'), ('h', 'H')]):
            row, col = divmod(n, 2)
            cell = tk.Frame(grid, bg=BG)
            cell.grid(row=row, column=col, padx=2, pady=1, sticky='ew')
            cell.columnconfigure(1, weight=1)

            lbl_widget = tk.Label(cell, text=lbl, bg=BG, fg=C['muted'],
                     font=('Courier New', 8), width=2)
            lbl_widget.grid(row=0, column=0, sticky='w')
            cells.append((cell, lbl_widget))

            var = tk.StringVar(value=str(w[field]))
            ent = tk.Entry(cell, textvariable=var, bg=C['bg_dark'], fg=C['text'],
                           insertbackground='white', relief='flat', bd=1,
                           font=('Courier New', 9),
                           highlightthickness=1,
                           highlightbackground=C['border'],
                           highlightcolor=C['blue'])
            ent.grid(row=0, column=1, sticky='ew', padx=(2, 0))

            def commit(e=None, i=idx, f=field, v=var):
                try:
                    val = max(0, int(v.get()))
                    self.wins[i][f] = val
                    v.set(str(val))
                    self._render_cv()
                    self._schedule_save()
                except ValueError:
                    v.set(str(self.wins[i][f]))

            ent.bind('<Return>',   commit)
            ent.bind('<FocusOut>', commit)

        def on_click(e, i=idx):
            if isinstance(e.widget, tk.Entry):
                return
            self._select_window(i)
            self._center(i)

        for widget in (outer, inner, head, grid):
            widget.bind('<Button-1>', on_click)

        self._cards.append({
            'outer': outer, 'inner': inner, 'head': head, 'grid': grid,
            'lbl_num': lbl_num, 'btn_del': btn_del, 'cells': cells,
        })

    def _remove_window(self, idx: int):
        win = self.wins.pop(idx)
        wcx1, wcy1 = win['x'], win['y']
        wcx2, wcy2 = win['x'] + win['w'], win['y'] + win['h']
        self.panes = [
            c for c in self.panes
            if not (wcx1 <= c['x'] + c['w'] / 2 <= wcx2 and wcy1 <= c['y'] + c['h'] / 2 <= wcy2)
        ]
        self.sel_idx = min(self.sel_idx, len(self.wins) - 1)
        self._render_list()
        self._render_cv()
        self._schedule_save()

    def _center(self, idx: int):
        if not (0 <= idx < len(self.wins)):
            return
        w = self.wins[idx]
        W = self.cv.winfo_width()  or 800
        H = self.cv.winfo_height() or 600
        self.off_x = W / 2 - (w['x'] + w['w'] / 2) * self.zoom
        self.off_y = H / 2 - (w['y'] + w['h'] / 2) * self.zoom
        self._render_cv()

    # ── Folder tree ───────────────────────────────────────────────────────

    def _fill_tree(self, parent='', path: Path | None = None):
        if path is None:
            path = self.dir_path
            self.tree.delete(*self.tree.get_children())
        if not path or not path.is_dir():
            return
        try:
            entries = sorted(path.iterdir(),
                             key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith('.') or entry.name.endswith(EXCLUDE_SUFFIXES):
                continue
            if entry.is_dir():
                # Haus-Ordner (Konvention: Unterordner mit genau einer
                # zugehoerigen Bild-/PDF-Datei, siehe _resolve_house_file)
                # werden FLACH als EIN klickbarer Eintrag dargestellt --
                # kein Foldout/Aufklappen noetig, um an die Datei darin zu
                # kommen. Nur "echte" Sammelordner (mehrere Haeuser als
                # Unterordner, z.B. public/houses selbst) bekommen weiterhin
                # den aufklappbaren Ordner-Knoten.
                house_file = self._resolve_house_file(entry)
                if house_file is not None:
                    has_json = house_file.with_suffix('.json').exists()
                    active   = (self.img_path == house_file)
                    icon     = '✅' if has_json else '🖼 '
                    prefix   = '▶ ' if active else '   '
                    self.tree.insert(parent, 'end',
                                     text=f'{prefix}{icon} {entry.name}',
                                     values=[str(house_file)])
                    continue
                node = self.tree.insert(parent, 'end',
                                        text=f'📁  {entry.name}',
                                        values=[str(entry)], open=False)
                self.tree.insert(node, 'end', text='', values=['__loading__'])
            elif entry.suffix.lower() in IMAGE_EXTS:
                has_json = entry.with_suffix('.json').exists()
                active   = (self.img_path == entry)
                icon     = '✅' if has_json else '🖼 '
                prefix   = '▶ ' if active else '   '
                self.tree.insert(parent, 'end',
                                 text=f'{prefix}{icon} {entry.name}',
                                 values=[str(entry)])

    def _tree_open(self, _e):
        node = self.tree.focus()
        kids = self.tree.get_children(node)
        if len(kids) == 1 and self.tree.item(kids[0], 'values') == ('__loading__',):
            self.tree.delete(kids[0])
            p = Path(self.tree.item(node, 'values')[0])
            self._fill_tree(node, p)

    def _tree_click(self, e):
        node = self.tree.identify_row(e.y)
        if not node:
            return
        vals = self.tree.item(node, 'values')
        if not vals or vals[0] == '__loading__':
            return
        p = Path(vals[0])
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            self._load(p)

    # ── Drag & drop ───────────────────────────────────────────────────────

    def _dnd_drop(self, e):
        raw = e.data.strip()
        if raw.startswith('{') and raw.endswith('}'):
            raw = raw[1:-1]
        p = Path(raw)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            self._load(p)

    # ── Run ───────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


def _launch_combined():
    """Startet Fenster-Markierung und LED-Batch-Editor gemeinsam in drei Tabs.
    Alle Tools teilen sich ein Hauptfenster; wechselt man zum LED-Tab, wird
    dort automatisch das im Fenster-Tab geoeffnete Bild uebernommen (sofern im
    LED-Tab noch keins offen ist). Der LED-Tab listet ausserdem selbst alle
    Haeuser aus public/houses. Der dritte Tab (LED-Kette) teilt sich dieselbe
    LED-App-Instanz wie Tab 2 (Platzierungen/Varianten/Fenster) und dient nur
    dazu, die Batches zu einer Kette zu verbinden und global durchzunummerieren."""
    Root = TkinterDnD.Tk if _DND else tk.Tk
    root = Root()
    root.title('Window Tool + LED Batch Editor')
    root.geometry('1400x820')
    root.minsize(900, 560)
    root.configure(bg=C['bg'])

    nb = ttk.Notebook(root)
    nb.pack(fill='both', expand=True)
    tab_win = tk.Frame(nb, bg=C['bg'])
    tab_led = tk.Frame(nb, bg=C['bg'])
    tab_chain = tk.Frame(nb, bg=C['bg'])
    nb.add(tab_win, text='Fenster markieren')
    nb.add(tab_led, text='LED-Batches')
    nb.add(tab_chain, text='LED-Kette')

    win_app = App(root=root, parent=tab_win,
                  is_active=lambda: nb.index('current') == 0)

    led_app = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ledBatchEditor'))
        from led_batch_editor import App as LedApp
        led_app = LedApp(root=root, parent=tab_led,
                         is_active=lambda: nb.index('current') == 1)
        led_app.build_chain_tab(tab_chain)
    except Exception as ex:
        tk.Label(tab_led, text=f'LED Batch Editor konnte nicht geladen werden:\n{ex}',
                 bg=C['bg'], fg='#f87171', font=('Segoe UI', 10),
                 justify='center').pack(expand=True)

    def on_tab_change(_e):
        cur = nb.index('current')
        if led_app is not None and cur in (1, 2):
            # Beim Wechsel in den LED-Tab das aktuell markierte Bild uebernehmen,
            # falls dort noch keins geoeffnet ist ...
            if led_app.img_path is None and win_app.img_path is not None:
                led_app._load_image(win_app.img_path)
            else:
                # ... sonst die Fensterliste frisch von der Platte einlesen --
                # der Fenster-Tab kann sie veraendert haben, waehrend dieser
                # Tab schon offen war.
                led_app._reload_windows()
        # Beim Wechsel in den Ketten-Tab dessen (eigene, auto-fit) Ansicht
        # neu einpassen -- Groessenaenderungen des Fensters waehrend er
        # nicht sichtbar war werden sonst nicht mitbekommen.
        if led_app is not None and cur == 2:
            led_app._fit_chain()
            led_app._render_chain_tab()

    nb.bind('<<NotebookTabChanged>>', on_tab_change)
    root.mainloop()


if __name__ == '__main__':
    _launch_combined()
