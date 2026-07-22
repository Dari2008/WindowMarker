#!/usr/bin/env python3
"""
dxfExport.py -- Exportiert die platzierten LEDs eines Hauses als DXF-Zeichnung.

DxfDrawing        Bequemer Wrapper um ezdxf: Rechtecke, Linien, Polylinien,
                  Text-Labels -- ohne dass der Aufrufer sich mit
                  ezdxf-Details (modelspace, Layer, Punktlisten)
                  beschaeftigen muss. Alle Koordinaten in BILD-Konvention
                  (Y waechst nach unten); die Y-Achse wird beim Zeichnen
                  automatisch in CAD-Konvention gespiegelt (siehe _fy).
get_placed_leds() Liest aus einem <name>.json-Datensatz alle platzierten,
                  aktiven LEDs -- je einen Eintrag
                  {'x','y','w','h','ledIndex','variantUuid'} pro physischer
                  LED (mit dem Rechteck des von ihr versorgten Fensters,
                  ihrem Ketten-Index, und der Platinen-Platzierung, zu der
                  sie gehoert).
export_dxf()      DIE EINE Funktion, die tatsaechlich die DXF-Datei schreibt.
                  Nimmt die platzierten LEDs eines Hauses (siehe
                  get_placed_leds()) + optionale Gebaeude-Umriss-Box
                  entgegen; sortiert nach Variant-UUID und zeichnet jede
                  Variante auf ihrem eigenen Layer (+ Farbe).

Den projektweiten Export-Einstiegspunkt (alle Haeuser auf einmal, siehe
images.json) gibt es NICHT mehr in diesem Modul -- er lebt als
ledBatchEditor.App._export_project (kombiniert DXF + CSV + footprint-
WxHmm.dxf-Dateien in EINEM Rutsch, siehe dort).
"""

import json
import zlib
from pathlib import Path
from typing import Union

import ezdxf

import pdfHouse
import footprintScale

Rect = Union[dict, tuple]   # {'x','y','w','h'} oder (x, y, w, h[, ...])

DEFAULT_DPI = 150.0   # falls house_data['dpi'] fehlt (identisch zu ledBatchEditor.DEFAULT_DPI)

# ── Gehaeuseteile: Gebaeudekontur (mit/ohne Fensterscheiben) ────────────────
# ALLE tatsaechlich geschnittenen Entities beider Gehaeuseteil-DXFs (siehe
# export_outline_with_panes_dxf/export_outline_only_dxf weiter unten) --
# Aussenkontur, Glasscheiben-Ausschnitte, Footprint-Zungen-Loecher UND
# Rahmenleisten-Loecher -- landen ALLE auf demselben footprintScale.
# CUT_LAYER (frueher vier getrennte Layer): EIN Schnitt-Layer pro Datei,
# damit ein Laser-Programm nicht mehrere Cut-Layer einzeln aktivieren muss.
# edit_outline_with_panes_dxf/edit_outline_only_dxf raeumen beim
# Aktualisieren einer BEREITS exportierten Datei gezielt NUR diesen (und
# footprintScale.ENGRAVE_LAYER, siehe _insert_placement_numbers) per
# _replace_layer_entities() auf, ohne andere, vom Nutzer manuell in
# derselben Datei ergaenzte Layer (z.B. von Hand berechnete Seitenteile/
# Verbinder) anzutasten.
OUTLINE_PANES_LAYER = footprintScale.CUT_LAYER
OUTLINE_ONLY_LAYER = footprintScale.CUT_LAYER
OUTLINE_PANES_FOOTPRINT_LAYER = footprintScale.CUT_LAYER
OUTLINE_FRAME_HOLES_LAYER = footprintScale.CUT_LAYER


class Outline:
    """Gebaeude-Umriss: der EXAKTE, aus dem PDF nachgezeichnete Pfad
    (`polylines`, siehe pdfHouse.load_pdf_house) UND die daraus abgeleitete
    Bounding-Box (`left`/`top`/`right`/`bottom`) -- beide zusammen, nicht
    nur die Box. Der Export zeichnet den echten Pfad (DxfDrawing.
    add_outline_path), die Box bleibt fuer einfache Positions-/
    Groessenberechnungen verfuegbar (z.B. Footprints zentrieren). Die Box
    wird HIER in der Klasse aus dem Pfad berechnet, nicht vom Aufrufer."""

    def __init__(self, polylines: list):
        self.polylines = polylines   # list[list[(x, y)]] -- exakter Pfad
        xs = [x for poly in polylines for x, y in poly]
        ys = [y for poly in polylines for x, y in poly]
        self.left:   float = min(xs)
        self.top:    float = min(ys)
        self.right:  float = max(xs)
        self.bottom: float = max(ys)

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def inner_bbox(self) -> tuple:
        """(left, top, right, bottom) -- die GEMEINSAME (innerste) Bounding-Box
        ueber ALLE Teilpfade von `polylines`, statt der aeusseren Huelle (siehe
        left/top/right/bottom oben, die den GLOBALEN min/max ueber ALLE Punkte
        bilden). Die nachgezeichnete Kontur besteht i.d.R. aus MEHREREN
        einzelnen Linienzuegen (siehe pdfHouse._extract_outline -- jede
        Illustrator-Zeichenoperation wird zu einem eigenen Teilpfad); ragt
        irgendeiner davon (z.B. ein Detail/eine zusaetzliche Linie) weiter
        nach aussen als die anderen, soll der Rahmen-Default (siehe
        led_batch_editor.App._resolve_frame_rect_px) trotzdem nur so weit
        reichen wie ALLE Teilpfade GEMEINSAM -- die Schnittmenge ihrer je
        EIGENEN Bounding-Boxen, nicht die Vereinigung. Bei nur einem
        einzigen Teilpfad identisch zu (left, top, right, bottom). Sind
        Teilpfade EINANDER FREMD (kein gemeinsamer Bereich, z.B. ein
        eigenstaendiges Detail weit ausserhalb der Haupt-Kontur statt einer
        konzentrisch nachgezeichneten Wandstaerke), waere die Schnittmenge
        leer/invertiert -- dann faellt dies auf die aeussere Huelle zurueck,
        statt ein ungueltiges Rechteck zu liefern."""
        lefts, tops, rights, bottoms = [], [], [], []
        for poly in self.polylines:
            xs = [x for x, _y in poly]
            ys = [y for _x, y in poly]
            lefts.append(min(xs))
            tops.append(min(ys))
            rights.append(max(xs))
            bottoms.append(max(ys))
        left, top, right, bottom = max(lefts), max(tops), min(rights), min(bottoms)
        if right <= left or bottom <= top:
            return self.left, self.top, self.right, self.bottom
        return left, top, right, bottom


def _clip_halfplane(points: list, keep, intersect) -> list:
    """Sutherland-Hodgman-Clip EINES geschlossenen Polygons gegen EINE
    Halbebene: `keep(p)` -- ist der Punkt INNERHALB (bleibt erhalten)?
    `intersect(a, b)` -- Schnittpunkt der Kante a->b mit der Clip-Linie
    (nur aufgerufen, wenn genau einer von a/b innerhalb liegt). Gemeinsamer
    Baustein fuer clip_outline_to_frame (3x aufgerufen: links/rechts/unten)."""
    if not points:
        return points
    out = []
    n = len(points)
    for i in range(n):
        curr = points[i]
        prev = points[i - 1]
        curr_in = keep(curr)
        prev_in = keep(prev)
        if curr_in:
            if not prev_in:
                out.append(intersect(prev, curr))
            out.append(curr)
        elif prev_in:
            out.append(intersect(prev, curr))
    return out


def clip_outline_to_frame(polylines: list, frame_left: float | None, frame_right: float | None,
                          frame_bottom: float, frame_top: float | None = None) -> list:
    """Beschneidet `polylines` (siehe Outline.polylines, ECHTE mm) auf
    LINKS/RECHTS/UNTEN gerade Kanten bei frame_left/frame_right/
    frame_bottom. `frame_left`/`frame_right`/`frame_top` sind je OPTIONAL
    (Default fuer `frame_top` None): OHNE eine dieser Kanten wird dort NICHT
    beschnitten (die Kontur darf dort ueber den Rahmen hinausragen, z.B. ein
    Dachgiebel oben oder ein bewusst ueberstehendes Haus links/rechts --
    siehe _draw_outline_with_panes' `clip_left`/`clip_right`, per Haken in
    der Toolbar umschaltbar, siehe led_batch_editor._build); MIT einer Kante
    wird dort gerade abgeschnitten (so verwendet von _draw_outline_only, der
    blanken RUECKSEITE ohne Fensterscheiben, IMMER an allen 4 Seiten -- die
    braucht keine Haken, siehe dort). `frame_bottom` ist NICHT optional --
    unten wird immer beschnitten. Reines Halbebenen-Clipping
    (Sutherland-Hodgman, siehe _clip_halfplane), funktioniert auch fuer eine
    NICHT konvexe Kontur, solange sie dabei zusammenhaengend bleibt.
    Polygone, die komplett ausserhalb landen, fallen weg (leere Punktliste
    wird uebersprungen)."""
    result = []
    for poly in polylines:
        pts = list(poly)
        if frame_left is not None:
            pts = _clip_halfplane(pts, lambda p: p[0] >= frame_left,
                                 lambda a, b: (frame_left, a[1] + (frame_left - a[0]) * (b[1] - a[1]) / (b[0] - a[0])))
        if frame_right is not None:
            pts = _clip_halfplane(pts, lambda p: p[0] <= frame_right,
                                 lambda a, b: (frame_right, a[1] + (frame_right - a[0]) * (b[1] - a[1]) / (b[0] - a[0])))
        pts = _clip_halfplane(pts, lambda p: p[1] <= frame_bottom,
                             lambda a, b: (a[0] + (frame_bottom - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), frame_bottom))
        if frame_top is not None:
            pts = _clip_halfplane(pts, lambda p: p[1] >= frame_top,
                                 lambda a, b: (a[0] + (frame_top - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), frame_top))
        if pts:
            result.append(pts)
    return result


def frame_side_hole_rects_mm(frame_rect: tuple, clip_top: bool = False,
                             clip_left: bool = True, clip_right: bool = True) -> list:
    """(x, y, w, h, open_side)-Rechtecke (ECHTE Haus-mm), die die
    wiederkehrenden Laengskanten-Zungen der 4 Rahmenleisten (footprintScale.
    get_frame_side_points fuer links/rechts, get_frame_top_points fuer
    oben/unten -- siehe frame_strip_tongue_hole_positions) in die
    Hauskontur schneiden. `frame_rect` = (left, top, right, bottom).

    `clip_left`/`clip_right` (analog zu `clip_top`, siehe unten): NUR wenn
    die Kontur auf der jeweiligen Seite ueberhaupt gerade beschnitten wird
    (siehe _draw_outline_with_panes' gleichnamige Parameter/
    clip_outline_to_frame) liegt dort eine echte Kontur-Kante an, an die das
    Loch buendig anschliesst -- dann muss es 'left'/'right'-offen bleiben,
    sonst wuerde die gemeinsame Kante doppelt geschnitten. Ist diese Seite
    NICHT beschnitten (die Kontur ragt dort frei ueber den Rahmen hinaus),
    gibt es keine solche Kante -- das Loch bleibt dann ein normales
    geschlossenes Rechteck (open_side=None), exakt wie beim `clip_top`-Fall.

    Links/rechts-Leisten laufen VERTIKAL (ihre eigene Laengsachse = die
    Haus-Y-Achse) -- deren lokale (x, y, w, h)-Loecher werden daher um 90°
    gedreht eingesetzt (lokale Laenge -> real-Y, lokale Tiefe -> real-X).
    Oben/unten-Leisten laufen HORIZONTAL (keine Drehung noetig).

    `ly` liegt (siehe frame_strip_tongue_hole_positions) komplett auf der
    lokalen 'nach aussen'-Seite (negativ). Fuer die MIN-Kante (links/oben)
    zeigt 'nach aussen' bereits in die richtige Richtung (kleinere Werte),
    daher unveraendert `frame_left/top + ly` uebernommen. Fuer die MAX-Kante
    (rechts/unten) zeigt 'nach aussen' andersrum (groessere Werte) -- daher
    hier gespiegelt (`frame_right/bottom - ly - lh`), sonst wuerden die
    Loecher dort faelschlich ins Hausinnere statt in den Rand ragen.

    `open_side` (5. Tupel-Element, siehe DxfDrawing.add_rect): die AEUSSERE
    Kante jedes Lochs (links/rechts/unten) liegt IMMER exakt auf der
    aussen um die Materialstaerke erweiterten Kontur-Grenze (siehe
    clip_outline_to_frame) -- dort auf 'closed' zu zeichnen wuerde diese
    Kante doppelt schneiden, daher immer offen. Die OBERE Kante liegt nur
    dann auf einer echten Kontur-Grenze, wenn diese Seite ueberhaupt
    beschnitten wird (`clip_top=True`, siehe _draw_outline_only) -- bei der
    sichtbaren Vorderseite (_draw_outline_with_panes, `clip_top=False`,
    Dachgiebel-Ueberstand bleibt oben unbeschnitten) gibt es dort KEINE
    Kontur-Linie zum Anschliessen, die oberen Loecher bleiben also normale
    geschlossene Rechtecke."""
    frame_left, frame_top, frame_right, frame_bottom = frame_rect
    side_length = frame_bottom - frame_top
    top_length = frame_right - frame_left
    rects = []
    for lx, ly, lw, lh in footprintScale.frame_strip_tongue_hole_positions(side_length):
        y = frame_top + lx
        rects.append((frame_left + ly, y, lh, lw, 'left' if clip_left else None))
        rects.append((frame_right - ly - lh, y, lh, lw, 'right' if clip_right else None))
    for lx, ly, lw, lh in footprintScale.frame_strip_tongue_hole_positions(top_length):
        x = frame_left + lx
        rects.append((x, frame_top + ly, lw, lh, 'top' if clip_top else None))
        rects.append((x, frame_bottom - ly - lh, lw, lh, 'bottom'))
    return rects


def _rect_xywh(rect: Rect) -> tuple:
    if isinstance(rect, dict):
        return rect['x'], rect['y'], rect['w'], rect['h']
    x, y, w, h = rect[:4]
    return x, y, w, h


def _rect_center(rect: Rect) -> tuple:
    x, y, w, h = _rect_xywh(rect)
    return x + w / 2, y + h / 2


class DxfDrawing:
    """Duenner Komfort-Wrapper um ein ezdxf-Dokument."""

    def __init__(self, dxfversion: str = 'R2010'):
        self.doc = ezdxf.new(dxfversion)
        # ezdxf.new() setzt $INSUNITS defaultmaessig auf 6 (Meter) -- ALLE
        # Koordinaten in dieser Datei sind aber echte MILLIMETER (siehe
        # get_placed_leds/house_outline). Ohne diese Korrektur liest jedes
        # einheitenbewusste CAD-/Laserschneide-Programm (z.B. beim Import in
        # ein mm-Arbeitsblatt) die Zahlen als Meter und skaliert sie beim
        # Uebernehmen um den Faktor 1000 hoch (aus 293mm werden angezeigte
        # 293000mm) -- genau das "Dateien sind viel zu gross"-Symptom.
        self.doc.header['$INSUNITS'] = 4   # 4 = Millimeter (siehe ezdxf.units)
        self.msp = self.doc.modelspace()
        self._layers: set = set()

    @classmethod
    def load(cls, path) -> 'DxfDrawing':
        """Oeffnet eine BESTEHENDE DXF-Datei zum Weiterbearbeiten (statt eine
        neue, leere zu erzeugen wie __init__)."""
        self = cls.__new__(cls)
        self.doc = ezdxf.readfile(str(path))
        self.msp = self.doc.modelspace()
        self._layers = {layer.dxf.name for layer in self.doc.layers}
        return self

    def _ensure_layer(self, name: str, color: int) -> str:
        if name not in self._layers:
            if name not in self.doc.layers:
                self.doc.layers.add(name, color=color)
            self._layers.add(name)
        return name

    @staticmethod
    def _fy(y: float) -> float:
        """Spiegelt eine Y-Koordinate von Bild-Konvention (Y waechst nach
        UNTEN, Ursprung oben links -- wie alle Koordinaten in diesem Modul,
        siehe get_placed_leds/house_outline) in CAD-Konvention (Y waechst
        nach OBEN) um -- einfache Negation reicht (reine Spiegeltransformation,
        erhaelt alle relativen Positionen/Ausrichtungen exakt). OHNE diese
        Spiegelung wuerde jede Zeichnung, die per add_rect/add_line/
        add_polyline/add_text erzeugt wird, in einem CAD-Programm auf dem
        Kopf stehen (was oben im Bild war, wuerde unten im DXF landen und
        umgekehrt)."""
        return -y

    def add_rect(self, x: float, y: float, w: float, h: float,
                *, layer: str = 'WINDOWS', color: int = 3,
                open_side: str | None = None) -> None:
        """Rechteck an Position (x, y) [linke obere Ecke, BILD-Konvention]
        mit Breite w und Hoehe h -- wie bei den Fenster-Eintraegen in
        <name>.json. Die Y-Achse wird beim Zeichnen automatisch in
        CAD-Konvention gespiegelt (siehe _fy).

        `open_side` ('left'/'right'/'top'/'bottom', BILD-Konvention wie bei
        (x, y) selbst -- 'top' = die y-Kante, 'bottom' = die y+h-Kante):
        WENN eine Kante dieses Rechtecks exakt mit einer ANDEREN, bereits
        vorhandenen Kontur-Linie zusammenfaellt (z.B. ein Zungen-Loch, das
        buendig an der beschnittenen Hauskontur liegt, siehe
        frame_side_hole_rects_mm) wuerde diese Kante sonst DOPPELT
        gezeichnet/geschnitten -- `open_side` laesst genau diese eine Kante
        weg (offene 3-seitige Linie statt geschlossenem Rechteck)."""
        self._ensure_layer(layer, color)
        yt, yb = self._fy(y), self._fy(y + h)
        if open_side is None:
            pts = [(x, yt), (x + w, yt), (x + w, yb), (x, yb)]
            self.msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': layer})
            return
        order = {
            'top':    [(x, yt), (x, yb), (x + w, yb), (x + w, yt)],
            'bottom': [(x, yb), (x, yt), (x + w, yt), (x + w, yb)],
            'left':   [(x, yt), (x + w, yt), (x + w, yb), (x, yb)],
            'right':  [(x + w, yt), (x, yt), (x, yb), (x + w, yb)],
        }[open_side]
        self.msp.add_lwpolyline(order, close=False, dxfattribs={'layer': layer})

    def add_line(self, x1: float, y1: float, x2: float, y2: float,
                *, layer: str = 'WIRING', color: int = 5) -> None:
        """Linie von (x1, y1) nach (x2, y2) [BILD-Konvention, siehe add_rect]."""
        self._ensure_layer(layer, color)
        self.msp.add_line((x1, self._fy(y1)), (x2, self._fy(y2)), dxfattribs={'layer': layer})

    def add_line_point_to_rect(self, point: tuple, rect: Rect,
                               *, layer: str = 'WIRING', color: int = 5) -> None:
        """Linie von einem Punkt (x, y) zum Mittelpunkt eines Rechtecks."""
        cx, cy = _rect_center(rect)
        self.add_line(point[0], point[1], cx, cy, layer=layer, color=color)

    def add_line_rect_to_rect(self, rect_a: Rect, rect_b: Rect,
                              *, layer: str = 'WIRING', color: int = 5) -> None:
        """Linie zwischen den Mittelpunkten zweier Rechtecke."""
        ax, ay = _rect_center(rect_a)
        bx, by = _rect_center(rect_b)
        self.add_line(ax, ay, bx, by, layer=layer, color=color)

    def add_outline(self, left: float, top: float, right: float, bottom: float,
                    *, layer: str = 'OUTLINE', color: int = 7) -> None:
        """Rechteckige Bounding-Box aus den vier Kanten -- fuer Faelle, in
        denen nur eine grobe Box gebraucht wird. Fuer den echten Gebaeude-
        Umriss siehe add_outline_path()."""
        self.add_rect(left, top, right - left, bottom - top, layer=layer, color=color)

    def add_polyline(self, points: list, *, closed: bool = False,
                     layer: str = 'OUTLINE', color: int = 7) -> None:
        """Beliebige Polylinie aus einer Punktliste [(x, y), ...] [BILD-
        Konvention, siehe add_rect] -- z.B. fuer einen exakten,
        nicht-rechteckigen Gebaeude-Umriss."""
        self._ensure_layer(layer, color)
        pts = [(x, self._fy(y)) for x, y in points]
        self.msp.add_lwpolyline(pts, close=closed, dxfattribs={'layer': layer})

    def add_outline_path(self, outline: 'Outline',
                         *, layer: str = 'OUTLINE', color: int = 7) -> None:
        """Zeichnet den EXAKTEN Gebaeude-Umriss -- alle Polylinien aus
        outline.polylines (der aus dem PDF nachgezeichnete Pfad) -- statt
        nur seiner Bounding-Box."""
        for poly in outline.polylines:
            self.add_polyline(poly, layer=layer, color=color)

    def add_text(self, text: str, x: float, y: float,
                *, height: float = 10.0, layer: str = 'LABELS', color: int = 2) -> None:
        """Textbeschriftung (z.B. LED-/Ketten-Index) mit Mittelpunkt bei
        (x, y) [BILD-Konvention, siehe add_rect]."""
        self._ensure_layer(layer, color)
        e = self.msp.add_text(text, dxfattribs={'layer': layer, 'height': height})
        e.set_placement((x, self._fy(y)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.saveas(str(path))
        return path


def get_placed_leds(house_data: dict) -> list:
    """Alle platzierten, aktiven LEDs eines Hauses -- pro physischer LED
    (nicht pro Fenster: ein Fenster kann von mehreren LEDs versorgt werden)
    ein Eintrag {'x','y','w','h','ledIndex','variantUuid','width_mm',
    'height_mm','batch_x','batch_y','flipped'} mit dem Rechteck des
    Fensters, das diese LED versorgt, ihrem Ketten-Index (chainIndex), der
    ID der physischen Platinen-PLATZIERUNG (ledBatches[].id), zu der sie
    gehoert -- platziert man eine Variante mit 3 LEDs, teilen sich alle 3
    dieselbe variantUuid; eine andere Platzierung (auch derselben
    Varianten-ART, z.B. wieder "70mm") bekommt eine ANDERE -- und der PRO
    PLATZIERUNG eintragbaren Footprint-Groesse (ledBatches[].width_mm/
    height_mm, siehe ledBatchEditor.py's Footprint-B×H-Feldern je
    Platzierungskarte); `None`, wenn diese Platzierung keine eigene hat
    (dann gilt beim Export der Default der Variante, siehe
    resolve_footprint_size). 'batch_x'/'batch_y' (mm, wie 'x'/'y') und
    'flipped' sind der ROHE Anker/Spiegel-Zustand der PLATZIERUNG selbst
    (ledBatches[].x/y/flipped, NICHT das Fenster-Rechteck) -- fuer den
    Footprint-Anker (siehe _footprint_anchor), der STARR an der Platzierung
    haengt, nicht an den echten Fenstern (die koennen bewusst abweichen,
    wenn eine Platzierung nicht exakt ueber ihrer Fenstermitte sitzt).

    Liest direkt aus house_data['ledBatches'][*]['leds'] (die eigentliche
    Quelle der Wahrheit), statt aus windows[].ledIndex zu lesen -- letzteres
    behaelt bei mehreren LEDs auf demselben Fenster nur die zuletzt von
    _recompute_chain geschriebene LED, waehrend hier jede einzelne platzierte
    LED einen eigenen Eintrag bekommt.

    Die Fensterrechtecke (windows[].{x,y,w,h}) UND der Platzierungs-Anker
    (ledBatches[].x/y) liegen im JSON in BILD-PIXELN vor, nicht in mm --
    werden hier aber ueber house_data['dpi'] (dieselbe Umrechnung wie
    ledBatchEditor.px_per_mm: dpi / 25.4) in ECHTE mm umgerechnet, damit sie
    im DXF dieselbe Einheit wie die LED-Footprint-Kontur (footprints/
    Led-Footprint.dxf, echte mm) haben. Ohne diese Umrechnung wurden
    Fensterrechtecke mit ihrem rohen Pixelwert als "mm" gezeichnet -- bei
    ueblichen Aufloesungen ein Vielfaches ihrer echten Groesse, wodurch die
    (korrekt in mm bemessene) Footprint-Kontur daneben winzig aussah."""
    px_per_mm = (house_data.get('dpi') or DEFAULT_DPI) / 25.4
    windows = house_data.get('windows', [])
    placed = []
    for batch in house_data.get('ledBatches', []):
        variant_uuid = batch.get('id')
        width_mm = batch.get('width_mm')
        height_mm = batch.get('height_mm')
        batch_x = (batch.get('x') or 0) / px_per_mm
        batch_y = (batch.get('y') or 0) / px_per_mm
        flipped = bool(batch.get('flipped'))
        for led in batch.get('leds', []):
            if not led.get('enabled'):
                continue
            wi = led.get('windowIndex')
            if wi is None or not (0 <= wi < len(windows)):
                continue
            w = windows[wi]
            placed.append({
                'x': w['x'] / px_per_mm, 'y': w['y'] / px_per_mm,
                'w': w['w'] / px_per_mm, 'h': w['h'] / px_per_mm,
                'ledIndex': led.get('chainIndex'),
                'variantUuid': variant_uuid,
                'width_mm': width_mm,
                'height_mm': height_mm,
                'batch_x': batch_x,
                'batch_y': batch_y,
                'flipped': flipped,
            })
    return placed


def house_outline(pdf_path: Path, px_per_mm: float = 1.0) -> Outline | None:
    """Liest die Gebaeude-Kontur aus dem Quell-PDF (siehe pdfHouse.py) und
    baut daraus ein Outline-Objekt -- den EXAKTEN Pfad (die nachgezeichneten
    Polylinien), nicht nur dessen Bounding-Box (die berechnet Outline selbst
    aus dem Pfad). Die Kontur selbst wird nicht im JSON gespeichert, sondern
    bei jedem Laden neu aus dem PDF extrahiert (siehe windowTool.py) --
    daher hier derselbe Weg. Gibt None zurueck, wenn keine PDF-Quelle
    vorhanden ist oder keine Kontur gefunden wurde.

    Die Kontur liegt (wie die Fensterrechtecke) in BILD-PIXELN vor; `px_per_mm`
    (siehe get_placed_leds) rechnet sie in dieselben echten mm um, in denen
    auch die restliche Zeichnung steht -- Default 1.0 laesst sie unveraendert
    (Bild-px), falls kein DPI-Wert bekannt ist."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        return None
    try:
        _img, outline_polylines = pdfHouse.load_pdf_house(pdf_path)
    except Exception:
        return None
    if not outline_polylines:
        return None
    if px_per_mm != 1.0:
        outline_polylines = [[(x / px_per_mm, y / px_per_mm) for x, y in poly]
                             for poly in outline_polylines]
    return Outline(outline_polylines)


def _replace_layer_entities(dwg: 'DxfDrawing', layer: str) -> None:
    """Loescht alle vorhandenen Entities auf `layer` (falls die Zeichnung per
    DxfDrawing.load() aus einer BEREITS exportierten Datei stammt) -- damit
    ein wiederholter edit_*_dxf()-Aufruf DIESES eine Teil aktualisiert statt
    es bei jedem Lauf zu duplizieren, waehrend alles, was der Nutzer selbst
    manuell in einem CAD-Programm auf ANDEREN Layern ergaenzt hat (z.B. von
    Hand berechnete Seitenteile/Verbinder), unangetastet bleibt."""
    for e in list(dwg.msp.query(f'*[layer=="{layer}"]')):
        dwg.msp.delete_entity(e)


def _draw_outline_with_panes(dwg: 'DxfDrawing', outline: 'Outline', panes: list,
                             entries: list | None = None, variant_size: tuple | None = None,
                             variant_leds: list | None = None,
                             frame_rect: tuple | None = None,
                             placement_numbers: dict | None = None,
                             clip_left: bool = True, clip_right: bool = True) -> None:
    """Zeichnet den echten Gebaeude-Umriss (siehe Outline.polylines) MIT
    ALLEN Glasscheiben-Ausschnitten aus `panes` (bereits in ECHTEN mm, siehe
    get_placed_leds()'s Umrechnung -- NUR die tatsaechliche Glasflaeche, z.B.
    windowTool._svg_rects()/house_data['glassPanes']: einzeln markierte
    Scheiben PLUS jedes Fenster ohne eigene Scheiben-Unterteilung als Ganzes
    -- NICHT der volle Fensterrahmen, der Rahmen selbst bleibt Material)
    PLUS (falls `entries` angegeben, siehe get_placed_leds()) je Platzierung
    NUR deren Zungen-Loecher/Ausschnitte (siehe footprintScale.
    get_footprint_points) -- dieselben Positionen wie im LED-/Platinen-
    Export (siehe _insert_footprints), damit die Bodenplatten-/Seitenteil-
    Zungen spaeter durch genau diese Loecher passen. OHNE die reine
    Skizzen-Aussenlinie (Layer 'SKETCH') -- die ist nur eine Ausrichthilfe
    beim Editieren, kein echter Schnitt (siehe _insert_footprints'
    `only_layers`). Kontur, Scheiben-Ausschnitte, Footprint-Loecher UND
    Rahmenleisten-Loecher landen ALLE auf demselben OUTLINE_PANES_LAYER
    (== footprintScale.CUT_LAYER) -- EIN Schnitt-Layer fuer die ganze Datei.

    `placement_numbers` ({variantUuid: nummer}, siehe led_batch_editor.
    App._export_project): WENN angegeben, wird an JEDER Platzierung ihre
    Nummer graviert (footprintScale.ENGRAVE_LAYER, siehe
    _insert_placement_numbers) -- dieselbe Nummer wie auf den zugehoerigen
    Bodenplatten-/Seitenteil-Kopien im kombinierten Teile-Blatt, damit sich
    jedes geschnittene Teil eindeutig seinem Fenster zuordnen laesst.

    `frame_rect` ((left, top, right, bottom), ECHTE mm, siehe
    clip_outline_to_frame): WENN angegeben, wird die Kontur links/rechts/
    unten beschnitten (oben NICHT -- dort darf sie ueber den Rahmen
    hinausragen, siehe dort) -- NICHT an `frame_rect` selbst (der inneren,
    im Editor gezogenen Linie), sondern an dessen AEUSSERER Kante (um
    footprintScale.FRAME_MATERIAL_THICKNESS_MM nach aussen versetzt, siehe
    dort) -- die Zungen-Loecher (siehe frame_side_hole_rects_mm) liegen
    GENAU in diesem Rand-Streifen, die Kontur muss also bis dorthin reichen,
    sonst waeren die Loecher ausserhalb der geschnittenen Flaeche. `top`
    wird hier nicht gebraucht (nur links/rechts/unten werden beschnitten),
    bleibt aber Teil der Signatur fuer den gemeinsamen (left,top,right,
    bottom)-Rahmen-Tupel, das auch die Rahmenleisten-Laengen bestimmt.

    `clip_left`/`clip_right` (Default True = bisheriges Verhalten): schalten
    JE EINZELN ab, ob links/rechts ueberhaupt beschnitten wird -- per Haken
    in der Toolbar umschaltbar (siehe led_batch_editor._build/
    _export_project), z.B. wenn das Haus an einer Seite bewusst ueber den
    Rahmen hinausragen soll. Wirkt NUR hier (der sichtbaren Vorderseite mit
    Fensterscheiben) -- die blanke Rueckseite (_draw_outline_only) wird
    davon unabhaengig IMMER an allen 4 Seiten gerade beschnitten."""
    polylines = outline.polylines
    if frame_rect is not None:
        frame_left, _frame_top, frame_right, frame_bottom = frame_rect
        thick = footprintScale.FRAME_MATERIAL_THICKNESS_MM
        polylines = clip_outline_to_frame(polylines,
                                         frame_left - thick if clip_left else None,
                                         frame_right + thick if clip_right else None,
                                         frame_bottom + thick)
    for poly in polylines:
        dwg.add_polyline(poly, closed=True, layer=OUTLINE_PANES_LAYER, color=7)
    for p in panes:
        dwg.add_rect(p['x'], p['y'], p['w'], p['h'], layer=OUTLINE_PANES_LAYER, color=6)
    if entries:
        _insert_footprints(dwg, entries, variant_size, layer=OUTLINE_PANES_FOOTPRINT_LAYER,
                          variant_leds=variant_leds, only_layers={footprintScale.CUT_LAYER})
        if placement_numbers:
            _insert_placement_numbers(dwg, entries, placement_numbers, variant_size, variant_leds)
    if frame_rect is not None:
        for x, y, w, h, open_side in frame_side_hole_rects_mm(frame_rect, clip_top=False,
                                                              clip_left=clip_left, clip_right=clip_right):
            dwg.add_rect(x, y, w, h, layer=OUTLINE_FRAME_HOLES_LAYER, color=6, open_side=open_side)


def export_outline_with_panes_dxf(outline: 'Outline', panes: list, out_path,
                                  entries: list | None = None,
                                  variant_size: tuple | None = None,
                                  variant_leds: list | None = None,
                                  frame_rect: tuple | None = None,
                                  placement_numbers: dict | None = None,
                                  clip_left: bool = True, clip_right: bool = True) -> Path:
    """Schreibt EINE NEUE DXF-Datei mit dem Gebaeude-Umriss + allen
    Glasscheiben-Ausschnitten + (mit `entries`) den Zungen-Loechern
    ("Gebaeudekontur mit Fensterscheiben"). Ueberschreibt `out_path`
    komplett -- fuer eine bereits exportierte Datei stattdessen zu
    AKTUALISIEREN (statt zu ueberschreiben), siehe edit_outline_with_panes_dxf().
    `clip_left`/`clip_right` siehe _draw_outline_with_panes."""
    dwg = DxfDrawing()
    _draw_outline_with_panes(dwg, outline, panes, entries, variant_size, variant_leds,
                            frame_rect, placement_numbers, clip_left, clip_right)
    return dwg.save(out_path)


def edit_outline_with_panes_dxf(outline: 'Outline', panes: list, path,
                                entries: list | None = None,
                                variant_size: tuple | None = None,
                                variant_leds: list | None = None,
                                frame_rect: tuple | None = None,
                                placement_numbers: dict | None = None,
                                clip_left: bool = True, clip_right: bool = True) -> Path:
    """Aktualisiert die Gebaeudekontur + Glasscheiben-Ausschnitte + Zungen-
    Loecher + Platzierungs-Nummern in einer BEREITS exportierten DXF-Datei
    bei `path` (per DxfDrawing.load() geoeffnet) -- ersetzt dazu nur die
    vorhandenen Entities auf OUTLINE_PANES_LAYER und footprintScale.
    ENGRAVE_LAYER (siehe _replace_layer_entities), laesst aber ALLES ANDERE
    in der Datei (z.B. vom Nutzer manuell auf eigenen Layern ergaenzte
    Seitenteile/Verbinder) unangetastet. Existiert `path` noch nicht,
    verhaelt sich das wie export_outline_with_panes_dxf() (legt die Datei
    neu an). `clip_left`/`clip_right` siehe _draw_outline_with_panes."""
    path = Path(path)
    dwg = DxfDrawing.load(path) if path.is_file() else DxfDrawing()
    _replace_layer_entities(dwg, OUTLINE_PANES_LAYER)
    _replace_layer_entities(dwg, footprintScale.ENGRAVE_LAYER)
    _draw_outline_with_panes(dwg, outline, panes, entries, variant_size, variant_leds,
                            frame_rect, placement_numbers, clip_left, clip_right)
    return dwg.save(path)


def _draw_outline_only(dwg: 'DxfDrawing', outline: 'Outline',
                       frame_rect: tuple | None = None) -> None:
    """Zeichnet NUR den echten Gebaeude-Umriss (siehe Outline.polylines),
    OHNE Fensteroeffnungen, auf OUTLINE_ONLY_LAYER (== footprintScale.
    CUT_LAYER, EIN Schnitt-Layer wie ueberall sonst). `frame_rect` --
    beschneidet links/rechts/unten UND oben an der AEUSSEREN Rahmenkante
    (frame_rect +/- Materialstaerke) -- anders als _draw_outline_with_panes
    (die sichtbare Vorderseite, dort bleibt oben ein Dachgiebel-Ueberstand
    bewusst erhalten): diese blanke Rueckseite ohne Fensterscheiben braucht
    den Ueberstand nicht und wird komplett gerade abgeschnitten."""
    polylines = outline.polylines
    if frame_rect is not None:
        frame_left, frame_top, frame_right, frame_bottom = frame_rect
        thick = footprintScale.FRAME_MATERIAL_THICKNESS_MM
        polylines = clip_outline_to_frame(polylines, frame_left - thick, frame_right + thick,
                                         frame_bottom + thick, frame_top - thick)
    for poly in polylines:
        dwg.add_polyline(poly, closed=True, layer=OUTLINE_ONLY_LAYER, color=7)
    if frame_rect is not None:
        for x, y, w, h, open_side in frame_side_hole_rects_mm(frame_rect, clip_top=True):
            dwg.add_rect(x, y, w, h, layer=OUTLINE_FRAME_HOLES_LAYER, color=6, open_side=open_side)


def export_outline_only_dxf(outline: 'Outline', out_path, frame_rect: tuple | None = None) -> Path:
    """Schreibt EINE NEUE DXF-Datei mit NUR dem Gebaeude-Umriss (keine
    Fensteroeffnungen) -- siehe edit_outline_only_dxf() zum Aktualisieren
    einer bereits exportierten Datei."""
    dwg = DxfDrawing()
    _draw_outline_only(dwg, outline, frame_rect)
    return dwg.save(out_path)


def edit_outline_only_dxf(outline: 'Outline', path, frame_rect: tuple | None = None) -> Path:
    """Aktualisiert NUR den Gebaeude-Umriss in einer BEREITS exportierten
    DXF-Datei bei `path` -- wie edit_outline_with_panes_dxf(), aber fuer
    OUTLINE_ONLY_LAYER (ohne Fensteroeffnungen)."""
    path = Path(path)
    dwg = DxfDrawing.load(path) if path.is_file() else DxfDrawing()
    _replace_layer_entities(dwg, OUTLINE_ONLY_LAYER)
    _replace_layer_entities(dwg, OUTLINE_FRAME_HOLES_LAYER)
    _draw_outline_only(dwg, outline, frame_rect)
    return dwg.save(path)


def _variant_layer(variant_uuid) -> str:
    return f'VARIANT_{variant_uuid}' if variant_uuid else 'VARIANT_UNKNOWN'


def _variant_color(variant_uuid) -> int:
    """Deterministische ACI-Farbe (1-254) aus der Variant-UUID -- damit
    dieselbe Platzierung bei jedem Export dieselbe Farbe bekommt (Pythons
    eingebautes hash() ist pro Prozess zufaellig gesalzen, daher zlib.crc32
    statt hash())."""
    if not variant_uuid:
        return 7
    return 1 + (zlib.crc32(str(variant_uuid).encode()) % 254)


FOOTPRINT_WIDTH  = 75  # mm -- Fallback, falls weder Platzierung noch Variante eine eigene Groesse setzen
FOOTPRINT_HEIGHT = 60  # mm


def resolve_footprint_size(variant_size: tuple | None, leds: list) -> tuple:
    """Aufloesungsreihenfolge fuer die Footprint-Groesse EINER Platzierung
    (Gegenstueck zu ledBatchEditor.resolve_footprint_size): PLATZIERUNGS-
    Override (leds[0]['width_mm']/['height_mm'], siehe get_placed_leds) >
    VARIANTEN-Default (`variant_size`, z.B. aus variant['footprint_width_mm']/
    ['footprint_height_mm']) > FOOTPRINT_WIDTH/HEIGHT. Es gibt keinen
    benannten Footprint-"Typ" mehr --
    jede Platzierung/Variante traegt ihre Groesse direkt als Zahl."""
    w = leds[0].get('width_mm') if leds else None
    h = leds[0].get('height_mm') if leds else None
    if w and h:
        return w, h
    if variant_size:
        return variant_size
    return FOOTPRINT_WIDTH, FOOTPRINT_HEIGHT


def _footprint_scaled_points(width_mm: float, height_mm: float,
                             only_layers: set | None = None) -> list:
    """Generiert die Footprint-Kontur in der gegebenen Groesse, auf (0, 0)
    normiert. footprintScale.get_footprint_points() gibt dazu ein
    EIGENSTAENDIGES ezdxf-Dokument zurueck (nicht nur rohe Punkte) -- die
    LWPOLYLINE-Punkte werden hier aus dessen modelspace() ausgelesen, damit
    der Rest dieses Moduls (Anker/Uebersetzung, Y-Flip beim Zeichnen) wie
    gewohnt mit reinen (x, y)-Punktlisten weiterarbeiten kann. Gibt eine
    Liste von (points, closed)-Paaren zurueck -- `closed` wird 1:1 von der
    Quell-Entity uebernommen (siehe get_footprint_points' `open_side`:
    Loecher, deren eine Kante buendig an der SKETCH-Aussenkontur liegt,
    sind dort BEWUSST offen/3-seitig, damit diese Kante nicht doppelt
    gezeichnet/geschnitten wird -- diese Offenheit muss beim Wiedereinfuegen
    erhalten bleiben, siehe _insert_footprints).

    `only_layers` (z.B. `{'PINS'}`): WENN angegeben, werden NUR Polylinien
    von genau diesen Layern uebernommen -- get_footprint_points() legt neben
    den echten Zungen-Loechern (Layer 'PINS') auch eine reine Skizzenlinie
    an (Layer 'SKETCH', width_mm x height_mm-Aussenmass, KEIN echter
    Laserschnitt, nur eine Ausrichthilfe). Ohne `only_layers` (None) werden
    ALLE Layer uebernommen (bisheriges Verhalten, siehe export_dxf, wo die
    Skizzenlinie als Referenz erwuenscht bleibt).

    Y WIRD HIER GESPIEGELT (height_mm - y): footprintScale.py rechnet in
    PHYSISCHER Konvention (Y=0 = UNTERKANTE, wo die Bodenplatten-Zungen
    sitzen, Y=height_mm = OBERKANTE, naeher an den LEDs), waehrend
    _footprint_anchor/_insert_footprints (wie der Rest dieses Moduls) in
    BILD-Konvention rechnen (Y=0 = oben, waechst nach unten). Ohne diese
    Spiegelung landet die gesamte Footprint-Kontur auf dem Kopf: die
    Unterkanten-Merkmale (Bodenplatten-/Seitenteil-Zungen-Loecher) wuerden
    naeher an den LEDs enden als die eigentliche Oberkante -- ein Bug, der
    erst sichtbar wurde, als der Footprint eigene (nicht mehr Y-symmetrische)
    Loecher bekam (siehe get_footprint_points)."""
    doc = footprintScale.get_footprint_points(width_mm, height_mm)
    msp = doc.modelspace()
    entities = msp.query('LWPOLYLINE')
    if only_layers is not None:
        entities = [e for e in entities if e.dxf.layer in only_layers]
    return [([(pt[0], height_mm - pt[1]) for pt in e.get_points()], e.closed) for e in entities]


def _footprint_placement_transform(leds: list, width_mm: float, height_mm: float,
                                   variant_leds: list | None = None):
    """Gibt eine Funktion `transform(fx, fy) -> (x, y)` zurueck, die einen
    LOKALEN Footprint-Punkt (siehe _footprint_scaled_points, fx in
    [0, width_mm], fy in [0, height_mm]) in ABSOLUTE Haus-mm umrechnet.

    Der Footprint haengt STARR an den LEDs DIESER Platzierung (mittig,
    siehe footprintScale.led_footprint_offset_mm) -- NICHT an den echten
    Fenstern, die sie gerade zufaellig beleuchtet (eine fruehere Version
    zentrierte stattdessen ueber der tatsaechlichen Ausdehnung der
    versorgten Fenster; dadurch landete der Footprint an einer anderen
    Stelle als im Editor, sobald eine Platzierung bewusst nicht exakt ueber
    ihrer Fenstermitte sass). `variant_leds` (die LED-Vorlage der Variante,
    x_mm/y_mm) plus `leds[0]['batch_x']/['batch_y']/['flipped']` (der ROHE
    Anker/Spiegel-Zustand der Platzierung selbst, siehe get_placed_leds)
    ergeben GENAU dieselbe Position wie ledBatchEditor.led_batch_editor.
    footprint_image_points -- beide rufen dieselbe Formel auf
    (footprintScale.led_footprint_offset_mm), damit Editor-Vorschau und
    tatsaechlicher Export niemals auseinanderlaufen.

    Bei gespiegelten Platzierungen (`flipped`) wird `fx` PRO PUNKT gespiegelt
    (nicht nur ein fester Versatz addiert -- die Spiegelachse ist
    `mirror_w` (die eigene Breite der LED-Vorlage), NICHT width_mm), exakt
    wie ledBatchEditor._footprint_geometry_image das tut."""
    if not leds:
        return lambda fx, fy: (fx, fy)
    batch_x = leds[0].get('batch_x', 0.0)
    batch_y = leds[0].get('batch_y', 0.0)
    flipped = leds[0].get('flipped', False)
    dx, dy, mirror_w = footprintScale.led_footprint_offset_mm(variant_leds or [], width_mm, height_mm)

    def transform(fx, fy):
        lx = dx + fx
        if flipped and variant_leds:
            lx = mirror_w - lx
        return batch_x + lx, batch_y + dy + fy

    return transform


def format_footprint_size(width_mm: float, height_mm: float) -> str:
    """Formatiert eine Footprint-Groesse als 'WxHmm' (z.B. '10x100mm', ohne
    ueberfluessige Nachkommastellen) -- EIN Format fuer BOM-Zeilen (siehe
    csvExport.get_part_counts) UND den Dateinamen der zugehoerigen
    footprint-WxHmm.dxf (siehe collect_footprint_sizes/windowTool.py's
    kombinierter Export), damit CSV-'filename'-Spalte und tatsaechlich
    geschriebener Dateiname garantiert uebereinstimmen."""
    return f'{width_mm:g}x{height_mm:g}mm'


def collect_footprint_sizes(entries: list, variant_size: tuple | None = None) -> set:
    """Alle DISTINKTEN (width_mm, height_mm)-Footprint-Groessen, die unter
    `entries` (siehe get_placed_leds) tatsaechlich vorkommen -- je
    Platzierung (variantUuid-Gruppe) aufgeloest ueber resolve_footprint_size.
    Genutzt von csvExport.py (BOM-Zeilen) UND windowTool.py (kombinierter
    Export: schreibt fuer jede hier gefundene Groesse eine eigene
    footprint-WxHmm.dxf, siehe footprintScale.export_all_footprints)."""
    leds_by_variant: dict = {}
    for led in entries:
        leds_by_variant.setdefault(led.get('variantUuid'), []).append(led)
    return {resolve_footprint_size(variant_size, leds) for leds in leds_by_variant.values()}


def _insert_footprints(dwg: 'DxfDrawing', entries: list,
                       variant_size: tuple | None = None, layer: str | None = None,
                       variant_leds: list | None = None,
                       only_layers: set | None = None) -> None:
    """Fuegt fuer JEDE Platzierung (gruppiert nach variantUuid) ihre
    Footprint-Kontur ein -- Groesse aufgeloest ueber resolve_footprint_size
    (Platzierungs-Override aus `leds[0]`, sonst der hier uebergebene
    `variant_size`, sonst FOOTPRINT_WIDTH/HEIGHT). Wird sowohl von
    export_dxf() (LED-/Platinen-Datei, `layer=None` -- Default-Layer '0',
    `only_layers=None` -- Skizzenlinie + Loecher, dient dort als sichtbare
    Referenz) als auch von _draw_outline_with_panes() (Zungen-Loecher AUF
    der Fensterscheiben-Kontur, `layer=OUTLINE_PANES_FOOTPRINT_LAYER`,
    `only_layers={'PINS'}` -- NUR die echten Loecher/Ausschnitte, OHNE die
    reine Skizzen-Aussenlinie, die dort kein echter Schnitt waere) verwendet,
    damit beide GENAU dieselben Footprint-Positionen zeichnen. Siehe
    `only_layers` bei _footprint_scaled_points fuer die Filterung selbst.

    `variant_leds` (die LED-Vorlage der Variante, x_mm/y_mm -- siehe
    _footprint_placement_transform) bestimmt den STARREN Anker relativ zu
    den LEDs jeder Platzierung; ohne sie (z.B. alter Aufrufer, der sie noch
    nicht mitgibt) faellt die Position auf (0, 0) relativ zur Platzierung
    zurueck (kein Absturz, aber vermutlich nicht die gewuenschte Stelle).

    Zeichnet ganz normal ueber add_polyline() (reine (x, y)-Punktlisten,
    kein ezdxf.Importer/entity.transform() -- LWPOLYLINE-Entities tragen ein
    eigenes OCS/eine Extrusionsrichtung, ein SPIEGEL-Transform darauf kann
    ezdxf dazu bringen, die OCS-Basis neu zu berechnen, wodurch die
    zurueckgelesenen 2D-Punkte ZUSAETZLICH ungewollt an der X-Achse
    gespiegelt wuerden -- siehe DxfDrawing._fy fuer den regulaeren
    Bild-zu-CAD-Y-Flip, den add_polyline() bereits korrekt anwendet)."""
    leds_by_variant: dict = {}
    for led in entries:
        leds_by_variant.setdefault(led.get('variantUuid'), []).append(led)
    for leds in leds_by_variant.values():
        width_mm, height_mm = resolve_footprint_size(variant_size, leds)
        polylines = _footprint_scaled_points(width_mm, height_mm, only_layers=only_layers)
        if not polylines:
            continue
        transform = _footprint_placement_transform(leds, width_mm, height_mm, variant_leds)
        for poly, closed in polylines:
            pts = [transform(fx, fy) for fx, fy in poly]
            dwg.add_polyline(pts, closed=closed, layer=layer or '0', color=7)


def _insert_placement_numbers(dwg: 'DxfDrawing', entries: list, placement_numbers: dict,
                              variant_size: tuple | None = None,
                              variant_leds: list | None = None) -> None:
    """Graviert (auf footprintScale.ENGRAVE_LAYER, NIE auf dem Schnitt-Layer
    -- eine Gravur darf nicht versehentlich mitgeschnitten werden) an JEDER
    Platzierung (gruppiert nach variantUuid, wie _insert_footprints) an
    JEDER der 5 Zungen-Loch-Positionen aus footprintScale.
    footprint_hole_anchors (bottom/outer_left/outer_right/inner_left/
    inner_right) die passende Nummer -- NICHT mittig auf der gesamten
    Footprint-Flaeche: die Bodenplatte steckt nur im 'bottom'-Loch, die
    AEUSSEREN Seitenteile nur in 'outer_left'/'outer_right', die INNEREN nur
    in 'inner_left'/'inner_right' -- die Nummer soll also genau DORT stehen,
    wo das jeweilige Teil tatsaechlich eingesteckt wird, statt an einer
    Stelle, die keinem der Teile eindeutig zugeordnet werden kann.

    `placement_numbers` ({variantUuid: (width_number, height_number)}, aus
    led_batch_editor.App._export_project): ZWEI VONEINANDER UNABHAENGIGE
    Nummern-Folgen -- `width_number` fuer die Bodenplatte (haengt NUR von
    width_mm ab, siehe get_bottom_plate_points -- passt in JEDEN Footprint
    dieser Breite, unabhaengig von dessen Hoehe) an der 'bottom'-Position,
    `height_number` fuer BEIDE Seitenteil-Varianten (haengen NUR von
    height_mm ab, siehe get_side_plate_points -- passen in JEDEN Footprint
    dieser Hoehe, unabhaengig von dessen Breite) an 'outer_left'/
    'outer_right'/'inner_left'/'inner_right'. EINE gemeinsame (width_mm, height_mm)-
    "Baugruppen"-Nummer waere hier FALSCH: zwei Platzierungen mit gleicher
    Breite aber unterschiedlicher Hoehe brauchen z.B. physisch IDENTISCHE
    (austauschbare) Bodenplatten -- eine gemeinsame Nummer nur bei exakt
    gleichem (Breite, Hoehe)-Paar wuerde ihnen faelschlich unterschiedliche
    Bodenplatten-Nummern geben.
    Platzierungen ohne Eintrag in `placement_numbers` (sollte nicht
    vorkommen, aber schadet nicht) werden einfach uebersprungen."""
    leds_by_variant: dict = {}
    for led in entries:
        leds_by_variant.setdefault(led.get('variantUuid'), []).append(led)
    label_h = max(1.5, (footprintScale.TONGUE_DEPTH_MM - footprintScale.TONGUE_HOLE_UNDERSIZE_MM) * 0.8)
    for variant_uuid, leds in leds_by_variant.items():
        numbers = placement_numbers.get(variant_uuid)
        if numbers is None:
            continue
        width_number, height_number = numbers
        width_mm, height_mm = resolve_footprint_size(variant_size, leds)
        transform = _footprint_placement_transform(leds, width_mm, height_mm, variant_leds)
        anchors = footprintScale.footprint_hole_anchors(width_mm, height_mm)
        for key, (local_x, local_y) in anchors.items():
            number = width_number if key == 'bottom' else height_number
            # anchors sind PHYSISCHE Konvention (Y=0=Unterkante, wie
            # get_footprint_points) -- transform() erwartet BILD-Konvention
            # (siehe _footprint_scaled_points), daher hier dieselbe Spiegelung
            # (height_mm - y).
            x, y = transform(local_x, height_mm - local_y)
            dwg.add_text(str(number), x, y, height=label_h,
                        layer=footprintScale.ENGRAVE_LAYER, color=3)


def export_dxf(entries: list, outline: Outline | None = None, out_path=None,
               variant_size: tuple | None = None, variant_leds: list | None = None) -> Path:
    """DIE EINE Funktion, die tatsaechlich die DXF-Datei schreibt.

    entries: platzierte LEDs EINES Hauses (siehe get_placed_leds()), je
    Eintrag {'x','y','w','h','ledIndex','variantUuid'}.
    outline: optionale Gebaeude-Umriss-Box.
    out_path: Zieldatei.
    variant_size: (width_mm, height_mm) Default-Footprint-Groesse der
    Variante (z.B. aus variant['footprint_width_mm']/['footprint_height_mm'])
    -- gilt fuer jede Platzierung ohne eigene width_mm/height_mm (siehe
    resolve_footprint_size).
    variant_leds: die LED-Vorlage der Variante (x_mm/y_mm je LED, z.B.
    variant['leds']) -- bestimmt den STARREN Footprint-Anker relativ zu den
    LEDs (siehe _footprint_placement_transform/
    footprintScale.led_footprint_offset_mm).

    Sortiert `entries` zuerst nach Variant-UUID, damit Rechtecke/Labels
    derselben physisch platzierten Platine im DXF hintereinander stehen
    statt in beliebiger Reihenfolge. Jede Variant-UUID bekommt ausserdem
    ihren eigenen Layer + eine daraus abgeleitete Farbe, damit sich einzelne
    Platinen im CAD-Programm ein-/ausblenden lassen: ein Rechteck pro
    (einzigartigem Fenster, Variante)-Paar, und je LED eine Text-
    Beschriftung mit ihrem Ketten-Index (`ledIndex`) an der Fenstermitte --
    teilen sich mehrere LEDs derselben Variante dasselbe Fenster, werden
    ihre Beschriftungen leicht uebereinander versetzt statt sich zu
    ueberlappen. Zusaetzlich wird pro Variant-UUID die gewaehlte Referenz-
    Footprint mittig ueber der tatsaechlichen Ausdehnung ihrer Fenster
    eingefuegt (siehe _footprint_anchor). Gibt den geschriebenen Dateipfad
    zurueck."""
    dwg = DxfDrawing()
    if outline is not None:
        dwg.add_outline_path(outline)

    seen_rects: set = set()
    label_offset: dict = {}
    leds_by_variant: dict = {}
    for led in sorted(entries, key=lambda e: str(e.get('variantUuid') or '')):
        variant_uuid = led.get('variantUuid')
        layer = _variant_layer(variant_uuid)
        color = _variant_color(variant_uuid)
        key = (led['x'], led['y'], led['w'], led['h'], layer)
        if key not in seen_rects:
            dwg.add_rect(led['x'], led['y'], led['w'], led['h'], layer=layer, color=color)
            seen_rects.add(key)

        leds_by_variant.setdefault(variant_uuid, []).append(led)

        if led.get('ledIndex') is None:
            continue
        n = label_offset.get(key, 0)
        label_offset[key] = n + 1
        cx, cy = _rect_center(led)
        label_h = led['h'] * 0.18
        # Gravur (Text), NICHT auf demselben Layer wie das Fenster-Rechteck
        # (das ist ein Schnitt/Referenz-Layer) -- siehe Modul-weites Prinzip:
        # EIN Layer fuer Schnitte, EIN eigener fuer alles Graviert-/Beschriftete.
        dwg.add_text(str(led['ledIndex']), cx, cy - n * label_h,
                    height=label_h, layer=footprintScale.ENGRAVE_LAYER, color=color)

    # Footprint-Groesse ist PRO PLATZIERUNG eintragbar (ledBatches[].width_mm/
    # height_mm, siehe get_placed_leds()) -- fehlt sie fuer eine Platzierung,
    # gilt der hier uebergebene `variant_size` (Default der Variante) als
    # Fallback (siehe resolve_footprint_size).
    _insert_footprints(dwg, entries, variant_size, variant_leds=variant_leds)

    return dwg.save(out_path)
