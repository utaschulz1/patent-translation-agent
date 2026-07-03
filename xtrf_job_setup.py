"""
xtrf_job_setup.py  —  XTRF workflow step 4

Given an XTRF job URL or numeric job ID (from the start email link),
performs the full step-4 setup:
  4.1  Parse job number + project ID, create project folder + pre-processing/
  4.2  Download source files, unzip, locate Clean_XTM.docx
  4.3  Extract EPO title from job instructions, write glossary CSV

Usage:
    python xtrf_job_setup.py <job-url-or-id>

    <job-url-or-id> must be the XTRF job URL or numeric job ID from the
    start email — NOT the project ID (e.g. "HALA_2606_P0476").

    Examples:
        python xtrf_job_setup.py https://comunicadk.s.xtrf.eu/vendors/#/jobs/classic/316307
        python xtrf_job_setup.py 316307
"""

import argparse
import csv
import os
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv
from openai import OpenAI

import project_log
from config import WORK_DIR, extract_project_id

BASE_URL = "https://comunicadk.s.xtrf.eu/vendors"
MODEL = "deepseek/deepseek-chat-v3-0324"

_ENV = Path(__file__).parent / ".env"


def _load_creds() -> dict:
    """Load XTRF login credentials from .env."""
    load_dotenv(_ENV)
    return {
        "email": os.environ["COMUNICA_JOBLIST_USERNAME"],
        "password": os.environ["COMUNICA_JOBLIST_PASSWORD"],
    }


def _llm_extract_terms(en_title: str, de_title: str, retries: int = 5) -> list[tuple[str, str]]:
    """Use DeepSeek to extract bilingual term pairs from an EN/DE patent title."""
    load_dotenv(_ENV)
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    prompt = (
        "You are a patent terminology extractor. "
        "Given an English and German patent title, extract all meaningful noun phrases and technical terms as bilingual pairs. "
        "English lowercase, German with correct noun capitalisation. "
        "Return ONLY CSV with two columns EN,DE — one term pair per line, no header, no explanation.\n\n"
        f"English title: {en_title}\n"
        f"German title: {de_title}"
    )
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = response.choices[0].message.content.strip()
            pairs = []
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.lower().startswith("en,"):
                    continue
                parts = line.split(",", 1)
                if len(parts) == 2:
                    pairs.append((parts[0].strip(), parts[1].strip()))
            if pairs:
                return pairs
        except Exception as e:
            print(f"  DeepSeek attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    print("  DeepSeek extraction failed after all retries — glossary will be empty.")
    return []

def _extract_job_id(raw: str) -> str | None:
    """Extract the numeric job ID from a full XTRF URL or a bare ID string.

    Returns None when the URL uses the new token-based format (#/job/TOKEN)
    so the caller can fall back to a project-name search.
    """
    # Old format: #/jobs/classic/316307
    m = re.search(r"/jobs/(?:classic/)?(\d+)", raw)
    if m:
        return m.group(1)

    if re.fullmatch(r"\d+", raw.strip()):
        return raw.strip()

    # New format: #/job/BASE64TOKEN — token cannot be used as a REST job ID
    if re.search(r"/job/[A-Za-z0-9+/=_-]{10,}", raw):
        return None

    raise ValueError(f"Cannot extract job ID from: {raw!r}")


def _find_job_id_by_project(session: requests.Session, project_id: str) -> str:
    """Search the job list for a job whose project name contains project_id."""
    statuses = "IN_PROGRESS,IN_PROGRESS_AWAITING_CORRECTIONS,PENDING"
    r = session.get(f"{BASE_URL}/jobs", params={"statuses": statuses})
    r.raise_for_status()
    for job in r.json():
        name = job.get("overview", {}).get("projectName", "")
        if project_id in name:
            return str(job["id"])
    raise ValueError(
        f"No IN_PROGRESS/PENDING job found for project '{project_id}'. "
        "Check XTRF or verify the project ID."
    )

def _login(session: requests.Session, creds: dict) -> None:
    """Authenticate the session against the XTRF vendor portal."""
    r = session.post(
        f"{BASE_URL}/sign-in",
        json={"email": creds["email"], "password": creds["password"]},
        headers={"time-zone-offset-in-minutes": "60"},
    )
    r.raise_for_status()


def _get_job(session: requests.Session, job_id: str) -> dict:
    """Fetch full job JSON from the XTRF API."""
    endpoint = f"{BASE_URL}/jobs/classic/{job_id}"
    
    r = session.get(endpoint, headers={"time-zone-offset-in-minutes": "60"})
    r.raise_for_status()
    return r.json()


def _make_folder_name(id_number: str, project_id: str) -> str:
    """Build a filesystem-safe folder name from the job ID number and project ID."""
    # "2026/4545/EN » DE/1/1"  →  "20264545ENDE11"
    folder_id = re.sub(r"[^a-zA-Z0-9]", "", id_number)
    return f"{folder_id}_{project_id}"


def _download_file(session: requests.Session, url: str, dest: Path) -> Path:
    """Download a single file, using the content-disposition filename when available."""
    r = session.get(url, headers={"time-zone-offset-in-minutes": "60"}, stream=True)
    r.raise_for_status()
    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename[^;=\n]*=\s*["\']?([^"\';\n]+)', cd)
    fname = unquote(m.group(1).strip()) if m else dest.name
    out = dest.parent / fname if dest.is_dir() else dest
    with open(out, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return out


def _strip_tilde_suffix(name: str) -> str:
    """Return the base filename without a Windows-style ~N dedup suffix (e.g. foo~1.zip → foo.zip)."""
    stem, _, ext = name.rpartition(".")
    stem_clean = re.sub(r"~\d+$", "", stem)
    return f"{stem_clean}.{ext}" if ext else stem_clean


def _download_source_files(
    session: requests.Session, job_id: str, source_files: list, dest_folder: Path
) -> list[Path]:
    """Download all downloadable source files for a job into dest_folder.

    Skips files whose name is a ~N duplicate of an already-downloaded file
    (XTRF sometimes returns the same attachment twice with a ~1 suffix).
    """
    downloaded = []
    downloaded_bases: set[str] = set()
    for sf in source_files:
        if not sf.get("downloadable"):
            continue
        filename = sf["name"]
        base = _strip_tilde_suffix(filename)
        if base in downloaded_bases:
            print(f"  Skipping duplicate: {filename} (already have {base})")
            continue
        url = f"{BASE_URL}/jobs/classic/{job_id}/source-files/{sf['id']}"
        out_path = dest_folder / filename
        print(f"  Downloading {filename}...")
        _download_file(session, url, out_path)
        downloaded.append(out_path)
        downloaded_bases.add(base)
        downloaded_bases.add(filename)
    return downloaded


def _unzip_all(zip_paths: list[Path], dest_folder: Path) -> list[Path]:
    """Extract all zip archives into dest_folder and return the list of extracted paths."""
    extracted = []
    for zp in zip_paths:
        if zp.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(zp) as zf:
                zf.extractall(dest_folder)
                extracted.extend(dest_folder / n for n in zf.namelist())
            zp.unlink()
        except zipfile.BadZipFile:
            print(f"  WARNING: {zp.name} is not a valid zip — skipping and deleting.")
            zp.unlink()
    return extracted


def _parse_epo_title(instructions_html: str) -> tuple[str, str]:
    """Extract the English and German EPO title strings from the job instructions HTML.

    Finds every "German:"/"English:"/"French:" marker and takes the text between
    each one and whichever marker comes next (or end of string), then cuts that
    slice at its first newline. This avoids assuming any particular separator
    character between a title and the next marker — some jobs put
    "German: ... English: ..." on one line with no real delimiter to anchor on;
    others put unrelated instructions text on the lines following the title.
    """
    text = re.sub(r"<[^>]+>", " ", instructions_html)
    text = re.sub(r"&nbsp;", " ", text)
    markers = list(re.finditer(r"(German|English|French):", text))
    en, de = "", ""
    for i, m in enumerate(markers):
        next_start = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        value = text[m.end():next_start].split("\n", 1)[0].strip()
        lang = m.group(1)
        if lang == "English" and not en:
            en = value
        elif lang == "German" and not de:
            de = value
    return en, de


def _write_glossary(project_id: str, pairs: list[tuple[str, str]], dest_dir: Path, en_title: str = "", de_title: str = "") -> Path:
    """Write EN/DE term pairs to a CSV glossary file named after the project."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dest_dir / f"glossary_{project_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["EN", "DE"])
        if en_title or de_title:
            writer.writerow([f"EPO EN: {en_title}", f"EPO DE: {de_title}"])
            writer.writerow([])
        writer.writerows(pairs)
    return csv_path


def run(job_url_or_id: str, project_id_override: str | None = None) -> dict:
    """Run the full step-4 setup: login, fetch job, create folders, download files, write glossary."""
    creds = _load_creds()
    job_id = _extract_job_id(job_url_or_id)

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    })

    print(f"Logging in to XTRF...")
    _login(session, creds)

    if job_id is None:
        if not project_id_override:
            raise ValueError(
                "XTRF URL uses the new token-based format (#/job/TOKEN). "
                "Pass a project ID (e.g. workflow_lara.py --target PROJ_ID) so the job can be looked up."
            )
        print(f"Token URL detected — looking up job for '{project_id_override}'...")
        job_id = _find_job_id_by_project(session, project_id_override)
        print(f"  Found job ID: {job_id}")

    print(f"Fetching job {job_id}...")
    job = _get_job(session, job_id)
    overview = job["overview"]

    id_number = overview["idNumber"]       # "2026/4545/EN » DE/1/1"
    project_name = overview["projectName"] # "Patents | RTC_2604_P0732"
    task_type = overview["type"]           # "Post-editing" or "Revision"
    source_files = job.get("sourceFiles") or []
    instructions = job.get("instructions") or ""

    # project_id_override comes from the email subject (e.g. "HUAW_2604_P0843");
    # fall back to the XTRF project name when no override is supplied.
    project_id = project_id_override or extract_project_id(project_name)
    folder_name = _make_folder_name(id_number, project_id)

    # 4.1  Create folders
    project_folder = WORK_DIR / folder_name          # OneDrive — source files
    pre_folder = project_folder / "pre-processing"
    project_folder.mkdir(parents=True, exist_ok=True)
    pre_folder.mkdir(exist_ok=True)
    print(f"Created XTRF folder: {project_folder}")

    # 4.1b  Set active project context (pre-processing folder is the working area)
    project_log.set_context(project_id, pre_folder,
                            xtrf_job_folder=str(project_folder),
                            task_type=task_type,
                            xtrf_job_id=job_id)

    # 4.2  Download + unzip source files
    if source_files:
        downloaded = _download_source_files(session, job_id, source_files, project_folder)
        zip_files = [p for p in downloaded if p.suffix.lower() == ".zip"]
        if zip_files:
            extracted = _unzip_all(zip_files, project_folder)
            cat_files = [p for p in extracted if "Clean_XTM" in p.name and p.suffix.lower() == ".docx"]
            if cat_files:
                print(f"  CAT file: {cat_files[0].name}")
            else:
                print(f"  Extracted {len(extracted)} file(s) — no Clean_XTM.docx found, check manually")
    else:
        print("No source files attached to this job.")

    # 4.3  EPO title → DeepSeek term extraction → glossary CSV
    en_title, de_title = _parse_epo_title(instructions)
    if en_title:
        print(f"EPO title found — extracting terms with DeepSeek...")
        pairs = _llm_extract_terms(en_title, de_title)
        csv_path = _write_glossary(project_id, pairs, pre_folder, en_title, de_title)
        print(f"Glossary written: {csv_path}  ({len(pairs)} term(s))")
        for en, de in pairs:
            print(f"  {en}  →  {de}")
    else:
        print("EPO title not found in instructions — create glossary manually.")

    # Summary
    print()
    print("=" * 50)
    print(f"Job:        {id_number}")
    print(f"Project:    {project_id}")
    print(f"Task type:  {task_type}  ({'1/1 translation' if 'edit' in task_type.lower() or 'translat' in task_type.lower() else '1/2 review'})")
    print(f"Folder:     {folder_name}")
    if en_title:
        print(f"EPO EN:     {en_title}")
        print(f"EPO DE:     {de_title}")
    print("=" * 50)
    print("Step 4 complete. Next: open XTM link from the XTRF job page (step 5).")
    print(f"XTM login: https://word.welocalize.com/project-manager-gui/login.jsp?client=IP#!/login")
    return {"project_id": project_id, "project_folder": str(pre_folder)}


def main():
    """CLI entry point — parse arguments and call run()."""
    parser = argparse.ArgumentParser(description="XTRF step 4: job setup")
    parser.add_argument("job", help="XTRF job URL or numeric job ID from the start email (not the project ID)")
    args = parser.parse_args()
    result = run(args.job)
    print(f"Project folder: {result['project_folder']}")


if __name__ == "__main__":
    main()
