#!/usr/bin/env python3
"""
DiskAnalyzer — Analizador de espacio en disco para Windows
Genera un informe HTML interactivo con árbol de directorios,
top archivos más grandes, duplicados y gráficos visuales.

Uso:
  python disk_analyzer.py                        # Escanea todos los drives detectados
  python disk_analyzer.py C:\\ D:\\              # Escanea drives específicos
  python disk_analyzer.py C:\\Users --top 100    # Top 100 archivos, ruta personalizada
  python disk_analyzer.py --output informe.html  # Nombre de salida personalizado
"""

import os
import sys
import json
import hashlib
import argparse
import string
import time
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict


# ─────────────────────────────────────────────
# BARRA DE PROGRESO
# ─────────────────────────────────────────────

class ProgressBar:
    """
    Barra de progreso para terminal. Dos modos:
      - Indeterminado (spinner): para escaneo de archivos sin total conocido
      - Determinado   (barra):  para verificación de duplicados con total conocido
    """

    SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    BAR_FILL = '█'
    BAR_EMPTY = '░'

    # Colores ANSI
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    GREY = '\033[90m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

    def __init__(self, label: str, total: int = 0, unit: str = 'archivos',
                 bar_width: int = 30, refresh_interval: float = 0.08):
        self.label = label
        self.total = total  # 0 = indeterminado
        self.unit = unit
        self.bar_width = bar_width
        self.refresh = refresh_interval
        self.count = 0
        self.start_t = time.time()
        self.last_t = self.start_t
        self.last_count = 0
        self._spin_i = 0
        self._last_render = 0.0
        self._finished = False
        self._detail = ''
        self._supports_color = sys.stdout.isatty()
        self._term_width = shutil.get_terminal_size((80, 20)).columns

    # ── Actualización ──────────────────────────

    def update(self, n: int = 1, detail: str = ''):
        """Avanza el contador n pasos y opcionalmente actualiza el texto de detalle."""
        self.count += n
        if detail:
            self._detail = detail
        now = time.time()
        if now - self._last_render >= self.refresh:
            self._render()
            self._last_render = now

    def set_detail(self, detail: str):
        self._detail = detail

    def finish(self, message: str = ''):
        """Marca como completado y muestra el resumen final."""
        if self._finished:
            return
        self._finished = True
        elapsed = time.time() - self.start_t
        speed = self.count / elapsed if elapsed > 0 else 0

        # Limpiar línea actual
        sys.stdout.write('\r' + ' ' * self._term_width + '\r')

        c = self.CYAN if self._supports_color else ''
        g = self.GREEN if self._supports_color else ''
        y = self.YELLOW if self._supports_color else ''
        gr = self.GREY if self._supports_color else ''
        b = self.BOLD if self._supports_color else ''
        r = self.RESET if self._supports_color else ''

        summary = (
            f"  {g}✓{r} {b}{self.label}{r}  "
            f"{c}{self.count:,} {self.unit}{r}  "
            f"{gr}en {self._fmt_time(elapsed)} "
            f"({speed:,.0f} {self.unit}/s){r}"
        )
        if message:
            summary += f"  {y}→ {message}{r}"

        print(summary)
        sys.stdout.flush()

    # ── Renderizado ────────────────────────────

    def _render(self):
        elapsed = time.time() - self.start_t
        now = time.time()
        dt = now - self.last_t
        dn = self.count - self.last_count
        speed = dn / dt if dt > 0 else 0
        self.last_t = now
        self.last_count = self.count

        self._spin_i = (self._spin_i + 1) % len(self.SPINNER)

        c = self.CYAN if self._supports_color else ''
        g = self.GREEN if self._supports_color else ''
        y = self.YELLOW if self._supports_color else ''
        gr = self.GREY if self._supports_color else ''
        b = self.BOLD if self._supports_color else ''
        r = self.RESET if self._supports_color else ''

        if self.total > 0:
            # ── Modo determinado ──────────────
            pct = min(self.count / self.total, 1.0)
            filled = int(self.bar_width * pct)
            bar_str = self.BAR_FILL * filled + self.BAR_EMPTY * (self.bar_width - filled)
            eta = (self.total - self.count) / speed if speed > 0 else 0

            line = (
                f"\r  {c}{self.SPINNER[self._spin_i]}{r} "
                f"{b}{self.label}{r}  "
                f"{g}[{bar_str}]{r} "
                f"{y}{pct * 100:5.1f}%{r}  "
                f"{c}{self.count:,}/{self.total:,}{r} {self.unit}  "
                f"{gr}{speed:,.0f}/s  ETA {self._fmt_time(eta)}{r}"
            )
        else:
            # ── Modo indeterminado ────────────
            # Barra con bloque deslizante
            pos = int(self._spin_i / len(self.SPINNER) * self.bar_width) % self.bar_width
            bar_chars = list(self.BAR_EMPTY * self.bar_width)
            for k in range(4):
                bar_chars[(pos + k) % self.bar_width] = self.BAR_FILL
            bar_str = ''.join(bar_chars)

            line = (
                f"\r  {c}{self.SPINNER[self._spin_i]}{r} "
                f"{b}{self.label}{r}  "
                f"{gr}[{bar_str}]{r}  "
                f"{c}{self.count:,}{r} {self.unit}  "
                f"{gr}{speed:,.0f}/s  {self._fmt_time(elapsed)}{r}"
            )

        # Detalle de ruta/archivo truncado
        if self._detail:
            avail = max(0, self._term_width - len(self._strip_ansi(line)) - 4)
            detail = self._detail[-avail:] if avail < len(self._detail) else self._detail
            line += f"  {gr}{detail}{r}"

        # Truncar a ancho de terminal
        visible_len = len(self._strip_ansi(line))
        if visible_len > self._term_width:
            line = line[:self._term_width + (len(line) - visible_len)]

        sys.stdout.write(line + ' ' * max(0, self._term_width - visible_len))
        sys.stdout.flush()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s" if m < 60 else f"{m // 60}h{m % 60:02d}m"

    @staticmethod
    def _strip_ansi(s: str) -> str:
        import re
        return re.sub(r'\033\[[0-9;]*m', '', s)

    # ── Context manager ────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self._finished:
            self.finish()


# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    """Convierte bytes a formato legible (KB, MB, GB...)."""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_windows_drives() -> list[str]:
    """Detecta todas las unidades disponibles en Windows."""
    if sys.platform != 'win32':
        print("[!] No estás en Windows. Usando el directorio actual como ejemplo.")
        return [str(Path.home())]

    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)

    if not drives:
        drives = [str(Path.home())]

    return drives


def hash_file(path: str, block_size: int = 65536) -> str | None:
    """Calcula MD5 de un archivo de forma eficiente."""
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while chunk := f.read(block_size):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError, FileNotFoundError):
        return None


# ─────────────────────────────────────────────
# ESCANEO
# ─────────────────────────────────────────────

# Directorios del sistema a ignorar
SKIP_DIRS = {
    'System Volume Information', 'Recovery', '$Recycle.Bin',
    '$RECYCLE.BIN', 'Windows', 'SysWOW64', 'System32',
    'WinSxS', 'Prefetch', '.git'
}


def count_files_quick(root_path: str) -> int:
    """Pre-conteo rápido de archivos sin stat (solo listado de directorio)."""
    total = 0
    skip = SKIP_DIRS
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('$')]
        total += len(filenames)
    return total


def scan_path(root_path: str, verbose: bool = True) -> dict:
    """
    Escanea recursivamente un directorio y recopila:
    - Lista de archivos con tamaño
    - Tamaño acumulado por directorio
    - Grupos de archivos por tamaño (para detectar duplicados)
    """
    root = Path(root_path)
    files = []
    dir_sizes = defaultdict(int)
    size_groups = defaultdict(list)
    errors = 0
    scanned = 0

    if verbose:
        print(f"\n  📂  {root_path}")
        pb_count = ProgressBar('Contando archivos', unit='archivos')
        # Pre-conteo: recorre el árbol solo listando (sin stat), muy rápido
        total_files = 0
        for dirpath, dirnames, filenames in os.walk(str(root), topdown=True):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('$')]
            total_files += len(filenames)
            pb_count.update(len(filenames))
        pb_count.finish(f"{total_files:,} archivos encontrados")
    else:
        total_files = 0

    pb = ProgressBar('Escaneando', total=total_files, unit='archivos') if verbose else None

    for dirpath_str, dirnames, filenames in os.walk(str(root), topdown=True, onerror=None):
        # Filtrar directorios del sistema
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith('$')
        ]

        if pb:
            pb.set_detail(dirpath_str)

        for filename in filenames:
            filepath = Path(dirpath_str) / filename
            try:
                stat = filepath.stat()
                size = stat.st_size
                mtime = stat.st_mtime

                files.append({
                    'path': str(filepath),
                    'name': filename,
                    'size': size,
                    'size_str': format_size(size),
                    'dir': dirpath_str,
                    'mtime': mtime,
                    'ext': filepath.suffix.lower() or '(sin extensión)',
                })

                # Acumular tamaño en todos los directorios padres
                p = Path(dirpath_str)
                while True:
                    dir_sizes[str(p)] += size
                    if p == root or p.parent == p:
                        break
                    p = p.parent

                # Agrupar por tamaño para búsqueda de duplicados
                if size > 0:
                    size_groups[size].append(str(filepath))

                scanned += 1
                if pb:
                    pb.update(1)
            except (PermissionError, OSError, FileNotFoundError):
                errors += 1

    if pb:
        suffix = f'{errors} sin acceso' if errors else ''
        pb.finish(suffix)

    return {
        'root': str(root),
        'files': files,
        'dir_sizes': dict(dir_sizes),
        'size_groups': dict(size_groups),
        'total_size': dir_sizes.get(str(root), 0),
        'file_count': scanned,
        'error_count': errors,
    }


# ─────────────────────────────────────────────
# DUPLICADOS
# ─────────────────────────────────────────────

def find_duplicates(size_groups: dict, min_size: int = 4096, verbose: bool = True) -> list:
    """
    Encuentra archivos duplicados:
    1. Agrupa por tamaño (filtro rápido)
    2. Para grupos con ≥2 archivos, calcula MD5
    3. Retorna grupos con hash idéntico
    """
    candidates = {
        size: paths for size, paths in size_groups.items()
        if len(paths) > 1 and size >= min_size
    }

    # Total de archivos a hashear para la barra determinada
    total_to_check = sum(len(p) for p in candidates.values())

    if verbose:
        print(f"\n  🔍  {len(candidates)} grupos candidatos · {total_to_check:,} archivos a verificar")

    pb = ProgressBar('Verificando', total=total_to_check, unit='archivos') if verbose else None

    hash_groups = defaultdict(list)

    for size, paths in sorted(candidates.items(), key=lambda x: x[0], reverse=True):
        for path in paths:
            h = hash_file(path)
            if h:
                hash_groups[h].append({'path': path, 'size': size})
            if pb:
                pb.update(1, detail=path)

    duplicates = []
    for h, group in hash_groups.items():
        if len(group) > 1:
            wasted = group[0]['size'] * (len(group) - 1)
            duplicates.append({
                'hash': h,
                'size': group[0]['size'],
                'size_str': format_size(group[0]['size']),
                'count': len(group),
                'files': [g['path'] for g in group],
                'wasted': wasted,
                'wasted_str': format_size(wasted),
            })

    duplicates.sort(key=lambda x: x['wasted'], reverse=True)

    if pb:
        total_wasted = sum(d['wasted'] for d in duplicates)
        pb.finish(f"{len(duplicates)} grupos · {format_size(total_wasted)} recuperables")

    return duplicates


# ─────────────────────────────────────────────
# ÁRBOL DE DIRECTORIOS
# ─────────────────────────────────────────────

def build_tree_data(dir_sizes: dict, root: str, max_depth: int = 4, max_children: int = 8) -> dict:
    """Construye estructura de árbol para la visualización treemap."""

    def get_top_children(path_str: str):
        path = Path(path_str)
        children = []
        try:
            for child in path.iterdir():
                child_str = str(child)
                if child.is_dir() and child_str in dir_sizes and child.name not in SKIP_DIRS:
                    children.append({
                        'name': child.name,
                        'path': child_str,
                        'size': dir_sizes[child_str],
                    })
        except (PermissionError, OSError):
            pass
        children.sort(key=lambda x: x['size'], reverse=True)
        return children[:max_children]

    def build_node(path_str: str, depth: int = 0) -> dict | None:
        if depth > max_depth:
            return None
        node = {
            'name': Path(path_str).name or path_str,
            'path': path_str,
            'size': dir_sizes.get(path_str, 0),
            'size_str': format_size(dir_sizes.get(path_str, 0)),
            'children': [],
        }
        for child in get_top_children(path_str):
            child_node = build_node(child['path'], depth + 1)
            if child_node:
                node['children'].append(child_node)
        return node

    return build_node(root) or {'name': root, 'size': 0, 'children': []}


# ─────────────────────────────────────────────
# GENERACIÓN DEL INFORME HTML
# ─────────────────────────────────────────────

def generate_report(scan_results: list[dict], output_path: str, top_n: int = 50):
    """Genera el informe HTML completo con todos los datos."""

    # Combinar archivos de todos los drives para estadísticas globales
    all_files = []
    all_duplicates = []

    for result in scan_results:
        all_files.extend(result['files'])
        all_duplicates.extend(result.get('duplicates', []))

    # Top N archivos más grandes
    top_files = sorted(all_files, key=lambda x: x['size'], reverse=True)[:top_n]

    # Top directorios por drive
    trees = []
    for result in scan_results:
        tree = build_tree_data(result['dir_sizes'], result['root'])
        trees.append({'root': result['root'], 'tree': tree, 'total': result['total_size']})

    # Estadísticas por extensión
    ext_sizes = defaultdict(int)
    ext_counts = defaultdict(int)
    for f in all_files:
        ext_sizes[f['ext']] += f['size']
        ext_counts[f['ext']] += 1

    top_exts = sorted(ext_sizes.items(), key=lambda x: x[1], reverse=True)[:15]

    # Preparar datos para charts
    top_files_chart = [
        {'name': Path(f['path']).name[:40], 'size': f['size'], 'size_str': f['size_str']}
        for f in top_files[:20]
    ]

    total_wasted = sum(d['wasted'] for d in all_duplicates)
    total_size_all = sum(r['total_size'] for r in scan_results)
    total_files_all = sum(r['file_count'] for r in scan_results)

    data = {
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'drives': [
            {
                'root': r['root'],
                'total_size': r['total_size'],
                'total_size_str': format_size(r['total_size']),
                'file_count': r['file_count'],
                'error_count': r['error_count'],
            }
            for r in scan_results
        ],
        'top_files': [
            {**f, 'path_short': f['path'][:80] + '...' if len(f['path']) > 80 else f['path']}
            for f in top_files
        ],
        'top_files_chart': top_files_chart,
        'top_exts': [{'ext': e[0], 'size': e[1], 'size_str': format_size(e[1]),
                      'count': ext_counts[e[0]]} for e in top_exts],
        'duplicates': all_duplicates[:200],
        'trees': trees,
        'summary': {
            'total_size': total_size_all,
            'total_size_str': format_size(total_size_all),
            'total_files': total_files_all,
            'total_duplicates': len(all_duplicates),
            'wasted_space': total_wasted,
            'wasted_str': format_size(total_wasted),
        }
    }

    html = generate_html_template(data, top_n)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n✅ Informe generado: {output_path}")
    print(f"   Abre el archivo en tu navegador para verlo.")


def generate_html_template(data: dict, top_n: int) -> str:
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DiskAnalyzer — Informe {data['generated']}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0d0f14;
    --surface: #151820;
    --surface2: #1c2030;
    --border: #252a3a;
    --accent: #00d4aa;
    --accent2: #5b8af4;
    --accent3: #f4a25b;
    --danger: #f45b5b;
    --text: #e4e8f5;
    --muted: #6b738f;
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Space Grotesk', sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
  }}

  /* ── HEADER ── */
  .header {{
    background: linear-gradient(135deg, #0d0f14 0%, #1a1f2e 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(8px);
  }}

  .header-logo {{
    font-family: var(--mono);
    font-size: 18px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
  }}

  .header-logo span {{
    color: var(--muted);
    font-weight: 400;
  }}

  .header-meta {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
  }}

  /* ── NAV ── */
  .nav {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 32px;
    display: flex;
    gap: 0;
    overflow-x: auto;
  }}

  .nav-btn {{
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 500;
    padding: 12px 16px;
    transition: all 0.2s;
    white-space: nowrap;
  }}

  .nav-btn:hover {{ color: var(--text); }}
  .nav-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}

  /* ── LAYOUT ── */
  .container {{ max-width: 1400px; margin: 0 auto; padding: 32px; }}

  .section {{ display: none; }}
  .section.active {{ display: block; }}

  /* ── GRID CARDS ── */
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}

  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    position: relative;
    overflow: hidden;
  }}

  .card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: var(--accent);
  }}

  .card.danger::before {{ background: var(--danger); }}
  .card.warning::before {{ background: var(--accent3); }}
  .card.info::before {{ background: var(--accent2); }}

  .card-label {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }}

  .card-value {{
    font-family: var(--mono);
    font-size: 24px;
    font-weight: 700;
    color: var(--accent);
  }}

  .card.danger .card-value {{ color: var(--danger); }}
  .card.warning .card-value {{ color: var(--accent3); }}
  .card.info .card-value {{ color: var(--accent2); }}

  .card-sub {{
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
  }}

  /* ── DRIVE CARDS ── */
  .drives-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}

  .drive-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }}

  .drive-letter {{
    font-family: var(--mono);
    font-size: 32px;
    font-weight: 700;
    color: var(--accent2);
    line-height: 1;
    margin-bottom: 8px;
  }}

  .drive-path {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 12px;
    word-break: break-all;
  }}

  .drive-size {{
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }}

  .drive-files {{
    font-size: 12px;
    color: var(--muted);
  }}

  /* ── TABLAS ── */
  .table-wrapper {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 24px;
  }}

  .table-header {{
    background: var(--surface2);
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
  }}

  .table-title {{
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
  }}

  .table-count {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    background: var(--bg);
    padding: 2px 8px;
    border-radius: 4px;
  }}

  .search-box {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 6px 12px;
    width: 240px;
    outline: none;
    transition: border-color 0.2s;
  }}

  .search-box:focus {{ border-color: var(--accent); }}

  .data-table {{
    width: 100%;
    border-collapse: collapse;
  }}

  .data-table th {{
    background: var(--surface2);
    color: var(--muted);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.5px;
    padding: 10px 16px;
    text-align: left;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}

  .data-table th:hover {{ color: var(--text); }}

  .data-table td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 12px;
  }}

  .data-table tr:last-child td {{ border-bottom: none; }}
  .data-table tr:hover td {{ background: var(--surface2); }}

  .size-bar {{
    display: inline-block;
    height: 3px;
    background: var(--accent);
    border-radius: 2px;
    margin-top: 2px;
    vertical-align: bottom;
    opacity: 0.6;
  }}

  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    background: var(--accent2);
    color: var(--bg);
  }}

  .badge.danger {{ background: var(--danger); }}
  .badge.warn {{ background: var(--accent3); }}

  .path-cell {{
    max-width: 400px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font-size: 11px;
    display: block;
  }}

  /* ── CHARTS ── */
  .charts-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 24px;
  }}

  @media (max-width: 900px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}

  .chart-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }}

  .chart-card.wide {{ grid-column: 1 / -1; }}

  .chart-title {{
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 16px;
  }}

  canvas {{ max-height: 320px; }}

  /* ── TREEMAP ── */
  #treemap-container {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 24px;
  }}

  .treemap-nav {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}

  .treemap-nav-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 11px;
    padding: 4px 10px;
    transition: all 0.2s;
  }}

  .treemap-nav-btn:hover {{ color: var(--text); border-color: var(--accent); }}
  .treemap-nav-btn.root {{ color: var(--accent); }}

  #treemap {{
    width: 100%;
    height: 480px;
    position: relative;
  }}

  .tm-cell {{
    position: absolute;
    border: 1px solid var(--bg);
    border-radius: 3px;
    overflow: hidden;
    cursor: pointer;
    transition: filter 0.15s;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    padding: 4px 6px;
  }}

  .tm-cell:hover {{ filter: brightness(1.3); z-index: 10; }}

  .tm-label {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    color: rgba(255,255,255,0.9);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
  }}

  .tm-size {{
    font-family: var(--mono);
    font-size: 10px;
    color: rgba(255,255,255,0.65);
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
  }}

  /* ── DUPLICADOS ── */
  .dup-group {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 10px;
    overflow: hidden;
  }}

  .dup-header {{
    background: var(--surface2);
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
  }}

  .dup-header:hover {{ background: var(--border); }}

  .dup-wasted {{
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 700;
    color: var(--danger);
    min-width: 80px;
  }}

  .dup-info {{
    font-size: 12px;
    color: var(--muted);
    flex: 1;
  }}

  .dup-files {{
    display: none;
    padding: 10px 16px;
    border-top: 1px solid var(--border);
  }}

  .dup-files.open {{ display: block; }}

  .dup-file {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
    word-break: break-all;
  }}

  .dup-file:first-child {{ color: var(--text); }}
  .dup-file:last-child {{ border-bottom: none; }}

  /* ── DRIVE SELECTOR ── */
  .drive-selector {{
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}

  .drive-sel-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 12px;
    padding: 6px 14px;
    transition: all 0.2s;
  }}

  .drive-sel-btn.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: var(--bg);
    font-weight: 700;
  }}

  /* ── MISC ── */
  .section-title {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  .empty-state {{
    text-align: center;
    padding: 48px;
    color: var(--muted);
    font-size: 14px;
  }}

  .pagination {{
    display: flex;
    gap: 8px;
    justify-content: center;
    margin-top: 16px;
  }}

  .page-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 12px;
    padding: 6px 12px;
    transition: all 0.2s;
  }}

  .page-btn:hover, .page-btn.active {{
    background: var(--accent2);
    border-color: var(--accent2);
    color: var(--bg);
  }}

  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}
</style>
</head>
<body>

<div class="header">
  <div class="header-logo">disk<span>analyzer</span>.py</div>
  <div class="header-meta">Generado el {data['generated']}</div>
</div>

<nav class="nav">
  <button class="nav-btn active" onclick="showSection('overview')">📊 Resumen</button>
  <button class="nav-btn" onclick="showSection('topfiles')">📁 Top Archivos</button>
  <button class="nav-btn" onclick="showSection('treemap')">🗂️ Árbol</button>
  <button class="nav-btn" onclick="showSection('duplicates')">🔁 Duplicados</button>
  <button class="nav-btn" onclick="showSection('extensions')">📦 Extensiones</button>
</nav>

<div class="container">

  <!-- ═══ OVERVIEW ═══ -->
  <div id="section-overview" class="section active">
    <div class="section-title">Resumen General</div>

    <div class="cards">
      <div class="card">
        <div class="card-label">Espacio Analizado</div>
        <div class="card-value">{data['summary']['total_size_str']}</div>
        <div class="card-sub">{data['summary']['total_files']:,} archivos escaneados</div>
      </div>
      <div class="card info">
        <div class="card-label">Unidades / Rutas</div>
        <div class="card-value info">{len(data['drives'])}</div>
        <div class="card-sub">Analizadas en este informe</div>
      </div>
      <div class="card danger">
        <div class="card-label">Duplicados</div>
        <div class="card-value">{data['summary']['total_duplicates']}</div>
        <div class="card-sub">grupos — {data['summary']['wasted_str']} recuperables</div>
      </div>
      <div class="card warning">
        <div class="card-label">Top archivo</div>
        <div class="card-value" id="top-file-size">—</div>
        <div class="card-sub" id="top-file-name">—</div>
      </div>
    </div>

    <div class="section-title">Unidades / Rutas</div>
    <div class="drives-grid" id="drives-grid"></div>

    <div class="section-title">Gráficos</div>
    <div class="charts-grid">
      <div class="chart-card">
        <div class="chart-title">Top 20 archivos más grandes</div>
        <canvas id="chart-topfiles"></canvas>
      </div>
      <div class="chart-card">
        <div class="chart-title">Espacio por tipo de extensión</div>
        <canvas id="chart-exts"></canvas>
      </div>
    </div>
  </div>

  <!-- ═══ TOP FILES ═══ -->
  <div id="section-topfiles" class="section">
    <div class="section-title">Top {top_n} Archivos Más Grandes</div>
    <div class="table-wrapper">
      <div class="table-header">
        <span class="table-title">Archivos por tamaño</span>
        <input class="search-box" type="text" placeholder="Filtrar por nombre o ruta..." oninput="filterTable('topfiles-table', this.value)">
        <span class="table-count" id="topfiles-count"></span>
      </div>
      <div style="overflow-x:auto">
        <table class="data-table" id="topfiles-table">
          <thead>
            <tr>
              <th onclick="sortTable('topfiles-table',0)">#</th>
              <th onclick="sortTable('topfiles-table',1)">Archivo</th>
              <th onclick="sortTable('topfiles-table',2)">Tamaño ↓</th>
              <th onclick="sortTable('topfiles-table',3)">Extensión</th>
              <th onclick="sortTable('topfiles-table',4)">Ruta</th>
            </tr>
          </thead>
          <tbody id="topfiles-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ═══ TREEMAP ═══ -->
  <div id="section-treemap" class="section">
    <div class="section-title">Árbol de Directorios</div>
    <div id="treemap-container">
      <div class="treemap-nav" id="treemap-nav"></div>
      <div class="drive-selector" id="treemap-drive-sel"></div>
      <div id="treemap"></div>
    </div>
  </div>

  <!-- ═══ DUPLICADOS ═══ -->
  <div id="section-duplicates" class="section">
    <div class="section-title">Archivos Duplicados</div>
    <div class="cards" style="margin-bottom:24px">
      <div class="card danger">
        <div class="card-label">Espacio recuperable</div>
        <div class="card-value">{data['summary']['wasted_str']}</div>
        <div class="card-sub">{data['summary']['total_duplicates']} grupos de duplicados</div>
      </div>
    </div>
    <div id="duplicates-list"></div>
  </div>

  <!-- ═══ EXTENSIONS ═══ -->
  <div id="section-extensions" class="section">
    <div class="section-title">Espacio por Extensión</div>
    <div class="table-wrapper">
      <div class="table-header">
        <span class="table-title">Tipos de archivo</span>
        <span class="table-count">{len(data['top_exts'])} extensiones</span>
      </div>
      <div style="overflow-x:auto">
        <table class="data-table" id="ext-table">
          <thead>
            <tr>
              <th>Extensión</th>
              <th>Espacio Total ↓</th>
              <th>Archivos</th>
              <th>Barra</th>
            </tr>
          </thead>
          <tbody id="ext-body"></tbody>
        </table>
      </div>
    </div>
  </div>

</div>

<script>
const DATA = {data_json};

// ── NAVEGACIÓN ──
function showSection(name) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  event.target.classList.add('active');

  if (name === 'treemap' && !window._treemapInit) {{
    initTreemap();
    window._treemapInit = true;
  }}
}}

// ── COLORES ──
const PALETTE = [
  '#5b8af4','#00d4aa','#f4a25b','#a25bf4','#f45b8a',
  '#5bf4d4','#f4d45b','#8af45b','#f45b5b','#5b8af4',
  '#4fc3f7','#81c784','#ffb74d','#ba68c8','#ff8a65',
];

function colorFor(i) {{ return PALETTE[i % PALETTE.length]; }}
function sizeBar(pct, color) {{
  return `<span class="size-bar" style="width:${{Math.max(4, pct * 120)}}px;background:${{color}}"></span>`;
}}

// ── OVERVIEW ──
function initOverview() {{
  // Drives
  const grid = document.getElementById('drives-grid');
  DATA.drives.forEach((d, i) => {{
    const name = d.root.replace(/\\\\/g, '/');
    const letter = name.length <= 3 ? name[0] : '📁';
    grid.innerHTML += `
      <div class="drive-card">
        <div class="drive-letter" style="color:${{colorFor(i)}}">${{letter}}</div>
        <div class="drive-path">${{d.root}}</div>
        <div class="drive-size">${{d.total_size_str}}</div>
        <div class="drive-files">${{d.file_count.toLocaleString()}} archivos · ${{d.error_count}} sin acceso</div>
      </div>`;
  }});

  // Top file card
  if (DATA.top_files.length > 0) {{
    const tf = DATA.top_files[0];
    document.getElementById('top-file-size').textContent = tf.size_str;
    document.getElementById('top-file-name').textContent = tf.name.substring(0, 30);
  }}

  // Chart: Top files
  const topCtx = document.getElementById('chart-topfiles').getContext('2d');
  new Chart(topCtx, {{
    type: 'bar',
    data: {{
      labels: DATA.top_files_chart.map(f => f.name),
      datasets: [{{
        data: DATA.top_files_chart.map(f => f.size),
        backgroundColor: DATA.top_files_chart.map((_, i) => colorFor(i) + 'cc'),
        borderColor: DATA.top_files_chart.map((_, i) => colorFor(i)),
        borderWidth: 1,
        borderRadius: 3,
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: ctx => ' ' + DATA.top_files_chart[ctx.dataIndex].size_str
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#6b738f', callback: v => formatSize(v) }},
          grid: {{ color: '#252a3a' }},
        }},
        y: {{
          ticks: {{ color: '#e4e8f5', font: {{ size: 11 }} }},
          grid: {{ display: false }},
        }}
      }}
    }}
  }});

  // Chart: Extensions
  const extCtx = document.getElementById('chart-exts').getContext('2d');
  new Chart(extCtx, {{
    type: 'doughnut',
    data: {{
      labels: DATA.top_exts.map(e => e.ext),
      datasets: [{{
        data: DATA.top_exts.map(e => e.size),
        backgroundColor: DATA.top_exts.map((_, i) => colorFor(i) + 'dd'),
        borderColor: '#0d0f14',
        borderWidth: 2,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ position: 'right', labels: {{ color: '#e4e8f5', font: {{ size: 11 }} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{DATA.top_exts[ctx.dataIndex].size_str}}` }} }}
      }}
    }}
  }});
}}

// ── TOP FILES TABLE ──
function initTopFiles() {{
  const tbody = document.getElementById('topfiles-body');
  const maxSize = DATA.top_files[0]?.size || 1;
  DATA.top_files.forEach((f, i) => {{
    const pct = f.size / maxSize;
    tbody.innerHTML += `<tr>
      <td style="color:var(--muted)">${{i+1}}</td>
      <td><strong>${{f.name}}</strong></td>
      <td>
        <span style="color:var(--accent);font-weight:700">${{f.size_str}}</span>
        ${{sizeBar(pct, colorFor(i))}}
      </td>
      <td><span class="badge">${{f.ext}}</span></td>
      <td><span class="path-cell" title="${{f.path}}">${{f.path_short}}</span></td>
    </tr>`;
  }});
  document.getElementById('topfiles-count').textContent = DATA.top_files.length + ' archivos';
}}

// ── TREEMAP ──
let treemapCurrentDrive = 0;
let treemapPath = [];

function initTreemap() {{
  const sel = document.getElementById('treemap-drive-sel');
  DATA.trees.forEach((t, i) => {{
    const btn = document.createElement('button');
    btn.className = 'drive-sel-btn' + (i === 0 ? ' active' : '');
    btn.textContent = t.root;
    btn.onclick = () => {{
      document.querySelectorAll('.drive-sel-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      treemapCurrentDrive = i;
      treemapPath = [];
      renderTreemap(DATA.trees[i].tree, DATA.trees[i].tree.name);
    }};
    sel.appendChild(btn);
  }});

  if (DATA.trees.length > 0) {{
    renderTreemap(DATA.trees[0].tree, DATA.trees[0].tree.name);
  }}
}}

function renderTreemap(node, rootName) {{
  const container = document.getElementById('treemap');
  container.innerHTML = '';

  const nav = document.getElementById('treemap-nav');
  nav.innerHTML = '';

  // Breadcrumb
  treemapPath.forEach((n, i) => {{
    const btn = document.createElement('button');
    btn.className = 'treemap-nav-btn' + (i === 0 ? ' root' : '');
    btn.textContent = n.name;
    btn.onclick = () => {{
      treemapPath = treemapPath.slice(0, i + 1);
      renderTreemap(n, n.name);
    }};
    nav.appendChild(btn);
    if (i < treemapPath.length - 1) {{
      const sep = document.createElement('span');
      sep.textContent = ' › ';
      sep.style.color = 'var(--muted)';
      nav.appendChild(sep);
    }}
  }});

  // Squarify treemap
  const items = node.children.length > 0 ? node.children : [node];
  const W = container.offsetWidth || 800;
  const H = container.offsetHeight || 480;
  const totalSize = items.reduce((s, c) => s + c.size, 0) || 1;

  squarify(items, 0, 0, W, H, totalSize, container);
}}

function squarify(items, x, y, w, h, total, container) {{
  if (!items.length) return;

  const sorted = [...items].sort((a, b) => b.size - a.size);
  const colors = ['#1a3f6f','#1e4d3f','#4d2b1e','#3f1a4d','#1e3d4d',
                  '#4d3f1a','#1a4d2b','#4d1a2b','#2b4d1a','#1a2b4d'];

  function layoutRow(row, x, y, w, h, isHoriz, colorOff) {{
    const rowTotal = row.reduce((s, n) => s + n.size, 0);
    let pos = isHoriz ? x : y;
    row.forEach((node, i) => {{
      const frac = rowTotal > 0 ? node.size / rowTotal : 0;
      const cw = isHoriz ? w * frac : w;
      const ch = isHoriz ? h : h * frac;
      const cx = isHoriz ? pos : x;
      const cy = isHoriz ? y : pos;

      const cell = document.createElement('div');
      cell.className = 'tm-cell';
      cell.style.cssText = `left:${{cx}}px;top:${{cy}}px;width:${{Math.max(0,cw-2)}}px;height:${{Math.max(0,ch-2)}}px;background:${{colors[(colorOff+i) % colors.length]}};`;
      cell.innerHTML = cw > 40 && ch > 30 ? `
        <div class="tm-label">${{node.name}}</div>
        <div class="tm-size">${{node.size_str}}</div>` : '';

      if (node.children && node.children.length > 0) {{
        cell.onclick = () => {{
          treemapPath.push(node);
          renderTreemap(node, node.name);
        }};
        cell.title = `${{node.name}} — ${{node.size_str}} (click para entrar)`;
      }} else {{
        cell.style.cursor = 'default';
        cell.title = `${{node.name}} — ${{node.size_str}}`;
      }}

      container.appendChild(cell);
      pos += isHoriz ? cw : ch;
    }});
  }}

  // Simple row-based layout
  let remaining = [...sorted];
  let rx = x, ry = y, rw = w, rh = h;
  let colorOffset = 0;

  while (remaining.length > 0) {{
    const isHoriz = rw >= rh;
    const rowTotal = remaining.reduce((s, n) => s + n.size, 0);
    const rowFrac = remaining.length > 3 ? 0.4 : 1;

    let row, rest;
    if (remaining.length <= 3) {{
      row = remaining; rest = [];
    }} else {{
      const rowCount = Math.max(1, Math.round(Math.sqrt(remaining.length) * 0.7));
      row = remaining.slice(0, rowCount);
      rest = remaining.slice(rowCount);
    }}

    const rowSize = row.reduce((s, n) => s + n.size, 0);
    const frac = rowTotal > 0 ? rowSize / rowTotal : 1;

    if (isHoriz) {{
      layoutRow(row, rx, ry, rw * frac, rh, false, colorOffset);
      rx += rw * frac;
      rw -= rw * frac;
    }} else {{
      layoutRow(row, rx, ry, rw, rh * frac, true, colorOffset);
      ry += rh * frac;
      rh -= rh * frac;
    }}

    colorOffset += row.length;
    remaining = rest;
    if (rw < 4 || rh < 4) break;
  }}
}}

// ── DUPLICADOS ──
function initDuplicates() {{
  const list = document.getElementById('duplicates-list');
  if (DATA.duplicates.length === 0) {{
    list.innerHTML = '<div class="empty-state">🎉 No se encontraron duplicados</div>';
    return;
  }}
  DATA.duplicates.forEach((d, i) => {{
    const div = document.createElement('div');
    div.className = 'dup-group';
    div.innerHTML = `
      <div class="dup-header" onclick="toggleDup(this)">
        <div class="dup-wasted">${{d.wasted_str}}</div>
        <div class="dup-info">
          ${{d.count}} copias · ${{d.size_str}} cada una · 
          <code style="font-size:10px;color:var(--muted)">${{d.hash.substring(0,8)}}…</code>
        </div>
        <span style="color:var(--muted);font-size:12px">▼</span>
      </div>
      <div class="dup-files">
        ${{d.files.map((f, fi) => 
          `<div class="dup-file">${{fi === 0 ? '✓ ' : '  '}}${{f}}</div>`
        ).join('')}}
      </div>`;
    list.appendChild(div);
  }});
}}

function toggleDup(header) {{
  const files = header.nextElementSibling;
  files.classList.toggle('open');
  header.querySelector('span').textContent = files.classList.contains('open') ? '▲' : '▼';
}}

// ── EXTENSIONES ──
function initExtensions() {{
  const tbody = document.getElementById('ext-body');
  const maxSize = DATA.top_exts[0]?.size || 1;
  DATA.top_exts.forEach((e, i) => {{
    const pct = e.size / maxSize;
    tbody.innerHTML += `<tr>
      <td><span class="badge" style="background:${{colorFor(i)}}">${{e.ext}}</span></td>
      <td style="color:var(--accent);font-weight:700">${{e.size_str}}</td>
      <td style="color:var(--muted)">${{e.count.toLocaleString()}}</td>
      <td>${{sizeBar(pct, colorFor(i))}}</td>
    </tr>`;
  }});
}}

// ── UTILIDADES DE TABLA ──
function filterTable(tableId, query) {{
  const table = document.getElementById(tableId);
  const q = query.toLowerCase();
  let count = 0;
  Array.from(table.tBodies[0].rows).forEach(row => {{
    const text = row.textContent.toLowerCase();
    const show = text.includes(q);
    row.style.display = show ? '' : 'none';
    if (show) count++;
  }});
  const countEl = document.getElementById(tableId.replace('-table', '-count'));
  if (countEl) countEl.textContent = count + ' archivos';
}}

let sortDir = {{}};
function sortTable(tableId, col) {{
  const table = document.getElementById(tableId);
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const key = tableId + col;
  sortDir[key] = !sortDir[key];

  rows.sort((a, b) => {{
    const aVal = a.cells[col].textContent.trim();
    const bVal = b.cells[col].textContent.trim();
    const aNum = parseFloat(aVal.replace(/[^0-9.]/g, ''));
    const bNum = parseFloat(bVal.replace(/[^0-9.]/g, ''));
    const cmp = isNaN(aNum) || isNaN(bNum)
      ? aVal.localeCompare(bVal)
      : aNum - bNum;
    return sortDir[key] ? cmp : -cmp;
  }});

  rows.forEach(r => tbody.appendChild(r));
}}

function formatSize(bytes) {{
  const units = ['B','KB','MB','GB','TB'];
  let u = 0;
  while (bytes >= 1024 && u < units.length - 1) {{ bytes /= 1024; u++; }}
  return bytes.toFixed(1) + ' ' + units[u];
}}

// ── INIT ──
initOverview();
initTopFiles();
initDuplicates();
initExtensions();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='DiskAnalyzer — Analizador de espacio en disco para Windows',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        'paths', nargs='*',
        help='Rutas o drives a escanear (ej: C:\\ D:\\). Si se omite, detecta automáticamente.'
    )
    parser.add_argument(
        '--output', '-o', default='disk_report.html',
        help='Nombre del archivo HTML de salida (default: disk_report.html)'
    )
    parser.add_argument(
        '--top', '-t', type=int, default=50,
        help='Número de archivos más grandes a incluir (default: 50)'
    )
    parser.add_argument(
        '--no-duplicates', action='store_true',
        help='Omitir la detección de duplicados (más rápido)'
    )
    parser.add_argument(
        '--min-dup-size', type=int, default=4096,
        help='Tamaño mínimo en bytes para considerar duplicados (default: 4096)'
    )

    args = parser.parse_args()

    # Determinar rutas a escanear
    paths = args.paths if args.paths else get_windows_drives()

    print(f"\n╔══════════════════════════════════════════════╗")
    print(f"║       DiskAnalyzer — Análisis de disco       ║")
    print(f"╚══════════════════════════════════════════════╝")
    print(f"\nRutas a escanear: {', '.join(paths)}")

    # Escanear cada ruta
    scan_results = []
    for path in paths:
        if not os.path.exists(path):
            print(f"[!] Ruta no encontrada: {path}")
            continue
        result = scan_path(path, verbose=True)

        # Detectar duplicados
        if not args.no_duplicates:
            result['duplicates'] = find_duplicates(
                result['size_groups'],
                min_size=args.min_dup_size,
                verbose=True
            )
        else:
            result['duplicates'] = []

        scan_results.append(result)

    if not scan_results:
        print("[!] No se pudo escanear ninguna ruta.")
        sys.exit(1)

    # Generar informe
    print(f"\n📝 Generando informe HTML...")
    generate_report(scan_results, args.output, top_n=args.top)


if __name__ == '__main__':
    main()