#!/usr/bin/env python3
"""The page's 'Timeline updated: ...' message about a typed care-team update says what its timeline card says
(timeline_html.display_headline): a procedure the quote says will not happen or was cancelled is told in its own words,
never 'Operation planned: ...'; a plan that stands keeps the core headline. A stub model, never called over the
network. Needs the packages in requirements-ui.txt:
  python ui/test_toast_headline.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from episode import llm_extractor  # noqa: E402
from test_timeline_page import StubModel, add_story, fresh, heads, open_panel, setUpModule  # noqa: E402,F401


class TestToastHeadline(unittest.TestCase):
    def tearDown(self):
        for k in ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def typed(self, text: str, fact: dict):
        at = fresh()
        add_story(at, 1)
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="stub")   # never called
        at.session_state["extractor"] = llm_extractor(StubModel({"facts": [{"type": "procedure_planned", **fact}]}))
        at.run()
        open_panel(at, "recording")
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.text_area(key="rec_text").set_value(text).run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["episode"].entries[-1]["rejected"], [])
        return at

    def test_a_plan_that_will_not_happen_is_told_in_its_own_words(self):
        for text, fact in (("The surgeon will not operate tomorrow morning.",
                            {"what": "Operation", "quote": "The surgeon will not operate tomorrow morning",
                             "when_text": "tomorrow morning"}),
                           ("Surgery has been cancelled.", {"what": "Surgery", "quote": "Surgery has been cancelled"})):
            with self.subTest(text=text):
                at = self.typed(text, fact)
                self.assertEqual([t.value for t in at.toast], [f"Timeline updated: {fact['quote']}"])
                self.assertIn(fact["quote"], heads(at))   # the same words as its timeline card

    def test_a_plan_that_stands_keeps_the_core_headline(self):
        at = self.typed("Surgery was cancelled today and is rebooked for Friday.",
                        {"what": "Surgery", "quote": "Surgery was cancelled today and is rebooked for Friday",
                         "when_text": "Friday"})
        headline = at.session_state["episode"].render(at.session_state["episode"].entries[-1])["headline"]
        self.assertTrue(headline.startswith("Surgery planned"))
        self.assertEqual([t.value for t in at.toast], [f"Timeline updated: {headline}"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
