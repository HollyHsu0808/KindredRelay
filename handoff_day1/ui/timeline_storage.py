"""Local durable timeline snapshots; no clients, credentials or draft recordings.

SQLite is the authority. The in-process objects are only a cache. Each write uses
an optimistic revision check in the same transaction as the snapshot and photos.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from types import MethodType


class StoreError(RuntimeError):
    """The saved timeline cannot safely be read or written."""


class StoreConflict(StoreError):
    """Another writer committed after this view was loaded."""


class StoreMissing(StoreError):
    """A valid capability has no saved timeline of the requested kind."""


def validate_token(token: str, kind: str) -> str:
    # Eight characters are accepted only to recover existing family invitations.
    lengths = (8, 43) if kind == "family" else (43,)
    if kind not in ("private", "family") or not isinstance(token, str) or len(token) not in lengths or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise StoreMissing("This timeline link is invalid. Open your saved timeline link again.")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _snapshot(snapshot: dict) -> str:
    if not isinstance(snapshot, dict):
        raise StoreError("The saved timeline snapshot is damaged. It has not been reset.")
    payload = {k: v for k, v in snapshot.items() if k != "sha256"}
    if snapshot.get("format") != 1 or snapshot.get("projection") != "episode-revision-v1":
        raise StoreError("This saved timeline uses an unsupported snapshot version. It has not been reset.")
    if snapshot.get("sha256") != hashlib.sha256(_json(payload).encode("utf-8")).hexdigest():
        raise StoreError("The saved timeline checksum failed. It has not been reset.")
    return _json(snapshot)


@dataclass
class StoredTimeline:
    revision: int
    snapshot: dict
    photos: dict[str, bytes]


class TimelineStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def _connection(self):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.execute("PRAGMA foreign_keys = ON")
            # Zero deleted rows and freed pages, so a Restart or an overwritten snapshot or
            # photo leaves no readable copy in the file. The journal stays rollback-mode.
            connection.execute("PRAGMA secure_delete = ON")
            # Initialization is serialized, including first use by two browsers.
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if tables:
                    raise StoreError("The timeline store has an unsupported schema. It has not been reset.")
                connection.execute("CREATE TABLE timelines (id TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL)")
                connection.execute("CREATE TABLE photos (timeline_id TEXT NOT NULL REFERENCES timelines(id), update_id TEXT NOT NULL, data BLOB NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(timeline_id, update_id))")
                connection.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise StoreError("The timeline store has an unsupported schema version. It has not been reset.")
            connection.commit()
            yield connection
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise StoreError("Saved timelines are unavailable. Nothing has been reset; try again or contact the host.") from exc
        finally:
            if connection is not None:
                connection.close()

    def load(self, token: str, kind: str) -> StoredTimeline:
        key = validate_token(token, kind)
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT kind, revision, snapshot FROM timelines WHERE id=?", (key,)).fetchone()
            if row is None or row[0] != kind:
                raise StoreMissing("This timeline link cannot be found. Check the saved link; no saved timeline has been changed.")
            if type(row[1]) is not int or row[1] < 1:
                raise StoreError("The saved timeline revision is damaged. It has not been reset.")
            snapshot = json.loads(row[2])
            _snapshot(snapshot)
            photos = {}
            for uid, data, checksum in connection.execute("SELECT update_id, data, sha256 FROM photos WHERE timeline_id=?", (key,)):
                if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != checksum:
                    raise StoreError("A saved source photo is damaged. The timeline has not been reset.")
                photos[uid] = data
            return StoredTimeline(row[1], snapshot, photos)

    def save(self, token: str, kind: str, snapshot: dict, photos: dict[str, bytes], *, expected_revision: int) -> int:
        key, encoded = validate_token(token, kind), _snapshot(snapshot)
        # The caller passes only photos attached to committed source identities.
        media = [(key, uid, data, hashlib.sha256(data).hexdigest()) for uid, data in photos.items()]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if expected_revision == 0:
                try:
                    connection.execute("INSERT INTO timelines VALUES (?, ?, 1, ?)", (key, kind, encoded))
                except sqlite3.IntegrityError as exc:
                    raise StoreConflict("This timeline already exists. Reload the latest timeline and try again.") from exc
            else:
                prior = connection.execute("SELECT kind, revision, snapshot FROM timelines WHERE id=?", (key,)).fetchone()
                if prior is not None and prior[0] == kind and prior[1] == expected_revision:
                    _snapshot(json.loads(prior[2]))
                    for data, checksum in connection.execute("SELECT data, sha256 FROM photos WHERE timeline_id=?", (key,)):
                        if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != checksum:
                            raise StoreError("A saved source photo is damaged. It has not been overwritten.")
                changed = connection.execute("UPDATE timelines SET revision=revision+1, snapshot=? WHERE id=? AND kind=? AND revision=?",
                                             (encoded, key, kind, expected_revision)).rowcount
                if changed != 1:
                    raise StoreConflict("Another view changed this timeline. Reload the latest timeline, check the new updates, and retry your action. Your draft is kept.")
            connection.execute("DELETE FROM photos WHERE timeline_id=?", (key,))
            connection.executemany("INSERT INTO photos VALUES (?, ?, ?, ?)", media)
            connection.commit()
        return expected_revision + 1


def _restore(episode_type, snapshot):
    try:
        return episode_type.from_snapshot(snapshot)
    except Exception as exc:
        raise StoreError("The saved timeline could not be restored. It has not been reset or overwritten.") from exc


class TimelineSession:
    """Bind persistence to the existing Episode command journal, before UI success.

    Episode._commit replaces its own __dict__; the hook is rebound after every
    command. Only to_snapshot() is serialized, never this hook or session object.
    """
    def __init__(self, store, token, kind, episode, photos, revision, on_error=None):
        self.store, self.token, self.kind = store, token, kind
        self.episode, self.photos, self.revision = episode, photos, revision
        self.lock = threading.RLock()
        self.on_error = on_error
        self.bind()

    @classmethod
    def create(cls, store, kind, episode, photos=None, *, token=None, on_error=None):
        token = token or secrets.token_urlsafe(32)
        _restore(type(episode), episode.to_snapshot())
        session = cls(store, token, kind, episode, dict(photos or {}), 0, on_error)
        session.save()
        return session

    @classmethod
    def open(cls, store, token, kind, episode_type, *, on_error=None):
        stored = store.load(token, kind)
        return cls(store, token, kind, _restore(episode_type, stored.snapshot), stored.photos, stored.revision, on_error)

    def bind(self):
        session, native = self, type(self.episode)._commit

        def commit(episode, event, request_id=None, request=None):
            with session.lock:
                if episode is not session.episode:
                    # Restart replaced this object: committing would save the new episode
                    # and silently drop this command.
                    conflict = StoreConflict("Another view changed this timeline. Reload the latest timeline, check the new updates, and retry your action. Your draft is kept.")
                    if session.on_error is not None:
                        session.on_error(str(conflict))
                    raise conflict
                before = episode.to_snapshot()
                try:
                    result = native(episode, event, request_id, request)
                    session.save()
                    return result
                except BaseException as exc:
                    # Any failure, not only StoreError (e.g. a NaN in a model reply that the
                    # snapshot JSON rejects), leaves memory equal to the saved state.
                    restored = _restore(type(episode), before)
                    episode.__dict__.clear()
                    episode.__dict__.update(restored.__dict__)
                    if isinstance(exc, StoreError) and session.on_error is not None:
                        session.on_error(str(exc))
                    raise
                finally:
                    session.bind()

        self.episode._commit = MethodType(commit, self.episode)

    def save(self):
        snapshot = self.episode.to_snapshot()
        # Preserve original checked photos for the complete journal, including
        # tombstoned sources. Unsubmitted upload and recording drafts stay out.
        attached = {event["update_id"] for event in snapshot["events"] if event["op"] == "add" and event["update"].get("kind") == "photo"}
        photos = {uid: data for uid, data in self.photos.items() if uid in attached}
        self.revision = self.store.save(self.token, self.kind, snapshot, photos, expected_revision=self.revision)

    def refresh(self, episode_type):
        with self.lock:
            stored = self.store.load(self.token, self.kind)
            restored = _restore(episode_type, stored.snapshot)
            if stored.revision != self.revision:
                self.episode.__class__ = episode_type
                self.episode.__dict__.clear()
                self.episode.__dict__.update(restored.__dict__)
                self.photos.clear()
                self.photos.update(stored.photos)
                self.revision = stored.revision
            self.bind()

    def replace(self, episode, photos=None):
        # The explicit Restart control is the only destructive reset path.
        with self.lock:
            snapshot = episode.to_snapshot()
            _restore(type(episode), snapshot)
            photos = dict(photos or {})
            revision = self.store.save(self.token, self.kind, snapshot, photos, expected_revision=self.revision)
            self.episode, self.photos, self.revision = episode, photos, revision
            self.bind()
