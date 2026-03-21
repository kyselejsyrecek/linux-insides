# -*- coding: utf-8 -*-
"""
Google Open Buildings – JOSM importer
======================================
Jython skript pro doplněk JOSM Scripting (Jython engine).

Stáhne polygony budov z datasetu Google Open Buildings V3 pro aktuální
výřez mapy v JOSM a vloží je jako novou vrstvu „Google Open Buildings".

Instalace a spuštění
--------------------
1. V JOSM nainstalujte doplněk „Scripting" (Předvolby › Doplňky).
2. Doplněk musí mít dostupný engine Jython (obvykle se stáhne automaticky).
3. Přibližte mapu na oblast, pro kterou chcete data stáhnout.
4. Scripting ▸ Run Script … › vyberte tento soubor.

Zdroj dat
---------
Google Open Buildings V3
  https://sites.research.google/open-buildings/
  Licence: Creative Commons Attribution 4.0 International (CC BY 4.0)
  GCS bucket: gs://open-buildings-data/v3/
  HTTP: https://storage.googleapis.com/open-buildings-data/v3/

Struktura GCS dat
-----------------
  tiles.geojson
      Index dlaždic – FeatureCollection, každá feature je jeden S2 level-4
      tile s vlastností „tile_id" a polygonem hranice.
  polygons_s2_level_4_gzip/{tile_id}_buildings.csv.gz
      Gzipovaný CSV soubor s budovami pro danou dlaždici.
      Sloupce: latitude, longitude, area_in_meters, confidence,
               geometry (WKT POLYGON (lon lat, …)), full_plus_code

Pokrytí datasetu
----------------
  Afrika, jižní Asie, část jihovýchodní Asie, Oceánie.
  Evropa a Amerika nejsou zahrnuty.

Omezení
-------
  - JOSM bude dočasně nereagovat po dobu stahování (skript běží v EDT).
  - Doporučujeme přiblížit na oblast max. ~ 50 × 50 km (≤ 4 dlaždice S2).
  - Jeden S2 level-4 tile pokrývá přibližně 98 000 km² a může obsahovat
    statisíce budov; pro JOSM doporučujeme stahovat malé oblasti.
"""

import csv
import json

try:
    from StringIO import StringIO          # Jython 2.7 / Python 2
except ImportError:
    from io import StringIO                # Python 3 (záložní)

from java.io import BufferedReader, InputStreamReader
from java.lang import StringBuilder
from java.net import URL
from java.util.zip import GZIPInputStream
from javax.swing import JOptionPane

from org.openstreetmap.josm.data.coor import LatLon
from org.openstreetmap.josm.data.osm import DataSet, Node, Way
from org.openstreetmap.josm.gui import MainApplication
from org.openstreetmap.josm.gui.layer import OsmDataLayer

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------

_GOB_BASE  = "https://storage.googleapis.com/open-buildings-data/v3"
_TILES_URL = _GOB_BASE + "/tiles.geojson"
# {t} se nahradí tokenem dlaždice (např. „06f")
_CSV_TMPL  = _GOB_BASE + "/polygons_s2_level_4_gzip/{t}_buildings.csv.gz"

_MAX_TILES  = 4       # max. počet dlaždic bez dalšího varování
_CON_TIMEOUT = 30000  # ms – timeout připojení
_READ_TIMEOUT = 180000  # ms – timeout čtení (gzip soubory mohou být velké)


# ---------------------------------------------------------------------------
# Pomocné funkce – síť
# ---------------------------------------------------------------------------

def _fetch_text(url_str, gzip=False):
    """Stáhne URL a vrátí obsah jako řetězec Unicode.

    Parametry
    ---------
    url_str : str
        URL ke stažení.
    gzip : bool
        True = obsah je gzip-komprimovaný, rozbalí se před čtením.
    """
    conn = URL(url_str).openConnection()
    conn.setConnectTimeout(_CON_TIMEOUT)
    conn.setReadTimeout(_READ_TIMEOUT)
    conn.setRequestProperty("User-Agent", "JOSM-OpenBuildings/1.0")
    raw = conn.getInputStream()
    stream = GZIPInputStream(raw) if gzip else raw
    reader = BufferedReader(InputStreamReader(stream, "UTF-8"))
    sb = StringBuilder()
    line = reader.readLine()
    while line is not None:
        sb.append(line)
        sb.append(u"\n")
        line = reader.readLine()
    reader.close()
    return unicode(sb.toString())


# ---------------------------------------------------------------------------
# Pomocné funkce – geometrie
# ---------------------------------------------------------------------------

def _bbox_intersects(tile_box, bounds):
    """Vrátí True, pokud se tile_box [W, S, E, N] překrývá s JOSM Bounds."""
    w, s, e, n = tile_box
    return not (
        e < bounds.getMinLon() or w > bounds.getMaxLon() or
        n < bounds.getMinLat() or s > bounds.getMaxLat()
    )


def _wkt_polygon_to_latlon(wkt):
    """Parsuje 'POLYGON ((lon lat, lon lat, …))' → [(lat, lon), …].

    Poznámka: WKT ukládá souřadnice v pořadí (zeměpisná délka, šířka),
    zatímco JOSM používá (šířka, délka) = (lat, lon).
    """
    try:
        start = wkt.index("((") + 2
        end   = wkt.rindex("))")
        coords = []
        for pair in wkt[start:end].split(","):
            xy = pair.strip().split()
            if len(xy) >= 2:
                coords.append((float(xy[1]), float(xy[0])))   # (lat, lon)
        return coords
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Parsování CSV
# ---------------------------------------------------------------------------

def _parse_gob_csv(text, bounds):
    """Parsuje CSV soubor Google Open Buildings.

    Vrátí seznam polygonů filtrovaných na centroidy uvnitř ``bounds``.
    Každý polygon je seznam ``(lat, lon)`` tuplů.

    Formát CSV:
        latitude, longitude, area_in_meters, confidence,
        geometry (WKT POLYGON), full_plus_code
    """
    buildings = []

    # csv.reader v Jythonu/Pythonu 2 očekává bytový (str) vstup,
    # nikoliv unicode – proto kódujeme do ASCII (data jsou čistě ASCII).
    lines_bytes = [line.encode("ascii", "replace")
                   for line in text.splitlines()]
    if not lines_bytes:
        return buildings

    reader = csv.reader(lines_bytes)
    try:
        header = [c.strip().lower() for c in next(reader)]
    except StopIteration:
        return buildings

    # Zjistíme indexy sloupců z hlavičky; záložní pevné pořadí pro V3.
    try:
        i_lat  = header.index("latitude")
        i_lon  = header.index("longitude")
        i_geom = header.index("geometry")
    except ValueError:
        i_lat, i_lon, i_geom = 0, 1, 4

    min_lat = bounds.getMinLat()
    max_lat = bounds.getMaxLat()
    min_lon = bounds.getMinLon()
    max_lon = bounds.getMaxLon()

    for row in reader:
        if len(row) <= i_geom:
            continue
        try:
            lat = float(row[i_lat])
            lon = float(row[i_lon])
        except ValueError:
            continue

        # Rychlý test: střed budovy musí ležet v bounding boxu.
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue

        wkt = row[i_geom].strip()
        if not wkt.startswith("POLYGON"):
            continue

        coords = _wkt_polygon_to_latlon(wkt)
        if len(coords) >= 3:
            buildings.append(coords)

    return buildings


# ---------------------------------------------------------------------------
# Tvorba vrstvy JOSM
# ---------------------------------------------------------------------------

def _create_osm_layer(buildings):
    """Vytvoří OsmDataLayer se zadanými polygony budov.

    Každý polygon se stane uzavřeným Way s tagem building=yes
    a source=Google Open Buildings.
    """
    ds = DataSet()

    for coords in buildings:
        # Odstraníme uzavírací duplikát (POLYGON má první == poslední bod).
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) < 3:
            continue

        nodes = []
        for lat, lon in coords:
            nd = Node(LatLon(lat, lon))
            ds.addPrimitive(nd)
            nodes.append(nd)

        nodes.append(nodes[0])   # uzavřeme prstenec (první == poslední)

        w = Way()
        w.setNodes(nodes)
        w.put("building", "yes")
        w.put("source", "Google Open Buildings")
        ds.addPrimitive(w)

    return OsmDataLayer(ds, u"Google Open Buildings", None)


# ---------------------------------------------------------------------------
# Hlavní funkce
# ---------------------------------------------------------------------------

def main():
    # --- 0) Zjistíme aktuální výřez mapy v JOSM ----------------------------
    map_frame = MainApplication.getMap()
    if map_frame is None:
        JOptionPane.showMessageDialog(
            None,
            u"Žádná mapa není otevřena.\n"
            u"Otevřete nejprve datovou vrstvu nebo OSM data\n"
            u"a přibližte se na oblast zájmu (Afrika, jižní Asie…).",
            u"Google Open Buildings",
            JOptionPane.ERROR_MESSAGE)
        return

    bounds = map_frame.mapView.getRealBounds()
    bb_info = u"%.5f°, %.5f°  …  %.5f°, %.5f°" % (
        bounds.getMinLat(), bounds.getMinLon(),
        bounds.getMaxLat(), bounds.getMaxLon())

    rc = JOptionPane.showConfirmDialog(
        None,
        u"Importovat budovy Google Open Buildings pro výřez:\n%s\n\n"
        u"Skript stáhne index dlaždic a pak příslušné CSV soubory.\n"
        u"⚠  JOSM bude po dobu stahování dočasně nereagovat." % bb_info,
        u"Google Open Buildings – Import",
        JOptionPane.OK_CANCEL_OPTION,
        JOptionPane.QUESTION_MESSAGE)
    if rc != JOptionPane.OK_OPTION:
        return

    try:
        # --- 1) Stáhneme index dlaždic (tiles.geojson) ---------------------
        print("[GOB] Stahuji index dlaždic: " + _TILES_URL)
        tiles_data = json.loads(_fetch_text(_TILES_URL))

        # --- 2) Filtrujeme dlaždice dle bounding boxu ----------------------
        matching = []
        for feat in tiles_data.get("features", []):
            token = feat.get("properties", {}).get("tile_id", "")
            if not token:
                continue
            geom = feat.get("geometry", {})
            if geom.get("type") != "Polygon":
                continue
            ring = geom["coordinates"][0]
            lons = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            if _bbox_intersects([min(lons), min(lats), max(lons), max(lats)], bounds):
                matching.append(token)

        print("[GOB] Protínající dlaždice (%d): %s" % (len(matching), matching))

        if not matching:
            JOptionPane.showMessageDialog(
                None,
                u"Žádná dlaždice datasetu nepokrývá zvolený výřez.\n\n"
                u"Dataset Google Open Buildings pokrývá:\n"
                u"  • Afriku\n"
                u"  • Jižní Asii\n"
                u"  • Část jihovýchodní Asie\n"
                u"  • Oceánii\n\n"
                u"Přesuňte výřez do pokryté oblasti a zkuste znovu.",
                u"Google Open Buildings",
                JOptionPane.INFORMATION_MESSAGE)
            return

        # Varování při příliš velké oblasti
        if len(matching) > _MAX_TILES:
            rc2 = JOptionPane.showConfirmDialog(
                None,
                u"Oblast zahrnuje %d dlaždic (doporučené maximum: %d).\n"
                u"Stahování může trvat velmi dlouho nebo selhat.\n\n"
                u"Doporučujeme přiblížit se na oblast cca 50 × 50 km.\n"
                u"Přesto pokračovat?" % (len(matching), _MAX_TILES),
                u"Příliš velká oblast",
                JOptionPane.YES_NO_OPTION,
                JOptionPane.WARNING_MESSAGE)
            if rc2 != JOptionPane.YES_OPTION:
                return

        # --- 3) Stáhneme a naparsujeme CSV soubory -------------------------
        all_buildings = []
        errors = []

        for token in matching:
            url = _CSV_TMPL.replace("{t}", token)
            print("[GOB] Stahuji dlaždici %s …" % token)
            try:
                csv_text = _fetch_text(url, gzip=True)
                bldgs = _parse_gob_csv(csv_text, bounds)
                print("[GOB]   → %d budov v bounding boxu" % len(bldgs))
                all_buildings.extend(bldgs)
            except Exception as ex:
                err_msg = u"Dlaždice %s: %s" % (token, unicode(ex))
                errors.append(err_msg)
                print(u"[GOB] CHYBA: " + err_msg)

        if not all_buildings:
            warn = u"V zadané oblasti nebyly nalezeny žádné budovy."
            if errors:
                warn += u"\n\nChyby:\n" + u"\n".join(errors)
            JOptionPane.showMessageDialog(
                None, warn,
                u"Google Open Buildings", JOptionPane.WARNING_MESSAGE)
            return

        # --- 4) Vytvoříme vrstvu a přidáme do JOSM -------------------------
        layer = _create_osm_layer(all_buildings)
        MainApplication.getLayerManager().addLayer(layer)

        summary = u"Importováno %d budov z %d dlaždice/dlaždic." % (
            len(all_buildings), len(matching))
        if errors:
            summary += u"\n\nChyby při stahování (%d dlaždic):\n%s" % (
                len(errors), u"\n".join(errors))
        JOptionPane.showMessageDialog(
            None, summary,
            u"Google Open Buildings – Hotovo ✓",
            JOptionPane.INFORMATION_MESSAGE)

    except Exception as ex:
        import traceback
        tb = traceback.format_exc()
        JOptionPane.showMessageDialog(
            None,
            u"Neočekávaná chyba:\n%s\n\n%s" % (unicode(ex), unicode(tb)[:1500]),
            u"Google Open Buildings – Chyba",
            JOptionPane.ERROR_MESSAGE)
        raise   # výpis do konzole Scripting plugin


# ---------------------------------------------------------------------------
main()
