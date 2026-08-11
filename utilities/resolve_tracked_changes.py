"""
resolve_tracked_changes.py
============================
Lists (or resolves) Word tracked changes (insertions/deletions) in a .docx.

Two subcommands:

  list      Extract every tracked change into JSON, with the surrounding
            paragraph reconstructed both before and after the edit, so an
            agent/human can review each one against a source document.

  resolve   Accept or reject tracked changes by their w:id, producing a
            clean (or partially clean) docx. Defaults to accepting
            everything except the ids you list with --reject.

Background
----------
A tracked insertion is a <w:ins> wrapping normal <w:r>/<w:t> runs; a tracked
deletion is a <w:del> wrapping <w:r>/<w:delText> runs (deleted text uses
delText, not t, per the OOXML spec). Accepting an insertion means unwrapping
it (keep the content, drop the <w:ins> tag); rejecting one means deleting the
whole subtree. Accepting a deletion means deleting the whole subtree;
rejecting one means unwrapping it and renaming delText -> t so the text
becomes normal again.

A paragraph mark can *itself* be tracked as inserted or deleted — this shows
up as <w:ins>/<w:del> inside <w:pPr>/<w:rPr> rather than wrapping a run, and
means "this paragraph break is new" / "this paragraph break is proposed for
removal" (e.g. from splitting or merging paragraphs). This script accepts
paragraph-mark insertions (strip the marker, keep the break) and accepts
paragraph-mark deletions only via rejection (strip the marker, keep the
break — merging paragraphs on accept isn't implemented); `list` reports
these as `paragraph_mark_insertion`/`paragraph_mark_deletion`, `resolve`
raises a clear error if you try to do the unsupported direction.

Tables have their own tracked-change vocabulary that lives OUTSIDE
<w:body>'s direct <w:p> children — a whole row being deleted shows up as
<w:del> inside <w:trPr> (not wrapping a run at all), and column/cell
formatting changes show up as <w:tblPrChange>/<w:tcPrChange>/<w:trPrChange>/
<w:tblGridChange>, which store the OLD properties as a child of the *Pr
element that already carries the new ones. A plain `body.findall('w:p')`
scan never sees any of this, since table paragraphs are nested inside
tbl > tr > tc, not direct children of body — first-cut versions of this
script missed a whole artifact table this way, which is exactly the kind of
thing worth catching. `list` walks tables explicitly; `resolve` removes a
deleted row entirely (dropping the whole `<w:tbl>` too if that empties it)
and drops property-change bookkeeping on accept (rejecting a property change
— restoring the old values — isn't implemented).

Usage
-----
    python resolve_tracked_changes.py list <file.docx> [--out-dir DIR]
    python resolve_tracked_changes.py resolve <file.docx> \\
        [--reject <id,id,...>] [--output out.docx] [--in-place]
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qn(local: str) -> str:
    return f"{{{W}}}{local}"


def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("t")))


def del_text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("delText")))


# ---------------------------------------------------------------- list ----

PROPERTY_CHANGE_TAGS = ("tblPrChange", "tcPrChange", "trPrChange", "tblGridChange", "pPrChange", "rPrChange")


def _original_text(p):
    parts = []
    for el in p.iter():
        tag = etree.QName(el).localname
        if tag == "t":
            cur, in_ins = el, False
            while cur is not None:
                if etree.QName(cur).localname == "ins":
                    in_ins = True
                    break
                cur = cur.getparent()
            if not in_ins:
                parts.append(el.text or "")
        elif tag == "delText":
            parts.append(el.text or "")
    return "".join(parts)


def _revised_text(p):
    parts = []
    for el in p.iter():
        tag = etree.QName(el).localname
        if tag == "t":
            cur, in_del = el, False
            while cur is not None:
                if etree.QName(cur).localname == "del":
                    in_del = True
                    break
                cur = cur.getparent()
            if not in_del:
                parts.append(el.text or "")
    return "".join(parts)


def _paragraph_edits(p, location: str) -> list[dict]:
    """ins/del content changes + a tracked paragraph-mark change, for one <w:p>."""
    orig_ctx = _original_text(p)
    rev_ctx = _revised_text(p)

    pPr = p.find(qn("pPr"))
    para_mark = None  # (kind, id, author, date)
    if pPr is not None:
        rPr = pPr.find(qn("rPr"))
        if rPr is not None:
            for kind in ("ins", "del"):
                el = rPr.find(qn(kind))
                if el is not None:
                    para_mark = (kind, el.get(qn("id")), el.get(qn("author")), el.get(qn("date")))
                    break

    seq = [(etree.QName(c).localname, c) for c in list(p)
           if etree.QName(c).localname in ("ins", "del")]

    edits = []
    j = 0
    while j < len(seq):
        kind, el = seq[j]
        author, date = el.get(qn("author")), el.get(qn("date"))
        wid = el.get(qn("id"))
        paired = (
            j + 1 < len(seq)
            and seq[j + 1][0] != kind
            and (
                (kind == "del" and text_of(seq[j + 1][1]))
                or (kind == "ins" and del_text_of(seq[j + 1][1]))
            )
        )
        if paired:
            other_kind, other_el = seq[j + 1]
            old_t = del_text_of(el) if kind == "del" else del_text_of(other_el)
            new_t = text_of(other_el) if kind == "del" else text_of(el)
            edits.append({
                "ids": [wid, other_el.get(qn("id"))],
                "location": location,
                "type": "replacement",
                "old_text": old_t,
                "new_text": new_t,
                "author": author,
                "date": date,
                "paragraph_original": orig_ctx,
                "paragraph_revised": rev_ctx,
            })
            j += 2
            continue
        edits.append({
            "ids": [wid],
            "location": location,
            "type": "insertion" if kind == "ins" else "deletion",
            "old_text": "" if kind == "ins" else del_text_of(el),
            "new_text": text_of(el) if kind == "ins" else "",
            "author": author,
            "date": date,
            "paragraph_original": orig_ctx,
            "paragraph_revised": rev_ctx,
        })
        j += 1

    if para_mark is not None:
        kind, wid, author, date = para_mark
        edits.append({
            "ids": [wid],
            "location": location,
            "type": f"paragraph_mark_{'insertion' if kind == 'ins' else 'deletion'}",
            "old_text": None,
            "new_text": None,
            "author": author,
            "date": date,
            "paragraph_original": orig_ctx,
            "paragraph_revised": rev_ctx,
        })

    return edits


def _cell_text(tc) -> str:
    return " ".join(_revised_text(p) or _original_text(p) for p in tc.findall(qn("p"))).strip()


def build_list_report(document_xml: bytes) -> list[dict]:
    """Walks the WHOLE body — including table rows/cells, which a plain
    body.findall('w:p') misses entirely since they're nested several levels
    deep (body > tbl > tr > tc > p). Missing those means missing whole-row
    deletions and any table-formatting tracked changes, which is exactly the
    kind of thing worth catching (a stray front-matter table has shown up in
    at least one real Issue Resolution round)."""
    tree = etree.fromstring(document_xml)
    body = tree.find(qn("body"))

    edits = []
    p_idx = 0
    tbl_idx = 0
    for child in body:
        tag = etree.QName(child).localname
        if tag == "p":
            edits.extend(_paragraph_edits(child, f"paragraph {p_idx}"))
            p_idx += 1
        elif tag == "tbl":
            for tag_name in ("tblPrChange", "tblGridChange"):
                el = child.find(f".//{qn(tag_name)}")
                if el is not None:
                    edits.append({
                        "ids": [el.get(qn("id"))], "location": f"table {tbl_idx}",
                        "type": f"property_change:{tag_name}", "old_text": None, "new_text": None,
                        "author": None, "date": None,
                        "paragraph_original": None, "paragraph_revised": None,
                    })
            for tr_idx, tr in enumerate(child.findall(qn("tr"))):
                loc = f"table {tbl_idx} row {tr_idx}"
                trPr = tr.find(qn("trPr"))
                row_del = trPr.find(qn("del")) if trPr is not None else None
                cells_text = " | ".join(_cell_text(tc) for tc in tr.findall(qn("tc")))
                if row_del is not None:
                    edits.append({
                        "ids": [row_del.get(qn("id"))], "location": loc,
                        "type": "row_deletion", "old_text": cells_text, "new_text": None,
                        "author": row_del.get(qn("author")), "date": row_del.get(qn("date")),
                        "paragraph_original": cells_text, "paragraph_revised": "(entire row removed)",
                    })
                for tc_idx, tc in enumerate(tr.findall(qn("tc"))):
                    tcPrChange = tc.find(f"{qn('tcPr')}/{qn('tcPrChange')}")
                    if tcPrChange is not None:
                        edits.append({
                            "ids": [tcPrChange.get(qn("id"))], "location": f"{loc} cell {tc_idx}",
                            "type": "property_change:tcPrChange", "old_text": None, "new_text": None,
                            "author": None, "date": None,
                            "paragraph_original": None, "paragraph_revised": None,
                        })
                    for cp_idx, p in enumerate(tc.findall(qn("p"))):
                        edits.extend(_paragraph_edits(p, f"{loc} cell {tc_idx} paragraph {cp_idx}"))
            tbl_idx += 1

    return edits


def cmd_list(args):
    z = zipfile.ZipFile(args.docx_path)
    edits = build_list_report(z.read("word/document.xml"))

    out_dir = args.out_dir or args.docx_path.with_name(f"{args.docx_path.stem}_tracked_changes")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "tracked_changes.json"
    report_path.write_text(json.dumps(edits, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(edits)} tracked change(s) found.")
    print(f"Report: {report_path}")


# ------------------------------------------------------------- resolve ----

def _unwrap(el, parent):
    """Replace el with its own children, in place."""
    idx = list(parent).index(el)
    for child in list(el):
        el.remove(child)
        parent.insert(idx, child)
        idx += 1
    parent.remove(el)


def resolve_document(document_xml: bytes, reject_ids: set[str]) -> bytes:
    tree = etree.fromstring(document_xml)

    # --- pass 1: whole-row deletions (<w:del> directly inside <w:trPr>) ---
    # Accepting removes the entire <w:tr> (and everything in it — cell
    # paragraph-mark changes, tcPrChange, etc. all go with it, since they're
    # descendants). Rejecting just strips the marker so the row stays.
    for trPr in list(tree.iter(qn("trPr"))):
        del_el = trPr.find(qn("del"))
        if del_el is None:
            continue
        wid = del_el.get(qn("id"))
        tr = trPr.getparent()
        if wid in reject_ids:
            trPr.remove(del_el)
        else:
            tbl = tr.getparent()
            tbl.remove(tr)
            if tbl.find(qn("tr")) is None:  # no rows left — drop the shell table
                tbl.getparent().remove(tbl)

    # --- pass 2: remaining ins/del, collected fresh after pass 1's removals ---
    # (mutating a tree mid-iter() skips siblings, so collect first, then act)
    targets = [el for el in tree.iter() if etree.QName(el).localname in ("ins", "del")]

    for el in targets:
        if el.getparent() is None:
            continue  # already removed as part of a deleted row in pass 1
        tag = etree.QName(el).localname
        wid = el.get(qn("id"))
        parent = el.getparent()
        reject = wid in reject_ids

        is_para_mark = (
            etree.QName(parent).localname == "rPr"
            and parent.getparent() is not None
            and etree.QName(parent.getparent()).localname == "pPr"
        )

        if is_para_mark:
            if tag == "ins":
                if reject:
                    raise ValueError(
                        f"Cannot reject paragraph-mark insertion id={wid}: "
                        "would require merging two paragraphs, not supported."
                    )
                parent.remove(el)  # accept: drop the tracking marker, keep the break
            else:  # del: paragraph-mark deletion == proposal to merge with next paragraph
                if not reject:
                    raise ValueError(
                        f"Cannot accept paragraph-mark deletion id={wid}: "
                        "would require merging two paragraphs, not supported."
                    )
                parent.remove(el)  # reject: drop the marker, keep the break (paragraph stays separate)
            continue

        if tag == "ins":
            if reject:
                parent.remove(el)
            else:
                _unwrap(el, parent)
        else:  # del
            if reject:
                for delText in el.iter(qn("delText")):
                    delText.tag = qn("t")
                _unwrap(el, parent)
            else:
                parent.remove(el)

    # --- pass 3: leftover property-change bookkeeping (tblPrChange etc.) ---
    # These store the OLD property values as a child of the *Pr element that
    # already carries the new/active values — so on accept there's nothing
    # to apply, just drop the historical record. Rejecting (restoring the old
    # values) isn't implemented.
    for tag in PROPERTY_CHANGE_TAGS:
        for el in list(tree.iter(qn(tag))):
            wid = el.get(qn("id"))
            if wid in reject_ids:
                raise ValueError(f"Cannot reject property change id={wid} ({tag}): not supported.")
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)


def validate(docx_bytes: bytes) -> None:
    buf = io.BytesIO(docx_bytes)
    bad = zipfile.ZipFile(buf).testzip()
    if bad:
        raise RuntimeError(f"Corrupt zip entry produced: {bad}")
    from docx import Document
    Document(io.BytesIO(docx_bytes))


def cmd_resolve(args):
    reject_ids = set(args.reject.split(",")) if args.reject else set()
    reject_ids.discard("")

    zin = zipfile.ZipFile(args.docx_path)
    new_doc_xml = resolve_document(zin.read("word/document.xml"), reject_ids)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = new_doc_xml if info.filename == "word/document.xml" else zin.read(info.filename)
            zout.writestr(info, data)
    result = buf.getvalue()
    validate(result)

    print(f"Resolved. Rejected id(s): {sorted(reject_ids) or 'none'} — everything else accepted.")

    if args.in_place:
        backup = args.docx_path.with_suffix(args.docx_path.suffix + ".bak")
        shutil.copy2(args.docx_path, backup)
        args.docx_path.write_bytes(result)
        print(f"Overwrote {args.docx_path} (backup at {backup})")
    else:
        out_path = args.output or args.docx_path.with_name(f"{args.docx_path.stem}_resolved.docx")
        out_path.write_bytes(result)
        print(f"Written: {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("docx_path", type=Path)
    p_list.add_argument("--out-dir", type=Path, default=None)
    p_list.set_defaults(func=cmd_list)

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("docx_path", type=Path)
    p_resolve.add_argument("--reject", default="", help="Comma-separated w:id values to reject. All others are accepted.")
    p_resolve.add_argument("--output", type=Path, default=None)
    p_resolve.add_argument("--in-place", action="store_true")
    p_resolve.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
