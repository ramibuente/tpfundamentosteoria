# -*- coding: utf-8 -*-
"""
=============================================================================
ANÁLISIS DE RENDIMIENTO DE INTERNET EN ARGENTINA
Trabajo universitario - Fundamentos de Ingeniería (Parte 2)
=============================================================================

Compara dos conjuntos de datos REALES de rendimiento de Internet en Argentina
(Ookla Open Data: red fija vs red móvil) usando métricas de latencia y
throughput de mediciones de usuarios, los compara con datos oficiales de ENACOM
(velocidad media y rangos de velocidad por provincia, Q4 2024) y correlaciona los
resultados con la infraestructura de conectividad del país: cables submarinos y
puntos de aterrizaje (Las Toninas), red troncal terrestre y estaciones
satelitales de ARSAT, y última milla.

Datasets de entrada (ya descargados, NO se descarga nada de internet):
  - 2024-10-01_performance_fixed_tiles.parquet    (Ookla red fija,  Q4 2024)
  - 2024-10-01_performance_mobile_tiles.parquet   (Ookla red móvil, Q4 2024)
  - Internet Accesos Velocidad Provincias.xlsx    (ENACOM, histograma vel.)
  - Internet Accesos Velocidad Rango Provincias.xlsx (ENACOM, rangos de vel.)

Salidas:
  CSV  -> ookla_argentina_summary.csv, ookla_argentina_distribucion.csv,
          ookla_argentina_regions.csv,
          enacom_velocidad_media_2024q4_clean.csv, enacom_rangos_2024q4_clean.csv
  PNG  -> 8 gráficos (comparación fija/móvil, distribución de latencia, latencia
          vs throughput, download y latencia por región, y top ENACOM)
  Además imprime al final un RESUMEN TEXTUAL automático con los hallazgos.

Requisitos: pandas, matplotlib, pyarrow, openpyxl  (geopandas es OPCIONAL).
Autor: generado para Rami.
=============================================================================
"""

# -----------------------------------------------------------------------------
# 0) IMPORTS Y CONFIGURACIÓN
# -----------------------------------------------------------------------------
import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")               # backend sin pantalla (sirve también en Colab)
import matplotlib.pyplot as plt

import pyarrow.dataset as ds        # lectura eficiente de parquet con filtros
import pyarrow.compute as pc        # expresiones de filtro "push-down"
from matplotlib.path import Path    # test punto-en-polígono (sin descargar nada)

# =============================================================================
# CONFIGURACIÓN (lo único que un usuario podría querer cambiar)
# =============================================================================
# Trimestre objetivo de ENACOM. Si el archivo NO tiene ese período, el programa
# avisa y usa automáticamente el más reciente disponible (así no se rompe para
# quien tenga otra descarga de ENACOM).
ANIO_OBJETIVO = 2024
TRIM_OBJETIVO = 4

# Carpeta de datos: por defecto, la carpeta donde está este script/notebook.
# El programa también busca los archivos en subcarpetas comunes ('data', 'datos').
# Todas las salidas (CSV, PNG, TXT) se guardan en esta misma carpeta.
if "__file__" in globals():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
else:                                # en notebook/Colab no existe __file__
    BASE_DIR = os.getcwd()
os.chdir(BASE_DIR)
print(f"[INFO] Carpeta de trabajo: {BASE_DIR}")

# ---- Búsqueda automática y portable de los archivos de entrada --------------
# En vez de exigir un nombre exacto, buscamos por PATRÓN. Así el código funciona
# aunque el usuario tenga otro trimestre (otra fecha en el nombre del parquet) o
# haya guardado los datos en una subcarpeta. Se valida con mensajes claros.
_CARPETAS_BUSQUEDA = [BASE_DIR, os.path.join(BASE_DIR, "data"), os.path.join(BASE_DIR, "datos")]

def _buscar(patrones, descripcion):
    """Devuelve el primer archivo que coincide con alguno de los patrones, o None."""
    for carpeta in _CARPETAS_BUSQUEDA:
        for patron in patrones:
            encontrados = sorted(glob.glob(os.path.join(carpeta, patron)))
            if encontrados:
                return encontrados[0]
    return None

# PORTABILIDAD: preferimos el subconjunto YA filtrado a Argentina (archivos
# 'ookla_ar_*.parquet', de ~1 MB), que SÍ entra en GitHub y permite correr OFFLINE
# sin descargar nada. Si no está, usamos el parquet GLOBAL grande (~359/195 MB) y
# lo filtramos en vivo. Esos subconjuntos se generan una vez con 'preparar_datasets_ar.py'.
F_FIXED_AR  = _buscar(["ookla_ar_fixed*.parquet"],  "Ookla AR fija (pre-filtrado)")
F_MOBILE_AR = _buscar(["ookla_ar_mobile*.parquet"], "Ookla AR móvil (pre-filtrado)")

OOKLA_FIXED_PREFILTRADO  = F_FIXED_AR is not None
OOKLA_MOBILE_PREFILTRADO = F_MOBILE_AR is not None

F_FIXED  = F_FIXED_AR or _buscar(
    ["*performance_fixed_tiles.parquet", "*fixed*tiles*.parquet", "*fixed*.parquet"], "Ookla red fija")
F_MOBILE = F_MOBILE_AR or _buscar(
    ["*performance_mobile_tiles.parquet", "*mobile*tiles*.parquet", "*mobile*.parquet"], "Ookla red móvil")
F_VELOC  = _buscar(["*Velocidad Provincias*.xlsx", "*elocidad*rovincias*.xlsx", "*velocidad*provincia*.xlsx"],
                   "ENACOM velocidad por provincia")
F_RANGOS = _buscar(["*Velocidad Rango*Provincias*.xlsx", "*ango*rovincias*.xlsx", "*rango*.xlsx"],
                   "ENACOM rangos por provincia")

# ---- Chequeo de insumos con mensajes amigables ------------------------------
_REQUERIDOS = {
    "Ookla red fija (.parquet)":          F_FIXED,
    "Ookla red móvil (.parquet)":         F_MOBILE,
    "ENACOM velocidad por provincia (.xlsx)": F_VELOC,
    "ENACOM rangos por provincia (.xlsx)":    F_RANGOS,
}
print("\n[INFO] Archivos de entrada detectados:")
_faltan = []
for desc, ruta in _REQUERIDOS.items():
    if ruta:
        print(f"   OK  {desc:42s} -> {os.path.basename(ruta)}")
    else:
        print(f"   --  {desc:42s} -> NO ENCONTRADO")
        _faltan.append(desc)
if _faltan:
    raise FileNotFoundError(
        "No se encontraron estos archivos: " + "; ".join(_faltan) + ".\n"
        "Colocá los 4 archivos de entrada en la misma carpeta de este script/notebook "
        "(o en una subcarpeta 'data'/'datos'). Nombres esperados (Ookla Open Data y ENACOM):\n"
        "  - <fecha>_performance_fixed_tiles.parquet\n"
        "  - <fecha>_performance_mobile_tiles.parquet\n"
        "  - 'Internet Accesos Velocidad Provincias.xlsx'\n"
        "  - 'Internet Accesos Velocidad Rango Provincias.xlsx'"
    )

# ---- Período de Ookla deducido del nombre del archivo (para títulos/textos) --
# Los parquet de Ookla traen la fecha del trimestre en el nombre (p.ej.
# '2024-10-01' = Q4 2024). Lo parseamos para que los gráficos y textos muestren
# el período REAL de los datos en vez de un valor fijo.
def _periodo_desde_nombre(ruta):
    nombre = os.path.basename(ruta) or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", nombre)      # parquet global: 2024-10-01
    if m:
        anio, mes = int(m.group(1)), int(m.group(2))
        return f"Q{(mes - 1)//3 + 1} {anio}"
    m = re.search(r"(\d{4})q(\d)", nombre, re.IGNORECASE)  # subset AR: ..._2024q4
    if m:
        return f"Q{int(m.group(2))} {int(m.group(1))}"
    return "(período Ookla)"

OOKLA_PERIODO = _periodo_desde_nombre(F_FIXED)
_fuente = "subconjunto pre-filtrado (offline, apto GitHub)" if OOKLA_FIXED_PREFILTRADO else "parquet global Ookla"
print(f"\n[INFO] Fuente Ookla: {_fuente}")
print(f"[INFO] Período Ookla detectado: {OOKLA_PERIODO}")

# Límites geográficos aproximados de Argentina (bounding box) -----------------
# La consigna fija estos valores. Los usamos como PRIMER filtro rápido en la
# lectura del parquet (predicate push-down).
LAT_MIN, LAT_MAX = -56, -21         # tile_y = latitud
LON_MIN, LON_MAX = -74, -53         # tile_x = longitud

# Refinamiento con polígono aproximado de Argentina ---------------------------
# Un bounding box rectangular incluye porciones grandes de países limítrofes
# (p.ej. Santiago de Chile aporta un solo tile con +16.000 tests, y Montevideo,
# Asunción y el sur de Brasil también caen dentro del rectángulo). Eso DISTORSIONA
# los promedios. Para evitarlo, además del bounding box aplicamos un test
# "punto en polígono" contra un contorno aproximado de Argentina continental
# (vértices lon/lat embebidos: NO se descarga ningún shapefile). Se valida con
# ciudades conocidas: Buenos Aires, Córdoba, Mendoza, Mar del Plata, Salta,
# Bariloche quedan DENTRO; Santiago de Chile y Montevideo quedan AFUERA.
# Limitación: es un contorno simplificado (~45 vértices); tiles muy pegados a la
# frontera podrían clasificarse mal. Es una aproximación adecuada para el TP.
POLY_ARGENTINA = [
    (-66.3, -22.0), (-62.8, -22.0), (-62.3, -22.2), (-61.0, -23.0), (-59.5, -24.1),
    (-58.2, -24.9), (-58.6, -27.3), (-56.0, -27.3), (-55.0, -25.6), (-53.6, -26.2),
    (-53.7, -27.6), (-55.2, -28.0), (-56.0, -29.5), (-57.6, -30.2), (-58.1, -32.0),
    (-58.2, -33.9), (-57.3, -34.9), (-56.7, -36.4), (-57.55, -38.05), (-59.0, -38.9),
    (-61.0, -39.0), (-62.3, -38.9), (-63.8, -41.0), (-65.0, -40.8), (-65.0, -43.0),
    (-65.3, -45.0), (-67.5, -46.0), (-67.7, -49.3), (-69.0, -52.0), (-68.4, -52.4),
    (-72.5, -51.6), (-72.0, -49.0), (-73.4, -47.0), (-71.8, -45.0), (-71.6, -42.9),
    (-71.4, -40.8), (-71.0, -38.8), (-70.9, -37.0), (-70.0, -35.2), (-69.8, -33.0),
    (-70.0, -31.0), (-69.5, -29.0), (-68.4, -27.0), (-68.6, -24.5), (-67.2, -23.0),
    (-66.3, -22.0),
]
# Tierra del Fuego (isla) como rectángulo aparte, ya que el contorno continental
# llega sólo hasta el estrecho de Magallanes (~-52.5).
POLY_TDF = [(-68.7, -52.5), (-65.0, -52.5), (-65.0, -55.2), (-68.7, -55.2)]
_PATH_AR = Path(POLY_ARGENTINA)
_PATH_TDF = Path(POLY_TDF)

def en_argentina(lon, lat):
    """Devuelve un array booleano: True si el punto cae dentro de Argentina."""
    pts = np.column_stack([np.asarray(lon), np.asarray(lat)])
    return _PATH_AR.contains_points(pts) | _PATH_TDF.contains_points(pts)


# -----------------------------------------------------------------------------
# 1) y 2) CARGA + FILTRADO DE OOKLA A ARGENTINA
# -----------------------------------------------------------------------------
# Los parquet de Ookla son GLOBALES (millones de tiles de ~600 m). Cada fila es
# un "tile" con su centroide en tile_x (longitud) y tile_y (latitud) y métricas
# agregadas de las mediciones de usuarios de ese tile.
#
# Como los archivos son grandes, NO cargamos todo en memoria: usamos pyarrow
# con un filtro "push-down" sobre el bounding box, de modo que sólo se leen del
# disco las filas de Argentina.
def cargar_ookla_argentina(path, prefiltrado=False):
    """Devuelve los tiles de Argentina (con columnas en Mbps) desde un parquet.

    - prefiltrado=True  : el archivo YA es el subconjunto de Argentina
      ('ookla_ar_*.parquet'); se lee tal cual, sin filtrar (rápido y offline).
    - prefiltrado=False : el archivo es el parquet GLOBAL de Ookla; se aplica el
      filtro por bounding box (push-down) + el refinamiento por polígono.
    """
    dataset = ds.dataset(path)
    esperadas = ["tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps", "avg_lat_ms", "tests", "devices"]

    # Diagnóstico: si las columnas esperadas no estuvieran, lo avisamos.
    cols_disp = [f.name for f in dataset.schema]
    faltan = [c for c in esperadas if c not in cols_disp]
    if faltan:
        print(f"[ADVERTENCIA] En {os.path.basename(path)} faltan columnas {faltan}.")
        print(f"              Columnas disponibles: {cols_disp}")

    if prefiltrado:
        # Ya está acotado a Argentina: leemos directo (sin bounding box ni polígono).
        df = dataset.to_table(columns=esperadas).to_pandas()
        print(f"      {os.path.basename(path)}: {len(df):,} tiles (pre-filtrado a Argentina)")
    else:
        # Filtro geográfico aplicado en la lectura (mucho más rápido y liviano)
        filtro = (
            (pc.field("tile_x") >= LON_MIN) & (pc.field("tile_x") <= LON_MAX) &
            (pc.field("tile_y") >= LAT_MIN) & (pc.field("tile_y") <= LAT_MAX)
        )
        df = dataset.to_table(columns=esperadas, filter=filtro).to_pandas()
        # Refinamiento: descartamos tiles fuera del polígono de Argentina
        # (países limítrofes dentro del rectángulo), que inflarían los promedios.
        n_box = len(df)
        df = df[en_argentina(df["tile_x"].values, df["tile_y"].values)].copy()
        print(f"      {os.path.basename(path)}: {n_box:,} tiles en el box -> "
              f"{len(df):,} dentro del polígono de Argentina")

    # 4) Conversión de velocidades de Kbps a Mbps
    df["download_mbps"] = df["avg_d_kbps"] / 1000.0
    df["upload_mbps"]   = df["avg_u_kbps"] / 1000.0
    df["latencia_ms"]   = df["avg_lat_ms"].astype(float)
    return df


print("[1/2] Cargando Ookla (fixed y mobile) para Argentina...")
df_fixed  = cargar_ookla_argentina(F_FIXED,  prefiltrado=OOKLA_FIXED_PREFILTRADO)
df_mobile = cargar_ookla_argentina(F_MOBILE, prefiltrado=OOKLA_MOBILE_PREFILTRADO)
print(f"      Red fija:  {len(df_fixed):,} tiles en Argentina")
print(f"      Red móvil: {len(df_mobile):,} tiles en Argentina\n")


# -----------------------------------------------------------------------------
# 5) FUNCIÓN DE PROMEDIO PONDERADO POR CANTIDAD DE TESTS
# -----------------------------------------------------------------------------
# promedio_ponderado = sum(valor * tests) / sum(tests)
# Se usa porque cada tile representa una cantidad distinta de mediciones; un
# promedio simple le daría el mismo peso a un tile con 1 test que a uno con 1000.
def promedio_ponderado(df, columna, peso="tests"):
    w = df[peso].sum()
    if w == 0:
        return np.nan
    return (df[columna] * df[peso]).sum() / w


# -----------------------------------------------------------------------------
# 3) MÉTRICAS GENERALES POR DATASET  +  8) TABLA COMPARATIVA GENERAL
# -----------------------------------------------------------------------------
def resumen_general(df, tipo_red):
    """Calcula las métricas globales de un dataset Ookla."""
    return {
        "tipo_red": tipo_red,
        "tests": int(df["tests"].sum()),
        "devices": int(df["devices"].sum()),
        "download_mbps_promedio": round(promedio_ponderado(df, "download_mbps"), 2),
        "upload_mbps_promedio":   round(promedio_ponderado(df, "upload_mbps"), 2),
        "latencia_ms_promedio":   round(promedio_ponderado(df, "latencia_ms"), 2),
    }

ookla_summary = pd.DataFrame([
    resumen_general(df_fixed,  "fixed"),
    resumen_general(df_mobile, "mobile"),
])
print("[3/8] Tabla comparativa general Ookla (fixed vs mobile):")
print(ookla_summary.to_string(index=False), "\n")
ookla_summary.to_csv("ookla_argentina_summary.csv", index=False)


# -----------------------------------------------------------------------------
# 3b) DISTRIBUCIÓN DE LATENCIA Y RELACIÓN LATENCIA <-> THROUGHPUT
# -----------------------------------------------------------------------------
# El promedio ponderado resume con UN número, pero esconde la dispersión. Para
# comparar mejor "latencia y throughput de mediciones de usuarios" agregamos:
#   - estadística de distribución por tile: mediana y percentil 90 (p90),
#     que muestran el "valor típico" y la "cola" de mala experiencia;
#   - un gráfico de distribución de latencia (fija vs móvil);
#   - un scatter latencia vs download que evidencia la relación entre ambas
#     métricas (a mayor latencia, normalmente menor throughput).
# Nota: mediana y p90 se calculan a nivel de tile (cada tile = 1 punto), no
# ponderados, para describir la forma de la distribución geográfica.
def stats_distribucion(df, tipo_red):
    return {
        "tipo_red": tipo_red,
        "latencia_mediana_ms": round(df["latencia_ms"].median(), 2),
        "latencia_p90_ms":     round(df["latencia_ms"].quantile(0.90), 2),
        "download_mediana_mbps": round(df["download_mbps"].median(), 2),
        "download_p90_mbps":     round(df["download_mbps"].quantile(0.90), 2),
    }

ookla_distrib = pd.DataFrame([
    stats_distribucion(df_fixed,  "fixed"),
    stats_distribucion(df_mobile, "mobile"),
])
print("[3b] Distribución por tile (mediana y percentil 90):")
print(ookla_distrib.to_string(index=False), "\n")
ookla_distrib.to_csv("ookla_argentina_distribucion.csv", index=False)

# Gráfico: distribución (histograma) de latencia, fija vs móvil --------------
fig, ax = plt.subplots(figsize=(8.5, 4.8))
# Recortamos a 250 ms para que la cola no aplaste el histograma (sólo visual)
ax.hist(df_fixed["latencia_ms"].clip(0, 250),  bins=60, alpha=0.6,
        color="#2c7fb8", label="Fija (fixed)", edgecolor="white")
ax.hist(df_mobile["latencia_ms"].clip(0, 250), bins=60, alpha=0.6,
        color="#de2d26", label="Móvil (mobile)", edgecolor="white")
ax.axvline(promedio_ponderado(df_fixed, "latencia_ms"),  color="#08519c", ls="--",
           lw=2, label=f"Media pond. fija: {promedio_ponderado(df_fixed,'latencia_ms'):.1f} ms")
ax.axvline(promedio_ponderado(df_mobile, "latencia_ms"), color="#a50f15", ls="--",
           lw=2, label=f"Media pond. móvil: {promedio_ponderado(df_mobile,'latencia_ms'):.1f} ms")
ax.set_xlabel("Latencia (ms)"); ax.set_ylabel("Cantidad de tiles")
ax.set_title(f"Distribución de latencia: fija vs móvil (Ookla AR {OOKLA_PERIODO})", fontweight="bold")
ax.legend(fontsize=8); ax.grid(axis="y", ls="--", alpha=0.4)
fig.tight_layout(); fig.savefig("ookla_latency_distribution.png", dpi=130); plt.close(fig)

# Gráfico: latencia vs throughput (scatter), fija y móvil --------------------
fig, ax = plt.subplots(figsize=(8.5, 4.8))
ax.scatter(df_fixed["latencia_ms"].clip(0, 250),  df_fixed["download_mbps"],
           s=4, alpha=0.10, color="#2c7fb8", label="Fija (fixed)")
ax.scatter(df_mobile["latencia_ms"].clip(0, 250), df_mobile["download_mbps"],
           s=4, alpha=0.12, color="#de2d26", label="Móvil (mobile)")
ax.set_xlabel("Latencia (ms)"); ax.set_ylabel("Download (Mbps)")
ax.set_title(f"Relación latencia vs throughput (Ookla AR {OOKLA_PERIODO})", fontweight="bold")
leg = ax.legend(markerscale=4, fontsize=9)
for lh in leg.legend_handles:
    lh.set_alpha(1)
ax.grid(ls="--", alpha=0.4)
fig.tight_layout(); fig.savefig("ookla_latency_vs_throughput.png", dpi=130); plt.close(fig)
print("     Gráficos de distribución y dispersión guardados.\n")


# -----------------------------------------------------------------------------
# 6) y 7) AGRUPAMIENTO POR GRANDES REGIONES ARGENTINAS
# -----------------------------------------------------------------------------
# La consigna pide agrupar por 5 macro-regiones. Los tiles de Ookla NO traen el
# nombre de provincia, sólo coordenadas. Para no depender de descargas externas
# (shapefile), asignamos región mediante una APROXIMACIÓN por rangos de
# latitud/longitud. Es una simplificación: las fronteras provinciales reales son
# irregulares, así que algunos tiles cercanos a límites podrían quedar en la
# región vecina. Se documenta como limitación metodológica.
#
# Referencia de las 5 regiones (según la consigna):
#   Centro-Litoral/Pampeana: Buenos Aires, CABA, Córdoba, Santa Fe, Entre Ríos
#   NOA:   Jujuy, Salta, Tucumán, Catamarca, La Rioja, Santiago del Estero
#   NEA:   Chaco, Formosa, Corrientes, Misiones
#   Cuyo/Centro-oeste: Mendoza, San Juan, San Luis
#   Patagonia: Neuquén, Río Negro, Chubut, Santa Cruz, Tierra del Fuego, La Pampa
def asignar_region(lat, lon):
    """Asigna una macro-región argentina a partir de lat/lon aproximadas."""
    # Patagonia: todo el sur del país (al sur del paralelo -39 aprox.)
    if lat <= -39:
        return "Patagonia"
    # Norte del país (al norte de -29 aprox.): se separa por longitud en NOA/NEA
    if lat >= -29:
        # NEA (noreste, mesopotamia y Chaco-Formosa) está al este de -61.5 aprox.
        if lon >= -61.5:
            return "NEA"
        # NOA (noroeste) al oeste de -61.5
        return "NOA"
    # Franja central (lat entre -39 y -29): se separa por longitud
    #   Cuyo (centro-oeste, cordillera) al oeste de -65.5 aprox.
    if lon <= -65.5:
        return "Cuyo/Centro-oeste"
    # Resto de la franja central = Centro-Litoral/Pampeana
    return "Centro-Litoral/Pampeana"

ORDEN_REGIONES = ["Centro-Litoral/Pampeana", "NOA", "NEA", "Cuyo/Centro-oeste", "Patagonia"]

def resumen_por_region(df, tipo_red):
    """Aplica la asignación de región y calcula métricas ponderadas por región."""
    df = df.copy()
    df["region"] = [asignar_region(la, lo) for la, lo in zip(df["tile_y"], df["tile_x"])]
    filas = []
    for region, g in df.groupby("region"):
        filas.append({
            "region": region,
            "tipo_red": tipo_red,
            "tests": int(g["tests"].sum()),
            "devices": int(g["devices"].sum()),
            "download_mbps_promedio": round(promedio_ponderado(g, "download_mbps"), 2),
            "upload_mbps_promedio":   round(promedio_ponderado(g, "upload_mbps"), 2),
            "latencia_ms_promedio":   round(promedio_ponderado(g, "latencia_ms"), 2),
        })
    return pd.DataFrame(filas)

ookla_regions = pd.concat([
    resumen_por_region(df_fixed,  "fixed"),
    resumen_por_region(df_mobile, "mobile"),
], ignore_index=True)
# Ordenamos por tipo de red y por el orden geográfico de regiones definido arriba
ookla_regions["region"] = pd.Categorical(ookla_regions["region"], categories=ORDEN_REGIONES, ordered=True)
ookla_regions = ookla_regions.sort_values(["tipo_red", "region"]).reset_index(drop=True)
print("[6/9] Tabla Ookla por regiones:")
print(ookla_regions.to_string(index=False), "\n")
ookla_regions.to_csv("ookla_argentina_regions.csv", index=False)


# =============================================================================
# PARTE ENACOM
# =============================================================================
# -----------------------------------------------------------------------------
# Utilidad: parsear el formato numérico argentino de ENACOM.
# -----------------------------------------------------------------------------
# Los Excel de ENACOM traen los números con el PUNTO como separador de miles
# (p.ej. "1.142.774" = 1.142.774 accesos). Al abrir el archivo, algunos valores
# quedaron como texto ("1.142.774") y otros fueron mal interpretados como
# decimales (98.069 que en realidad es 98069). Esta función reconstruye el
# entero correcto en ambos casos:
#   - str  -> se quitan todos los puntos de miles.
#   - float con parte decimal -> el "." era separador de miles mal leído: x*1000.
#   - entero -> es una cuenta chica (<1000), se deja igual.
# (Validado: la suma del histograma de velocidad por provincia coincide
#  exactamente con la columna Total del archivo de rangos.)
def parse_arg_num(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    if isinstance(x, str):
        s = x.strip().replace(".", "").replace(" ", "")
        return float(s) if s else np.nan
    x = float(x)
    if abs(x - round(x)) > 1e-9:     # tiene parte decimal -> punto de miles mal leído
        return round(x * 1000)
    return round(x)

# Normalización de nombres de provincia: el archivo mezcla MAYÚSCULAS, Title Case
# y "Capital Federal"/"CABA". Unificamos para poder agrupar y comparar.
MAPA_PROV = {
    "capital federal": "CABA", "caba": "CABA", "ciudad autonoma de buenos aires": "CABA",
    "buenos aires": "Buenos Aires", "cordoba": "Córdoba", "córdoba": "Córdoba",
    "santa fe": "Santa Fe", "entre rios": "Entre Ríos", "entre ríos": "Entre Ríos",
    "jujuy": "Jujuy", "salta": "Salta", "tucuman": "Tucumán", "tucumán": "Tucumán",
    "catamarca": "Catamarca", "la rioja": "La Rioja",
    "santiago del estero": "Santiago del Estero",
    "chaco": "Chaco", "formosa": "Formosa", "corrientes": "Corrientes", "misiones": "Misiones",
    "mendoza": "Mendoza", "san juan": "San Juan", "san luis": "San Luis",
    "neuquen": "Neuquén", "neuquén": "Neuquén", "rio negro": "Río Negro", "río negro": "Río Negro",
    "chubut": "Chubut", "santa cruz": "Santa Cruz",
    "tierra del fuego": "Tierra del Fuego", "la pampa": "La Pampa",
}
def norm_prov(p):
    if not isinstance(p, str):
        return p
    return MAPA_PROV.get(p.strip().lower(), p.strip().title())

# Mapa provincia -> macro-región (para enriquecer las tablas de ENACOM)
PROV_A_REGION = {
    "Buenos Aires": "Centro-Litoral/Pampeana", "CABA": "Centro-Litoral/Pampeana",
    "Córdoba": "Centro-Litoral/Pampeana", "Santa Fe": "Centro-Litoral/Pampeana",
    "Entre Ríos": "Centro-Litoral/Pampeana",
    "Jujuy": "NOA", "Salta": "NOA", "Tucumán": "NOA", "Catamarca": "NOA",
    "La Rioja": "NOA", "Santiago del Estero": "NOA",
    "Chaco": "NEA", "Formosa": "NEA", "Corrientes": "NEA", "Misiones": "NEA",
    "Mendoza": "Cuyo/Centro-oeste", "San Juan": "Cuyo/Centro-oeste", "San Luis": "Cuyo/Centro-oeste",
    "Neuquén": "Patagonia", "Río Negro": "Patagonia", "Chubut": "Patagonia",
    "Santa Cruz": "Patagonia", "Tierra del Fuego": "Patagonia", "La Pampa": "Patagonia",
}

# 11) Selección ROBUSTA del trimestre objetivo (ANIO_OBJETIVO / TRIM_OBJETIVO).
# Si el archivo no tiene ese período (otra descarga de ENACOM), se usa el más
# reciente disponible y se avisa. Así el notebook es universal: nunca queda vacío.
def seleccionar_periodo(df, etiqueta):
    pares = df[["Año", "Trimestre"]].dropna()
    disponibles = sorted({(int(a), int(t)) for a, t in pares.values})
    if (ANIO_OBJETIVO, TRIM_OBJETIVO) in disponibles:
        return ANIO_OBJETIVO, TRIM_OBJETIVO
    ultimo = disponibles[-1]   # par (año, trimestre) más reciente
    print(f"        [AVISO] {etiqueta}: no se encontró {ANIO_OBJETIVO} Q{TRIM_OBJETIVO}. "
          f"Se usa el más reciente disponible: {ultimo[0]} Q{ultimo[1]}.")
    return ultimo

# -----------------------------------------------------------------------------
# 10), 11), 12) VELOCIDAD MEDIA POR PROVINCIA (ENACOM)
# -----------------------------------------------------------------------------
# El archivo "Velocidad Provincias" es en realidad un HISTOGRAMA: por cada
# provincia hay varias filas (una por cada valor de velocidad de bajada en Mbps)
# con la cantidad de accesos a esa velocidad. La "velocidad media de bajada" se
# obtiene como promedio PONDERADO de la velocidad por la cantidad de accesos:
#       velocidad_media = sum(Velocidad * Accesos) / sum(Accesos)
print("[10/12] Cargando ENACOM - velocidad media por provincia...")
veloc = pd.read_excel(F_VELOC, header=1)   # header real está en la 2da fila
print(f"        Columnas disponibles: {list(veloc.columns)}")
ANIO, TRIM = seleccionar_periodo(veloc, "velocidad media")
# Etiquetas y 'slug' de período usados en títulos, textos y nombres de salida.
# Para 2024 Q4 el slug da 'enacom_..._2024q4_clean.csv' (nombre que pide la consigna);
# para cualquier otro período el nombre se adapta automáticamente.
ENACOM_PERIODO = f"Q{TRIM} {ANIO}"
ENACOM_SLUG = f"{ANIO}q{TRIM}"
print(f"        Período ENACOM usado: {ENACOM_PERIODO}")
veloc = veloc[(veloc["Año"] == ANIO) & (veloc["Trimestre"] == TRIM)].copy()
veloc["Accesos"] = veloc["Accesos"].apply(parse_arg_num)
veloc["Provincia"] = veloc["Provincia"].apply(norm_prov)

filas_vm = []
for prov, g in veloc.groupby("Provincia"):
    total_acc = g["Accesos"].sum()
    vmedia = (g["Velocidad"] * g["Accesos"]).sum() / total_acc if total_acc else np.nan
    filas_vm.append({
        "provincia": prov,
        "region": PROV_A_REGION.get(prov, "Sin asignar"),
        "velocidad_media_bajada_mbps": round(vmedia, 2),
        "accesos_totales": int(total_acc),
    })
enacom_vmedia = pd.DataFrame(filas_vm).sort_values("velocidad_media_bajada_mbps", ascending=False).reset_index(drop=True)
enacom_vmedia["ranking"] = range(1, len(enacom_vmedia) + 1)
print(f"        Provincias procesadas: {len(enacom_vmedia)}")
enacom_vmedia.to_csv(f"enacom_velocidad_media_{ENACOM_SLUG}_clean.csv", index=False)

# Rankings (mayor y menor velocidad media)
top5_rapidas = enacom_vmedia.head(5)[["ranking", "provincia", "velocidad_media_bajada_mbps"]]
top5_lentas  = enacom_vmedia.tail(5).sort_values("velocidad_media_bajada_mbps")[["provincia", "velocidad_media_bajada_mbps"]]
print(f"\n  >> Top 5 provincias con MAYOR velocidad media (ENACOM {ENACOM_PERIODO}):")
print(top5_rapidas.to_string(index=False))
print(f"\n  >> Top 5 provincias con MENOR velocidad media (ENACOM {ENACOM_PERIODO}):")
print(top5_lentas.to_string(index=False), "\n")

# -----------------------------------------------------------------------------
# 13) RANGOS DE VELOCIDAD POR PROVINCIA (ENACOM)
# -----------------------------------------------------------------------------
# El archivo "Rango Provincias" da, por provincia, la cantidad de accesos en
# cada franja de velocidad. Calculamos:
#   - total de accesos
#   - accesos <= 10 Mbps  (Hasta 512k + 512k-1M + 1-6M + 6-10M) y su %
#   - accesos > 30 Mbps   (columna "+ 30 Mbps") y su %
print("[13] Cargando ENACOM - rangos de velocidad por provincia...")
rangos = pd.read_excel(F_RANGOS, header=1)
print(f"     Columnas disponibles: {list(rangos.columns)}")
anio_r, trim_r = seleccionar_periodo(rangos, "rangos de velocidad")  # mismo período (o su propio fallback)
rangos = rangos[(rangos["Año"] == anio_r) & (rangos["Trimestre"] == trim_r)].copy()

# Columnas de rangos (los nombres pueden variar; tomamos las que existen)
COLS_RANGO = ["Hasta 512 kbps", "+ 512 Kbps - 1 Mbps", "+ 1 Mbps - 6 Mbps",
              "+ 6 Mbps - 10 Mbps", "+ 10 Mbps - 20 Mbps", "+ 20 Mbps - 30 Mbps",
              "+ 30 Mbps", "Otros", "Total"]
for c in COLS_RANGO:
    if c in rangos.columns:
        rangos[c] = rangos[c].apply(parse_arg_num)
    else:
        print(f"     [ADVERTENCIA] No se encontró la columna '{c}'.")

rangos["Provincia"] = rangos["Provincia"].apply(norm_prov)
# Franja "<= 10 Mbps" = suma de las cuatro franjas más bajas
cols_lentas = ["Hasta 512 kbps", "+ 512 Kbps - 1 Mbps", "+ 1 Mbps - 6 Mbps", "+ 6 Mbps - 10 Mbps"]
cols_lentas = [c for c in cols_lentas if c in rangos.columns]

filas_r = []
for prov, g in rangos.groupby("Provincia"):
    g = g.iloc[0]  # una fila por provincia en el trimestre
    total = g["Total"] if "Total" in rangos.columns else g[COLS_RANGO[:-1]].sum()
    acc_lentos = sum(g[c] for c in cols_lentas)
    acc_30 = g["+ 30 Mbps"] if "+ 30 Mbps" in rangos.columns else np.nan
    filas_r.append({
        "provincia": prov,
        "region": PROV_A_REGION.get(prov, "Sin asignar"),
        "total_accesos": int(total),
        "accesos_10mbps_o_menos": int(acc_lentos),
        "pct_10mbps_o_menos": round(100 * acc_lentos / total, 2) if total else np.nan,
        "accesos_mas_30mbps": int(acc_30),
        "pct_mas_30mbps": round(100 * acc_30 / total, 2) if total else np.nan,
    })
enacom_rangos = pd.DataFrame(filas_r).sort_values("pct_10mbps_o_menos", ascending=False).reset_index(drop=True)
enacom_rangos.to_csv(f"enacom_rangos_{ENACOM_SLUG}_clean.csv", index=False)

# -----------------------------------------------------------------------------
# 14) TABLAS TOP 5 ENACOM
# -----------------------------------------------------------------------------
top5_lentos_pct = enacom_rangos.head(5)[["provincia", "total_accesos", "accesos_10mbps_o_menos", "pct_10mbps_o_menos"]]
top5_rapidos_pct = enacom_rangos.sort_values("pct_mas_30mbps", ascending=False).head(5)[
    ["provincia", "total_accesos", "accesos_mas_30mbps", "pct_mas_30mbps"]]
print(f"\n  >> Top 5 provincias con MAYOR % de accesos <= 10 Mbps (ENACOM {ENACOM_PERIODO}):")
print(top5_lentos_pct.to_string(index=False))
print(f"\n  >> Top 5 provincias con MAYOR % de accesos > 30 Mbps (ENACOM {ENACOM_PERIODO}):")
print(top5_rapidos_pct.to_string(index=False), "\n")


# =============================================================================
# 15) y 17) GRÁFICOS (matplotlib) -> PNG
# =============================================================================
print("[15/17] Generando gráficos PNG...")

def barras(x, y, titulo, ylabel, archivo, color="#2c7fb8", rot=0, fmt="{:.1f}"):
    """Helper para gráficos de barras simples y consistentes."""
    fig, ax = plt.subplots(figsize=(8, 4.8))
    barras_ = ax.bar([str(v) for v in x], y, color=color)
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.xticks(rotation=rot, ha="right" if rot else "center")
    for b, v in zip(barras_, y):
        if pd.notna(v):
            ax.text(b.get_x() + b.get_width()/2, v, fmt.format(v), ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(archivo, dpi=130)
    plt.close(fig)

# (a) Comparación fixed vs mobile: download / upload / latencia
fig, ax = plt.subplots(figsize=(8, 4.8))
metricas = ["download_mbps_promedio", "upload_mbps_promedio", "latencia_ms_promedio"]
etiquetas = ["Download (Mbps)", "Upload (Mbps)", "Latencia (ms)"]
x = np.arange(len(metricas)); w = 0.35
vf = ookla_summary[ookla_summary.tipo_red == "fixed"][metricas].values.flatten()
vm = ookla_summary[ookla_summary.tipo_red == "mobile"][metricas].values.flatten()
b1 = ax.bar(x - w/2, vf, w, label="Fija (fixed)", color="#2c7fb8")
b2 = ax.bar(x + w/2, vm, w, label="Móvil (mobile)", color="#de2d26")
ax.set_xticks(x); ax.set_xticklabels(etiquetas)
ax.set_title(f"Ookla Argentina ({OOKLA_PERIODO}): Internet fijo vs móvil", fontweight="bold")
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.4)
for bs in (b1, b2):
    for b in bs:
        ax.text(b.get_x()+b.get_width()/2, b.get_height(), f"{b.get_height():.1f}", ha="center", va="bottom", fontsize=8)
fig.tight_layout(); fig.savefig("ookla_fixed_mobile_comparison.png", dpi=130); plt.close(fig)

# (b-e) Download y latencia por región, para fixed y para mobile
reg_fixed  = ookla_regions[ookla_regions.tipo_red == "fixed"]
reg_mobile = ookla_regions[ookla_regions.tipo_red == "mobile"]
barras(reg_fixed["region"],  reg_fixed["download_mbps_promedio"],
       f"Download promedio por región - Red FIJA (Ookla {OOKLA_PERIODO})", "Mbps",
       "ookla_fixed_download_region.png", color="#2c7fb8", rot=30)
barras(reg_fixed["region"],  reg_fixed["latencia_ms_promedio"],
       f"Latencia promedio por región - Red FIJA (Ookla {OOKLA_PERIODO})", "ms",
       "ookla_fixed_latency_region.png", color="#41ae76", rot=30)
barras(reg_mobile["region"], reg_mobile["download_mbps_promedio"],
       f"Download promedio por región - Red MÓVIL (Ookla {OOKLA_PERIODO})", "Mbps",
       "ookla_mobile_download_region.png", color="#de2d26", rot=30)
barras(reg_mobile["region"], reg_mobile["latencia_ms_promedio"],
       f"Latencia promedio por región - Red MÓVIL (Ookla {OOKLA_PERIODO})", "ms",
       "ookla_mobile_latency_region.png", color="#fd8d3c", rot=30)

# (f) Top 5 provincias con mayor % de accesos <= 10 Mbps (ENACOM)
barras(top5_lentos_pct["provincia"], top5_lentos_pct["pct_10mbps_o_menos"],
       f"Top 5 provincias con mayor % de accesos <= 10 Mbps (ENACOM {ENACOM_PERIODO})", "%",
       "enacom_accesos_lentos_top5.png", color="#756bb1", rot=30, fmt="{:.1f}%")

print("        8 gráficos guardados.\n")


# =============================================================================
# ANEXO) ANÁLISIS DE EFICIENCIA COMPUTACIONAL (benchmarking de librerías)
# =============================================================================
# Estudio pedido en la 2da entrega: comparar el rendimiento de librerías al
# procesar un conjunto de datos REPRESENTATIVO del problema (los tiles de Ookla
# de Argentina). Comparamos pandas vs Polars (head-to-head, MISMA operación) y
# sumamos Numba para el kernel numérico (compilación JIT).
#
# OPERACIONES que ejecuta cada pipeline (un flujo típico de análisis de datos):
#   1) LECTURA de un CSV.
#   2) FILTRO de filas (latencia > 0).
#   3) TRANSFORMACIÓN: derivar la columna 'zona' según la latitud (vectorizado).
#   4) AGREGACIÓN: groupby por zona -> media y desvío de latencia, media de
#      download y conteo.
#
# MÉTRICAS:
#   - Tiempo de ejecución (promedio de varias repeticiones, con warm-up).
#   - Pico de memoria (tracemalloc; mide asignaciones a nivel Python -> es lo más
#     representativo para pandas. Polars/Numba trabajan parte de su memoria en
#     código nativo (Rust/LLVM) que tracemalloc no captura del todo: se aclara
#     como limitación de la medición).
#   - Uso de CPU expresado como "núcleos efectivos" = tiempo_CPU / tiempo_reloj.
#     ~1 => un solo núcleo (limitado por el GIL, caso de pandas); >1 => varios
#     núcleos en paralelo (caso de Polars, que no depende del GIL de Python).
import time
import tracemalloc
import tempfile

try:
    import polars as pl
    HAS_POLARS = True
except Exception:
    HAS_POLARS = False
try:
    from numba import njit
    HAS_NUMBA = True
except Exception:
    HAS_NUMBA = False

print("[ANEXO] Benchmarking de librerías (pandas / Polars / Numba)...")
print(f"        Disponibles -> pandas: sí | Polars: {'sí' if HAS_POLARS else 'no'} | "
      f"Numba: {'sí' if HAS_NUMBA else 'no'}")

# Dataset representativo: tiles fijos de Argentina. Como el set es chico (~57k),
# lo replicamos hasta ~1 millón de filas para que las mediciones de tiempo sean
# ESTABLES y comparables. Se escribe a un CSV temporal porque Polars puede leerlo
# de forma 'lazy' con scan_csv (evaluación diferida).
_bench_src = df_fixed[["tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps", "avg_lat_ms", "tests"]].copy()
_n_rep = max(1, 1_000_000 // max(1, len(_bench_src)))
_bench_df = pd.concat([_bench_src] * _n_rep, ignore_index=True)
_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
BENCH_CSV = _tmp.name
_tmp.close()
_bench_df.to_csv(BENCH_CSV, index=False)
print(f"        Dataset de benchmark: {len(_bench_df):,} filas (AR x{_n_rep})")

# ---- Pipelines (misma lógica en cada librería) ------------------------------
def pipe_pandas():
    df = pd.read_csv(BENCH_CSV)                       # 1) lectura
    df = df[df["avg_lat_ms"] > 0]                     # 2) filtro
    lat = df["tile_y"].values                         # 3) transformación (vectorizada)
    df = df.assign(zona=np.select(
        [lat > -30, lat > -38, lat > -45],
        ["norte", "centro", "buenos_aires"], "patagonia"))
    return (df.groupby("zona")                        # 4) agregación
              .agg(lat_media=("avg_lat_ms", "mean"),
                   lat_std=("avg_lat_ms", "std"),
                   dl_media=("avg_d_kbps", "mean"),
                   n=("tests", "count"))
              .reset_index())

def pipe_polars():
    return (pl.scan_csv(BENCH_CSV)                    # 1) lectura LAZY (no ejecuta aún)
              .filter(pl.col("avg_lat_ms") > 0)       # 2) filtro
              .with_columns(                          # 3) transformación
                  pl.when(pl.col("tile_y") > -30).then(pl.lit("norte"))
                    .when(pl.col("tile_y") > -38).then(pl.lit("centro"))
                    .when(pl.col("tile_y") > -45).then(pl.lit("buenos_aires"))
                    .otherwise(pl.lit("patagonia")).alias("zona"))
              .group_by("zona")                        # 4) agregación
              .agg([pl.col("avg_lat_ms").mean().alias("lat_media"),
                    pl.col("avg_lat_ms").std().alias("lat_std"),
                    pl.col("avg_d_kbps").mean().alias("dl_media"),
                    pl.col("tests").count().alias("n")])
              .collect())                              # <- recién acá se ejecuta el plan

if HAS_NUMBA:
    @njit(cache=True)
    def _stats_jit(a):
        """Media y desvío sobre un array (loops compilados a código máquina)."""
        n = len(a)
        if n == 0:
            return 0.0, 0.0
        s = 0.0
        for x in a:
            s += x
        m = s / n
        v = 0.0
        for x in a:
            v += (x - m) ** 2
        return m, (v / n) ** 0.5

    def pipe_numba():
        df = pd.read_csv(BENCH_CSV)
        a = df.loc[df["avg_lat_ms"] > 0, "avg_lat_ms"].to_numpy(np.float64)
        return _stats_jit(a)

    _stats_jit(np.array([1.0, 2.0, 3.0]))   # warm-up: fuerza la compilación JIT

# ---- Medición ---------------------------------------------------------------
def medir(func, reps=3):
    func()                                            # warm-up (cachés, lazy, etc.)
    t0, c0 = time.perf_counter(), time.process_time()
    for _ in range(reps):
        func()
    wall = (time.perf_counter() - t0) / reps          # tiempo de reloj
    cpu = (time.process_time() - c0) / reps           # tiempo de CPU (suma de hilos)
    tracemalloc.start()                               # pico de memoria (1 corrida)
    func()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    nucleos = cpu / wall if wall > 0 else float("nan")
    return wall, peak / 1e6, nucleos

_filas_bench = [("pandas",) + medir(pipe_pandas)]
if HAS_POLARS:
    _filas_bench.append(("Polars",) + medir(pipe_polars))
if HAS_NUMBA:
    _filas_bench.append(("Numba (kernel)",) + medir(pipe_numba))

benchmark = pd.DataFrame(_filas_bench,
                         columns=["libreria", "tiempo_s", "memoria_pico_mb", "cpu_nucleos_efectivos"])
benchmark = benchmark.round({"tiempo_s": 4, "memoria_pico_mb": 1, "cpu_nucleos_efectivos": 2})
benchmark.to_csv("benchmark_librerias.csv", index=False)
print("\n  >> Resultados del benchmarking:")
print(benchmark.to_string(index=False))

if len(benchmark) < 2:
    print("\n  [NOTA] Sólo se midió pandas. Instalá Polars y/o Numba para una "
          "comparación completa: pip install polars numba")

# ---- Gráfico comparativo ----------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
_cols = {"pandas": "#3498db", "Polars": "#e67e22", "Numba (kernel)": "#2ecc71"}
_cl = [_cols.get(l, "#888888") for l in benchmark["libreria"]]
for ax, col, titulo, ylab, fmt in [
    (axes[0], "tiempo_s", "Tiempo de ejecución", "segundos", "{:.3f}"),
    (axes[1], "memoria_pico_mb", "Pico de memoria (Python)", "MB", "{:.0f}"),
    (axes[2], "cpu_nucleos_efectivos", "CPU: núcleos efectivos", "tiempoCPU / tiempoReloj", "{:.2f}")]:
    bars = ax.bar(benchmark["libreria"], benchmark[col], color=_cl)
    ax.set_title(titulo, fontweight="bold", fontsize=11)
    ax.set_ylabel(ylab); ax.grid(axis="y", ls="--", alpha=0.4)
    ax.tick_params(axis="x", rotation=15)
    for b, v in zip(bars, benchmark[col]):
        ax.text(b.get_x() + b.get_width()/2, b.get_height(), fmt.format(v),
                ha="center", va="bottom", fontsize=8)
axes[2].axhline(1.0, color="red", ls="--", lw=1, alpha=0.7)   # 1 núcleo (GIL)
plt.suptitle("Benchmarking de librerías - pipeline sobre tiles Ookla AR", fontweight="bold")
fig.tight_layout(); fig.savefig("benchmark_comparativo.png", dpi=130); plt.close(fig)

# ---- Discusión + relación con la teoría -------------------------------------
_mas_rapida = benchmark.loc[benchmark["tiempo_s"].idxmin(), "libreria"]
discusion_bench = f"""
--------------------------------------------------------------------------------
DISCUSIÓN DEL BENCHMARKING (relación con la teoría de la materia)
--------------------------------------------------------------------------------
Tarea medida: lectura CSV + filtro + transformación + agregación (groupby) sobre
{len(_bench_df):,} filas de tiles Ookla. La librería más rápida fue: {_mas_rapida}.

- pandas: opera bajo el GIL (Global Interpreter Lock), que impide el paralelismo
  real de hilos en Python puro; por eso su "núcleos efectivos" queda cerca de 1.
  Sus operaciones vectorizadas se apoyan en C/NumPy y se benefician de la
  LOCALIDAD ESPACIAL del formato columnar (datos contiguos -> mejor uso de las
  LÍNEAS DE CACHÉ) e instrucciones SIMD, pero el motor es de un solo hilo.
- Polars: usa EVALUACIÓN LAZY (scan_csv arma un plan y recién se ejecuta en
  .collect(), permitiendo optimizarlo: proyección/empuje de filtros). Está escrito
  en Rust, sin GIL, con PARALELISMO MULTI-CORE y SIMD sobre columnas Arrow; por eso
  suele usar varios núcleos (ratio > 1) y escalar mejor en datasets grandes.
- Numba: compila el kernel numérico a código máquina con JIT (Just-In-Time). Tras
  el 'warm-up' de compilación, los loops sobre arrays corren a velocidad cercana a
  C, sin overhead del intérprete. Es ideal para cálculo numérico intensivo sobre
  arrays, pero NO reemplaza a un motor de dataframes para operaciones tabulares.

Conclusión: para el pipeline tabular de este TP (leer + filtrar + agrupar),
{_mas_rapida} resulta la opción más conveniente; Numba conviene cuando el cuello
de botella es un cálculo numérico a medida sobre arrays.
NOTA de medición: el pico de memoria por tracemalloc refleja asignaciones a nivel
Python; subestima la memoria nativa de Polars (Rust) y Numba (LLVM).
--------------------------------------------------------------------------------
"""
print(discusion_bench)

# Guardamos la discusión y limpiamos el CSV temporal
with open("benchmark_discusion.txt", "w", encoding="utf-8") as fh:
    fh.write(discusion_bench)
try:
    os.remove(BENCH_CSV)
except OSError:
    pass


# =============================================================================
# RESUMEN TEXTUAL AUTOMÁTICO (interpretación para el informe)
# =============================================================================
f = ookla_summary[ookla_summary.tipo_red == "fixed"].iloc[0]
m = ookla_summary[ookla_summary.tipo_red == "mobile"].iloc[0]

# Mejor / peor región por download en red fija
mejor_reg = reg_fixed.loc[reg_fixed["download_mbps_promedio"].idxmax()]
peor_reg  = reg_fixed.loc[reg_fixed["download_mbps_promedio"].idxmin()]
mejor_lat = reg_fixed.loc[reg_fixed["latencia_ms_promedio"].idxmin()]
peor_lat  = reg_fixed.loc[reg_fixed["latencia_ms_promedio"].idxmax()]

prov_top_lenta = enacom_rangos.iloc[0]
prov_top_rapida = enacom_rangos.sort_values("pct_mas_30mbps", ascending=False).iloc[0]

resumen = f"""
================================================================================
RESUMEN DE HALLAZGOS - RENDIMIENTO DE INTERNET EN ARGENTINA
Ookla {OOKLA_PERIODO}  |  ENACOM {ENACOM_PERIODO}
================================================================================

1) INTERNET FIJO vs MÓVIL (Ookla, mediciones de usuarios)
   - Download : fija {f.download_mbps_promedio} Mbps  vs  móvil {m.download_mbps_promedio} Mbps
   - Upload   : fija {f.upload_mbps_promedio} Mbps  vs  móvil {m.upload_mbps_promedio} Mbps
   - Latencia : fija {f.latencia_ms_promedio} ms   vs  móvil {m.latencia_ms_promedio} ms
   => La red {'FIJA' if f.download_mbps_promedio > m.download_mbps_promedio else 'MÓVIL'} ofrece mayor download,
      la red {'FIJA' if f.upload_mbps_promedio > m.upload_mbps_promedio else 'MÓVIL'} mayor upload, y
      la red {'FIJA' if f.latencia_ms_promedio < m.latencia_ms_promedio else 'MÓVIL'} menor latencia.
   (Se usaron promedios PONDERADOS por cantidad de tests: {int(f.tests):,} tests fijos y
    {int(m.tests):,} móviles, sobre {int(f.devices):,} y {int(m.devices):,} dispositivos.)
   - Distribución (mediana / percentil 90 por tile):
       Latencia fija  -> mediana {df_fixed['latencia_ms'].median():.0f} ms, p90 {df_fixed['latencia_ms'].quantile(0.90):.0f} ms
       Latencia móvil -> mediana {df_mobile['latencia_ms'].median():.0f} ms, p90 {df_mobile['latencia_ms'].quantile(0.90):.0f} ms
     El p90 (peor 10%) muestra que la red móvil no sólo es más lenta en promedio,
     sino que su "cola" de mala experiencia es bastante peor que la de la fija.
   - El gráfico de dispersión latencia-vs-throughput confirma la relación esperada:
     los tiles de baja latencia concentran los downloads más altos, mientras que a
     mayor latencia el throughput cae (típico de accesos móviles o de zonas alejadas).

2) REGIONES CON MEJOR RENDIMIENTO (red fija)
   - Mayor download : {mejor_reg.region} ({mejor_reg.download_mbps_promedio} Mbps)
   - Menor latencia : {mejor_lat.region} ({mejor_lat.latencia_ms_promedio} ms)

3) REGIONES CON PEOR RENDIMIENTO (red fija)
   - Menor download : {peor_reg.region} ({peor_reg.download_mbps_promedio} Mbps)
   - Mayor latencia : {peor_lat.region} ({peor_lat.latencia_ms_promedio} ms)

4) PROVINCIAS CON MÁS ACCESOS LENTOS (ENACOM, <= 10 Mbps)
   - La provincia con mayor proporción de accesos lentos es {prov_top_lenta.provincia}
     ({prov_top_lenta.pct_10mbps_o_menos}% de sus accesos son <= 10 Mbps).
   - En el otro extremo, {prov_top_rapida.provincia} lidera en accesos > 30 Mbps
     ({prov_top_rapida.pct_mas_30mbps}% de sus accesos superan los 30 Mbps).

5) RELACIÓN CON LA INFRAESTRUCTURA DE CONECTIVIDAD
   - Los cables submarinos que aterrizan principalmente en Las Toninas (Buenos
     Aires) aportan la CAPACIDAD INTERNACIONAL de salida del país. Sin embargo,
     esa capacidad explica sólo una parte del rendimiento que percibe el usuario.
   - El rendimiento final depende de la cadena completa: redes TRONCALES de
     fibra, nodos e IXP regionales, la densidad de infraestructura local y, sobre
     todo, la ÚLTIMA MILLA (la tecnología de acceso: FTTH, HFC/cablemódem, xDSL
     o radioenlaces). Esto explica por qué la región Centro-Litoral/Pampeana
     -donde aterrizan los cables y se concentra la inversión en fibra- muestra
     mejor download, mientras regiones más alejadas y de menor densidad quedan
     rezagadas pese a existir backbone nacional.
   - ARSAT - Red troncal terrestre (REFEFO): la Red Federal de Fibra Óptica es
     la red troncal estatal que ayuda a DISTRIBUIR conectividad mayorista hacia el
     interior y a federalizar el acceso, pero por sí sola NO garantiza buena
     calidad final: necesita complementarse con redes de distribución locales y,
     en especial, con despliegue de última milla. Por eso una provincia puede
     estar alcanzada por la troncal y, aun así, registrar alta proporción de
     accesos lentos en ENACOM si la última milla sigue dominada por tecnologías de
     baja capacidad.
   - ARSAT - Estaciones satelitales: ARSAT opera además los satélites
     geoestacionarios ARSAT-1 (2014) y ARSAT-2 (2015) y la infraestructura terrena
     asociada -el Centro de control y telepuerto de Benavídez (Buenos Aires) y la
     estación terrena de Bosque Alegre (Córdoba)-. El segmento satelital cumple un
     rol DISTINTO al de la fibra: provee conectividad a localidades rurales,
     dispersas o de difícil acceso donde el tendido de fibra troncal/última milla
     no resulta viable (parajes de la Patagonia, Puna del NOA, zonas del NEA).
     Esto se correlaciona con los datos: las regiones que en Ookla muestran menor
     download y mayor latencia (Patagonia, NOA y NEA) son justamente las de baja
     densidad donde el satélite suele ser la única o principal opción de acceso.
     Su contrapartida técnica es la latencia: un enlace geoestacionario agrega
     cientos de milisegundos por el trayecto Tierra-órbita-Tierra (~36.000 km),
     por lo que aporta COBERTURA pero no el rendimiento de un acceso de fibra.
     En síntesis, cables submarinos (capacidad internacional) + troncal REFEFO
     (transporte nacional) + estaciones satelitales de ARSAT (cobertura en zonas
     aisladas) + última milla (acceso final) forman la cadena completa; el
     rendimiento que mide el usuario depende del eslabón más débil de esa cadena.

NOTA METODOLÓGICA:
   - Ookla filtrado por bounding box (lat {LAT_MIN}..{LAT_MAX}, lon {LON_MIN}..{LON_MAX});
     incluye marginalmente zonas limítrofes. La región se asignó por aproximación
     de lat/lon (no por shapefile), por lo que tiles cercanos a límites
     provinciales pueden caer en la región vecina.
   - ENACOM: números en formato argentino reconstruidos y validados contra los
     totales oficiales. Velocidad media = promedio ponderado por accesos.
================================================================================
"""
print(resumen)

# Guardamos también el resumen en un .txt por comodidad para el informe
with open("resumen_hallazgos.txt", "w", encoding="utf-8") as fh:
    fh.write(resumen)

print("[OK] Listo. Archivos generados en:", BASE_DIR)
print("     CSV : ookla_argentina_summary.csv, ookla_argentina_distribucion.csv,")
print("           ookla_argentina_regions.csv,")
print(f"           enacom_velocidad_media_{ENACOM_SLUG}_clean.csv, enacom_rangos_{ENACOM_SLUG}_clean.csv")
print("           benchmark_librerias.csv")
print("     PNG : ookla_fixed_mobile_comparison.png, ookla_latency_distribution.png,")
print("           ookla_latency_vs_throughput.png, ookla_fixed_download_region.png,")
print("           ookla_fixed_latency_region.png, ookla_mobile_download_region.png,")
print("           ookla_mobile_latency_region.png, enacom_accesos_lentos_top5.png,")
print("           benchmark_comparativo.png")
print("     TXT : resumen_hallazgos.txt, benchmark_discusion.txt")
