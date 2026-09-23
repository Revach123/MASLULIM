"""ממיר out/master.json ו-out/funds_detail.json ל-master.sql/funds_detail.sql
עבור wrangler d1 execute. מקביל ל-build_d1.py/build_d1_tracks.py ב-revach.

DB: maslulim_autopilot (binding AUTOPILOT ב-Pages).
טבלת master: עמודת מפתח (PRIMARY KEY) + כמה עמודות לאינדוקס/סינון + data
  (JSON מלא של השורה - כל שאר השדות, כולל אלה שמשתנים בין ריצות כמו עמודות
  "קרן מחקה - X"). טבלת funds_detail: מפתח (PRIMARY KEY) + data (JSON
  array של רשימת הקרנות המלאה לאותו מסלול).

הרצה: python -m funds_holdings.build_d1 --out-dir out
"""
import argparse
import json
from pathlib import Path

MAX_BYTES = 80000  # תקרת D1 לסטייטמנט (~100KB), עם מרווח ביטחון

MASTER_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS master (\n"
    "  מפתח TEXT PRIMARY KEY,\n"
    "  ח_פ_חברה TEXT,\n"
    "  מספר_מסלול TEXT,\n"
    "  שם_חברה TEXT,\n"
    "  תחום TEXT,\n"
    "  כשרות TEXT,\n"
    "  data TEXT\n"
    ");\n"
    "CREATE INDEX IF NOT EXISTS idx_master_chp ON master(ח_פ_חברה);\n"
    "CREATE INDEX IF NOT EXISTS idx_master_domain ON master(תחום);\n"
)

DETAIL_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS funds_detail (\n"
    "  מפתח TEXT PRIMARY KEY,\n"
    "  data TEXT\n"
    ");\n"
)


def sql_str(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def write_batched(out_path: Path, table: str, schema: str, col_names: list[str], rows: list[tuple]):
    cols_clause = "(" + ",".join(col_names) + ")"
    header = f"INSERT INTO {table} {cols_clause} VALUES\n"

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(schema)
        out.write(f"DELETE FROM {table};\n")

        batch = []
        batch_bytes = len(header.encode("utf-8"))

        def flush():
            nonlocal batch, batch_bytes
            if not batch:
                return
            out.write(header + ",\n".join(batch) + ";\n")
            batch = []
            batch_bytes = len(header.encode("utf-8"))

        written = 0
        for row in rows:
            tup = "(" + ",".join(row) + ")"
            tb = len(tup.encode("utf-8")) + 2
            if batch and batch_bytes + tb > MAX_BYTES:
                flush()
            batch.append(tup)
            batch_bytes += tb
            written += 1
        flush()
    return written


def build_master_sql(master: list[dict], out_path: Path) -> int:
    col_names = ["מפתח", "ח_פ_חברה", "מספר_מסלול", "שם_חברה", "תחום", "כשרות", "data"]
    rows = []
    for rec in master:
        key = rec.get("מפתח")
        if key is None:
            continue
        data_json = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        rows.append((
            sql_str(key),
            sql_str(rec.get("ח.פ. חברה")),
            sql_str(rec.get("מס' מסלול")),
            sql_str(rec.get("שם החברה")),
            sql_str(rec.get("תחום")),
            sql_str(rec.get("כשרות")),
            sql_str(data_json),
        ))
    return write_batched(out_path, "master", MASTER_SCHEMA, col_names, rows)


def build_detail_sql(detail: dict[str, list], out_path: Path) -> int:
    col_names = ["מפתח", "data"]
    rows = []
    for key, funds in detail.items():
        data_json = json.dumps(funds, ensure_ascii=False, separators=(",", ":"))
        rows.append((sql_str(key), sql_str(data_json)))
    return write_batched(out_path, "funds_detail", DETAIL_SCHEMA, col_names, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path("out"))
    args = ap.parse_args()

    with open(args.out_dir / "master.json", encoding="utf-8") as f:
        master = json.load(f)
    with open(args.out_dir / "funds_detail.json", encoding="utf-8") as f:
        detail = json.load(f)

    n1 = build_master_sql(master, args.out_dir / "master.sql")
    n2 = build_detail_sql(detail, args.out_dir / "funds_detail.sql")
    print(f"[build_d1] master: {n1} שורות -> {args.out_dir}/master.sql")
    print(f"[build_d1] funds_detail: {n2} שורות -> {args.out_dir}/funds_detail.sql")


if __name__ == "__main__":
    main()
