"""Sync the standalone WebUI sources under ``web/`` into AstrBot plugin pages.

``web/`` is the single source of truth for the control console.  This script
copies the shared assets into ``pages/control/`` so the standalone HTTP server
and the AstrBot plugin-page bridge serve identical code.  ``index.html`` is
intentionally not copied because the two hosts use different asset URL bases.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PLUGIN_ROOT / "web"
PAGES_DIR = PLUGIN_ROOT / "pages" / "control"
SHARED_FILES = ("app.js", "app.css", "theme.js")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_web_assets(
    web_dir: Path = WEB_DIR,
    pages_dir: Path = PAGES_DIR,
) -> list[str]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for filename in SHARED_FILES:
        source = web_dir / filename
        target = pages_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"missing WebUI source asset: {source}")
        source_bytes = source.read_bytes()
        if not target.is_file() or target.read_bytes() != source_bytes:
            target.write_bytes(source_bytes)
            copied.append(filename)
    return copied


def verify_hashes(web_dir: Path = WEB_DIR, pages_dir: Path = PAGES_DIR) -> None:
    mismatched = [
        filename
        for filename in SHARED_FILES
        if file_sha256(web_dir / filename) != file_sha256(pages_dir / filename)
    ]
    if mismatched:
        raise SystemExit(
            "WebUI asset hash mismatch after sync: " + ", ".join(mismatched)
        )


def main() -> None:
    copied = sync_web_assets()
    verify_hashes()
    if copied:
        print("Synced WebUI assets:", ", ".join(copied))
    else:
        print("WebUI assets already in sync.")


if __name__ == "__main__":
    main()
