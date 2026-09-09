def shape_rows(pair):
    cols, rows = pair
    return {"columns": cols, "rows": [[r[c] for c in cols] for r in rows] if cols else rows}
