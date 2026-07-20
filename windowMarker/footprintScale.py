#!/usr/bin/env python3
"""
footprintScale.py -- Erzeugt Footprint-Konturen PROGRAMMATISCH (als
Rechtecke), OHNE auf vorgefertigte footprints/*.dxf-Dateien oder eine
Auswahl zwischen benannten Footprint-"Typen" (frueher "Footprint-Small"/
"-Big") angewiesen zu sein -- die physische Platine wird als einfaches,
mm-genaues Rechteck der jeweils konfigurierten Breite/Hoehe angenaehert
(Breite/Hoehe koennen sich pro Variante/Platzierung unterscheiden, siehe
dxfExport.py/led_batch_editor.py -- es gibt aber KEINEN Auswahl-Dialog
("Big"/"Small") mehr, jede Platzierung bekommt einfach ihre eigene
Groesse). Genutzt von windowMarker/dxfExport.py (Export) UND
ledBatchEditor/led_batch_editor.py (Vorschau, per Cross-Import), damit
beide exakt dieselbe Geometrie zeigen/exportieren.

LED_OFFSET_TOP_MM
    FESTER Abstand (mm) zwischen der LED-Reihe und der Footprint-Oberkante
    -- war frueher ein PRO FOOTPRINT-NAME konfigurierbarer Wert (aus einer
    <name>.json), ist jetzt EIN EINZIGER globaler Wert, weil es keine
    benannten Footprint-Typen mehr gibt. Wird sowohl beim Generieren der
    Kontur (siehe get_footprint_points) als auch beim Anker/Zentrieren ueber
    den LEDs verwendet (siehe dxfExport._footprint_anchor/
    led_batch_editor._footprint_anchor).

get_footprint_points(width_mm, height_mm)
    Erzeugt DEN FOOTPRINT: ein EIGENSTAENDIGES ezdxf-Dokument. Das
    width_mm x height_mm-Aussenmass selbst ist KEIN Schnitt mehr, sondern
    nur eine Konstruktions-/Skizzenlinie auf dem separaten Layer 'SKETCH'
    (Referenz zur Ausrichtung, wird beim Laserschnitt ignoriert). Die
    echten Schnitte sind 2 horizontale Schlitze an der Unterkante (fuer die
    2 Zungen der Bodenplatte, siehe get_bottom_plate_points) und 2 vertikale
    Schlitze an der linken/rechten Kante (fuer die neue Unterkanten-Zunge
    jedes Seitenteils, siehe get_side_plate_points), alle auf Layer PINS,
    Presssitz-Untermass TONGUE_HOLE_UNDERSIZE_MM. Gibt das ezdxf-Dokument
    selbst zurueck (NICHT gespeichert) -- Aufrufer, die nur die rohen Punkte
    brauchen, lesen sie ueber dessen modelspace() aus (siehe
    dxfExport._footprint_scaled_points/led_batch_editor._load_footprint_polylines).

    ABSICHTLICH kein DxfDrawing (siehe dxfExport.py) -- DxfDrawing spiegelt
    die Y-Achse automatisch (Bild-Konvention -> CAD-Konvention, siehe
    DxfDrawing._fy), das ist aber NUR fuer Geometrie richtig, die aus Bild-
    Pixel-Koordinaten stammt (Fenster/LEDs/Kontur). Diese generierte
    Footprint-Kontur hat damit nichts zu tun -- sie wird SPAETER
    unveraendert in die (bereits gespiegelte) Hauszeichnung eingefuegt; ein
    zweites Mal spiegeln wuerde die Platine an der falschen Stelle/
    seitenverkehrt landen lassen.

get_bottom_plate_points(width_mm)
    Erzeugt DIE BODENPLATTE -- ein SEPARATES Teil vom Footprint: ein
    eigenstaendiges ezdxf-Dokument mit einem width_mm breiten,
    SIDE_PLATE_WIDTH_MM (11mm) hohen Aussenumriss, MIT ZWEI ZUNGEN an der
    Unterkante (ragen unter Y=0 hinaus, TONGUE_WIDTH_MM x TONGUE_DEPTH_MM),
    die in die 2 horizontalen Schlitze des Footprints greifen, PLUS den
    schon bestehenden ZWEI Zungen-Loechern (TONGUE_DEPTH_MM x
    TONGUE_WIDTH_MM minus TONGUE_HOLE_UNDERSIZE_MM Presssitz), die die
    Seitenteil-Endzungen aufnehmen (siehe get_side_plate_points).
    Unabhaengig von height_mm.

get_side_plate_points(height_mm, inner)
    Erzeugt EIN SEITENTEIL im LANDSCAPE-Format (X = height_mm, die lange
    Achse; Y = SIDE_PLATE_WIDTH_MM = 11mm, die kurze Achse). Am linken Ende
    eine Zunge (steckt in ein Loch der Bodenplatte, siehe
    get_bottom_plate_points); ein Schlitz/Ausschnitt fuer den Kreuz-/
    Ueberblattungs-Stoss mit dem jeweils ANDEREN Seitenteil (`inner=True`/
    `False` waehlt Innen-/Aussen-Variante, siehe dort fuer Details).
    Unabhaengig von width_mm (der Footprint-Breite spielt fuer die
    Seitenteil-Groesse keine Rolle).

export_all_footprints(sizes, out_dir)
    Erzeugt UND schreibt je Groesse aus `sizes` ({name: (width_mm,
    height_mm)}) eine Footprint-DXF (per get_footprint_points,
    <name-ohne-.dxf>.dxf) PLUS -- einmal je DISTINKTER width_mm -- eine
    Bodenplatten-DXF (per get_bottom_plate_points) als
    'bottomplate-{width_mm}mm.dxf' -- UND, einmal je DISTINKTER height_mm
    (dito fuer die Seitenteile), ZWEI Seitenteil-DXFs (Aussen-/Innen-
    Variante, je 2x in der Stueckliste benoetigt -- siehe csvExport.py --
    aber als DXF-Vorlage reicht je EINE Datei) als
    'sideplate-outer-{height_mm}mm.dxf'/'sideplate-inner-{height_mm}mm.dxf'.
    Gibt die Liste der geschriebenen Dateipfade zurueck.

get_frame_side_points(length_mm) / get_frame_top_points(length_mm)
    Rahmenleisten, die aussen an den 4 Seiten des Haus-Umrisses entlanglaufen
    (side = links/rechts, top = oben/unten). FRAME_DEPTH_MM (11mm, wie die
    Seitenteile) breiter Querschnitt, an beiden Laengskanten alle
    FRAME_TONGUE_SPACING_MM (100mm) eine Zunge (steckt durch ein Loch in der
    Hauskontur, siehe dxfExport.py), an beiden Enden ein Eckstoss (side =
    Zunge, top = passende Aussparung), siehe _get_frame_strip_points.
frame_strip_tongue_hole_positions(length_mm)
    Lokale (x, y, w, h)-Loecher, die die wiederkehrenden Laengskanten-Zungen
    einer Rahmenleiste dieser Laenge in die Hauskontur schneiden muessen.

nest_parts_sheet(items, out_path, spacing_mm, max_row_width_mm)
    Baut aus `items` ({(ezdxf.Drawing, count)}-Paaren, beliebige Mischung
    aus Footprint-/Bodenplatten-/Seitenteil-/Hauszeichnungs-Docs) EIN
    einziges DXF: `count` Kopien je Eintrag, in Zeilen gepackt (neue Zeile
    sobald SHEET_MAX_WIDTH_MM ueberschritten wuerde), PART_SPACING_MM (5mm)
    Abstand in beide Richtungen -- ein ungefaehr rechteckiges, direkt an
    den Laser schickbares Schnitt-Blatt statt einer einzigen langen Reihe.
    Gedacht fuer EIN Blatt pro Haus (siehe led_batch_editor.py
    App._export_project), mit Stueckzahlen direkt aus der Stueckliste
    (csvExport.get_part_counts), damit CSV und Blatt nie auseinanderlaufen.
"""

from pathlib import Path

import ezdxf

# Siehe Modul-Docstring -- ersetzt die frueheren, PRO FOOTPRINT-NAME in
# einer <name>.json konfigurierbaren 'led_offset_top_mm'-Werte (es gibt
# keine benannten Footprint-Typen/Auswahl mehr, nur noch EINE Groesse pro
# Platzierung/Variante).
LED_OFFSET_TOP_MM = 7.3


def led_footprint_offset_mm(variant_leds: list, width_mm: float, height_mm: float,
                            led_width_mm: float = 5.0) -> tuple:
    """(dx, dy, mirror_width_mm): der Footprint haengt STARR an den LEDs
    einer Platzierung (mittig, siehe get_footprint_points) -- NICHT an
    irgendwelchen echten Fenstern, die diese Platzierung gerade zufaellig
    beleuchtet (eine Platzierung kann bewusst neben ihrer Fenstermitte
    sitzen). `dx`/`dy` (mm) sind der Versatz von der "Anker-LED" der
    Vorlage `variant_leds` (der mit dem kleinsten x_mm/y_mm, ueblicherweise
    die erste LED der Kette) zur linken oberen Ecke des width_mm x
    height_mm grossen Footprints: HORIZONTAL mittig ueber ALLEN LEDs der
    Vorlage (inkl. led_width_mm/2 Rand je Seite), VERTIKAL LED_OFFSET_TOP_MM
    oberhalb der Anker-LED. `mirror_width_mm` ist die eigene horizontale
    Spannweite der LED-Vorlage (max(x_mm)-min(x_mm), mindestens 1.0) -- die
    Achse, um die bei GESPIEGELTEN Platzierungen zu spiegeln ist (Footprint
    UND LEDs zusammen, als EIN starres Stueck).

    DIES IST DIE EINE STELLE, an der diese Rechnung steht -- sowohl
    windowMarker.dxfExport (tatsaechlicher Export) als auch
    ledBatchEditor.led_batch_editor (Editor-Vorschau, siehe dortiges
    _footprint_anchor) rufen sie auf, damit beide IMMER exakt dieselbe
    Position liefern, unabhaengig davon, welche echten Fenster gerade
    beruehrt werden. (0.0, 0.0, 1.0) ohne `variant_leds`."""
    if not variant_leds:
        return 0.0, 0.0, 1.0
    xs = [l['x_mm'] for l in variant_leds]
    ys = [l['y_mm'] for l in variant_leds]
    anchor_x, anchor_y = min(xs), min(ys)
    min_x = anchor_x - led_width_mm / 2
    max_x = max(xs) + led_width_mm / 2
    size_x = max_x - min_x
    desired_left = min_x + (size_x - width_mm) / 2
    desired_top = anchor_y - LED_OFFSET_TOP_MM
    dx = desired_left - anchor_x
    dy = desired_top - anchor_y
    mirror_width_mm = (max(xs) - anchor_x) or 1.0
    return dx, dy, mirror_width_mm

# Bodenplatte (siehe get_bottom_plate_points): feste Hoehe (== SIDE_PLATE_WIDTH_MM,
# 11mm), unabhaengig von height_mm (der Footprint-/LED-Flaechen-Hoehe). Traegt
# 2 Zungen an der UNTERKANTE (Y=0, ragen nach UNTEN ueber den Rand hinaus --
# gleiche Nominalgroesse wie ueberall sonst, TONGUE_WIDTH_MM x TONGUE_DEPTH_MM),
# die in die 2 horizontalen Schlitz-Ausschnitte des Footprints greifen (siehe
# get_footprint_points).

# Seitenteil (siehe get_side_plate_points): feste Breite, unabhaengig von der
# Bodenplatten-Breite (width_mm) -- nur die Hoehe folgt der Bodenplatte/dem
# Footprint (height_mm). Es gibt ZWEI Seitenteil-Varianten (Aussen-/Innen-,
# "Seitenteile"/"Innere Seitenteile" in der Stueckliste, siehe csvExport.py)
# -- pro Platzierung werden von JEDER Variante 2 Stueck gebraucht (macht 4
# Seitenteile insgesamt), aber als DXF-VORLAGE reicht je EINE Datei pro
# Variante und Hoehe (siehe export_all_footprints).
SIDE_PLATE_WIDTH_MM = 11.0

# "Zunge" am LINKEN Ende jedes Seitenteils (schmalerer Abschnitt, der in ein
# Loch der Bodenplatte gesteckt wird) -- KEIN Ueberstand ueber die
# Aussenkontur hinaus, sondern ein Einschnitt aus den beiden Ecken an diesem
# Ende, der in der Mitte einen schmaleren Steg (TONGUE_WIDTH_MM) stehen laesst
# (TONGUE_MARGIN_MM oben/unten + TONGUE_WIDTH_MM + TONGUE_MARGIN_MM =
# SIDE_PLATE_WIDTH_MM). TONGUE_DEPTH_MM = wie tief dieser Einschnitt reicht.
TONGUE_WIDTH_MM = 5.10
TONGUE_MARGIN_MM = (SIDE_PLATE_WIDTH_MM - TONGUE_WIDTH_MM) / 2   # 2.95
TONGUE_DEPTH_MM = 3.0

# Presssitz-Untermass fuer das Zungen-Loch im Footprint (siehe
# get_footprint_points): JEDES Loch ist auf JEDER Seite um dieses Mass
# KLEINER als die Zunge, die hineingesteckt wird (0.05mm/Seite = 0.1mm in
# Summe pro Dimension) -- Loch = (TONGUE_WIDTH_MM - TONGUE_HOLE_UNDERSIZE_MM)
# x (TONGUE_DEPTH_MM - TONGUE_HOLE_UNDERSIZE_MM).
TONGUE_HOLE_UNDERSIZE_MM = 0.1

# Schlitz/Ausschnitt am RECHTEN (vom Zungen-Ende entfernten) Ende jedes
# Seitenteils -- fuer den Kreuz-/Ueberblattungs-Stoss zwischen Aussen- und
# Innen-Seitenteil (siehe get_side_plate_points). Das INNERE Seitenteil
# bekommt einen SCHMALEN Schlitz (INNER_SLOT_WIDTH_MM breit), der von der
# UNTERKANTE bis zur Mitte + SLOT_OVERLAP_MM reicht; das AEUSSERE Seitenteil
# bekommt eine BREITERE Oeffnung (OUTER_SLOT_WIDTH_MM breit), die von der
# OBERKANTE OUTER_SLOT_HEIGHT_MM tief hinunterreicht. Beide sitzen am
# gleichen X (rechtsbuendig), sodass sich Aussen- und Innen-Seitenteil beim
# Zusammenbau an dieser Stelle ineinander schieben.
INNER_SLOT_WIDTH_MM = 1.6
OUTER_SLOT_WIDTH_MM = 5.0
OUTER_SLOT_HEIGHT_MM = 7.0
SLOT_OVERLAP_MM = -0.5
# Abstand vom RECHTEN Ende der Aussenkontur bis zur naeher am Ende liegenden
# Kante des Schlitzes/Ausschnitts -- der Schlitz liegt also NICHT mehr
# buendig an der Kante, sondern laesst ein SLOT_END_MARGIN_MM breites Stueck
# durchgehendes Material zwischen sich und dem Ende stehen.
SLOT_END_MARGIN_MM = 5.7


def _new_plate_doc():
    """Legt ein neues ezdxf-Dokument (mm, siehe $INSUNITS) mit den Layern
    OUTLINE/PINS an (ACI-Farbe 1 = Rot, explizit auf jeder Entity gesetzt,
    nicht nur am Layer, damit die Kontur in JEDEM CAD-Viewer sofort sichtbar
    ist) und gibt (doc, add_rect) zurueck -- add_rect(x, y, w, h, layer)
    zeichnet ein Rechteck als LWPOLYLINE. Gemeinsamer Unterbau fuer
    get_footprint_points/get_bottom_plate_points/get_side_plate_points."""
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4   # 4 = Millimeter (siehe dxfExport.DxfDrawing.__init__)
    msp = doc.modelspace()
    RED = 1
    for layer in ('OUTLINE', 'PINS'):
        if layer not in doc.layers:
            doc.layers.add(layer, color=RED)
    # SKETCH: NICHT schneiden -- reine Konstruktions-/Referenzlinie (graues
    # ACI 8), fuer Konturen, die nur zur Ausrichtung markiert werden, aber
    # kein echter Laserschnitt sind (siehe get_footprint_points).
    if 'SKETCH' not in doc.layers:
        doc.layers.add('SKETCH', color=8)

    def add_rect(x: float, y: float, w: float, h: float, layer: str) -> None:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': layer, 'color': RED})

    return doc, add_rect


def get_footprint_points(width_mm: float, height_mm: float) -> ezdxf.document.Drawing:
    """Erzeugt DEN FOOTPRINT: ein eigenstaendiges ezdxf-Dokument, dessen
    width_mm x height_mm-Aussenmass NICHT geschnitten wird -- es ist nur eine
    Konstruktions-/Skizzenlinie auf dem separaten Layer 'SKETCH' (dient der
    Ausrichtung, markiert die LED-Ruecklageflaeche, ist aber kein echter
    Laserschnitt). Die tatsaechlichen Schnitte sind zwei Lochpaare (Layer
    PINS, Presssitz-Untermass TONGUE_HOLE_UNDERSIZE_MM wie ueberall sonst):

      - 2 HORIZONTALE Schlitze an der Unterkante (Y=0), fuer die 2 Zungen
        der Bodenplatte (siehe get_bottom_plate_points) -- dieselbe
        X-Verteilung (gap-Formel ueber TONGUE_WIDTH_MM), damit sie exakt
        fluchten, wenn beide Teile am selben X=0-Rand ausgerichtet werden.
      - 4 VERTIKALE Schlitze fuer die neue Unterkanten-Zunge JEDES
        Seitenteils (siehe get_side_plate_points) -- MITTIG im Bereich
        zwischen TONGUE_DEPTH_MM (Ende der Endzungen-Zone) und height_mm
        zentriert (exakt dieselbe Formel wie die Seitenteil-Zungenposition,
        bx0/bx1 dort, damit beide garantiert fluchten). VIER statt zwei, aus
        demselben Grund wie bei get_bottom_plate_points (Aussen-/Innen-
        Seitenteil sitzen wegen des Kreuz-/Ueberblattungs-Stoss versetzt):
        2 an der linken/rechten Kante (fuer die Aussen-Seitenteile) + 2
        weiter innen (per derselben spacing-Formel wie in
        get_bottom_plate_points, fuer die Innen-Seitenteile).

    Gibt das (nicht gespeicherte) ezdxf-Dokument zurueck.

    ABSICHTLICH kein DxfDrawing (siehe Modul-Docstring) -- DxfDrawing
    spiegelt die Y-Achse automatisch fuer Bild-Pixel-Konvention, diese
    generierte Kontur steht aber in ihrem EIGENEN, unabhaengigen
    Koordinatensystem und wird unveraendert in die (bereits gespiegelte)
    Hauszeichnung eingefuegt; ein zweites Mal spiegeln wuerde sie seitenverkehrt
    platzieren."""
    doc, add_rect = _new_plate_doc()
    msp = doc.modelspace()

    sketch = [(0.0, 0.0), (width_mm, 0.0), (width_mm, height_mm), (0.0, height_mm)]
    msp.add_lwpolyline(sketch, close=True, dxfattribs={'layer': 'SKETCH', 'color': 8})

    hole_w = TONGUE_WIDTH_MM - TONGUE_HOLE_UNDERSIZE_MM
    hole_d = TONGUE_DEPTH_MM - TONGUE_HOLE_UNDERSIZE_MM

    # 2 horizontale Schlitze, Unterkante (Y=0), gleiche X-Verteilung wie die
    # Zungen der Bodenplatte (siehe dort).
    gap = (width_mm - TONGUE_WIDTH_MM * 2) / 2
    for i in range(2):
        nominal_x = gap / 2 + i * (TONGUE_WIDTH_MM + gap)
        hole_x = nominal_x + (TONGUE_WIDTH_MM - hole_w) / 2
        add_rect(hole_x, 0.0, hole_w, hole_d, 'PINS')

    # 4 vertikale Schlitze -- MITTIG zwischen TONGUE_DEPTH_MM und height_mm
    # zentriert, exakt dieselbe Formel wie die Seitenteil-Zungenposition
    # (siehe get_side_plate_points' bx0/bx1), damit beide garantiert exakt
    # fluchten. 2 aussen (linke/rechte Kante, fuer die Aussen-Seitenteile) +
    # 2 innen (dieselbe spacing-Formel wie get_bottom_plate_points, fuer die
    # Innen-Seitenteile).
    tongue_center = TONGUE_DEPTH_MM + (height_mm - TONGUE_DEPTH_MM) / 2
    slot_y = tongue_center - hole_w / 2
    spacing = (width_mm - TONGUE_WIDTH_MM * 4) / 3
    inner_left_x = 1 * (spacing + TONGUE_WIDTH_MM)
    inner_right_x = 2 * (spacing + TONGUE_WIDTH_MM)
    for slot_x in (0.0, inner_left_x, inner_right_x, width_mm - hole_d):
        add_rect(slot_x, slot_y, hole_d, hole_w, 'PINS')

    return doc


def get_bottom_plate_points(width_mm: float) -> ezdxf.document.Drawing:
    """Erzeugt DIE BODENPLATTE -- ein SEPARATES Teil vom Footprint (siehe
    get_footprint_points): ein width_mm breiter, SIDE_PLATE_WIDTH_MM (11mm)
    hoher Aussenumriss, MIT ZWEI ZUNGEN, die an der Unterkante (Y=0) nach
    UNTEN ueber den Rand hinausragen (TONGUE_WIDTH_MM breit x
    TONGUE_DEPTH_MM tief, dieselbe Nominalgroesse wie ueberall sonst),
    symmetrisch verteilt -- diese stecken in die 2 horizontalen Schlitze des
    Footprints (siehe dort). PLUS VIER Zungen-Loecher (TONGUE_DEPTH_MM breit
    x TONGUE_WIDTH_MM hoch, minus TONGUE_HOLE_UNDERSIZE_MM Presssitz), die
    die Seitenteil-Endzungen aufnehmen (siehe get_side_plate_points) -- VIER
    statt zwei, weil Aussen- und Innen-Seitenteil je Fensterseite durch den
    Kreuz-/Ueberblattungs-Stoss NICHT an derselben Stelle sitzen, sondern
    versetzt zueinander (Aussen buendig am Rand, Innen weiter zur Mitte
    eingerueckt): 2 aussen (X=0 und X=width_mm-hole_w, direkt am Rand) und 2
    innen (per spacing-Formel symmetrisch verteilt -- teilt width_mm in 3
    gleiche Luecken zwischen 4 TONGUE_WIDTH_MM-breiten Zonen auf).
    Unabhaengig von height_mm. Gibt das (nicht gespeicherte) ezdxf-Dokument
    zurueck."""
    doc, add_rect = _new_plate_doc()
    plate_h = SIDE_PLATE_WIDTH_MM

    # Aussenkontur als EIN zusammenhaengender Pfad (die 2 Zungen ragen unter
    # Y=0 hinaus, das geht nicht mit einem einzelnen Rechteck).
    tw, td = TONGUE_WIDTH_MM, TONGUE_DEPTH_MM
    gap = (width_mm - tw * 2) / 2
    tongue_x = [gap / 2 + i * (tw + gap) for i in range(2)]

    outline = [(0.0, 0.0)]
    for x0 in tongue_x:
        outline += [(x0, 0.0), (x0, -td), (x0 + tw, -td), (x0 + tw, 0.0)]
    outline += [(width_mm, 0.0), (width_mm, plate_h), (0.0, plate_h)]
    doc.modelspace().add_lwpolyline(outline, close=True, dxfattribs={'layer': 'OUTLINE', 'color': 1})

    # VIER Zungen-Loecher fuer die Seitenteil-Endzungen: 2 aussen (direkt am
    # Rand) + 2 innen (per Formel symmetrisch verteilt -- siehe
    # SPACING_GAP_MM), vertikal zentriert in plate_h.
    hole_w = TONGUE_DEPTH_MM - TONGUE_HOLE_UNDERSIZE_MM
    hole_h = TONGUE_WIDTH_MM - TONGUE_HOLE_UNDERSIZE_MM
    hole_y = (plate_h - hole_h) / 2
    spacing = (width_mm - tw * 4) / 3
    inner_left_x = 1 * (spacing + tw)
    inner_right_x = 2 * (spacing + tw)
    for hole_x in (0.0, inner_left_x, inner_right_x, width_mm - hole_w):
        add_rect(hole_x, hole_y, hole_w, hole_h, 'PINS')

    return doc


def get_side_plate_points(height_mm: float, inner: bool) -> ezdxf.document.Drawing:
    """Erzeugt EIN SEITENTEIL -- LANDSCAPE: X = height_mm (die lange Achse,
    entlang der Platzierung), Y = SIDE_PLATE_WIDTH_MM (11mm, die kurze
    Achse). `inner` waehlt zwischen Innen-/Aussen-Variante (siehe unten).

    Aussenkontur: ein X=[0, height_mm] x Y=[0, SIDE_PLATE_WIDTH_MM]-Rechteck,
    aus dem ZWEI Stuecke herausgeschnitten sind (kein Ueberstand ueber diese
    Aussenkontur hinaus), PLUS eine neue Zunge, die unter Y=0 hinausragt:
      1. Am LINKEN Ende (X=0..TONGUE_DEPTH_MM) eine schmalere "Zunge"
         (TONGUE_WIDTH_MM breit, mittig, TONGUE_MARGIN_MM Rand oben/unten) --
         steckt in eines der zwei Zungen-Loecher der Bodenplatte (siehe
         get_bottom_plate_points).
      2. Ein Schlitz/Ausschnitt fuer den Kreuz-/Ueberblattungs-Stoss mit dem
         jeweils anderen Seitenteil:
         `inner=False` (offen zur OBERKANTE, Y=0, OUTER_SLOT_HEIGHT_MM tief)
         -- liegt DIREKT am rechten Ende, buendig, KEIN Abstand;
         `inner=True` (offen zur UNTERKANTE, Y=SIDE_PLATE_WIDTH_MM, reicht
         bis zur Mitte + SLOT_OVERLAP_MM hinauf) -- liegt NICHT am rechten
         Ende selbst, sondern SLOT_END_MARGIN_MM davor (ein durchgehendes
         Materialstueck bleibt zwischen Schlitz und Ende stehen).
      3. NEU: eine Zunge an der UNTERKANTE (Y=0), die nach UNTEN ueber den
         Rand hinausragt (TONGUE_WIDTH_MM breit x TONGUE_DEPTH_MM tief,
         dieselbe Nominalgroesse wie ueberall sonst) -- steckt in einen der
         zwei vertikalen Schlitze des Footprints (siehe
         get_footprint_points). Position: MITTIG im Bereich zwischen
         TONGUE_DEPTH_MM (Ende der Endzungen-Zone) und height_mm zentriert --
         bei BEIDEN Varianten (inner/outer) mit DERSELBEN Formel/X-Position,
         damit sie in denselben Footprint-Schlitz treffen (die Formel ist
         identisch zu der in get_footprint_points fuer die vertikalen
         Schlitze, damit beide garantiert fluchten)."""
    doc, _add_rect = _new_plate_doc()
    msp = doc.modelspace()

    tm, tw, td = TONGUE_MARGIN_MM, TONGUE_WIDTH_MM, TONGUE_DEPTH_MM

    # Neue Unterkanten-Zunge: mittig zwischen td und height_mm zentriert,
    # ragt von Y=0 nach unten bis Y=-td.
    tongue_center = td + (height_mm - td) / 2
    bx0, bx1 = tongue_center - tw / 2, tongue_center + tw / 2

    if inner:
        # Schlitz unten: SLOT_END_MARGIN_MM Abstand zum rechten Ende, offen
        # zur UNTERKANTE, bis zur Mitte + SLOT_OVERLAP_MM.
        slot_right = height_mm - SLOT_END_MARGIN_MM
        slot_left = slot_right - INNER_SLOT_WIDTH_MM
        slot_top = SIDE_PLATE_WIDTH_MM / 2 + SLOT_OVERLAP_MM
        outline = [
            (0.0, tm),
            (0.0, tm + tw),
            (td, tm + tw),
            (td, SIDE_PLATE_WIDTH_MM),
            (slot_left, SIDE_PLATE_WIDTH_MM),
            (slot_left, slot_top),
            (slot_right, slot_top),
            (slot_right, SIDE_PLATE_WIDTH_MM),
            (height_mm, SIDE_PLATE_WIDTH_MM),
            (height_mm, 0.0),
            (bx1, 0.0),
            (bx1, -td),
            (bx0, -td),
            (bx0, 0.0),
            (td, 0.0),
            (td, tm),
        ]
    else:
        # Ausschnitt oben: DIREKT am rechten Ende (buendig, kein Abstand),
        # offen zur OBERKANTE, OUTER_SLOT_HEIGHT_MM tief.
        slot_left = height_mm - OUTER_SLOT_WIDTH_MM
        slot_bottom = OUTER_SLOT_HEIGHT_MM
        outline = [
            (0.0, tm),
            (0.0, tm + tw),
            (td, tm + tw),
            (td, SIDE_PLATE_WIDTH_MM),
            (height_mm, SIDE_PLATE_WIDTH_MM),
            (height_mm, slot_bottom),
            (slot_left, slot_bottom),
            (slot_left, 0.0),
            (bx1, 0.0),
            (bx1, -td),
            (bx0, -td),
            (bx0, 0.0),
            (td, 0.0),
            (td, tm),
        ]

    msp.add_lwpolyline(outline, close=True, dxfattribs={'layer': 'OUTLINE', 'color': 1})
    return doc


# Rahmenleisten (siehe get_frame_side_points/get_frame_top_points): laufen
# aussen an den 4 Seiten des Haus-Umrisses entlang -- links/rechts (die
# "side"-Variante) und oben/unten (die "top"-Variante). FRAME_DEPTH_MM
# (== SIDE_PLATE_WIDTH_MM, 11mm) breiter Querschnitt, genau wie die
# Seitenteile. Tragen an BEIDEN Laengskanten alle FRAME_TONGUE_SPACING_MM
# (100mm) eine nach aussen ragende Zunge -- IDENTISCH bei beiden Varianten,
# diese Zungen stecken durch ein passendes Loch in der Hauskontur (siehe
# windowMarker/dxfExport.py). An den beiden ENDEN (den Laengsenden, wo eine
# side- auf eine top-Leiste trifft -- die 4 Ecken des Rahmens) unter-
# scheiden sich die Varianten: "side" hat dort eine Zunge, "top" eine
# Aussparung derselben Tiefe -- zusammen ein Eckstoss an allen 4 Ecken.
# EIGENE (kleinere) Masse als die wiederkehrenden Laengskanten-Zungen, siehe
# FRAME_END_TONGUE_WIDTH_MM/FRAME_END_TONGUE_HEIGHT_MM unten -- die 10mm-
# Breite gilt NUR fuer die Laengskanten-Zungen, nicht fuer den Eckstoss.
FRAME_DEPTH_MM = SIDE_PLATE_WIDTH_MM
FRAME_TONGUE_SPACING_MM = 100.0
FRAME_TONGUE_HEIGHT_MM = 2.9
# Feste Breite der WIEDERKEHRENDEN Laengskanten-Zungen (nicht von
# FRAME_DEPTH_MM abgeleitet, gilt NUR fuer diese -- der Eckstoss an den
# Leisten-ENDEN hat eine eigene, depth/2-basierte Breite, siehe unten).
FRAME_TONGUE_WIDTH_MM = 10.0
# Eckstoss an den Leisten-ENDEN (wo side- auf top-Leiste trifft): eigene
# Masse, unabhaengig von den wiederkehrenden Laengskanten-Zungen. Breite =
# depth/2 (mit 0.1mm Presssitz-Uebermass bei der Zunge, ohne bei der
# Aussparung -- Original-Formel), Hoehe (wie weit sie uebersteht/einschneidet)
# = 3mm, EIGENER Wert, nicht FRAME_TONGUE_HEIGHT_MM (die gilt nur fuer die
# wiederkehrenden Zungen).
FRAME_END_TONGUE_WIDTH_MM = FRAME_DEPTH_MM / 2 + 0.1
FRAME_END_CUTOUT_WIDTH_MM = FRAME_DEPTH_MM / 2
FRAME_END_TONGUE_HEIGHT_MM = 3.0
# Materialstaerke der Platten selbst (Hauskontur UND Rahmenleiste, beide aus
# demselben Plattenmaterial) -- bestimmt die Breite des Lochs, das eine
# wiederkehrende Laengskanten-Zunge in die Hauskontur schneiden muss (siehe
# frame_strip_tongue_hole_positions), PLUS 0.1mm Presssitz-Luft. Auch fuer
# die "Materialstaerke als Doppellinie"-Voransicht der Kontur im Editor
# UND den entsprechend nach aussen erweiterten Kontur-Beschnitt beim Export
# gebraucht (siehe led_batch_editor.App._draw_frame_rect,
# dxfExport.clip_outline_to_frame).
FRAME_MATERIAL_THICKNESS_MM = 3.0
# Breite des Lochs, QUER zur Zungen-Laengsrichtung -- NICHT von
# FRAME_TONGUE_HEIGHT_MM abgeleitet (die bestimmt nur, wie weit die Zunge an
# der Leiste selbst uebersteht, nicht wie breit das Loch im Gegenstueck sein
# muss). GENAU FRAME_MATERIAL_THICKNESS_MM (KEIN zusaetzliches Presssitz-
# Uebermass mehr) -- der Rand (siehe dxfExport.clip_outline_to_frame, dort
# um genau diese Materialstaerke nach aussen erweitert) ist exakt so breit
# wie das Loch tief ist, das Loch darf also NICHT ueber den Rand
# hinausragen, sonst waere es teilweise ausserhalb der geschnittenen
# Kontur-Flaeche statt vollstaendig darin zu liegen.
FRAME_HOLE_DEPTH_MM = FRAME_MATERIAL_THICKNESS_MM
# Abstand vom jeweiligen Ende, ab dem die erste wiederkehrende Laengskanten-
# Zunge sitzt -- laesst Platz fuer den Eckstoss dort (Schaetzwert, siehe
# Modul-Docstring/Uebergabe an den Nutzer -- im Code leicht anpassbar).
FRAME_END_MARGIN_MM = 15.0


def _frame_repeat_tongue_positions(length_mm: float) -> list:
    """X-Positionen (linke Kante) der wiederkehrenden Laengskanten-Zungen
    einer Rahmenleiste dieser Laenge -- alle FRAME_TONGUE_SPACING_MM,
    mit FRAME_END_MARGIN_MM Abstand zu beiden Enden (Platz fuer den
    Eckstoss, siehe _get_frame_strip_points)."""
    xs = []
    x = FRAME_END_MARGIN_MM
    while x + FRAME_TONGUE_WIDTH_MM <= length_mm - FRAME_END_MARGIN_MM:
        xs.append(x)
        x += FRAME_TONGUE_SPACING_MM
    return xs


def _get_frame_strip_points(length_mm: float, end_as_tongue: bool) -> ezdxf.document.Drawing:
    """Baut EINE Rahmenleiste: Aussenkontur length_mm x FRAME_DEPTH_MM, mit
    wiederkehrenden Zungen an beiden Laengskanten (siehe
    _frame_repeat_tongue_positions, FRAME_TONGUE_WIDTH_MM breit x
    FRAME_TONGUE_HEIGHT_MM ueberstehend) UND an beiden Enden dem Eckstoss --
    entweder einer Zunge (`end_as_tongue=True`, FRAME_END_TONGUE_WIDTH_MM
    breit) oder einer Aussparung (`end_as_tongue=False`,
    FRAME_END_CUTOUT_WIDTH_MM breit), beide mittig im FRAME_DEPTH_MM breiten
    Querschnitt, FRAME_END_TONGUE_HEIGHT_MM tief/ueberstehend -- EIGENE Masse,
    unabhaengig von den wiederkehrenden Laengskanten-Zungen. Gemeinsamer
    Unterbau fuer get_frame_side_points/get_frame_top_points."""
    doc, _add_rect = _new_plate_doc()
    depth = FRAME_DEPTH_MM
    tw, th = FRAME_TONGUE_WIDTH_MM, FRAME_TONGUE_HEIGHT_MM
    end_w = FRAME_END_TONGUE_WIDTH_MM if end_as_tongue else FRAME_END_CUTOUT_WIDTH_MM
    end_th = FRAME_END_TONGUE_HEIGHT_MM
    end_margin = (depth - end_w) / 2
    y_lo, y_hi = end_margin, end_margin + end_w
    positions = _frame_repeat_tongue_positions(length_mm)

    outline = [(0.0, 0.0)]
    # Unterkante (Y=0), X=0 -> length_mm, mit nach unten ragenden Zungen.
    for x in positions:
        outline += [(x, 0.0), (x, -th), (x + tw, -th), (x + tw, 0.0)]
    outline.append((length_mm, 0.0))

    # Rechtes Ende (Y=0 -> depth): Zunge ragt ueber X=length_mm hinaus,
    # Aussparung schneidet von X=length_mm nach innen.
    end_x = length_mm + end_th if end_as_tongue else length_mm - end_th
    outline += [(length_mm, y_lo), (end_x, y_lo), (end_x, y_hi), (length_mm, y_hi)]
    outline.append((length_mm, depth))

    # Oberkante (Y=depth), X=length_mm -> 0, mit nach oben ragenden Zungen.
    for x in reversed(positions):
        outline += [(x + tw, depth), (x + tw, depth + th), (x, depth + th), (x, depth)]
    outline.append((0.0, depth))

    # Linkes Ende (Y=depth -> 0): spiegelbildlich zum rechten Ende.
    start_x = -end_th if end_as_tongue else end_th
    outline += [(0.0, y_hi), (start_x, y_hi), (start_x, y_lo), (0.0, y_lo)]

    doc.modelspace().add_lwpolyline(outline, close=True, dxfattribs={'layer': 'OUTLINE', 'color': 1})
    return doc


def get_frame_side_points(length_mm: float) -> ezdxf.document.Drawing:
    """Rahmenleiste fuer LINKS/RECHTS vom Haus -- Zungen an beiden Enden
    (stecken in die Aussparungen der Oben/Unten-Leisten, siehe
    get_frame_top_points, an allen 4 Ecken des Rahmens). Siehe
    _get_frame_strip_points fuer die gemeinsame Konstruktion."""
    return _get_frame_strip_points(length_mm, end_as_tongue=True)


def get_frame_top_points(length_mm: float) -> ezdxf.document.Drawing:
    """Rahmenleiste fuer OBEN/UNTEN vom Haus -- Aussparungen an beiden
    Enden (nehmen die Zungen der Links/Rechts-Leisten auf, siehe
    get_frame_side_points, an allen 4 Ecken des Rahmens). Siehe
    _get_frame_strip_points fuer die gemeinsame Konstruktion."""
    return _get_frame_strip_points(length_mm, end_as_tongue=False)


# Zusaetzliches Mittenloch der "top-mit-Loch"-Variante (siehe
# get_frame_top_hole_points, z.B. fuer eine Kabeldurchfuehrung) -- NUR bei
# DIESER Variante, nicht bei den anderen 3 Rahmenleisten. FRAME_TOP_HOLE_
# WIDTH_MM laeuft entlang der Leisten-LAENGSRICHTUNG (X, dieselbe Richtung
# wie die Gesamtbreite der Leiste), FRAME_TOP_HOLE_DEPTH_MM quer dazu (Y,
# passt mit Rand in den FRAME_DEPTH_MM=11mm breiten Querschnitt).
FRAME_TOP_HOLE_WIDTH_MM = 10.5
FRAME_TOP_HOLE_DEPTH_MM = 6.5
# Abstand von der Unterkante (Y=0) bis zum Loch -- NICHT mittig im
# Querschnitt, nur mittig entlang der Laenge (X), siehe unten.
FRAME_TOP_HOLE_MARGIN_MM = 0.65


def get_frame_top_hole_points(length_mm: float) -> ezdxf.document.Drawing:
    """Wie get_frame_top_points, PLUS ein zusaetzliches rechteckiges
    Mittenloch (z.B. fuer eine Kabeldurchfuehrung): FRAME_TOP_HOLE_WIDTH_MM
    (10.5mm) x FRAME_TOP_HOLE_DEPTH_MM (6.5mm), entlang der Leisten-Laenge
    (X) mittig ueber length_mm zentriert, aber quer dazu (Y) NICHT mittig --
    FRAME_TOP_HOLE_MARGIN_MM (0.65mm) Abstand zur Unterkante (Y=0), der Rest
    bleibt zur Oberkante hin frei. EIGENE, separate Datei (siehe
    led_batch_editor.App._export_project) -- ersetzt eine der beiden sonst
    identischen top/bottom-Leisten; die andere bleibt unveraendert bei
    get_frame_top_points."""
    doc = get_frame_top_points(length_mm)
    hole_w, hole_h = FRAME_TOP_HOLE_WIDTH_MM, FRAME_TOP_HOLE_DEPTH_MM
    hx = length_mm / 2 - hole_w / 2
    hy = FRAME_TOP_HOLE_MARGIN_MM
    pts = [(hx, hy), (hx + hole_w, hy), (hx + hole_w, hy + hole_h), (hx, hy + hole_h)]
    doc.modelspace().add_lwpolyline(pts, close=True, dxfattribs={'layer': 'OUTLINE', 'color': 1})
    return doc


def frame_strip_tongue_hole_positions(length_mm: float) -> list:
    """Liste von (x, y, w, h) -- die Loecher (im LOKALEN Koordinatensystem
    einer bei (0,0) beginnenden, entlang X verlaufenden Rahmenleiste
    dieser Laenge, siehe _get_frame_strip_points), die deren wieder-
    kehrende Laengskanten-Zungen in die Hauskontur schneiden muessen
    (siehe windowMarker/dxfExport.py) -- EIN Loch je Zungen-Position.

    Die beiden Loch-Dimensionen sind ABSICHTLICH unterschiedlich behandelt:
    - Tiefe (quer zur Zungen-Laengsrichtung) = FRAME_HOLE_DEPTH_MM, GENAU
      FRAME_MATERIAL_THICKNESS_MM, OHNE jedes Presssitz-Mass -- diese Seite
      muss exakt zur aussen um dieselbe Materialstaerke erweiterten Kontur
      passen (siehe dxfExport.clip_outline_to_frame), ein Uebermass wuerde
      hier ueber die beschnittene Kontur hinausragen.
    - Breite (entlang der Zungen-Laengsrichtung) = FRAME_TONGUE_WIDTH_MM
      MINUS 0.1mm Presssitz-Untermass (0.05mm je Seite, mittig zur Zunge --
      dieselbe Konvention wie TONGUE_HOLE_UNDERSIZE_MM beim Footprint-
      Zungen-Loch), damit die Zunge selbst (bleibt bei voller Breite, siehe
      _get_frame_strip_points) stramm hineinpasst.

    Liegt komplett auf der lokalen NEGATIVEN Y-Seite (Y=0 bis
    Y=-FRAME_HOLE_DEPTH_MM) -- Y=0 ist die Kante, an der die Leiste an der
    Hauskontur anliegt, negative Y ist dieselbe 'nach aussen'-Richtung, in
    die auch die Zunge selbst ragt (siehe _get_frame_strip_points). NICHT
    mittig um Y=0 (das liesse die Haelfte des Lochs ins Hausinnere
    hineinragen) -- das Loch soll komplett im Rand (dem Materialstreifen)
    liegen. Der Aufrufer (dxfExport.frame_side_hole_rects_mm) spiegelt diese
    'nach aussen'-Richtung je nach Haus-Seite passend (links/oben behalten
    sie, rechts/unten drehen sie um)."""
    undersize = 0.1
    tw = FRAME_TONGUE_WIDTH_MM - undersize
    hd = FRAME_HOLE_DEPTH_MM
    return [(x + undersize / 2, -hd, tw, hd) for x in _frame_repeat_tongue_positions(length_mm)]


def export_all_footprints(sizes: dict, out_dir) -> list:
    """Erzeugt UND schreibt je Groesse aus `sizes` ({name: (width_mm,
    height_mm)}) eine Footprint-DXF (per get_footprint_points) nach
    `out_dir` (<name-ohne-.dxf>.dxf) -- PLUS, einmal je DISTINKTER width_mm
    (mehrere Footprint-Groessen mit gleicher Breite teilen sich dieselbe
    Bodenplatten-VORLAGE), eine Bodenplatten-DXF (per
    get_bottom_plate_points) als 'bottomplate-{width_mm}mm.dxf' -- UND,
    einmal je DISTINKTER height_mm (dito fuer die Seitenteile), ZWEI
    Seitenteil-DXFs (Aussen-/Innen-Variante, je 2x in der Stueckliste
    benoetigt -- siehe csvExport.py -- aber als DXF-Vorlage reicht je EINE
    Datei) als 'sideplate-outer-{height_mm}mm.dxf'/
    'sideplate-inner-{height_mm}mm.dxf'. Gibt die Liste der geschriebenen
    Dateipfade zurueck."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list = []
    widths_done: set = set()
    heights_done: set = set()
    for name, (width_mm, height_mm) in sizes.items():
        doc = get_footprint_points(width_mm, height_mm)
        out_path = out_dir / f'{Path(name).stem}.dxf'
        doc.saveas(str(out_path))
        written.append(out_path)

        if width_mm not in widths_done:
            widths_done.add(width_mm)
            bottom_doc = get_bottom_plate_points(width_mm)
            bottom_path = out_dir / f'bottomplate-{width_mm:g}mm.dxf'
            bottom_doc.saveas(str(bottom_path))
            written.append(bottom_path)

        if height_mm not in heights_done:
            heights_done.add(height_mm)
            for variant, inner in (('outer', False), ('inner', True)):
                side_doc = get_side_plate_points(height_mm, inner)
                side_path = out_dir / f'sideplate-{variant}-{height_mm:g}mm.dxf'
                side_doc.saveas(str(side_path))
                written.append(side_path)
    return written


# Abstand zwischen den Teilen auf dem kombinierten Schnitt-Blatt (siehe
# nest_parts_sheet) -- wie der Luftspalt, den ein Laser zwischen zwei
# nebeneinanderliegenden Teilen braucht, damit sie sich nicht beruehren.
PART_SPACING_MM = 5.0

# Ziel-Breite des Schnitt-Blatts (siehe nest_parts_sheet) -- sobald eine
# Zeile diese Breite ueberschreiten wuerde, beginnt eine NEUE Zeile darunter,
# damit das Ergebnis ein ungefaehr RECHTECKIGES Blatt ist statt einer
# einzigen, beliebig langen Reihe.
SHEET_MAX_WIDTH_MM = 600.0


def _doc_bbox(doc: ezdxf.document.Drawing) -> tuple:
    """(min_x, min_y, max_x, max_y) ueber ALLE LWPOLYLINE-Punkte in `doc`."""
    pts = [p for e in doc.modelspace().query('LWPOLYLINE') for p in e.get_points()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def nest_parts_sheet(items: list, out_path, spacing_mm: float = PART_SPACING_MM,
                     max_row_width_mm: float = SHEET_MAX_WIDTH_MM) -> Path:
    """Baut EIN einzelnes DXF, das `items` -- eine Liste von
    (ezdxf.Drawing, count)-Paaren, z.B. [(get_bottom_plate_points(75), 3),
    (get_side_plate_points(40, inner=False), 6), ...] -- als `count` Kopien
    JE Eintrag nebeneinander/untereinander vereint. ZEILEN-Packung (Shelf
    Packing): Teile werden von links nach rechts angeordnet, sobald die
    naechste Kopie SHEET_MAX_WIDTH_MM ueberschreiten wuerde, beginnt eine
    neue Zeile darunter -- Ergebnis ist ein ungefaehr RECHTECKIGES Blatt
    statt einer einzigen langen Reihe. PART_SPACING_MM (5mm) Abstand
    zwischen allen Teilen, in beiden Richtungen.

    Jede (Doc, count)-Gruppe wird VOLLSTAENDIG abgearbeitet, bevor die
    naechste beginnt -- die Reihenfolge in `items` bestimmt also, in
    welcher Gruppierung die Teile auf dem Blatt erscheinen (z.B. alle
    Bodenplatten, dann alle Footprints, dann alle Seitenteile, dann die
    Hauszeichnung -- siehe led_batch_editor.App._export_project fuer die
    tatsaechliche Reihenfolge/Herkunft der Stueckzahlen, die 1:1 aus der
    Stueckliste stammen, siehe csvExport.get_part_counts).

    Schreibt EINE Datei nach `out_path` (Elternordner wird bei Bedarf
    angelegt) und gibt den Path zurueck."""
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    for layer, color in (('OUTLINE', 1), ('PINS', 1), ('SKETCH', 8)):
        if layer not in doc.layers:
            doc.layers.add(layer, color=color)

    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for part_doc, count in items:
        if count <= 0:
            continue
        min_x, min_y, max_x, max_y = _doc_bbox(part_doc)
        part_w, part_h = max_x - min_x, max_y - min_y
        entities = list(part_doc.modelspace().query('LWPOLYLINE'))
        for _ in range(count):
            if cursor_x > 0.0 and cursor_x + part_w > max_row_width_mm:
                cursor_x = 0.0
                cursor_y += row_height + spacing_mm
                row_height = 0.0
            for e in entities:
                pts = [(p[0] - min_x + cursor_x, p[1] - min_y + cursor_y) for p in e.get_points()]
                msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': e.dxf.layer, 'color': e.dxf.color})
            cursor_x += part_w + spacing_mm
            row_height = max(row_height, part_h)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out_path))
    return out_path
