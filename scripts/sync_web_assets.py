"""Sync the standalone WebUI sources under ``web/`` into AstrBot plugin pages.

``web/`` is the single source of truth for the control console.  This script
copies the shared assets into ``pages/control/`` so the standalone HTTP server
and the AstrBot plugin-page bridge serve identical code.

``index.html`` is copied with an asset-URL rewrite: the standalone host serves
``/assets/...`` while the plugin-page host serves ``./...``.  The rewritten
output is hashed against ``web/index.html`` with the same rewrite applied, so
both hosts always render the same console (3.1.428: they had silently drifted
whenever only app.js was synced).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PLUGIN_ROOT / "web"
PAGES_DIR = PLUGIN_ROOT / "pages" / "control"
SHARED_FILES = ("app.js", "app.css", "theme.js")
INDEX_NAME = "index.html"
_ASSET_BASE_RE = '"/assets/'


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_plugin_page_index(web_index: Path) -> bytes:
    """Return the plugin-page flavor of ``web/index.html``.

    Rewrites the asset base to ``./`` and injects the plugin-page bridge
    script that the standalone host does not need.
    """

    text = web_index.read_text(encoding="utf-8")
    text = text.replace(_ASSET_BASE_RE, '"./')
    bridge = '<script src="/api/plugin/page/bridge-sdk.js"></script>\n'
    if "bridge-sdk.js" not in text:
        text = text.replace("</head>", f"    {bridge}</head>", 1)
    return text.encode("utf-8")


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
    index_source = web_dir / INDEX_NAME
    index_target = pages_dir / INDEX_NAME
    expected = render_plugin_page_index(index_source)
    if not index_target.is_file() or index_target.read_bytes() != expected:
        index_target.write_bytes(expected)
        copied.append(INDEX_NAME)
    return copied


def verify_hashes(web_dir: Path = WEB_DIR, pages_dir: Path = PAGES_DIR) -> None:
    mismatched = [
        filename
        for filename in SHARED_FILES
        if file_sha256(web_dir / filename) != file_sha256(pages_dir / filename)
    ]
    expected_index = render_plugin_page_index(web_dir / INDEX_NAME)
    if (pages_dir / INDEX_NAME).read_bytes() != expected_index:
        mismatched.append(INDEX_NAME)
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
