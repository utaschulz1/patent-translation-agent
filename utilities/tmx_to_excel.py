"""
Convert a TMX (Translation Memory eXchange) file into an Excel spreadsheet.

Each <tu> in the TMX becomes one row, with one column per language found
in its <tuv> entries (columns are ordered by first appearance in the file),
plus a leading 'tuid' column. The output is written next to the input file
as <input_basename>.xlsx.

Usage:
    python3 tmx_to_excel.py -f /path/to/file.tmx

Example:
    python3 tmx_to_excel.py -f /home/user/Downloads/ICE_CATG_2607_P0406.tmx
    -> writes /home/user/Downloads/ICE_CATG_2607_P0406.xlsx
"""

import argparse
import os
import xml.etree.ElementTree as ET

import pandas as pd


def tmx_to_rows(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Collect languages in the order they first appear, so columns stay stable
    languages = []
    rows = []

    for tu in root.iter("tu"):
        row = {"tuid": tu.get("tuid")}
        for tuv in tu.findall("tuv"):
            # xml:lang uses the full XML namespace
            lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang")
            seg = tuv.find("seg")
            text = "".join(seg.itertext()) if seg is not None else ""
            if lang not in languages:
                languages.append(lang)
            row[lang] = text
        rows.append(row)

    return rows, languages


def tmx_to_excel(file_path):
    if not os.path.exists(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        return

    try:
        rows, languages = tmx_to_rows(file_path)

        if not rows:
            print("No translation units found in the provided TMX file.")
            return

        df = pd.DataFrame(rows, columns=["tuid"] + languages)

        dir_name, file_name = os.path.split(file_path)
        base_name = os.path.splitext(file_name)[0]
        output_path = os.path.join(dir_name, f"{base_name}.xlsx")

        df.to_excel(output_path, index=False)

        print(f"Success! Converted {len(rows)} translation units.")
        print(f"Saved to: {output_path}")

    except ET.ParseError as e:
        print(f"Error: Could not parse the TMX file: {e}")
    except Exception as e:
        print(f"An error occurred while processing the file: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a TMX translation memory file into an Excel file."
    )
    parser.add_argument(
        "-f",
        "--file",
        required=True,
        help="Path to the TMX file you want to convert",
    )

    args = parser.parse_args()
    tmx_to_excel(args.file)
