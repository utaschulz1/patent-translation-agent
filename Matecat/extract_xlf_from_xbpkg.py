"""
extract_xlf_from_xbpkg.py  —  Extract .xlf files from XTM .xbpkg archives.

.xbpkg files are ZIP archives. This script opens each one and saves any
.xlf files it finds to the same folder, ready for XLF2TMX.py.

Usage:
  python extract_xlf_from_xbpkg.py                  # processes HALA_old/ by default
  python extract_xlf_from_xbpkg.py path/to/folder   # processes given folder
"""

import sys
import zipfile
from pathlib import Path

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "HALA_old"

if not folder.is_dir():
    print(f"ERROR: not a directory: {folder}")
    sys.exit(1)

xbpkg_files = sorted(folder.glob("*.xbpkg"))
if not xbpkg_files:
    print(f"No .xbpkg files found in {folder}")
    sys.exit(1)

print(f"Found {len(xbpkg_files)} .xbpkg file(s) in {folder}\n")

total_extracted = 0

for pkg in xbpkg_files:
    try:
        with zipfile.ZipFile(pkg, "r") as zf:
            xlf_entries = [e for e in zf.namelist() if e.lower().endswith(".xlf")]
            if not xlf_entries:
                print(f"  {pkg.name}: no .xlf files inside — skipped.")
                continue
            for entry in xlf_entries:
                # Flatten path: save directly to folder using just the filename
                out_name = Path(entry).name
                out_path = folder / out_name
                # Avoid overwriting if multiple packages have the same xlf name
                if out_path.exists():
                    stem, suffix = out_name.rsplit(".", 1) if "." in out_name else (out_name, "")
                    out_path = folder / f"{pkg.stem}_{out_name}"
                out_path.write_bytes(zf.read(entry))
                print(f"  {pkg.name}  →  {out_path.name}")
                total_extracted += 1
    except zipfile.BadZipFile:
        print(f"  {pkg.name}: not a valid ZIP archive — skipped.")

print(f"\nDone. {total_extracted} .xlf file(s) extracted to {folder}")
