"""Upload a local directory tree to Google Drive (mirrors rclone copy behaviour)."""
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MIME_FOLDER = "application/vnd.google-apps.folder"


def _credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    q = (
        f"name='{name}' and mimeType='{MIME_FOLDER}'"
        f" and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": MIME_FOLDER, "parents": [parent_id]}
    return service.files().create(body=meta, fields="id").execute()["id"]


def _resolve_path(service, gdrive_path: str) -> str:
    """Walk a slash-separated path from Drive root, creating folders as needed."""
    parent_id = "root"
    for part in gdrive_path.strip("/").split("/"):
        parent_id = _get_or_create_folder(service, part, parent_id)
    return parent_id


def _upload_file(service, local_path: Path, parent_id: str) -> None:
    name = local_path.name
    media = MediaFileUpload(str(local_path), resumable=True)
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        service.files().create(
            body={"name": name, "parents": [parent_id]}, media_body=media
        ).execute()


def gdrive_sync(local_dir: Path, gdrive_base_path: str, project_id: str) -> None:
    """
    Upload all files under local_dir to gdrive_base_path/project_id/ on Drive.
    Push-only — does not delete remote files not present locally.
    """
    creds = _credentials()
    creds.refresh(Request())
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    root_folder_id = _resolve_path(service, f"{gdrive_base_path}/{project_id}")

    for local_file in sorted(local_dir.rglob("*")):
        if not local_file.is_file():
            continue
        rel_parts = local_file.relative_to(local_dir).parts
        parent_id = root_folder_id
        for part in rel_parts[:-1]:
            parent_id = _get_or_create_folder(service, part, parent_id)
        _upload_file(service, local_file, parent_id)
