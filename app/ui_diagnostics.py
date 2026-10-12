"""Read-only helper diagnosis and explicit, safe export of SuperRender logs."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


def helper_diagnostics(helper: Path, telemetry: Path | None = None) -> dict:
    helper = Path(helper)
    data = {"helper_exists": helper.is_file(), "sha256": None,
            "status": "missing", "last_error": None}
    if helper.is_file():
        data["sha256"] = hashlib.sha256(helper.read_bytes()).hexdigest()
        data["status"] = "available"
    if telemetry is not None and Path(telemetry).is_file():
        try:
            record = json.loads(Path(telemetry).read_text(encoding="utf-8"))
            data["status"] = str(record.get("status") or data["status"])
            data["last_error"] = record.get("message") if record.get("status") == "error" else None
        except (OSError, ValueError, TypeError):
            data["last_error"] = "Falha ao interpretar telemetria"
    return data


def export_logs(target: Path, source_dir: Path, *, max_bytes: int = 10_000_000) -> int:
    """Export ONLY JSON, CSV, LOG and TXT from an app-owned log directory.

    Avoid absolute paths or user-selected unrelated files in the archive.
    """
    target = Path(target)
    root = Path(source_dir).resolve()
    files = []
    if not root.is_dir():
        return 0
    for path in root.rglob("*"):
        if (path.is_file() and not path.is_symlink()
                and path.suffix.casefold() in (".json", ".csv", ".log", ".txt")
                and path.stat().st_size <= max_bytes):
            files.append(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    return len(files)
