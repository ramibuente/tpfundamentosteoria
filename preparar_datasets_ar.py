# -*- coding: utf-8 -*-
"""
=============================================================================
PREPARAR SUBCONJUNTOS DE OOKLA PARA ARGENTINA  (se corre UNA sola vez)
=============================================================================
Por qué existe este script
---------------------------
Los parquet ORIGINALES de Ookla son GLOBALES y pesan mucho:
  - 2024-10-01_performance_fixed_tiles.parquet   ~359 MB
  - 2024-10-01_performance_mobile_tiles.parquet  ~195 MB
GitHub no admite archivos de más de 100 MB, así que esos crudos NO se pueden
subir a un repo. Pero el análisis sólo usa los tiles de Argentina (~1% del
total). Este script filtra Argentina UNA vez y guarda dos archivos chiquitos:
  - ookla_ar_fixed_<periodo>.parquet   (~1 MB)
  - ookla_ar_mobile_<periodo>.parquet  (~0,3 MB)
Esos dos, junto con los 2 Excel de ENACOM (chicos), SÍ entran en GitHub y
permiten que el notebook corra OFFLINE, sin descargar nada en tiempo de
ejecución.

Cómo usarlo
-----------
1. Poné este script en la misma carpeta que los 2 parquet grandes de Ookla.
2. Ejecutá:  python preparar_datasets_ar.py
3. Subí al repo: el notebook + ookla_ar_*_<periodo>.parquet + los 2 .xlsx de ENACOM.
   (Los parquet grandes NO se suben.)
=============================================================================
"""
import os
import re
import glob
import numpy as np
import pyarrow.dataset as ds
import pyarrow.compute as pc
from matplotlib.path import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
os.chdir(BASE_DIR)

# Mismo bounding box y polígono de Argentina que usa el notebook principal -----
LAT_MIN, LAT_MAX = -56, -21
LON_MIN, LON_MAX = -74, -53
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
POLY_TDF = [(-68.7, -52.5), (-65.0, -52.5), (-65.0, -55.2), (-68.7, -55.2)]
_PATH_AR, _PATH_TDF = Path(POLY_ARGENTINA), Path(POLY_TDF)

COLS = ["quadkey", "tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps",
        "avg_lat_ms", "tests", "devices"]

def periodo_slug(nombre):
    """Deriva 'YYYYqN' a partir de la fecha del nombre del parquet (o '' si no hay)."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(nombre))
    if not m:
        return ""
    anio, mes = int(m.group(1)), int(m.group(2))
    return f"{anio}q{(mes - 1)//3 + 1}"

def procesar(patrones, tipo):
    # Encuentra el parquet global grande
    fuente = None
    for patron in patrones:
        hits = sorted(glob.glob(patron))
        # Evitamos tomar un subset ya generado (ookla_ar_...)
        hits = [h for h in hits if not os.path.basename(h).startswith("ookla_ar_")]
        if hits:
            fuente = hits[0]
            break
    if not fuente:
        print(f"[ERROR] No se encontró el parquet global de Ookla {tipo}. "
              f"Patrones probados: {patrones}")
        return
    print(f"[{tipo}] Fuente: {os.path.basename(fuente)} "
          f"({os.path.getsize(fuente)/1e6:.0f} MB)")

    d = ds.dataset(fuente)
    filt = ((pc.field("tile_x") >= LON_MIN) & (pc.field("tile_x") <= LON_MAX) &
            (pc.field("tile_y") >= LAT_MIN) & (pc.field("tile_y") <= LAT_MAX))
    df = d.to_table(columns=COLS, filter=filt).to_pandas()
    pts = np.column_stack([df["tile_x"].values, df["tile_y"].values])
    df = df[_PATH_AR.contains_points(pts) | _PATH_TDF.contains_points(pts)].copy()

    slug = periodo_slug(fuente)
    salida = f"ookla_ar_{tipo}{('_' + slug) if slug else ''}.parquet"
    df.to_parquet(salida, index=False, compression="zstd")
    print(f"[{tipo}] Guardado {salida}: {len(df):,} tiles, "
          f"{os.path.getsize(salida)/1e6:.2f} MB\n")

if __name__ == "__main__":
    print("Generando subconjuntos de Argentina (esto se hace una sola vez)...\n")
    procesar(["*performance_fixed_tiles.parquet", "*fixed*tiles*.parquet"],  "fixed")
    procesar(["*performance_mobile_tiles.parquet", "*mobile*tiles*.parquet"], "mobile")
    print("Listo. Subí al repo los archivos 'ookla_ar_*.parquet' (NO los parquet grandes).")
