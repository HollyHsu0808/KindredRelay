"""Offline AppTest coverage for the own-plan extractor timeout boundary.

All providers are explicit injected stand-ins. SQLite is isolated and Streamlit
secret discovery is disabled. No network or speech/vision model is invoked.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options

UI = Path(__file__).resolve().parent
sys.path[:0] = [str(UI), str(UI.parent / "agent")]
from timeline_storage import StoreConflict, TimelineSession, TimelineStore

PAGE = UI / "pages" / "1_Family_timeline.py"
SCENARIO = UI.parent / "care_cases" / "episode_hip_fracture.json"
WARNING = "Your plan was saved. AI details are temporarily unavailable."


class Capture:
    name = "plan.wav"
    file_id = "offline-plan-unique"

    def getvalue(self):
        return b"offline spoken plan fixture"


class PlanProviderFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {
            "CARERELAY_STATE_DIR": self.directory.name,
            "CARERELAY_STORY": str(SCENARIO),
            "CARERELAY_LLM_BASE_URL": "", "CARERELAY_LLM_MODEL": "",
            "KINDRED_VERIFIER_MODE": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        config = patch_config_options({"secrets.files": []})
        config.__enter__()
        self.addCleanup(config.__exit__, None, None, None)

    def fresh(self, params=None):
        app = AppTest.from_file(str(PAGE), default_timeout=30)
        app.query_params.update(params or {})
        app.run()
        self.assertFalse(app.exception)
        return app

    @staticmethod
    def token(app):
        token = app.query_params["private"]
        return token[0] if isinstance(token, list) else token

    def loaded(self, app):
        return TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(self.token(app), "private")

    def inject(self, app, exception=None, callback=None):
        calls = []

        def extract(update, episode):
            calls.append({"update": copy.deepcopy(update), "snapshot": episode.to_snapshot(),
                          "durable": self.loaded(app).snapshot})
            if callback is not None:
                callback()
            if exception is not None:
                raise exception
            return []

        extract.log = [{"parsed": True}]
        extract._kindred_explicit_factory = True
        app.session_state["extractor"] = extract
        os.environ.update(CARERELAY_LLM_BASE_URL="http://127.0.0.1:9/v1", CARERELAY_LLM_MODEL="offline-injected")
        return calls

    def rerender(self, app):
        fresh = AppTest.from_file(str(PAGE), default_timeout=30)
        fresh.session_state = app.session_state
        fresh.query_params.update(app.query_params)
        fresh.run()
        self.assertFalse(fresh.exception)
        return fresh

    def submit(self, app, words):
        app = self.rerender(app)
        if app.session_state.filtered_state.get("adding") != "paper":
            app.button(key="add_paper").click().run()
        app.text_area(key="note_text").set_value(words).run()
        next(b for b in app.button if b.label == "Share with the family").click().run()
        self.assertFalse(app.exception)
        # A successful submit closes the form. Rebuild its AppTest tree to avoid
        # Streamlit 1.58 retaining deleted widgets. Failed forms stay in place.
        return app if app.session_state.filtered_state.get("adding") == "paper" else self.rerender(app)

    def test_timeout_saves_one_factless_source_and_replaces_latest_plan_after_reload(self):
        app = self.fresh()
        app = self.submit(app, "I will arrive on November 20, 2027 in the afternoon.")
        before = self.loaded(app).snapshot
        calls = self.inject(app, TimeoutError("offline provider timeout"))
        words = "Actually, I will arrive on November 21, 2027 in the morning instead."
        app = self.submit(app, words)
        ep = app.session_state["episode"]
        self.assertEqual(len(calls), 1, "There must be no automatic API retry")
        self.assertEqual(calls[0]["snapshot"], before)
        self.assertEqual(calls[0]["durable"], before, "No source may be committed before extraction finishes")
        self.assertEqual(len(ep.updates), 2)
        self.assertEqual(ep.updates[-1]["at"], calls[0]["update"]["at"])
        self.assertEqual(ep.updates[-1]["update_id"], calls[0]["update"]["update_id"])
        adds = [event for event in ep.events if event["op"] == "add" and event["update_id"] == "c02"]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]["revision"], 1)
        self.assertEqual(adds[0]["facts"], [])
        self.assertEqual(ep.entries[-1]["authority"], "family")
        self.assertEqual(ep.slots, {}, "Raw family plans must not invent clinical state")
        self.assertEqual(ep.plans()[0]["text"], words)
        self.assertEqual(ep.plans()[0]["event_time"]["precision"], "part_of_day")
        self.assertIn("morning", ep.plans()[0]["event_time"]["when_text"])
        self.assertTrue(ep.plans()[0]["event_time"]["when"].startswith("2027-11-21"))
        self.assertTrue(any(WARNING in item.value for item in app.warning))
        app.run()
        self.assertTrue(any(WARNING in item.value for item in app.warning), "Feedback must survive an ordinary rerun")
        loaded = self.fresh({"private": self.token(app)})
        self.assertEqual(loaded.session_state["episode"].to_snapshot(), ep.to_snapshot())
        self.assertEqual(loaded.session_state["episode"].plans()[0]["text"], words)

    def test_ambiguous_plan_keeps_raw_words_and_stays_pending(self):
        app = self.fresh()
        self.inject(app, TimeoutError("offline timeout"))
        words = "I will arrive on 10/11 in the afternoon."
        app = self.submit(app, words)
        plan = app.session_state["episode"].plans()[0]
        self.assertEqual(plan["source_text"], words)
        self.assertEqual(plan["plan_status"], "pending_confirmation")
        self.assertIsNone(plan["event_time"]["when"])

    def test_repeat_submit_does_not_repeat_timeout_request_or_add(self):
        app = self.fresh()
        calls = self.inject(app, TimeoutError("offline timeout"))
        words = "I will arrive on November 21, 2027 in the morning."
        app = self.submit(app, words)
        app = self.submit(app, words)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(app.session_state["episode"].updates), 1)
        self.assertEqual(len([e for e in app.session_state["episode"].events if e["op"] == "add"]), 1)

    def test_spoken_timeout_keeps_receipt_and_asr_identity_and_deduplicates_save(self):
        app = self.fresh()
        calls = self.inject(app, TimeoutError("offline timeout"))
        words = "I will arrive on November 21, 2027 in the morning."
        transcriptions = []

        def transcribe(data, suffix):
            transcriptions.append((data, suffix))
            return {"text": words, "model": "offline-speech-fixture"}

        app.session_state["transcriber"] = transcribe
        with patch("asr_local.missing", return_value=[]), patch("streamlit.audio_input", return_value=Capture()):
            app.button(key="add_paper").click().run()
            self.assertFalse(app.button(key="plan_save").disabled)
            receipt = app.session_state["plan_recording"]["at"]
            app.button(key="plan_save").click().run()
            self.assertFalse(app.exception)
            app = self.rerender(app)
            if app.session_state.filtered_state.get("adding") != "paper":
                app.button(key="add_paper").click().run()
            app.button(key="plan_save").click().run()
        source = app.session_state["episode"].updates[-1]
        self.assertEqual(len(app.session_state["episode"].updates), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(transcriptions), 1)
        self.assertEqual(source["at"], receipt)
        self.assertEqual(source["reading"]["method"], "asr")
        self.assertEqual(source["reading"]["model"], "offline-speech-fixture")
        self.assertEqual(source["reading"]["audio_source_id"], Capture.file_id)
        self.assertEqual(source["reading"]["audio_sha256"], hashlib.sha256(Capture().getvalue()).hexdigest())

    def test_non_timeout_error_keeps_draft_and_persistent_inline_guidance(self):
        app = self.fresh()
        calls = self.inject(app, RuntimeError("offline non-network failure"))
        words = "I will arrive on November 21, 2027 in the morning."
        before = self.loaded(app).snapshot
        app = self.submit(app, words)
        self.assertEqual(self.loaded(app).snapshot, before)
        self.assertEqual(app.session_state["note_text"], words)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("Your words are kept" in item.value for item in app.error))
        app.run()
        self.assertTrue(any("Your words are kept" in item.value for item in app.error))

    def test_connect_timeout_wrapped_in_urlerror_saves_the_plan_without_ai_details(self):
        app = self.fresh()
        # urllib reports a connect timeout as URLError(reason=socket.timeout), not as TimeoutError.
        calls = self.inject(app, urllib.error.URLError(socket.timeout("timed out")))
        words = "I will arrive on November 21, 2027 in the morning."
        app = self.submit(app, words)
        ep = app.session_state["episode"]
        self.assertEqual(len(calls), 1, "There must be no automatic API retry")
        self.assertEqual([u["text"] for u in ep.updates], [words])
        self.assertEqual([event["facts"] for event in ep.events if event["op"] == "add"], [[]])
        self.assertTrue(any(WARNING in item.value for item in app.warning))
        self.assertEqual(self.loaded(app).snapshot, ep.to_snapshot())

    def test_non_timeout_urlerror_keeps_draft_and_saves_nothing(self):
        app = self.fresh()
        calls = self.inject(app, urllib.error.URLError(ConnectionRefusedError("offline connection refused")))
        words = "I will arrive on November 21, 2027 in the morning."
        before = self.loaded(app).snapshot
        app = self.submit(app, words)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.loaded(app).snapshot, before)
        self.assertEqual(app.session_state["episode"].updates, [])
        self.assertEqual(app.session_state["note_text"], words)
        self.assertTrue(any("Your words are kept" in item.value for item in app.error))
        self.assertFalse(any(WARNING in item.value for item in app.warning))

    def test_doctor_recording_timeout_does_not_save_or_create_clinical_state(self):
        app = self.fresh()
        calls = self.inject(app, TimeoutError("offline timeout"))
        before = self.loaded(app).snapshot
        app.session_state["rec_speaker_type"] = "Doctor / nurse"
        app.session_state["rec_speaker"] = "Fictional nurse"
        app.button(key="add_recording").click().run()
        app.text_area(key="rec_text").set_value("She was discharged home on November 21, 2027.").run()
        app.button(key="rec_add").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.loaded(app).snapshot, before)
        self.assertEqual(app.session_state["episode"].updates, [])
        self.assertNotIn("plan_save_feedback", app.session_state)

    def test_store_conflict_after_successful_extraction_is_not_a_provider_timeout(self):
        app = self.fresh()
        calls = self.inject(app)
        before = self.loaded(app).snapshot
        attempted = []

        def fail_save(session):
            attempted.append(session.episode.to_snapshot())
            raise StoreConflict("offline CAS conflict")

        with patch.object(TimelineSession, "save", fail_save):
            app = self.submit(app, "I will arrive on November 21, 2027 in the morning.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(attempted), 1, "A failed durable commit must not be retried as a raw plan")
        self.assertEqual(self.loaded(app).snapshot, before)
        self.assertEqual(app.session_state["episode"].updates, [])
        self.assertTrue(any("Your words are kept" in item.value for item in app.error))
        self.assertTrue(any("Reload" in item.value for item in app.error))

    def test_changed_journal_after_timeout_prevents_the_raw_fallback(self):
        app = self.fresh()
        ep = app.session_state["episode"]
        calls = self.inject(app, TimeoutError("offline timeout"), callback=lambda: ep.mark_read("anna"))
        words = "I will arrive on November 21, 2027 in the morning."
        app = self.submit(app, words)
        self.assertEqual(len(calls), 1)
        self.assertEqual(ep.updates, [])
        self.assertEqual([event["op"] for event in self.loaded(app).snapshot["events"]], ["read"])
        self.assertEqual(app.session_state["note_text"], words)
        self.assertTrue(any("could not be confirmed as saved" in item.value for item in app.error))

    def test_saved_warning_can_be_dismissed_without_changing_the_source(self):
        app = self.fresh()
        self.inject(app, TimeoutError("offline timeout"))
        app = self.submit(app, "I will arrive on November 21, 2027 in the morning.")
        before = self.loaded(app).snapshot
        self.assertTrue(any(WARNING in item.value for item in app.warning))
        app.button(key="dismiss_plan_save_feedback").click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("plan_save_feedback", app.session_state)
        self.assertEqual(self.loaded(app).snapshot, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
