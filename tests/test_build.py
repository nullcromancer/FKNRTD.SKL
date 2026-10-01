"""Standard-library tests: python -m unittest discover -s tests"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402

EXAMPLE = ROOT / "examples" / "questions.example.json"
SPEC_RE = re.compile(r'<script id="spec" type="application/json">(.*?)</script>', re.S)


def spec():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class Validate(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(build.validate(spec()), [])

    def test_catches_problems(self):
        s = spec()
        s["questions"][0]["section"] = "Z"
        s["questions"][1]["id"] = "A1"
        s["questions"][2]["freeText"] = ""
        s["questions"][0]["options"][1]["recommended"] = True
        errs = " | ".join(build.validate(s))
        for needle in ("unknown section", "duplicate question id", "free-text", "recommended options"):
            self.assertIn(needle, errs)

    def test_recommended_needs_reason(self):
        s = spec()
        s["questions"][0]["recommendation"] = ""
        self.assertTrue(any("no 'recommendation'" in e for e in build.validate(s)))


class Build(unittest.TestCase):
    def test_build_embeds_spec_and_escapes(self):
        s = spec()
        s["title"] = "T </script><!-- x"
        s["questions"][0]["text"] = "has </script> and \\ backslash"
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "q.json"
            sp.write_text(json.dumps(s), encoding="utf-8")
            out = Path(d) / "inquisitor"
            html = build.build(sp, out).read_text(encoding="utf-8")
            self.assertTrue((out / "questions.json").exists())
            blob = SPEC_RE.search(html).group(1)
            self.assertNotIn("</", blob)
            back = json.loads(blob)
            self.assertNotIn("<!--", blob)
            self.assertEqual(back["title"], s["title"])
            self.assertEqual(back["questions"][0]["text"], s["questions"][0]["text"])
            self.assertEqual(back["title"], s["title"])
            self.assertNotIn("<!--", blob)
            self.assertIn("&lt;/script>", html.split("<title>")[1].split("</title>")[0])

    def test_status_reports_open_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "answers.md").write_text(
                "Status: **IN PROGRESS** · answered 1/3 · deferred 0 · unanswered 2\n"
                "- A1 [unanswered, blocker] Which engine?\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), "--status", d],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0)
            self.assertIn("open blocker A1", r.stdout)


class Template(unittest.TestCase):
    def test_script_parses_and_markdown_roundtrips(self):
        try:
            subprocess.run(["node", "--version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "q.json"
            sp.write_text(json.dumps(spec()), encoding="utf-8")
            html = build.build(sp, Path(d) / "inquisitor").read_text(encoding="utf-8")
            js = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
            js = js.split("/* ---------- boot ---------- */")[0].replace('"use strict";', "")
            spec_json = SPEC_RE.search(html).group(1)
            harness = (
                "const document={getElementById:()=>({textContent:%s})};const localStorage={};"
                "const window={};\n" % json.dumps(spec_json) + js +
                "\nstate.answers.A1={sel:[0],other:'x --> y',note:'n\\nm',deferred:false,bulk:true};"
                "state.answers.A2={sel:[0,1],other:'',note:'',deferred:false,bulk:false};"
                "const md=buildMd(false);const s=parseState(md);"
                "if(JSON.stringify(s)!==JSON.stringify(state))throw new Error('roundtrip');"
                "if(!/Matches recommendation:\\*\\* no/.test(md))throw new Error('rec flag');"
                "if(!/accepted in bulk/.test(md))throw new Error('bulk');console.log('OK');"
            )
            f = Path(d) / "h.js"
            f.write_text(harness, encoding="utf-8")
            r = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.stdout.strip(), "OK", r.stderr)


if __name__ == "__main__":
    unittest.main()
