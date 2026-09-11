import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from openpyxl.utils import get_column_letter
from pathlib import Path

log = logging.getLogger("mcp_bd_readonly.excel")

MAX_FILE_MB = 25
MAX_TOTAL_CELLS = 250_000
MAX_SHEET_CELLS = 60_000
MAX_CELL_TEXT = 120


class ExcelSafetyError(Exception):
    pass


def _system() -> str:
    return platform.system()


def _get_libreoffice_cmd() -> list[str]:
    if _system() == "Windows":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    elif _system() == "Darwin":
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/opt/homebrew/bin/soffice",
            "/usr/local/bin/soffice",
        ]
    else:
        candidates = []
    for c in candidates:
        if Path(c).exists():
            return [c]
    return ["soffice"]


def _libreoffice_available() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            _get_libreoffice_cmd() + ["--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0:
            v = (r.stdout or r.stderr).strip().splitlines()
            return True, (v[0] if v else "unknown")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False, ""


def _formualizer_available() -> tuple[bool, str]:
    try:
        import formualizer
        return True, getattr(formualizer, "__version__", "unknown")
    except Exception:
        return False, ""


def check_excel_capabilities() -> dict:
    lo_ok, lo_v = _libreoffice_available()
    fm_ok, fm_v = _formualizer_available()
    if lo_ok:
        strategy = "libreoffice"
    elif fm_ok:
        strategy = "formualizer"
    else:
        strategy = "cached_only"
    return {
        "platform": _system(),
        "openpyxl": _version("openpyxl"),
        "libreoffice": {"available": lo_ok, "version": lo_v},
        "formualizer": {"available": fm_ok, "version": fm_v},
        "strategy": strategy,
        "note": strategy if strategy != "cached_only" else
            "Sin motor de recálculo: solo valores cached. Instala LibreOffice o formualizer.",
    }


def _version(pkg: str) -> str:
    try:
        mod = __import__(pkg)
        return getattr(mod, "__version__", "unknown")
    except Exception:
        return "no disponible"


def _safety_checks(path: Path) -> None:
    if not path.exists():
        raise ExcelSafetyError(f"Archivo no existe: {path}")
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ExcelSafetyError(f"Formato no soportado (solo .xlsx/.xlsm): {path.suffix}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise ExcelSafetyError(f"Archivo excede {MAX_FILE_MB}MB ({size_mb:.1f}MB)")
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            total = sum(i.file_size for i in z.infolist())
            if bad:
                raise ExcelSafetyError(f"XLSX corrupto (zip): {bad}")
            if total > 400 * 1024 * 1024:
                raise ExcelSafetyError(f"Descomprimir excede 400MB ({total/1e6:.0f}MB)")
    except zipfile.BadZipFile:
        raise ExcelSafetyError("No es un XLSX válido (no es ZIP)")


def _detect_formulas(path: Path) -> dict:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=False, read_only=True)
        out = {"has_formulas": False, "per_sheet": {}, "total": 0}
        for ws in wb.worksheets:
            n = 0
            for row in ws.iter_rows():
                for c in row:
                    if c.data_type == "f":
                        n += 1
                        out["has_formulas"] = True
                        if n >= 5000:
                            break
                if n >= 5000:
                    break
            out["per_sheet"][ws.title] = n
            out["total"] += n
        wb.close()
        return out
    except Exception as e:
        log.warning("detect_formulas: %s", e)
        return {"has_formulas": False, "per_sheet": {}, "total": 0, "error": str(e)}


def _recalc_with_libreoffice(path: Path, tmp_dir: Path) -> dict:
    out_file = tmp_dir / f"recalc_{path.stem}.xlsx"
    flags = ["--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(tmp_dir)]
    if _system() == "Darwin":
        flags = ["--headless", "--invisible", "--norestore", "--nologo", "--calc",
                 "--convert-to", "xlsx", "--outdir", str(tmp_dir)]
    elif _system() == "Windows":
        flags = ["--headless", "--nodefault", "--norestore", "--calc",
                 "--convert-to", "xlsx", "--outdir", str(tmp_dir)]
    import subprocess as sp
    cflags = sp.CREATE_NO_WINDOW if _system() == "Windows" else 0
    try:
        r = sp.run(_get_libreoffice_cmd() + flags + [str(path)],
                   capture_output=True, text=True, timeout=120, creationflags=cflags)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "LO returncode!=0")[:200]}
    except sp.TimeoutExpired:
        return {"ok": False, "error": "LibreOffice timeout 120s"}
    except Exception as e:
        return {"ok": False, "error": f"LibreOffice: {e}"}
    candidates = sorted(tmp_dir.glob(f"recalc_{path.stem}.xlsx")) + sorted(tmp_dir.glob("*.xlsx"))
    cand = next((c for c in candidates if c.exists() and c.stat().st_size > 0), None)
    if cand:
        return {"ok": True, "path": cand}
    return {"ok": False, "error": "LibreOffice no produjo archivo"}


def _recalc_with_formualizer(path: Path, tmp_dir: Path) -> dict:
    out_file = tmp_dir / f"recalc_{path.stem}.xlsx"
    try:
        import formualizer
        summary = formualizer.recalculate_file(str(path), output=str(out_file))
        if out_file.exists() and out_file.stat().st_size > 0:
            return {"ok": True, "path": out_file, "summary": summary}
        return {"ok": False, "error": "formualizer no produjo archivo"}
    except Exception as e:
        return {"ok": False, "error": f"formualizer: {e}"[:200]}


def _smart_recalc(path: Path, tmp_dir: Path) -> dict:
    lo_ok, _ = _libreoffice_available()
    if lo_ok:
        r = _recalc_with_libreoffice(path, tmp_dir)
        if r["ok"]:
            return {"recalculated": True, "engine": "libreoffice", "path": str(r["path"])}
        log.warning("LO recalc falló: %s", r.get("error"))
    fm_ok, _ = _formualizer_available()
    if fm_ok:
        r = _recalc_with_formualizer(path, tmp_dir)
        if r["ok"]:
            return {"recalculated": True, "engine": "formualizer", "path": str(r["path"]),
                    "warning": "formualizer: sin tablas dinámicas/LET/LAMBDA", "summary": r.get("summary")}
        log.warning("formualizer recalc falló: %s", r.get("error"))
    return {"recalculated": False, "engine": "cached_only",
            "warning": "Sin recálculo: valores cached."}


def _norm(v):
    """Aplana valores para JSON, acota strings largos."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(v, 6)
    s = str(v)
    return s if len(s) <= MAX_CELL_TEXT else s[:MAX_CELL_TEXT] + "…"


def _merged_ranges(path: Path, sheet_name: str) -> list[str]:
    """Merged ranges desde el XML de la hoja (read_only no los expone)."""
    try:
        with zipfile.ZipFile(path) as z:
            import xml.etree.ElementTree as ET
            for name in z.namelist():
                if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                    continue
                root = ET.fromstring(z.read(name))
                sh = root.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCells")
                if sh is None:
                    continue
                ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                ranges = [mc.attrib["ref"] for mc in sh.findall("m:mergeCell", ns)]
                if ranges:
                    return ranges
    except Exception:
        pass
    return []


def _sheet_to_json(ws, formulas: dict[str, str], max_cells: int, merged: list[str]) -> dict:
    cells = []
    for r_i, row in enumerate(ws.iter_rows(), start=1):
        for c_i, c in enumerate(row, start=1):
            if not hasattr(c, "value"):
                continue
            v = c.value
            coord = get_column_letter(c_i) + str(r_i)
            f = formulas.get(coord)
            if v is None and not f:
                continue
            cell = {"ref": coord}
            if f:
                cell["f"] = f[:200]
            if v is not None:
                cell["v"] = _norm(v)
            cells.append(cell)
            if len(cells) >= max_cells:
                return {
                    "name": ws.title,
                    "rows": ws.max_row, "cols": ws.max_column,
                    "cells": cells,
                    "merged_ranges": merged,
                    "truncated": True,
                }
    return {
        "name": ws.title,
        "rows": ws.max_row, "cols": ws.max_column,
        "cells": cells,
        "merged_ranges": merged,
        "truncated": False,
    }


def _formula_map(wb, sheet_name: str | None) -> dict[str, dict[str, str]]:
    from openpyxl import load_workbook
    out = {}
    wbf = load_workbook(wb, data_only=False, read_only=True)
    for ws in wbf.worksheets:
        if sheet_name and ws.title != sheet_name:
            continue
        m = {}
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f" and c.value and str(c.value).startswith("="):
                    m[c.coordinate] = str(c.value)
        out[ws.title] = m
        if sheet_name:
            break
    wbf.close()
    return out


def _resumen_sheet(ws, max_rows_preview: int, max_rows_scan: int) -> dict:
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return {"name": ws.title, "rows": 0, "cols": 0, "columnas": [], "preview": [],
                "agrupacion_sugerida": []}
    headers = [str(h) if h is not None else f"col_{i + 1}" for i, h in enumerate(header)]
    stats = [{"nulos": 0, "tipos": {}} for _ in headers]
    preview = []
    n_rows = 0
    for row in rows_iter:
        n_rows += 1
        if n_rows > max_rows_scan:
            break
        if len(preview) < max_rows_preview:
            preview.append([_norm(v) for v in row[:len(headers)]])
        for i, v in enumerate(row[:len(headers)]):
            if v is None:
                stats[i]["nulos"] += 1
            else:
                tname = type(v).__name__
                stats[i]["tipos"][tname] = stats[i]["tipos"].get(tname, 0) + 1

    columnas = []
    fechas, numericas = [], []
    for h, s in zip(headers, stats):
        tipo_dominante = max(s["tipos"], key=s["tipos"].get) if s["tipos"] else "vacio"
        columnas.append({"nombre": h, "nulos": s["nulos"], "tipos": s["tipos"],
                          "tipo_dominante": tipo_dominante})
        hl = h.lower()
        if "fecha" in hl or tipo_dominante in ("date", "datetime"):
            fechas.append(h)
        elif tipo_dominante in ("int", "float", "Decimal") or any(
                k in hl for k in ("importe", "total", "base", "iva", "monto")):
            numericas.append(h)

    agrupacion = []
    if fechas and numericas:
        agrupacion.append(f"Agrupar por {fechas[0]} (mes/año) sumando {', '.join(numericas)}")
    elif numericas:
        agrupacion.append(f"Sumar/agregar {', '.join(numericas)}")

    return {"name": ws.title, "rows": n_rows, "cols": len(headers),
            "columnas": columnas, "preview": preview, "agrupacion_sugerida": agrupacion}


def resumen_excel(xlsx_path: str, sheet_name: str | None = None,
                   max_rows_preview: int = 10, max_rows_scan: int = 5000) -> dict:
    """Shape de un .xlsx sin exigir recálculo: dims, tipos por columna, nulos,
    primeras filas y una sugerencia simple de agrupación. Usa valores cached (data_only),
    nunca modifica el original."""
    path = Path(xlsx_path).expanduser().resolve()
    try:
        _safety_checks(path)
    except ExcelSafetyError as e:
        return {"error": str(e)}

    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        out_sheets = []
        for ws in wb.worksheets:
            if sheet_name and ws.title != sheet_name:
                continue
            out_sheets.append(_resumen_sheet(ws, max_rows_preview, max_rows_scan))
            if sheet_name:
                break
    finally:
        wb.close()

    if sheet_name and not out_sheets:
        return {"error": f"Hoja no encontrada: {sheet_name}"}
    return {"name": path.name, "sheets": out_sheets}


def reconciliar_excel_bd(excel_rows: list[dict], bd_rows: list[dict], key_col: str,
                          importe_col: str, fecha_col: str | None = None,
                          tolerancia: float = 0.01) -> dict:
    """Concilia filas de una hoja Excel (ya leída, p.ej. con leer_excel/resumen_excel)
    contra filas de la BD (ya obtenidas, p.ej. con run_query), cruzando por key_col.
    key_col es OBLIGATORIO y explícito: no intenta adivinar una clave difusa.
    Devuelve diff por línea (OK/DIFF/SOLO_EXCEL/SOLO_BD) + totales."""
    if not key_col:
        raise ValueError("key_col es obligatorio: indica qué columna identifica cada línea de forma única")

    from decimal import Decimal

    def _idx(rows, origen):
        out = {}
        for r in rows:
            if key_col not in r:
                raise ValueError(f"Falta la columna clave '{key_col}' en una fila de {origen}")
            out[r[key_col]] = r
        return out

    excel_idx = _idx(excel_rows, "excel")
    bd_idx = _idx(bd_rows, "bd")
    tol = Decimal(str(tolerancia))

    diferencias = []
    total_excel = Decimal("0")
    total_bd = Decimal("0")
    for key in sorted(set(excel_idx) | set(bd_idx), key=str):
        e = excel_idx.get(key)
        b = bd_idx.get(key)
        if e is None:
            total_bd += Decimal(str(b[importe_col] or 0))
            diferencias.append({"clave": key, "estado": "SOLO_BD",
                                 "importe_bd": b[importe_col]})
            continue
        if b is None:
            total_excel += Decimal(str(e[importe_col] or 0))
            diferencias.append({"clave": key, "estado": "SOLO_EXCEL",
                                 "importe_excel": e[importe_col]})
            continue
        importe_e = Decimal(str(e[importe_col] or 0))
        importe_b = Decimal(str(b[importe_col] or 0))
        total_excel += importe_e
        total_bd += importe_b
        diff = importe_e - importe_b
        item = {"clave": key, "importe_excel": e[importe_col], "importe_bd": b[importe_col],
                "diff": diff}
        if fecha_col:
            item["fecha_excel"] = e.get(fecha_col)
            item["fecha_bd"] = b.get(fecha_col)
        item["estado"] = "OK" if abs(diff) <= tol else "DIFF"
        diferencias.append(item)

    return {
        "diferencias": diferencias,
        "totales": {"excel": total_excel, "bd": total_bd, "diff": total_excel - total_bd},
        "n_ok": sum(1 for d in diferencias if d["estado"] == "OK"),
        "n_diff": sum(1 for d in diferencias if d["estado"] in ("DIFF", "SOLO_EXCEL", "SOLO_BD")),
    }


def leer_excel(xlsx_path: str, sheet_name: str | None = None,
               include_formulas: bool = True, force_recalc: bool = True,
               max_cells: int = 5000) -> dict:
    """Lee un XLSX de finanzas y devuelve JSON consumible por un LLM para auditoría.
    Nunca modifica el original. Si hay fórmulas y force_recalc activo, recalcula a un
    archivo temporal (LibreOffice si existe, si no formualizer, si no: valores cached
    con aviso). max_cells limita celdas devueltas por hoja (default 5000).
    """
    path = Path(xlsx_path).expanduser().resolve()
    try:
        _safety_checks(path)
    except ExcelSafetyError as e:
        return {"error": str(e)}

    from openpyxl import load_workbook

    formula_info = _detect_formulas(path)
    recalc = {"recalculated": False, "engine": "cached_only"}
    read_path = path
    tmp_dir = None

    if force_recalc and formula_info.get("has_formulas"):
        tmp_dir = Path(tempfile.mkdtemp(prefix="xlsxrecalc_"))
        recalc = _smart_recalc(path, tmp_dir)

    if recalc.get("recalculated"):
        read_path = Path(recalc["path"])

    try:
        wb = load_workbook(read_path, data_only=True, read_only=True)
        fmaps = {}
        if include_formulas and formula_info.get("has_formulas"):
            fmaps = _formula_map(path, sheet_name)
        sheets = []
        for ws in wb.worksheets:
            if sheet_name and ws.title != sheet_name:
                continue
            fmap = fmaps.get(ws.title, {})
            sheets.append(_sheet_to_json(ws, fmap, min(max_cells, MAX_SHEET_CELLS),
                                         _merged_ranges(path, ws.title)))
            if sheet_name:
                break
        meta = {
            "name": path.name,
            "platform": _system(),
            "sheets_meta": [
                {"name": ws.title, "rows": ws.max_row, "cols": ws.max_column,
                 "formulas": formula_info["per_sheet"].get(ws.title, 0)}
                for ws in wb.worksheets
            ],
        }
        wb.close()
    except Exception as e:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"error": f"No se pudo leer XLSX: {e}"}

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if sheet_name:
        chosen = next((s for s in sheets if s["name"] == sheet_name), None)
        sheets = [chosen] if chosen else []

    return {
        "workbook": meta,
        "recalc": recalc,
        "has_formulas": formula_info.get("has_formulas", False),
        "formula_count": formula_info.get("total", 0),
        "sheets": sheets,
    }