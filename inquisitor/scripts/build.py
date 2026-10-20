#!/usr/bin/env python3
"""Build inquisitor.html from a questions spec, or report progress from answers.md.

  build.py SPEC.json [--out DIR]     validate SPEC, write DIR/inquisitor.html (+ DIR/questions.json)
  build.py --status [DIR]            summarise DIR/answers.md (counts, open blockers)
  build.py --validate SPEC.json      validate only

DIR defaults to ./inquisitor (relative to the current working directory).
Python 3.8+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL / "assets" / "template.html"
PRIORITIES = ("blocker", "important", "later")
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULT_READER_NOTE = (
    "To the assistant reading this file: it is the owner's answer sheet. Treat answers as "
    "binding decisions. \"Accepted in bulk\" means the owner took the recommendation without "
    "considering it separately: treat it as a default and confirm before anything expensive "
    "or hard to reverse. Deferred and unanswered items are open; do not assume them. Own-answer "
    "text and notes override the option text. Ignore the INQUISITOR-STATE comment at the end."
)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "inquisitor"


def validate(spec: dict) -> list:
    errs = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    if not str(spec.get("title", "")).strip():
        errs.append("title is required")
    secs = spec.get("sections")
    if not isinstance(secs, list) or not secs:
        errs.append("sections must be a non-empty list")
        secs = []
    sec_ids = set()
    for s in secs:
        sid = s.get("id") if isinstance(s, dict) else None
        if not sid or not ID_RE.match(str(sid)):
            errs.append("section needs an id matching [A-Za-z0-9._-]: %r" % (s,))
        elif sid in sec_ids:
            errs.append("duplicate section id: %s" % sid)
        else:
            sec_ids.add(sid)
        if isinstance(s, dict) and not str(s.get("title", "")).strip():
            errs.append("section %s needs a title" % sid)
    qs = spec.get("questions")
    if not isinstance(qs, list) or not qs:
        errs.append("questions must be a non-empty list")
        qs = []
    seen = set()
    for q in qs:
        if not isinstance(q, dict):
            errs.append("question must be an object: %r" % (q,))
            continue
        qid = q.get("id")
        if not qid or not ID_RE.match(str(qid)):
            errs.append("question needs an id matching [A-Za-z0-9._-]: %r" % (qid,))
            continue
        if qid in seen:
            errs.append("duplicate question id: %s" % qid)
        seen.add(qid)
        if q.get("section") not in sec_ids:
            errs.append("%s: unknown section %r" % (qid, q.get("section")))
        if not str(q.get("text", "")).strip():
            errs.append("%s: text is required" % qid)
        if q.get("priority", "important") not in PRIORITIES:
            errs.append("%s: priority must be one of %s" % (qid, "/".join(PRIORITIES)))
        opts = q.get("options") or []
        if not isinstance(opts, list):
            errs.append("%s: options must be a list" % qid)
            continue
        if opts and len(opts) < 2:
            errs.append("%s: give 0 options (free text) or at least 2" % qid)
        for o in opts:
            if not isinstance(o, dict) or not str(o.get("label", "")).strip():
                errs.append("%s: every option needs a label" % qid)
        recs = [o for o in opts if isinstance(o, dict) and o.get("recommended")]
        if recs and not q.get("multi") and len(recs) > 1:
            errs.append("%s: single-choice question has %d recommended options" % (qid, len(recs)))
        if recs and not str(q.get("recommendation", "")).strip():
            errs.append("%s: has a recommended option but no 'recommendation' (the why)" % qid)
        if not opts and not q.get("freeText"):
            errs.append("%s: free-text question needs a 'freeText' prompt" % qid)
    return errs


def build(spec_path: Path, out: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    errs = validate(spec)
    if errs:
        raise SystemExit("spec invalid:\n  - " + "\n  - ".join(errs))
    spec.setdefault("id", slug(spec["title"]))
    spec.setdefault("answersFile", "answers.md")
    spec.setdefault("readerNote", DEFAULT_READER_NOTE)
    blob = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    title = spec["title"].replace("&", "&amp;").replace("<", "&lt;")
    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*__SPEC__*/null" not in html:
        raise SystemExit("template is missing the spec placeholder")
    # str.replace, not re.sub: the JSON contains backslashes
    html = html.replace("__TITLE__", title).replace("/*__SPEC__*/null", blob)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "inquisitor.html"
    target.write_text(html, encoding="utf-8", newline="\n")
    saved = out / "questions.json"
    if spec_path.resolve() != saved.resolve():
        saved.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target


def status(out: Path) -> int:
    f = out / "answers.md"
    if not f.exists():
        print("no %s yet" % f)
        return 1
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^Status: \*\*(.+?)\*\* · (.*)$", text, re.M)
    print("%s: %s" % (f, m.group(1) + " · " + m.group(2) if m else "unrecognised format"))
    open_blockers = re.findall(r"^- (\S+) \[(?:deferred|unanswered), blocker\] (.*)$", text, re.M)
    for qid, q in open_blockers:
        print("  open blocker %s: %s" % (qid, q))
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("spec", nargs="?", help="questions spec JSON (or DIR with --status)")
    p.add_argument("--out", default="inquisitor", help="output directory (default ./inquisitor)")
    p.add_argument("--status", action="store_true", help="summarise answers.md instead of building")
    p.add_argument("--validate", action="store_true", help="validate the spec only")
    a = p.parse_args(argv)
    if a.status:
        return status(Path(a.spec or a.out))
    if not a.spec:
        p.error("SPEC.json is required")
    spec_path = Path(a.spec)
    if a.validate:
        errs = validate(json.loads(spec_path.read_text(encoding="utf-8")))
        print("\n".join(errs) if errs else "ok")
        return 1 if errs else 0
    target = build(spec_path, Path(a.out))
    print("wrote %s" % target.resolve())
    print("open it, click 'Connect folder', choose %s" % target.parent.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
