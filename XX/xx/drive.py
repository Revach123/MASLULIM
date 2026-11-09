"""העלאה ל-Google Drive. הרשאה: OAuth (credentials.json) או חשבון שירות."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_service(credentials_file: str = "credentials.json", token_file: str = "token.json"):
    cred_path = Path(credentials_file)
    if not cred_path.exists():
        raise SystemExit(f"לא נמצא {credentials_file} - ראה README (הגדרת Google Drive)")
    import json

    info = json.loads(cred_path.read_text())
    if info.get("type") == "service_account":
        creds = service_account.Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
    else:
        creds = None
        tp = Path(token_file)
        if tp.exists():
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES).run_local_server(port=0)
            tp.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def ensure_folder(service, name: str, parent_id: str | None = None) -> str:
    q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    found = service.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if found:
        return found[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    return service.files().create(body=meta, fields="id").execute()["id"]


def upload(service, files: list[Path], folder_id: str) -> list[str]:
    links = []
    for p in files:
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
        res = service.files().create(
            body={"name": p.name, "parents": [folder_id]}, media_body=media, fields="id,webViewLink"
        ).execute()
        links.append(res["webViewLink"])
        print(f"הועלה: {p.name} -> {res['webViewLink']}")
    return links
