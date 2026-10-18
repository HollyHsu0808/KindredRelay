"""Focused offline persistence tests. Run with the project's .venv Python.

Uses temporary databases and disables Streamlit secret discovery. AppTest cases
exercise the real page; extractor/transcriber models are not invoked.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

UI = Path(__file__).resolve().parent
AGENT = UI.parent / "agent"
sys.path.insert(0, str(UI))
sys.path.insert(0, str(AGENT))
from episode import Episode, load_scenario
from timeline_storage import StoreConflict, StoreError, StoreMissing, TimelineSession, TimelineStore, validate_token

SCENARIO = UI.parent / "care_cases" / "episode_hip_fracture.json"
PAGE = UI / "pages" / "1_Family_timeline.py"


def state_get(at, key: str, default=None):
    """at.session_state.filtered_state.get(key, default) without filtered_state, which Streamlit 1.64's AppTest
    session view lacks (membership there follows the same filtered view)."""
    return at.session_state[key] if key in at.session_state else default


def episode():
    return Episode(load_scenario(SCENARIO))


def update(uid="p1", text="I will visit on Tuesday afternoon."):
    return {"update_id": uid, "kind": "note", "author": "anna", "text": text,
            "at": "2026-10-17T11:00:00+01:00", "topic": "plan"}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timelines.sqlite3"
        self.store = TimelineStore(self.path)

    def test_restart_process_reloads_snapshot_source_revisions_and_checked_photo_only(self):
        saved = TimelineSession.create(self.store, "private", episode(), {"draft": b"do not save"})
        saved.episode.add_update(update(), facts=[])
        saved.episode.revise_update("p1", {"text": "I will visit Wednesday."}, expected_revision=1, request_id="revise", facts=[])
        saved.episode.mark_read("anna")
        saved.episode.add_question("Can we visit?", "mia")
        saved.photos["photo1"] = b"checked photo fixture"
        saved.episode.add_update({**update("photo1"), "kind": "photo", "photo_of": "Fictional paper"}, facts=[])
        script = """import json,sys
from pathlib import Path
from episode import Episode
from timeline_storage import TimelineSession, TimelineStore
s=TimelineSession.open(TimelineStore(Path(sys.argv[1])),sys.argv[2],'private',Episode)
print(json.dumps({'snapshot':s.episode.to_snapshot(),'photos':{k:v.decode() for k,v in s.photos.items()}}))
"""
        result = subprocess.run([sys.executable, "-c", "import sys;sys.path[:0]=" + repr([str(UI), str(AGENT)]) + ";" + script,
                                 str(self.path), saved.token], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["snapshot"], saved.episode.to_snapshot())
        self.assertEqual(payload["photos"], {"photo1": "checked photo fixture"})
        self.assertEqual(Episode.from_snapshot(payload["snapshot"]).source_revision("p1"), 2)

    def test_independent_capabilities_kinds_and_malformed_tokens(self):
        first = TimelineSession.create(self.store, "private", episode())
        second = TimelineSession.create(self.store, "private", episode())
        first.episode.add_update(update(text="Only first timeline."), facts=[])
        self.assertEqual(TimelineSession.open(self.store, second.token, "private", Episode).episode.updates, [])
        with self.assertRaises(StoreMissing): self.store.load(first.token, "family")
        with self.assertRaises(StoreMissing): self.store.load(secrets.token_urlsafe(32), "private")
        for token in ("../timelines.sqlite3", "/tmp/x", "a" * 42, "a" * 44, "?family=aaaa", "a" * 42 + "/", None):
            with self.subTest(token=token), self.assertRaises(StoreMissing): self.store.load(token, "private")
        self.assertEqual(len(first.token), 43)
        legacy = TimelineSession.create(self.store, "family", episode(), token="Ab12_-xy")
        self.assertEqual(TimelineSession.open(self.store, legacy.token, "family", Episode).episode.updates, [])

    def test_two_writers_conflict_rolls_back_local_command_and_preserves_winner(self):
        first = TimelineSession.create(self.store, "private", episode())
        errors = []
        second = TimelineSession.open(TimelineStore(self.path), first.token, "private", Episode, on_error=errors.append)
        first.episode.add_update(update("winner", "First writer's update."), facts=[])
        with self.assertRaises(StoreConflict): second.episode.add_update(update("loser", "Second writer's draft."), facts=[])
        self.assertEqual(second.episode.updates, [])
        self.assertIn("retry your action", errors[0])
        second.refresh(Episode)
        self.assertEqual(second.episode.updates[0]["update_id"], "winner")
        second.episode.add_update(update("retry", "Second writer retried."), facts=[])
        restored = TimelineSession.open(self.store, first.token, "private", Episode)
        self.assertEqual([u["update_id"] for u in restored.episode.updates], ["winner", "retry"])

    def test_unsaveable_model_reply_restores_episode_and_next_command_saves(self):
        errors = []
        saved = TimelineSession.create(self.store, "private", episode(), on_error=errors.append)
        saved.episode.add_update(update(), facts=[])
        before, revision = saved.episode.to_snapshot(), saved.revision
        # json.loads (as in llm_client.extract_json) accepts NaN; the snapshot JSON (allow_nan=False) does not.
        reply = json.loads('[{"type": "event", "what": "Visit on Wednesday", "quote": "I will visit on Wednesday.", "confidence": NaN}]')
        with self.assertRaises(ValueError):
            saved.episode.add_update(update("p2", "I will visit on Wednesday."), extractor=lambda source, ep: reply)
        self.assertEqual(saved.episode.to_snapshot(), before)
        self.assertEqual(self.store.load(saved.token, "private").snapshot, before)
        self.assertEqual((saved.revision, errors), (revision, []), "not a storage failure: no reload banner")
        saved.episode.mark_read("anna")
        stored = self.store.load(saved.token, "private")
        self.assertEqual((stored.revision, stored.snapshot["events"][-1]["op"]), (revision + 1, "read"))
        self.assertEqual(stored.snapshot, saved.episode.to_snapshot())

    def test_any_save_failure_restores_episode_and_next_command_saves(self):
        saved = TimelineSession.create(self.store, "private", episode())
        saved.episode.add_update(update(), facts=[])
        before, revision = saved.episode.to_snapshot(), saved.revision
        with patch.object(TimelineStore, "save", side_effect=ValueError("offline unserialisable snapshot")):
            with self.assertRaises(ValueError): saved.episode.add_update(update("p2", "Never saved."), facts=[])
        self.assertEqual(saved.episode.to_snapshot(), before)
        self.assertEqual([u["update_id"] for u in saved.episode.updates], ["p1"])
        saved.episode.mark_read("anna")
        stored = self.store.load(saved.token, "private")
        self.assertEqual((stored.revision, stored.snapshot), (revision + 1, saved.episode.to_snapshot()))

    def test_command_on_a_replaced_episode_is_refused_without_mutation_or_save(self):
        errors = []
        saved = TimelineSession.create(self.store, "family", episode(), on_error=errors.append)
        old = saved.episode
        old.add_update(update(), facts=[])
        saved.replace(episode())
        restarted, old_snapshot = self.store.load(saved.token, "family"), old.to_snapshot()
        with self.assertRaises(StoreConflict): old.add_update(update("p2", "Added from a view opened before the restart."), facts=[])
        self.assertEqual(old.to_snapshot(), old_snapshot)
        stored = self.store.load(saved.token, "family")
        self.assertEqual((stored.revision, stored.snapshot), (restarted.revision, restarted.snapshot))
        self.assertEqual(saved.episode.updates, [])
        self.assertIn("Reload the latest timeline", errors[-1])
        saved.episode.add_update(update("p3", "Added after the restart."), facts=[])
        stored = self.store.load(saved.token, "family")
        self.assertEqual([u["update_id"] for u in Episode.from_snapshot(stored.snapshot).updates], ["p3"])

    def test_delete_tombstone_questions_and_revision_survive_reload(self):
        saved = TimelineSession.create(self.store, "family", episode())
        saved.episode.add_update(update(), facts=[])
        q, _ = saved.episode.add_question("Can we visit?", "mia")
        saved.episode.set_answered(q["qid"], update_id="p1", by="anna")
        saved.episode.delete_update("p1", expected_revision=1, request_id="delete")
        loaded = TimelineSession.open(self.store, saved.token, "family", Episode).episode
        self.assertEqual(loaded.updates, [])
        self.assertEqual(loaded.source_revision("p1"), 2)
        self.assertEqual(loaded.source_history("p1")[-1]["op"], "delete")
        self.assertEqual(loaded.questions[0]["status"], "open")

    def test_corruption_does_not_reset_or_overwrite_store(self):
        saved = TimelineSession.create(self.store, "private", episode())
        key = validate_token(saved.token, "private")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE timelines SET snapshot=? WHERE id=?", ('{"damaged":true}', key))
        before = self.path.read_bytes()
        with self.assertRaises(StoreError): self.store.load(saved.token, "private")
        with self.assertRaises(StoreError): saved.episode.add_update(update(), facts=[])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(saved.episode.updates, [])

    def test_unsupported_snapshot_and_store_schema_are_preserved(self):
        saved = TimelineSession.create(self.store, "private", episode())
        snapshot = saved.episode.to_snapshot()
        snapshot["projection"] = "future-version"
        payload = {k: v for k, v in snapshot.items() if k != "sha256"}
        snapshot["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE timelines SET snapshot=?", (json.dumps(snapshot),))
        with self.assertRaisesRegex(StoreError, "unsupported snapshot"): self.store.load(saved.token, "private")
        with closing(sqlite3.connect(self.path)) as connection, connection: connection.execute("PRAGMA user_version = 99")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(StoreError, "unsupported schema"): self.store.load(saved.token, "private")
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_sqlite_file_is_not_reset(self):
        self.path.write_bytes(b"not a SQLite database")
        before = self.path.read_bytes()
        with self.assertRaises(StoreError): self.store.load(secrets.token_urlsafe(32), "private")
        self.assertEqual(self.path.read_bytes(), before)


class PagePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"CARERELAY_STATE_DIR": self.directory.name,
                                                   "CARERELAY_LLM_BASE_URL": "", "CARERELAY_LLM_MODEL": "",
                                                   "CARERELAY_STORY": str(SCENARIO), "KINDRED_VERIFIER_MODE": "off"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def fresh(self, params=None):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(PAGE), default_timeout=30)
        app.query_params.update(params or {})
        app.run()
        self.assertFalse(app.exception)
        return app

    @staticmethod
    def token(app, key="private"):
        value = app.query_params[key]
        return value[0] if isinstance(value, list) else value

    def note(self, app, text):
        app.button(key="add_paper").click().run()
        app.text_area(key="note_text").set_value(text).run()
        next(b for b in app.button if b.label == "Share with the family").click().run()
        self.assertFalse(app.exception)
        # As documented by the existing page suite's reload_view(), AppTest can
        # retain removed widgets across st.rerun. A new URL-only view also tests
        # real persistence rather than handing the backend object to another run.
        return self.fresh(dict(app.query_params))

    def test_private_story_note_correction_and_new_tab_have_same_saved_snapshot(self):
        app = self.fresh()
        token = self.token(app)
        next(b for b in app.button if b.label == "Add this update").click().run()
        app = self.note(app, "I will visit on Tuesday afternoon.")
        app.text_area(key="correction_text_c01_1").set_value("I will visit on Wednesday afternoon.").run()
        app.checkbox(key="correction_checked_c01_1").check().run()
        app.button(key="correction_save_c01_1").click().run()
        self.assertFalse(app.exception)
        expected = app.session_state["episode"].to_snapshot()
        loaded = self.fresh({"private": token})
        self.assertEqual(loaded.session_state["episode"].to_snapshot(), expected)
        self.assertEqual(loaded.session_state["episode"].source_revision("c01"), 2)
        self.assertIn("bookmark this address", " ".join(c.value for c in loaded.caption))
        other = self.fresh()
        self.assertNotEqual(self.token(other), token)
        self.assertEqual(other.session_state["episode"].updates, [])

    def test_family_survives_cache_eviction_refresh_and_keeps_member_view(self):
        app = self.fresh()
        app = self.note(app, "Private timeline copied into family.")
        app.button(key="invite_family").click().run()
        family = self.token(app, "family")
        david = self.fresh({"family": family, "as": "david"})
        self.assertEqual(david.selectbox[0].value, "david")
        david = self.note(david, "David can help on Thursday.")
        import streamlit as st
        st.cache_resource.clear()
        loaded = self.fresh({"family": family, "as": "mia"})
        self.assertEqual(loaded.selectbox[0].value, "mia")
        store = TimelineStore(Path(self.directory.name) / "timelines.sqlite3")
        saved = store.load(family, "family")
        restored = Episode.from_snapshot(saved.snapshot)
        self.assertEqual(len(restored.updates), 2)
        self.assertEqual(restored.updates[-1]["author"], "david")
        self.assertIn("David can help on Thursday.", " ".join(m.value for m in loaded.markdown))

    def test_corrupted_private_store_shows_error_without_fresh_empty_episode(self):
        app = self.fresh()
        token = self.token(app)
        path = Path(self.directory.name) / "timelines.sqlite3"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE timelines SET snapshot='broken json'")
        before = path.read_bytes()
        loaded = self.fresh({"private": token})
        self.assertTrue(loaded.error)
        self.assertNotIn("episode", loaded.session_state)
        self.assertEqual(path.read_bytes(), before)

    def test_stale_demo_callback_shows_conflict_and_preserves_committed_update(self):
        first = self.fresh()
        token = self.token(first)
        second = self.fresh({"private": token})
        next(b for b in first.button if b.label == "Add this update").click().run()
        next(b for b in second.button if b.label == "Add this update").click().run()
        self.assertFalse(second.exception)
        self.assertTrue(any("Another view changed" in item.value for item in second.error))
        saved = TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(token, "private")
        self.assertEqual(len(Episode.from_snapshot(saved.snapshot).updates), 1)

    def test_story_callback_rendered_before_a_family_restart_is_refused_not_lost(self):
        owner = self.fresh()
        owner.button(key="invite_family").click().run()
        family = self.token(owner, "family")
        stale = self.fresh({"family": family, "as": "david"})
        restarter = self.fresh({"family": family, "as": "mia"})
        next(b for b in restarter.button if b.label == "Restart the story for everyone").click().run()
        self.assertFalse(restarter.exception)
        store = TimelineStore(Path(self.directory.name) / "timelines.sqlite3")
        restarted = store.load(family, "family")
        # This button's callback still holds the episode object the restart replaced.
        next(b for b in stale.button if b.label == "Add this update").click().run()
        self.assertFalse(stale.exception)
        self.assertTrue(any("Another view changed" in item.value for item in stale.error))
        saved = store.load(family, "family")
        self.assertEqual((saved.revision, saved.snapshot), (restarted.revision, restarted.snapshot))

    def test_checked_photo_and_source_words_survive_url_only_reload(self):
        app = self.fresh()
        token = self.token(app)

        def extract(source, ep):
            return []
        extract.log = [{"parsed": True}]
        extract._kindred_explicit_factory = True

        def read(data, mime):
            return {"text": "She is comfortable.", "model": "injected-offline-photo-reader",
                    "image_sha256": hashlib.sha256(data).hexdigest()}

        app.session_state["extractor"] = extract
        app.session_state["photo_reader"] = read
        with patch.dict(os.environ, {"CARERELAY_LLM_BASE_URL": "http://127.0.0.1:9/v1", "CARERELAY_LLM_MODEL": "injected-offline"}):
            app.button(key="add_recording").click().run()
            app.radio(key="hosp_how").set_value("📷 Photograph a paper").run()
            next(b for b in app.button if b.label == "Use the sample photo (discharge medication list)").click().run()
            next(b for b in app.button if b.label == "Read the text on the photo").click().run()
            app.text_input(key="photo_of_text").set_value("Fictional checked paper").run()
            next(b for b in app.button if b.label == "Add to the timeline").click().run()
            self.assertFalse(app.exception)
        loaded = self.fresh({"private": token})
        self.assertEqual(loaded.session_state["episode"].updates[-1]["text"], "She is comfortable.")
        saved = TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(token, "private")
        self.assertEqual(set(saved.photos), {"c01"})
        self.assertTrue(saved.photos["c01"].startswith(b"\xff\xd8"))
        self.assertNotIn("extractor", saved.snapshot)

    def test_invalid_private_token_denies_load_and_missing_family_never_opens_other_data(self):
        owner = self.fresh()
        owner = self.note(owner, "Only the owner's saved timeline.")
        invalid = self.fresh({"private": "../timelines.sqlite3"})
        self.assertTrue(invalid.error)
        self.assertNotIn("episode", invalid.session_state)
        missing_family = self.fresh({"family": "no-such-space", "as": "mia"})
        self.assertEqual(missing_family.session_state["episode"].updates, [])
        self.assertNotIn("Only the owner's saved timeline.", " ".join(m.value for m in missing_family.markdown))

    def interleave_writer_before_read_marker(self):
        """Commit another view after add succeeds but before the read-marker CAS."""
        native_save = TimelineStore.save
        injected = []

        def save(store, token, kind, snapshot, photos, *, expected_revision):
            if not injected and snapshot["events"] and snapshot["events"][-1]["op"] == "read":
                injected.append(True)
                other = TimelineSession.open(store, token, kind, Episode)
                other.episode.add_update({**update("parallel", "Another view's intervening update."), "author": "david"}, facts=[])
            return native_save(store, token, kind, snapshot, photos, expected_revision=expected_revision)

        return patch.object(TimelineStore, "save", save), injected

    def test_read_marker_conflict_keeps_typed_add_success_without_retry_draft(self):
        app = self.fresh()
        token = self.token(app)
        words = "I will visit on Tuesday afternoon."
        app.button(key="add_paper").click().run()
        app.text_area(key="note_text").set_value(words).run()
        interleave, injected = self.interleave_writer_before_read_marker()
        with interleave:
            next(b for b in app.button if b.label == "Share with the family").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(injected), 1)
        saved = TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(token, "private")
        sources = Episode.from_snapshot(saved.snapshot).updates
        self.assertEqual([u["text"] for u in sources].count(words), 1)
        self.assertEqual(len(sources), 2)
        self.assertIsNone(state_get(app, "adding"), "The durable add must close the submit panel despite read-marker conflict")
        self.assertTrue(any("Your update was saved" in warning.value for warning in app.warning))
        self.assertFalse(any("nothing was added" in toast.value.lower() for toast in app.toast))
        reloaded = self.fresh({"private": token})
        self.assertEqual(len(reloaded.session_state["episode"].updates), 2)
        self.assertNotIn("note_text", reloaded.session_state)

    def test_read_marker_conflict_keeps_photo_add_success_and_clears_retry_draft(self):
        app = self.fresh()
        token = self.token(app)

        def extract(source, ep):
            return []
        extract.log = [{"parsed": True}]
        extract._kindred_explicit_factory = True

        def read(data, mime):
            return {"text": "She is comfortable.", "model": "injected-offline-photo-reader",
                    "image_sha256": hashlib.sha256(data).hexdigest()}

        app.session_state["extractor"], app.session_state["photo_reader"] = extract, read
        with patch.dict(os.environ, {"CARERELAY_LLM_BASE_URL": "http://127.0.0.1:9/v1", "CARERELAY_LLM_MODEL": "injected-offline"}):
            app.button(key="add_recording").click().run()
            app.radio(key="hosp_how").set_value("📷 Photograph a paper").run()
            next(b for b in app.button if b.label == "Use the sample photo (discharge medication list)").click().run()
            next(b for b in app.button if b.label == "Read the text on the photo").click().run()
            app.text_input(key="photo_of_text").set_value("Fictional checked paper").run()
            interleave, injected = self.interleave_writer_before_read_marker()
            with interleave:
                next(b for b in app.button if b.label == "Add to the timeline").click().run()
            self.assertFalse(app.exception)
        self.assertEqual(len(injected), 1)
        saved = TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(token, "private")
        sources = Episode.from_snapshot(saved.snapshot).updates
        self.assertEqual(len([u for u in sources if u["kind"] == "photo"]), 1)
        self.assertEqual(set(saved.photos), {"c01"})
        self.assertIsNone(state_get(app, "adding"), "The saved photo must not remain as a failed submission")
        self.assertNotIn("photo", app.session_state)
        self.assertTrue(any("Your update was saved" in warning.value for warning in app.warning))
        self.assertFalse(any("nothing was added" in toast.value.lower() for toast in app.toast))
        self.assertEqual(len(self.fresh({"private": token}).session_state["episode"].updates), 2)

    def test_family_transition_never_exposes_origin_private_capability_to_visitor(self):
        owner = self.fresh()
        private = self.token(owner)
        owner.button(key="invite_family").click().run()
        self.assertFalse(owner.exception)
        family = self.token(owner, "family")
        self.assertNotIn("private", owner.query_params, "Copying the family browser URL must not expose the origin private capability")
        self.assertTrue(all(private not in code.value for code in owner.code))
        store = TimelineStore(Path(self.directory.name) / "timelines.sqlite3")
        private_session = TimelineSession.open(store, private, "private", Episode)
        private_session.episode.add_update(update("private_only", "Private words added after the family copy."), facts=[])
        visitor = self.fresh(dict(owner.query_params))
        self.assertNotIn("persistent_private", visitor.session_state)
        self.assertNotIn("private", visitor.query_params)
        visitor.button(key="leave_space").click().run()
        self.assertFalse(visitor.exception)
        self.assertNotEqual(self.token(visitor), private)
        self.assertEqual(visitor.session_state["episode"].updates, [])
        owner.button(key="leave_space").click().run()
        self.assertFalse(owner.exception)
        self.assertEqual(self.token(owner), private)
        self.assertEqual(owner.session_state["episode"].updates[-1]["update_id"], "private_only")
        self.assertEqual(store.load(family, "family").snapshot["events"], [])

    def test_explicit_restart_is_persisted_for_private_and_family(self):
        app = self.fresh()
        token = self.token(app)
        app = self.note(app, "This is explicitly restarted.")
        next(b for b in app.button if b.label == "Restart the demo").click().run()
        app = self.fresh({"private": token})
        self.assertEqual(app.session_state["episode"].updates, [])
        app = self.note(app, "A family story to restart.")
        app.button(key="invite_family").click().run()
        family = self.token(app, "family")
        next(b for b in app.button if b.label == "Restart the story for everyone").click().run()
        saved = TimelineStore(Path(self.directory.name) / "timelines.sqlite3").load(family, "family")
        self.assertEqual(Episode.from_snapshot(saved.snapshot).updates, [])


if __name__ == "__main__":
    from streamlit.testing.v1.util import patch_config_options
    with patch_config_options({"secrets.files": []}):
        unittest.main(verbosity=2)
