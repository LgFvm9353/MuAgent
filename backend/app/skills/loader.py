import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.skills.contracts import SkillDefinition, SkillManifest


class SkillLoadError(ValueError):
    pass


def _safe_file(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise SkillLoadError(f"invalid skill path: {relative}")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve(strict=True)
    if resolved_root not in resolved.parents:
        raise SkillLoadError(f"skill path escapes root: {relative}")
    if resolved.is_symlink() or not resolved.is_file():
        raise SkillLoadError(f"skill path must be a regular file: {relative}")
    return resolved


def _read_text(root: Path, relative: str) -> str:
    try:
        return _safe_file(root, relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillLoadError(f"cannot read skill file: {relative}") from error


def load_skill(directory: Path) -> SkillDefinition:
    if directory.is_symlink() or not directory.is_dir():
        raise SkillLoadError(f"skill directory is invalid: {directory.name}")
    try:
        raw = yaml.safe_load(_read_text(directory, "skill.yaml"))
        if not isinstance(raw, dict):
            raise SkillLoadError("skill.yaml must contain an object")
        manifest = SkillManifest.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as error:
        raise SkillLoadError(f"invalid skill manifest: {directory.name}") from error
    if manifest.id != directory.name:
        raise SkillLoadError("skill ID must match directory name")

    instructions = _read_text(directory, "SKILL.md").strip()
    if not instructions:
        raise SkillLoadError("SKILL.md must not be empty")
    references = {path: _read_text(directory, path) for path in manifest.references}
    output_schema: dict[str, object] | None = None
    if manifest.output_schema is not None:
        try:
            parsed: Any = json.loads(_read_text(directory, manifest.output_schema))
        except json.JSONDecodeError as error:
            raise SkillLoadError("output schema must be valid JSON") from error
        if not isinstance(parsed, dict):
            raise SkillLoadError("output schema must contain an object")
        output_schema = parsed

    hashed_files = {
        "skill.yaml": json.dumps(raw, ensure_ascii=False, sort_keys=True),
        "SKILL.md": instructions,
        **references,
    }
    if manifest.output_schema is not None and output_schema is not None:
        hashed_files[manifest.output_schema] = json.dumps(output_schema, sort_keys=True)
    digest = hashlib.sha256()
    for path, content in sorted(hashed_files.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")
    return SkillDefinition(
        manifest=manifest,
        instructions=instructions,
        content_hash=digest.hexdigest(),
        references=references,
        output_schema=output_schema,
    )
