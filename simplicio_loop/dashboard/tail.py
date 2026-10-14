'''Incremental JSONL tail of one run's events file for the dashboard SSE stream (#1399).

Each poll reads only the bytes after the saved offset, so the reader keeps an offset and the last
seq, never the event list. Rotation is detected by an inode change and truncation by a size below
the offset; both restart from byte 0. Only newline-terminated lines are consumed.
'''
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

ACTIVE_DELAY = 0.1
IDLE_CEILING = 0.25
TERMINAL_DELAY = 0.5  # finished runs: one stat per 0.5 s keeps alert frames under the 2 s target


class EventTail:
    '''Returns the events of ``path`` whose ``seq`` is above the cursor, one poll at a time.'''

    def __init__(self, path: str | os.PathLike, *, terminal: bool = False) -> None:
        self.path = Path(path)
        self.terminal = terminal
        self.last_seq = 0
        self._offset = 0
        self._inode: int | None = None
        self._had_events = False

    def poll(self) -> list[dict[str, Any]]:
        '''Read complete new lines and return the events not yet seen, in file order.'''
        self._had_events = False
        try:
            st = os.lstat(self.path)
        except OSError:
            return []
        if not stat.S_ISREG(st.st_mode):  # a symlink is never followed out of the run directory
            return []
        if self._inode is not None and st.st_ino != self._inode:
            self._offset = 0
        self._inode = st.st_ino
        if st.st_size < self._offset:
            self._offset = 0
        if st.st_size == self._offset:
            return []
        with open(self.path, 'rb') as fh:
            fh.seek(self._offset)
            chunk = fh.read(st.st_size - self._offset)
        end = chunk.rfind(b'\n')
        if end < 0:
            return []
        self._offset += end + 1
        events: list[dict[str, Any]] = []
        for raw in chunk[:end].split(b'\n'):
            try:
                event = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, ValueError):
                continue
            seq = event.get('seq') if isinstance(event, dict) else None
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= self.last_seq:
                continue
            self.last_seq = seq
            events.append(event)
        self._had_events = bool(events)
        return events

    def next_delay(self, idle_max: float = TERMINAL_DELAY) -> float:
        '''Seconds to wait before the next poll: 0.1 after events, 0.25 while idle, 0.5 when terminal.

        ``idle_max`` caps the result so a caller can ask for a shorter wait.
        '''
        if self.terminal:
            delay = TERMINAL_DELAY
        elif self._had_events:
            delay = ACTIVE_DELAY
        else:
            delay = IDLE_CEILING
        return min(delay, idle_max)
