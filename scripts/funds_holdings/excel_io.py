"""עזרי קריאת Excel: python-calamine, בלי המרת טיפוסים (כמו Excel.Workbook(..., null, true))."""
from python_calamine import CalamineWorkbook


def read_workbook_sheets(path) -> dict[str, list[list]]:
    """שם גיליון -> רשימת שורות (כל שורה = רשימת ערכים גולמיים, בלי המרה)."""
    wb = CalamineWorkbook.from_path(str(path))
    return {name: wb.get_sheet_by_name(name).to_python() for name in wb.sheet_names}


def to_ratio(v) -> float | None:
    """שיעור/אחוז לערך יחסי (0.00093), בין אם המקור הוא מספר גולמי (כבר יחסי)
    או טקסט עם % (אז מחלקים ב-100). נמצא בפועל: ~14% מהשורות מגיעות כטקסט
    כמו "0.093%" במקום float גולמי - תלוי בקובץ המקור."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def text_from(v) -> str | None:
    """Text.From-מקביל: מספרים שלמים בלי .0, שאר הערכים כטקסט. None נשאר None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    return str(v)
