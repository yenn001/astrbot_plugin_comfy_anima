"""Versioned prompt resources with one deterministic resolution path.

Each ``prompts/*.txt`` file starts with a machine-readable header::

    # prompt_id: director_semantic_redraw
    # prompt_role: director_task
    # prompt_version: 1

``PromptCatalog`` scans one directory only. It never reads ``legacy/`` and
never falls back silently: a missing file, duplicate id, missing header or
invalid version is a loud ``PromptCatalogError``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_HEADER_LINE_RE = re.compile(r"^#\s*(?P<key>prompt_id|prompt_role|prompt_version)\s*:\s*(?P<value>.+?)\s*$")

_DEFAULT_HEADER: dict[str, str] = {
    "prompt_id": "",
    "prompt_role": "",
    "prompt_version": "",
}


class PromptCatalogError(RuntimeError):
    """Raised when a prompt resource cannot be loaded deterministically."""


@dataclass(frozen=True, slots=True)
class PromptResource:
    """One parsed prompt file."""

    prompt_id: str
    role: str
    version: int
    path: Path
    sha256: str
    text: str

    @property
    def sha256_prefix(self) -> str:
        return self.sha256[:12]


@dataclass(frozen=True, slots=True)
class EffectivePrompt:
    """The resolved prompt text actually used for one role."""

    source: str
    prompt_id: str
    version: int
    sha256_prefix: str
    text: str


def strip_prompt_header(text: str) -> str:
    """Remove only the initial contiguous ``#`` metadata header block."""

    lines = text.splitlines()
    index = 0
    while index < len(lines) and lines[index].lstrip().startswith("#"):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    return "\n".join(lines[index:])


def _parse_header(text: str, path: Path) -> dict[str, str]:
    header: dict[str, str] = dict(_DEFAULT_HEADER)
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        match = _HEADER_LINE_RE.match(line)
        if match is None:
            continue
        key = match.group("key")
        value = match.group("value").strip()
        if key in header:
            header[key] = value
    missing = [key for key, value in header.items() if not value]
    if missing:
        raise PromptCatalogError(
            f"prompt resource {path} missing header fields: {', '.join(missing)}"
        )
    try:
        version = int(header["prompt_version"])
    except ValueError as exc:
        raise PromptCatalogError(
            f"prompt resource {path} has invalid prompt_version"
        ) from exc
    if version <= 0:
        raise PromptCatalogError(
            f"prompt resource {path} must have prompt_version >= 1"
        )
    return {**header, "prompt_version": str(version)}


class PromptCatalog:
    """Load and resolve versioned prompt resources from one directory."""

    def __init__(self, prompts_dir: Path | str) -> None:
        self._dir = Path(prompts_dir)
        self._resources: dict[str, PromptResource] = {}
        if not self._dir.is_dir():
            raise PromptCatalogError(f"prompt directory does not exist: {self._dir}")
        for path in sorted(self._dir.glob("*.txt")):
            if "legacy" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise PromptCatalogError(f"unable to read prompt resource {path}") from exc
            header = _parse_header(text, path)
            prompt_id = header["prompt_id"]
            if prompt_id in self._resources:
                raise PromptCatalogError(
                    f"duplicate prompt_id {prompt_id!r} in {path}"
                )
            self._resources[prompt_id] = PromptResource(
                prompt_id=prompt_id,
                role=header["prompt_role"],
                version=int(header["prompt_version"]),
                path=path,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                text=strip_prompt_header(text).strip(),
            )

    def get(self, prompt_id: str) -> PromptResource:
        try:
            return self._resources[str(prompt_id)]
        except KeyError as exc:
            raise PromptCatalogError(f"unknown prompt_id: {prompt_id!r}") from exc

    def effective(
        self,
        *,
        role: str,
        settings: object,
        default_prompt_id: str,
        config_text: str = "",
    ) -> EffectivePrompt:
        """Resolve config text first, then the catalog file.

        ``config_text`` comes from the role-specific PluginSettings field.
        An empty config value falls back to the default file resource.
        """
        if str(config_text or "").strip():
            digest = hashlib.sha256(
                str(config_text).encode("utf-8")
            ).hexdigest()
            return EffectivePrompt(
                source=f"config:{role}",
                prompt_id="",
                version=0,
                sha256_prefix=digest[:12],
                text=str(config_text),
            )
        resource = self.get(default_prompt_id)
        return EffectivePrompt(
            source=f"file:{resource.path.as_posix()}",
            prompt_id=resource.prompt_id,
            version=resource.version,
            sha256_prefix=resource.sha256_prefix,
            text=resource.text,
        )

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "prompt_id": resource.prompt_id,
                "role": resource.role,
                "version": resource.version,
                "sha256": resource.sha256,
                "path": resource.path.as_posix(),
            }
            for resource in sorted(
                self._resources.values(), key=lambda item: item.prompt_id
            )
        ]

    def resources(self) -> Iterable[PromptResource]:
        return sorted(self._resources.values(), key=lambda item: item.prompt_id)


__all__ = [
    "EffectivePrompt",
    "PromptCatalog",
    "PromptCatalogError",
    "PromptResource",
    "strip_prompt_header",
]
