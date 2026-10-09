#!/usr/bin/env python3
"""Swarm tests: parallel slices, overlap gate, queue merge, takeover + cross-review."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRCTL = ROOT / "scripts" / "pairctl.py"

FAKE_SEAT = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys, tempfile
from pathlib import Path
name = Path(sys.argv[0]).stem.lower()
args = sys.argv[1:]
if name == "codex":
    review = "read-only" in args
    wt = Path(args[args.index("-C") + 1]); prompt = args[-1]; seat = "codex"
else:
    wt = Path(os.getcwd()); prompt = args[args.index("-p") + 1]; seat = "lmstudio"
    review = "--permission-mode" not in args
if "CVM1 review" in prompt:
    print("looks fine\nREVIEW: PASS"); raise SystemExit(0)
m = re.search(r'python "([^"]*pairctl\.py)" show (\d+) --wire --repo "([^"]+)"', prompt)
if not m: raise SystemExit(4)
ctl, bid, main = m.groups()
wire = subprocess.run([sys.executable, ctl, "show", bid, "--wire", "--repo", main], text=True, capture_output=True).stdout
target = re.search(r"F\|([^\s|:]+)", wire).group(1)
bad = os.environ.get("FAKE_FAIL_SEAT") == seat
(wt / target).write_text("wrong\n" if bad else "paired\n", encoding="utf-8")
subprocess.run(["git", "-C", str(wt), "add", target], check=True)
if os.environ.get("FAKE_STRAY") == seat:
    (wt / "stray.txt").write_text("paired\n")
    subprocess.run(["git", "-C", str(wt), "add", "stray.txt"], check=True)
subprocess.run(["git", "-C", str(wt), "commit", "-qm", "fake " + seat], check=True)
sha = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
Path(path).write_text(json.dumps({"delta": ["wrote " + target], "commit": sha, "tests": [], "blockers": [], "uncertainties": [], "evidence": [target]}))
try:
    rc = subprocess.run([sys.executable, ctl, "report", bid, "--verdict", "pass", "--spec", path, "--repo", main, "--seat", seat]).returncode
finally:
    os.unlink(path)
raise SystemExit(rc)
'''

VERIFY = "import pathlib,sys\nsys.exit(1 if any('wrong' in p.read_text() for p in pathlib.Path('.').glob('*.txt')) else 0)\n"


class Models(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-model"}, {"id": "text-embedding-x"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class SwarmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); base = Path(self.tmp.name)
        self.repo = base / "repo"; self.bin = base / "bin"; home = base / "home"
        for p in (self.repo, self.bin, home, base / "pairing"):
            p.mkdir(exist_ok=True)
        self.server = HTTPServer(("127.0.0.1", 0), Models)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PAIRING_HOME=str(base / "pairing"))
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]
        self.env.pop("PAIRCTL_IMPLEMENTER_SEAT", None)
        (base / "pairing" / "config.json").write_text(json.dumps({
            "lmstudio_use_lms": False, "lmstudio_url": "http://127.0.0.1:%d" % self.server.server_port,
            "max_rounds": 1, "implementer_priority": ["codex"]}))
        for n in ("codex", "claude"):
            if os.name == "nt":
                (self.bin / (n + ".py")).write_text(FAKE_SEAT, encoding="utf-8")
                (self.bin / (n + ".CMD")).write_text('@echo off\r\n"%s" "%%~dp0%s.py" %%*\r\n' % (sys.executable, n), encoding="utf-8")
            else:
                exe = self.bin / n; exe.write_text(FAKE_SEAT, encoding="utf-8"); exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a), check=True, capture_output=True)
        g("init", "-q", "-b", "main"); g("config", "user.name", "T"); g("config", "user.email", "t@t.invalid")
        (self.repo / "a.txt").write_text("base\n"); (self.repo / "b.txt").write_text("base\n"); (self.repo / "verify.py").write_text(VERIFY)
        (self.repo / ".pairing.json").write_text(json.dumps({"verification": {"commands": ["%s verify.py" % sys.executable]}}))
        g("add", "."); g("commit", "-qm", "base")

    def tearDown(self):
        self.server.shutdown(); self.tmp.cleanup()

    def ctl(self, *args, expect=0, env=None):
        p = subprocess.run([sys.executable, str(PAIRCTL)] + [str(a) for a in args] + ["--repo", str(self.repo)],
                           env=env or self.env, text=True, capture_output=True, encoding="utf-8", errors="replace")
        logs = "".join(f.read_text(errors="replace") for f in (Path(self.env["PAIRING_HOME"]) / "logs").rglob("*.log"))[-1500:]
        self.assertEqual(p.returncode, expect, "%s\n%s\n%s\nLOGS:%s" % (args, p.stdout, p.stderr, logs))
        return p.stdout + p.stderr

    def spec(self, files, name="swarm.json"):
        briefs = [{"seat": seat, "goal": "write " + f, "scope": [f], "files": [f], "acceptance": [f + " contains paired"]}
                  for seat, f in files]
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps({"goal": "swarm", "briefs": briefs})); return path

    def queue(self):
        return json.loads(subprocess.run(["git", "-C", str(self.repo), "cat-file", "-p", "refs/pairing/queue:queue.json"],
                                         text=True, capture_output=True, check=True).stdout)["briefs"]

    def test_overlap_rejected(self):
        out = self.ctl("swarm", "--spec", self.spec([("codex", "src"), ("lmstudio", "src/x.py")]), expect=1)
        self.assertIn("overlap", out)

    def test_parallel_slices_audit_and_land(self):
        out = self.ctl("swarm", "t", "--spec", self.spec([("codex", "a.txt"), ("lmstudio", "b.txt")]))
        self.assertIn("fake-model", out)
        briefs = self.queue()
        self.assertEqual({b["state"] for b in briefs}, {"reported"})
        self.assertEqual({b["implementer"] for b in briefs}, {"codex", "lmstudio"})
        for b in briefs:
            spec = Path(self.tmp.name) / ("audit%s.json" % b["id"]); spec.write_text(json.dumps({"evidence": ["diff"], "tests": ["ok"]}))
            self.ctl("audit", b["id"], "--verdict", "pass", "--spec", spec, "--seat", "claude")
        out = self.ctl("swarm", "--land", briefs[0]["swarm"])
        self.assertIn("integration verification on main: PASS", out)
        self.assertEqual({b["state"] for b in self.queue()}, {"landed"})
        self.assertEqual((self.repo / "a.txt").read_text().strip(), "paired")
        self.assertEqual((self.repo / "b.txt").read_text().strip(), "paired")

    def test_out_of_scope_edit_blocks_slice(self):
        env = dict(self.env, FAKE_STRAY="lmstudio")
        out = self.ctl("swarm", "t", "--spec", self.spec([("codex", "a.txt"), ("lmstudio", "b.txt")]), expect=1, env=env)
        states = {b["implementer"]: b["state"] for b in self.queue()}
        self.assertEqual(states, {"codex": "reported", "lmstudio": "blocked"})
        ev = [b for b in self.queue() if b["implementer"] == "lmstudio"][0]["events"]
        self.assertIn("out of scope: stray.txt", json.dumps(ev))

    def test_seat_cannot_audit_or_swarm(self):
        env = dict(self.env, PAIRCTL_IMPLEMENTER_SEAT="codex")
        out = self.ctl("swarm", "--status", "1", expect=1, env=env)
        self.assertIn("reserved for the auditor", out)

    def test_failing_seat_takeover_needs_review(self):
        env = dict(self.env, FAKE_FAIL_SEAT="codex")
        out = self.ctl("swarm", "t", "--spec", self.spec([("codex", "a.txt"), ("lmstudio", "b.txt")]), expect=1, env=env)
        briefs = {b["implementer"]: b for b in self.queue()}
        self.assertEqual(briefs["codex"]["state"], "blocked")
        self.assertEqual(briefs["lmstudio"]["state"], "reported")
        self.assertIn("--takeover %s" % briefs["codex"]["id"], out)
        bid = briefs["codex"]["id"]
        self.ctl("swarm", "--takeover", bid)
        entry = [b for b in self.queue() if b["id"] == bid][0]
        self.assertEqual((entry["state"], entry["implementer"]), ("claimed", "claude"))
        wt = Path(entry["worktree"])
        (wt / "a.txt").write_text("paired\n")
        subprocess.run(["git", "-C", str(wt), "commit", "-qam", "claude fix"], check=True, capture_output=True)
        rep = Path(self.tmp.name) / "rep.json"; rep.write_text(json.dumps({"delta": ["fixed a.txt"]}))
        self.ctl("report", bid, "--verdict", "pass", "--spec", rep, "--seat", "claude")
        aud = Path(self.tmp.name) / "aud.json"; aud.write_text(json.dumps({"evidence": ["diff"]}))
        self.assertIn("run verify", self.ctl("audit", bid, "--verdict", "pass", "--spec", aud, "--seat", "claude", expect=1))
        self.ctl("verify", bid)
        self.assertIn("cross-seat review", self.ctl("audit", bid, "--verdict", "pass", "--spec", aud, "--seat", "claude", expect=1))
        self.assertIn("review verdict: PASS", self.ctl("swarm", "--review", bid))
        self.ctl("audit", bid, "--verdict", "pass", "--spec", aud, "--seat", "claude")
        self.assertEqual([b for b in self.queue() if b["id"] == bid][0]["state"], "audit-passed")


if __name__ == "__main__":
    unittest.main()
