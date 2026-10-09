#!/usr/bin/env python3
"""Build reproducible, allow-listed OpenAI and Claude plugin ZIPs."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
COMMON_FILES = (
    "LICENSE",
    "assets/pandorium-icon-orbit.svg",
    "skills/pandorium-search-audit/SKILL.md",
    "skills/pandorium-search-audit/scripts/search_audit.py",
)
PACKAGE_FILES = {
    "openai": ("plugin.json",) + COMMON_FILES,
    "claude": (".claude-plugin/plugin.json",) + COMMON_FILES,
}


def _version() -> str:
    payload = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    return str(payload["version"])


def archive_name(target: str) -> str:
    return f"pandorium-search-audit-{target}-{_version()}.zip"


def _write_zip(destination: Path, members: Iterable[str]) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(members):
            source = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(f"Required package file missing: {relative}")
            info = zipfile.ZipInfo(relative, FIXED_TIMESTAMP)
            info.create_system = 3
            mode = 0o755 if relative.endswith(".py") else 0o644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def build_packages(output_dir: Path) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for target, members in PACKAGE_FILES.items():
        destination = output_dir / archive_name(target)
        digest = _write_zip(destination, members)
        results[target] = {
            "path": str(destination),
            "sha256": digest,
            "bytes": destination.stat().st_size,
            "members": list(sorted(members)),
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(ROOT / "dist"))
    args = parser.parse_args()
    results = build_packages(Path(args.output_dir))
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
