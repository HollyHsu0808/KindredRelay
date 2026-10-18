"""Offline residue tests for the SQLite timeline store. Run with the project's .venv Python.

Restart replaces a saved timeline. Afterwards the replaced text and photo bytes
must not stay readable in the database file or its journal files. Uses temporary
databases; no Streamlit page, models or network.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

UI = Path(__file__).resolve().parent
AGENT = UI.parent / "agent"
sys.path.insert(0, str(UI))
sys.path.insert(0, str(AGENT))
from episode import Episode, load_scenario
import timeline_storage
from timeline_storage import TimelineSession, TimelineStore

SCENARIO = UI.parent / "care_cases" / "episode_hip_fracture.json"
TEXT = b"RESIDUE-MARKER-NOTE-TEXT"
PHOTO = b"\xff\xd8RESIDUE-MARKER-PHOTO" + b"y" * 5000


def episode():
    return Episode(load_scenario(SCENARIO))


def update(uid, text):
    return {"update_id": uid, "kind": "note", "author": "anna", "text": text,
            "at": "2026-10-17T11:00:00+01:00", "topic": "plan"}


def snapshot(note):
    payload = {"format": 1, "projection": "episode-revision-v1", "scenario": {"note": note}, "events": []}
    return {**payload, "sha256": hashlib.sha256(timeline_storage._json(payload).encode("utf-8")).hexdigest()}


class ResidueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "timelines.sqlite3"
        self.store = TimelineStore(self.path)

    def raw(self):
        # The database and any rollback-journal or WAL file left next to it.
        files = [self.path] + [self.path.with_name(self.path.name + suffix) for suffix in ("-journal", "-wal")]
        return b"".join(p.read_bytes() for p in files if p.is_file())

    def test_restart_leaves_no_replaced_text_or_photo_bytes(self):
        for kind in ("private", "family"):
            with self.subTest(kind=kind):
                saved = TimelineSession.create(self.store, kind, episode())
                saved.episode.add_update(update("p1", TEXT.decode() + " " + "x" * 3000), facts=[])
                saved.photos["photo1"] = PHOTO
                saved.episode.add_update({**update("photo1", "Photo of the discharge letter."), "kind": "photo", "photo_of": "Fictional paper"}, facts=[])
                # The deleted source keeps its text in the journal by design (PF3) until Restart.
                saved.episode.delete_update("p1", expected_revision=1, request_id="delete")
                stored = self.store.load(saved.token, kind)
                self.assertIn(TEXT.decode(), Episode.from_snapshot(stored.snapshot).source_history("p1")[0]["update"]["text"])
                self.assertEqual(stored.photos, {"photo1": PHOTO})
                raw = self.raw()
                self.assertTrue(TEXT in raw and b"RESIDUE-MARKER-PHOTO" in raw, "the scan must see the saved bytes")
                saved.replace(episode())
                stored = self.store.load(saved.token, kind)
                self.assertEqual((Episode.from_snapshot(stored.snapshot).updates, stored.photos), ([], {}))
                raw = self.raw()
                self.assertFalse(TEXT in raw, "replaced note text is still in the store files")
                self.assertFalse(b"RESIDUE-MARKER-PHOTO" in raw, "replaced photo bytes are still in the store files")

    def test_overwritten_snapshot_and_dropped_photo_leave_no_residue(self):
        token = secrets.token_urlsafe(32)
        revision = self.store.save(token, "family", snapshot(TEXT.decode() + "x" * 3000), {"c01": PHOTO}, expected_revision=0)
        revision = self.store.save(token, "family", snapshot("demo story again"), {}, expected_revision=revision)
        loaded = self.store.load(token, "family")
        self.assertEqual((loaded.revision, loaded.snapshot["scenario"]["note"], loaded.photos), (2, "demo story again", {}))
        raw = self.raw()
        self.assertFalse(TEXT in raw, "overwritten snapshot text is still in the store files")
        self.assertFalse(b"RESIDUE-MARKER-PHOTO" in raw, "dropped photo bytes are still in the store files")

    def test_every_connection_zeroes_deleted_content_and_uses_a_rollback_journal(self):
        TimelineSession.create(self.store, "private", episode())
        with self.store._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA secure_delete").fetchone()[0], 1)
            # No WAL file whose old frames could still hold replaced pages.
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.assertFalse(self.path.with_name(self.path.name + "-wal").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
