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
# Layer-Namen der beiden eigenstaendigen Gehaeuseteil-DXFs (siehe
# export_outline_with_panes_dxf/export_outline_only_dxf weiter unten) --
# damit edit_outline_with_panes_dxf/edit_outline_only_dxf beim Aktualisieren
# einer BEREITS exportierten Datei gezielt NUR ihre eigenen Entities
# ersetzen koennen, ohne andere, vom Nutzer manuell in derselben Datei
# ergaenzte Layer (z.B. von Hand berechnete Seitenteile/Verbinder) anzutasten.
OUTLINE_PANES_LAYER = 'HOUSE_OUTLINE_PANES'
OUTLINE_ONLY_LAYER = 'HOUSE_OUTLINE'
# Eigener Layer NUR fuer die Footprint-Ausschnitte auf der "mit
# Fensterscheiben"-Kontur (siehe _draw_outline_with_panes) -- getrennt von
# OUTLINE_PANES_LAYER, damit sie im CAD-Programm unabhaengig von den
# Fensteroeffnungen ein-/ausgeblendet werden koennen UND damit
# _replace_layer_entities() sie beim Aktualisieren (edit_outline_with_panes_dxf)
# zuverlaessig wiederfindet -- ohne dieses Layer-Tag wuerden Footprint-
# Konturen sonst auf ihrem Default-Layer '0' landen (siehe
# _insert_footprints), auf dem `_replace_layer_entities(OUTLINE_PANES_LAYER)`
# sie nicht faende.
OUTLINE_PANES_FOOTPRINT_LAYER = 'HOUSE_OUTLINE_PANES_FOOTPRINTS'


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
                *, layer: str = 'WINDOWS', color: int = 3) -> None:
        """Rechteck an Position (x, y) [linke obere Ecke, BILD-Konvention]
        mit Breite w und Hoehe h -- wie bei den Fenster-Eintraegen in
        <name>.json. Die Y-Achse wird beim Zeichnen automatisch in
        CAD-Konvention gespiegelt (siehe _fy)."""
        self._ensure_layer(layer, color)
        y, yh = self._fy(y), self._fy(y + h)
        pts = [(x, y), (x + w, y), (x + w, yh), (x, yh)]
        self.msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': layer})

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


def _draw_outline_with_panes(dwg: 'DxfDrawing', outline: 'Outline', windows: list,
                             entries: list | None = None, variant_size: tuple | None = None,
                             variant_leds: list | None = None) -> None:
    """Zeichnet den echten Gebaeude-Umriss (siehe Outline.polylines) MIT
    ALLEN Fensteroeffnungen aus `windows` (bereits in ECHTEN mm, siehe
    get_placed_leds()'s Umrechnung -- ALLE Fenster des Hauses, nicht nur die
    von LEDs beleuchteten: eine "Glasscheibe" braucht jedes Fenster,
    unabhaengig von der Beleuchtung) auf Layer OUTLINE_PANES_LAYER, PLUS
    (falls `entries` angegeben, siehe get_placed_leds()) je Platzierung ihre
    Footprint-Kontur als AUSSCHNITT auf OUTLINE_PANES_FOOTPRINT_LAYER --
    dieselben Positionen wie im LED-/Platinen-Export (siehe
    _insert_footprints), damit die Platine spaeter genau in dieses Loch der
    Fensterscheiben-Kontur passt."""
    for poly in outline.polylines:
        dwg.add_polyline(poly, closed=True, layer=OUTLINE_PANES_LAYER, color=7)
    for w in windows:
        dwg.add_rect(w['x'], w['y'], w['w'], w['h'], layer=OUTLINE_PANES_LAYER, color=6)
    if entries:
        _insert_footprints(dwg, entries, variant_size, layer=OUTLINE_PANES_FOOTPRINT_LAYER,
                          variant_leds=variant_leds)


def export_outline_with_panes_dxf(outline: 'Outline', windows: list, out_path,
                                  entries: list | None = None,
                                  variant_size: tuple | None = None,
                                  variant_leds: list | None = None) -> Path:
    """Schreibt EINE NEUE DXF-Datei mit dem Gebaeude-Umriss + allen
    Fensteroeffnungen + (mit `entries`) den Footprint-Ausschnitten
    ("Gebaeudekontur mit Fensterscheiben"). Ueberschreibt `out_path`
    komplett -- fuer eine bereits exportierte Datei stattdessen zu
    AKTUALISIEREN (statt zu ueberschreiben), siehe edit_outline_with_panes_dxf()."""
    dwg = DxfDrawing()
    _draw_outline_with_panes(dwg, outline, windows, entries, variant_size, variant_leds)
    return dwg.save(out_path)


def edit_outline_with_panes_dxf(outline: 'Outline', windows: list, path,
                                entries: list | None = None,
                                variant_size: tuple | None = None,
                                variant_leds: list | None = None) -> Path:
    """Aktualisiert die Gebaeudekontur + Fensteroeffnungen + Footprint-
    Ausschnitte in einer BEREITS exportierten DXF-Datei bei `path` (per
    DxfDrawing.load() geoeffnet) -- ersetzt dazu nur die vorhandenen Entities
    auf OUTLINE_PANES_LAYER und OUTLINE_PANES_FOOTPRINT_LAYER (siehe
    _replace_layer_entities), laesst aber ALLES ANDERE in der Datei (z.B.
    vom Nutzer manuell auf eigenen Layern ergaenzte Seitenteile/Verbinder)
    unangetastet. Existiert `path` noch nicht, verhaelt sich das wie
    export_outline_with_panes_dxf() (legt die Datei neu an)."""
    path = Path(path)
    dwg = DxfDrawing.load(path) if path.is_file() else DxfDrawing()
    _replace_layer_entities(dwg, OUTLINE_PANES_LAYER)
    _replace_layer_entities(dwg, OUTLINE_PANES_FOOTPRINT_LAYER)
    _draw_outline_with_panes(dwg, outline, windows, entries, variant_size, variant_leds)
    return dwg.save(path)


def _draw_outline_only(dwg: 'DxfDrawing', outline: 'Outline') -> None:
    """Zeichnet NUR den echten Gebaeude-Umriss (siehe Outline.polylines),
    OHNE Fensteroeffnungen, auf Layer OUTLINE_ONLY_LAYER."""
    for poly in outline.polylines:
        dwg.add_polyline(poly, closed=True, layer=OUTLINE_ONLY_LAYER, color=7)


def export_outline_only_dxf(outline: 'Outline', out_path) -> Path:
    """Schreibt EINE NEUE DXF-Datei mit NUR dem Gebaeude-Umriss (keine
    Fensteroeffnungen) -- siehe edit_outline_only_dxf() zum Aktualisieren
    einer bereits exportierten Datei."""
    dwg = DxfDrawing()
    _draw_outline_only(dwg, outline)
    return dwg.save(out_path)


def edit_outline_only_dxf(outline: 'Outline', path) -> Path:
    """Aktualisiert NUR den Gebaeude-Umriss in einer BEREITS exportierten
    DXF-Datei bei `path` -- wie edit_outline_with_panes_dxf(), aber fuer
    OUTLINE_ONLY_LAYER (ohne Fensteroeffnungen)."""
    path = Path(path)
    dwg = DxfDrawing.load(path) if path.is_file() else DxfDrawing()
    _replace_layer_entities(dwg, OUTLINE_ONLY_LAYER)
    _draw_outline_only(dwg, outline)
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


def _footprint_scaled_points(width_mm: float, height_mm: float) -> list:
    """Generiert die Footprint-Kontur (ein Rechteck) in der gegebenen
    Groesse, auf (0, 0) normiert. footprintScale.get_footprint_points() gibt
    dazu ein EIGENSTAENDIGES ezdxf-Dokument zurueck (nicht nur rohe Punkte)
    -- die LWPOLYLINE-Punkte werden hier aus dessen modelspace() ausgelesen,
    damit der Rest dieses Moduls (Anker/Uebersetzung, Y-Flip beim Zeichnen)
    wie gewohnt mit reinen (x, y)-Punktlisten weiterarbeiten kann.

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
    return [[(pt[0], height_mm - pt[1]) for pt in e.get_points()] for e in msp.query('LWPOLYLINE')]


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
                       variant_leds: list | None = None) -> None:
    """Fuegt fuer JEDE Platzierung (gruppiert nach variantUuid) ihre
    Footprint-Kontur ein -- Groesse aufgeloest ueber resolve_footprint_size
    (Platzierungs-Override aus `leds[0]`, sonst der hier uebergebene
    `variant_size`, sonst FOOTPRINT_WIDTH/HEIGHT). Wird sowohl von
    export_dxf() (LED-/Platinen-Datei, `layer=None` -- Default-Layer '0')
    als auch von _draw_outline_with_panes() (Footprint-AUSSCHNITTE auf der
    Fensterscheiben-Kontur, `layer=OUTLINE_PANES_FOOTPRINT_LAYER`) verwendet,
    damit beide GENAU dieselben Footprint-Positionen zeichnen.

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
        polylines = _footprint_scaled_points(width_mm, height_mm)
        if not polylines:
            continue
        transform = _footprint_placement_transform(leds, width_mm, height_mm, variant_leds)
        for poly in polylines:
            pts = [transform(fx, fy) for fx, fy in poly]
            dwg.add_polyline(pts, closed=True, layer=layer or '0', color=7)


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
        dwg.add_text(str(led['ledIndex']), cx, cy - n * label_h,
                    height=label_h, layer=layer, color=color)

    # Footprint-Groesse ist PRO PLATZIERUNG eintragbar (ledBatches[].width_mm/
    # height_mm, siehe get_placed_leds()) -- fehlt sie fuer eine Platzierung,
    # gilt der hier uebergebene `variant_size` (Default der Variante) als
    # Fallback (siehe resolve_footprint_size).
    _insert_footprints(dwg, entries, variant_size, variant_leds=variant_leds)

    return dwg.save(out_path)
