#!/usr/bin/env python3
"""
LED Batch Editor
Platziert physische SK6812-RGBW-LED-Batches (PCBs) auf Gebäudebildern
und speichert die Positionen (in mm, auf ein anpassbares Rechteck skaliert)
als JSON neben dem Bild - fuer spaeteren Export an einen ESP32.

Abhaengigkeiten:
  pip install Pillow
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import re
import sys
import uuid
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageDraw
except ImportError:
    print("Fehler: Pillow fehlt.  Bitte: pip install Pillow")
    sys.exit(1)

# pdfHouse.py liegt in windowMarker/ (dieselbe Cross-Import-Handhabung wie
# windowTool.py._launch_combined() in die Gegenrichtung) -- optional: ohne
# pymupdf installiert bleibt der alte JPG/PNG-Workflow trotzdem nutzbar,
# nur PDF-Quellen liefern dann eine klare Fehlermeldung beim Laden.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'windowMarker'))
try:
    import pdfHouse
except ImportError:
    pdfHouse = None
# dxfExport/csvExport brauchen (wie pdfHouse) ezdxf/pymupdf -- optional, wie
# die Footprint-Kontur-Vorschau weiter unten (ezdxf = None), damit der Rest
# des Editors auch ohne diese Pakete nutzbar bleibt (siehe _export_project_dxf/
# _export_project_csv fuer die entsprechende Fehlermeldung, statt eines
# Crashs beim Modul-Import).
try:
    import dxfExport
    import csvExport
    import footprintScale
except ImportError:
    dxfExport = None
    csvExport = None
    footprintScale = None

# ── Pfade ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).resolve().parent
PUBLIC_DIR    = SCRIPT_DIR.parent / 'public'
# Jedes Haus liegt in seinem EIGENEN Unterordner (public/houses/<name>/
# <name>.EXT + <name>.json usw.) -- siehe windowTool.py's DEFAULT_HOUSES_DIR/
# _sync_houses_json fuer denselben Ordner aus Sicht des Fenster-Markieren-Tabs.
HOUSES_DIR    = PUBLIC_DIR / 'houses'
# Liegt bewusst NICHT in public/houses/ -- dieser Ordner soll nur Haus-
# spezifische Dateien enthalten (siehe images.json-Autosync); die
# bildübergreifende PCB-Varianten-Bibliothek gehoert eine Ebene hoeher.
VARIANTS_PATH = PUBLIC_DIR / 'batch_variants.json'

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.pdf'}
EXCLUDE_MARKERS = ('._annotated', '._greenness', '._greenmask', '._redness', '._redmask', '.panes.pdf')

LED_HIT_R = 9        # Klick-Radius fuer LEDs (px, Bildschirm)
DEFAULT_DPI = 96.0   # falls weder JSON noch Bilddatei eine Aufloesung liefern
# Beide muessen gleich sein: der Einrasten-Schritt entscheidet anhand von
# SNAP_PX, welche Fenster eine Platzierung "beruehrt" und richtet die LED-Reihe
# an der obersten Kante DIESER Fenster aus. Waere WINDOW_TOL (fuer die
# an/aus-Zuordnung) kleiner, koennte ein Fenster, das gerade noch fuer's
# Einrasten zaehlte, danach als "nicht beruehrt" gelten und faelschlich
# deaktiviert werden -- siehe _auto_assign.
SNAP_PX = 14         # Einrast-Abstand an Fenster-Oberkanten (Bild-px)
WINDOW_TOL = SNAP_PX # Toleranz fuer "LED beruehrt Fenster" (muss >= SNAP_PX sein)
# Beruehren mehrere (nicht manuell gesetzte) LEDs dasselbe Fenster und ihre
# gemeinsame Spannweite ist >= 30mm, ist das Fenster/die Reihe zu lang fuer nur
# eine mittige Lampe -- dann bleiben ALLE beruehrenden LEDs an, statt nur die
# mittigste (sonst waere ein grosses Fenster nur an einer Stelle beleuchtet).
LONG_RUN_MM = 30.0
# Groesse des Kabel-Verbinder-Markers (echte mm) -- sowohl im Varianten-
# Designer als auch bei platzierten Batches auf dem Hauptbild.
CONNECTOR_W_MM = 5.0
CONNECTOR_H_MM = 8.0

# Maximale Kabellaenge zwischen dem DOUT einer Platine und dem DIN der
# naechsten in der Kette (echte mm, ueber px_per_mm) -- laengere
# Verbindungen werden im Ketten-Tab rot statt amber gezeichnet und mit der
# tatsaechlichen Laenge beschriftet (siehe _render_chain_cv).
MAX_CONNECTION_MM = 100.0

# ── "🪄 Auto platzieren" (siehe App._auto_place) ────────────────────────────
# Bild-px-Toleranz, innerhalb derer Fenster als "in derselben Reihe" gelten
# (Clustering nach Oberkante y) -- absichtlich grosszuegiger als SNAP_PX,
# weil von Hand nachgezeichnete Fensterrahmen selten pixelgenau auf einer
# Linie liegen.
AUTO_PLACE_ROW_TOL_PX = 30
# Schwarzer Eingangs-Knoten am unteren Rand der Gebaeude-Kontur (Einspeisung
# der Kette von aussen) -- daran wird die ERSTE Platzierung der Kette (die
# am weitesten unten UND am weitesten mittig liegende, siehe
# _auto_connect_chain) mit ihrem DIN angeschlossen (echte mm).
INPUT_NODE_W_MM = 8.0
INPUT_NODE_H_MM = 5.0

# Physische LED-Gehaeusegroesse (SK6812-RGBW, 5050-Bauform: 5x5 mm) und
# Fallback-Referenz-Platinenumriss-Groesse (dieselben Werte wie
# windowMarker/dxfExport.py, damit Vorschau hier und DXF-Export spaeter
# uebereinstimmen), falls weder die Platzierung noch die Variante eine
# eigene Footprint-Groesse eingetragen hat -- siehe resolve_footprint_size.
# Wird gebraucht, um die Footprint-Kontur mittig ueber der tatsaechlichen
# Ausdehnung der LEDs zu zeichnen -- siehe _footprint_anchor.
LED_WIDTH_MM     = 5.0
FOOTPRINT_WIDTH  = 75.0
FOOTPRINT_HEIGHT = 60.0

# Footprint-Groesse per Ziehen an den Kanten aendern (siehe App._hit_footprint_edge/
# _cv_dn/_cv_mv): Trefferzone (Bildschirm-px) um eine Kante, und Mindestgroesse,
# damit width_mm/height_mm nie auf 0 oder negativ gezogen werden koennen.
FOOTPRINT_RESIZE_TOL_PX = 8
FOOTPRINT_MIN_MM = 5.0

# Rahmen-Rechteck (siehe App._hit_frame_edge/_cv_dn/_cv_mv, windowMarker.
# dxfExport.clip_outline_to_frame/frame_side_hole_rects_mm): dieselbe
# Trefferzone wie bei Footprint-Kanten, und eine Mindestgroesse, damit sich
# das Rechteck nicht auf 0 oder negativ zusammenziehen laesst.
FRAME_RESIZE_TOL_PX = 8
FRAME_MIN_SIZE_MM = 20.0

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
    'green':    '#4ade80',
    'red':      '#f87171',
    'amber':    '#fbbf24',
    'orange':   '#f97316',
}


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-')
    return s or 'variante'


def bind_wheel_scroll(area: tk.Widget, canvas: tk.Canvas):
    """Mausrad-Scrollen fuer eine Scroll-Canvas, das auch dann greift, wenn der
    Cursor ueber einem der eingebetteten Kind-Widgets (Karten/Labels/Buttons/
    Eintraege) steht -- praktisch die gesamte sichtbare Listenflaeche. Ein
    direktes <MouseWheel>-Bind NUR auf die Canvas selbst feuert naemlich nur,
    wenn der Cursor ueber deren nacktem Hintergrund liegt, nicht ueber Kindern.
    Bindet das Rad daher GLOBAL, aber nur solange sich der Cursor innerhalb der
    aeusseren Wrapper-Flaeche `area` befindet (Enter/Leave dieser Flaeche)."""
    def _wheel(e):
        canvas.yview_scroll(-(e.delta // 120), 'units')
    def _on_enter(_e):
        canvas.bind_all('<MouseWheel>', _wheel)
    def _on_leave(_e):
        canvas.unbind_all('<MouseWheel>')
    area.bind('<Enter>', _on_enter, add='+')
    area.bind('<Leave>', _on_leave, add='+')


def unique_id(base: str, existing: set) -> str:
    if base not in existing:
        return base
    n = 2
    while f'{base}-{n}' in existing:
        n += 1
    return f'{base}-{n}'


def _find_house_image_path(house_dir: Path, name: str) -> Path | None:
    """Findet die eigentliche Bilddatei EINES Hauses (dieselbe Logik wie
    App._scan_images): <name>.EXT mit EXT aus IMAGE_EXTS, direkt im
    Hausordner, ohne die generierten Zwischendateien (siehe
    EXCLUDE_MARKERS -- z.B. '._annotated.png'). None, wenn keine passt."""
    if not house_dir.is_dir():
        return None
    for f in house_dir.iterdir():
        if (f.stem == name and f.suffix.lower() in IMAGE_EXTS
                and not any(m in f.name for m in EXCLUDE_MARKERS)):
            return f
    return None


def load_variant() -> dict | None:
    """Es gibt bewusst nur EINE LED-Variante (keine Bibliothek mehrerer
    benannter PCB-Typen mehr) -- batch_variants.json haelt daher ein
    einzelnes 'variant'-Objekt statt eines Arrays. Gibt None zurueck, wenn
    noch keine Variante angelegt wurde."""
    if VARIANTS_PATH.exists():
        try:
            return json.loads(VARIANTS_PATH.read_text(encoding='utf-8')).get('variant')
        except Exception:
            return None
    return None


def save_variant(variant: dict | None):
    VARIANTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VARIANTS_PATH.write_text(
        json.dumps({'variant': variant}, indent=2, ensure_ascii=False), encoding='utf-8')


def variant_bbox(variant: dict):
    leds = variant.get('leds', [])
    if not leds:
        return 0.0, 0.0, 1.0, 1.0
    xs = [l['x_mm'] for l in leds]
    ys = [l['y_mm'] for l in leds]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    return minx, miny, (maxx - minx) or 1.0, (maxy - miny) or 1.0


def led_image_positions(variant: dict, x: float, y: float, px_per_mm: float,
                        flipped: bool = False):
    """LED-Positionen des Batches (mm-Layout) ab Anker (x, y) in Bild-px --
    MASSSTABSGETREU ueber px_per_mm (aus DPI). Der LED-Abstand kommt allein aus
    der Variante; Platzierungen koennen nicht gestreckt oder skaliert werden.

    flipped=True spiegelt die PHYSISCHE Lage der LEDs an der Y-Achse (die
    montierte Platine liegt seitenverkehrt) -- die Reihenfolge der Liste
    (self.leds, d.h. die Kettenfolge auf der Platine) bleibt unveraendert;
    welche Richtung das fuer die globale Nummerierung bedeutet, wird separat
    in _recompute_chain entschieden."""
    minx, miny, w_mm, _ = variant_bbox(variant)
    pts = []
    for l in variant.get('leds', []):
        lx = l['x_mm'] - minx
        if flipped:
            lx = w_mm - lx
        pts.append((x + lx * px_per_mm, y + (l['y_mm'] - miny) * px_per_mm))
    return pts


def default_din_mm(variant: dict) -> dict:
    """Automatische DIN-Position (mm, IM ROHEN Varianten-Koordinatensystem --
    nicht Bbox-relativ), solange die Variante keine eigene `din_mm` hat:
    fester Ursprung (0,0) der Platine."""
    return {'x_mm': 0.0, 'y_mm': 0.0}


def default_dout_mm(variant: dict) -> dict:
    """Automatische DOUT-Position (mm, roh), solange die Variante keine
    eigene `dout_mm` hat: kurz hinter der LETZTEN LED IN KETTENREIHENFOLGE
    (hoechster Index -- die tatsaechliche Richtung des Datenflusses, NICHT
    die raeumlich am weitesten rechts liegende LED), im Abstand
    CONNECTOR_W_MM -- ungefaehr die eigene Kastengroesse, wie beim echten
    Bauteil auf der Platine."""
    leds = variant.get('leds', [])
    last_led = leds[-1] if leds else {'x_mm': 0.0, 'y_mm': 0.0}
    return {'x_mm': last_led['x_mm'] + CONNECTOR_W_MM, 'y_mm': last_led['y_mm']}


def connector_positions(variant: dict, x: float, y: float, px_per_mm: float,
                        flipped: bool = False):
    """Bildschirm-/Bild-Positionen der beiden Kabelverbinder einer Platinen-
    Platzierung -- exakt dieselbe Transform wie led_image_positions, nur fuer
    zwei feste Punkte statt fuer jede einzelne LED:
      - DIN  (Daten-Eingang): `variant['din_mm']`, falls im Varianten-Designer
        von Hand verschoben, sonst der automatische mm-Ursprung (0,0) der
        Platine (default_din_mm).
      - DOUT (Daten-Ausgang): `variant['dout_mm']`, falls von Hand verschoben,
        sonst automatisch kurz hinter der letzten LED in Kettenreihenfolge
        (default_dout_mm).
    Massgeblich ist bei der Automatik die LISTEN-/INDEX-Reihenfolge der
    Variante (Index 0 = DIN-seitig, Index n-1 = DOUT-seitig), NICHT die
    raeumliche x_mm-Position -- bei einem Layout, das nicht streng von links
    nach rechts angeklickt wurde (z.B. Zickzack-Anordnung), waere "die LED
    mit dem groessten x_mm" nicht dieselbe wie "die letzte LED der Kette".
    Gibt (din_pt, dout_pt) zurueck. Wird fuer die Kettenverbindungslinien
    gebraucht: das physische Kabel laeuft von DOUT der einen Platine zu DIN
    der naechsten -- NICHT von Ursprung zu Ursprung (das ergaebe bei
    gespiegelten Platzierungen einen unnatuerlichen Zickzack, weil DIN dann
    auf die jeweils andere Seite der Platzierung springt)."""
    minx, miny, w_mm, _ = variant_bbox(variant)
    din_mm  = variant.get('din_mm')  or default_din_mm(variant)
    dout_mm = variant.get('dout_mm') or default_dout_mm(variant)

    din_lx  = din_mm['x_mm']  - minx
    dout_lx = dout_mm['x_mm'] - minx
    if flipped:
        din_lx  = w_mm - din_lx
        dout_lx = w_mm - dout_lx

    din  = (x + din_lx  * px_per_mm, y + (din_mm['y_mm']  - miny) * px_per_mm)
    dout = (x + dout_lx * px_per_mm, y + (dout_mm['y_mm'] - miny) * px_per_mm)
    return din, dout


# ── Referenz-Footprint (generiertes Rechteck, siehe windowMarker/
# footprintScale.py) ─────────────────────────────────────────────────────
# Wird sowohl im Varianten-Designer als auch bei jeder Platzierung auf dem
# Hausbild eingeblendet, damit man sieht, wo die physische Platine tatsaechlich
# hinragt -- nicht nur die einzelnen LED-Punkte. KEINE Auswahl zwischen
# benannten Footprint-"Typen" (fruehere "Footprint-Small"/"-Big") mehr --
# jede Platzierung/Variante traegt einfach ihre eigene Breite/Hoehe direkt
# ein (siehe resolve_footprint_size), das deckt genauso ab, dass sich die
# Groesse von Fenster zu Fenster unterscheiden kann.

_footprint_polylines_cache: dict = {}   # (width_mm, height_mm) -> [([(x,y),...], closed), ...]


def resolve_footprint_size(variant: dict | None, placement: dict | None = None) -> tuple:
    """Effektive Footprint-Groesse (width_mm, height_mm): zuerst die
    Platzierung selbst (`placement['width_mm']`/`['height_mm']`, falls
    BEIDE gesetzt sind), sonst die Variante (`variant['footprint_width_mm']`/
    `['footprint_height_mm']`), sonst der Fallback FOOTPRINT_WIDTH/HEIGHT.
    Ersetzt die fruehere Auswahl ueber einen Footprint-NAMEN -- jede
    Platzierung/Variante traegt ihre Groesse jetzt direkt ein, dadurch kann
    sie sich (falls gewuenscht) von Fenster zu Fenster unterscheiden."""
    if placement and placement.get('width_mm') and placement.get('height_mm'):
        return placement['width_mm'], placement['height_mm']
    variant = variant or {}
    width_mm = variant.get('footprint_width_mm') or FOOTPRINT_WIDTH
    height_mm = variant.get('footprint_height_mm') or FOOTPRINT_HEIGHT
    return width_mm, height_mm


def _load_footprint_polylines(width_mm: float, height_mm: float) -> list:
    """Generiert die Footprint-Kontur (ein Rechteck von width_mm x
    height_mm, siehe windowMarker/footprintScale.get_footprint_points)
    EINMAL pro Groesse und cacht das Ergebnis -- Generieren bei jedem
    Redraw waere unnoetig teuer. get_footprint_points() gibt dazu ein
    EIGENSTAENDIGES ezdxf-Dokument zurueck (nicht nur rohe Punkte) -- die
    LWPOLYLINE-Punkte werden hier aus dessen modelspace() ausgelesen. Gibt
    eine leere Liste zurueck, wenn footprintScale fehlt (Footprint-Anzeige
    ist rein optisch, kein Grund, deswegen abzustuerzen).

    Y WIRD HIER GESPIEGELT (height_mm - y): footprintScale.py rechnet in
    PHYSISCHER Konvention (Y=0 = UNTERKANTE, wo die Bodenplatten-Zungen
    sitzen, Y=height_mm = OBERKANTE, naeher an den LEDs), waehrend
    _footprint_anchor (wie der Rest dieser Datei) in BILD-Konvention rechnet
    (Y=0 = oben, waechst nach unten). Ohne diese Spiegelung landet die
    gesamte Footprint-Kontur auf dem Kopf (siehe dxfExport._footprint_scaled_points
    fuer denselben Fix auf der Export-Seite)."""
    key = (width_mm, height_mm)
    if key not in _footprint_polylines_cache:
        polylines = []
        if footprintScale is not None:
            try:
                doc = footprintScale.get_footprint_points(width_mm, height_mm)
                msp = doc.modelspace()
                polylines = [
                    ([(pt[0], height_mm - pt[1]) for pt in e.get_points()], True)
                    for e in msp.query('LWPOLYLINE')
                ]
            except Exception:
                polylines = []
        _footprint_polylines_cache[key] = polylines
    return _footprint_polylines_cache[key]


def _footprint_geometry_bbox(width_mm: float, height_mm: float) -> tuple:
    """Bounding-Box der generierten Footprint-Geometrie (siehe
    _load_footprint_polylines) -- (0, 0, width_mm, height_mm), da
    footprintScale.get_footprint_points() bereits auf (0, 0) normiert.
    Faellt auf (0, 0, FOOTPRINT_WIDTH, FOOTPRINT_HEIGHT) zurueck, wenn keine
    Geometrie erzeugt werden konnte (kein footprintScale)."""
    if not _load_footprint_polylines(width_mm, height_mm):
        return 0.0, 0.0, FOOTPRINT_WIDTH, FOOTPRINT_HEIGHT
    return 0.0, 0.0, width_mm, height_mm


def _footprint_anchor(leds: list, width_mm: float, height_mm: float) -> tuple:
    """Translationsvektor (mm, im rohen Koordinatensystem der LEDs -- also
    VOR der minx/miny-Normalisierung aus variant_bbox), um die (width_mm x
    height_mm grosse) Footprint-Kontur so zu verschieben, dass sie
    HORIZONTAL zentriert ueber ALLEN LEDs der Vorlage liegt (inkl.
    LED_WIDTH_MM/2 Rand je Seite), VERTIKAL footprintScale.LED_OFFSET_TOP_MM
    oberhalb der Anker-LED (der mit dem kleinsten x_mm/y_mm).

    Delegiert an footprintScale.led_footprint_offset_mm -- DIESELBE Formel,
    die auch windowMarker/dxfExport.py's export_dxf fuer den tatsaechlichen
    Export verwendet, damit Editor-Vorschau und Export NIEMALS auseinander-
    laufen, egal welche echten Fenster eine Platzierung gerade beleuchtet
    (siehe dortige Docstrings -- der Footprint haengt STARR an den LEDs,
    nicht an den Fenstern)."""
    fp_left, fp_top, fp_right, _fp_bottom = _footprint_geometry_bbox(width_mm, height_mm)
    if not leds:
        return -fp_left, -fp_top
    if footprintScale is None:
        return -fp_left, -fp_top
    dx, dy, _mirror_w = footprintScale.led_footprint_offset_mm(leds, width_mm, height_mm, LED_WIDTH_MM)
    anchor_x = min(l['x_mm'] for l in leds)
    anchor_y = min(l['y_mm'] for l in leds)
    return (anchor_x + dx) - fp_left, (anchor_y + dy) - fp_top


def _footprint_geometry_mm(polylines: list, ox: float, oy: float) -> list:
    """Verschiebt rohe Footprint-Geometrie um den Anker (ox, oy) --
    gemeinsame Transform fuer footprint_points_mm."""
    return [([(ox + fx, oy + fy) for fx, fy in pts], closed) for pts, closed in polylines]


def _footprint_geometry_image(polylines: list, ox: float, oy: float, minx: float, miny: float,
                              w_mm: float, x: float, y: float, px_per_mm: float,
                              flipped: bool) -> list:
    """Wie _footprint_geometry_mm, aber in Bild-px an einer Platzierung
    ausgerichtet (inkl. Bbox-Normalisierung + Spiegelung) -- gemeinsame
    Transform fuer footprint_image_points."""
    out = []
    for pts, closed in polylines:
        spts = []
        for fx, fy in pts:
            lx = (ox + fx) - minx
            if flipped:
                lx = w_mm - lx
            spts.append((x + lx * px_per_mm, y + ((oy + fy) - miny) * px_per_mm))
        out.append((spts, closed))
    return out


def footprint_points_mm(leds: list, width_mm: float, height_mm: float) -> list:
    """Footprint-Konturpunkte (eine Liste je Polylinie, mit 'closed'-Flag) im
    selben rohen mm-Koordinatensystem wie die LEDs (x_mm/y_mm) -- zentriert
    auf deren tatsaechliche Ausdehnung (siehe _footprint_anchor). Fuer die
    direkte Vorschau im Varianten-Designer (dort keine Bbox-Normalisierung/
    Spiegelung wie bei einer Platzierung -- siehe footprint_image_points)."""
    ox, oy = _footprint_anchor(leds, width_mm, height_mm)
    return _footprint_geometry_mm(_load_footprint_polylines(width_mm, height_mm), ox, oy)


def footprint_image_points(variant: dict, x: float, y: float, px_per_mm: float,
                           flipped: bool = False, placement: dict | None = None) -> list:
    """Wie led_image_positions/connector_positions, aber fuer die komplette
    Footprint-Kontur: eine Liste von (Punktliste, closed)-Paaren, eine je
    Polylinie, in Bild-px an der Platzierung ausgerichtet.

    Die LEDs sitzen IMMER an einer FESTEN Position relativ zum Footprint
    (mittig, siehe _footprint_anchor -- aus der Varianten-LED-Vorlage
    berechnet, NICHT aus real zugewiesenen Fenstern) -- nur die Platzierung
    ALS GANZES (Footprint + LEDs zusammen) bewegt sich, wenn man sie zieht.
    Footprint und LEDs haengen also STARR zusammen, unabhaengig davon,
    welche Fenster diese Platzierung gerade tatsaechlich beleuchtet (eine
    fruehere Version zentrierte den Footprint stattdessen ueber den real
    zugewiesenen Fenstern -- dadurch konnte er beim Ziehen/Loslassen von der
    LED-Position abweichen/"zurueckspringen", je nachdem, welche Fenster
    gerade als beruehrt galten).

    `placement` liefert eine PRO-PLATZIERUNG-Groesse (`width_mm`/
    `height_mm`, siehe App._draw_footprint); fehlt sie, gilt der Default
    der Variante (siehe resolve_footprint_size)."""
    width_mm, height_mm = resolve_footprint_size(variant, placement)
    polylines = _load_footprint_polylines(width_mm, height_mm)
    minx, miny, w_mm, _ = variant_bbox(variant)
    ox, oy = _footprint_anchor(variant.get('leds', []), width_mm, height_mm)
    return _footprint_geometry_image(polylines, ox, oy,
                                     minx, miny, w_mm, x, y, px_per_mm, flipped)


def draw_footprint_polylines(cv: tk.Canvas, to_screen, poly_points: list,
                             *, color: str = '#22d3ee', dash=(4, 2), width: int = 1):
    """Zeichnet eine Liste von (Punktliste, closed)-Paaren (bereits in Bild-
    px/mm, je nach `to_screen`) als Canvas-Linien -- gemeinsame Zeichenroutine
    fuer Varianten-Designer und Hauptbild-Platzierung."""
    for pts, closed in poly_points:
        spts = [to_screen(px, py) for px, py in pts]
        if len(spts) < 2:
            continue
        flat = [c for pt in spts for c in pt]
        if closed:
            flat += list(spts[0])
        cv.create_line(*flat, fill=color, width=width, dash=dash)


# ── Variant-Designer (In-Tool-Editor fuer neue PCB-Batch-Typen) ────────────────

class VariantDesigner(tk.Toplevel):
    """
    Modal-Fenster: neuen Batch-Typ anlegen (oder bestehenden bearbeiten), indem
    einzelne LEDs mit Klick auf einem mm-Raster platziert werden. Die Klick-
    Reihenfolge ist die Ketten-Reihenfolge (Index 0..N-1) der physischen PCB.
    """

    PX_PER_MM = 6.0

    def __init__(self, master, on_save, existing: dict | None = None, existing_ids: set = ()):
        super().__init__(master)
        self.title('Neue Batch-Variante' if existing is None else f'Variante bearbeiten – {existing.get("name")}')
        self.configure(bg=C['bg'])
        self.geometry('820x560')
        self.transient(master)
        self.grab_set()

        self.on_save = on_save
        self.existing = existing
        self.existing_ids = set(existing_ids)
        self.zoom = self.PX_PER_MM
        self.leds = [dict(l) for l in existing['leds']] if existing else []
        # Groesse der generierten Footprint-Kontur (siehe windowMarker/
        # footprintScale.py) -- vom Nutzer direkt eintragbar (siehe
        # _build/self.v_footprint_w/self.v_footprint_h), Default: die der
        # bestehenden Variante, sonst FOOTPRINT_WIDTH/HEIGHT.
        self.footprint_width_mm = (existing or {}).get('footprint_width_mm') or FOOTPRINT_WIDTH
        self.footprint_height_mm = (existing or {}).get('footprint_height_mm') or FOOTPRINT_HEIGHT
        # None = automatisch (default_din_mm/default_dout_mm); erst sobald
        # der Nutzer den Anschluss zieht, wird eine feste mm-Position gesetzt
        # (siehe _mv/_reset_connector).
        self.din_mm  = dict(existing['din_mm'])  if existing and existing.get('din_mm')  else None
        self.dout_mm = dict(existing['dout_mm']) if existing and existing.get('dout_mm') else None
        self.sel = -1
        self.sel_connector: str | None = None  # 'din' | 'dout' | None -- Auswahl in der Liste/auf dem Canvas
        self._drag = False
        self._drag_target: str | None = None   # 'led' | 'din' | 'dout'

        self._build()
        self._render()

    # -- Anschluss-Positionen (automatisch oder von Hand verschoben) ------------

    def _effective_din_mm(self) -> tuple:
        d = self.din_mm or default_din_mm({'leds': self.leds})
        return d['x_mm'], d['y_mm']

    def _effective_dout_mm(self) -> tuple:
        """Immer eine (x_mm, y_mm)-Position -- default_dout_mm liefert auch
        ohne platzierte LEDs einen sinnvollen Default (0,0)+CONNECTOR_W_MM,
        damit DOUT auch schon VOR der ersten LED als Listeneintrag gezeigt
        und gesetzt werden kann."""
        d = self.dout_mm or default_dout_mm({'leds': self.leds})
        return d['x_mm'], d['y_mm']

    # -- UI --------------------------------------------------------------------

    def _build(self):
        top = tk.Frame(self, bg=C['bg_dark'], height=44)
        top.pack(side='top', fill='x')
        top.pack_propagate(False)
        tk.Label(top, text='Name:', bg=C['bg_dark'], fg=C['muted']).pack(side='left', padx=(10, 4), pady=8)
        self.v_name = tk.StringVar(value=(self.existing or {}).get('name', ''))
        tk.Entry(top, textvariable=self.v_name, bg=C['bg_panel'], fg=C['text'],
                  insertbackground='white', relief='flat', width=28).pack(side='left', pady=8)

        tk.Label(top, text='Footprint B×H (mm):', bg=C['bg_dark'], fg=C['muted']).pack(side='left', padx=(14, 4), pady=8)
        self.v_footprint_w = tk.StringVar(value=f'{self.footprint_width_mm:g}')
        ent_fp_w = tk.Entry(top, textvariable=self.v_footprint_w, bg=C['bg_panel'], fg=C['text'],
                           insertbackground='white', relief='flat', width=6)
        ent_fp_w.pack(side='left', pady=8)
        ent_fp_w.bind('<Return>', self._on_footprint_size_commit)
        ent_fp_w.bind('<FocusOut>', self._on_footprint_size_commit)
        tk.Label(top, text='×', bg=C['bg_dark'], fg=C['muted']).pack(side='left')
        self.v_footprint_h = tk.StringVar(value=f'{self.footprint_height_mm:g}')
        ent_fp_h = tk.Entry(top, textvariable=self.v_footprint_h, bg=C['bg_panel'], fg=C['text'],
                           insertbackground='white', relief='flat', width=6)
        ent_fp_h.pack(side='left', pady=8)
        ent_fp_h.bind('<Return>', self._on_footprint_size_commit)
        ent_fp_h.bind('<FocusOut>', self._on_footprint_size_commit)

        ttk.Button(top, text='Speichern', command=self._save).pack(side='right', padx=(4, 10), pady=6)
        ttk.Button(top, text='Abbrechen', command=self.destroy).pack(side='right', pady=6)

        tk.Label(top, text='Klick = LED hinzufügen · Ziehen = LED/Anschluss verschieben · '
                          'Rechtsklick auf Anschluss = zurücksetzen · Entf = löschen',
                 bg=C['bg_dark'], fg=C['dim'], font=('Segoe UI', 8)).pack(side='left', padx=16)

        main = tk.Frame(self, bg=C['bg'])
        main.pack(fill='both', expand=True)

        self.cv = tk.Canvas(main, bg=C['bg_dark'], highlightthickness=0, cursor='crosshair')
        self.cv.pack(side='left', fill='both', expand=True)

        tk.Frame(main, bg=C['border'], width=1).pack(side='left', fill='y')

        right = tk.Frame(main, bg=C['bg'], width=240)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        rh = tk.Frame(right, bg=C['bg_dark'], height=30)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        tk.Label(rh, text='LEDs (Kettenreihenfolge)', bg=C['bg_dark'], fg=C['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8, pady=5)

        wrap = tk.Frame(right, bg=C['bg'])
        wrap.pack(fill='both', expand=True)
        self.list_canvas = tk.Canvas(wrap, bg=C['bg'], highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.list_canvas.yview)
        self.list_frame = tk.Frame(self.list_canvas, bg=C['bg'])
        self.list_frame.bind('<Configure>',
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox('all')))
        self.list_canvas.create_window((0, 0), window=self.list_frame, anchor='nw', tags='f')
        self.list_canvas.configure(yscrollcommand=sb.set)
        self.list_canvas.bind('<Configure>', lambda e: self.list_canvas.itemconfig('f', width=e.width))
        self.list_canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        bind_wheel_scroll(wrap, self.list_canvas)

        self.cv.bind('<ButtonPress-1>', self._dn)
        self.cv.bind('<B1-Motion>', self._mv)
        self.cv.bind('<ButtonRelease-1>', self._up)
        self.cv.bind('<Button-3>', self._reset_connector)
        self.bind('<Delete>', self._del_sel)
        self.bind('<BackSpace>', self._del_sel)
        self.cv.bind('<Configure>', lambda e: self._render())

    # -- Koordinaten -------------------------------------------------------------

    def _mm_to_screen(self, x_mm, y_mm):
        W = self.cv.winfo_width() or 700
        H = self.cv.winfo_height() or 500
        return W / 2 + x_mm * self.zoom, H / 2 + y_mm * self.zoom

    def _screen_to_mm(self, sx, sy):
        W = self.cv.winfo_width() or 700
        H = self.cv.winfo_height() or 500
        return (sx - W / 2) / self.zoom, (sy - H / 2) / self.zoom

    # -- Rendering -----------------------------------------------------------------

    def _render(self):
        self._render_canvas()
        self._render_list()

    def _render_canvas(self):
        self.cv.delete('all')
        W = self.cv.winfo_width() or 700
        H = self.cv.winfo_height() or 500

        # Raster: 10mm hell, 50mm dunkler
        step = self.zoom * 10
        if step > 3:
            ox, oy = self._mm_to_screen(0, 0)
            x = ox % step
            i = round((0 - ox) / step)
            while x < W:
                is_major = (round((x - ox) / step) + i) % 5 == 0
                self.cv.create_line(x, 0, x, H, fill=C['border'] if not is_major else '#475569')
                x += step
            y = oy % step
            while y < H:
                is_major = (round((y - oy) / step)) % 5 == 0
                self.cv.create_line(0, y, W, y, fill=C['border'] if not is_major else '#475569')
                y += step
        ox, oy = self._mm_to_screen(0, 0)
        self.cv.create_line(0, oy, W, oy, fill='#64748b')
        self.cv.create_line(ox, 0, ox, H, fill='#64748b')

        # Referenz-Footprint (generiertes Rechteck der konfigurierten
        # Groesse, siehe windowMarker/footprintScale.py) -- mittig ueber der
        # tatsaechlichen LED-Ausdehnung (siehe _footprint_anchor), rein zur
        # Orientierung beim Platzieren der LEDs; kein eigenes Klick-/Zieh-Ziel.
        draw_footprint_polylines(self.cv, self._mm_to_screen,
                                 footprint_points_mm(self.leds, self.footprint_width_mm, self.footprint_height_mm),
                                 color=C['red'])

        # Kabelverbinder der Platine -- schwarze Kaesten in echter Bauteil-
        # groesse (CONNECTOR_W_MM x CONNECTOR_H_MM, mit dem Raster mitskaliert):
        # DIN (Daten-Eingang) automatisch bei (0,0), DOUT (Daten-Ausgang)
        # automatisch kurz hinter der letzten LED IN KETTENREIHENFOLGE
        # (self.leds[-1], hoechster Index -- die tatsaechliche Richtung des
        # Datenflusses, NICHT die raeumlich am weitesten rechts liegende LED,
        # falls das Layout nicht streng von links nach rechts angeklickt
        # wurde) -- SOLANGE der Nutzer den Anschluss nicht selbst gezogen hat
        # (siehe _dn/_mv/_effective_din_mm/_effective_dout_mm); ein gezogener
        # Anschluss wird amber hervorgehoben, waehrend er gerade bewegt wird.
        conn_w = CONNECTOR_W_MM * self.zoom / 2
        conn_h = CONNECTOR_H_MM * self.zoom / 2

        din_x_mm, din_y_mm = self._effective_din_mm()
        ix, iy = self._mm_to_screen(din_x_mm, din_y_mm)
        din_sel = (self._drag_target == 'din' or self.sel_connector == 'din')
        self.cv.create_rectangle(ix - conn_w, iy - conn_h, ix + conn_w, iy + conn_h,
                                 fill='#000000',
                                 outline=C['amber'] if din_sel else '#f8fafc',
                                 width=2.5 if din_sel else 1.5)
        self.cv.create_text(ix, iy - conn_h - 10, text='DIN', fill='#94a3b8',
                            font=('Segoe UI', 8))

        dx, dy = self._mm_to_screen(*self._effective_dout_mm())
        dout_sel = (self._drag_target == 'dout' or self.sel_connector == 'dout')
        self.cv.create_rectangle(dx - conn_w, dy - conn_h, dx + conn_w, dy + conn_h,
                                 fill='#000000',
                                 outline=C['amber'] if dout_sel else '#f8fafc',
                                 width=2.5 if dout_sel else 1.5)
        self.cv.create_text(dx, dy - conn_h - 10, text='DOUT', fill='#94a3b8',
                            font=('Segoe UI', 8))

        # PCB-Strang (Linie zwischen aufeinanderfolgenden LEDs)
        if len(self.leds) > 1:
            pts = []
            for l in self.leds:
                pts.extend(self._mm_to_screen(l['x_mm'], l['y_mm']))
            self.cv.create_line(*pts, fill=C['blue_dim'], width=2, dash=(3, 2))

        for i, l in enumerate(self.leds):
            sx, sy = self._mm_to_screen(l['x_mm'], l['y_mm'])
            sel = (i == self.sel)
            r = 8 if sel else 6
            self.cv.create_oval(sx - r, sy - r, sx + r, sy + r,
                fill=C['amber'] if sel else C['green'], outline='white', width=1.5)
            self.cv.create_text(sx, sy - 14, text=str(i), fill=C['text'],
                font=('Segoe UI', 8, 'bold'))

    def _render_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        self._render_connector_card('din', 'DIN')
        self._render_connector_card('dout', 'DOUT')
        tk.Frame(self.list_frame, bg=C['border'], height=1).pack(fill='x', padx=4, pady=(4, 6))

        if not self.leds:
            tk.Label(self.list_frame, text='Auf das Raster klicken,\num LEDs hinzuzufügen',
                     bg=C['bg'], fg=C['dim'], justify='center', font=('Segoe UI', 9)).pack(pady=20)
            return
        for i, l in enumerate(self.leds):
            sel = (i == self.sel)
            BG = C['blue_sel'] if sel else C['bg_panel']
            outer = tk.Frame(self.list_frame, bg=C['blue'] if sel else C['border'], padx=1, pady=1)
            outer.pack(fill='x', padx=4, pady=2)
            inner = tk.Frame(outer, bg=BG, padx=6, pady=4)
            inner.pack(fill='x')

            head = tk.Frame(inner, bg=BG)
            head.pack(fill='x')
            tk.Label(head, text=f'#{i}', bg=BG, fg='#60a5fa',
                     font=('Segoe UI', 9, 'bold')).pack(side='left')
            tk.Button(head, text='✕', bg=BG, fg=C['dim'], relief='flat', bd=0,
                      activebackground='#450a0a', activeforeground=C['red'],
                      command=lambda i=i: self._del_idx(i)).pack(side='right')

            grid = tk.Frame(inner, bg=BG)
            grid.pack(fill='x', pady=(3, 0))
            grid.columnconfigure(1, weight=1)
            grid.columnconfigure(3, weight=1)
            for col, (field, lbl) in enumerate([('x_mm', 'X'), ('y_mm', 'Y')]):
                tk.Label(grid, text=lbl, bg=BG, fg=C['muted'],
                         font=('Courier New', 8)).grid(row=0, column=col * 2, sticky='w')
                var = tk.StringVar(value=f'{l[field]:.2f}')
                ent = tk.Entry(grid, textvariable=var, bg=C['bg_dark'], fg=C['text'],
                               insertbackground='white', relief='flat', bd=1, width=7,
                               font=('Courier New', 9), highlightthickness=1,
                               highlightbackground=C['border'], highlightcolor=C['blue'])
                ent.grid(row=0, column=col * 2 + 1, sticky='ew', padx=(2, 8 if col == 0 else 0))

                def commit(e=None, i=i, f=field, v=var):
                    try:
                        val = round(float(v.get().replace(',', '.')), 2)
                        self.leds[i][f] = val
                        v.set(f'{val:.2f}')
                        self.sel = i
                        self.sel_connector = None
                        self._render_canvas()
                    except ValueError:
                        v.set(f'{self.leds[i][f]:.2f}')
                ent.bind('<Return>', commit)
                ent.bind('<FocusOut>', commit)

            def on_click(e, i=i):
                self.sel = i
                self.sel_connector = None
                self._render()
            for wgt in (outer, inner, head):
                wgt.bind('<Button-1>', on_click)

    def _render_connector_card(self, which: str, label: str):
        """Listeneintrag fuer DIN/DOUT -- editierbare X/Y-Felder wie bei einer
        LED, aber mit eigenem (amberfarbenem) Hintergrund statt dem
        blaugrauen LED-Kartenstil, damit die beiden Anschluesse auf den
        ersten Blick von der eigentlichen LED-Kette zu unterscheiden sind.
        ↺-Button (nur sichtbar, wenn von Hand verschoben) setzt zurueck auf
        automatisch; sonst zeigt ein '(auto)'-Hinweis den aktuellen Status."""
        getter = self._effective_din_mm if which == 'din' else self._effective_dout_mm
        x_mm, y_mm = getter()
        is_custom = (self.din_mm if which == 'din' else self.dout_mm) is not None
        sel = (self.sel_connector == which)

        BORDER = C['amber'] if sel else '#7c5a12'
        BG = '#4a3413' if sel else '#2d2410'
        outer = tk.Frame(self.list_frame, bg=BORDER, padx=1, pady=1)
        outer.pack(fill='x', padx=4, pady=2)
        inner = tk.Frame(outer, bg=BG, padx=6, pady=4)
        inner.pack(fill='x')

        head = tk.Frame(inner, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text=label, bg=BG, fg=C['amber'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        if is_custom:
            tk.Button(head, text='↺', bg=BG, fg=C['dim'], relief='flat', bd=0,
                      activebackground=BG, activeforeground=C['amber'],
                      command=lambda w=which: self._reset_connector_by_name(w)).pack(side='right')
        else:
            tk.Label(head, text='(auto)', bg=BG, fg=C['dim'], font=('Segoe UI', 8)).pack(side='right')

        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill='x', pady=(3, 0))
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        values = {'x_mm': x_mm, 'y_mm': y_mm}
        for col, (field, lbl) in enumerate([('x_mm', 'X'), ('y_mm', 'Y')]):
            tk.Label(grid, text=lbl, bg=BG, fg=C['muted'],
                     font=('Courier New', 8)).grid(row=0, column=col * 2, sticky='w')
            var = tk.StringVar(value=f'{values[field]:.2f}')
            ent = tk.Entry(grid, textvariable=var, bg=C['bg_dark'], fg=C['text'],
                           insertbackground='white', relief='flat', bd=1, width=7,
                           font=('Courier New', 9), highlightthickness=1,
                           highlightbackground=C['border'], highlightcolor=C['amber'])
            ent.grid(row=0, column=col * 2 + 1, sticky='ew', padx=(2, 8 if col == 0 else 0))

            def commit(e=None, w=which, f=field, v=var, cur_x=x_mm, cur_y=y_mm):
                try:
                    val = round(float(v.get().replace(',', '.')), 2)
                    pt = {'x_mm': cur_x, 'y_mm': cur_y}
                    pt[f] = val
                    if w == 'din':
                        self.din_mm = pt
                    else:
                        self.dout_mm = pt
                    self.sel = -1
                    self.sel_connector = w
                    self._render()
                except ValueError:
                    v.set(f'{(cur_x if f == "x_mm" else cur_y):.2f}')
            ent.bind('<Return>', commit)
            ent.bind('<FocusOut>', commit)

        def on_click(e, w=which):
            self.sel = -1
            self.sel_connector = w
            self._render()
        for wgt in (outer, inner, head):
            wgt.bind('<Button-1>', on_click)

    # -- Interaktion ---------------------------------------------------------------

    def _hit(self, sx, sy):
        for i in range(len(self.leds) - 1, -1, -1):
            lx, ly = self._mm_to_screen(self.leds[i]['x_mm'], self.leds[i]['y_mm'])
            if (lx - sx) ** 2 + (ly - sy) ** 2 <= LED_HIT_R ** 2:
                return i
        return -1

    def _hit_connector(self, sx, sy) -> str | None:
        """'din'/'dout', falls (sx, sy) auf dem jeweiligen Anschluss-Kasten
        liegt (rechteckiger Hit-Test in echter Bauteilgroesse), sonst None."""
        conn_w = CONNECTOR_W_MM * self.zoom / 2
        conn_h = CONNECTOR_H_MM * self.zoom / 2
        dx, dy = self._mm_to_screen(*self._effective_dout_mm())
        if abs(sx - dx) <= conn_w and abs(sy - dy) <= conn_h:
            return 'dout'
        ix, iy = self._mm_to_screen(*self._effective_din_mm())
        if abs(sx - ix) <= conn_w and abs(sy - iy) <= conn_h:
            return 'din'
        return None

    def _dn(self, e):
        conn = self._hit_connector(e.x, e.y)
        if conn:
            self.sel = -1
            self.sel_connector = conn
            self._drag_target = conn
            self._drag = True
            self._render()
            return
        self.sel_connector = None
        i = self._hit(e.x, e.y)
        if i >= 0:
            self.sel = i
            self._drag_target = 'led'
            self._drag = True
            self._render()
        else:
            mx, my = self._screen_to_mm(e.x, e.y)
            self.leds.append({'x_mm': round(mx, 1), 'y_mm': round(my, 1)})
            self.sel = len(self.leds) - 1
            self._drag_target = 'led'
            self._drag = True
            self._render()

    def _mv(self, e):
        if not self._drag:
            return
        if self._drag_target == 'led':
            if 0 <= self.sel < len(self.leds):
                mx, my = self._screen_to_mm(e.x, e.y)
                self.leds[self.sel]['x_mm'] = round(mx, 1)
                self.leds[self.sel]['y_mm'] = round(my, 1)
                self._render()
        elif self._drag_target in ('din', 'dout'):
            mx, my = self._screen_to_mm(e.x, e.y)
            pt = {'x_mm': round(mx, 1), 'y_mm': round(my, 1)}
            if self._drag_target == 'din':
                self.din_mm = pt
            else:
                self.dout_mm = pt
            self._render()

    def _up(self, _e):
        self._drag = False
        self._drag_target = None

    def _reset_connector(self, e):
        """Rechtsklick auf einen von Hand verschobenen Anschluss (auf dem
        Canvas) setzt ihn wieder auf die automatische Position zurueck."""
        conn = self._hit_connector(e.x, e.y)
        if conn:
            self._reset_connector_by_name(conn)

    def _reset_connector_by_name(self, which: str):
        """Wie _reset_connector, aber direkt per Name aufrufbar -- fuer den
        ↺-Button im Listeneintrag (siehe _render_connector_card)."""
        if which == 'din':
            self.din_mm = None
        else:
            self.dout_mm = None
        self._render()

    def _del_sel(self, _e=None):
        self._del_idx(self.sel)

    def _del_idx(self, i):
        if 0 <= i < len(self.leds):
            self.leds.pop(i)
            self.sel = min(self.sel, len(self.leds) - 1)
            self._render()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showwarning('Fehlt', 'Bitte einen Namen für die Variante angeben.')
            return
        if not self.leds:
            messagebox.showwarning('Fehlt', 'Bitte mindestens eine LED platzieren.')
            return
        if self.existing:
            vid = self.existing['id']
        else:
            vid = unique_id(slugify(name), self.existing_ids)
        variant = {'id': vid, 'name': name, 'leds': [dict(l) for l in self.leds]}
        # din_mm/dout_mm nur speichern, wenn von Hand verschoben -- sonst
        # bleibt die Variante bei der automatischen Position (siehe
        # connector_positions/default_din_mm/default_dout_mm), unveraendert
        # gegenueber Varianten von vor diesem Feature.
        if self.din_mm is not None:
            variant['din_mm'] = dict(self.din_mm)
        if self.dout_mm is not None:
            variant['dout_mm'] = dict(self.dout_mm)
        variant['footprint_width_mm'] = self.footprint_width_mm
        variant['footprint_height_mm'] = self.footprint_height_mm
        self.on_save(variant, is_new=(self.existing is None))
        self.destroy()

    def _on_footprint_size_commit(self, _e=None):
        try:
            w = float(self.v_footprint_w.get().replace(',', '.'))
            h = float(self.v_footprint_h.get().replace(',', '.'))
            if w <= 0 or h <= 0:
                raise ValueError
        except ValueError:
            self.v_footprint_w.set(f'{self.footprint_width_mm:g}')
            self.v_footprint_h.set(f'{self.footprint_height_mm:g}')
            return
        self.footprint_width_mm, self.footprint_height_mm = w, h
        self._render_canvas()


# ── Hauptanwendung ─────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Misc | None = None, parent: tk.Misc | None = None,
                 is_active=None):
        """
        root/parent: Ohne Argumente laeuft der Editor als eigenes Fenster.
        Eingebettet (Tab-Ansicht in windowTool._launch_combined) wird ein
        gemeinsames `root` und ein Tab-Frame als `parent` uebergeben;
        `is_active` meldet, ob dieser Tab gerade sichtbar ist (damit
        Tastatur-Kuerzel nicht im inaktiven Tab ausgefuehrt werden).
        """
        if root is None:
            root = tk.Tk()
            root.title('LED Batch Editor')
            root.geometry('1400x800')
            root.minsize(900, 560)
            root.configure(bg=C['bg'])
        self.root = root
        self.container = parent if parent is not None else root
        self._is_active = is_active if is_active is not None else (lambda: True)

        self.variant: dict | None = load_variant()  # es gibt nur DIESE eine LED-Variante

        self.img_orig: Image.Image | None = None
        self.img_path: Path | None = None
        self.json_path: Path | None = None
        self.windows: list = []       # Fensterrahmen aus dem JSON (nur lesen, gelb anzeigen)
        self.placements: list = []    # [{'id','variantId','x','y','leds':[...]}, ...]
        self.sel_idx = -1
        self.sel_idxs: set = set()    # Mehrfachauswahl (Strg+Klick, siehe _cv_dn) -- self.sel_idx
                                       # bleibt die "primaere"/zuletzt angeklickte davon, fuer alle
                                       # Aktionen, die weiterhin nur EIN Ziel kennen (Loeschen,
                                       # Verschieben in der Liste, Anschluss-Editor).
        self.dpi = DEFAULT_DPI        # mm -> Bild-px Umrechnung (aus JSON/Bilddatei/Eingabe)

        # Anzeige-Einstellungen
        self.show_color = tk.BooleanVar(master=self.root, value=False)  # Foto farbig statt grau
        self.show_wins  = tk.BooleanVar(master=self.root, value=True)   # gelbe Fensterrahmen
        self.place_flipped = tk.BooleanVar(master=self.root, value=False)  # naechste Platzierung gespiegelt?
        # Werkzeuge (gegenseitig exklusiv, siehe _pick_tool/_cv_dn):
        # - tool_led_toggle: Klick auf eine LED schaltet ihren aktuellen Zustand
        #   manuell fest um (an<->aus), statt eine Platzierung auszuwaehlen/zu
        #   verschieben.
        # - tool_place: Klick setzt IMMER eine neue Platzierung der gewaehlten
        #   Variante -- ohne aktives Werkzeug waehlt/verschiebt ein Klick nur
        #   bestehende Platzierungen (kein versehentliches Neu-Platzieren mehr).
        # - tool_measure: Klicken+Ziehen zieht ein Massband (Bild-px -> mm ueber
        #   px_per_mm) zwischen zwei Punkten -- zum Nachmessen echter Abstaende
        #   auf dem Foto (z.B. Fensterbreiten, LED-Abstaende), ohne eine
        #   Platzierung anzulegen. Siehe _cv_dn/_cv_mv/_cv_up.
        # - tool_scale: Klicken+Ziehen zwischen zwei Punkten, danach Dialog
        #   ("wie viele mm soll das sein?") -- berechnet daraus die DPI neu
        #   (dpi = gemessene_px / eingegebene_mm * 25.4) und setzt sie sofort.
        #   Zum Kalibrieren, wenn die tatsaechliche Aufloesung/der Massstab
        #   des Fotos unbekannt ist, aber eine bekannte Referenzstrecke
        #   (z.B. eine echte Fensterbreite von 10cm) im Bild sichtbar ist.
        self.tool_led_toggle = tk.BooleanVar(master=self.root, value=False)
        self.tool_place = tk.BooleanVar(master=self.root, value=False)
        self.tool_measure = tk.BooleanVar(master=self.root, value=False)
        self.tool_scale = tk.BooleanVar(master=self.root, value=False)
        self._measuring = False
        self._measure_pts: list = []   # [] | [(ix,iy)] | [(ix,iy),(ix,iy)], Bild-px
        self._scaling = False
        self._scale_pts: list = []     # [] | [(ix,iy)] | [(ix,iy),(ix,iy)], Bild-px

        # LED-Kette (3. Tab): Reihenfolge + berechnete Nummerierung
        self.chain_order: list = []      # [placementId, ...] explizite Verbindungsreihenfolge
        self.disabled_leds: list = []    # globale Kettenindizes ohne Fensterzuordnung
        self.total_led_count = 0
        self.total_pixel_count = 0       # Anzahl DISTINKTER logischer Pixel (siehe pixelIndex)
        self.data_chain: list = []       # ["<from>-<to>", ...] je logischem Pixel, ab Daten-Eingang
        self.chain_sel_idx = -1
        self.chain_zoom = 1.0
        self.chain_off_x = 0.0
        self.chain_off_y = 0.0
        self._chain_cache_zoom = None
        self._chain_cache_tk = None
        self._chain_pan_ref = None
        # Werkzeug "LEDs gruppieren": Klick auf eine LED merkt sie als Anker
        # vor (self._group_anchor), Klick auf eine zweite LED uebernimmt deren
        # Fensterzuordnung -- beide teilen sich danach denselben pixelIndex.
        # Rechtsklick auf eine LED loest sie wieder aus jeder manuellen
        # Gruppierung (zurueck auf automatisch).
        self.chain_tool_group = tk.BooleanVar(master=self.root, value=False)
        self._group_anchor: tuple | None = None   # (placementId, lokaler LED-Index) oder None
        self._lamp_icon_cache: dict = {}   # {(radius, enabled, selected): PhotoImage}

        self.zoom = 1.0
        self.off_x = 0.0
        self.off_y = 0.0
        self._display_img = None      # grau/farbig aufbereitetes Anzeigebild
        self._cache_zoom = None
        self._cache_tk = None

        self._space = False
        self._space_used_for_pan = False  # unterscheidet kurzes Antippen (Spiegeln) von Halten+Ziehen (Pan)
        self._pan_ref = None
        self._move_ref = None
        self._resize_ref = None       # (edge, start_x, start_y, w0_mm, h0_mm) siehe _hit_footprint_edge
        self._hover = None            # (ix, iy) Anker der Platzierungs-Vorschau (Schatten)

        # Rahmen-Rechteck der 4 Rahmenleisten (siehe windowMarker.footprintScale.
        # get_frame_side_points/get_frame_top_points, dxfExport.
        # clip_outline_to_frame) -- (left, top, right, bottom) in Bild-px, siehe
        # _default_frame_rect_px/_hit_frame_edge. None, solange kein Bild geladen ist.
        self.frame_rect_px: tuple | None = None
        self._frame_resize_ref = None  # (edge, start_x, start_y, rect0) siehe _hit_frame_edge

        # Bewegliches Hoehen-Overlay (siehe _build/_render_height_panel):
        # klickbare Liste aller im Bild vorkommenden Footprint-Hoehen (siehe
        # resolve_footprint_size) -- Klick markiert ALLE Platzierungen mit
        # genau dieser Hoehe im Canvas (siehe _draw_footprint). None = keine
        # Hoehe markiert. Ziehen an der Titelzeile verschiebt das Panel frei
        # ueber dem Canvas (_height_panel_ref), unabhaengig vom fest
        # verankerten tools_panel oben rechts.
        self.height_highlight_mm: float | None = None
        self._height_panel_ref = None

        self._save_after = None

        self._style()
        self._build()
        self._bind()
        self._scan_images()

    # ── Style ──────────────────────────────────────────────────────────────

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.', background=C['bg'], foreground=C['text'], font=('Segoe UI', 9))
        s.configure('TFrame', background=C['bg'])
        s.configure('TLabel', background=C['bg'], foreground=C['text'])
        s.configure('TButton', background=C['border'], foreground=C['text'],
                    relief='flat', borderwidth=0, padding=(7, 3), focuscolor='none')
        s.map('TButton', background=[('active', '#475569'), ('pressed', '#64748b')])
        s.configure('TScrollbar', background=C['border'], troughcolor=C['bg_dark'],
                    arrowcolor=C['muted'], borderwidth=0, relief='flat')
        s.configure('TCombobox', fieldbackground=C['bg_panel'], background=C['bg_panel'],
                    foreground=C['text'], arrowcolor=C['muted'])

    # ── UI Aufbau ─────────────────────────────────────────────────────────

    def _build(self):
        tb = tk.Frame(self.container, bg=C['bg_dark'], height=44)
        tb.pack(side='top', fill='x')
        tb.pack_propagate(False)

        # Es gibt nur EINE LED-Variante (kein Auswahl-Dropdown mehr fuer eine
        # Bibliothek mehrerer PCB-Typen) -- Name-Anzeige + direkter Zugang
        # zum Varianten-Designer.
        tk.Label(tb, text='LED-Variante:', bg=C['bg_dark'], fg=C['muted']).pack(side='left', padx=(10, 4))
        self.v_variant = tk.StringVar()
        self._update_variant_label()
        tk.Label(tb, textvariable=self.v_variant, bg=C['bg_dark'], fg=C['text'],
                font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 6))
        ttk.Button(tb, text='Bearbeiten...', command=self._edit_variant, takefocus=0).pack(side='left', padx=2)

        # Footprint-Groesse fuer die NAECHSTE Platzierung (Werkzeug "Variante
        # platzieren") -- unabhaengig vom Default der Variante eintragbar, so
        # lassen sich mit derselben LED-Variante Platzierungen mit
        # UNTERSCHIEDLICHEN Platinen-Groessen anlegen, ohne jede einzelne
        # danach ueber ihre Karte umstellen zu muessen (siehe _add_card fuer
        # das nachtraegliche Aendern EINER bestehenden Platzierung). Leer =
        # folgt dem Default der Variante (siehe resolve_footprint_size).
        tk.Label(tb, text='Footprint B×H (mm):', bg=C['bg_dark'], fg=C['muted']).pack(side='left', padx=(10, 4))
        self.v_next_footprint_w = tk.StringVar(value='')
        ent_next_fp_w = tk.Entry(tb, textvariable=self.v_next_footprint_w, bg=C['bg_panel'], fg=C['text'],
                                 insertbackground='white', relief='flat', width=5)
        ent_next_fp_w.pack(side='left', pady=8)
        ent_next_fp_w.bind('<Return>', lambda e: self._render_cv())
        ent_next_fp_w.bind('<FocusOut>', lambda e: self._render_cv())
        tk.Label(tb, text='×', bg=C['bg_dark'], fg=C['muted']).pack(side='left')
        self.v_next_footprint_h = tk.StringVar(value='')
        ent_next_fp_h = tk.Entry(tb, textvariable=self.v_next_footprint_h, bg=C['bg_panel'], fg=C['text'],
                                 insertbackground='white', relief='flat', width=5)
        ent_next_fp_h.pack(side='left', pady=8)
        ent_next_fp_h.bind('<Return>', lambda e: self._render_cv())
        ent_next_fp_h.bind('<FocusOut>', lambda e: self._render_cv())

        tk.Frame(tb, bg=C['border'], width=1).pack(side='left', fill='y', padx=10, pady=8)

        tk.Label(tb, text='DPI:', bg=C['bg_dark'], fg=C['muted']).pack(side='left', padx=(0, 4))
        self.v_dpi = tk.StringVar(value=f'{self.dpi:g}')
        ent_dpi = tk.Entry(tb, textvariable=self.v_dpi, bg=C['bg_panel'], fg=C['text'],
                           insertbackground='white', relief='flat', width=7,
                           font=('Courier New', 9))
        ent_dpi.pack(side='left', pady=8)
        ent_dpi.bind('<Return>', self._commit_dpi)
        ent_dpi.bind('<FocusOut>', self._commit_dpi)

        tk.Frame(tb, bg=C['border'], width=1).pack(side='left', fill='y', padx=10, pady=8)
        tk.Checkbutton(tb, text='Neue Platzierung spiegeln', variable=self.place_flipped,
                      bg=C['bg_dark'], fg=C['text'], selectcolor=C['bg_panel'],
                      activebackground=C['bg_dark'], activeforeground=C['text'],
                      font=('Segoe UI', 9), highlightthickness=0, bd=0,
                      takefocus=0).pack(side='left', padx=4)

        tk.Frame(tb, bg=C['border'], width=1).pack(side='left', fill='y', padx=10, pady=8)
        self._v_name = tk.StringVar(value='Kein Bild geöffnet')
        tk.Label(tb, textvariable=self._v_name, bg=C['bg_dark'], fg=C['muted']).pack(side='left')
        self._v_status = tk.StringVar()
        self._lbl_status = tk.Label(tb, textvariable=self._v_status, bg=C['bg_dark'])
        self._lbl_status.pack(side='left', padx=8)

        # Zuerst (= am weitesten rechts, garantiert sichtbar auch bei
        # schmalem Fenster) die Export-Buttons + "Auto platzieren" packen --
        # side='right'-Elemente stapeln sich in Packreihenfolge von rechts
        # nach links, das zuerst gepackte landet also ganz aussen/sichtbar.
        # Der Projekt-Export gehoert hierher (nicht in Tab 1 "Fenster
        # markieren") -- er exportiert ALLE Haeuser (dxfExport.py/
        # csvExport.py), das passt inhaltlich zum LED-/Platinen-Tab. EIN
        # Button statt getrennter DXF-/CSV-Buttons (siehe _export_project),
        # damit DXF und CSV nie aus unterschiedlichen Projektstaenden stammen.
        ttk.Button(tb, text='Projekt exportieren',
                  command=self._export_project, takefocus=0).pack(side='right', padx=2, pady=6)
        tk.Frame(tb, bg=C['border'], width=1).pack(side='right', fill='y', padx=8, pady=8)
        ttk.Button(tb, text='🪄 Auto platzieren', command=self._auto_place, takefocus=0).pack(side='right', padx=2, pady=6)
        tk.Frame(tb, bg=C['border'], width=1).pack(side='right', fill='y', padx=8, pady=8)
        ttk.Button(tb, text='Anpassen', command=self._fit, takefocus=0).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' + ', command=lambda: self._zoom_center(1.25), takefocus=0).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' − ', command=lambda: self._zoom_center(1 / 1.25), takefocus=0).pack(side='right', padx=2, pady=6)
        tk.Frame(tb, bg=C['border'], width=1).pack(side='right', fill='y', padx=8, pady=8)

        # Werkzeug-Hilfetext -- eigene, unten zentrierte Leiste statt Teil der
        # (bereits vollen) oberen Toolbar: dort wurde er bei schmalerem Fenster
        # zusammen mit dem "Auto platzieren"-Button aus der sichtbaren Breite
        # herausgedraengt. Hier unten (side='bottom', VOR main gepackt, damit
        # er sein Platz garantiert von der Cavity abbekommt) ist immer Platz.
        help_bar = tk.Frame(self.container, bg=C['bg_dark'], height=22)
        help_bar.pack(side='bottom', fill='x')
        help_bar.pack_propagate(False)
        tk.Label(help_bar, text='Shift+Rechtsklick auf LED = zurueck auf automatisch · '
                                'Messen: Ziehen = Abstand in mm · '
                                'Skalieren: Ziehen = DPI aus bekannter Strecke berechnen',
                bg=C['bg_dark'], fg=C['dim'], font=('Segoe UI', 8)).pack(pady=3)

        main = tk.Frame(self.container, bg=C['bg'])
        main.pack(fill='both', expand=True)

        # Linkes Panel: Bilder aus public/houses
        left = tk.Frame(main, bg=C['bg'], width=220)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        lh = tk.Frame(left, bg=C['bg_dark'], height=32)
        lh.pack(fill='x')
        lh.pack_propagate(False)
        tk.Label(lh, text='public/houses', bg=C['bg_dark'], fg=C['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8, pady=6)
        ttk.Button(lh, text='⟳', width=2, command=self._scan_images).pack(side='right', padx=4, pady=4)
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
                           highlightthickness=0, bd=0, takefocus=0).pack(fill='x', padx=2)

        _chk('Farbe anzeigen',   self.show_color, self._update_display_img)
        _chk('Fenster anzeigen', self.show_wins,  self._render_cv)
        tk.Frame(left, bg=C['border'], height=1).pack(fill='x')

        wrap = tk.Frame(left, bg=C['bg'])
        wrap.pack(fill='both', expand=True)
        self._img_canvas = tk.Canvas(wrap, bg=C['bg'], highlightthickness=0)
        isb = ttk.Scrollbar(wrap, orient='vertical', command=self._img_canvas.yview)
        self._img_list_frame = tk.Frame(self._img_canvas, bg=C['bg'])
        self._img_list_frame.bind('<Configure>',
            lambda e: self._img_canvas.configure(scrollregion=self._img_canvas.bbox('all')))
        self._img_canvas.create_window((0, 0), window=self._img_list_frame, anchor='nw', tags='f')
        self._img_canvas.configure(yscrollcommand=isb.set)
        self._img_canvas.bind('<Configure>', lambda e: self._img_canvas.itemconfig('f', width=e.width))
        self._img_canvas.pack(side='left', fill='both', expand=True)
        isb.pack(side='right', fill='y')
        bind_wheel_scroll(wrap, self._img_canvas)

        tk.Frame(main, bg=C['border'], width=1).pack(side='left', fill='y')

        # Canvas
        self.cv = tk.Canvas(main, bg=C['bg_dark'], highlightthickness=0, cursor='crosshair')
        self.cv.pack(side='left', fill='both', expand=True)

        # Schwebendes Werkzeug-Panel oben rechts UEBER dem Canvas (statt in
        # der oberen Toolbar) -- die Toolbar wurde mit Variante/Footprint/
        # DPI/Export-Buttons zu voll, wodurch Werkzeug-Buttons je nach
        # Fensterbreite abgeschnitten wurden. place() mit relx/rely haelt
        # das Panel automatisch in der Ecke, auch wenn sich der Canvas mit
        # dem Fenster mitverkleinert/vergroessert (kein <Configure>-Binding
        # noetig -- place() rechnet bei relx/rely selbst bei jeder
        # Groessenaenderung des Eltern-Widgets neu). Als Kind DES Canvas
        # (nicht eines Geschwister-Frames) liegt es automatisch UEBER allem,
        # was der Canvas zeichnet, bleibt aber normal klickbar.
        tools_panel = tk.Frame(self.cv, bg=C['bg_panel'], bd=1, relief='solid')
        tools_panel.place(relx=1.0, rely=0.0, x=-10, y=10, anchor='ne')

        def _tool_btn(text, variable, which, selectcolor):
            btn = tk.Checkbutton(
                tools_panel, text=text, variable=variable, indicatoron=False,
                command=lambda: self._pick_tool(which),
                bg=C['bg_panel'], fg=C['text'], selectcolor=selectcolor,
                activebackground=C['border'], activeforeground=C['text'],
                font=('Segoe UI', 9), relief='flat', bd=0, padx=8, pady=4,
                highlightthickness=0, anchor='w', takefocus=0)
            btn.pack(fill='x', padx=2, pady=1)
            return btn

        self.btn_led_toggle = _tool_btn('💡 LED umschalten', self.tool_led_toggle, 'led_toggle', C['amber'])
        self.btn_place = _tool_btn('✛ Variante platzieren', self.tool_place, 'place', C['blue'])
        self.btn_measure = _tool_btn('📏 Messen', self.tool_measure, 'measure', C['green'])
        self.btn_scale = _tool_btn('📐 Skalieren', self.tool_scale, 'scale', C['blue'])

        # Groesse fuer die AKTUELLE Auswahl (Strg+Klick auf dem Canvas fuer
        # Mehrfachauswahl, siehe sel_idxs/_cv_dn) setzen -- Gegenstueck zum
        # Ziehen an einer Footprint-Kante (siehe _cv_mv), das dieselbe
        # Groesse ebenfalls auf die ganze Auswahl spiegelt. Wirkt auf ALLE
        # aktuell ausgewaehlten Platzierungen (ohne Auswahl: nur die primaere).
        tk.Frame(tools_panel, bg=C['border'], height=1).pack(fill='x', padx=2, pady=(4, 4))
        tk.Label(tools_panel, text='Größe für Auswahl:', bg=C['bg_panel'], fg=C['muted'],
                font=('Segoe UI', 8)).pack(anchor='w', padx=8)
        size_row = tk.Frame(tools_panel, bg=C['bg_panel'])
        size_row.pack(fill='x', padx=8, pady=(2, 6))
        self.v_sel_footprint_w = tk.StringVar(value='')
        ent_sel_w = tk.Entry(size_row, textvariable=self.v_sel_footprint_w, bg=C['bg_dark'], fg=C['text'],
                             insertbackground='white', relief='flat', width=5, font=('Courier New', 8))
        ent_sel_w.pack(side='left')
        tk.Label(size_row, text='×', bg=C['bg_panel'], fg=C['muted'], font=('Courier New', 8)).pack(side='left', padx=2)
        self.v_sel_footprint_h = tk.StringVar(value='')
        ent_sel_h = tk.Entry(size_row, textvariable=self.v_sel_footprint_h, bg=C['bg_dark'], fg=C['text'],
                             insertbackground='white', relief='flat', width=5, font=('Courier New', 8))
        ent_sel_h.pack(side='left', padx=(0, 4))
        ttk.Button(size_row, text='✓', width=2, command=self._apply_size_to_selection,
                  takefocus=0).pack(side='left')
        ent_sel_w.bind('<Return>', lambda e: self._apply_size_to_selection())
        ent_sel_h.bind('<Return>', lambda e: self._apply_size_to_selection())

        # Bewegliches Hoehen-Overlay (siehe self.height_highlight_mm/
        # _render_height_panel/_draw_footprint) -- anders als tools_panel oben
        # NICHT per relx/rely fest verankert, sondern per Ziehen an der
        # Titelzeile FREI ueber dem Canvas verschiebbar (place() mit reinen
        # x/y-Pixelkoordinaten, die _height_panel_mv beim Ziehen aktualisiert).
        # Default-Position oben links, damit es dem tools_panel (oben rechts)
        # nicht sofort im Weg steht.
        self.height_panel = tk.Frame(self.cv, bg=C['bg_panel'], bd=1, relief='solid')
        self.height_panel.place(x=10, y=10)
        height_head = tk.Frame(self.height_panel, bg=C['bg_dark'], cursor='fleur')
        height_head.pack(fill='x')
        tk.Label(height_head, text='⠿ Höhen', bg=C['bg_dark'], fg=C['muted'],
                font=('Segoe UI', 8, 'bold')).pack(side='left', padx=6, pady=3)
        height_head.bind('<ButtonPress-1>', self._height_panel_dn)
        height_head.bind('<B1-Motion>', self._height_panel_mv)
        self.height_list_frame = tk.Frame(self.height_panel, bg=C['bg_panel'])
        self.height_list_frame.pack(fill='both', padx=3, pady=(2, 4))

        tk.Frame(main, bg=C['border'], width=1).pack(side='left', fill='y')

        # Rechtes Panel: platzierte Batches
        right = tk.Frame(main, bg=C['bg'], width=270)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        rh = tk.Frame(right, bg=C['bg_dark'], height=32)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        tk.Label(rh, text='Platzierte Batches', bg=C['bg_dark'], fg=C['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8, pady=6)
        self._v_count = tk.StringVar(value='0')
        tk.Label(rh, textvariable=self._v_count, bg=C['border'], fg=C['muted'],
                 font=('Segoe UI', 8), padx=4).pack(side='right', padx=6, pady=8)
        tk.Frame(right, bg=C['border'], height=1).pack(fill='x')

        pwrap = tk.Frame(right, bg=C['bg'])
        pwrap.pack(fill='both', expand=True)
        self._p_canvas = tk.Canvas(pwrap, bg=C['bg'], highlightthickness=0)
        psb = ttk.Scrollbar(pwrap, orient='vertical', command=self._p_canvas.yview)
        self._p_list_frame = tk.Frame(self._p_canvas, bg=C['bg'])
        self._p_list_frame.bind('<Configure>',
            lambda e: self._p_canvas.configure(scrollregion=self._p_canvas.bbox('all')))
        self._p_canvas.create_window((0, 0), window=self._p_list_frame, anchor='nw', tags='f')
        self._p_canvas.configure(yscrollcommand=psb.set)
        self._p_canvas.bind('<Configure>', lambda e: self._p_canvas.itemconfig('f', width=e.width))
        self._p_canvas.pack(side='left', fill='both', expand=True)
        psb.pack(side='right', fill='y')
        bind_wheel_scroll(pwrap, self._p_canvas)

        self._update_variant_label()
        self._render_cv()
        self._render_placements()

    def _bind(self):
        # add='+': im Tab-Verbund teilen sich mehrere Apps dasselbe root --
        # ohne '+' wuerde diese App die Tastatur-Bindings der anderen ersetzen.
        self.root.bind('<KeyPress-space>', lambda e: self._set_space(True, e), add='+')
        self.root.bind('<KeyRelease-space>', lambda e: self._set_space(False, e), add='+')
        self.root.bind('<Delete>', self._kb_del, add='+')
        self.root.bind('<BackSpace>', self._kb_del, add='+')
        self.root.bind('<Escape>', self._kb_esc, add='+')

        self.cv.bind('<ButtonPress-1>', self._cv_dn)
        self.cv.bind('<B1-Motion>', self._cv_mv)
        self.cv.bind('<ButtonRelease-1>', self._cv_up)
        self.cv.bind('<ButtonPress-3>', self._cv_right_click)
        self.cv.bind('<ButtonPress-2>', self._pan_dn)
        self.cv.bind('<B2-Motion>', self._pan_mv)
        self.cv.bind('<ButtonRelease-2>', self._pan_up)
        self.cv.bind('<MouseWheel>', self._scroll)
        self.cv.bind('<Configure>', lambda e: self._render_cv())
        self.cv.bind('<Motion>', self._cv_hover)
        self.cv.bind('<Leave>', self._cv_leave)

    def _set_space(self, v, e=None):
        if not self._is_active():
            return
        if e is not None and isinstance(e.widget, tk.Entry):
            return  # Leerzeichen beim Tippen (DPI/X/Y-Felder) nicht als Kuerzel werten
        if v:
            if not self._space:
                self._space_used_for_pan = False  # frischer Tastendruck, kein Key-Repeat
        else:
            if self._space and not self._space_used_for_pan:
                # Kurzes Antippen ohne Ziehen -> Spiegeln umschalten statt Pan
                self._toggle_flip_via_space()
        self._space = v
        if self.img_orig and not self._pan_ref:
            if v:
                self.cv.configure(cursor='hand2')
            else:
                self._update_tool_cursor()

    def _pick_tool(self, which: str):
        """Die vier Werkzeuge (LED umschalten / Variante platzieren / Messen /
        Skalieren) sind gegenseitig exklusiv (wie eine Radiobutton-Gruppe,
        aber abschaltbar): aktiviert man eines, werden die anderen
        deaktiviert; klickt man das aktive nochmal an, geht es aus (zurueck
        zu Auswaehlen/Verschieben)."""
        tool_vars = {
            'led_toggle': self.tool_led_toggle,
            'place': self.tool_place,
            'measure': self.tool_measure,
            'scale': self.tool_scale,
        }
        if tool_vars[which].get():
            for name, var in tool_vars.items():
                if name != which:
                    var.set(False)
        self._update_tool_cursor()
        if not self.tool_place.get() and self._hover is not None:
            self._hover = None  # Platzieren-Schattenvorschau ausblenden
        if not self.tool_measure.get():
            self._measure_pts = []  # Massband ausblenden, sobald das Werkzeug abgeschaltet wird
        if not self.tool_scale.get():
            self._scale_pts = []  # Kalibrierlinie ausblenden, sobald das Werkzeug abgeschaltet wird
        self._render_cv()
        # Tastaturfokus zurueck auf die Canvas: sonst behaelt der gerade
        # angeklickte Werkzeug-Checkbutton den Fokus, und ein Leertaste-Tipp
        # (Spiegeln) wuerde zuerst dessen eingebaute <space>-Klassenbindung
        # ausloesen -- das Werkzeug wuerde sich dabei ungewollt selbst wieder
        # abschalten, statt (nur) die Ausrichtung zu spiegeln.
        self.cv.focus_set()

    def _update_tool_cursor(self):
        if self._space:
            return
        if self.tool_led_toggle.get():
            self.cv.configure(cursor='hand2')
        elif self.tool_place.get():
            self.cv.configure(cursor='plus')
        elif self.tool_measure.get():
            self.cv.configure(cursor='tcross')
        elif self.tool_scale.get():
            self.cv.configure(cursor='sizing')
        else:
            self.cv.configure(cursor='crosshair')

    def _toggle_flip_via_space(self):
        """Leertaste antippen: spiegelt die ausgewaehlte Platzierung, oder -- wenn
        keine ausgewaehlt ist -- die naechste noch zu platzierende (Schatten-
        Vorschau)."""
        if 0 <= self.sel_idx < len(self.placements):
            p = self.placements[self.sel_idx]
            p['flipped'] = not p.get('flipped', False)
            self._auto_assign()
            self._render_placements()
            self._render_cv()
            self._schedule_save()
            self._status('Platzierung gespiegelt' if p['flipped'] else 'Platzierung normal', C['green'])
        else:
            self.place_flipped.set(not self.place_flipped.get())
            self._render_cv()
            self._status('Naechste Platzierung: gespiegelt' if self.place_flipped.get()
                        else 'Naechste Platzierung: normal', C['blue'])

    def _next_footprint_size(self) -> tuple | None:
        """Footprint-Groessen-Override fuer die NAECHSTE Platzierung (Toolbar-
        Eingabefelder oben) -- None (leer oder ungueltig) bedeutet: keine
        Ueberschreibung, die neue Platzierung folgt dem Default der Variante
        (siehe resolve_footprint_size)."""
        try:
            w = float(self.v_next_footprint_w.get().replace(',', '.'))
            h = float(self.v_next_footprint_h.get().replace(',', '.'))
            if w <= 0 or h <= 0:
                return None
            return (w, h)
        except ValueError:
            return None

    # ── Variant-Verwaltung (nur EINE Variante) ──────────────────────────────

    def _update_variant_label(self):
        self.v_variant.set(self.variant['name'] if self.variant else '(noch keine angelegt)')

    def _edit_variant(self):
        """Oeffnet den Varianten-Designer fuer die eine, einzige Variante --
        existiert noch keine, wird hier die erste (und einzige) angelegt."""
        VariantDesigner(self.root, self._on_variant_saved, existing=self.variant)

    def _on_variant_saved(self, variant: dict, is_new: bool):
        self.variant = variant
        save_variant(self.variant)
        self._update_variant_label()
        # LED-Anzahl/Layout der Variante kann sich geaendert haben ->
        # Platzierungs-LED-Listen angleichen und Zuordnung neu berechnen.
        for p in self.placements:
            n = len(variant['leds'])
            p['leds'] = [{'index': i, 'enabled': False, 'windowIndex': None}
                         for i in range(n)]
        self._auto_assign()
        self._render_cv()
        self._schedule_save()

    # ── Projekt-Export (DXF/CSV, alle Haeuser) ───────────────────────────────
    #
    # Lebt bewusst in diesem Tab (nicht in Tab 1 "Fenster markieren") -- die
    # exportierten Dateien (LED-/Platinen-Platzierungen, Footprints,
    # Stueckliste) haengen inhaltlich an den LED-Batches, nicht am reinen
    # Fenster-Markieren.

    def _export_project(self):
        """Kombinierter Projekt-Export: schreibt in EINEM Rutsch je Haus aus
        public/houses (siehe images.json) dessen DXF-Datei(en) (LED-/
        Platinen-Platzierung + Gebaeudekontur-Teile, siehe dxfExport.py),
        seine Stueckliste als CSV (csvExport.py), je tatsaechlich
        vorkommender Bodenplatten-/Seitenteil-Groesse (width_mm bzw.
        height_mm, siehe footprintScale.get_bottom_plate_points/
        get_side_plate_points) eine EIGENE Datei UND ein kombiniertes
        Teile-Blatt, das dieselben Bodenplatten/Aussen-/Innen-Seitenteile in
        der Stueckzahl aus der Stueckliste (siehe csvExport.
        count_footprint_sizes, dieselbe Zaehlung wie in get_part_counts,
        damit CSV, Einzeldateien und Blatt nie auseinanderlaufen) PLUS je
        EINE Referenz-Kopie der Hauszeichnung (Kontur mit Fensterscheiben UND
        Kontur ohne) vereint -- die Haus-Kopien werden NICHT mit ihrer
        Stueckliste-Stueckzahl multipliziert (die bezieht sich auf reale
        Material-Zuschnitte, nicht auf Kopien in dieser Uebersicht). OHNE den
        Footprint -- der wird NICHT als eigene Datei geschrieben (nur als
        Skizze/Ausschnitt direkt in die Hauszeichnung eingefuegt, siehe
        dxfExport._insert_footprints), also auch nicht aufs Blatt gepackt.

        JEDE geschriebene Datei (ausser der Hauszeichnung selbst und dem
        Teile-Blatt) traegt ihre Stueckzahl als Praefix im Dateinamen --
        'quantity_name.dxf' (z.B. '6_bottomplate-75mm.dxf',
        '4_sideplate-outer-33mm.dxf') --, damit auf einen Blick klar ist,
        wie viele Kopien davon zu schneiden sind, ohne extra in der CSV
        nachschauen zu muessen.

        Alles (Teile-Blatt) auf EINER DXF, in Zeilen gepackt
        (footprintScale.nest_parts_sheet, PART_SPACING_MM Abstand, ein
        ungefaehr rechteckiges statt ein beliebig langes Blatt). ALLE Dateien
        landen in DIESES Hauses EIGENEM 'exported'-Unterordner (public/
        houses/<name>/exported/), getrennt von dessen Quelldateien
        (<name>.pdf/.json/...) im Elternordner. Ersetzt die frueher
        getrennten 'Projekt als DXF exportieren'/'Stückliste als CSV
        exportieren'-Buttons, damit DXF und CSV niemals aus unterschiedlichen
        Projektstaenden stammen. Haeuser ohne platzierte LEDs/Kontur werden
        dabei stillschweigend uebersprungen."""
        if dxfExport is None or csvExport is None or footprintScale is None:
            messagebox.showinfo('Projekt-Export',
                'ezdxf ist nicht installiert (pip install ezdxf) -- Export nicht verfuegbar.')
            return

        index_path = HOUSES_DIR / 'images.json'
        if not index_path.is_file():
            messagebox.showinfo('Projekt-Export', 'Keine Häuser gefunden (public/houses/images.json fehlt).')
            return

        variant = load_variant()
        fw = (variant or {}).get('footprint_width_mm')
        fh = (variant or {}).get('footprint_height_mm')
        variant_size = (fw, fh) if fw and fh else None
        variant_leds = (variant or {}).get('leds') or []

        try:
            names = json.loads(index_path.read_text(encoding='utf-8')).get('images', [])
            written: list = []
            for name in names:
                house_dir = HOUSES_DIR / name
                json_path = house_dir / f'{name}.json'
                if not json_path.is_file():
                    continue
                exported_dir = house_dir / 'exported'
                house_data = json.loads(json_path.read_text(encoding='utf-8'))
                px_per_mm = (house_data.get('dpi') or dxfExport.DEFAULT_DPI) / 25.4
                outline = dxfExport.house_outline(house_dir / f'{name}.pdf', px_per_mm)
                entries = dxfExport.get_placed_leds(house_data)

                # Reines Foto in Farbe, OHNE jede Markierung (Fenster/LEDs/
                # Kontur) -- nur das eingebettete Bild selbst (bei PDF-
                # Quellen dessen "Bild"-Ebene, siehe pdfHouse.load_pdf_house,
                # dieselbe Bildebene, die auch der Editor als Grundlage
                # zeigt). Landet DIREKT NEBEN der Eingabedatei (house_dir),
                # NICHT im exported-Unterordner -- rein informativ (kein
                # Laserschnitt-Teil), daher auch nicht in der Stueckliste.
                # Ein Fehlschlag hier (z.B. unlesbares Bild) soll auch nicht
                # den restlichen Export dieses Hauses verhindern.
                img_src_path = _find_house_image_path(house_dir, name)
                if img_src_path is not None:
                    try:
                        if img_src_path.suffix.lower() == '.pdf' and pdfHouse is not None:
                            photo, _outline_px = pdfHouse.load_pdf_house(img_src_path)
                        else:
                            photo = Image.open(img_src_path)
                            photo.load()
                        if photo.mode != 'RGB':
                            photo = photo.convert('RGB')
                        photo_path = house_dir / f'{name}_photo.png'
                        photo.save(photo_path, 'PNG')
                        written.append(photo_path)
                    except Exception:
                        pass

                # house1.code.json (siehe App._build_code_json/_save -- direkt
                # neben der Eingabedatei geschrieben, bei jedem Speichern
                # aktuell gehalten) gehoert als Kopie MIT in den exported-
                # Ordner, damit dieser fuer sich allein alles Noetige fuer den
                # ESP32 enthaelt, ohne im Hausordner selbst suchen zu muessen.
                code_json_path = house_dir / f'{name}.code.json'
                if code_json_path.is_file():
                    exported_dir.mkdir(parents=True, exist_ok=True)
                    exported_code_json_path = exported_dir / f'{name}.code.json'
                    exported_code_json_path.write_bytes(code_json_path.read_bytes())
                    written.append(exported_code_json_path)

                # Fuer das kombinierte Teile-Blatt gesammelt, waehrend die
                # einzelnen Dateien weiter unten wie gewohnt geschrieben
                # werden -- (Doc, Stueckzahl)-Paare, siehe nest_parts_sheet.
                sheet_items: list = []
                frame_rect = None

                if entries:
                    written.append(dxfExport.export_dxf(
                        entries, outline, exported_dir / f'{name}_house_led_overview.dxf',
                        variant_size, variant_leds))
                    size_counts = csvExport.count_footprint_sizes(entries, variant_size)
                    if size_counts:
                        # Bodenplatte haengt NUR von width_mm ab, Seitenteile
                        # NUR von height_mm -- je EINE Datei pro distinktem
                        # Wert (nicht pro (width_mm,height_mm)-Paar), sonst
                        # wuerde dieselbe Datei mehrfach mit unterschiedlicher
                        # Stueckzahl im Namen ueberschrieben (siehe
                        # csvExport.get_part_counts, dieselbe Aufsummierung).
                        width_counts: dict = {}
                        height_counts: dict = {}
                        for (width_mm, height_mm), count in size_counts.items():
                            width_counts[width_mm] = width_counts.get(width_mm, 0) + count
                            height_counts[height_mm] = height_counts.get(height_mm, 0) + count

                        for width_mm, count in sorted(width_counts.items()):
                            bp_count = count * csvExport.BOTTOM_PLATES_PER_PLACEMENT
                            bp_doc = footprintScale.get_bottom_plate_points(width_mm)
                            bp_path = exported_dir / f'{bp_count}_bottomplate-{width_mm:g}mm.dxf'
                            bp_path.parent.mkdir(parents=True, exist_ok=True)
                            bp_doc.saveas(str(bp_path))
                            written.append(bp_path)
                            sheet_items.append((bp_doc, count))

                        for height_mm, count in sorted(height_counts.items()):
                            for kind, inner, multiplier in (
                                ('outer', False, csvExport.SIDE_PIECES_PER_PLACEMENT),
                                ('inner', True, csvExport.INNER_SIDE_PIECES_PER_PLACEMENT),
                            ):
                                sp_count = count * multiplier
                                sp_doc = footprintScale.get_side_plate_points(height_mm, inner=inner)
                                sp_path = exported_dir / f'{sp_count}_sideplate-{kind}-{height_mm:g}mm.dxf'
                                sp_doc.saveas(str(sp_path))
                                written.append(sp_path)
                                sheet_items.append((sp_doc, sp_count))

                if outline is not None:
                    # Glasscheiben-Ausschnitte, NICHT die vollen Fensterrahmen
                    # (siehe dxfExport._draw_outline_with_panes -- der Rahmen
                    # selbst bleibt Material, nur die Glasflaeche wird
                    # ausgeschnitten) -- 'glassPanes' (siehe windowTool.
                    # App._save/_svg_rects: einzeln markierte Scheiben PLUS
                    # jedes Fenster ohne eigene Scheiben-Unterteilung als
                    # Ganzes) ist dafuer die richtige Quelle, nicht 'windows'
                    # (die vollen Rahmen). Fehlt der Schluessel komplett (sehr
                    # alte, vor dieser Funktion gespeicherte Haus-JSONs), auf
                    # 'windows' zurueckfallen statt eine leere (lichtdichte)
                    # Kontur zu erzeugen.
                    pane_rects = house_data['glassPanes'] if 'glassPanes' in house_data \
                        else house_data.get('windows', [])
                    panes = [
                        {'x': p['x'] / px_per_mm, 'y': p['y'] / px_per_mm,
                         'w': p['w'] / px_per_mm, 'h': p['h'] / px_per_mm}
                        for p in pane_rects
                    ]
                    # Rahmen-Rechteck (siehe App._frame_rect_px/_default_frame_px):
                    # per Hand gesetzt (house_data['frame'], Bild-px) oder Default =
                    # Bounding-Box der Kontur selbst (siehe dxfExport.Outline) --
                    # bestimmt sowohl den Beschnitt (links/rechts/unten gerade,
                    # oben bleibt die Kontur wie sie ist) als auch die Laenge der
                    # 4 Rahmenleisten weiter unten.
                    frame_px = house_data.get('frame')
                    if frame_px:
                        frame_rect = (frame_px['left'] / px_per_mm, frame_px['top'] / px_per_mm,
                                    frame_px['right'] / px_per_mm, frame_px['bottom'] / px_per_mm)
                    else:
                        frame_rect = (outline.left, outline.top, outline.right, outline.bottom)

                    panes_path = exported_dir / f'{csvExport.OUTLINE_WITH_PANES_COUNT}_{name}_outline_with_panes.dxf'
                    written.append(dxfExport.export_outline_with_panes_dxf(
                        outline, panes, panes_path, entries, variant_size, variant_leds, frame_rect))
                    outline_path = exported_dir / f'{csvExport.OUTLINE_ONLY_COUNT}_{name}_outline.dxf'
                    written.append(dxfExport.export_outline_only_dxf(outline, outline_path, frame_rect))

                    # Die Hauszeichnung selbst gehoert mit aufs Teile-Blatt
                    # (siehe Docstring) -- per readfile() zurueckgelesen, da
                    # export_outline_*_dxf nur den Pfad zurueckgibt, nicht das
                    # Doc. NUR JE EINE Kopie (nicht mit der Stueckzahl aus der
                    # Stueckliste multipliziert wie bei den Platten-Teilen) --
                    # die Hauszeichnung dient hier als Referenz, nicht als
                    # tatsaechlich in dieser Stueckzahl zu schneidendes Teil.
                    sheet_items.append((dxfExport.ezdxf.readfile(str(panes_path)), 1))
                    sheet_items.append((dxfExport.ezdxf.readfile(str(outline_path)), 1))

                    # 4 Rahmenleisten (2x side links/rechts -- identisch, EINE
                    # Datei mit Stueckzahl 2 -- sowie je 1x top OHNE und 1x top
                    # MIT Mittenloch fuer oben/unten, siehe footprintScale.
                    # get_frame_side_points/get_frame_top_points/
                    # get_frame_top_hole_points) -- Laenge aus dem Rahmen-Rechteck.
                    frame_left, frame_top, frame_right, frame_bottom = frame_rect
                    side_length = frame_bottom - frame_top
                    top_length = frame_right - frame_left
                    side_doc = footprintScale.get_frame_side_points(side_length)
                    side_path = exported_dir / f'2_frameside-{side_length:g}mm.dxf'
                    side_doc.saveas(str(side_path))
                    written.append(side_path)
                    sheet_items.append((side_doc, 2))

                    top_doc = footprintScale.get_frame_top_points(top_length)
                    top_path = exported_dir / f'1_frametop-{top_length:g}mm.dxf'
                    top_doc.saveas(str(top_path))
                    written.append(top_path)
                    sheet_items.append((top_doc, 1))

                    top_hole_doc = footprintScale.get_frame_top_hole_points(top_length)
                    top_hole_path = exported_dir / f'1_frametop-hole-{top_length:g}mm.dxf'
                    top_hole_doc.saveas(str(top_hole_path))
                    written.append(top_hole_path)
                    sheet_items.append((top_hole_doc, 1))

                if sheet_items:
                    written.append(footprintScale.nest_parts_sheet(
                        sheet_items, exported_dir / f'{name}_parts_combined.dxf'))

                rows = csvExport.get_part_counts(house_data, variant, outline, house_name=name,
                                                frame_rect=frame_rect)
                if rows:
                    written.append(csvExport.export_csv(rows, exported_dir / f'{name}.csv'))
        except Exception as ex:
            self._status(f'⚠ Projekt-Export fehlgeschlagen: {ex}', C['red'])
            return

        if not written:
            messagebox.showinfo('Projekt-Export',
                'Keine Dateien geschrieben -- kein Haus hat platzierte LEDs/Kontur.')
            return
        self._status(f'✓ {len(written)} Datei(en) exportiert', C['green'])
        messagebox.showinfo('Projekt-Export',
            f'{len(written)} Datei(en) geschrieben in\n{HOUSES_DIR}\\<Haus>\\exported\\')

    # ── Bilder-Panel ──────────────────────────────────────────────────────

    def _scan_images(self):
        """Fuellt die Bilderliste im linken Panel -- jedes Haus liegt in
        seinem EIGENEN Unterordner (public/houses/<name>/<name>.EXT, siehe
        HOUSES_DIR), daher wird HIER eine Ebene tiefer gesucht (nicht direkt
        in HOUSES_DIR selbst): pro Unterordner die Bilddatei, deren Name
        (ohne Endung) mit dem Ordnernamen uebereinstimmt."""
        for w in self._img_list_frame.winfo_children():
            w.destroy()
        if not HOUSES_DIR.is_dir():
            tk.Label(self._img_list_frame, text=f'Ordner nicht gefunden:\n{HOUSES_DIR}',
                     bg=C['bg'], fg=C['red'], justify='left', wraplength=190,
                     font=('Segoe UI', 8)).pack(padx=8, pady=12)
            return
        files = sorted(
            f for sub in HOUSES_DIR.iterdir() if sub.is_dir()
            for f in sub.iterdir()
            if f.stem == sub.name and f.suffix.lower() in IMAGE_EXTS
            and not any(m in f.name for m in EXCLUDE_MARKERS)
        )
        if not files:
            tk.Label(self._img_list_frame, text='Keine Bilder gefunden.',
                     bg=C['bg'], fg=C['dim'], font=('Segoe UI', 9)).pack(pady=12)
            return
        for f in files:
            active = (self.img_path == f)
            has_json = f.with_suffix('.json').exists()
            bg = C['blue_sel'] if active else C['bg']
            row = tk.Frame(self._img_list_frame, bg=bg)
            row.pack(fill='x')
            icon = '✅' if has_json else '🖼'
            lbl = tk.Label(row, text=f'{icon}  {f.name}', bg=bg,
                           fg=C['text'] if active else C['muted'],
                           anchor='w', font=('Segoe UI', 9), padx=8, pady=5)
            lbl.pack(fill='x')
            for wgt in (row, lbl):
                wgt.bind('<Button-1>', lambda e, p=f: self._load_image(p))

    # ── Bild laden/speichern ────────────────────────────────────────────────

    def _load_image(self, path: Path):
        try:
            if path.suffix.lower() == '.pdf':
                if pdfHouse is None:
                    raise RuntimeError('PDF-Unterstuetzung fehlt (pip install pymupdf)')
                # Die Kontur-Referenzebene wird nur im Fenster-Markieren-Tab
                # gezeichnet (siehe windowTool.py) -- hier zaehlt nur das Foto.
                im, _ = pdfHouse.load_pdf_house(path)
            else:
                im = Image.open(path)
                im.load()
        except Exception as ex:
            self._status(f'⚠ Ladefehler: {ex}', C['red'])
            return
        if im.mode not in ('RGB', 'RGBA', 'L'):
            im = im.convert('RGBA')

        self.img_orig = im
        self.img_path = path
        self.json_path = path.with_suffix('.json')
        self.windows = []
        self.placements = []
        self.sel_idx = -1
        self.sel_idxs = set()
        self.chain_sel_idx = -1
        self._hover = None
        self._v_name.set(f'{path.name}  ({im.width}×{im.height} px)')

        data = {}
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding='utf-8'))
            except Exception:
                data = {}
        self.windows = data.get('windows', [])
        self.placements = [self._migrate_placement(p) for p in data.get('ledBatches', [])]
        self.chain_order = list(data.get('chainOrder', []))
        self.frame_rect_px = self._resolve_frame_rect_px(data.get('frame'), path, im)

        # DPI-Prioritaet: JSON > Bilddatei-Metadaten > Standard
        file_dpi = None
        info_dpi = im.info.get('dpi')
        if info_dpi:
            try:
                file_dpi = float(info_dpi[0]) if isinstance(info_dpi, (tuple, list)) else float(info_dpi)
            except (TypeError, ValueError):
                file_dpi = None
        self.dpi = float(data.get('dpi') or file_dpi or DEFAULT_DPI)
        self.v_dpi.set(f'{self.dpi:g}')

        self._update_display_img()
        self._auto_assign()
        self._fit()
        self._fit_chain()
        self._render_placements()
        self._render_chain_tab()
        self._scan_images()

    def _migrate_placement(self, p: dict) -> dict:
        """Altes Format {'rect': {x,y,w,h}} -> neues Positions-Format {'x','y'}.
        LED-Eintraege werden auf {'index','enabled','windowIndex'} normalisiert.
        'enabled'/'windowIndex' werden von _auto_assign() neu berechnet -- die
        einzige echte, ueber einen Neustart hinweg zu erhaltende Information ist
        ein manueller An/Aus-Override ('manual'), den der Nutzer per Rechtsklick
        gesetzt hat."""
        out = {
            'id': p.get('id') or uuid.uuid4().hex[:8],
            'variantId': p.get('variantId'),
            'x': p.get('x', p.get('rect', {}).get('x', 0)),
            'y': p.get('y', p.get('rect', {}).get('y', 0)),
            'flipped': bool(p.get('flipped', False)),
            'leds': [],
        }
        if p.get('width_mm') and p.get('height_mm'):
            out['width_mm'] = p['width_mm']
            out['height_mm'] = p['height_mm']
        n = len(self.variant['leds']) if self.variant else len(p.get('leds', []))
        saved_by_index = {l.get('index'): l for l in p.get('leds', [])}
        for i in range(n):
            saved = saved_by_index.get(i, {})
            led = {'index': i, 'enabled': False, 'windowIndex': None}
            if saved.get('manual'):
                led['manual'] = True
                led['enabled'] = bool(saved.get('enabled', False))
            out['leds'].append(led)
        return out

    def _resolve_frame_rect_px(self, frame_data: dict | None, path: Path, im: 'Image.Image') -> tuple:
        """(left, top, right, bottom) in Bild-px fuer das Rahmen-Rechteck
        (siehe self.frame_rect_px/_hit_frame_edge). Per Hand gesetzt
        (`frame_data` aus dem JSON, siehe _save) gewinnt immer. Ohne das:
        Default = die INNERSTE Bounding-Box der Gebaeude-KONTUR selbst (siehe
        dxfExport.Outline.inner_bbox/house_outline, hier mit px_per_mm=1.0
        aufgerufen, damit sie in denselben Bild-px wie windows/placements
        steht) -- hat NICHTS mit den Fenstern zu tun, nur mit der Kontur.
        'Innerste' statt der aeusseren Huelle, weil die nachgezeichnete Kontur
        aus mehreren Teilpfaden bestehen kann (siehe inner_bbox) -- ragt einer
        davon weiter raus, soll der Rahmen trotzdem nur so weit reichen wie
        ALLE Teilpfade gemeinsam. Ohne PDF-Quelle (aeltere Bild-Haeuser ohne
        nachgezeichnete Kontur, siehe pdfHouse) faellt das auf die volle
        Bildgroesse zurueck."""
        if frame_data:
            return (frame_data['left'], frame_data['top'],
                    frame_data['right'], frame_data['bottom'])
        outline_px = None
        if dxfExport is not None and path.suffix.lower() == '.pdf':
            outline_px = dxfExport.house_outline(path, 1.0)
        if outline_px is not None:
            return outline_px.inner_bbox()
        return (0.0, 0.0, float(im.width), float(im.height))

    def _reload_windows(self):
        """Liest die Fensterliste frisch von der Platte ein -- der Fenster-Tab
        kann sie veraendert haben, waehrend dieser Tab schon offen war (neue
        Fenster markiert, verschoben, geloescht). Wird bei jedem Wechsel in
        diesen bzw. den Ketten-Tab aufgerufen (siehe windowTool._launch_combined),
        damit man nicht das Bild manuell neu laden muss, um aktuelle Fenster zu
        sehen. Ueberschreibt bewusst nur self.windows, nichts sonst."""
        if not self.json_path or not self.json_path.exists():
            return
        try:
            data = json.loads(self.json_path.read_text(encoding='utf-8'))
        except Exception:
            return
        new_windows = data.get('windows', [])
        if new_windows == self.windows:
            return
        self.windows = new_windows
        self._auto_assign()
        self._render_cv()
        self._render_chain_tab()

    def _schedule_save(self):
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(400, self._save)

    def _save(self):
        if not self.img_path:
            return
        # chainIndex kommt aus _recompute_chain (Verbindungsreihenfolge + Spiegelung),
        # nicht mehr aus der blossen Platzierungs-Array-Reihenfolge.
        batches_out = []
        for p in self.placements:
            leds_out = [{
                'index': led['index'],
                'chainIndex': led.get('chainIndex', led['index']),
                'pixelIndex': led.get('pixelIndex'),
                'enabled': led['enabled'],
                'windowIndex': led.get('windowIndex'),
                'manual': led.get('manual', False),
            } for led in p['leds']]
            batch_out = {
                'id': p['id'],
                'variantId': p['variantId'],
                'x': round(p['x'], 1),
                'y': round(p['y'], 1),
                'flipped': bool(p.get('flipped', False)),
                'leds': leds_out,
            }
            if p.get('width_mm') and p.get('height_mm'):
                batch_out['width_mm'] = p['width_mm']
                batch_out['height_mm'] = p['height_mm']
            batches_out.append(batch_out)

        # Bestehendes JSON einlesen und nur die LED-Teile aktualisieren.
        # 'windows' wird vom Fenster-Tool geschrieben -- wir duerfen es hier
        # NIEMALS blind durch unsere eigene (moeglicherweise veraltete, z.B.
        # geladen bevor das Fenster-Tool zuletzt gespeichert hat) self.windows-
        # Kopie ersetzen. Das hat frueher echte, muehsam markierte Fenster
        # geloescht, sobald self.windows aus irgendeinem Grund nicht dem
        # aktuellen Stand entsprach. Stattdessen: die FRISCH von der Platte
        # gelesene Fensterliste ist die Wahrheit; wir tragen 'ledIndex' nur
        # hinein, wenn die Anzahl zu self.windows passt (sonst lassen wir die
        # Fenster unangetastet, statt zu raten).
        data = {}
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding='utf-8'))
            except Exception:
                data = {}
        fresh_windows = data.get('windows', [])
        if len(fresh_windows) == len(self.windows):
            for fw, mw in zip(fresh_windows, self.windows):
                led_idx = mw.get('ledIndex')
                if led_idx is not None:
                    fw['ledIndex'] = led_idx
                else:
                    fw.pop('ledIndex', None)
                pixel_idx = mw.get('pixelIndex')
                if pixel_idx is not None:
                    fw['pixelIndex'] = pixel_idx
                else:
                    fw.pop('pixelIndex', None)
        data['name'] = self.img_path.stem
        data['dpi'] = self.dpi
        data['ledBatches'] = batches_out
        data['windows'] = fresh_windows
        if self.frame_rect_px is not None:
            left, top, right, bottom = self.frame_rect_px
            data['frame'] = {'left': round(left, 1), 'top': round(top, 1),
                            'right': round(right, 1), 'bottom': round(bottom, 1)}
        valid_ids = {p['id'] for p in self.placements}
        data['chainOrder'] = [pid for pid in self.chain_order if pid in valid_ids]
        data['disabledLeds'] = list(self.disabled_leds)
        data['totalLedCount'] = self.total_led_count
        data['totalPixelCount'] = self.total_pixel_count
        data['dataChain'] = list(self.data_chain)
        try:
            self.json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            code_path = self.json_path.with_suffix('.code.json')
            code_path.write_text(
                json.dumps(self._build_code_json(), indent=2, ensure_ascii=False), encoding='utf-8')
            self._status('✓ Gespeichert', C['green'])
            self._scan_images()
        except Exception as ex:
            self._status(f'⚠ {ex}', C['red'])

    @staticmethod
    def _compact_ranges(indices) -> list:
        """Komprimiert eine Liste von Ganzzahlen zu einer sortierten Liste aus
        einzelnen Werten (int) und zusammenhaengenden Laeufen ("<from>-<to>",
        als String). Beispiel: [1, 3, 9, 10, 11] -> [1, 3, '9-11']."""
        idxs = sorted(set(indices))
        out = []
        i = 0
        while i < len(idxs):
            j = i
            while j + 1 < len(idxs) and idxs[j + 1] == idxs[j] + 1:
                j += 1
            out.append(idxs[i] if i == j else f'{idxs[i]}-{idxs[j]}')
            i = j + 1
        return out

    def _build_code_json(self) -> dict:
        """Kompakte, ESP32-taugliche Zweitkodierung derselben Zuordnung wie im
        Haupt-JSON, aber mit dem PHYSISCHEN chainIndex (nicht dem
        kompaktierten pixelIndex) und durchgehend bereichs-komprimiert:
          - 'windows': {str(fensterindex): chainIndex (int) oder "<from>-<to>"}
            -- nur Fenster mit mindestens einer aktiven LED tauchen auf.
          - 'disabled-leds': [int oder "<from>-<to>", ...] -- ALLE chainIndex-
            Werte ohne aktive Fensterzuordnung (deaktivierte LEDs zaehlen
            weiterhin mit, belegen ja weiterhin einen Platz auf dem Strang)."""
        window_chain_idxs: dict = {}
        disabled: list = []
        for p in self.placements:
            for led in p['leds']:
                ci = led.get('chainIndex')
                if ci is None:
                    continue
                wi = led.get('windowIndex')
                if led['enabled'] and wi is not None:
                    window_chain_idxs.setdefault(wi, []).append(ci)
                else:
                    disabled.append(ci)

        windows_out = {}
        for wi, idxs in window_chain_idxs.items():
            idxs = sorted(idxs)
            windows_out[str(wi)] = idxs[0] if len(idxs) == 1 else f'{idxs[0]}-{idxs[-1]}'

        return {
            'windows': windows_out,
            'disabled-leds': self._compact_ranges(disabled),
        }

    def _status(self, text, color=None):
        if getattr(self, '_status_after', None) is not None:
            self.root.after_cancel(self._status_after)
        self._v_status.set(text)
        self._lbl_status.configure(fg=color or C['text'])
        self._status_after = self.root.after(2500, lambda: self._v_status.set(''))

    # ── Canvas Rendering ────────────────────────────────────────────────────

    def _s2i(self, cx, cy):
        return (cx - self.off_x) / self.zoom, (cy - self.off_y) / self.zoom

    def _i2s(self, ix, iy):
        return self.off_x + ix * self.zoom, self.off_y + iy * self.zoom

    def _fit(self):
        if not self.img_orig:
            return
        # update_idletasks() erzwingt ausstehende Geometrie-Berechnungen, BEVOR
        # gemessen wird -- ohne das liefert ein gerade erst sichtbar gewordener
        # Tab (z.B. direkt nach einem Notebook-Tab-Wechsel) winfo_width()==1
        # (statt der echten Groesse). "or 800" faengt das NICHT ab, da 1
        # wahr ist -- daher zusaetzlich ein expliziter Mindestgroessen-Check.
        self.cv.update_idletasks()
        W = self.cv.winfo_width()
        H = self.cv.winfo_height()
        if W <= 1:
            W = 800
        if H <= 1:
            H = 600
        pad = 24
        self.zoom = min((W - pad * 2) / self.img_orig.width,
                        (H - pad * 2) / self.img_orig.height, 1.0)
        self._cache_zoom = None
        self.off_x = (W - self.img_orig.width * self.zoom) / 2
        self.off_y = (H - self.img_orig.height * self.zoom) / 2
        self._render_cv()

    # ── DPI / Massstab ───────────────────────────────────────────────────────

    def px_per_mm(self) -> float:
        return self.dpi / 25.4

    def _commit_dpi(self, _e=None):
        try:
            val = float(self.v_dpi.get().replace(',', '.'))
            if val <= 0:
                raise ValueError
        except ValueError:
            self.v_dpi.set(f'{self.dpi:g}')
            return
        if val != self.dpi:
            self.dpi = val
            self._auto_assign()
            self._render_cv()
            self._schedule_save()

    def _update_display_img(self):
        """Anzeigebild grau (Standard) oder farbig aufbereiten."""
        if self.img_orig is None:
            self._display_img = None
            return
        if self.show_color.get():
            self._display_img = self.img_orig.convert('RGB')
        else:
            self._display_img = self.img_orig.convert('L').convert('RGB')
        self._cache_zoom = None
        self._render_cv()

    # ── Platzierungen (massstabsgetreu, nur Position) ────────────────────────

    def _placement_points(self, p: dict):
        """LED-Positionen einer Platzierung in Bild-px, oder None wenn die
        Variante fehlt."""
        variant = self.variant
        if not variant:
            return None
        return led_image_positions(variant, p['x'], p['y'], self.px_per_mm(),
                                   p.get('flipped', False))

    def _snap_anchor(self, ax: float, ay: float, variant: dict, flipped: bool = False):
        """Rastet den Anker so ein, dass die LED-Reihe auf der OBERKANTE des am
        weitesten oben liegenden beruehrten Fensters liegt. Damit landen ALLE
        beruehrten Fenster unterhalb der LEDs (nicht nur das naechstgelegene --
        wuerde man stattdessen zur naechstgelegenen Kante snappen, koennte ein
        anderes, knapp tiefer/hoeher liegendes Fenster ueber/in der LED-Reihe
        statt darunter landen)."""
        pts = led_image_positions(variant, ax, ay, self.px_per_mm(), flipped)
        candidates = []  # (Fenster-Oberkante y, dazu noetiger dy)
        for w in self.windows:
            for (px, py) in pts:
                if w['x'] - SNAP_PX <= px <= w['x'] + w['w'] + SNAP_PX:
                    dy = w['y'] - py
                    if abs(dy) <= SNAP_PX:
                        candidates.append((w['y'], dy))
        if candidates:
            _, dy = min(candidates, key=lambda t: t[0])
            ay += dy
        return ax, ay

    def _nearest_touching_window(self, px: float, py: float):
        """Index des Fensters, dessen Rechteck (inkl. WINDOW_TOL-Toleranz) den
        Punkt beruehrt und dessen Mitte am naechsten liegt -- oder None."""
        best_wi, best_d = None, None
        for wi, w in enumerate(self.windows):
            if (w['x'] - WINDOW_TOL <= px <= w['x'] + w['w'] + WINDOW_TOL and
                    w['y'] - WINDOW_TOL <= py <= w['y'] + w['h'] + WINDOW_TOL):
                cx = w['x'] + w['w'] / 2
                cy = w['y'] + w['h'] / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if best_d is None or d < best_d:
                    best_wi, best_d = wi, d
        return best_wi

    # ── "🪄 Auto platzieren" ─────────────────────────────────────────────────

    def _group_windows_into_rows(self, windows: list | None = None,
                                 tol_px: float = AUTO_PLACE_ROW_TOL_PX) -> list:
        """Clustert `windows` (Default self.windows) nach Oberkante (y) in
        "Reihen" -- ein Fenster gehoert zur ersten Reihe, deren Referenz-y
        (die des ersten Fensters darin) innerhalb `tol_px` liegt. Gibt eine
        Liste von Reihen zurueck, jede Reihe eine Liste von Fenster-Dicts
        (unsortiert innerhalb der Reihe -- Sortierung nach x macht der
        Aufrufer)."""
        rows: list = []
        for w in sorted(windows if windows is not None else self.windows, key=lambda w: w['y']):
            for row in rows:
                if abs(row[0]['y'] - w['y']) <= tol_px:
                    row.append(w)
                    break
            else:
                rows.append([w])
        return rows

    def _cluster_windows_into_groups(self, windows: list) -> list:
        """Gruppiert `windows` in Cluster von HOECHSTENS 3 raeumlich
        benachbarten Fenstern: zuerst in Reihen (siehe
        _group_windows_into_rows), dann innerhalb jeder Reihe (nach x
        sortiert) in aufeinanderfolgende Dreiergruppen. Die LETZTE Gruppe
        einer Reihe kann dabei WENIGER als 3 Fenster enthalten, wenn die
        Reihenlaenge nicht durch 3 teilbar ist -- es wird nie ein Fenster
        verworfen, jedes bekommt eine Gruppe (und damit spaeter eine
        Platzierung)."""
        groups: list = []
        for row in self._group_windows_into_rows(windows):
            row_sorted = sorted(row, key=lambda w: w['x'])
            for gi in range(0, len(row_sorted), 3):
                groups.append(row_sorted[gi:gi + 3])
        return groups

    _CACHE_UNSET = object()   # eigenes Sentinel -- None ist bei img_path/Kontur ein gueltiger Wert

    def _get_outline_bbox_px(self):
        """(left, top, right, bottom) der Gebaeude-Kontur in Bild-px (aus
        dem Quell-PDF, siehe pdfHouse.load_pdf_house -- dieselbe Kontur, die
        windowTool.py als Referenz-Ebene zeichnet). Wird wie die Kontur
        selbst NICHT im JSON gespeichert, sondern bei Bedarf frisch aus dem
        PDF gelesen (gecacht pro img_path, PDF-Parsing ist nicht ganz
        billig). None ohne PDF-Quelle/pymupdf/Kontur."""
        cached_path = getattr(self, '_outline_bbox_cache_path', self._CACHE_UNSET)
        if cached_path != self.img_path:
            self._outline_bbox_cache_path = self.img_path
            self._outline_bbox_cache = None
            if (pdfHouse is not None and self.img_path
                    and self.img_path.suffix.lower() == '.pdf'):
                try:
                    _img, outline_polylines = pdfHouse.load_pdf_house(self.img_path)
                except Exception:
                    outline_polylines = []
                if outline_polylines:
                    xs = [x for poly in outline_polylines for x, y in poly]
                    ys = [y for poly in outline_polylines for x, y in poly]
                    self._outline_bbox_cache = (min(xs), min(ys), max(xs), max(ys))
        return self._outline_bbox_cache

    def _get_input_node_pos(self):
        """Bild-px-Position (x, y) des Eingangs-Knotens: Mitte der
        Unterkante der Gebaeude-Kontur. None ohne Kontur (siehe
        _get_outline_bbox_px)."""
        bbox = self._get_outline_bbox_px()
        if bbox is None:
            return None
        left, _top, right, bottom = bbox
        return ((left + right) / 2, bottom)

    def _touches_any_window(self, px: float, py: float, windows: list) -> bool:
        return any(
            w['x'] - WINDOW_TOL <= px <= w['x'] + w['w'] + WINDOW_TOL and
            w['y'] - WINDOW_TOL <= py <= w['y'] + w['h'] + WINDOW_TOL
            for w in windows)

    def _best_group_anchor_x(self, group: list, group_top: float, px_per_mm: float,
                             naive_anchor_x: float) -> float:
        """Sucht den Anker-x, bei dem MOEGLICHST VIELE LEDs der Variante ein
        Fenster der Gruppe beruehren -- der feste LED-Abstand der Variante
        (led_image_positions: kann nicht gestreckt/gestaucht werden) passt
        naemlich nicht zwangslaeufig zum tatsaechlichen Abstand der Fenster,
        z.B. wenn zwischen zwei Fenstern eine Tuer/Luecke liegt: stur
        zentrieren (naive_anchor_x) kann dann dazu fuehren, dass mehr LEDs
        ins Leere treffen als noetig. Kandidaten sind alle Anker, bei denen
        irgendeine LED exakt auf die Mitte irgendeines Fensters der Gruppe
        faellt (plus der naive zentrierte Anker selbst) -- einer davon
        maximiert immer die Zahl DISTINKTER beruehrter Fenster, weil sich
        dieses Maximum nur an solchen "LED-auf-Fenstermitte"-Ausrichtungen
        aendern kann.

        Bewertet wird bewusst die Anzahl VERSCHIEDENER beruehrter Fenster,
        NICHT die rohe Anzahl beruehrender LEDs: bei stark unterschiedlich
        breiten Fenstern in einer Gruppe (z.B. ein breites Schaufenster neben
        normalen Fenstern) waeren sonst alle 3 LEDs bequem in EINEM breiten
        Fenster untergebracht (Trefferzahl 3) staerker bewertet als je eine
        LED in zwei verschiedenen, weiter auseinanderliegenden Fenstern
        (Trefferzahl 2) -- das wuerde die ganze Platine auf ein einzelnes
        Fenster zusammenziehen und ein danebenliegendes, genauso zur Gruppe
        gehoerendes Fenster komplett unbeleuchtet lassen (samt sichtbarem
        Ueberstand der Platine ueber die Fensterkante hinaus). Mit
        distinkten Fenstern zaehlt das Ueberdecken zweier verschiedener
        Fenster mehr als das mehrfache Treffen desselben.

        Bei Gleichstand gewinnt der Kandidat, der am naechsten am naiv
        zentrierten Anker liegt (bleibt so nah wie moeglich am optischen
        Zentrum der Gruppe -- insbesondere wenn KEIN Anker mehr als ein
        Fenster beruehren kann, weil die Fenster der Gruppe weiter
        auseinanderliegen als die feste LED-Spannweite der Variante: dann
        landet die Platine lieber sichtbar mittig zwischen den Fenstern als
        hart an eines herangezogen)."""
        variant = self.variant
        base_pts = led_image_positions(variant, 0.0, group_top, px_per_mm, False)
        candidates = {naive_anchor_x}
        for w in group:
            wcx = w['x'] + w['w'] / 2
            for (lx, _ly) in base_pts:
                candidates.add(wcx - lx)

        def distinct_windows_touched(ax):
            pts = led_image_positions(variant, ax, group_top, px_per_mm, False)
            touched = set()
            for wi, w in enumerate(group):
                if any(self._touches_any_window(px, py, (w,)) for (px, py) in pts):
                    touched.add(wi)
            return len(touched)

        best_ax, best_count, best_dist = naive_anchor_x, -1, None
        for ax in candidates:
            count = distinct_windows_touched(ax)
            dist = abs(ax - naive_anchor_x)
            if count > best_count or (count == best_count and (best_dist is None or dist < best_dist)):
                best_ax, best_count, best_dist = ax, count, dist
        return best_ax

    def _auto_place(self):
        """Platziert automatisch je EINE Batch pro Cluster von hoechstens 3
        raeumlich benachbarten Fenstern (siehe _cluster_windows_into_groups)
        -- ALLE Platzierungen bekommen dieselbe Footprint-Groesse (Default
        der Variante, siehe resolve_footprint_size); es gibt keine
        Sonderbehandlung mehr fuer Fenster nahe der Gebaeude-Unterkante.
        Jede Gruppe wird horizontal zentriert und vertikal an die
        Gruppen-Oberkante angelegt -- wie eine manuelle Platzierung, nur
        automatisch fuer alle Gruppen auf einmal. Direkt im Anschluss wird
        auch die komplette Verbindungsreihenfolge automatisch neu berechnet
        (siehe _auto_connect_chain), die versucht, keine Verbindung ueber
        MAX_CONNECTION_MM zu ziehen. Ueberschreibt alle bestehenden
        Platzierungen -- fragt vorher nach Bestaetigung."""
        if not self.img_orig or not self.variant:
            messagebox.showinfo('Keine Variante',
                'Bitte zuerst im Varianten-Designer LEDs anlegen ("Bearbeiten...").')
            return
        if not self.windows:
            messagebox.showinfo('Keine Fenster', 'Dieses Bild hat noch keine markierten Fenster.')
            return
        if self.placements and not messagebox.askyesno(
                'Auto platzieren',
                f'{len(self.placements)} bestehende Platzierung(en) werden dabei ERSETZT. Fortfahren?'):
            return

        px_per_mm = self.px_per_mm()
        minx, miny, w_mm, _h_mm = variant_bbox(self.variant)
        led_span_px = w_mm * px_per_mm

        new_placements: list = []
        for group in self._cluster_windows_into_groups(self.windows):
            group_left = min(w['x'] for w in group)
            group_right = max(w['x'] + w['w'] for w in group)
            group_top = min(w['y'] for w in group)
            anchor_x = (group_left + group_right) / 2 - led_span_px / 2
            placement = {
                'id': uuid.uuid4().hex[:8],
                'variantId': self.variant['id'],
                'x': round(anchor_x, 1),
                'y': round(group_top, 1),
                'flipped': False,
                'leds': [{'index': i, 'enabled': False, 'windowIndex': None}
                         for i in range(len(self.variant['leds']))],
            }
            new_placements.append(placement)

        if not new_placements:
            messagebox.showinfo('Auto platzieren',
                'Keine Dreiergruppe benachbarter Fenster in einer Reihe gefunden.')
            return

        self.placements = new_placements
        self.sel_idx = -1
        self.sel_idxs = set()
        self._auto_assign()
        self._auto_connect_chain()
        self._render_list_and_save()
        self._status(f'✓ {len(new_placements)} Batch(es) automatisch platziert', C['green'])

    def _find_bottom_center_placement(self):
        """Bestimmt die Platzierung, an deren DIN der Eingangs-Knoten
        angeschlossen wird (siehe _get_input_node_pos): unter allen
        Platzierungen der untersten Reihe (groesstes y, Toleranz
        AUTO_PLACE_ROW_TOL_PX -- deckt mehrere nebeneinander liegende
        Bodenplatzierungen ab) diejenige, deren horizontale Mitte am
        naechsten an der Mitte der Gebaeude-Kontur liegt (ohne Kontur:
        Mitte aller Platzierungen der untersten Reihe). None ohne
        Platzierungen."""
        if not self.placements:
            return None
        max_y = max(p['y'] for p in self.placements)
        bottom_row = [p for p in self.placements if abs(p['y'] - max_y) <= AUTO_PLACE_ROW_TOL_PX]
        px_per_mm = self.px_per_mm()
        _minx, _miny, w_mm, _h_mm = variant_bbox(self.variant)
        half_span_px = w_mm * px_per_mm / 2

        def x_center(p):
            return p['x'] + half_span_px

        bbox = self._get_outline_bbox_px()
        if bbox is not None:
            target_x = (bbox[0] + bbox[2]) / 2
        else:
            target_x = sum(x_center(p) for p in bottom_row) / len(bottom_row)
        return min(bottom_row, key=lambda p: abs(x_center(p) - target_x))

    def _auto_connect_chain(self):
        """Berechnet eine Verbindungsreihenfolge (chain_order) per gieriger
        Naechster-Nachbar-Heuristik: startet bei der Platzierung, an die der
        Eingangs-Knoten angeschlossen wird (unterste Reihe, horizontal am
        naechsten zur Gebaeudemitte -- siehe _find_bottom_center_placement,
        _get_input_node_pos), haengt danach immer die (nach DIN-Position)
        naechstgelegene noch unverbundene Platzierung an das DOUT der
        zuletzt angehaengten an. Minimiert dadurch JEDEN einzelnen
        Kabelabschnitt -- der beste Weg, um moeglichst keine Verbindung ueber
        MAX_CONNECTION_MM zu ziehen (garantiert es aber nicht, falls
        Platzierungen schlicht zu weit auseinander liegen -- das faellt dann
        weiterhin im Ketten-Tab als rote Verbindung auf, siehe
        _render_chain_cv). Der fest verankerte Start (statt z.B. eines frei
        waehlbaren zweiten Kettenendes) stellt sicher, dass der Eingangs-
        Knoten immer an chain_order[0] angeschlossen bleibt."""
        variant = self.variant
        if not variant or not self.placements:
            self.chain_order = []
            return
        px_per_mm = self.px_per_mm()
        start = self._find_bottom_center_placement()
        remaining = [p for p in self.placements if p is not start]
        order = [start]
        while remaining:
            _, prev_dout = connector_positions(
                variant, order[-1]['x'], order[-1]['y'], px_per_mm, order[-1].get('flipped', False))
            best_i, best_d = 0, None
            for i, p in enumerate(remaining):
                din, _ = connector_positions(variant, p['x'], p['y'], px_per_mm, p.get('flipped', False))
                d = (din[0] - prev_dout[0]) ** 2 + (din[1] - prev_dout[1]) ** 2
                if best_d is None or d < best_d:
                    best_d, best_i = d, i
            order.append(remaining.pop(best_i))
        self.chain_order = [p['id'] for p in order]

    def _auto_assign(self):
        """LED-Zuordnung automatisch berechnen:
        - eine LED gehoert zu dem Fenster, dessen Rechteck (inkl. kleiner
          Toleranz an den Kanten) sie beruehrt;
        - beruehren mehrere (nicht manuell gesetzte) LEDs dasselbe Fenster und
          ihre Spannweite ist >= LONG_RUN_MM, bleiben ALLE aktiv (langes
          Fenster/Reihe -- eine einzelne mittige Lampe wuerde es nicht
          ausreichend ausleuchten). Sonst bleibt nur die am naechsten zur
          Fenstermitte aktiv, die uebrigen werden deaktiviert;
        - LEDs, die kein Fenster beruehren, werden deaktiviert;
        - LEDs mit 'manual'=True (vom Nutzer per Rechtsklick/Werkzeug fest
          an/aus geschaltet ODER im Ketten-Tab manuell einem Fenster
          zugeordnet) werden hier NICHT angefasst -- weder ihr 'enabled' noch
          ihr 'windowIndex' wird geometrisch neu berechnet -- und nehmen auch
          nicht an der Ein-Lampe-pro-Fenster-Konkurrenz teil."""
        px_per_mm = self.px_per_mm()
        # Kandidaten sammeln: fensterindex -> Liste von (abstand_zur_mitte, x_px, placement, led_idx)
        per_window: dict = {}
        for p in self.placements:
            pts = self._placement_points(p)
            for led in p['leds']:
                if not led.get('manual'):
                    led['enabled'] = False
                    led['windowIndex'] = None
            if pts is None:
                continue
            for li, (px, py) in enumerate(pts):
                led = p['leds'][li]
                if led.get('manual'):
                    # manuell gesetzte Fensterzuordnung (z.B. per LEDs-
                    # gruppieren-Werkzeug) bleibt unangetastet -- NICHT
                    # geometrisch ueberschreiben.
                    wi = led.get('windowIndex')
                    if wi is not None and not (0 <= wi < len(self.windows)):
                        wi = None
                        led['windowIndex'] = None
                else:
                    wi = self._nearest_touching_window(px, py)
                    led['windowIndex'] = wi
                if wi is None:
                    continue
                w = self.windows[wi]
                cx = w['x'] + w['w'] / 2
                cy = w['y'] + w['h'] / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                per_window.setdefault(wi, []).append((d, px, p, li))

        for wi, cands in per_window.items():
            auto_cands = [c for c in cands if not c[2]['leds'][c[3]].get('manual')]
            if not auto_cands:
                continue
            xs = [c[1] for c in auto_cands]
            span_mm = (max(xs) - min(xs)) / px_per_mm
            if span_mm >= LONG_RUN_MM:
                for _, _, p, li in auto_cands:
                    p['leds'][li]['enabled'] = True
            else:
                auto_cands.sort(key=lambda t: t[0])
                _, _, p, li = auto_cands[0]   # die LED am naechsten zur Fenstermitte
                p['leds'][li]['enabled'] = True

        self._recompute_chain()
        # Tab 3 (falls schon gebaut) mit der neu berechneten Nummerierung
        # aktualisieren -- so bleibt er nach JEDER Aenderung in Tab 2
        # (Platzierung, Loeschen, Verschieben, DPI, Variante ...) synchron,
        # ohne dass jede einzelne Aufrufstelle daran denken muss.
        self._render_chain_tab()

    def _preview_enabled(self, pts: list) -> list:
        """Simuliert An/Aus fuer eine noch nicht platzierte LED-Reihe (Hover-
        Vorschau vor dem Klick), unter Beruecksichtigung der Konkurrenz mit
        bereits platzierten (nicht manuellen) LEDs am selben Fenster --
        dieselbe Regel wie _auto_assign (mittigste LED aktiv, ausser bei einer
        Spannweite >= LONG_RUN_MM: dort alle beruehrenden LEDs aktiv)."""
        px_per_mm = self.px_per_mm()
        per_window: dict = {}

        def add(px, py, wi, kind, i):
            w = self.windows[wi]
            cx = w['x'] + w['w'] / 2
            cy = w['y'] + w['h'] / 2
            d = (px - cx) ** 2 + (py - cy) ** 2
            per_window.setdefault(wi, []).append((d, px, kind, i))

        for p in self.placements:
            real_pts = self._placement_points(p)
            if real_pts is None:
                continue
            for li, (px, py) in enumerate(real_pts):
                if p['leds'][li].get('manual'):
                    continue
                wi = self._nearest_touching_window(px, py)
                if wi is not None:
                    add(px, py, wi, 'real', None)

        for i, (px, py) in enumerate(pts):
            wi = self._nearest_touching_window(px, py)
            if wi is not None:
                add(px, py, wi, 'hover', i)

        hover_enabled = [False] * len(pts)
        for wi, cands in per_window.items():
            xs = [c[1] for c in cands]
            span_mm = (max(xs) - min(xs)) / px_per_mm
            if span_mm >= LONG_RUN_MM:
                for _, _, kind, i in cands:
                    if kind == 'hover':
                        hover_enabled[i] = True
            else:
                cands.sort(key=lambda t: t[0])
                _, _, kind, i = cands[0]
                if kind == 'hover':
                    hover_enabled[i] = True
        return hover_enabled

    # ── LED-Kette (Verbindungsreihenfolge + globale Nummerierung) ────────────

    def _ordered_placements(self) -> list:
        """Alle Platzierungen in der Reihenfolge, in der sie verkettet/nummeriert
        werden: zuerst die explizit verbundenen (self.chain_order), danach die
        restlichen (noch nicht verbundenen) von links nach rechts (nach x)."""
        by_id = {p['id']: p for p in self.placements}
        chained = [by_id[pid] for pid in self.chain_order if pid in by_id]
        chained_ids = {p['id'] for p in chained}
        remaining = sorted((p for p in self.placements if p['id'] not in chained_ids),
                          key=lambda p: p['x'])
        return chained + remaining

    @staticmethod
    def _local_order(p: dict) -> list:
        """Reihenfolge der lokalen LED-Indizes einer Platzierung in Signalfluss-
        Richtung: 0..n-1 normal, n-1..0 wenn gespiegelt (numeriert rechts nach
        links). Wird sowohl fuer die Nummerierung als auch fuer die Richtungs-
        Pfeile beim Zeichnen verwendet."""
        n = len(p['leds'])
        return list(range(n - 1, -1, -1)) if p.get('flipped') else list(range(n))

    def _lamp_icon(self, radius: int, enabled: bool, selected: bool = False,
                   opacity: float = 1.0) -> ImageTk.PhotoImage:
        """Rendert (und cacht) ein kleines Lampen-Symbol mit weichem Schein statt
        eines flachen Kreises -- deutlich sichtbar, ob eine LED aktiv ist.
        opacity < 1.0 wird fuer die Hover-Vorschau einer noch nicht platzierten
        LED-Reihe verwendet (zeigt schon vorab an/aus, sieht aber sichtbar
        anders aus als eine tatsaechlich platzierte LED)."""
        radius = max(3, int(round(radius)))
        key = (radius, enabled, selected, opacity)
        icon = self._lamp_icon_cache.get(key)
        if icon is not None:
            return icon

        size = radius * 4 + 6
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx = cy = size / 2

        if enabled:
            core = (251, 191, 36)     # warmes Gelb (C['amber']) -- wirkt wie eine leuchtende Lampe
            for rr in range(radius * 2, radius, -1):
                alpha = int(100 * (radius * 2 - rr) / max(1, radius) * opacity)
                draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=core + (alpha,))
            outline = (96, 165, 250, int(255 * opacity)) if selected else (255, 255, 255, int(255 * opacity))
        else:
            core = (107, 114, 128)    # gedimmtes Grau, kein Schein -- unbeleuchtete Lampe
            outline = (96, 165, 250, int(255 * opacity)) if selected else (156, 163, 175, int(255 * opacity))

        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     fill=core + (int(255 * opacity),), outline=outline, width=2 if selected else 1)

        icon = ImageTk.PhotoImage(img)
        self._lamp_icon_cache[key] = icon
        return icon

    def _render_windows(self, cv: tk.Canvas, i2s):
        """Zeichnet alle Fensterrahmen (gelb). Ein Fenster mit zugeordneter,
        aktiver LED ('ledIndex' gesetzt) wird zusaetzlich warm gefuellt --
        sieht dann 'erleuchtet' aus, unbeleuchtete Fenster bleiben nur Umriss."""
        for w in self.windows:
            x1, y1 = i2s(w['x'], w['y'])
            x2, y2 = i2s(w['x'] + w['w'], w['y'] + w['h'])
            if w.get('ledIndex') is not None:
                cv.create_rectangle(x1, y1, x2, y2, fill='#fde68a', stipple='gray25',
                                    outline='#fbbf24', width=2)
            else:
                cv.create_rectangle(x1, y1, x2, y2, outline='#eab308', width=1)

    def _draw_light_cone(self, cv: tk.Canvas, i2s, led_screen_pt: tuple, w: dict):
        """Weicher, nach unten breiter werdender Lichtkegel von einer aktiven LED
        bis zu ihrem zugeordneten (erleuchteten) Fenster."""
        lx, ly = led_screen_pt
        x1, y1 = i2s(w['x'], w['y'])
        x2, y2 = i2s(w['x'] + w['w'], w['y'] + w['h'])
        apex_hw = 3
        cv.create_polygon(lx - apex_hw, ly, lx + apex_hw, ly, x2, y2, x1, y2,
                         fill='#fde68a', stipple='gray12', outline='')

    def _draw_one_connector_box(self, cv: tk.Canvas, i2s, cx_img: float, cy_img: float,
                                px_per_mm: float, label: str, preview: bool):
        half_w_img = CONNECTOR_W_MM * px_per_mm / 2
        half_h_img = CONNECTOR_H_MM * px_per_mm / 2
        x1, y1 = i2s(cx_img - half_w_img, cy_img - half_h_img)
        x2, y2 = i2s(cx_img + half_w_img, cy_img + half_h_img)
        if preview:
            cv.create_rectangle(x1, y1, x2, y2, fill='#000000', stipple='gray50',
                                outline=C['muted'], width=1, dash=(2, 2))
        else:
            cv.create_rectangle(x1, y1, x2, y2, fill='#000000', outline='#f8fafc', width=1)
            cv.create_text((x1 + x2) / 2, min(y1, y2) - 7, text=label, fill=C['muted'],
                           font=('Segoe UI', 7, 'bold'))
        return i2s(cx_img, cy_img)

    def _draw_connector(self, cv: tk.Canvas, i2s, p: dict, variant: dict, preview: bool = False):
        """Zeichnet die beiden Kabelverbinder-Marker (schwarze, massstabsgetreue
        CONNECTOR_W_MM x CONNECTOR_H_MM Kaesten) einer Platzierung an ihrer
        tatsaechlichen Bild-Position -- gleiche Groesse/Farbe wie im Varianten-
        Designer: DIN am mm-Ursprung (0,0), DOUT kurz hinter der letzten LED.
        Damit ist auf dem Foto sofort sichtbar, wo/wie herum das Kabel an jede
        physische Platine an- (DIN) bzw. weitergeschlossen wird (DOUT).
        preview=True (Hover-Schattenvorschau vor dem Platzieren) zeichnet sie
        gerastert/gedaempft statt voll deckend. Gibt (din_pt, dout_pt) als
        Bildschirm-Positionen zurueck (fuer die Ketten-Verbindungslinien --
        das Kabel laeuft von DOUT zu DIN der naechsten Platine, nicht DIN zu
        DIN, sonst zickzackt die Linie bei gespiegelten Platzierungen)."""
        px_per_mm = self.px_per_mm()
        din_img, dout_img = connector_positions(
            variant, p['x'], p['y'], px_per_mm, p.get('flipped', False))
        din_pt = self._draw_one_connector_box(cv, i2s, *din_img, px_per_mm, 'IN', preview)
        dout_pt = self._draw_one_connector_box(cv, i2s, *dout_img, px_per_mm, 'OUT', preview)
        return din_pt, dout_pt

    def _draw_footprint(self, cv: tk.Canvas, i2s, p: dict, variant: dict,
                        preview: bool = False, highlight: bool = False):
        """Zeichnet die (generierte, siehe windowMarker/footprintScale.py)
        Footprint-Kontur an der tatsaechlichen Bild-Position einer
        Platzierung -- mittig ueber der LED-Ausdehnung (siehe
        _footprint_anchor), damit sichtbar ist, wo die physische Platine
        wirklich hinragt (nicht nur die einzelnen LED-Punkte). Footprint und
        LEDs haengen STARR zusammen (fester Anker aus der Varianten-Vorlage,
        siehe footprint_image_points) -- die ganze Platzierung bewegt sich
        beim Ziehen als EIN Stueck, unabhaengig davon, welche Fenster sie
        gerade tatsaechlich beleuchtet. Welche Footprint-Groesse, ist PRO
        PLATZIERUNG eintragbar (`p['width_mm']`/`p['height_mm']`, siehe
        _add_card) -- fehlt sie, gilt der Default der Variante (siehe
        resolve_footprint_size). preview=True (Hover-Schattenvorschau)
        zeichnet sie gedaempft/gestrichelt statt als durchgezogene rote
        Linie. highlight=True (siehe self.height_highlight_mm/
        _render_height_panel) zeichnet sie stattdessen dick und gelb --
        Vorrang vor der roten Normalfarbe, damit auf einen Blick sichtbar
        ist, welche Platzierungen die im Hoehen-Overlay ausgewaehlte Hoehe
        haben."""
        poly_points = footprint_image_points(
            variant, p['x'], p['y'], self.px_per_mm(), p.get('flipped', False), placement=p)
        if preview:
            color = C['dim']
        elif highlight:
            color = C['amber']
        else:
            color = C['red']
        draw_footprint_polylines(cv, i2s, poly_points, color=color, width=3 if highlight else 1,
                                 dash=(2, 2) if preview else None)

    def _render_windows_and_cones(self, cv: tk.Canvas, i2s, pts_by_id: dict):
        """Zeichnet zuerst alle Fenster (erleuchtet/nicht), dann die Lichtkegel
        aktiver LEDs darueber -- muss VOR den Lampen-Symbolen aufgerufen werden,
        damit die Kegel nicht ueber den Lampen liegen."""
        if not self.show_wins.get():
            return
        self._render_windows(cv, i2s)
        for p in self.placements:
            pts = pts_by_id.get(p['id'])
            if pts is None:
                continue
            spts = [i2s(px, py) for px, py in pts]
            for li, sxsy in enumerate(spts):
                led = p['leds'][li]
                wi = led.get('windowIndex')
                if led['enabled'] and wi is not None and 0 <= wi < len(self.windows):
                    self._draw_light_cone(cv, i2s, sxsy, self.windows[wi])

    def _draw_chain_links(self, cv: tk.Canvas, i2s, spts: list, flipped: bool,
                          color: str, width: int):
        """Zeichnet die Verbindungslinien zwischen den LEDs EINER Platzierung als
        einzelne Pfeile in Signalfluss-Richtung (zeigt die 'Richtung' der Kette;
        bei gespiegelten Platzierungen zeigen die Pfeile folgerichtig rueckwaerts)."""
        order = self._local_order({'leds': [None] * len(spts), 'flipped': flipped})
        for a, b in zip(order, order[1:]):
            x1, y1 = spts[a]
            x2, y2 = spts[b]
            cv.create_line(x1, y1, x2, y2, fill=color, width=width,
                          arrow=tk.LAST, arrowshape=(8, 10, 3))

    def _ensure_full_chain_order(self):
        """Macht die aktuell wirksame Reihenfolge explizit (fuer eindeutige
        Auf/Ab-Verschiebung in der Ketten-Liste)."""
        self.chain_order = [p['id'] for p in self._ordered_placements()]

    def _recompute_chain(self):
        """Nummeriert alle LEDs global durch (0..N-1) in Verbindungsreihenfolge;
        innerhalb einer Platzierung von links nach rechts (Variante-Reihenfolge),
        bei gespiegelten Platzierungen von rechts nach links. `chainIndex` ist
        die PHYSISCHE Position auf der Datenleitung -- jede LED bekommt einen
        eigenen, nie uebersprungenen Wert, da jede physische LED weiterhin
        einen eigenen Slot im Datenprotokoll belegt.

        `pixelIndex` ist dagegen die LOGISCHE Nummerierung: beruehren mehrere
        LEDs dasselbe Fenster (siehe LONG_RUN_MM in _auto_assign), gelten sie
        als EIN logisches Pixel (gleiche Farbe/Zustand) und teilen sich
        denselben pixelIndex -- der Zaehler wird fuer sie NICHT weitergezaehlt
        (uebersprungen), statt wie bisher jeder beteiligten LED einen eigenen
        Index zuzuteilen und die Kombination separat nachzutragen. Deaktivierte
        LEDs bzw. LEDs ohne Fenster bekommen pixelIndex=None.

        `self.data_chain` fasst das Ergebnis als geordnete Liste zusammen (ein
        Eintrag pro logischem Pixel, in Reihenfolge ab Daten-Eingang): jeder
        Eintrag ist IMMER ein "<from>-<to>"-String mit dem physischen
        chainIndex-Bereich der an diesem Pixel beteiligten LED(s) -- auch bei
        nur einer einzelnen LED (z.B. "23-23"), fuer ein einheitliches Format."""
        for w in self.windows:
            w.pop('ledIndex', None)
            w.pop('pixelIndex', None)

        global_idx = 0
        pixel_idx = 0
        disabled = []
        window_to_pixel: dict = {}  # fensterindex -> bereits vergebener pixelIndex
        pixel_chain_indices: list = []  # pixel_idx -> [chainIndex, ...] (in Vergabereihenfolge)
        for p in self._ordered_placements():
            n = len(p['leds'])
            order = range(n - 1, -1, -1) if p.get('flipped') else range(n)
            for local_i in order:
                led = p['leds'][local_i]
                led['chainIndex'] = global_idx
                wi = led.get('windowIndex')
                if led['enabled'] and wi is not None and 0 <= wi < len(self.windows):
                    self.windows[wi]['ledIndex'] = global_idx
                    if wi in window_to_pixel:
                        pi = window_to_pixel[wi]   # beruehrt dasselbe Fenster -> teilt sich den Pixel
                    else:
                        pi = pixel_idx
                        window_to_pixel[wi] = pi
                        pixel_chain_indices.append([])
                        pixel_idx += 1
                    led['pixelIndex'] = pi
                    pixel_chain_indices[pi].append(global_idx)
                    self.windows[wi]['pixelIndex'] = pi
                else:
                    led['pixelIndex'] = None
                    disabled.append(global_idx)
                global_idx += 1

        self.disabled_leds = disabled
        self.total_led_count = global_idx
        self.total_pixel_count = pixel_idx
        self.data_chain = [f'{min(idxs)}-{max(idxs)}' for idxs in pixel_chain_indices]

    def _reset_chain(self):
        self.chain_order = []
        self._auto_assign()
        self._render_chain_tab()
        self._schedule_save()

    def _move_in_chain(self, placement_id: str, direction: int):
        self._ensure_full_chain_order()
        idx = self.chain_order.index(placement_id)
        j = idx + direction
        if 0 <= j < len(self.chain_order):
            self.chain_order[idx], self.chain_order[j] = self.chain_order[j], self.chain_order[idx]
            self._auto_assign()
            self._render_chain_tab()
            self._schedule_save()

    def _remove_from_chain(self, placement_id: str):
        if placement_id in self.chain_order:
            self.chain_order.remove(placement_id)
            self._auto_assign()
            self._render_chain_tab()
            self._schedule_save()

    def _add_to_chain(self, placement_id: str):
        if placement_id not in self.chain_order:
            self.chain_order.append(placement_id)
            self._auto_assign()
            self._render_chain_tab()
            self._schedule_save()

    def _render_cv(self):
        self.cv.delete('all')
        W = self.cv.winfo_width() or 800
        H = self.cv.winfo_height() or 600

        if not self.img_orig:
            self.cv.create_text(W // 2, H // 2,
                text='Bild aus der Liste links auswählen',
                fill=C['dim'], font=('Segoe UI', 12), justify='center')
            return

        if self._display_img is None:
            self._update_display_img()
            return
        if self._cache_zoom != self.zoom:
            iw = max(1, int(self._display_img.width * self.zoom))
            ih = max(1, int(self._display_img.height * self.zoom))
            method = Image.LANCZOS if self.zoom < 1 else Image.NEAREST
            self._cache_tk = ImageTk.PhotoImage(
                self._display_img.resize((iw, ih), method, reducing_gap=2.0))
            self._cache_zoom = self.zoom

        self.cv.create_image(int(self.off_x), int(self.off_y), image=self._cache_tk, anchor='nw')

        self._draw_frame_rect(self.cv, self._i2s)

        # Fenster (gelb, nur die Fenster -- NICHT die Glasscheiben) + Lichtkegel
        # aktiver LEDs: muss VOR den Verbindungslinien/Lampen gezeichnet werden,
        # damit die Lampen-Symbole oben auf den Kegeln sitzen statt darunter.
        pts_by_id = {p['id']: self._placement_points(p) for p in self.placements}
        self._render_windows_and_cones(self.cv, self._i2s, pts_by_id)

        # Platzierte Batches: Signalfluss-Pfeile (zeigen die Richtung/Reihenfolge)
        # + Lampen-Symbole (gelb leuchtend = aktiv, grau = deaktiviert/unbeleuchtet)
        for i, p in enumerate(self.placements):
            sel = (i in self.sel_idxs)
            pts = pts_by_id[p['id']]
            if pts is None:
                sx, sy = self._i2s(p['x'], p['y'])
                self.cv.create_text(sx, sy, text='⚠ Variante fehlt',
                                    fill=C['red'], font=('Segoe UI', 9, 'bold'))
                continue
            spts = [self._i2s(px, py) for px, py in pts]
            if len(spts) > 1:
                self._draw_chain_links(self.cv, self._i2s, spts, p.get('flipped', False),
                                       color='#60a5fa' if sel else C['blue_dim'],
                                       width=2 if sel else 1)
            variant_p = self.variant
            if variant_p:
                highlight = (self.height_highlight_mm is not None and
                            abs(resolve_footprint_size(variant_p, p)[1] - self.height_highlight_mm) < 1e-6)
                self._draw_footprint(self.cv, self._i2s, p, variant_p, highlight=highlight)
                self._draw_connector(self.cv, self._i2s, p, variant_p)
            r = (5 if self.zoom >= 0.6 else 3)
            for li, (sx, sy) in enumerate(spts):
                enabled = p['leds'][li]['enabled']
                icon = self._lamp_icon(r, enabled, selected=sel)
                self.cv.create_image(sx, sy, image=icon)
            sx0, sy0 = spts[0]
            self.cv.create_text(sx0 + 3, sy0 - 14, text=f'#{i + 1}',
                fill='#bfdbfe' if sel else '#93c5fd', anchor='nw',
                font=('Segoe UI', max(7, min(int(10 * self.zoom), 14)), 'bold'))

        # Platzierungs-Vorschau: halbtransparenter "Schatten" der Variante am
        # Mauszeiger -- zeigt schon vorab (gelb/grau, gedimmt), welche LEDs an
        # dieser Position an- bzw. ausgeschaltet waeren, sowie den (gerastert
        # gezeichneten) Kabelverbinder an dieser Position.
        variant = self.variant
        if self._hover and variant and not self._move_ref and not self._pan_ref:
            ax, ay = self._hover
            pts = led_image_positions(variant, ax, ay, self.px_per_mm(), self.place_flipped.get())
            spts = [self._i2s(px, py) for px, py in pts]
            if len(spts) > 1:
                flat = [c for pt in spts for c in pt]
                self.cv.create_line(*flat, fill=C['dim'], width=1, dash=(2, 3))
            next_size = self._next_footprint_size()
            hover_p = {'x': ax, 'y': ay, 'flipped': self.place_flipped.get()}
            if next_size:
                hover_p['width_mm'], hover_p['height_mm'] = next_size
            self._draw_footprint(self.cv, self._i2s, hover_p, variant, preview=True)
            self._draw_connector(self.cv, self._i2s, hover_p, variant, preview=True)
            r = 5 if self.zoom >= 0.6 else 3
            preview_enabled = self._preview_enabled(pts)
            for (sx, sy), en in zip(spts, preview_enabled):
                icon = self._lamp_icon(r, en, opacity=0.55)
                self.cv.create_image(sx, sy, image=icon)

        self._draw_measure(self.cv, self._i2s)
        self._draw_scale_drag(self.cv, self._i2s)

    def _draw_frame_rect(self, cv: tk.Canvas, i2s):
        """Zeichnet das Rahmen-Rechteck (self.frame_rect_px) als DOPPELLINIE
        in Gruen -- die gezogene Kante selbst PLUS eine zweite, um
        footprintScale.FRAME_MATERIAL_THICKNESS_MM (3mm) nach aussen versetzte
        Linie, wie in technischen Zeichnungen ueblich fuer eine Material-/
        Wandstaerke (das ist die Kontur-Platte, gegen die die Rahmenleisten
        stossen). Eigene Kanten links/rechts/oben/unten sind per Ziehen
        unabhaengig verschiebbar (siehe _hit_frame_edge/_cv_dn/_cv_mv, wirkt
        weiterhin nur auf die INNERE Linie = self.frame_rect_px). Legt fest,
        wo die 4 Rahmenleisten (footprintScale.get_frame_side_points/
        get_frame_top_points) sitzen und wo die echte Haus-Kontur beim Export
        links/rechts/unten gerade abgeschnitten wird (oben bleibt sie
        unveraendert, siehe dxfExport.clip_outline_to_frame). Zeichnet
        ZUSAETZLICH in ORANGE jedes Zungen-Loch (siehe dxfExport.
        frame_side_hole_rects_mm/footprintScale.FRAME_HOLE_DEPTH_MM, 3.1mm x
        FRAME_TONGUE_WIDTH_MM=10mm), das der Export in die Hauskontur
        schneiden wuerde -- dieselbe Rechnung wie beim echten Export, nur ueber
        px_per_mm zurueck in Bild-px umgerechnet, damit man VOR dem Export
        sieht, wo genau die Rahmenleisten-Zungen die Kontur durchstossen."""
        if self.frame_rect_px is None:
            return
        left, top, right, bottom = self.frame_rect_px
        x0, y0 = i2s(left, top)
        x1, y1 = i2s(right, bottom)
        cv.create_rectangle(x0, y0, x1, y1, outline=C['green'], width=2, dash=(4, 3))

        if dxfExport is None or footprintScale is None:
            return
        px_per_mm = self.px_per_mm()
        thickness_img_px = footprintScale.FRAME_MATERIAL_THICKNESS_MM * px_per_mm
        ox0, oy0 = i2s(left - thickness_img_px, top - thickness_img_px)
        ox1, oy1 = i2s(right + thickness_img_px, bottom + thickness_img_px)
        cv.create_rectangle(ox0, oy0, ox1, oy1, outline=C['green'], width=2, dash=(4, 3))

        frame_rect_mm = (left / px_per_mm, top / px_per_mm, right / px_per_mm, bottom / px_per_mm)
        for hx, hy, hw, hh in dxfExport.frame_side_hole_rects_mm(frame_rect_mm):
            hp0 = i2s(hx * px_per_mm, hy * px_per_mm)
            hp1 = i2s((hx + hw) * px_per_mm, (hy + hh) * px_per_mm)
            cv.create_rectangle(*hp0, *hp1, outline=C['orange'], fill=C['orange'])

    def _draw_dragline(self, cv: tk.Canvas, i2s, pts: list, label: str, color: str):
        """Gemeinsame Zeichenroutine fuer Mess-/Kalibrier-Ziehlinien: eine
        Linie zwischen zwei Bild-Punkten, Endpunkt-Markierungen, und eine
        Beschriftung mit hellem Hintergrund an der Mitte (Tk-Canvas-Text hat
        keine eingebaute Kontur/Hintergrundfarbe, ohne die waere die Zahl auf
        dunklem Bildhintergrund schwer lesbar). Nichts zu zeichnen, solange
        kein zweiter Punkt gesetzt ist (reiner Klick ohne Ziehen)."""
        if len(pts) != 2:
            return
        (ix1, iy1), (ix2, iy2) = pts
        x1, y1 = i2s(ix1, iy1)
        x2, y2 = i2s(ix2, iy2)
        cv.create_line(x1, y1, x2, y2, fill=color, width=2, dash=(5, 3))
        for x, y in ((x1, y1), (x2, y2)):
            cv.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline='white')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        cv.create_text(mx, my - 12, text=label, fill=C['bg_dark'],
                       font=('Segoe UI', 10, 'bold'), anchor='s',
                       tags='dragline_label_bg')
        bbox = cv.bbox('dragline_label_bg')
        if bbox:
            cv.tag_lower(
                cv.create_rectangle(bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2,
                                    fill=color, outline=''),
                'dragline_label_bg')

    def _draw_measure(self, cv: tk.Canvas, i2s):
        """Zeichnet das aktuelle Massband (siehe tool_measure/_cv_dn/_cv_mv)
        mit einer Abstands-Beschriftung in echten mm (ueber px_per_mm)."""
        if len(self._measure_pts) != 2:
            return
        (ix1, iy1), (ix2, iy2) = self._measure_pts
        dist_mm = ((ix2 - ix1) ** 2 + (iy2 - iy1) ** 2) ** 0.5 / self.px_per_mm()
        self._draw_dragline(cv, i2s, self._measure_pts, f'{dist_mm:.1f} mm', C['green'])

    def _draw_scale_drag(self, cv: tk.Canvas, i2s):
        """Zeichnet die aktuelle Kalibrierlinie (siehe tool_scale/_cv_dn/
        _cv_mv) waehrend des Ziehens -- beschriftet mit der gemessenen
        PIXEL-Distanz (die echte mm-Distanz ist ja noch unbekannt, wird erst
        beim Loslassen per Dialog abgefragt, siehe _finish_scale_drag)."""
        if len(self._scale_pts) != 2:
            return
        (ix1, iy1), (ix2, iy2) = self._scale_pts
        dist_px = ((ix2 - ix1) ** 2 + (iy2 - iy1) ** 2) ** 0.5
        self._draw_dragline(cv, i2s, self._scale_pts, f'{dist_px:.0f} px', C['blue'])

    # ── Maus: Canvas ────────────────────────────────────────────────────────

    def _footprint_screen_bbox(self, p: dict):
        """(left, top, right, bottom) der Footprint-AUSSENKONTUR von
        Platzierung `p` in Bildschirm-px (Canvas-Koordinaten) -- die
        AUSSENKONTUR ist die erste der von footprint_image_points()
        gelieferten Polylinien (siehe footprintScale.get_footprint_points:
        dort zuerst gezeichnet, vor den Pin-Markierungen/der
        Verbinderleiste). None ohne Variante/Footprint-Geometrie."""
        variant = self.variant
        if not variant:
            return None
        poly_points = footprint_image_points(
            variant, p['x'], p['y'], self.px_per_mm(), p.get('flipped', False), placement=p)
        if not poly_points or not poly_points[0][0]:
            return None
        screen_pts = [self._i2s(ix, iy) for ix, iy in poly_points[0][0]]
        xs = [sx for sx, _sy in screen_pts]
        ys = [sy for _sx, sy in screen_pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _footprint_bbox_for_size(self, p: dict, width_mm: float, height_mm: float):
        """(left, top, right, bottom) der Footprint-AUSSENKONTUR von
        Platzierung `p` in Bild-px, WENN sie die gegebene width_mm/height_mm
        haette -- unabhaengig davon, was aktuell in p['width_mm']/['height_mm']
        steht. Fuer die Ueberlappungspruefung beim Resizen (siehe _cv_mv), OHNE
        die Platzierung dafuer schon zu veraendern. None ohne Variante."""
        variant = self.variant
        if not variant:
            return None
        px_per_mm = self.px_per_mm()
        minx, miny, w_mm, _ = variant_bbox(variant)
        ox, oy = _footprint_anchor(variant.get('leds', []), width_mm, height_mm)
        outline = [(0.0, 0.0), (width_mm, 0.0), (width_mm, height_mm), (0.0, height_mm)]
        transformed = _footprint_geometry_image(
            [(outline, True)], ox, oy, minx, miny, w_mm, p['x'], p['y'], px_per_mm,
            p.get('flipped', False))
        pts = transformed[0][0]
        xs = [x for x, _y in pts]
        ys = [y for _x, y in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _bbox_overlap(a: tuple, b: tuple) -> bool:
        """True, wenn sich zwei achsenparallele Bounding-Boxen (left, top,
        right, bottom) ECHT ueberschneiden (nur beruehrende Kanten zaehlen
        NICHT als Ueberlappung)."""
        al, at, ar, ab = a
        bl, bt, br, bb = b
        return al < br and bl < ar and at < bb and bt < ab

    def _hit_footprint_edge(self, e):
        """(edge, placement_index) fuer die OBERSTE Platzierung, deren
        Footprint-Kante der Cursor trifft ('left'/'right'/'bottom', Toleranz
        FOOTPRINT_RESIZE_TOL_PX, siehe _footprint_screen_bbox) -- durchsucht
        ALLE Platzierungen, nicht nur die ausgewaehlte, weil ein Ziehen an
        JEDER Footprint-Kante ALLE Platzierungen gemeinsam resized (siehe
        _cv_dn/_cv_mv) -- man muss dafuer also keine bestimmte Platzierung
        erst auswaehlen. (None, -1), wenn keine Kante getroffen wurde. KEINE
        'top'-Kante: die Footprint-Oberkante ist fest an footprintScale.
        LED_OFFSET_TOP_MM unterhalb der LED-Reihe verankert (siehe
        _footprint_anchor), sie folgt nicht height_mm und laesst sich daher
        nicht sinnvoll durch Ziehen verschieben."""
        tol = FOOTPRINT_RESIZE_TOL_PX
        x, y = e.x, e.y
        for pi in range(len(self.placements) - 1, -1, -1):
            bbox = self._footprint_screen_bbox(self.placements[pi])
            if bbox is None:
                continue
            left, top, right, bottom = bbox
            if top - tol <= y <= bottom + tol:
                if abs(x - left) <= tol:
                    return 'left', pi
                if abs(x - right) <= tol:
                    return 'right', pi
            if left - tol <= x <= right + tol and abs(y - bottom) <= tol:
                return 'bottom', pi
        return None, -1

    def _hit_frame_edge(self, e):
        """Welche Kante ('left'/'right'/'top'/'bottom') des Rahmen-Rechtecks
        (self.frame_rect_px) der Cursor trifft (Toleranz FRAME_RESIZE_TOL_PX),
        sonst None. Analog zu _hit_footprint_edge, aber fuer GENAU EIN
        Rechteck mit VIER (statt drei) unabhaengig ziehbaren Kanten -- siehe
        _cv_dn/_cv_mv."""
        if self.frame_rect_px is None:
            return None
        tol = FRAME_RESIZE_TOL_PX
        left, top, right, bottom = self.frame_rect_px
        sl, st = self._i2s(left, top)
        sr, sb = self._i2s(right, bottom)
        x, y = e.x, e.y
        if st - tol <= y <= sb + tol:
            if abs(x - sl) <= tol:
                return 'left'
            if abs(x - sr) <= tol:
                return 'right'
        if sl - tol <= x <= sr + tol:
            if abs(y - st) <= tol:
                return 'top'
            if abs(y - sb) <= tol:
                return 'bottom'
        return None

    def _apply_size_to_selection(self):
        """Setzt width_mm/height_mm ALLER aktuell ausgewaehlten Platzierungen
        (sel_idxs, siehe _cv_dn's Strg+Klick-Mehrfachauswahl -- ohne
        Mehrfachauswahl nur die primaere self.sel_idx) auf den in den
        Eingabefeldern im schwebenden Werkzeug-Panel eingetragenen Wert.
        Gegenstueck zum Ziehen an einer Footprint-Kante (siehe _cv_mv), das
        dieselbe Groesse ebenfalls auf die ganze Auswahl spiegelt -- hier
        tippt man die Zielgroesse stattdessen einmal ein."""
        targets = self.sel_idxs if self.sel_idxs else (
            {self.sel_idx} if 0 <= self.sel_idx < len(self.placements) else set())
        if not targets:
            self._status('Keine Platzierung ausgewählt', C['amber'])
            return
        try:
            w = float(self.v_sel_footprint_w.get().replace(',', '.'))
            h = float(self.v_sel_footprint_h.get().replace(',', '.'))
            if w <= 0 or h <= 0:
                raise ValueError
        except ValueError:
            self._status('Ungültige Größe', C['red'])
            return
        for ti in targets:
            self.placements[ti]['width_mm'] = w
            self.placements[ti]['height_mm'] = h
        self._render_list_and_save()
        self._status(f'✓ Größe auf {len(targets)} Platzierung(en) angewendet', C['green'])

    def _hit_placement(self, e):
        """Index der Platzierung, deren LED-Punkt unter dem Cursor liegt (oberste
        zuerst), sonst -1."""
        for pi in range(len(self.placements) - 1, -1, -1):
            pts = self._placement_points(self.placements[pi])
            if pts is None:
                continue
            for (ix, iy) in pts:
                sx, sy = self._i2s(ix, iy)
                if (sx - e.x) ** 2 + (sy - e.y) ** 2 <= LED_HIT_R ** 2:
                    return pi
        return -1

    def _footprint_contains_point(self, p: dict, x: float, y: float) -> bool:
        """True, wenn der Bildschirm-Punkt (x, y) innerhalb der Footprint-
        AUSSENKONTUR von Platzierung `p` liegt (einfache Bounding-Box-Pruefung
        reicht -- die Kontur selbst ist ein Rechteck, siehe
        footprintScale.get_footprint_points/_footprint_screen_bbox)."""
        bbox = self._footprint_screen_bbox(p)
        if bbox is None:
            return False
        left, top, right, bottom = bbox
        return left <= x <= right and top <= y <= bottom

    def _hit_placements_at(self, e) -> list:
        """ALLE Platzierungs-Indizes (oberste zuerst), deren LED-Punkt ODER
        Footprint-Flaeche den Cursor trifft (siehe _footprint_contains_point)
        -- ein Klick muss also nicht mehr exakt eine LED treffen, ein Klick
        IRGENDWO auf der gezeichneten Platine waehlt sie ebenfalls aus.
        Liefert MEHRERE Indizes, wenn sich die Footprints mehrerer
        Platzierungen an dieser Stelle ueberlappen -- ein Klick in den
        ueberlappenden Bereich waehlt dann ALLE gemeinsam aus, statt nur die
        oberste (siehe _cv_dn)."""
        hits = []
        for pi in range(len(self.placements) - 1, -1, -1):
            p = self.placements[pi]
            pts = self._placement_points(p)
            hit = pts is not None and any(
                (self._i2s(ix, iy)[0] - e.x) ** 2 + (self._i2s(ix, iy)[1] - e.y) ** 2 <= LED_HIT_R ** 2
                for ix, iy in pts)
            if not hit:
                hit = self._footprint_contains_point(p, e.x, e.y)
            if hit:
                hits.append(pi)
        return hits

    def _hit_led(self, e):
        """(Platzierungs-Index, lokaler LED-Index) der einzelnen LED unter dem
        Cursor (oberste zuerst), sonst (-1, -1)."""
        for pi in range(len(self.placements) - 1, -1, -1):
            pts = self._placement_points(self.placements[pi])
            if pts is None:
                continue
            for li, (ix, iy) in enumerate(pts):
                sx, sy = self._i2s(ix, iy)
                if (sx - e.x) ** 2 + (sy - e.y) ** 2 <= LED_HIT_R ** 2:
                    return pi, li
        return -1, -1

    def _cv_right_click(self, e):
        """Rechtsklick auf eine einzelne LED: an/aus manuell fest umschalten
        (uebersteuert die automatische Zuordnung dauerhaft, bis wieder auf
        automatisch zurueckgesetzt). Shift+Rechtsklick setzt sie zurueck auf
        automatisch (_auto_assign berechnet sie dann wieder selbst)."""
        if not self.img_orig:
            return
        pi, li = self._hit_led(e)
        if pi < 0:
            return
        led = self.placements[pi]['leds'][li]
        shift = bool(e.state & 0x0001)
        if shift:
            led.pop('manual', None)
            self._status('LED: wieder automatisch', C['blue'])
        else:
            led['manual'] = True
            led['enabled'] = not led['enabled']
            self._status('LED manuell an' if led['enabled'] else 'LED manuell aus', C['amber'])
        self._auto_assign()
        self._render_placements()
        self._render_cv()
        self._schedule_save()

    def _cv_dn(self, e):
        if not self.img_orig:
            return
        if self._space:
            self._pan_ref = (e.x - self.off_x, e.y - self.off_y)
            self._space_used_for_pan = True  # war Halten+Ziehen -> beim Loslassen NICHT spiegeln
            self.cv.configure(cursor='fleur')
            return

        # Jeder "echte" Klick auf den Canvas (kein Pan) verwirft eine evtl.
        # aktive Hoehen-Hervorhebung (siehe self.height_highlight_mm/
        # _toggle_height_highlight) -- sonst blieb sie "haengen" und liess
        # sich nur durch erneuten Klick auf denselben Eintrag im Hoehen-
        # Overlay wieder aufheben, was Nutzer nicht erwarten (sie klicken
        # normalerweise einfach anderswo hin, um etwas abzuwaehlen).
        if self.height_highlight_mm is not None:
            self.height_highlight_mm = None
            self._render_height_panel()

        # 0z) "Messen"-Werkzeug aktiv: Klick setzt den Startpunkt eines neuen
        #     Massbands -- ein evtl. vorheriges wird dabei verworfen (immer
        #     nur EIN Massband gleichzeitig, wie ein einfaches Lineal).
        if self.tool_measure.get():
            ix, iy = self._s2i(e.x, e.y)
            self._measure_pts = [(ix, iy)]
            self._measuring = True
            self._render_cv()
            return

        # 0y) "Skalieren"-Werkzeug aktiv: Klick setzt den Startpunkt einer
        #     Kalibrierlinie -- beim Loslassen (siehe _cv_up) wird nach der
        #     echten Distanz gefragt und daraus die DPI neu berechnet.
        if self.tool_scale.get():
            ix, iy = self._s2i(e.x, e.y)
            self._scale_pts = [(ix, iy)]
            self._scaling = True
            self._render_cv()
            return

        # 0a) "LED umschalten"-Werkzeug aktiv: Klick auf eine LED schaltet
        #     ihren aktuellen Zustand manuell fest um (an<->aus, uebersteuert
        #     die automatische Zuordnung dauerhaft), statt eine Platzierung
        #     auszuwaehlen/zu verschieben -- ein Klick daneben tut bewusst
        #     nichts (kein versehentliches Verschieben).
        if self.tool_led_toggle.get():
            pi, li = self._hit_led(e)
            if pi >= 0:
                led = self.placements[pi]['leds'][li]
                led['manual'] = True
                led['enabled'] = not led['enabled']
                self._auto_assign()
                self._render_placements()
                self._render_cv()
                self._schedule_save()
            return

        # 0b) "Variante platzieren"-Werkzeug aktiv: Klick setzt IMMER eine neue
        #     Platzierung der gewaehlten Variante an der (ggf. eingerasteten)
        #     Schattenposition -- unabhaengig davon, ob dabei zufaellig eine
        #     bestehende Platzierung getroffen wird (kein Auswaehlen/
        #     Verschieben, solange dieses Werkzeug aktiv ist).
        if self.tool_place.get():
            variant = self.variant
            if not variant:
                messagebox.showinfo('Keine Variante',
                    'Bitte zuerst im Varianten-Designer LEDs anlegen ("Bearbeiten...").')
                return
            ix, iy = self._s2i(e.x, e.y)
            flipped = self.place_flipped.get()
            ax, ay = self._snap_anchor(ix, iy, variant, flipped)
            new_placement = {
                'id': uuid.uuid4().hex[:8],
                'variantId': variant['id'],
                'x': round(ax, 1),
                'y': round(ay, 1),
                'flipped': flipped,
                'leds': [{'index': i, 'enabled': False, 'windowIndex': None}
                         for i in range(len(variant['leds']))],
            }
            # Footprint-Groesse aus den Toolbar-Eingabefeldern oben
            # uebernehmen (siehe _next_footprint_size) -- so lassen sich mit
            # derselben Variante nacheinander Platzierungen mit
            # unterschiedlichen Footprint-Groessen anlegen, ohne jede danach
            # einzeln umstellen zu muessen.
            next_size = self._next_footprint_size()
            if next_size:
                new_placement['width_mm'], new_placement['height_mm'] = next_size
            self.placements.append(new_placement)
            self.sel_idx = len(self.placements) - 1
            self._auto_assign()
            self._render_list_and_save()
            return

        # 0c) Kein Werkzeug aktiv, Strg gedrueckt: Mehrfachauswahl (sel_idxs)
        #     an-/abwaehlen statt zu ziehen -- Strg+Klick auf eine bereits
        #     ausgewaehlte Platzierung nimmt sie aus der Auswahl (self.sel_idx,
        #     die "primaere" Auswahl, ruetscht dann auf ein anderes noch
        #     ausgewaehltes Element oder -1), Strg+Klick auf eine neue fuegt
        #     sie hinzu und macht sie zur primaeren; Strg+Klick daneben laesst
        #     die Auswahl unveraendert (kein versehentliches Abwaehlen).
        #     Ueberlappen sich an dieser Stelle mehrere Footprints (siehe
        #     _hit_placements_at), wird JEDE davon einzeln umgeschaltet.
        if e.state & 0x0004:
            hits = self._hit_placements_at(e)
            if hits:
                for pi in hits:
                    if pi in self.sel_idxs:
                        self.sel_idxs.discard(pi)
                    else:
                        self.sel_idxs.add(pi)
                if self.sel_idx not in self.sel_idxs:
                    self.sel_idx = next(iter(self.sel_idxs), -1)
                self._render_placements()
                self._render_cv()
            return

        # 0d) Kein Werkzeug aktiv, aber Klick auf eine Resize-Kante EINER
        #     Footprint-Kontur (siehe _hit_footprint_edge, egal ob diese
        #     Platzierung ausgewaehlt ist): startet einen Resize-Zug statt
        #     eine Platzierung neu auszuwaehlen/zu verschieben. Der Zug wirkt
        #     auf die aktuelle Mehrfachauswahl (sel_idxs), wenn es eine gibt
        #     -- sonst (keine Auswahl) auf ALLE Platzierungen zusammen, als
        #     schneller Weg, alle auf einmal gleich gross zu machen. Alle
        #     Ziele werden sofort auf die aufgeloeste Groesse der angefassten
        #     Platzierung synchronisiert, _cv_mv haelt sie waehrend des
        #     Ziehens weiter synchron (siehe dort).
        edge, epi = self._hit_footprint_edge(e)
        if edge is not None:
            w0, h0 = resolve_footprint_size(self.variant, self.placements[epi])
            targets = self.sel_idxs if self.sel_idxs else set(range(len(self.placements)))
            for ti in targets:
                self.placements[ti]['width_mm'] = w0
                self.placements[ti]['height_mm'] = h0
            self._resize_ref = (edge, e.x, e.y, w0, h0, epi)
            return

        # 0e) Kein Werkzeug aktiv, keine Footprint-Kante getroffen: Klick auf
        #     eine Kante des Rahmen-Rechtecks (siehe self.frame_rect_px/
        #     _hit_frame_edge) startet dessen Resize-Zug (siehe _cv_mv/_cv_up)
        #     statt eine Platzierung auszuwaehlen/zu verschieben.
        frame_edge = self._hit_frame_edge(e)
        if frame_edge is not None:
            self._frame_resize_ref = (frame_edge, e.x, e.y, self.frame_rect_px)
            return

        # 1) Kein Werkzeug aktiv: bestehende Platzierung treffen (per LED-Punkt
        #    ODER Footprint-Flaeche, siehe _hit_placements_at) -> auswaehlen +
        #    verschieben, sonst Auswahl aufheben (kein Platzieren mehr ohne
        #    aktives "Variante platzieren"-Werkzeug). Ueberlappen sich an
        #    dieser Stelle mehrere Footprints, werden ALLE ausgewaehlt (die
        #    oberste bleibt die "primaere" self.sel_idx, u.a. fuer den
        #    Verschieben-Zug); ein normaler (nicht Strg-)Klick ersetzt die
        #    bisherige Mehrfachauswahl dabei immer komplett.
        hits = self._hit_placements_at(e)
        if hits:
            self.sel_idx = hits[0]
            self.sel_idxs = set(hits)
            p = self.placements[hits[0]]
            ix, iy = self._s2i(e.x, e.y)
            self._move_ref = (ix - p['x'], iy - p['y'])
            self._render_placements()
            self._render_cv()
        else:
            self.sel_idx = -1
            self.sel_idxs = set()
            self._render_placements()
            self._render_cv()

    def _cv_mv(self, e):
        if not self.img_orig:
            return
        if self._pan_ref:
            self.off_x = e.x - self._pan_ref[0]
            self.off_y = e.y - self._pan_ref[1]
            self._render_cv()
            return
        if self._measuring:
            ix, iy = self._s2i(e.x, e.y)
            self._measure_pts = [self._measure_pts[0], (ix, iy)]
            self._render_cv()
            return
        if self._scaling:
            ix, iy = self._s2i(e.x, e.y)
            self._scale_pts = [self._scale_pts[0], (ix, iy)]
            self._render_cv()
            return
        if self._move_ref and 0 <= self.sel_idx < len(self.placements):
            p = self.placements[self.sel_idx]
            variant = self.variant
            ix, iy = self._s2i(e.x, e.y)
            ax, ay = ix - self._move_ref[0], iy - self._move_ref[1]
            if variant:
                ax, ay = self._snap_anchor(ax, ay, variant, p.get('flipped', False))
            p['x'], p['y'] = round(ax, 1), round(ay, 1)
            self._render_cv()
            return
        if self._resize_ref:
            edge, x0, y0, w0, h0, epi = self._resize_ref
            px_per_mm = self.px_per_mm()
            # Nur ganze mm-Schritte, kein Sub-mm-Zittern.
            if edge == 'bottom':
                d_mm = (e.y - y0) / self.zoom / px_per_mm
                new_w, new_h = w0, max(FOOTPRINT_MIN_MM, round(h0 + d_mm))
            else:
                # Links/rechts wachsen SYMMETRISCH um die LED-Mitte (der
                # Footprint ist horizontal ueber den LEDs zentriert, siehe
                # _footprint_anchor) -- daher *2, unabhaengig davon, an
                # welcher der beiden Seiten gezogen wird.
                sign = -1 if edge == 'left' else 1
                d_mm = (e.x - x0) / self.zoom / px_per_mm
                new_w, new_h = max(FOOTPRINT_MIN_MM, round(w0 + 2 * sign * d_mm)), h0
            # Wirkt auf die aktuelle Mehrfachauswahl, wenn es eine gibt --
            # sonst auf ALLE Platzierungen zusammen (siehe _cv_dn).
            has_selection = bool(self.sel_idxs)
            targets = self.sel_idxs if has_selection else set(range(len(self.placements)))

            # Ueberlappungs-Check NUR bei einer ECHTEN Teilauswahl (sonst
            # wachsen ALLE Platzierungen gemeinsam -- dann gibt es keinen
            # unveraenderten "Hintergrund", in den sie hineinwachsen koennten,
            # jede Beruehrung zwischen Nachbarn ist Teil derselben Bewegung
            # und kein Kollisionsfall). Wuerde die neue Groesse dazu fuehren,
            # dass ein ausgewaehlter Footprint einen NICHT ausgewaehlten
            # ueberschneidet, wird NICHT weiter VERGROESSERT -- das Ziehen
            # "haengt" beim Wachsen an dieser Stelle fest. VERKLEINERN bleibt
            # immer erlaubt (auch bei schon bestehender Ueberlappung), sonst
            # liesse sie sich per Ziehen nie mehr aufloesen.
            cur_w = self.placements[epi].get('width_mm', w0)
            cur_h = self.placements[epi].get('height_mm', h0)
            growing = new_w > cur_w or new_h > cur_h
            if growing and has_selection:
                bboxes = {}
                for i, tp in enumerate(self.placements):
                    w, h = (new_w, new_h) if i in targets else resolve_footprint_size(self.variant, tp)
                    bbox = self._footprint_bbox_for_size(tp, w, h)
                    if bbox is not None:
                        bboxes[i] = bbox
                idxs = list(bboxes.keys())
                # NUR Paare pruefen, bei denen mindestens eine Seite ein
                # ausgewaehltes Ziel ist -- zwei bereits vorher (unveraendert)
                # ueberlappende NICHT ausgewaehlte Platzierungen sollen das
                # Vergroessern nicht blockieren, das hat mit dieser Aktion
                # nichts zu tun.
                if any(self._bbox_overlap(bboxes[idxs[a]], bboxes[idxs[b]])
                       for a in range(len(idxs)) for b in range(a + 1, len(idxs))
                       if idxs[a] in targets or idxs[b] in targets):
                    return

            for ti in targets:
                self.placements[ti]['width_mm'] = new_w
                self.placements[ti]['height_mm'] = new_h
            self._render_cv()
            return
        if self._frame_resize_ref:
            edge, x0, y0, rect0 = self._frame_resize_ref
            left0, top0, right0, bottom0 = rect0
            min_px = FRAME_MIN_SIZE_MM * self.px_per_mm()
            dx = (e.x - x0) / self.zoom
            dy = (e.y - y0) / self.zoom
            left, top, right, bottom = left0, top0, right0, bottom0
            if edge == 'left':
                left = min(left0 + dx, right0 - min_px)
            elif edge == 'right':
                right = max(right0 + dx, left0 + min_px)
            elif edge == 'top':
                top = min(top0 + dy, bottom0 - min_px)
            elif edge == 'bottom':
                bottom = max(bottom0 + dy, top0 + min_px)
            self.frame_rect_px = (left, top, right, bottom)
            self._render_cv()

    def _cv_up(self, _e):
        if self._pan_ref:
            self._pan_ref = None
            self.cv.configure(cursor='crosshair')
            return
        if self._measuring:
            self._measuring = False
            return
        if self._scaling:
            self._scaling = False
            self._finish_scale_drag()
            return
        if self._move_ref:
            self._move_ref = None
            self._auto_assign()
            self._render_list_and_save()
            return
        if self._resize_ref:
            self._resize_ref = None
            self._render_list_and_save()
            return
        if self._frame_resize_ref:
            self._frame_resize_ref = None
            self._schedule_save()

    def _finish_scale_drag(self):
        """Nach dem Loslassen einer Kalibrierlinie (Werkzeug 'Skalieren'):
        fragt per Dialog die ECHTE Distanz (mm) ab und berechnet daraus die
        neue DPI (dpi = gemessene_px / eingegebene_mm * 25.4) -- dieselbe
        Umrechnung wie px_per_mm, nur rueckwaerts. Ein reiner Klick ohne
        Ziehen (Distanz ~0) tut nichts."""
        pts = self._scale_pts
        self._scale_pts = []
        if len(pts) != 2:
            self._render_cv()
            return
        (ix1, iy1), (ix2, iy2) = pts
        pixel_dist = ((ix2 - ix1) ** 2 + (iy2 - iy1) ** 2) ** 0.5
        self._render_cv()
        if pixel_dist < 2:
            return
        real_mm = self._ask_real_distance_mm(pixel_dist)
        if not real_mm:
            return
        new_dpi = (pixel_dist / real_mm) * 25.4
        self.dpi = new_dpi
        self.v_dpi.set(f'{new_dpi:g}')
        self._auto_assign()
        self._render_cv()
        self._schedule_save()
        self._status(f'✓ DPI kalibriert: {new_dpi:.1f}', C['green'])

    def _ask_real_distance_mm(self, pixel_dist: float) -> float | None:
        """Modaler Dialog (im Look der App statt eines OS-Standarddialogs):
        fragt die ECHTE Distanz (mm) fuer die gerade gezogene Kalibrierlinie
        ab. Gibt den eingegebenen Wert zurueck, oder None bei Abbruch/
        ungueltiger Eingabe."""
        result: dict = {}
        dlg = tk.Toplevel(self.root)
        dlg.title('Massstab kalibrieren')
        dlg.configure(bg=C['bg'])
        dlg.transient(self.root)
        dlg.resizable(False, False)

        tk.Label(dlg, text=f'Gemessene Strecke: {pixel_dist:.1f} px\n'
                           'Wie viele mm soll diese Strecke in Wirklichkeit sein?',
                bg=C['bg'], fg=C['text'], justify='left', padx=16, pady=12).pack()
        var = tk.StringVar(value='100')
        ent = tk.Entry(dlg, textvariable=var, bg=C['bg_panel'], fg=C['text'],
                      insertbackground='white', relief='flat', width=12,
                      font=('Courier New', 11), justify='center')
        ent.pack(pady=(0, 12))

        btns = tk.Frame(dlg, bg=C['bg'])
        btns.pack(pady=(0, 14))

        def ok(_e=None):
            try:
                val = float(var.get().replace(',', '.'))
                if val <= 0:
                    raise ValueError
                result['mm'] = val
            except ValueError:
                messagebox.showwarning('Ungueltig', 'Bitte eine Zahl groesser als 0 eingeben.',
                                       parent=dlg)
                return
            dlg.destroy()

        def cancel(_e=None):
            dlg.destroy()

        ttk.Button(btns, text='OK', command=ok).pack(side='left', padx=4)
        ttk.Button(btns, text='Abbrechen', command=cancel).pack(side='left', padx=4)
        ent.bind('<Return>', ok)
        dlg.bind('<Escape>', cancel)
        dlg.protocol('WM_DELETE_WINDOW', cancel)

        dlg.update_idletasks()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f'+{rx + max(0, (rw - dw) // 2)}+{ry + max(0, (rh - dh) // 2)}')

        dlg.grab_set()
        ent.focus_set()
        ent.select_range(0, 'end')
        dlg.wait_window()
        return result.get('mm')

    def _cv_hover(self, e):
        if not self.img_orig or self._pan_ref or self._move_ref or self._resize_ref \
                or self._frame_resize_ref:
            return
        if not any((self.tool_led_toggle.get(), self.tool_place.get(),
                   self.tool_measure.get(), self.tool_scale.get())):
            # Kein Werkzeug aktiv: Cursor auf JEDER Footprint-Resize-Kante
            # (nicht nur der ausgewaehlten Platzierung) auf einen Doppelpfeil
            # umstellen (siehe _hit_footprint_edge/_cv_dn), sonst auf eine
            # Rahmen-Kante (siehe _hit_frame_edge) pruefen, sonst zurueck auf
            # den normalen Crosshair.
            edge, _epi = self._hit_footprint_edge(e)
            if edge is None:
                edge = self._hit_frame_edge(e)
            cursor = {'left': 'sb_h_double_arrow', 'right': 'sb_h_double_arrow',
                      'top': 'sb_v_double_arrow', 'bottom': 'sb_v_double_arrow'}.get(edge, 'crosshair')
            self.cv.configure(cursor=cursor)
        if not self.tool_place.get():
            # Schattenvorschau nur, solange das "Variante platzieren"-Werkzeug
            # aktiv ist -- sonst wuerde ein Klick sowieso nichts platzieren.
            if self._hover is not None:
                self._hover = None
                self._render_cv()
            return
        variant = self.variant
        if not variant:
            return
        ix, iy = self._s2i(e.x, e.y)
        self._hover = self._snap_anchor(ix, iy, variant, self.place_flipped.get())
        self._render_cv()

    def _cv_leave(self, _e):
        if self._hover is not None:
            self._hover = None
            self._render_cv()

    def _render_list_and_save(self):
        self._render_placements()
        self._render_cv()
        self._schedule_save()

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

    def _height_panel_dn(self, e):
        """Start eines Ziehens am Hoehen-Overlay (siehe self.height_panel) --
        merkt sich Maus- UND Panel-Startposition in BILDSCHIRM-Koordinaten
        (e.x_root/e.y_root, nicht e.x/e.y: die sind relativ zur Titelzeile
        selbst, die sich waehrend des Ziehens mitbewegt -- root-Koordinaten
        bleiben ein stabiler Bezugspunkt)."""
        self._height_panel_ref = (e.x_root, e.y_root,
                                  self.height_panel.winfo_x(), self.height_panel.winfo_y())

    def _height_panel_mv(self, e):
        if not self._height_panel_ref:
            return
        x0, y0, px0, py0 = self._height_panel_ref
        self.height_panel.place(x=px0 + (e.x_root - x0), y=py0 + (e.y_root - y0))

    def _scroll(self, e):
        if not self.img_orig:
            return
        f = 1.1 if e.delta > 0 else 1 / 1.1
        self._zoom_at(e.x, e.y, f)

    def _zoom_center(self, f):
        if not self.img_orig:
            return
        self._zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, f)

    def _zoom_at(self, cx, cy, f):
        nz = max(0.02, min(32.0, self.zoom * f))
        self.off_x = cx - (cx - self.off_x) * (nz / self.zoom)
        self.off_y = cy - (cy - self.off_y) * (nz / self.zoom)
        self.zoom = nz
        self._cache_zoom = None
        self._render_cv()

    # ── Tastatur ──────────────────────────────────────────────────────────

    def _kb_del(self, e):
        if not self._is_active() or isinstance(e.widget, tk.Entry):
            return
        if 0 <= self.sel_idx < len(self.placements):
            self._del_placement(self.sel_idx)

    def _kb_esc(self, _e):
        if not self._is_active():
            return
        self.sel_idx = -1
        self.sel_idxs = set()
        self._measure_pts = []
        self._scale_pts = []
        self._render_placements()
        self._render_cv()

    # ── Rechtes Panel: Batch-Liste ─────────────────────────────────────────

    def _render_placements(self):
        for w in self._p_list_frame.winfo_children():
            w.destroy()
        self._v_count.set(str(len(self.placements)))
        self._render_height_panel()

        if not self.placements:
            msg = ('Variante wählen, dann auf\ndem Bild klicken zum Platzieren\n'
                   '(rastet an Fenster-Oberkanten ein)'
                   if self.img_orig else 'Kein Bild geöffnet')
            tk.Label(self._p_list_frame, text=msg, bg=C['bg'], fg=C['dim'],
                     justify='center', font=('Segoe UI', 9)).pack(pady=24)
            return

        for i, p in enumerate(self.placements):
            self._add_card(i, p)

    def _render_height_panel(self):
        """Baut die Liste im beweglichen Hoehen-Overlay neu auf (siehe
        self.height_panel/height_highlight_mm) -- eine anklickbare Zeile je
        DISTINKTER Footprint-Hoehe (siehe resolve_footprint_size), mit der
        Anzahl Platzierungen dieser Hoehe. Klick markiert/entmarkiert diese
        Hoehe (siehe _toggle_height_highlight) -- ALLE Platzierungen mit
        GENAU dieser Hoehe werden dann in _draw_footprint hervorgehoben.
        Von _render_placements() bei jeder Aenderung der Platzierungsliste
        (neu/geloescht/Groesse geaendert) neu aufgebaut, damit die Liste nie
        veraltet."""
        for w in self.height_list_frame.winfo_children():
            w.destroy()
        variant = self.variant
        counts: dict = {}
        for p in self.placements:
            _w, h = resolve_footprint_size(variant, p)
            counts[h] = counts.get(h, 0) + 1
        if not counts:
            tk.Label(self.height_list_frame, text='(keine)', bg=C['bg_panel'], fg=C['dim'],
                    font=('Segoe UI', 8)).pack(anchor='w')
            return
        for h in sorted(counts):
            sel = self.height_highlight_mm is not None and abs(h - self.height_highlight_mm) < 1e-6
            row = tk.Label(self.height_list_frame, text=f'{h:g} mm  ({counts[h]})',
                          bg=C['blue_sel'] if sel else C['bg_panel'],
                          fg=C['text'] if sel else C['muted'],
                          font=('Segoe UI', 8, 'bold' if sel else 'normal'),
                          anchor='w', padx=4, pady=1, cursor='hand2')
            row.pack(fill='x')
            row.bind('<Button-1>', lambda e, h=h: self._toggle_height_highlight(h))

    def _toggle_height_highlight(self, h: float):
        """Klick auf eine Zeile im Hoehen-Overlay: markiert diese Hoehe (alle
        Platzierungen mit genau dieser Hoehe werden im Canvas hervorgehoben,
        siehe _draw_footprint), oder hebt die Markierung wieder auf, wenn
        dieselbe Hoehe schon markiert war (Klick = Umschalter)."""
        if self.height_highlight_mm is not None and abs(h - self.height_highlight_mm) < 1e-6:
            self.height_highlight_mm = None
        else:
            self.height_highlight_mm = h
        self._render_height_panel()
        self._render_cv()

    def _add_card(self, idx, p):
        sel = (idx in self.sel_idxs)
        BG = C['blue_sel'] if sel else C['bg_panel']
        BD = C['blue'] if sel else C['border']
        variant = self.variant
        vname = variant['name'] if variant else '⚠ fehlt'
        n_enabled = sum(1 for l in p['leds'] if l['enabled'])
        n_total = len(p['leds'])

        outer = tk.Frame(self._p_list_frame, bg=BD, padx=1, pady=1)
        outer.pack(fill='x', padx=4, pady=2)
        inner = tk.Frame(outer, bg=BG, padx=6, pady=5)
        inner.pack(fill='x')

        head = tk.Frame(inner, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text=f'#{idx + 1}  {vname}', bg=BG, fg='#60a5fa',
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        tk.Button(head, text='✕', bg=BG, fg=C['dim'], relief='flat', bd=0,
                  activebackground='#450a0a', activeforeground=C['red'],
                  command=lambda i=idx: self._del_placement(i)).pack(side='right')

        sub = tk.Frame(inner, bg=BG)
        sub.pack(fill='x', pady=(2, 0))
        tk.Label(sub, text=f'{n_enabled}/{n_total} LEDs aktiv', bg=BG, fg=C['muted'],
                 font=('Segoe UI', 8)).pack(side='left')
        tk.Button(sub, text='▲', bg=BG, fg=C['muted'], relief='flat', bd=0,
                  command=lambda i=idx: self._move_placement(i, -1)).pack(side='right', padx=1)
        tk.Button(sub, text='▼', bg=BG, fg=C['muted'], relief='flat', bd=0,
                  command=lambda i=idx: self._move_placement(i, 1)).pack(side='right', padx=1)

        flip_var = tk.BooleanVar(value=p.get('flipped', False))
        def toggle_flip(i=idx, v=flip_var):
            self.placements[i]['flipped'] = v.get()
            self._auto_assign()
            self._render_cv()
            self._schedule_save()
        tk.Checkbutton(inner, text='Gespiegelt (Y-Achse)', variable=flip_var, command=toggle_flip,
                       bg=BG, fg=C['text'], selectcolor=C['bg_dark'],
                       activebackground=BG, activeforeground=C['text'],
                       font=('Segoe UI', 8), highlightthickness=0, bd=0,
                       anchor='w').pack(fill='x', pady=(2, 0))

        # Footprint-Groesse PRO PLATZIERUNG eintragbar (ueberschreibt den
        # Default der Variante nur fuer DIESE eine Platzierung) -- leer
        # loescht die Ueberschreibung wieder (siehe _draw_footprint/
        # resolve_footprint_size/dxfExport.py).
        foot_row = tk.Frame(inner, bg=BG)
        foot_row.pack(fill='x', pady=(2, 0))
        tk.Label(foot_row, text='Footprint B×H:', bg=BG, fg=C['muted'],
                font=('Courier New', 8)).pack(side='left')
        fp_w_var = tk.StringVar(value=f"{p['width_mm']:g}" if p.get('width_mm') else '')
        ent_fp_w = tk.Entry(foot_row, textvariable=fp_w_var, bg=C['bg_dark'], fg=C['text'],
                           insertbackground='white', relief='flat', width=5, font=('Courier New', 8))
        ent_fp_w.pack(side='left', padx=(4, 1))
        tk.Label(foot_row, text='×', bg=BG, fg=C['muted'], font=('Courier New', 8)).pack(side='left')
        fp_h_var = tk.StringVar(value=f"{p['height_mm']:g}" if p.get('height_mm') else '')
        ent_fp_h = tk.Entry(foot_row, textvariable=fp_h_var, bg=C['bg_dark'], fg=C['text'],
                           insertbackground='white', relief='flat', width=5, font=('Courier New', 8))
        ent_fp_h.pack(side='left', padx=(1, 0))

        def on_footprint_size_commit(_e=None, i=idx, vw=fp_w_var, vh=fp_h_var):
            try:
                w = float(vw.get().replace(',', '.')) if vw.get().strip() else None
                h = float(vh.get().replace(',', '.')) if vh.get().strip() else None
            except ValueError:
                w = h = None
            if w and h and w > 0 and h > 0:
                self.placements[i]['width_mm'] = w
                self.placements[i]['height_mm'] = h
            else:
                self.placements[i].pop('width_mm', None)
                self.placements[i].pop('height_mm', None)
                vw.set('')
                vh.set('')
            self._render_cv()
            self._schedule_save()
        ent_fp_w.bind('<Return>', on_footprint_size_commit)
        ent_fp_w.bind('<FocusOut>', on_footprint_size_commit)
        ent_fp_h.bind('<Return>', on_footprint_size_commit)
        ent_fp_h.bind('<FocusOut>', on_footprint_size_commit)

        ttk.Button(inner, text='🎯 Auf beleuchtete Fenster zentrieren',
                  command=lambda i=idx: self._center_placement_on_lit_windows(i),
                  takefocus=0).pack(fill='x', pady=(4, 0))

        # Nur Position (X/Y) -- Groesse/Layout kommt fix aus der Variante (mm + DPI)
        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill='x', pady=(3, 0))
        for c in range(2):
            grid.columnconfigure(c, weight=1)
        for col, (field, lbl) in enumerate([('x', 'X'), ('y', 'Y')]):
            cell = tk.Frame(grid, bg=BG)
            cell.grid(row=0, column=col, padx=2, pady=1, sticky='ew')
            cell.columnconfigure(1, weight=1)
            tk.Label(cell, text=lbl, bg=BG, fg=C['muted'], font=('Courier New', 8), width=2).grid(row=0, column=0)
            var = tk.StringVar(value=f"{p[field]:g}")
            ent = tk.Entry(cell, textvariable=var, bg=C['bg_dark'], fg=C['text'],
                           insertbackground='white', relief='flat', bd=1, font=('Courier New', 9),
                           highlightthickness=1, highlightbackground=C['border'], highlightcolor=C['blue'])
            ent.grid(row=0, column=1, sticky='ew', padx=(2, 0))

            def commit(e=None, i=idx, f=field, v=var):
                try:
                    val = round(float(v.get().replace(',', '.')), 1)
                    self.placements[i][f] = val
                    v.set(f'{val:g}')
                    self._auto_assign()
                    self._render_cv()
                    self._schedule_save()
                except ValueError:
                    v.set(f"{self.placements[i][f]:g}")
            ent.bind('<Return>', commit)
            ent.bind('<FocusOut>', commit)

        def on_click(e, i=idx):
            if isinstance(e.widget, tk.Entry):
                return
            self.sel_idx = i
            self.sel_idxs = {i}
            self._render_placements()
            self._render_cv()
        for wgt in (outer, inner, head, sub, grid):
            wgt.bind('<Button-1>', on_click)

    def _del_placement(self, idx):
        self.placements.pop(idx)
        self.sel_idx = min(self.sel_idx, len(self.placements) - 1)
        # Mehrfachauswahl (sel_idxs) wuerde nach dem Loeschen auf verschobene
        # Indizes zeigen -- statt sie umzurechnen, wird sie einfach geleert.
        self.sel_idxs = set()
        # Ein Fenster, das von einer geloeschten LED versorgt wurde, kann jetzt
        # von einer anderen Kandidaten-LED uebernommen werden.
        self._auto_assign()
        self._render_list_and_save()

    def _move_placement(self, idx, direction):
        j = idx + direction
        if 0 <= j < len(self.placements):
            self.placements[idx], self.placements[j] = self.placements[j], self.placements[idx]
            self.sel_idx = j
            self.sel_idxs = set()
            self._render_list_and_save()

    def _center_placement_on_lit_windows(self, idx: int):
        """Zentriert Platzierung `idx` horizontal zwischen ALLEN Fenstern, die
        sie GERADE JETZT beleuchtet (deren windowIndex von einer ihrer
        aktiven LEDs referenziert wird, siehe _auto_assign) -- unabhaengig
        von der automatischen Gruppierung aus _auto_place, auf Wunsch fuer
        eine einzelne bereits platzierte Variante von Hand anwendbar (z.B.
        nach manuellem Verschieben/Umgruppieren). Ohne aktuell beleuchtete
        Fenster passiert nichts (Statusmeldung statt stillem No-op)."""
        if not (0 <= idx < len(self.placements)) or not self.variant:
            return
        p = self.placements[idx]
        lit_indices = {led['windowIndex'] for led in p['leds']
                       if led.get('enabled') and led.get('windowIndex') is not None}
        lit_windows = [self.windows[wi] for wi in lit_indices if 0 <= wi < len(self.windows)]
        if not lit_windows:
            self._status('⚠ Diese Platzierung beleuchtet aktuell kein Fenster.', C['amber'])
            return
        px_per_mm = self.px_per_mm()
        _minx, _miny, w_mm, _h_mm = variant_bbox(self.variant)
        led_span_px = w_mm * px_per_mm
        group_left = min(w['x'] for w in lit_windows)
        group_right = max(w['x'] + w['w'] for w in lit_windows)
        p['x'] = round((group_left + group_right) / 2 - led_span_px / 2, 1)
        self._auto_assign()
        self._render_list_and_save()
        self._status(f'✓ Zwischen {len(lit_windows)} beleuchteten Fenstern zentriert', C['green'])

    # ── 3. Tab: LED-Kette (Variants verbinden, global durchnummerieren) ─────
    #
    # Teilt sich Bild/Fenster/Platzierungen/Varianten mit den ersten beiden
    # Tabs (dieselbe App-Instanz) -- baut nur eine eigene, zusaetzliche
    # Ansicht in einen separaten Tab-Frame (siehe windowTool._launch_combined).

    def build_chain_tab(self, parent):
        self.chain_container = parent

        tb = tk.Frame(parent, bg=C['bg_dark'], height=44)
        tb.pack(side='top', fill='x')
        tb.pack_propagate(False)
        tk.Label(tb, text='LED-Kette', bg=C['bg_dark'], fg=C['text'],
                font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(10, 8), pady=6)
        ttk.Button(tb, text='Kette zuruecksetzen (links-nach-rechts)',
                  command=self._reset_chain, takefocus=0).pack(side='left', padx=4, pady=6)

        tk.Frame(tb, bg=C['border'], width=1).pack(side='left', fill='y', padx=10, pady=8)
        self.btn_chain_group = tk.Checkbutton(
            tb, text='🔗 LEDs gruppieren', variable=self.chain_tool_group, indicatoron=False,
            command=self._pick_chain_group_tool,
            bg=C['bg_panel'], fg=C['text'], selectcolor=C['blue'],
            activebackground=C['border'], activeforeground=C['text'],
            font=('Segoe UI', 9), relief='flat', bd=0, padx=8, pady=4, highlightthickness=0,
            takefocus=0)
        self.btn_chain_group.pack(side='left', padx=(4, 2), pady=6)

        self._v_chain_total = tk.StringVar(value='0 LEDs gesamt')
        tk.Label(tb, textvariable=self._v_chain_total, bg=C['bg_dark'], fg=C['muted'],
                font=('Segoe UI', 9)).pack(side='left', padx=12)
        self._v_chain_disabled = tk.StringVar(value='0 deaktiviert')
        tk.Label(tb, textvariable=self._v_chain_disabled, bg=C['bg_dark'], fg=C['muted'],
                font=('Segoe UI', 9)).pack(side='left', padx=4)
        self._v_chain_pixels = tk.StringVar(value='0 Pixel')
        tk.Label(tb, textvariable=self._v_chain_pixels, bg=C['bg_dark'], fg=C['muted'],
                font=('Segoe UI', 9)).pack(side='left', padx=4)
        self._v_chain_warn = tk.StringVar(value='')
        tk.Label(tb, textvariable=self._v_chain_warn, bg=C['bg_dark'], fg=C['red'],
                font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8)

        tk.Frame(tb, bg=C['border'], width=1).pack(side='right', fill='y', padx=8, pady=8)
        ttk.Button(tb, text='Anpassen', command=self._fit_chain, takefocus=0).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' + ', command=lambda: self._chain_zoom_center(1.25), takefocus=0).pack(side='right', padx=2, pady=6)
        ttk.Button(tb, text=' − ', command=lambda: self._chain_zoom_center(1 / 1.25), takefocus=0).pack(side='right', padx=2, pady=6)

        self._v_chain_hint = tk.StringVar(
            value='Klick = anhaengen · Rechtsklick = aus Kette entfernen · Mausrad = Zoom · Mittlere Maustaste = Verschieben')
        tk.Label(tb, textvariable=self._v_chain_hint,
                bg=C['bg_dark'], fg=C['dim'], font=('Segoe UI', 8)).pack(side='right', padx=10)

        main = tk.Frame(parent, bg=C['bg'])
        main.pack(fill='both', expand=True)

        self.chain_cv = tk.Canvas(main, bg=C['bg_dark'], highlightthickness=0, cursor='hand2')
        self.chain_cv.pack(side='left', fill='both', expand=True)
        self.chain_cv.bind('<ButtonPress-1>', self._chain_cv_click)
        self.chain_cv.bind('<ButtonPress-3>', self._chain_cv_right_click)
        self.chain_cv.bind('<ButtonPress-2>', self._chain_pan_dn)
        self.chain_cv.bind('<B2-Motion>', self._chain_pan_mv)
        self.chain_cv.bind('<ButtonRelease-2>', self._chain_pan_up)
        self.chain_cv.bind('<MouseWheel>', self._chain_scroll)
        self.chain_cv.bind('<Configure>', lambda e: self._fit_chain())

        tk.Frame(main, bg=C['border'], width=1).pack(side='left', fill='y')

        right = tk.Frame(main, bg=C['bg'], width=280)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        rh = tk.Frame(right, bg=C['bg_dark'], height=32)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        tk.Label(rh, text='Verbindungsreihenfolge', bg=C['bg_dark'], fg=C['text'],
                font=('Segoe UI', 9, 'bold')).pack(side='left', padx=8, pady=6)
        tk.Frame(right, bg=C['border'], height=1).pack(fill='x')

        cwrap = tk.Frame(right, bg=C['bg'])
        cwrap.pack(fill='both', expand=True)
        self._chain_canvas_list = tk.Canvas(cwrap, bg=C['bg'], highlightthickness=0)
        csb = ttk.Scrollbar(cwrap, orient='vertical', command=self._chain_canvas_list.yview)
        self._chain_list_frame = tk.Frame(self._chain_canvas_list, bg=C['bg'])
        self._chain_list_frame.bind('<Configure>',
            lambda e: self._chain_canvas_list.configure(scrollregion=self._chain_canvas_list.bbox('all')))
        self._chain_canvas_list.create_window((0, 0), window=self._chain_list_frame, anchor='nw', tags='f')
        self._chain_canvas_list.configure(yscrollcommand=csb.set)
        self._chain_canvas_list.bind('<Configure>', lambda e: self._chain_canvas_list.itemconfig('f', width=e.width))
        self._chain_canvas_list.pack(side='left', fill='both', expand=True)
        csb.pack(side='right', fill='y')
        bind_wheel_scroll(cwrap, self._chain_canvas_list)

        self._fit_chain()
        self._render_chain_tab()

    def _fit_chain(self):
        if not hasattr(self, 'chain_cv'):
            return  # Tab noch nicht gebaut (siehe build_chain_tab)
        if not self.img_orig:
            self.chain_zoom = 1.0
            return
        # Siehe _fit(): ohne update_idletasks() + expliziten Mindestgroessen-
        # Check liefert ein gerade erst sichtbar gewordener Tab winfo_width()==1
        # und "or 800" faengt das nicht ab (1 ist wahr) -- Ergebnis waere ein
        # negativer/kaputter Zoom, der nie repariert wird.
        self.chain_cv.update_idletasks()
        W = self.chain_cv.winfo_width()
        H = self.chain_cv.winfo_height()
        if W <= 1:
            W = 800
        if H <= 1:
            H = 600
        pad = 24
        self.chain_zoom = min((W - pad * 2) / self.img_orig.width,
                              (H - pad * 2) / self.img_orig.height, 1.0)
        self._chain_cache_zoom = None
        self.chain_off_x = (W - self.img_orig.width * self.chain_zoom) / 2
        self.chain_off_y = (H - self.img_orig.height * self.chain_zoom) / 2
        self._render_chain_cv()

    def _chain_i2s(self, ix, iy):
        return self.chain_off_x + ix * self.chain_zoom, self.chain_off_y + iy * self.chain_zoom

    def _render_chain_tab(self):
        if not hasattr(self, 'chain_cv'):
            return  # Tab noch nicht gebaut (z.B. beim allerersten Laden)
        n_too_long = self._render_chain_cv()
        self._render_chain_list()
        self._v_chain_total.set(f'{self.total_led_count} LEDs gesamt')
        self._v_chain_disabled.set(f'{len(self.disabled_leds)} deaktiviert')
        self._v_chain_pixels.set(f'{self.total_pixel_count} Pixel')
        self._v_chain_warn.set(
            f'⚠ {n_too_long} Verbindung(en) > {MAX_CONNECTION_MM:.0f}mm' if n_too_long else '')

    def _render_chain_cv(self) -> int:
        """Zeichnet den Ketten-Tab. Gibt die Anzahl der Verbindungen zurueck,
        die MAX_CONNECTION_MM ueberschreiten (fuer die Warnanzeige in
        _render_chain_tab)."""
        self.chain_cv.delete('all')
        W = self.chain_cv.winfo_width() or 800
        H = self.chain_cv.winfo_height() or 600
        if not self.img_orig or self._display_img is None:
            self.chain_cv.create_text(W // 2, H // 2, text='Kein Bild geöffnet',
                fill=C['dim'], font=('Segoe UI', 12), justify='center')
            return 0

        if self._chain_cache_zoom != self.chain_zoom:
            iw = max(1, int(self._display_img.width * self.chain_zoom))
            ih = max(1, int(self._display_img.height * self.chain_zoom))
            method = Image.LANCZOS if self.chain_zoom < 1 else Image.NEAREST
            self._chain_cache_tk = ImageTk.PhotoImage(
                self._display_img.resize((iw, ih), method, reducing_gap=2.0))
            self._chain_cache_zoom = self.chain_zoom
        self.chain_cv.create_image(int(self.chain_off_x), int(self.chain_off_y),
                                   image=self._chain_cache_tk, anchor='nw')

        pts_by_id = {p['id']: self._placement_points(p) for p in self.placements}
        self._render_windows_and_cones(self.chain_cv, self._chain_i2s, pts_by_id)

        chained_ids = set(self.chain_order)
        r = 6 if self.chain_zoom >= 0.6 else 4
        conn_pts = []      # (din_screen, dout_screen) je Platzierung, in Kettenreihenfolge
        conn_pts_img = []  # (din_img, dout_img) je Platzierung -- fuer die mm-Laengenpruefung
        px_per_mm = self.px_per_mm()
        for p in self._ordered_placements():
            pts = pts_by_id[p['id']]
            if pts is None:
                conn_pts.append(None)
                conn_pts_img.append(None)
                continue
            in_chain = p['id'] in chained_ids
            spts = [self._chain_i2s(px, py) for px, py in pts]
            if len(spts) > 1:
                self._draw_chain_links(self.chain_cv, self._chain_i2s, spts, p.get('flipped', False),
                                       color=C['blue_dim'], width=2 if in_chain else 1)
            variant_p = self.variant
            conn_pt = None
            conn_pt_img = None
            if variant_p:
                conn_pt = self._draw_connector(self.chain_cv, self._chain_i2s, p, variant_p)
                conn_pt_img = connector_positions(variant_p, p['x'], p['y'], px_per_mm,
                                                  p.get('flipped', False))
            conn_pts.append(conn_pt)
            conn_pts_img.append(conn_pt_img)
            for li, (sx, sy) in enumerate(spts):
                led = p['leds'][li]
                if self._group_anchor == (p['id'], li):
                    # als "LED A" fuer das Gruppieren-Werkzeug vorgemerkt --
                    # deutlicher Ring, damit klar ist, worauf der naechste
                    # Klick angewendet wird.
                    self.chain_cv.create_oval(sx - r - 5, sy - r - 5, sx + r + 5, sy + r + 5,
                                              outline=C['blue'], width=2)
                icon = self._lamp_icon(r, led['enabled'])
                self.chain_cv.create_image(sx, sy, image=icon)
                # Zeigt den logischen Pixel-/Fensterindex (zaehlt ab Daten-Eingang
                # pro versorgtem Fenster hoch, siehe pixelIndex in _recompute_chain)
                # statt des einzelnen physischen chainIndex -- LEDs ohne Fenster
                # (pixelIndex=None) bleiben bewusst unbeschriftet.
                if led.get('pixelIndex') is not None:
                    self.chain_cv.create_text(sx, sy - r - 9, text=str(led['pixelIndex']),
                        fill=C['amber'] if led['enabled'] else C['muted'],
                        font=('Segoe UI', 8, 'bold'))

        # Kabel-Verbindungslinien ZWISCHEN den Verbindern aufeinanderfolgender
        # Platzierungen -- das physische Kabel laeuft vom DATEN-AUSGANG (DOUT)
        # der einen Platine zum DATEN-EINGANG (DIN) der naechsten, NICHT von
        # Ursprung zu Ursprung. Wuerde man stattdessen DIN mit DIN verbinden,
        # zickzackte die Linie bei gespiegelten Platzierungen quer durch die
        # Platzierung, weil DIN dann auf die jeweils andere Seite springt.
        # Ueberschreitet das reale Kabel dabei MAX_CONNECTION_MM (die physisch
        # verfuegbare/zulaessige Kabellaenge), wird die Linie ROT statt amber
        # gezeichnet und mit der tatsaechlichen Laenge beschriftet.
        n_too_long = 0
        for (prev_conn, prev_conn_img), (next_conn, next_conn_img) in zip(
                zip(conn_pts, conn_pts_img), zip(conn_pts[1:], conn_pts_img[1:])):
            if prev_conn is None or next_conn is None:
                continue
            _, prev_dout = prev_conn
            next_din, _ = next_conn
            _, prev_dout_img = prev_conn_img
            next_din_img, _ = next_conn_img
            n_too_long += self._draw_chain_wire(prev_dout, next_din, prev_dout_img,
                                                next_din_img, px_per_mm)

        # ERSTES gueltiges DIN der Kette merken (in _ordered_placements()-
        # Reihenfolge, d.h. chain_order[0] -- siehe _auto_connect_chain) --
        # daran wird der Eingangs-Knoten angeschlossen.
        first_din, first_din_img = None, None
        for conn, conn_img in zip(conn_pts, conn_pts_img):
            if conn is not None:
                first_din, _ = conn
                first_din_img, _ = conn_img
                break

        # Eingangs-Knoten (schwarzer Kasten, echte INPUT_NODE_W_MM x
        # INPUT_NODE_H_MM) an der Unterkante-Mitte der Gebaeude-Kontur --
        # speist die Kette von dort aus in das ERSTE Kettenglied (dessen DIN)
        # ein (Kabellaenge ebenso gegen MAX_CONNECTION_MM geprueft).
        input_pos = self._get_input_node_pos()
        if input_pos is not None:
            ix_img, iy_img = input_pos
            half_w_img = INPUT_NODE_W_MM * px_per_mm / 2
            half_h_img = INPUT_NODE_H_MM * px_per_mm / 2
            x1, y1 = self._chain_i2s(ix_img - half_w_img, iy_img - half_h_img)
            x2, y2 = self._chain_i2s(ix_img + half_w_img, iy_img + half_h_img)
            self.chain_cv.create_rectangle(x1, y1, x2, y2, fill='#000000',
                                           outline='#f8fafc', width=1.5)
            in_pt = self._chain_i2s(ix_img, iy_img)
            self.chain_cv.create_text(in_pt[0], y2 + 10, text='IN', fill=C['muted'],
                                      font=('Segoe UI', 8))
            if first_din is not None:
                n_too_long += self._draw_chain_wire(in_pt, first_din, input_pos,
                                                    first_din_img, px_per_mm)
        return n_too_long

    def _draw_chain_wire(self, from_screen: tuple, to_screen: tuple,
                         from_img: tuple, to_img: tuple, px_per_mm: float) -> int:
        """Zeichnet EIN Kabelsegment zwischen zwei Bild-Punkten (bereits in
        Bildschirmkoordinaten fuer die Linie, zusaetzlich in Bild-px fuer die
        mm-Berechnung) mit Pfeil + Laengenbeschriftung; rot statt amber,
        sobald die reale Laenge MAX_CONNECTION_MM ueberschreitet. Gibt 1
        zurueck, wenn zu lang, sonst 0 (zum Aufsummieren von n_too_long)."""
        dist_mm = ((to_img[0] - from_img[0]) ** 2 + (to_img[1] - from_img[1]) ** 2) ** 0.5 / px_per_mm
        too_long = dist_mm > MAX_CONNECTION_MM
        color = C['red'] if too_long else C['amber']
        self.chain_cv.create_line(*from_screen, *to_screen, fill=color,
                                  width=2, dash=(5, 3), arrow=tk.LAST, arrowshape=(10, 12, 4))
        mx, my = (from_screen[0] + to_screen[0]) / 2, (from_screen[1] + to_screen[1]) / 2
        label = f'⚠ {dist_mm:.0f} mm' if too_long else f'{dist_mm:.0f} mm'
        self.chain_cv.create_text(mx, my - 10, text=label,
                                  fill=C['red'] if too_long else C['text'],
                                  font=('Segoe UI', 8, 'bold' if too_long else 'normal'))
        return 1 if too_long else 0

    def _chain_hit_placement(self, e):
        for p in self._ordered_placements():
            pts = self._placement_points(p)
            if pts is None:
                continue
            for (ix, iy) in pts:
                sx, sy = self._chain_i2s(ix, iy)
                if (sx - e.x) ** 2 + (sy - e.y) ** 2 <= LED_HIT_R ** 2:
                    return p['id']
        return None

    def _hit_led_chain(self, e):
        """(Platzierungs-ID, lokaler LED-Index) der einzelnen LED unter dem
        Cursor im Ketten-Tab (oberste zuerst), sonst (None, None)."""
        for p in self._ordered_placements():
            pts = self._placement_points(p)
            if pts is None:
                continue
            for li, (ix, iy) in enumerate(pts):
                sx, sy = self._chain_i2s(ix, iy)
                if (sx - e.x) ** 2 + (sy - e.y) ** 2 <= LED_HIT_R ** 2:
                    return p['id'], li
        return None, None

    def _pick_chain_group_tool(self):
        self._group_anchor = None
        if self.chain_tool_group.get():
            self._v_chain_hint.set(
                'LEDs gruppieren: Klick auf LED A, dann LED B -> teilen sich ein Fenster · '
                'Rechtsklick = LED aus Gruppe loesen (zurueck auf automatisch)')
        else:
            self._v_chain_hint.set(
                'Klick = anhaengen · Rechtsklick = aus Kette entfernen · '
                'Mausrad = Zoom · Mittlere Maustaste = Verschieben')
        self.chain_cv.focus_set()
        self._render_chain_cv()

    def _chain_cv_click(self, e):
        if self.chain_tool_group.get():
            self._chain_group_click(e)
            return
        pid = self._chain_hit_placement(e)
        if pid:
            self._add_to_chain(pid)

    def _chain_cv_right_click(self, e):
        if self.chain_tool_group.get():
            self._chain_group_ungroup(e)
            return
        pid = self._chain_hit_placement(e)
        if pid:
            self._remove_from_chain(pid)

    def _chain_group_click(self, e):
        """Erster Klick auf eine (Fenster-zugeordnete) LED merkt sie als Anker
        vor; der zweite Klick auf eine ANDERE Fenster-zugeordnete LED laesst
        sie sich dieselbe Fensterzuordnung (windowIndex) teilen -- beide
        gelten danach als EIN logisches Pixel (siehe pixelIndex). Ein
        nochmaliger Klick auf den bereits gemerkten Anker verwirft ihn wieder."""
        pid, li = self._hit_led_chain(e)
        if pid is None:
            return
        p = next((x for x in self.placements if x['id'] == pid), None)
        if p is None:
            return
        led = p['leds'][li]
        if led.get('windowIndex') is None:
            self._status('LED beruehrt kein Fenster', C['red'])
            return

        if self._group_anchor is None:
            self._group_anchor = (pid, li)
            self._status('LED A gewaehlt -- jetzt LED B anklicken', C['blue'])
            self._render_chain_cv()
            return

        apid, ali = self._group_anchor
        if apid == pid and ali == li:
            self._group_anchor = None
            self._status('Auswahl verworfen', C['muted'])
            self._render_chain_cv()
            return

        anchor_p = next((x for x in self.placements if x['id'] == apid), None)
        if anchor_p is None:
            self._group_anchor = None
            return
        anchor_led = anchor_p['leds'][ali]
        if anchor_led.get('windowIndex') is None:
            self._group_anchor = None
            return

        led['manual'] = True
        led['enabled'] = True
        led['windowIndex'] = anchor_led['windowIndex']
        self._group_anchor = None
        self._auto_assign()
        self._render_chain_tab()
        self._schedule_save()
        self._status('LEDs gruppiert -- teilen sich jetzt ein Fenster', C['green'])

    def _chain_group_ungroup(self, e):
        """Rechtsklick (bei aktivem Gruppieren-Werkzeug): loest die LED aus
        jeder manuellen Gruppierung/Uebersteuerung -- _auto_assign berechnet
        ihre Fensterzuordnung danach wieder rein geometrisch selbst."""
        pid, li = self._hit_led_chain(e)
        if pid is None:
            return
        p = next((x for x in self.placements if x['id'] == pid), None)
        if p is None:
            return
        led = p['leds'][li]
        led.pop('manual', None)
        self._group_anchor = None
        self._auto_assign()
        self._render_chain_tab()
        self._schedule_save()
        self._status('LED zurueck auf automatisch', C['blue'])

    def _chain_pan_dn(self, e):
        self._chain_pan_ref = (e.x - self.chain_off_x, e.y - self.chain_off_y)
        self.chain_cv.configure(cursor='fleur')

    def _chain_pan_mv(self, e):
        if self._chain_pan_ref:
            self.chain_off_x = e.x - self._chain_pan_ref[0]
            self.chain_off_y = e.y - self._chain_pan_ref[1]
            self._render_chain_cv()

    def _chain_pan_up(self, _e):
        self._chain_pan_ref = None
        self.chain_cv.configure(cursor='hand2')

    def _chain_scroll(self, e):
        if not self.img_orig:
            return
        f = 1.1 if e.delta > 0 else 1 / 1.1
        self._chain_zoom_at(e.x, e.y, f)

    def _chain_zoom_center(self, f):
        if not self.img_orig:
            return
        self._chain_zoom_at(self.chain_cv.winfo_width() / 2, self.chain_cv.winfo_height() / 2, f)

    def _chain_zoom_at(self, cx, cy, f):
        nz = max(0.02, min(32.0, self.chain_zoom * f))
        self.chain_off_x = cx - (cx - self.chain_off_x) * (nz / self.chain_zoom)
        self.chain_off_y = cy - (cy - self.chain_off_y) * (nz / self.chain_zoom)
        self.chain_zoom = nz
        self._chain_cache_zoom = None
        self._render_chain_cv()

    def _render_chain_list(self):
        for w in self._chain_list_frame.winfo_children():
            w.destroy()
        ordered = self._ordered_placements()
        if not ordered:
            tk.Label(self._chain_list_frame, text='Noch keine Batches platziert\n(siehe Tab "LED-Batches")',
                     bg=C['bg'], fg=C['dim'], justify='center', font=('Segoe UI', 9)).pack(pady=24)
            return

        chained_ids = set(self.chain_order)
        for pos, p in enumerate(ordered):
            self._add_chain_card(pos, p, explicit=(p['id'] in chained_ids))

    def _add_chain_card(self, pos: int, p: dict, explicit: bool):
        variant = self.variant
        vname = variant['name'] if variant else '⚠ fehlt'
        idxs = [led.get('chainIndex') for led in p['leds']]
        idxs = [i for i in idxs if i is not None]
        rng = f'{min(idxs)}–{max(idxs)}' if idxs else '–'

        BG = C['bg_panel']
        BD = C['blue'] if explicit else C['border']
        outer = tk.Frame(self._chain_list_frame, bg=BD, padx=1, pady=1)
        outer.pack(fill='x', padx=4, pady=2)
        inner = tk.Frame(outer, bg=BG, padx=6, pady=5)
        inner.pack(fill='x')

        head = tk.Frame(inner, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text=f'#{pos + 1}  {vname}', bg=BG, fg='#60a5fa',
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        if explicit:
            tk.Button(head, text='✕', bg=BG, fg=C['dim'], relief='flat', bd=0,
                      activebackground='#450a0a', activeforeground=C['red'],
                      command=lambda pid=p['id']: self._remove_from_chain(pid)
                      ).pack(side='right')
        else:
            tk.Label(head, text='(auto)', bg=BG, fg=C['dim'], font=('Segoe UI', 8)).pack(side='right')

        sub = tk.Frame(inner, bg=BG)
        sub.pack(fill='x', pady=(2, 0))
        tk.Label(sub, text=f'Kette: {rng}', bg=BG, fg=C['muted'],
                 font=('Segoe UI', 8)).pack(side='left')
        tk.Button(sub, text='▲', bg=BG, fg=C['muted'], relief='flat', bd=0,
                  command=lambda pid=p['id']: self._move_in_chain(pid, -1)).pack(side='right', padx=1)
        tk.Button(sub, text='▼', bg=BG, fg=C['muted'], relief='flat', bd=0,
                  command=lambda pid=p['id']: self._move_in_chain(pid, 1)).pack(side='right', padx=1)

        flip_var = tk.BooleanVar(value=p.get('flipped', False))
        def toggle_flip(pid=p['id'], v=flip_var):
            pl = next((x for x in self.placements if x['id'] == pid), None)
            if pl:
                pl['flipped'] = v.get()
                self._auto_assign()
                self._render_cv()
                self._render_chain_tab()
                self._schedule_save()
        tk.Checkbutton(inner, text='Gespiegelt (nummeriert rechts nach links)',
                      variable=flip_var, command=toggle_flip,
                      bg=BG, fg=C['text'], selectcolor=C['bg_dark'],
                      activebackground=BG, activeforeground=C['text'],
                      font=('Segoe UI', 8), highlightthickness=0, bd=0,
                      anchor='w').pack(fill='x', pady=(2, 0))

    # ── Run ───────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
