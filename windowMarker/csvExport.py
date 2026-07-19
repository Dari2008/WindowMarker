#!/usr/bin/env python3
"""
csvExport.py -- Exportiert die Stueckliste (Part-Count) eines Hauses als CSV.

get_part_counts()  DIE zentrale Funktion: zaehlt, wie viele physische
                   Platinen-Platzierungen es insgesamt gibt (eine platzierte
                   Variante = ein Teil, unabhaengig davon, wie viele LEDs
                   darauf aktiv sind), wie viele davon nahe der Bodenkante
                   des Hauses liegen, und wie viele Bodenplatten/Seitenteile/
                   innere Seitenteile JE TATSAECHLICH VORKOMMENDER
                   Footprint-Groesse gebraucht werden (siehe
                   dxfExport.resolve_footprint_size/collect_footprint_sizes
                   -- es gibt keine benannten Footprint-"Typen" mehr, jede
                   Groesse bekommt einfach ihre eigene Zeile, benannt nach
                   ihren mm-Massen). Diese counts sind die Grundlage fuer die
                   Stueckzahl im kombinierten Teile-Blatt UND fuer die
                   Dateinamen der einzeln exportierten Teile (siehe
                   footprintScale.nest_parts_sheet/led_batch_editor.
                   App._export_project -- 'quantity_name.dxf'), damit CSV
                   und tatsaechlich geschriebene Dateien NIEMALS
                   auseinanderlaufen. Gibt eine Liste von {'count',
                   'description', 'filename'}-Dicts zurueck.
export_csv()       Schreibt eine Liste solcher Dicts als CSV-Datei (Spalten:
                   count, description, filename).

Den projektweiten Export-Einstiegspunkt (alle Haeuser auf einmal, siehe
images.json) gibt es NICHT mehr in diesem Modul -- er lebt als
ledBatchEditor.App._export_project (kombiniert DXF + CSV + Bodenplatten-/
Seitenteil-Dateien in EINEM Rutsch, siehe dort). Der Footprint selbst wird
NICHT mehr als eigene Datei geschrieben (nur als Skizze/Ausschnitt direkt
in die Hauszeichnung eingefuegt).
"""

import csv
import json
from pathlib import Path

import dxfExport

# Schwelle fuer "nahe der Bodenkante" -- 4 cm = 40 mm. Eine Platzierung
# zaehlt als bodennah, wenn ihre UNTERKANTE (tiefster Punkt ihrer LEDs)
# innerhalb dieser Distanz zur Unterkante der Gebaeude-Kontur liegt
# (Outline.bottom, siehe dxfExport.house_outline) -- also mit dem unteren
# 4cm-Streifen des Hauses ueberschneidet.
BOTTOM_THRESHOLD_MM = 40.0

# Wie viele Seitenteile/innere Seitenteile JE PLATZIERUNG gebraucht werden --
# unabhaengig von der tatsaechlichen Footprint-Groesse (siehe
# _format_size_mm): jede Groesse braucht gleich viele Stueck, nur eben in
# ihrer JEWEILS EIGENEN (unterschiedlich grossen) Auspraegung -- daher
# getrennte Stueckliste-Zeilen pro Groesse, aber derselbe Multiplikator.
SIDE_PIECES_PER_PLACEMENT = 2
INNER_SIDE_PIECES_PER_PLACEMENT = 2
# Bodenplatte: EIN Stueck JE PLATZIERUNG (siehe footprintScale.py -- eine
# Bodenplatte spannt genau eine Platzierungs-Breite). Der Footprint selbst
# wird NICHT als eigene Datei exportiert (nur als Skizze/Ausschnitt direkt
# in die Hauszeichnung eingefuegt, siehe dxfExport._insert_footprints) --
# daher KEINE eigene Stueckliste-Zeile/Datei dafuer.
BOTTOM_PLATES_PER_PLACEMENT = 1
# Verbinder sind dagegen bei JEDER Groesse physisch IDENTISCH -- deshalb nur
# EINE Zeile ueber alle Platzierungen hinweg, nicht nach Groesse aufgesplittet.
CONNECTORS_PER_PLACEMENT = 1

# Feste Anzahl je Haus (unabhaengig von der Zahl der LED-Platzierungen) --
# die Gehaeuseteile des Lichtkastens: zwei identische Frontteile mit den
# Fensteroeffnungen (fuer die "Glasscheiben"), sowie je zwei schmale
# Rahmenleisten horizontal (oben/unten) und vertikal (links/rechts).
OUTLINE_WITH_PANES_COUNT = 2
OUTLINE_HORIZONTAL_COUNT = 2
OUTLINE_VERTICAL_COUNT = 2

# Rahmenleisten (siehe footprintScale.get_frame_side_points/
# get_frame_top_points): je Haus zwei seitliche (links/rechts, gleiche
# Laenge = Rahmenhoehe) und zwei horizontale (oben/unten, gleiche Laenge =
# Rahmenbreite) -- daher je EINE Datei/Zeile mit Stueckzahl 2.
FRAME_SIDE_COUNT = 2
FRAME_TOP_COUNT = 2


def count_footprint_sizes(entries: list, variant_size: tuple | None = None) -> dict:
    """Zaehlt, wie oft jede (width_mm, height_mm)-Footprint-Groesse unter
    `entries` (siehe dxfExport.get_placed_leds) vorkommt -- EINE Platzierung
    (variantUuid-Gruppe) = EIN Vorkommen ihrer aufgeloesten Groesse (siehe
    dxfExport.resolve_footprint_size). Gemeinsame Grundlage fuer
    get_part_counts() (Stueckliste) UND das kombinierte Teile-Blatt (siehe
    footprintScale.nest_parts_sheet/led_batch_editor.App._export_project) --
    BEIDE rufen HIER dieselbe Zaehlung ab, statt sie getrennt zu berechnen,
    damit CSV-Stueckzahlen und tatsaechlich aufs Blatt gepackte Kopien
    GARANTIERT uebereinstimmen. Gibt {(width_mm, height_mm): count} zurueck."""
    by_placement: dict = {}
    for e in entries:
        by_placement.setdefault(e['variantUuid'], []).append(e)
    size_counts: dict = {}
    for leds in by_placement.values():
        size = dxfExport.resolve_footprint_size(variant_size, leds)
        size_counts[size] = size_counts.get(size, 0) + 1
    return size_counts


def get_part_counts(house_data: dict, variant: dict | None = None,
                    outline: dxfExport.Outline | None = None,
                    house_name: str | None = None,
                    frame_rect: tuple | None = None) -> list:
    """Baut die Stueckliste fuer EIN Haus.

    house_data: der geladene <name>.json-Datensatz.
    variant: die eine LED-Variante aus public/batch_variants.json (fuer die
    Beschriftung/den Namen des Teils UND ihre Default-Footprint-Groesse,
    falls eine einzelne Platzierung keine eigene hat -- siehe
    dxfExport.resolve_footprint_size) -- optional, Default-Bezeichnung
    "LED-Platine" ohne sie.
    outline: die Gebaeude-Umriss-Box (siehe dxfExport.house_outline, IN MM --
    also mit passendem px_per_mm aufgerufen). Ohne Outline kann weder
    bestimmt werden, was "nahe der Bodenkante" ist, noch macht eine Zeile zu
    Gehaeuseteilen (die sich auf DIESE Kontur beziehen) Sinn -- beide fallen
    dann einfach weg.
    house_name: Name des Hauses (Unterordner-/Dateiname ohne Endung) --
    fuer die 'filename'-Spalte (welche DXF-Datei zu dieser Zeile gehoert).
    Ohne Namen bleibt 'filename' bei den nicht footprint-groessen-bezogenen
    Zeilen leer.
    frame_rect: (left, top, right, bottom) in mm des Rahmen-Rechtecks (siehe
    led_batch_editor.App._export_project) -- bestimmt die Laenge der
    Rahmenleisten-Zeilen. Ohne outline oder frame_rect entfallen diese
    Zeilen.

    Gruppiert nach physischer Platzierung (dxfExport.get_placed_leds()'s
    variantUuid = ledBatches[].id -- eine Platine, unabhaengig davon, wie
    viele ihrer LEDs aktiv sind), nicht nach einzelner LED. 'filename'
    traegt IMMER die Stueckzahl als Praefix (siehe led_batch_editor.
    App._export_project, das die Dateien mit demselben Namen schreibt --
    'quantity_name.dxf' statt nur 'name.dxf', damit auf einen Blick klar
    ist, wie viele Kopien in der Datei gemeint sind). Der Footprint selbst
    hat KEINE eigene Zeile/Datei (nur Skizze/Ausschnitt direkt in der
    Hauszeichnung, siehe dxfExport._insert_footprints). Gibt eine Liste von
    {'count', 'description', 'filename'}-Dicts zurueck, z.B.:
        [{'count': 5, 'description': '70mm', 'filename': 'haus.dxf'},
         {'count': 2, 'description': '70mm (nahe Bodenkante, <= 40mm)', 'filename': 'haus.dxf'},
         {'count': 6, 'description': 'Bodenplatte (10mm)', 'filename': '6_bottomplate-10mm.dxf'},
         {'count': 4, 'description': 'Bodenplatte (75mm)', 'filename': '4_bottomplate-75mm.dxf'},
         {'count': 6, 'description': 'Seitenteile (100mm)', 'filename': '6_sideplate-outer-100mm.dxf'},
         {'count': 6, 'description': 'Innere Seitenteile (100mm)', 'filename': '6_sideplate-inner-100mm.dxf'},
         {'count': 4, 'description': 'Seitenteile (60mm)', 'filename': '4_sideplate-outer-60mm.dxf'},
         {'count': 4, 'description': 'Innere Seitenteile (60mm)', 'filename': '4_sideplate-inner-60mm.dxf'},
         {'count': 5, 'description': 'Verbinder', 'filename': 'haus.dxf'},
         {'count': 2, 'description': 'Gebaeudekontur mit Fensterscheiben', 'filename': '2_haus_outline_with_panes.dxf'},
         {'count': 2, 'description': 'Kontur horizontal', 'filename': '4_haus_outline.dxf'},
         {'count': 2, 'description': 'Kontur vertikal', 'filename': '4_haus_outline.dxf'},
         {'count': 2, 'description': 'Rahmenleiste seitlich (150mm)', 'filename': '2_frameside-150mm.dxf'},
         {'count': 2, 'description': 'Rahmenleiste oben/unten (200mm)', 'filename': '2_frametop-200mm.dxf'}]
    """
    entries = dxfExport.get_placed_leds(house_data)
    if not entries:
        return []

    by_placement: dict = {}
    for e in entries:
        by_placement.setdefault(e['variantUuid'], []).append(e)

    variant_name = (variant or {}).get('name') or 'LED-Platine'
    fw = (variant or {}).get('footprint_width_mm')
    fh = (variant or {}).get('footprint_height_mm')
    variant_size = (fw, fh) if fw and fh else None
    led_dxf = f'{house_name}.dxf' if house_name else None

    rows = [{'count': len(by_placement), 'description': variant_name, 'filename': led_dxf}]

    if outline is not None:
        near_bottom = 0
        for leds in by_placement.values():
            lowest_y = max(led['y'] + led['h'] for led in leds)
            if outline.bottom - lowest_y <= BOTTOM_THRESHOLD_MM:
                near_bottom += 1
        rows.append({
            'count': near_bottom,
            'description': f'{variant_name} (nahe Bodenkante, <= {BOTTOM_THRESHOLD_MM:.0f}mm)',
            'filename': led_dxf,
        })

    size_counts = count_footprint_sizes(entries, variant_size)

    # Bodenplatte haengt NUR von width_mm ab (siehe footprintScale.
    # get_bottom_plate_points) -- mehrere Groessen mit gleicher Breite
    # teilen sich dieselbe Bodenplatten-Datei, daher HIER separat nach
    # width_mm aufsummiert statt in der (width_mm, height_mm)-Schleife
    # unten (sonst gaebe es fuer dieselbe Breite mehrere Zeilen).
    width_counts: dict = {}
    for (width_mm, height_mm), count in size_counts.items():
        width_counts[width_mm] = width_counts.get(width_mm, 0) + count
    for width_mm, count in sorted(width_counts.items()):
        bp_count = count * BOTTOM_PLATES_PER_PLACEMENT
        label = f'{width_mm:g}mm'
        rows.append({'count': bp_count,
                    'description': f'Bodenplatte ({label})',
                    'filename': f'{bp_count}_bottomplate-{label}.dxf'})

    # Seitenteile haengen NUR von height_mm ab (siehe footprintScale.
    # get_side_plate_points) -- aus demselben Grund wie bei der Bodenplatte
    # HIER separat nach height_mm aufsummiert.
    height_counts: dict = {}
    for (width_mm, height_mm), count in size_counts.items():
        height_counts[height_mm] = height_counts.get(height_mm, 0) + count
    for height_mm, count in sorted(height_counts.items()):
        h_label = f'{height_mm:g}mm'
        outer_count = count * SIDE_PIECES_PER_PLACEMENT
        inner_count = count * INNER_SIDE_PIECES_PER_PLACEMENT
        rows.append({'count': outer_count,
                    'description': f'Seitenteile ({h_label})',
                    'filename': f'{outer_count}_sideplate-outer-{h_label}.dxf'})
        rows.append({'count': inner_count,
                    'description': f'Innere Seitenteile ({h_label})',
                    'filename': f'{inner_count}_sideplate-inner-{h_label}.dxf'})

    rows.append({'count': len(by_placement) * CONNECTORS_PER_PLACEMENT,
                'description': 'Verbinder', 'filename': led_dxf})

    if outline is not None:
        panes_count = OUTLINE_WITH_PANES_COUNT
        outline_count = OUTLINE_HORIZONTAL_COUNT + OUTLINE_VERTICAL_COUNT
        outline_with_panes_dxf = f'{panes_count}_{house_name}_outline_with_panes.dxf' if house_name else None
        outline_only_dxf = f'{outline_count}_{house_name}_outline.dxf' if house_name else None
        rows.append({'count': panes_count,
                    'description': 'Gebaeudekontur mit Fensterscheiben', 'filename': outline_with_panes_dxf})
        rows.append({'count': OUTLINE_HORIZONTAL_COUNT,
                    'description': 'Kontur horizontal', 'filename': outline_only_dxf})
        rows.append({'count': OUTLINE_VERTICAL_COUNT,
                    'description': 'Kontur vertikal', 'filename': outline_only_dxf})

    if outline is not None and frame_rect is not None:
        frame_left, frame_top, frame_right, frame_bottom = frame_rect
        side_length = frame_bottom - frame_top
        top_length = frame_right - frame_left
        side_label = f'{side_length:g}mm'
        top_label = f'{top_length:g}mm'
        side_dxf = f'{FRAME_SIDE_COUNT}_frameside-{side_label}.dxf' if house_name else None
        top_dxf = f'{FRAME_TOP_COUNT}_frametop-{top_label}.dxf' if house_name else None
        rows.append({'count': FRAME_SIDE_COUNT,
                    'description': f'Rahmenleiste seitlich ({side_label})', 'filename': side_dxf})
        rows.append({'count': FRAME_TOP_COUNT,
                    'description': f'Rahmenleiste oben/unten ({top_label})', 'filename': top_dxf})

    return rows


def export_csv(rows: list, out_path) -> Path:
    """Schreibt `rows` (Liste von {'count','description','filename'}-Dicts)
    als CSV (Spalten: count, description, filename). Gibt den geschriebenen
    Dateipfad zurueck."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['count', 'description', 'filename'])
        writer.writeheader()
        writer.writerows(rows)
    return out_path


