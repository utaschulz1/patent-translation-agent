"""Pull *_revised_translation_checks*.xlsx from Google Drive into the project folder."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# gdrive.py lives one level up in the app directory
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

load_dotenv()

from gdrive import gdrive_pull_revised_excel  # noqa: E402

project_id = sys.argv[1]
gdrive_base_path = os.environ.get("GDRIVE_BASE_PATH", "patent-translation-app/ComunicaDK")

ctx_path = Path(__file__).parent / "current_project.json"
ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
local_dir = Path(ctx["project_folder"])

gdrive_pull_revised_excel(local_dir, gdrive_base_path, project_id)
