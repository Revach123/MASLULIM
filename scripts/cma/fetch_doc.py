"""כלי חד-פעמי: מוריד PDF מ-URL נתון (חוזר CMA מ-gov.il, חסום ב-sandbox המקומי)
ומדפיס את הטקסט המחולץ ישירות ל-stdout (כדי שיהיה קריא מתוך לוגים של Actions,
בלי צורך בהורדת artifact בינארי).

הרצה: python -m scripts.cma.fetch_doc <url>
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

OUT = Path("doc_out")


def main():
    if len(sys.argv) < 2:
        print("usage: python -m scripts.cma.fetch_doc <url> [<url> ...]")
        sys.exit(1)
    OUT.mkdir(exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for url in sys.argv[1:]:
        name = Path(urlparse(url).path).name or "download"
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            path = OUT / name
            path.write_bytes(r.content)
            print(f"OK  {url} -> doc_out/{name} ({len(r.content)} bytes, content-type={r.headers.get('content-type')})")
        except Exception as e:
            print(f"FAIL {url}: {e!r}")
            continue

        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                print(f"--- {name}: {len(reader.pages)} עמודים ---")
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    print(f"\n===== עמוד {i + 1} =====")
                    print(text)
            except Exception as e:
                print(f"FAIL extracting text from {name}: {e!r}")


if __name__ == "__main__":
    main()
