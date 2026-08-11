"""
extract_docx_comments.py
=========================
Extracts every comment from a Word .docx, together with what it's anchored
to, and writes a structured JSON report plus any images involved.

Background
----------
python-docx does not expose comments at all, so this reads the raw OOXML
parts directly (word/document.xml, word/comments.xml and their .rels).

Two things make patent QA comments hard to read from python-docx or a plain
text dump:

1. The reviewer's comment often has a screenshot of the SOURCE PDF pasted
   into the comment itself (so the comment text alone reads like
   "Missing translation, ' ', pdf6." — meaningless without the picture).
2. The comment is sometimes anchored on a drawing (an inline chemical
   structure image) rather than on text, so the "anchored text" is empty and
   you have to go find the actual picture in the document body to see what's
   being flagged.

This script resolves both: it pulls out every image pasted into a comment
(comment_images) and, separately, every image the comment's range covers in
the document body (anchor_images) — writing both to an output folder so an
agent (or a human) can just look at them.

Usage
-----
    python extract_docx_comments.py <file.docx> [--out-dir DIR]

Writes DIR/comments.json and DIR/images/*.png (DIR defaults to
"<docx stem>_comments" next to the input file).
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"w": W, "w14": W14, "r": R, "a": A}


def qn(local: str, ns: str = W) -> str:
    return f"{{{ns}}}{local}"


def load_rels(z: zipfile.ZipFile, part_path: str) -> dict[str, str]:
    """rId -> target path (relative to the part's directory), for a given part."""
    rels_path = f"{Path(part_path).parent}/_rels/{Path(part_path).name}.rels"
    if rels_path not in z.namelist():
        return {}
    root = etree.fromstring(z.read(rels_path))
    base = Path(part_path).parent
    out = {}
    for rel in root.findall(f"{{{RELS}}}Relationship"):
        target = rel.get("Target")
        rid = rel.get("Id")
        out[rid] = str((base / target).as_posix()) if not target.startswith("http") else target
    return out


def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("t")))


def extract_comments(docx_path: Path) -> tuple[list[dict], dict[str, bytes]]:
    """Returns (comments, images) where images maps output-filename -> bytes."""
    z = zipfile.ZipFile(docx_path)
    comments_xml = etree.fromstring(z.read("word/comments.xml"))
    document_xml = etree.fromstring(z.read("word/document.xml"))

    doc_rels = load_rels(z, "word/document.xml")
    comments_rels = load_rels(z, "word/comments.xml")

    images: dict[str, bytes] = {}

    # ---- comment text + any screenshots pasted into the comment itself ----
    comment_info: dict[str, dict] = {}
    for c in comments_xml.findall(qn("comment"), NS):
        cid = c.get(qn("id"))
        comment_info[cid] = {
            "id": cid,
            "author": c.get(qn("author")),
            "date": c.get(qn("date")),
            "comment_text": text_of(c),
            "comment_images": [],
        }
        for i, blip in enumerate(c.findall(f".//{qn('blip', A)}"), start=1):
            rid = blip.get(qn("embed", R))
            target = comments_rels.get(rid)
            if target and target in z.namelist():
                fname = f"comment_{cid}_img{i}{Path(target).suffix}"
                images[fname] = z.read(target)
                comment_info[cid]["comment_images"].append(fname)

    # ---- walk the document body in order, tracking active comment ranges ----
    body = document_xml.find(qn("body"))
    active: dict[str, dict] = {}
    para_idx = -1
    img_counters: dict[str, int] = {}

    for el in body.iter():
        tag = etree.QName(el).localname
        if tag == "p":
            para_idx += 1
        elif tag == "commentRangeStart":
            cid = el.get(qn("id"))
            active[cid] = {"text_parts": [], "start_para": para_idx, "images": []}
        elif tag == "commentRangeEnd":
            cid = el.get(qn("id"))
            if cid in active:
                info = active.pop(cid)
                info["end_para"] = para_idx
                if cid in comment_info:
                    comment_info[cid]["anchor_start_para"] = info["start_para"]
                    comment_info[cid]["anchor_end_para"] = info["end_para"]
                    comment_info[cid]["anchor_text"] = "".join(info["text_parts"])
                    comment_info[cid]["anchor_images"] = info["images"]
        elif tag == "t":
            for info in active.values():
                info["text_parts"].append(el.text or "")
        elif tag == "blip":
            rid = el.get(qn("embed", R))
            target = doc_rels.get(rid)
            if not target or target not in z.namelist():
                continue
            for cid, info in active.items():
                img_counters[cid] = img_counters.get(cid, 0) + 1
                fname = f"anchor_{cid}_img{img_counters[cid]}{Path(target).suffix}"
                images[fname] = z.read(target)
                info["images"].append(fname)

    # ---- full paragraph text, for context, indexed by paragraph number ----
    paragraphs = body.findall(qn("p"))
    para_text = [text_of(p) for p in paragraphs]

    results = []
    for cid in sorted(comment_info, key=int):
        info = comment_info[cid]
        start = info.get("anchor_start_para")
        end = info.get("anchor_end_para")
        if start is not None:
            info["anchor_paragraph_text"] = " ".join(
                para_text[i] for i in range(start, min(end, len(para_text) - 1) + 1)
            )
        else:
            info["anchor_text"] = ""
            info["anchor_images"] = []
            info["anchor_paragraph_text"] = "(comment range not found in document body)"
        results.append(info)

    return results, images


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("docx_path", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or args.docx_path.with_name(f"{args.docx_path.stem}_comments")
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "images"
    img_dir.mkdir(exist_ok=True)

    comments, images = extract_comments(args.docx_path)

    for fname, data in images.items():
        (img_dir / fname).write_bytes(data)

    report_path = out_dir / "comments.json"
    report_path.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(comments)} comment(s) found.")
    print(f"Report: {report_path}")
    print(f"Images: {img_dir} ({len(images)} file(s))")


if __name__ == "__main__":
    main()
