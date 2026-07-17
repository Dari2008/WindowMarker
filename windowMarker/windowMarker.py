#!/usr/bin/env python3
"""
Window Marker
Markiert Fenster in Gebäudebildern und speichert als JSON.

Abhängigkeiten:
  pip install Pillow
  pip install tkinterdnd2   (optional, für Drag & Drop)
"""

import tkinter as tk
from tkinter import ttk, filedialog
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageTk
except ImportError:
    print("Fehler: Pillow fehlt.  Bitte: pip install Pillow")
    sys.exit(1)

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except ImportError:
    _DND = False

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
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
}


# ─────────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        Root = TkinterDnD.Tk if _DND else tk.Tk
        self.root = Root()
        self.root.title("Window Marker")
        self.root.geometry("1300x760")
        self.root.minsize(800, 500)
        self.root.configure(bg=C['bg'])

        # State
        self.img_orig: Image.Image | None = None
        self.img_path: Path | None = None
        self.json_path: Path | None = None
        self.dir_path: Path | None = None
        self.wins: list[dict] = []
        self.sel_idx = -1

        # Viewport
        self.zoom = 1.0
        self.off_x = 0.0
        self.off_y = 0.0

        # Interaction
        self._space = False
        self._pan_ref: tuple | None = None   # (canvas_x - off_x, canvas_y - off_y)
        self._draw_a: tuple | None = None    # img-coord start
        self._draw_b: tuple | None = None    # img-coord current

        # Image cache
        self._cache_zoom: float | None = None
        self._cache_tk: ImageTk.PhotoImage | None = None

        self._save_after = None

        self._style()
        self._build()
        self._bind()

    # ── Style ──────────────────────────────────────────────────────────────

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.', background=C['bg'], foreground=C['text'], font=('Segoe UI', 9))
        s.configure('TFrame', background=C['bg'])
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
        tb = tk.Frame(self.root, bg=C['bg_dark'], height=44)
        tb.pack(side='top', fill='x')
        tb.pack_propagate(False)

        ttk.Button(tb, text='Bild öffnen',   command=self._open_file).pack(side='left', padx=(8, 2), pady=6)
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
        main = tk.Frame(self.root, bg=C['bg'])
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

        # Right panel (hidden until folder opened)
        self._rsep = tk.Frame(main, bg=C['border'], width=1)
        self._rpanel = tk.Frame(main, bg=C['bg'], width=244)
        self._rpanel.pack_propagate(False)

        rh = tk.Frame(self._rpanel, bg=C['bg_dark'], height=32)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        self._lbl_folder = tk.Label(rh, text='Ordner', bg=C['bg_dark'], fg=C['text'],
                                    font=('Segoe UI', 9, 'bold'))
        self._lbl_folder.pack(side='left', padx=8, pady=6)
        ttk.Button(rh, text='✕', command=self._close_folder, width=2).pack(side='right', padx=4, pady=4)
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
        self.root.bind('<KeyPress-space>',   self._kb_space_dn)
        self.root.bind('<KeyRelease-space>', self._kb_space_up)
        self.root.bind('<Delete>',           self._kb_del)
        self.root.bind('<BackSpace>',        self._kb_del)
        self.root.bind('<Escape>',           self._kb_esc)

        self.cv.bind('<ButtonPress-1>',   self._cv_dn)
        self.cv.bind('<B1-Motion>',       self._cv_mv)
        self.cv.bind('<ButtonRelease-1>', self._cv_up)
        self.cv.bind('<ButtonPress-2>',   self._pan_dn)
        self.cv.bind('<B2-Motion>',       self._pan_mv)
        self.cv.bind('<ButtonRelease-2>', self._pan_up)
        self.cv.bind('<MouseWheel>',      self._scroll)
        self.cv.bind('<Configure>',       lambda _: self._render_cv())

        self.tree.bind('<ButtonRelease-1>',  self._tree_click)
        self.tree.bind('<<TreeviewOpen>>',   self._tree_open)

        if _DND:
            self.cv.drop_target_register(DND_FILES)
            self.cv.dnd_bind('<<Drop>>', self._dnd_drop)

    # ── Canvas rendering ──────────────────────────────────────────────────

    def _render_cv(self):
        self.cv.delete('all')
        W = self.cv.winfo_width()  or 800
        H = self.cv.winfo_height() or 600

        if not self.img_orig:
            self.cv.create_text(W // 2, H // 2,
                text='Bild per Drag & Drop ablegen\noder "Bild öffnen" klicken',
                fill=C['dim'], font=('Segoe UI', 12), justify='center')
            return

        # Scaled image (cached per zoom)
        if self._cache_zoom != self.zoom:
            iw = max(1, int(self.img_orig.width  * self.zoom))
            ih = max(1, int(self.img_orig.height * self.zoom))
            method = Image.LANCZOS if self.zoom < 1 else Image.NEAREST
            self._cache_tk   = ImageTk.PhotoImage(self.img_orig.resize((iw, ih), method))
            self._cache_zoom = self.zoom

        self.cv.create_image(int(self.off_x), int(self.off_y),
                             image=self._cache_tk, anchor='nw')

        # Window overlays
        for i, w in enumerate(self.wins):
            sel = (i == self.sel_idx)
            x1 = self.off_x + w['x'] * self.zoom
            y1 = self.off_y + w['y'] * self.zoom
            x2 = x1 + w['w'] * self.zoom
            y2 = y1 + w['h'] * self.zoom
            self.cv.create_rectangle(x1, y1, x2, y2,
                fill=C['blue_sel'] if sel else C['blue_dim'],
                stipple='gray25',
                outline='#60a5fa' if sel else C['blue'],
                width=2 if sel else 1)
            fs = max(7, min(int(10 * self.zoom), 14))
            self.cv.create_text(x1 + 3, y1 + 2,
                text=str(i + 1),
                fill='#bfdbfe' if sel else '#93c5fd',
                font=('Segoe UI', fs, 'bold'), anchor='nw')

        # Drawing preview
        if self._draw_a and self._draw_b:
            ax, ay = self._draw_a
            bx, by = self._draw_b
            x1 = self.off_x + min(ax, bx) * self.zoom
            y1 = self.off_y + min(ay, by) * self.zoom
            x2 = self.off_x + max(ax, bx) * self.zoom
            y2 = self.off_y + max(ay, by) * self.zoom
            self.cv.create_rectangle(x1, y1, x2, y2,
                outline='#fbbf24', fill='#451a03',
                stipple='gray12', dash=(4, 3), width=1)

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
        self._cache_zoom = None
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
        # Hit test windows (topmost first)
        for i in range(len(self.wins) - 1, -1, -1):
            w = self.wins[i]
            if w['x'] <= ix <= w['x'] + w['w'] and w['y'] <= iy <= w['y'] + w['h']:
                self.sel_idx = i
                self._render_list()
                self._render_cv()
                return
        # Start drawing
        self._draw_a = (ix, iy)
        self._draw_b = (ix, iy)

    def _cv_mv(self, e):
        if not self.img_orig:
            return
        if self._pan_ref:
            self.off_x = e.x - self._pan_ref[0]
            self.off_y = e.y - self._pan_ref[1]
            self._render_cv()
        elif self._draw_a:
            self._draw_b = self._s2i(e.x, e.y)
            self._render_cv()

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
                self.wins.append({'x': x, 'y': y, 'w': w, 'h': h})
                self.sel_idx = len(self.wins) - 1
                self._render_list()
                self._schedule_save()
            self._draw_a = self._draw_b = None
            self._render_cv()

    def _pan_dn(self, e):
        self._pan_ref = (e.x - self.off_x, e.y - self.off_y)
        self.cv.configure(cursor='fleur')

    def _pan_mv(self, e):
        if self._pan_ref:
            self.off_x = e.x - self._pan_ref[0]
            self.off_y = e.y - self._pan_ref[1]
            self._render_cv()

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
        self._cache_zoom = None
        self._render_cv()

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
        self._cache_zoom = None
        self._render_cv()

    # ── Keyboard ──────────────────────────────────────────────────────────

    def _kb_space_dn(self, e):
        if isinstance(e.widget, tk.Entry):
            return
        self._space = True
        if self.img_orig and not self._pan_ref:
            self.cv.configure(cursor='hand2')

    def _kb_space_up(self, _e):
        self._space = False
        if not self._pan_ref:
            self.cv.configure(cursor='crosshair')

    def _kb_del(self, e):
        if isinstance(e.widget, tk.Entry):
            return
        if 0 <= self.sel_idx < len(self.wins):
            self.wins.pop(self.sel_idx)
            self.sel_idx = min(self.sel_idx, len(self.wins) - 1)
            self._render_list()
            self._render_cv()
            self._schedule_save()

    def _kb_esc(self, _e):
        if self._draw_a:
            self._draw_a = self._draw_b = None
            self._render_cv()
        else:
            self.sel_idx = -1
            self._render_list()
            self._render_cv()

    # ── File operations ───────────────────────────────────────────────────

    def _open_file(self):
        p = filedialog.askopenfilename(
            title='Bild öffnen',
            filetypes=[('Bilder', ' '.join(f'*{e}' for e in IMAGE_EXTS)), ('Alle', '*.*')]
        )
        if p:
            self._load(Path(p))

    def _open_folder(self):
        p = filedialog.askdirectory(title='Ordner öffnen')
        if p:
            self.dir_path = Path(p)
            self._lbl_folder.configure(text=self.dir_path.name)
            self._rsep.pack(side='right', fill='y')
            self._rpanel.pack(side='right', fill='y')
            self._fill_tree()

    def _close_folder(self):
        self._rsep.pack_forget()
        self._rpanel.pack_forget()
        self.dir_path = None
        self.tree.delete(*self.tree.get_children())

    def _load(self, path: Path):
        try:
            im = Image.open(path)
            im.load()
        except Exception as ex:
            self._status(f'⚠ Ladefehler: {ex}', '#f87171')
            return

        # Convert palette / CMYK → RGBA for display
        if im.mode not in ('RGB', 'RGBA', 'L'):
            im = im.convert('RGBA')

        self.img_orig     = im
        self.img_path     = path
        self.json_path    = path.with_suffix('.json')
        self.wins         = []
        self.sel_idx      = -1
        self._cache_zoom  = None

        self._v_name.set(f'{path.name}   ({im.width} × {im.height} px)')

        # Load matching JSON
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding='utf-8'))
                self.wins = data.get('windows', [])
            except Exception:
                pass

        self._fit()
        self._render_list()
        if self.dir_path:
            self._fill_tree()

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

        data = {
            'name':    self.img_path.stem if self.img_path else 'unbenannt',
            'windows': self.wins,
        }
        try:
            self.json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            self._status('✓ Gespeichert', '#4ade80')
            if self.dir_path:
                self._fill_tree()
        except Exception as ex:
            self._status(f'⚠ {ex}', '#f87171')

    def _status(self, text, color='#e2e8f0'):
        self._v_status.set(text)
        self._lbl_status.configure(fg=color)
        self.root.after(2500, lambda: self._v_status.set(''))

    # ── Window list ───────────────────────────────────────────────────────

    def _render_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._v_count.set(str(len(self.wins)))

        if not self.wins:
            msg = ('Auf dem Bild ziehen,\num Fenster zu markieren'
                   if self.img_orig else 'Kein Bild geöffnet')
            tk.Label(self._list_frame, text=msg, bg=C['bg'], fg=C['dim'],
                     font=('Segoe UI', 9), justify='center').pack(pady=24)
            return

        for i, w in enumerate(self.wins):
            self._add_card(i, w)

        # Scroll to selected
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

        # Header
        head = tk.Frame(inner, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text=f'#{idx + 1}', bg=BG, fg='#60a5fa',
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        tk.Button(head, text='✕', bg=BG, fg=C['dim'], relief='flat', bd=0,
                  activebackground='#450a0a', activeforeground='#f87171',
                  font=('Segoe UI', 9), command=lambda i=idx: self._del_win(i)
                  ).pack(side='right')

        # 2×2 field grid
        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill='x', pady=(3, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        for n, (field, lbl) in enumerate([('x', 'X'), ('y', 'Y'), ('w', 'B'), ('h', 'H')]):
            row, col = divmod(n, 2)
            cell = tk.Frame(grid, bg=BG)
            cell.grid(row=row, column=col, padx=2, pady=1, sticky='ew')
            cell.columnconfigure(1, weight=1)

            tk.Label(cell, text=lbl, bg=BG, fg=C['muted'],
                     font=('Courier New', 8), width=2).grid(row=0, column=0, sticky='w')

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

        # Click card → select
        def on_click(e, i=idx):
            if isinstance(e.widget, tk.Entry):
                return
            self.sel_idx = i
            self._render_list()
            self._render_cv()
            self._center(i)

        for widget in (outer, inner, head, grid):
            widget.bind('<Button-1>', on_click)

    def _del_win(self, idx: int):
        self.wins.pop(idx)
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
            if entry.name.startswith('.'):
                continue
            if entry.is_dir():
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


if __name__ == '__main__':
    App().run()
