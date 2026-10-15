#!/usr/bin/env python3
"""Strata seat: the configuration is read live from the Strata install, and dispatch goes through strata_agent.py."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRCTL = ROOT / "scripts" / "pairctl.py"

# Stands in for C:\DEV\GIT\Strata\strata_agent.py: implements the brief like a seat would.
FAKE_AGENT = r'''import json, os, re, subprocess, sys, tempfile
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_AGENT_LOG"])
log.write_text(json.dumps({"args": args, "cwd": os.getcwd(), "seat": os.environ.get("PAIRCTL_IMPLEMENTER_SEAT")}))
prompt = args[args.index("-p") + 1]; wt = Path(os.getcwd())
m = re.search(r'python "([^"]*pairctl\.py)" show (\d+) --wire --repo "([^"]+)"', prompt)
ctl, bid, repo = m.groups()
(wt / "a.txt").write_text("paired\n")
subprocess.run(["git", "-C", str(wt), "commit", "-qam", "strata"], check=True)
sha = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
Path(path).write_text(json.dumps({"delta": ["a.txt"], "commit": sha, "tests": [], "blockers": [], "uncertainties": [], "evidence": ["a.txt"]}))
raise SystemExit(subprocess.run([sys.executable, ctl, "report", bid, "--verdict", "pass", "--spec", path, "--repo", repo, "--seat", "strata"]).returncode)
'''


class Health(BaseHTTPRequestHandler):
    model = "m-a"

    def do_GET(self):
        body = json.dumps({"loaded": True, "model": Health.model, "max_context": 131072}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class StrataSeatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); base = Path(self.tmp.name)
        self.home = base / "Strata"; self.repo = base / "repo"; self.bin = base / "bin"
        for p in (self.home, self.repo, self.bin, base / "pairing", base / "u"):
            p.mkdir()
        self.server = HTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        for name in ("engine.exe", "w-a.gguf", "w-b.gguf"):
            (self.home / name).write_text("x")
        for name in ("pack-a", "pack-b"):
            (self.home / name).mkdir()
        self.write_config("a")
        self.write_config("b")
        self.point_launcher_at("a")
        (self.home / "strata_agent.py").write_text(FAKE_AGENT, encoding="utf-8")
        claude = self.bin / ("claude.CMD" if os.name == "nt" else "claude")
        claude.write_text("@echo off\r\n" if os.name == "nt" else "#!/bin/sh\n"); claude.chmod(0o755)
        self.env = dict(os.environ, HOME=str(base / "u"), USERPROFILE=str(base / "u"), PAIRING_HOME=str(base / "pairing"),
                        FAKE_AGENT_LOG=str(base / "agent.json"))
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]
        self.env.pop("PAIRCTL_IMPLEMENTER_SEAT", None)
        (base / "pairing" / "config.json").write_text(json.dumps({"strata_home": str(self.home), "max_rounds": 1}))
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a), check=True, capture_output=True)
        g("init", "-q", "-b", "main"); g("config", "user.name", "T"); g("config", "user.email", "t@t.invalid")
        (self.repo / "a.txt").write_text("base\n"); g("add", "."); g("commit", "-qm", "base")

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def write_config(self, tag):
        h = self.home
        conf = {"exe": str(h / "engine.exe"), "model_name": "m-" + tag, "port": self.server.server_port, "backend": "hip",
                "reasoning_effort": "medium",
                "args": ["--pack", str(h / ("pack-" + tag)), "--native", str(h / ("w-%s.gguf" % tag)),
                         "--expert-cache", "17195", "--max-context", "131072"]}
        (h / ("strata-%s.json" % tag)).write_text(json.dumps(conf))
        (h / ("run-%s.bat" % tag)).write_text('"python.exe" "server.py" "--engine" "strata" "--config" "%s" "--port" "%d"\r\n'
                                             % (h / ("strata-%s.json" % tag), self.server.server_port))

    def point_launcher_at(self, tag):
        (self.home / "strata-up.ps1").write_text("param(\n  [string]$StartScript = '%s',\n  [int]$Port = %d\n)\n"
                                                 % (self.home / ("run-%s.bat" % tag), self.server.server_port))

    def ctl(self, *args, expect=0):
        p = subprocess.run([sys.executable, str(PAIRCTL)] + [str(a) for a in args], env=self.env, text=True,
                           capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, expect, "%s\n%s\n%s" % (args, p.stdout, p.stderr))
        return p.stdout + p.stderr

    def live(self):
        return json.loads(self.ctl("strata", "--json"))

    def test_reads_the_installed_configuration(self):
        live = self.live()
        self.assertEqual((live["model_name"], live["weights"], live["pack"], live["max_context"], live["expert_cache"]),
                         ("m-a", str(self.home / "w-a.gguf"), str(self.home / "pack-a"), "131072", "17195"))
        self.assertEqual(live["config"], str(self.home / "strata-a.json"))
        self.assertEqual(live["running"]["model"], "m-a")
        self.assertEqual(live["problems"], [])

    def test_follows_a_changed_install_without_any_conspirator_change(self):
        self.point_launcher_at("b"); Health.model = "m-b"
        try:
            self.assertEqual(self.live()["model_name"], "m-b")
        finally:
            Health.model = "m-a"

    def test_wrong_model_running_and_missing_files_are_problems(self):
        Health.model = "other"
        try:
            out = self.ctl("strata", expect=1)
        finally:
            Health.model = "m-a"
        self.assertIn("runs other", out)
        (self.home / "w-a.gguf").unlink()
        self.assertIn("missing weights", self.ctl("strata", expect=1))

    def test_pair_dispatches_through_strata_agent_in_the_worktree(self):
        spec = Path(self.tmp.name) / "brief.json"
        spec.write_text(json.dumps({"goal": "write a.txt", "scope": ["a.txt"], "files": ["a.txt"], "acceptance": ["a.txt says paired"]}))
        out = self.ctl("pair", "t", "--spec", spec, "--repo", self.repo, "--implementer", "strata", "--allow-dirty")
        self.assertIn("Strata: m-a, context 131072", out)
        self.assertIn("AUDIT-READY", out)
        seen = json.loads(Path(self.env["FAKE_AGENT_LOG"]).read_text())
        self.assertEqual(seen["seat"], "strata")
        self.assertNotEqual(Path(seen["cwd"]).resolve(), self.repo.resolve())  # ran in the worktree
        self.assertNotIn("--model", seen["args"])  # the model comes from the Strata install, never from conspirator
        self.assertIn("acceptEdits", seen["args"])

    def test_broken_install_refuses_dispatch(self):
        (self.home / "pack-a").rmdir()
        spec = Path(self.tmp.name) / "brief.json"
        spec.write_text(json.dumps({"goal": "write a.txt", "scope": ["a.txt"], "files": ["a.txt"], "acceptance": ["a.txt says paired"]}))
        out = self.ctl("pair", "t", "--spec", spec, "--repo", self.repo, "--implementer", "strata", "--allow-dirty", expect=1)
        self.assertIn("Strata is not usable: missing pack", out)
        self.assertFalse(Path(self.env["FAKE_AGENT_LOG"]).exists())

    def test_config_accepts_strata_implementer(self):
        self.assertIn('"strata"', self.ctl("config", "implementer", "strata"))


if __name__ == "__main__":
    unittest.main()
