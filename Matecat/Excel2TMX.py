"""
Excel2TMX.py  —  Convert translated xlsx files to a single TMX for Matecat TM upload.

Input format (same as *_translated.xlsx / *_iptranslated.xlsx):
  Row 0:  filename (metadata)
  Row 1:  blank / metadata
  Row 2:  blank / metadata
  Row 3+: data rows — columns 0=ID, 1=Source, 2=Target

Usage:
  python Excel2TMX.py                        # processes Final_*.xlsx in current directory
  python Excel2TMX.py path/to/folder         # processes Final_*.xlsx in given folder
  python Excel2TMX.py path/to/file.xlsx      # converts a single xlsx file directly

Output:
  folder mode: <folder_name>.tmx  in the same folder (e.g. ComunicaDK.tmx)
  file mode:   <stem>.tmx  next to the input file
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

if arg.is_file():
    xlsx_files = [arg]
    folder = arg.parent
    print(f"Single file: {arg.name}")
elif arg.is_dir():
    folder = arg
    xlsx_files = sorted(
        f for f in folder.glob("Final_*.xlsx")
        if not f.name.startswith("~$")
    )
    if not xlsx_files:
        print(f"No Final_*.xlsx files found in {folder}")
        sys.exit(1)
    print(f"Found {len(xlsx_files)} file(s) in {folder}:")
    for f in xlsx_files:
        print(f"  {f.name}")
else:
    print(f"ERROR: not a file or directory: {arg}")
    sys.exit(1)

timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

tmx = (
    '<?xml version="1.0" ?>\n'
    '<!DOCTYPE tmx SYSTEM "https://uri.etsi.org/lis/002/v1.4.2/tmx14.dtd">\n'
    '<tmx version="1.4">\n'
    '  <header creationtool="MyMemory - mymemory.translated.net"\n'
    '          creationtoolversion="1.3.25"\n'
    '          creationid="Translated"\n'
    '          datatype="PlainText"\n'
    '          segtype="sentence"\n'
    '          o-tmf="MyMemory"\n'
    '          adminlang="en-US"\n'
    '          srclang="en-US"/>\n'
    '  <body>\n'
)

total_segments = 0

for xlsx_path in xlsx_files:
    try:
        raw = pd.read_excel(xlsx_path, header=None, engine="openpyxl")
    except Exception as e:
        print(f"  WARNING: could not read {xlsx_path.name}: {e} — skipped.")
        continue

    data = raw.iloc[3:].reset_index(drop=True)
    data.columns = ["ID", "Source", "Target"] + list(data.columns[3:])

    file_count = 0
    for _, row in data.iterrows():
        source = str(row["Source"]).strip() if pd.notna(row["Source"]) else ""
        target = str(row["Target"]).strip() if pd.notna(row["Target"]) else ""
        if not source or not target or source == "nan" or target == "nan":
            continue

        tuid = str(row["ID"]).strip()
        src_xml = xml_escape(source)
        tgt_xml = xml_escape(target)

        tmx += (
            f'    <tu tuid="{xml_escape(tuid)}"\n'
            f'        srclang="en-US"\n'
            f'        creationdate="{timestamp}"\n'
            f'        creationid="MyMemory_{xml_escape(tuid)}"\n'
            f'        changedate="{timestamp}"\n'
            f'        changeid="MyMemory_{xml_escape(tuid)}">\n'
            f'      <tuv xml:lang="en-US"><seg>{src_xml}</seg></tuv>\n'
            f'      <tuv xml:lang="de-DE"><seg>{tgt_xml}</seg></tuv>\n'
            f'    </tu>\n'
        )
        file_count += 1

    print(f"  {xlsx_path.name}: {file_count} segment(s) added.")
    total_segments += file_count

tmx += "  </body>\n</tmx>\n"

stem = xlsx_files[0].stem if len(xlsx_files) == 1 and arg.is_file() else folder.name
out_path = folder / f"{stem}.tmx"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(tmx)

print(f"\nWritten {total_segments} segments → {out_path}")
