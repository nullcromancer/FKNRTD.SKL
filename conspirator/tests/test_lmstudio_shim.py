#!/usr/bin/env python3
"""lmstudio_shim.fix must remove mid-conversation system messages without disturbing the prompt prefix."""

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lmstudio_shim", ROOT / "scripts" / "lmstudio_shim.py")
shim = importlib.util.module_from_spec(spec); spec.loader.exec_module(shim)


def turn(n):
    return [{"role": "user", "content": "q%d" % n},
            {"role": "system", "content": [{"type": "text", "text": "reminder%d" % n}]},
            {"role": "assistant", "content": [{"type": "text", "text": "a%d" % n}]}]


class ShimFoldTests(unittest.TestCase):
    def test_no_system_messages_left_and_body_untouched_without_them(self):
        plain = {"messages": [{"role": "user", "content": "hi"}], "system": "s"}
        self.assertEqual(shim.fix(copy.deepcopy(plain)), plain)
        out = shim.fix({"messages": turn(1)})
        self.assertEqual([m["role"] for m in out["messages"]], ["user", "assistant"])

    def test_system_text_lands_in_preceding_user_message(self):
        out = shim.fix({"messages": turn(1)})
        self.assertEqual(out["messages"][0]["content"], [{"type": "text", "text": "q1"}, {"type": "text", "text": "reminder1"}])
        self.assertNotIn("system", out)

    def test_leading_system_message_goes_to_top_level_system(self):
        out = shim.fix({"system": "base", "messages": [{"role": "system", "content": "early"}, {"role": "user", "content": "q"}]})
        self.assertEqual(out["system"], [{"type": "text", "text": "base"}, {"type": "text", "text": "early"}])
        self.assertEqual(out["messages"], [{"role": "user", "content": "q"}])

    def test_each_request_extends_the_previous_one(self):
        """Prompt-cache invariant: the folded earlier conversation is an exact prefix of the folded longer one."""
        short = shim.fix({"system": "base", "messages": turn(1) + turn(2)[:1]})
        longer = shim.fix({"system": "base", "messages": turn(1) + turn(2) + turn(3)})
        self.assertEqual(short["system"], longer["system"])
        n = len(short["messages"])
        # all but the newest user message are identical; that one only gains its own trailing reminder
        self.assertEqual(short["messages"][:n - 1], longer["messages"][:n - 1])
        text = lambda m: "".join(b["text"] for b in shim.as_blocks(m["content"]))
        self.assertTrue(text(longer["messages"][n - 1]).startswith(text(short["messages"][n - 1])))

    def test_tool_result_blocks_stay_first(self):
        msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]},
                {"role": "system", "content": "note"}]
        out = shim.fix({"messages": msgs})
        self.assertEqual([b["type"] for b in out["messages"][0]["content"]], ["tool_result", "text"])

    def test_input_messages_are_not_mutated(self):
        msgs = turn(1)
        before = copy.deepcopy(msgs)
        shim.fix({"messages": msgs})
        self.assertEqual(msgs, before)


if __name__ == "__main__":
    unittest.main()
