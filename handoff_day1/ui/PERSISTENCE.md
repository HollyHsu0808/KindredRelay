Timeline storage
================

The family timeline page uses Python's standard-library SQLite module. Set the
new `CARERELAY_STATE_DIR` environment variable to a writable persistent directory.
Without this setting the directory is `~/.kindredrelay`; the database filename
is `timelines.sqlite3`. A container replacement retains data only if this
directory is mounted on persistent storage. For example, configure
`CARERELAY_STATE_DIR=/var/lib/kindredrelay` and mount the host's persistent volume
at `/var/lib/kindredrelay`. This document does not provision a volume or host.
Include `ui/timeline_storage.py` in the deployed image alongside the page.

New private timelines put a random 256-bit capability in `?private=...`. Bookmark
the complete address to return after refresh, in another tab or after a server
restart. A bare address starts a separate private timeline. Family invitations
use `?family=...&as=...`; new invitations also use 256-bit random capabilities.
Still-live eight-character invitations from the old in-memory implementation
are copied into the durable store on first access. Invitations whose old server
already discarded their data cannot be recovered by this change.

Both kinds of link grant access to view and change that timeline. The existing
prototype's identity selector is a display identity, not authentication. Anyone
with a family link can select another identity, issue invitations and restart
the shared story. Use fictional data and send links only to trusted people.
There is no new account authentication, revocation screen or encrypted storage.

Only Episode's versioned, checksummed event snapshot and photos attached to
committed photo sources are stored. Drafts, original audio, model clients,
callables and environment configuration are excluded. Original checked photos
remain attached to source history even after a source is tombstoned. Cache
expiry and cache size limits never delete durable timelines. The explicit
Restart control replaces the saved timeline; there is no automatic retention
deletion policy. The host is responsible for protecting, backing up and retaining
the storage directory and access links.

Every store connection sets SQLite `secure_delete`, so text and photo bytes
replaced by Restart, an overwritten snapshot or a dropped photo are zeroed in
`timelines.sqlite3`. The store keeps SQLite's default rollback journal, not WAL.
A deleted update stays in the event journal as a tombstone until Restart. This
does not erase backups, filesystem free space or copies on the storage device.
A file written before this setting can still hold earlier freed pages; stop the
page and run SQLite `VACUUM` once on it. `ui/test_timeline_storage_residue.py`
scans the database and journal files after Restart.

Each command is saved before the page reports success. SQLite transactions keep
the snapshot and attached photos together; a revision comparison rejects stale
writers. A conflict rolls back that local command and asks the user to reload,
check the latest updates and retry. Corrupted or unsupported stores show an
error and are not replaced with an empty timeline. This implementation targets
a single local SQLite store on one host; clustered storage and sustained
multi-process operation have not been accepted by deployment testing.

Focused offline verification from the repository root:

    .venv/Scripts/python.exe handoff_day1/ui/test_timeline_storage.py

The tests use temporary databases. Photo reading is an injected deterministic
fixture; it does not verify a live vision or transcription service. The browser,
container volume and public shell need separate deployment acceptance checks.
