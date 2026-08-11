"""
reply_docx_comments.py
========================
Injects answers as threaded Word reply-comments into a .docx, without
touching the document body.

Background
----------
A Word "reply" comment is not just a new <w:comment> — Word links a reply to
its parent comment through matching w14:paraId / w15:paraIdParent values
spread across FOUR separate OOXML parts:

    word/comments.xml            the comment text itself (paragraph w14:paraId)
    word/commentsExtended.xml    w15:commentEx paraId + paraIdParent (the actual thread link)
    word/commentsIds.xml         w16cid:commentId paraId + durableId
    word/commentsExtensible.xml  w16cex:commentExtensible durableId + dateUtc

This script reads the TRUE per-comment w14:paraId out of comments.xml itself
for the parent linkage — some tool-generated docx files (seen from XTM
exports) write a placeholder paraId (e.g. "00000001") for every entry in
commentsExtended.xml/commentsIds.xml, which would make every reply thread
under the same (wrong) comment if trusted. Linking through comments.xml's own
paraId sidesteps that.

The document body (word/document.xml) is never touched — replies attach to
the existing comment anchors, they don't need new ones.

Usage
-----
    python reply_docx_comments.py <file.docx> <replies.json> \\
        --author "Uta Schulz" --initials "US" [--output out.docx] [--in-place]

replies.json: {"<comment_id>": "<reply text>", ...} — keys are the w:id
values from comments.xml (see extract_docx_comments.py's report).

By default writes "<stem>_replied.docx" next to the input and leaves the
original untouched. Pass --in-place to overwrite the input file (a .bak copy
is made first).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex"

THREADING_PARTS = [
    "word/commentsExtended.xml",
    "word/commentsIds.xml",
    "word/commentsExtensible.xml",
]


def qn(local: str, ns: str = W) -> str:
    return f"{{{ns}}}{local}"


def rand_hex(n: int) -> str:
    return "".join(random.choice("0123456789ABCDEF") for _ in range(n))


def build_reply_docx(
    docx_path: Path,
    replies: dict[str, str],
    author: str,
    initials: str,
    date: str,
) -> bytes:
    zin = zipfile.ZipFile(docx_path)
    names = set(zin.namelist())

    if "word/comments.xml" not in names:
        raise ValueError("This docx has no comments part (word/comments.xml) — nothing to reply to.")

    comments_tree = etree.fromstring(zin.read("word/comments.xml"))
    orig_para: dict[str, str] = {}
    for c in comments_tree.findall(qn("comment")):
        cid = c.get(qn("id"))
        p = c.find(qn("p"))
        orig_para[cid] = p.get(qn("paraId", W14))

    missing = [cid for cid in replies if cid not in orig_para]
    if missing:
        raise ValueError(f"Comment id(s) not found in {docx_path.name}: {missing}")

    has_threading = all(p in names for p in THREADING_PARTS)
    if not has_threading:
        print("WARNING: this docx has no reply-threading parts "
              "(commentsExtended/commentsIds/commentsExtensible.xml) — "
              "replies will be added as plain new comments, not nested under the original.")

    new_entries = []  # (new_id, new_paraId, parent_paraId, durable_id)
    max_id = max((int(cid) for cid in orig_para), default=-1)
    next_id = max_id + 1

    comments_root = comments_tree
    for cid in sorted(replies, key=int):
        text = replies[cid]
        new_id = str(next_id)
        next_id += 1
        new_paraId = rand_hex(8)
        durable_id = rand_hex(8)
        new_entries.append((new_id, new_paraId, orig_para[cid], durable_id))

        comment_el = etree.SubElement(comments_root, qn("comment"))
        comment_el.set(qn("id"), new_id)
        comment_el.set(qn("author"), author)
        comment_el.set(qn("date"), date)
        comment_el.set(qn("initials"), initials)

        p_el = etree.SubElement(comment_el, qn("p"))
        p_el.set(qn("paraId", W14), new_paraId)
        p_el.set(qn("textId", W14), rand_hex(8))

        pPr = etree.SubElement(p_el, qn("pPr"))
        pStyle = etree.SubElement(pPr, qn("pStyle"))
        pStyle.set(qn("val"), "afa")  # CommentText style, reused from the file's own originals

        if not has_threading:
            prefix_r = etree.SubElement(p_el, qn("r"))
            prefix_t = etree.SubElement(prefix_r, qn("t"))
            prefix_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            prefix_t.text = f"[Reply to comment {cid}] "
        r_el = etree.SubElement(p_el, qn("r"))
        t_el = etree.SubElement(r_el, qn("t"))
        t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t_el.text = text

    updated_parts = {"word/comments.xml": etree.tostring(
        comments_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )}

    if has_threading:
        ext_root = etree.fromstring(zin.read("word/commentsExtended.xml"))
        ids_root = etree.fromstring(zin.read("word/commentsIds.xml"))
        cex_root = etree.fromstring(zin.read("word/commentsExtensible.xml"))

        for new_id, new_paraId, parent_paraId, durable_id in new_entries:
            el = etree.SubElement(ext_root, qn("commentEx", W15))
            el.set(qn("paraId", W15), new_paraId)
            el.set(qn("paraIdParent", W15), parent_paraId)
            el.set(qn("done", W15), "0")

            el = etree.SubElement(ids_root, qn("commentId", W16CID))
            el.set(qn("paraId", W16CID), new_paraId)
            el.set(qn("durableId", W16CID), durable_id)

            el = etree.SubElement(cex_root, qn("commentExtensible", W16CEX))
            el.set(qn("durableId", W16CEX), durable_id)
            el.set(qn("dateUtc", W16CEX), date)

        updated_parts["word/commentsExtended.xml"] = etree.tostring(
            ext_root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        updated_parts["word/commentsIds.xml"] = etree.tostring(
            ids_root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        updated_parts["word/commentsExtensible.xml"] = etree.tostring(
            cex_root, xml_declaration=True, encoding="UTF-8", standalone=True
        )

    # Repackage: every part byte-identical except the ones we touched.
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = updated_parts.get(info.filename, zin.read(info.filename))
            zout.writestr(info, data)
    return buf.getvalue()


def validate(docx_bytes: bytes) -> None:
    """Zip integrity + reopen check. Raises if the produced file is broken."""
    import io
    buf = io.BytesIO(docx_bytes)
    bad = zipfile.ZipFile(buf).testzip()
    if bad:
        raise RuntimeError(f"Corrupt zip entry produced: {bad}")
    from docx import Document
    Document(io.BytesIO(docx_bytes))  # raises if python-docx can't open it


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx_path", type=Path)
    ap.add_argument("replies_json", type=Path)
    ap.add_argument("--author", required=True)
    ap.add_argument("--initials", required=True)
    ap.add_argument("--date", default=None, help="ISO8601 UTC, e.g. 2026-08-11T12:00:00Z. Defaults to now.")
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--in-place", action="store_true", help="Overwrite docx_path (keeps a .bak copy).")
    args = ap.parse_args()

    replies = json.loads(args.replies_json.read_text(encoding="utf-8"))
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = build_reply_docx(args.docx_path, replies, args.author, args.initials, date)
    validate(result)
    print(f"{len(replies)} repl(y/ies) injected and validated OK.")

    if args.in_place:
        backup = args.docx_path.with_suffix(args.docx_path.suffix + ".bak")
        shutil.copy2(args.docx_path, backup)
        args.docx_path.write_bytes(result)
        print(f"Overwrote {args.docx_path} (backup at {backup})")
    else:
        out_path = args.output or args.docx_path.with_name(f"{args.docx_path.stem}_replied.docx")
        out_path.write_bytes(result)
        print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
