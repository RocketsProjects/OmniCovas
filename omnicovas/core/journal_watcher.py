"""
omnicovas.core.journal_watcher

Monitors the Elite Dangerous journal directory for new events.
Bridges watchdog's file system thread to the asyncio event loop.

Architecture:
    watchdog monitors journal directory (separate thread)
    → file change detected
    → loop.call_soon_threadsafe() bridges to asyncio
    → new journal lines dispatched as events

Critical Pattern (Law 6 — Performance Priority):
    watchdog runs on its OWN thread.
    asyncio runs on the MAIN thread.
    NEVER call asyncio functions directly from watchdog callbacks.
    ALWAYS use loop.call_soon_threadsafe() to cross the thread boundary.

See: Master Blueprint v4.0 Section 2 (Data Pipeline)
See: Phase 1 Development Guide Week 2
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# Default Elite Dangerous journal path on Windows
DEFAULT_JOURNAL_PATH = Path(
    os.path.expandvars(
        r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous"
    )
)

# Journal files match this pattern: Journal.2024-01-01T120000.01.log
JOURNAL_FILE_PREFIX = "Journal."
JOURNAL_FILE_SUFFIX = ".log"

# JOURNAL_ROLLOVER_01: how often (seconds) the watcher re-scans the journal
# directory for a newer Journal.*.log than the one currently being tailed.
# Elite creates a new journal at session start / on the ~per-session rollover;
# polling lets OmniCOVAS switch watchers without an app restart. The interval
# is generous (directory scan only) to respect Law 6 (Performance Priority).
ROLLOVER_POLL_INTERVAL = 3.0


class JournalEventHandler(FileSystemEventHandler):  # type: ignore[misc,unused-ignore]
    """
    watchdog event handler for Elite Dangerous journal files.

    Detects when ED writes new lines to the current journal file
    and bridges them to the asyncio event loop via call_soon_threadsafe.

    Args:
        loop: The running asyncio event loop (captured at startup)
        dispatch_fn: Async coroutine to call with each new journal line

    Note:
        This class runs on watchdog's thread, NOT the asyncio thread.
        All asyncio interaction MUST go through loop.call_soon_threadsafe().
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        dispatch_fn: Callable[[str], Coroutine[Any, Any, None]],
        current_journal: Path | None,
    ) -> None:
        super().__init__()
        self._loop = loop
        self._dispatch_fn = dispatch_fn
        self._current_journal = current_journal
        self._file_position = 0
        # JOURNAL_ROLLOVER_01: while paused, live tailing is suppressed so the
        # rollover routine can catch a new journal up from the beginning at a
        # known cursor without the watchdog thread reading it at a stale
        # position. The rollover routine runs on the asyncio loop; this flag is
        # the only state it touches that the watchdog thread also reads.
        self._paused = True

    def pause(self) -> None:
        """Suspend live tailing (used while a rollover catch-up is in flight)."""
        self._paused = True

    def retarget(self, journal: Path, position: int) -> None:
        """Point the live tailer at *journal* starting at *position* and resume.

        Order matters: set the cursor and target before clearing the pause flag
        so the watchdog thread never observes the new journal with the old
        file position.
        """
        self._file_position = position
        self._current_journal = journal
        self._paused = False

    def on_modified(self, event: FileSystemEvent) -> None:
        """
        Called by watchdog when a file is modified.

        Filters to only handle the current journal file.
        Reads any new lines added since last read.
        Bridges each line to asyncio via call_soon_threadsafe.
        """
        if self._paused or self._current_journal is None:
            return

        if event.is_directory:
            return

        modified_path = Path(str(event.src_path))

        # Only process the current journal file
        if modified_path != self._current_journal:
            return

        # Read new lines since last position
        try:
            with open(modified_path, encoding="utf-8") as f:
                f.seek(self._file_position)
                new_lines = f.readlines()
                self._file_position = f.tell()

            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                # Bridge to asyncio — this is the critical thread-safe call
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future, self._dispatch_fn(line)
                )

        except OSError as e:
            logger.warning("Failed to read journal file: %s", e)


class JournalWatcher:
    """
    Watches the Elite Dangerous journal directory for new events.

    Handles:
    - Finding the current journal file (newest Journal.*.log)
    - Catch-up reading all existing lines on startup
    - Handing off to watchdog for live monitoring
    - Graceful shutdown

    Args:
        dispatch_fn: Async coroutine called with each raw journal line (str)
        journal_path: Path to ED journal directory (defaults to standard location)

    Usage:
        watcher = JournalWatcher(dispatch_fn=my_handler)
        await watcher.start()
        # ... runs until stopped ...
        await watcher.stop()

    See: Phase 1 Development Guide Week 2, Part A
    """

    def __init__(
        self,
        dispatch_fn: Callable[[str], Coroutine[Any, Any, None]],
        journal_path: Path | None = None,
        on_rollover: Callable[[Path | None, Path], None] | None = None,
        poll_interval: float = ROLLOVER_POLL_INTERVAL,
    ) -> None:
        self._dispatch_fn = dispatch_fn
        self._journal_path = journal_path or DEFAULT_JOURNAL_PATH
        self._observer: Any = None
        self._current_journal: Path | None = None
        # JOURNAL_ROLLOVER_01 wiring.
        self._handler: JournalEventHandler | None = None
        self._on_rollover = on_rollover
        self._poll_interval = poll_interval
        self._rollover_task: asyncio.Task[None] | None = None
        self._running = False

    # Matches Journal.YYYY-MM-DDTHHMMSS.NN.log and Journal.YYYY-MM-DDTHH:MM:SS.NN.log
    _JOURNAL_TS_RE = re.compile(
        r"^Journal\.(\d{4}-\d{2}-\d{2}T\d{2}:?\d{2}:?\d{2})\.\d+\.log$"
    )
    # Captures the trailing per-session part number (the .NN before .log).
    _JOURNAL_PART_RE = re.compile(
        r"^Journal\.\d{4}-\d{2}-\d{2}T\d{2}:?\d{2}:?\d{2}\.(\d+)\.log$"
    )

    def _parse_journal_timestamp(self, filename: str) -> datetime | None:
        """Parse a journal filename into a datetime for ordering.

        Accepts both Journal.YYYY-MM-DDTHHMMSS.NN.log and the colon variant.
        Returns None when the filename does not match the expected pattern.
        """
        m = self._JOURNAL_TS_RE.match(filename)
        if not m:
            return None
        ts_str = m.group(1).replace(":", "")  # normalise HH:MM:SS → HHMMSS
        try:
            return datetime.strptime(ts_str, "%Y-%m-%dT%H%M%S")
        except ValueError:
            return None

    def _parse_journal_part(self, filename: str) -> int:
        """Return the per-session part number from a journal filename (0 if absent)."""
        m = self._JOURNAL_PART_RE.match(filename)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except ValueError:
            return 0

    def _journal_sort_key(self, path: Path) -> tuple[datetime, int]:
        """Ordering key: (filename timestamp, part number).

        Unparseable filenames sort lowest via datetime.min so a real,
        timestamped journal always outranks them.
        """
        ts = self._parse_journal_timestamp(path.name)
        return (ts or datetime.min, self._parse_journal_part(path.name))

    def _is_newer(self, candidate: Path, current: Path) -> bool:
        """Return True when *candidate* is a strictly newer journal than *current*.

        Uses filename timestamp + part ordering when both parse; falls back to
        modification time only when either filename is unparseable.
        """
        cand_ts = self._parse_journal_timestamp(candidate.name)
        cur_ts = self._parse_journal_timestamp(current.name)
        if cand_ts is not None and cur_ts is not None:
            return self._journal_sort_key(candidate) > self._journal_sort_key(current)
        try:
            return candidate.stat().st_mtime > current.stat().st_mtime
        except OSError:
            return False

    def _find_current_journal(self) -> Path | None:
        """
        Find the newest Journal.*.log file in the journal directory.

        Selection order:
        1. Parse the timestamp encoded in each filename and pick the newest.
        2. Fall back to file modification time only when no filename is parseable.

        Logs both the selected filename and the method used (filename_timestamp
        or fallback_mtime) so failures are easy to diagnose.

        Returns:
            Path to the newest journal file, or None if none found.
        """
        if not self._journal_path.exists():
            logger.error("Journal directory not found: %s", self._journal_path)
            return None

        journal_files = [
            f
            for f in self._journal_path.iterdir()
            if f.name.startswith(JOURNAL_FILE_PREFIX)
            and f.name.endswith(JOURNAL_FILE_SUFFIX)
        ]

        if not journal_files:
            logger.warning("No journal files found in: %s", self._journal_path)
            return None

        # Attempt filename-timestamp ordering first. Tie-break on the per-session
        # part number so two journals created in the same second are ordered
        # deterministically.
        parseable = [
            f
            for f in journal_files
            if self._parse_journal_timestamp(f.name) is not None
        ]

        if parseable:
            selected = max(parseable, key=self._journal_sort_key)
            logger.info(
                "Journal selected: %s (method: filename_timestamp)", selected.name
            )
            return selected

        # Fallback: use modification time when filenames cannot be parsed
        selected = max(journal_files, key=lambda f: f.stat().st_mtime)
        logger.warning(
            "Journal selected: %s (method: fallback_mtime — filename parsing failed)",
            selected.name,
        )
        return selected

    async def _catchup_read(self, journal_file: Path) -> int:
        """
        Read all existing lines from a journal file on startup.

        This reconstructs current game state from the beginning of the session.
        Must complete before watchdog starts monitoring, to avoid missing events.

        Args:
            journal_file: Path to the journal file to read

        Returns:
            File position after reading (passed to watchdog handler)
        """
        logger.info("Catch-up reading journal: %s", journal_file.name)
        position = 0
        lines_processed = 0

        try:
            with open(journal_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Parse to verify it's valid JSON before dispatching
                    try:
                        json.loads(line)
                        await self._dispatch_fn(line)
                        lines_processed += 1
                    except json.JSONDecodeError:
                        logger.warning(
                            "Skipping malformed JSON line during catch-up: %s",
                            line[:80],
                        )
                position = f.tell()
        except OSError as e:
            logger.error("Failed to read journal file during catch-up: %s", e)

        logger.info(
            "Catch-up complete: %d events from %s", lines_processed, journal_file.name
        )
        return position

    async def _attach_journal(self, journal: Path, *, catchup: bool) -> int:
        """Attach the live tailer to *journal*, optionally catching up first.

        Returns the file position the tailer was retargeted to. Updates
        ``self._current_journal`` and (when present) the watchdog handler.
        """
        position = await self._catchup_read(journal) if catchup else 0
        self._current_journal = journal
        if self._handler is not None:
            self._handler.retarget(journal, position)
        return position

    async def _perform_rollover(self, new_journal: Path) -> None:
        """Switch watchers from the current journal to a newer one (no restart).

        JOURNAL_ROLLOVER_01: Elite creates a new Journal.*.log at session
        start / per-session rollover. When that happens after OmniCOVAS has
        started, the old tailer must detach and the new journal must be caught
        up from the beginning so journal-owned facts (ship identity, loadout)
        re-ground from the latest session. Older-journal events cannot overwrite
        the newer state afterwards because the handler only tails the retargeted
        file.
        """
        old = self._current_journal
        logger.info(
            "Journal rollover detected: old=%s new=%s",
            old.name if old is not None else "none",
            new_journal.name,
        )
        # Suppress live tailing while we catch the new journal up at a known
        # cursor, then retarget + resume in one atomic handoff.
        if self._handler is not None:
            self._handler.pause()
        await self._attach_journal(new_journal, catchup=True)
        if self._on_rollover is not None:
            try:
                self._on_rollover(old, new_journal)
            except Exception:
                # Law 6: an audit-hook failure must never crash the watcher.
                logger.exception("Journal rollover callback failed")

    async def _check_for_rollover(self) -> bool:
        """Re-scan the directory and switch journals if a newer one appeared.

        Returns True when an attach or rollover happened. Safe to call
        repeatedly; a no-op when the newest journal is the one already tailed.
        """
        newest = self._find_current_journal()
        if newest is None:
            return False

        # Elite was not running at startup; attach now that a journal exists.
        if self._current_journal is None:
            logger.info("Journal now available; attaching: %s", newest.name)
            await self._attach_journal(newest, catchup=True)
            if self._on_rollover is not None:
                try:
                    self._on_rollover(None, newest)
                except Exception:
                    logger.exception("Journal rollover callback failed")
            return True

        if newest == self._current_journal:
            return False

        if not self._is_newer(newest, self._current_journal):
            # Older or sibling file surfaced (e.g. mtime churn). Never roll back.
            return False

        await self._perform_rollover(newest)
        return True

    async def _rollover_poll_loop(self) -> None:
        """Background loop: periodically check for a newer journal file."""
        while self._running:
            await asyncio.sleep(self._poll_interval)
            if not self._running:
                break
            try:
                await self._check_for_rollover()
            except Exception:
                # Law 6: never let the rollover watcher crash the event loop.
                logger.exception("Journal rollover check failed")

    async def start(self) -> None:
        """
        Start the journal watcher.

        Sequence (order is critical):
        1. Find current journal file (may be None if Elite is not running yet)
        2. Catch-up read all existing lines
        3. Start watchdog observer on the journal directory
        4. Start the rollover poll loop so a newer journal is picked up live

        This sequence guarantees no events are missed or duplicated, and that
        a journal created after startup is adopted without an app restart
        (JOURNAL_ROLLOVER_01).
        """
        if not self._journal_path.exists():
            logger.error(
                "Cannot start journal watcher: directory not found: %s. "
                "Is Elite Dangerous installed?",
                self._journal_path,
            )
            return

        self._running = True
        loop = asyncio.get_running_loop()

        # The handler watches the directory; it starts paused/unattached and is
        # retargeted to whichever journal is current now or appears later.
        self._handler = JournalEventHandler(
            loop=loop,
            dispatch_fn=self._dispatch_fn,
            current_journal=None,
        )

        current = self._find_current_journal()
        if current is not None:
            logger.info("Starting journal watcher for: %s", current.name)
            await self._attach_journal(current, catchup=True)
            logger.info("Journal watcher live. Monitoring: %s", self._journal_path)
        else:
            logger.warning(
                "No journal file found yet. Watcher will attach when Elite "
                "Dangerous creates one: %s",
                self._journal_path,
            )

        self._observer = Observer()
        self._observer.schedule(
            self._handler, path=str(self._journal_path), recursive=False
        )
        self._observer.start()

        self._rollover_task = asyncio.create_task(self._rollover_poll_loop())

    async def stop(self) -> None:
        """
        Stop the journal watcher gracefully.
        """
        self._running = False

        if self._rollover_task is not None:
            self._rollover_task.cancel()
            try:
                await self._rollover_task
            except asyncio.CancelledError:
                pass
            self._rollover_task = None

        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Journal watcher stopped.")
