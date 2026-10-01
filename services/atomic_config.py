"""Atomic JSON config write-back for one-time migrations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class AtomicConfigWriteError(RuntimeError):
    """Raised when the migrated config cannot be written atomically."""


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write JSON via temp file + fsync + os.replace.

    Once ``os.replace`` commits, directory fsync is best effort only: a
    failure there must not make the caller revert memory, because disk is
    already new and reverting would create a memory/disk fork.
    """
    target = Path(path)
    tmp = target.with_name(f"{target.name}.migration.tmp")
    replace_committed = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        replace_committed = True
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise AtomicConfigWriteError(f"atomic config write failed: {exc}") from exc

    # Best-effort durability of the directory entry. A failure here must not
    # be reported as a failed migration, because the target file is already
    # replaced.
    try:
        dir_fd = os.open(target.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
    finally:
        os.close(dir_fd)
    if not replace_committed:  # pragma: no cover - defensive invariant
        raise AtomicConfigWriteError("os.replace did not commit")


__all__ = ["AtomicConfigWriteError", "atomic_write_json"]