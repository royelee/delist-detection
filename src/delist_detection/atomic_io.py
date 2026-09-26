"""Atomic file writes: a reader sees the old file or the complete new one, never a part.

Two shapes. `write_atomic` replaces one cache file with data it is handed,
durably, through a temp file named for its writer (so `clean_orphan_temps` can
remove a killed writer's leftover). `replace_on_success`/`replace_all_on_success`
yield temp paths for a block to write, and replace their targets only when the
block finishes -- all of them together, for a group of output tables.
"""
from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """Make a rename in `directory` durable. Best effort: some filesystems refuse
    to fsync a directory."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_atomic(path: Path, data: str | bytes) -> None:
    """Replace `path` with `data` (text, written as UTF-8, or bytes) in one
    step: a reader -- in this process or another -- sees the old file or the
    complete new one, never a part. The temp file sits in the same directory
    (os.replace is atomic only within one filesystem) and carries the process
    and thread id, so two writers never
    share one and `clean_orphan_temps` can tell a dead writer's leftover from a
    live one's. The data is fsynced before the rename and the directory after
    it, so the new file also survives a power loss. Durability is fsync-level
    only: on macOS `os.fsync` does not flush the drive's own write cache (that
    takes `fcntl.F_FULLFSYNC`), so a power loss there may still lose a write the
    OS had accepted."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with (open(tmp, "wb") if isinstance(data, bytes) else open(tmp, "w", encoding="utf-8")) as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)


def _pid_alive(pid: int) -> bool:
    """False only when no process has `pid`. True when one may: it is running,
    it belongs to another user (EPERM), or `pid` is no number this OS can hold
    as a pid (a stray file's name, not ours to judge)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:              # EPERM: the process exists but belongs to another user
        return True
    except (OverflowError, ValueError):
        return True
    return True


_TEMP_NAME = re.compile(r"\.(.+)\.(\d+)\.(\d+)\.tmp", re.ASCII)


def clean_orphan_temps(directory: Path) -> None:
    """Delete the `write_atomic` temp files (`.<name>.<pid>.<thread>.tmp`) in
    `directory` whose writing process has exited: it was killed mid-write. A
    live process's temp file is left alone, since it may still be writing it,
    and so is any file whose name does not parse as one. The pid is checked on
    this host only: this assumes every writer to the cache runs on this machine
    in one PID namespace (a cache shared with another host or a container could
    see that writer's live temp file as a dead one's). Also deletes every
    `<name>.part` file: `sec_http.download` wrote its ZIPs through one before it
    used `write_atomic`, and nothing writes one now, so a `.part` file is only
    ever a leftover of a run killed mid-download."""
    if not directory.is_dir():
        return
    for p in directory.glob(".*.tmp"):
        m = _TEMP_NAME.fullmatch(p.name)
        if m and not _pid_alive(int(m.group(2))):
            p.unlink(missing_ok=True)
    for p in directory.glob("*.part"):
        p.unlink(missing_ok=True)


@contextmanager
def replace_all_on_success(paths: Sequence[str | Path]) -> Iterator[list[Path]]:
    """Yield one temp path beside each of `paths`; every path is replaced by its
    temp file, in order, only when the block finishes. On any failure no path
    is replaced and every temp file is removed, so an abort never leaves a
    partial file -- or one new file among old ones -- over the last complete set."""
    targets = [Path(p) for p in paths]
    tmps = [p.with_name(f".{p.name}.tmp") for p in targets]
    try:
        for p in targets:
            p.parent.mkdir(parents=True, exist_ok=True)
        yield tmps
        for tmp, p in zip(tmps, targets):
            os.replace(tmp, p)
    finally:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)


@contextmanager
def replace_on_success(path: str | Path) -> Iterator[Path]:
    """`replace_all_on_success` for one file: yield a temp path beside `path`,
    which replaces `path` only when the block finishes."""
    with replace_all_on_success([path]) as (tmp,):
        yield tmp
