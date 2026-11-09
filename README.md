# DiskAnalyzer

Analizador de espacio en disco para Windows, escrito en Python puro (sin dependencias externas). Escanea una o varias unidades/rutas y genera un **informe HTML interactivo** con árbol de directorios (treemap), top de archivos más grandes, detección de duplicados por hash y gráficos visuales.

## Características

- 📊 **Treemap navegable** de la estructura de directorios por tamaño.
- 📁 **Top N archivos más grandes** (configurable).
- 🔁 **Detección de duplicados** por tamaño + hash de contenido.
- 📈 **Gráficos** (barras, doughnut por extensión) con Chart.js.
- 🖥️ Barra de progreso en terminal (spinner / barra determinada) durante el escaneo.
- 🧭 Autodetección de unidades en Windows si no se especifica ninguna ruta.
- 📦 Sin dependencias externas: solo librería estándar de Python.

## Requisitos

- Python 3.8+
- Windows (usa `string`/detección de unidades de Windows; el escaneo de rutas en sí es portable)

## Uso

```bash
# Escanea todos los drives detectados automáticamente
python disk_analyzer.py

# Escanea unidades específicas
python disk_analyzer.py C:\ D:\

# Top 100 archivos, ruta personalizada
python disk_analyzer.py C:\Users --top 100

# Nombre de salida personalizado
python disk_analyzer.py --output informe.html

# Omitir detección de duplicados (más rápido)
python disk_analyzer.py --no-duplicates

# Tamaño mínimo (bytes) para considerar un archivo en la búsqueda de duplicados
python disk_analyzer.py --min-dup-size 8192
```

### Opciones

| Opción | Descripción | Default |
|---|---|---|
| `paths` | Rutas o drives a escanear (ej: `C:\ D:\`) | Autodetección de drives |
| `--output`, `-o` | Nombre del archivo HTML de salida | `disk_report.html` |
| `--top`, `-t` | Número de archivos más grandes a incluir | `50` |
| `--no-duplicates` | Omite la detección de duplicados | `False` |
| `--min-dup-size` | Tamaño mínimo en bytes para considerar duplicados | `4096` |

## Salida

El script genera un único archivo HTML autocontenido (solo depende de Chart.js vía CDN) con cuatro secciones navegables: resumen, árbol/treemap, top de archivos y duplicados. El informe generado **no se incluye en el repositorio** porque contiene rutas y datos reales del disco escaneado (ver `.gitignore`).

## Licencia

[MIT](LICENSE)
