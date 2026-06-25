# Análisis de rendimiento de Internet en Argentina — TP Fundamentos (Parte 2)

Compara dos datasets reales de mediciones de usuarios (Ookla Open Data: red **fija** vs **móvil**, Q4 2024), los contrasta con datos oficiales de **ENACOM** (velocidad media y rangos por provincia) y correlaciona los resultados con la infraestructura de conectividad del país: cables submarinos y puntos de aterrizaje (Las Toninas), red troncal **REFEFO** y **estaciones satelitales de ARSAT**, y última milla.

## Cómo correrlo (offline, sin descargar nada en ejecución)

1. Cloná o descargá este repositorio.
2. Abrí `analisis_internet_argentina.ipynb` (Jupyter o Google Colab) y ejecutá todas las celdas, **o** corré el script:
   ```
   pip install pandas matplotlib pyarrow openpyxl polars numba
   python analisis_internet_argentina.py
   ```
3. Los resultados (CSV, PNG y `resumen_hallazgos.txt`) se generan en la misma carpeta.

El notebook **autodetecta** los datos y corre **sin conexión**: lee los archivos que ya están en el repo. No descarga nada en tiempo de ejecución.

## Datos incluidos en el repo (livianos, ~2 MB en total)

| Archivo | Qué es | Peso aprox. |
|---|---|---|
| `ookla_ar_fixed_2024q4.parquet` | Tiles Ookla **red fija**, ya filtrados a Argentina | ~1 MB |
| `ookla_ar_mobile_2024q4.parquet` | Tiles Ookla **red móvil**, ya filtrados a Argentina | ~0,3 MB |
| `Internet Accesos Velocidad Provincias.xlsx` | ENACOM, histograma de velocidad por provincia | ~0,6 MB |
| `Internet Accesos Velocidad Rango Provincias.xlsx` | ENACOM, rangos de velocidad por provincia | ~0,1 MB |

> **Por qué un subconjunto de Ookla:** los parquet originales de Ookla son globales y pesan ~359 MB (fija) y ~195 MB (móvil), por encima del límite de 100 MB/archivo de GitHub. Como el análisis usa solo los tiles de Argentina (~1 % del total), se incluye únicamente ese recorte. El resultado es idéntico al de procesar el archivo completo.

## Regenerar el subconjunto desde los datos originales (opcional)

Si querés rehacer los recortes desde los parquet globales (otro trimestre, etc.):

1. Descargá los parquet de [Ookla Open Data](https://github.com/teamookla/ookla-open-data) (S3 público) y ponelos en esta carpeta.
2. Ejecutá:
   ```
   python preparar_datasets_ar.py
   ```
   Genera `ookla_ar_fixed_<periodo>.parquet` y `ookla_ar_mobile_<periodo>.parquet`. Subí esos al repo (los parquet grandes **no** se suben).

## Salidas que produce

- **CSV:** `ookla_argentina_summary.csv`, `ookla_argentina_distribucion.csv`, `ookla_argentina_regions.csv`, `enacom_velocidad_media_2024q4_clean.csv`, `enacom_rangos_2024q4_clean.csv`, `benchmark_librerias.csv`
- **PNG:** comparación fija/móvil, distribución de latencia, latencia vs throughput, download y latencia por región (fija y móvil), top ENACOM de accesos lentos y `benchmark_comparativo.png`.
- **TXT:** `resumen_hallazgos.txt` y `benchmark_discusion.txt`.

## Anexo: análisis de eficiencia computacional

El notebook incluye un *benchmarking* (pandas vs Polars vs Numba) sobre un pipeline representativo (lectura + filtro + transformación + agregación) midiendo tiempo, pico de memoria y uso de CPU (núcleos efectivos), con la discusión atada a los conceptos teóricos (GIL, multi-core, evaluación lazy, JIT, localidad de caché, SIMD). Requiere `polars` y `numba`; si no están instalados, el resto del análisis corre igual.

## `.gitignore` sugerido

Para no subir por accidente los parquet pesados:

```
*performance_fixed_tiles.parquet
*performance_mobile_tiles.parquet
```
