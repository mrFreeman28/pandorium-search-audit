#!/usr/bin/env python3
"""Offline source and ZIP format checks derived from current official docs."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def _load_pack_module():
    path = ROOT / "scripts" / "package.py"
    spec = importlib.util.spec_from_file_location("pandorium_search_audit_pack", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load packaging module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACK = _load_pack_module()


def _require(condition: bool, message: str, errors: List[str]) -> None:
    if not condition:
        errors.append(message)


def _json(path: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)}: top level must be an object")
        return {}
    return value


def verify_source() -> List[str]:
    errors: List[str] = []
    portable = _json(ROOT / "plugin.json", errors)
    claude = _json(ROOT / ".claude-plugin" / "plugin.json", errors)
    for label, manifest in (("portable", portable), ("claude", claude)):
        _require(manifest.get("name") == "pandorium-search-audit", f"{label}: stable kebab-case name missing", errors)
        _require(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))), f"{label}: semantic version missing", errors)
        _require(bool(str(manifest.get("description", "")).strip()), f"{label}: description missing", errors)
        _require(isinstance(manifest.get("author"), dict) and bool(manifest.get("author", {}).get("name")), f"{label}: author.name missing", errors)
        _require(manifest.get("license") == "MIT", f"{label}: explicit MIT license identifier missing", errors)
    _require(portable.get("$schema") == SCHEMA, "portable: official Agent Plugins schema URL missing", errors)
    extension = portable.get("extensions", {}).get("com.openai", {}) if isinstance(portable.get("extensions"), dict) else {}
    interface = extension.get("interface", {}) if isinstance(extension, dict) else {}
    limits = {"displayName": 30, "shortDescription": 30, "longDescription": 4000, "developerName": 80}
    for field, limit in limits.items():
        value = interface.get(field)
        _require(isinstance(value, str) and 0 < len(value) <= limit, f"openai interface: {field} must be 1-{limit} characters", errors)
    _require(interface.get("category") in {"Productivity", "Developer Tools"}, "openai interface: category must be a current documented dashboard category example", errors)
    capabilities = interface.get("capabilities")
    _require(isinstance(capabilities, list) and 0 < len(capabilities) <= 20 and all(isinstance(item, str) and 0 < len(item) <= 120 for item in capabilities), "openai interface: capabilities invalid", errors)
    prompts = interface.get("defaultPrompt")
    _require(isinstance(prompts, list) and 0 < len(prompts) <= 3 and len(set(prompts)) == len(prompts) and all(isinstance(item, str) and 0 < len(item) <= 128 for item in prompts), "openai interface: defaultPrompt invalid", errors)
    for field in ("composerIcon", "logo"):
        value = interface.get(field)
        _require(isinstance(value, str) and value.startswith("./") and (ROOT / value[2:]).is_file(), f"openai interface: {field} path invalid", errors)

    icon_path = ROOT / "assets" / "pandorium-icon-orbit.svg"
    try:
        icon = icon_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"icon missing: {exc}")
        icon = ""
    viewbox = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*"', icon)
    _require(bool(viewbox) and float(viewbox.group(1)) == float(viewbox.group(2)) and float(viewbox.group(1)) >= 48 if viewbox else False, "icon: square viewBox of at least 48 by 48 required", errors)
    _require(icon_path.stat().st_size <= 5 * 1024 * 1024 if icon_path.exists() else False, "icon: exceeds 5 MiB", errors)

    skill_path = ROOT / "skills" / "pandorium-search-audit" / "SKILL.md"
    try:
        skill = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"skill missing: {exc}")
        skill = ""
    frontmatter = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
    _require(frontmatter is not None, "skill: YAML frontmatter missing", errors)
    if frontmatter:
        _require(re.search(r"^name:\s*pandorium-search-audit\s*$", frontmatter.group(1), re.M) is not None, "skill: name missing", errors)
        _require(re.search(r"^description:\s*\S", frontmatter.group(1), re.M) is not None, "skill: description missing", errors)

    helper_path = ROOT / "skills" / "pandorium-search-audit" / "scripts" / "search_audit.py"
    try:
        helper = helper_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"helper missing: {exc}")
        helper = ""
    forbidden_imports = (
        r"^\s*(?:from|import)\s+urllib\.request\b",
        r"^\s*(?:from|import)\s+requests\b",
        r"^\s*(?:from|import)\s+httpx\b",
        r"^\s*(?:from|import)\s+socket\b",
        r"^\s*(?:from|import)\s+subprocess\b",
        r"^\s*(?:from|import)\s+selenium\b",
        r"^\s*(?:from|import)\s+playwright\b",
    )
    for pattern in forbidden_imports:
        _require(re.search(pattern, helper, re.M) is None, f"helper: forbidden network or process import matching {pattern!r}", errors)

    _require(claude.get("icon") == "./assets/pandorium-icon-orbit.svg", "claude: icon path missing", errors)
    _require(not any(key in claude for key in ("mcpServers", "hooks", "commands", "agents", "userConfig")), "claude: skills-only manifest contains unsupported dependency surfaces", errors)
    marketplace = _json(ROOT / ".claude-plugin" / "marketplace.json", errors)
    _require(marketplace.get("name") == "pandorium-search-audit", "claude marketplace: name missing", errors)
    _require(isinstance(marketplace.get("owner"), dict) and bool(marketplace.get("owner", {}).get("name")), "claude marketplace: owner.name missing", errors)
    entries = marketplace.get("plugins")
    _require(isinstance(entries, list) and len(entries) == 1, "claude marketplace: exactly one plugin entry required", errors)
    if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict):
        _require(entries[0].get("name") == claude.get("name"), "claude marketplace: entry and manifest names differ", errors)
        _require(entries[0].get("source") == ".", "claude marketplace: standalone-repository plugin source must be '.'", errors)
    _require((ROOT / "LICENSE").is_file(), "MIT LICENSE file missing", errors)
    return errors


def verify_archives(output_dir: Path) -> List[str]:
    errors: List[str] = []
    for target, expected_members in PACK.PACKAGE_FILES.items():
        path = output_dir / PACK.archive_name(target)
        if not path.is_file():
            errors.append(f"archive missing: {path}")
            continue
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            _require(names == sorted(expected_members), f"{target}: ZIP members differ from allow-list", errors)
            for info in archive.infolist():
                _require(info.date_time == PACK.FIXED_TIMESTAMP, f"{target}: non-deterministic timestamp for {info.filename}", errors)
                _require(not info.filename.startswith("/") and ".." not in Path(info.filename).parts, f"{target}: unsafe ZIP member {info.filename}", errors)
                mode = (info.external_attr >> 16) & 0o170000
                _require(mode != 0o120000, f"{target}: symlink member forbidden: {info.filename}", errors)
                _require(info.file_size <= 3 * 1024 * 1024, f"{target}: oversized member {info.filename}", errors)
                source = ROOT / info.filename
                _require(source.is_file() and archive.read(info.filename) == source.read_bytes(), f"{target}: archived bytes differ from source for {info.filename}", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(ROOT / "dist"))
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    errors = verify_source()
    if not args.source_only:
        errors.extend(verify_archives(Path(args.output_dir)))
    if errors:
        for item in errors:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1
    scope = "source" if args.source_only else "source and archives"
    print(f"PASS: {scope} satisfy the documented bounded checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
