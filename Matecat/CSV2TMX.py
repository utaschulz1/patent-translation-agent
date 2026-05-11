# ============================================================
# CSV2TMX.py  —  Convert a clean_glossary / glossary CSV to TMX
# ============================================================
# Reads EN/DE columns from a glossary CSV and writes a TMX 1.4
# file ready to import into a MateCat "Glossary" memory.
#
# USAGE
#   python CSV2TMX.py <path/to/glossary.csv>
#   python CSV2TMX.py <path/to/glossary.csv> <output.tmx>   # explicit output
#
# Output defaults to <same folder>/<stem>.tmx
# Skips:  comment lines starting with #
#         rows where EN starts with "EPO EN:" (metadata, not terms)
#         rows with empty EN or DE
# ============================================================

import csv
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SRC_LANG = "en-US"
TGT_LANG = "de-DE"


def csv_to_tmx(csv_path: Path, tmx_path: Path) -> int:
    """Convert glossary CSV to TMX. Returns number of TUs written."""
    root = ET.Element("tmx", version="1.4")

    header = ET.SubElement(root, "header",
        **{
            "creationtool":        "CSV2TMX",
            "creationtoolversion": "1.0",
            "datatype":            "plaintext",
            "segtype":             "phrase",
            "adminlang":           "en-US",
            "srclang":             SRC_LANG,
            "o-tmf":               "csv",
            "creationdate":        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        }
    )

    body = ET.SubElement(root, "body")
    count = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        lines = [l for l in f if not l.startswith("#")]

    for row in csv.DictReader(lines):
        en = row.get("EN", "").strip()
        de = row.get("DE", "").strip()

        if not en or not de:
            continue
        if en.startswith("EPO EN:"):
            continue

        tu = ET.SubElement(body, "tu")
        tuv_en = ET.SubElement(tu, "tuv", **{"xml:lang": SRC_LANG})
        ET.SubElement(tuv_en, "seg").text = en
        tuv_de = ET.SubElement(tu, "tuv", **{"xml:lang": TGT_LANG})
        ET.SubElement(tuv_de, "seg").text = de
        count += 1

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(tmx_path, "wb") as out:
        out.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        out.write(b'<!DOCTYPE tmx PUBLIC "-//LISA OSCAR:1998//DTD for Translation Memory eXchange//EN" "tmx14.dtd">\n')
        tree.write(out, encoding="utf-8", xml_declaration=False)

    return count


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python CSV2TMX.py <glossary.csv> [output.tmx]")
        raise SystemExit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: file not found: {csv_path}")
        raise SystemExit(1)

    tmx_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else csv_path.with_suffix(".tmx")

    print(f"Input:  {csv_path}")
    print(f"Output: {tmx_path}")

    count = csv_to_tmx(csv_path, tmx_path)
    print(f"Written {count} translation units to {tmx_path.name}")


if __name__ == "__main__":
    main()
