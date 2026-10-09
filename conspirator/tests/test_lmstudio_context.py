#!/usr/bin/env python3
"""LM Studio runs must use the largest context the machine can hold."""

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE_LMS = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_LMS_STATE"]); s = json.loads(state.read_text())
a = sys.argv[1:]
if a[0] == "ps":
    print(json.dumps([s["loaded"]] if s["loaded"] else []))
elif a[0] == "ls":
    print(json.dumps([{"type": "llm", "modelKey": s["key"], "path": s["key"], "maxContextLength": s["max"]}]))
elif a[0] == "unload":
    s["loaded"] = None; state.write_text(json.dumps(s))
elif a[0] == "load":
    ctx = int(a[a.index("-c") + 1])
    if ctx > s["fits"]:
        print("not enough memory", file=sys.stderr); raise SystemExit(1)
    s["loaded"] = {"type": "llm", "modelKey": s["key"], "identifier": a[a.index("--identifier") + 1],
                   "contextLength": ctx, "maxContextLength": s["max"], "parallel": int(a[a.index("--parallel") + 1])}
    s["history"].append(ctx); s["gpu"] = a[a.index("--gpu") + 1] if "--gpu" in a else None; state.write_text(json.dumps(s))
'''


class Quiet:
    def __init__(self): self.lines = []
    def say(self, m): self.lines.append(m)
    step = warn = say


class LmstudioContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); base = Path(self.tmp.name)
        self.bin = base / "bin"; self.bin.mkdir()
        if os.name == "nt":
            (self.bin / "lms.py").write_text(FAKE_LMS)
            (self.bin / "lms.CMD").write_text('@echo off\r\n"%s" "%%~dp0lms.py" %%*\r\n' % sys.executable)
        else:
            exe = self.bin / "lms"; exe.write_text(FAKE_LMS); exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        self.state = base / "state.json"
        self._env = dict(os.environ)
        os.environ["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        os.environ["FAKE_LMS_STATE"] = str(self.state)
        spec = importlib.util.spec_from_file_location("pairctl_ctx", ROOT / "scripts" / "pairctl.py")
        self.ctl = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.ctl)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env); self.tmp.cleanup()

    def setup_state(self, current, fits, top=262144):
        loaded = {"type": "llm", "modelKey": "m/x", "identifier": "x", "contextLength": current,
                  "maxContextLength": top, "parallel": 1} if current else None
        self.state.write_text(json.dumps({"key": "m/x", "max": top, "fits": fits, "loaded": loaded, "history": []}))

    def run_ensure(self, **extra):
        cfg = {"lmstudio_model": "x", **extra}
        got = self.ctl.ensure_lmstudio_max_context(cfg, Quiet())
        return got, json.loads(self.state.read_text())

    def test_reloads_at_model_maximum(self):
        self.setup_state(current=32768, fits=10**9)
        got, s = self.run_ensure()
        self.assertEqual((got, s["loaded"]["contextLength"], s["history"]), (262144, 262144, [262144]))

    def test_context_cap_lowers_the_maximum(self):
        self.setup_state(current=32768, fits=10**9)
        got, s = self.run_ensure(lmstudio_context_cap=131072)
        self.assertEqual((got, s["history"]), (131072, [131072]))

    def test_loaded_context_at_cap_is_untouched(self):
        self.setup_state(current=131072, fits=10**9)
        got, s = self.run_ensure(lmstudio_context_cap=131072)
        self.assertEqual((got, s["history"]), (131072, []))

    def test_gpu_setting_is_passed_to_lms_load(self):
        self.setup_state(current=32768, fits=10**9)
        _, s = self.run_ensure(lmstudio_gpu="off")
        self.assertEqual(s["gpu"], "off")

    def test_gpu_flag_omitted_when_unset(self):
        self.setup_state(current=32768, fits=10**9)
        _, s = self.run_ensure()
        self.assertIsNone(s["gpu"])

    def test_steps_down_when_maximum_does_not_fit(self):
        self.setup_state(current=32768, fits=150000)
        got, s = self.run_ensure()
        self.assertEqual(got, s["loaded"]["contextLength"])
        self.assertLessEqual(got, 150000)
        self.assertGreater(got, 100000)  # largest x0.75 step that fits: 262144*0.75*0.75 = 147456

    def test_already_at_maximum_is_untouched(self):
        self.setup_state(current=262144, fits=10**9)
        got, s = self.run_ensure()
        self.assertEqual((got, s["history"]), (262144, []))

    def test_loads_when_nothing_is_loaded(self):
        self.setup_state(current=0, fits=10**9)
        got, s = self.run_ensure()
        self.assertEqual((got, s["history"]), (262144, [262144]))


if __name__ == "__main__":
    unittest.main()
