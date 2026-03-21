# Google Open Buildings – import do JOSM

Tento adresář obsahuje Jython skript pro doplněk **JOSM Scripting**, který
stahuje polygony budov z datasetu
[Google Open Buildings V3](https://sites.research.google/open-buildings/)
a vkládá je jako novou vrstvu **OSM Data** přímo do JOSM.

---

## Co je Google Open Buildings?

Google Open Buildings je veřejný dataset obsahující přibližně 2,5 miliardy
automaticky detekovaných půdorysů budov získaných analýzou satelitních
snímků. Pokrývá:

- **Afriku** (plné pokrytí)
- Jižní Asii
- Část jihovýchodní Asie
- Oceánii

Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

---

## Proč ne MapWithAI?

Doplněk **MapWithAI** v JOSM poskytuje data detekce budov z AI (Meta/Facebook
Rapid), která ale nepokrývají africký kontinent. Google Open Buildings je
proto pro Afriku prakticky jediný volně dostupný velkorozlišovací zdroj
půdorysů budov.

---

## Požadavky

| Požadavek | Verze |
|-----------|-------|
| JOSM | nejnovější vývojová verze (tested build ≥ 18000) |
| Doplněk **Scripting** | nejnovější verze z Preference › Doplňky |
| Engine **Jython** | automaticky stažen doplňkem Scripting |

Doplněk Scripting stáhne Jython engine automaticky při prvním spuštění,
pokud ještě není nainstalován.

---

## Instalace skriptu

Soubor `google_open_buildings_import.py` z tohoto adresáře stačí jen
uložit kamkoliv na disk – žádná instalace není potřeba.

---

## Použití – krok za krokem

### 1. Přibližte JOSM na oblast zájmu

Otevřete libovolnou datovou vrstvu (např. stáhněte OSM data přes
**Soubor › Stáhnout data z OSM**) a přibližte výřez na oblast, pro kterou
chcete importovat budovy.

> ⚠ **Doporučená velikost oblasti:** cca **50 × 50 km** (≤ 4 dlaždice S2).
> Pro větší oblasti může stahování trvat desítky minut nebo JOSM zamrznout.

### 2. Spusťte skript

**Scripting ▸ Run Script …** → vyberte soubor
`google_open_buildings_import.py` → klikněte **Open**.

### 3. Potvrďte bounding box

Skript zobrazí dialog s informací o výřezu a požádá o potvrzení.

### 4. Počkejte na stažení

JOSM bude po dobu stahování dočasně nereagovat (skript běží synchronně
v EDT – Event Dispatch Thread). Průběh lze sledovat v konzoli Scripting
pluginu (záložka **Scripting console**).

### 5. Výsledná vrstva

Po dokončení se v JOSM objeví nová vrstva **„Google Open Buildings"**
s polygony budov označenými tagy:

```
building = yes
source   = Google Open Buildings
```

### 6. Sloučení s OSM daty

Vrstvu s importovanými budovami můžete:
- Porovnat s existujícími OSM daty (přepínáním viditelnosti vrstev)
- Ručně zkontrolovat a opravit geometrie
- Přidat další tagy (název, typ budovy apod.)
- Nakonec **sloučit** s OSM vrstvou přes **Vrstva ▸ Sloučit vrstvu**
  a nahrát na OSM

> ⚠ Před nahráváním na OSM ověřte, že data jsou aktuální a přesná,
> a zkontrolujte licenční podmínky. Google Open Buildings jsou dostupné
> pod CC BY 4.0, což je kompatibilní s ODbL při správném attribution.

---

## Technické detaily

### Zdroj dat (URL)

Skript přistupuje k datům přímo z Google Cloud Storage:

```
https://storage.googleapis.com/open-buildings-data/v3/tiles.geojson
https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/{tile_id}_buildings.csv.gz
```

Soubor `tiles.geojson` je GeoJSON FeatureCollection, kde každá feature
reprezentuje jeden S2 level-4 tile s jeho hranicí a identifikátorem
(`tile_id`). Skript stáhne tento index, zjistí, které dlaždice se
překrývají s aktuálním výřezem, a pak stáhne odpovídající CSV soubory.

### Formát CSV

```
latitude, longitude, area_in_meters, confidence, geometry, full_plus_code
```

Sloupec `geometry` obsahuje polygon budovy ve formátu WKT:

```
POLYGON ((lon1 lat1, lon2 lat2, …))
```

> Pozor: WKT ukládá souřadnice v pořadí **(zeměpisná délka, šířka)**,
> zatímco JOSM používá **(šířka, délka)**. Skript pořadí automaticky
> přehodí.

### Dlaždice S2 level 4

Jeden S2 level-4 tile pokrývá přibližně **98 000 km²** (± záleží na
zeměpisné šířce). Pro africkou oblast, kde jsou budovy hustě zastoupeny,
může jeden tile obsahovat statisíce budov. Proto silně doporučujeme
stahovat malé oblasti.

---

## Řešení problémů

| Příznak | Možná příčina | Řešení |
|---------|--------------|--------|
| `java.net.ConnectException` | Žádné připojení k internetu nebo blokovaný GCS | Zkontrolujte připojení; GCS musí být dostupný |
| `java.net.SocketTimeoutException` | Dlaždice je příliš velká / pomalé připojení | Zmenšete oblast nebo zvyšte `_READ_TIMEOUT` ve skriptu |
| „Žádná dlaždice nepokrývá výřez" | Oblast leží mimo pokrytí (Evropa, Amerika) | Přesuňte výřez do Afriky / Asie / Oceánie |
| JOSM zamrzne na velmi dlouho | Stahujete příliš velkou oblast | Přibližte výřez a spusťte znovu |
| `AttributeError: 'NoneType'` na `getMap()` | Žádná vrstva není otevřena | Otevřete libovolnou datovou vrstvu |

---

## Konfigurace ve skriptu

Na začátku souboru `google_open_buildings_import.py` lze upravit:

```python
_MAX_TILES   = 4        # max. počet dlaždic bez varování
_CON_TIMEOUT = 30000    # timeout připojení v ms
_READ_TIMEOUT = 180000  # timeout čtení v ms
```
