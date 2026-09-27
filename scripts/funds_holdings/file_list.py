"""FileList: הקובץ האחרון לכל CompanyType (LegalId_SystemName).

מקור: Autopilot_Section1.m, שאילתת FileList.
במקור: Folder.Files על תיקייה שטוחה במחשב המשתמש. אצלנו: reports/<year>Q<quarter>/
ב-repo MASLULIM (README.md), אז סורקים רקורסיבית על כל תת-התיקיות.
"""
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class ReportFile:
    name: str            # שם הקובץ בלי הנתיב, למשל "511789190_pn_0226.xlsx"
    path: Path           # נתיב מלא
    company_type: str    # "570009852_gm" (Parts[0] & "_" & Parts[1])
    sort_key: int         # YY*10 + QQ, מהחלק האחרון של השם - להשוואת "העדכני ביותר"
                          # בלבד (יש בו התנגשויות אמיתיות, למשל 2602 ו-1225 שניהם
                          # 262 - לא לשימוש כתאריך אמיתי, ר' report_month)
    report_month: date | None  # 1 לחודש הדיווח (YYYY-MM-01), מפורק בנפרד מ-sort_key


def _stem_parts(filename: str) -> list[str]:
    stem = filename.rsplit(".", 1)[0]
    return stem.split("_")


def _sort_key(last_part: str) -> int:
    """Number.From(Text.End(Last, 2)) * 10 + Number.From(Text.Start(Last, 2))."""
    yy = int(last_part[-2:])
    qq = int(last_part[:2])
    return yy * 10 + qq


def _report_month(last_part: str) -> date | None:
    """MMYY (למשל '0226' = פברואר 2026) -> תאריך היום ה-1 של חודש הדיווח.
    נפרד מ-_sort_key בכוונה - sort_key מתנגש בין תאריכים שונים (ר' הערת
    ReportFile), לא מתאים לשימוש כתאריך אמיתי."""
    try:
        mm = int(last_part[:2])
        yy = int(last_part[-2:])
        return date(2000 + yy, mm, 1)
    except (ValueError, IndexError):
        return None


def list_files(reports_dir: Path) -> list[ReportFile]:
    """כל קבצי ה-xlsx תחת reports_dir, עם CompanyType ו-SortKey."""
    out = []
    for p in sorted(reports_dir.rglob("*.xlsx")):
        parts = _stem_parts(p.name)
        if len(parts) < 2:
            continue  # שם שלא תואם לתבנית הצפויה - לא ניתן לסווג, מדולג
        company_type = f"{parts[0]}_{parts[1]}"
        last = parts[-1]
        try:
            sort_key = _sort_key(last)
        except (ValueError, IndexError):
            continue  # לא ניתן לחשב SortKey - מדולג (ראה TODO בהערת המודול)
        out.append(ReportFile(name=p.name, path=p, company_type=company_type, sort_key=sort_key,
                               report_month=_report_month(last)))
    return out


def latest_per_company(files: list[ReportFile]) -> list[ReportFile]:
    """Table.Group by CompanyType, שומר רק את השורה עם ה-SortKey המקסימלי."""
    best: dict[str, ReportFile] = {}
    for f in files:
        cur = best.get(f.company_type)
        if cur is None or f.sort_key > cur.sort_key:
            best[f.company_type] = f
    return list(best.values())


def get_file_list(reports_dir: Path) -> list[ReportFile]:
    return latest_per_company(list_files(reports_dir))
