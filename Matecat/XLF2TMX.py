"""
XLF2TMX.py  —  Convert *.xlf files to a single TMX for MateCat TM upload.

Reads source and target text from each <trans-unit> in the XLF.
Segments with empty targets are skipped.

Intended use: batch-convert a folder of old translated XLF files to
a TMX that can be uploaded to a MateCat TM to seed coming projects.

Usage:
  python XLF2TMX.py                  # processes *.xlf in current directory
  python XLF2TMX.py path/to/folder   # processes *.xlf in given folder

Output:
  <folder_name>.tmx  in the same folder
"""

import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

_XLF_NS = "urn:oasis:names:tc:xliff:document:1.2"

def _ns(tag: str) -> str:
    return f"{{{_XLF_NS}}}{tag}"


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def _element_text(elem: ET.Element) -> str:
    """Extract all text content including text inside inline child tags."""
    return "".join(elem.itertext()).strip()


folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
if not folder.is_dir():
    print(f"ERROR: not a directory: {folder}")
    sys.exit(1)

xlf_files = sorted(folder.glob("*.xlf"))

if not xlf_files:
    print(f"No *.xlf files found in {folder}")
    sys.exit(1)

print(f"Found {len(xlf_files)} file(s) in {folder}:")
for f in xlf_files:
    print(f"  {f.name}")

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

for xlf_path in xlf_files:
    try:
        tree = ET.parse(xlf_path)
    except Exception as e:
        print(f"  WARNING: could not parse {xlf_path.name}: {e} — skipped.")
        continue

    file_count = 0
    for tu in tree.getroot().iter(_ns("trans-unit")):
        tuid = tu.get("id", "")

        source_elem = tu.find(_ns("source"))
        target_elem = tu.find(_ns("target"))

        source = _element_text(source_elem) if source_elem is not None else ""
        target = _element_text(target_elem) if target_elem is not None else ""

        if not source or not target:
            continue

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

    print(f"  {xlf_path.name}: {file_count} segment(s) added.")
    total_segments += file_count

tmx += "  </body>\n</tmx>\n"

out_path = folder / f"{folder.name}.tmx"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(tmx)

print(f"\nWritten {total_segments} segments → {out_path}")
