"""Versioned, checksum-verified storage for trained model artifacts.

Layout (backend/artifacts/fraud/ is git-ignored):

    artifacts/fraud/<model_name>/versions/<version>/model.joblib       the fitted pipeline (preprocessing + classifier)
                                                   /metadata.json      provenance, split, metrics, threshold, checksum
                                                   /report.md          human-readable evaluation
                                                   /confusion_matrix.png
    artifacts/fraud/<model_name>/current.json                          {"version": ..., "history": [...]}  (the live pointer)

Rules:
  * A candidate is saved first and PROMOTED only after it passes validation, so the last known-good model is never overwritten.
    Old versions stay on disk; `rollback` re-points `current.json` at the previous one.
  * joblib/pickle files can run code when loaded. They are only ever loaded from this folder, only for a version name that
    matches a strict pattern (no path tricks), and only after the SHA-256 recorded at training time matches the file.
  * `load_current` reports one honest state: ready, not_trained, artifact_missing, schema_incompatible or failed_validation.
"""
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "fraud"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{1,60}$")

READY, NOT_TRAINED, ARTIFACT_MISSING, SCHEMA_INCOMPATIBLE, FAILED_VALIDATION = (
    "ready", "not_trained", "artifact_missing", "schema_incompatible", "failed_validation")
STATES = (READY, NOT_TRAINED, ARTIFACT_MISSING, SCHEMA_INCOMPATIBLE, FAILED_VALIDATION)


class RegistryError(Exception):
    pass


@dataclass
class LoadResult:
    state: str
    detail: str = ""
    pipeline: object = None
    metadata: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state == READY


def _check_name(name: str) -> str:
    if not _NAME.match(name or ""):
        raise RegistryError(f"Invalid model name: {name!r}")
    return name


def _check_version(version: str) -> str:
    if not _VERSION.match(version or "") or ".." in version:
        raise RegistryError(f"Invalid model version: {version!r}")
    return version


def model_dir(name: str, root: Path = ARTIFACT_ROOT) -> Path:
    return Path(root) / _check_name(name)


def version_dir(name: str, version: str, root: Path = ARTIFACT_ROOT) -> Path:
    return model_dir(name, root) / "versions" / _check_version(version)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def save_version(name: str, version: str, pipeline, metadata: dict, report_md: str = "", png: Path | None = None,
                 root: Path = ARTIFACT_ROOT) -> Path:
    """Write a candidate version. It is NOT live until `promote` is called."""
    d = version_dir(name, version, root)
    if d.exists():
        raise RegistryError(f"Version {version} of {name} already exists: refusing to overwrite it.")
    d.mkdir(parents=True)
    try:
        joblib.dump(pipeline, d / "model.joblib")
        meta = dict(metadata)
        meta["artifact"] = {"file": "model.joblib", "sha256": sha256_of(d / "model.joblib"), "bytes": (d / "model.joblib").stat().st_size}
        _atomic_write(d / "metadata.json", json.dumps(meta, indent=2, default=str))
        if report_md:
            _atomic_write(d / "report.md", report_md)
        if png and Path(png).exists():
            (d / "confusion_matrix.png").write_bytes(Path(png).read_bytes())
    except Exception:
        import shutil
        shutil.rmtree(d, ignore_errors=True)                 # never leave a half-written version behind
        raise
    return d


def list_versions(name: str, root: Path = ARTIFACT_ROOT) -> list[str]:
    d = model_dir(name, root) / "versions"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []


def read_pointer(name: str, root: Path = ARTIFACT_ROOT) -> dict | None:
    p = model_dir(name, root) / "current.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return {"version": None, "corrupt": True, "history": []}


def promote(name: str, version: str, root: Path = ARTIFACT_ROOT) -> dict:
    """Make `version` the live one. Refuses a version that is missing or whose checksum does not match."""
    d = version_dir(name, version, root)
    meta_path = d / "metadata.json"
    if not meta_path.exists() or not (d / "model.joblib").exists():
        raise RegistryError(f"Cannot promote {name} {version}: its files are missing.")
    meta = json.loads(meta_path.read_text(encoding="utf8"))
    if meta.get("artifact", {}).get("sha256") != sha256_of(d / "model.joblib"):
        raise RegistryError(f"Cannot promote {name} {version}: the model file does not match its recorded checksum.")
    if not meta.get("validation", {}).get("passed"):
        raise RegistryError(f"Cannot promote {name} {version}: it has not passed validation "
                            f"({meta.get('validation', {}).get('failures')}).")
    old = read_pointer(name, root) or {}
    history = [v for v in ([old.get("version")] + list(old.get("history", []))) if v and v != version][:10]
    pointer = {"version": version, "promoted_at": datetime.now(timezone.utc).isoformat(), "history": history}
    _atomic_write(model_dir(name, root) / "current.json", json.dumps(pointer, indent=2))
    return pointer


def rollback(name: str, root: Path = ARTIFACT_ROOT) -> dict:
    """Point `current` back at the previous validated version (the version being rolled back is dropped from history)."""
    old = read_pointer(name, root)
    if not old or not old.get("history"):
        raise RegistryError(f"{name} has no previous version to roll back to.")
    target = old["history"][0]
    d = version_dir(name, target, root)
    if not (d / "model.joblib").exists():
        raise RegistryError(f"The previous version {target} is no longer on disk.")
    pointer = {"version": target, "promoted_at": datetime.now(timezone.utc).isoformat(), "history": old["history"][1:],
               "rolled_back_from": old.get("version")}
    _atomic_write(model_dir(name, root) / "current.json", json.dumps(pointer, indent=2))
    return pointer


def load_current(name: str, expected_features: list[str] | None = None, root: Path = ARTIFACT_ROOT) -> LoadResult:
    """Load the live version of `name`, or say precisely why it cannot be used. Never raises for an unusable model."""
    try:
        _check_name(name)
    except RegistryError as exc:
        return LoadResult(FAILED_VALIDATION, str(exc))
    pointer = read_pointer(name, root)
    if pointer is None:
        if list_versions(name, root):
            return LoadResult(NOT_TRAINED, "Candidate versions exist but none has been promoted (none passed validation).")
        return LoadResult(NOT_TRAINED, "No model has been trained yet.")
    if pointer.get("corrupt") or not pointer.get("version"):
        return LoadResult(FAILED_VALIDATION, "current.json is unreadable.")
    try:
        d = version_dir(name, pointer["version"], root)
    except RegistryError as exc:
        return LoadResult(FAILED_VALIDATION, str(exc))
    if not (d / "model.joblib").exists() or not (d / "metadata.json").exists():
        return LoadResult(ARTIFACT_MISSING, f"Version {pointer['version']} is listed as live but its files are missing.")
    try:
        meta = json.loads((d / "metadata.json").read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return LoadResult(FAILED_VALIDATION, "metadata.json is unreadable.")
    if sha256_of(d / "model.joblib") != meta.get("artifact", {}).get("sha256"):
        return LoadResult(FAILED_VALIDATION, "The model file does not match the checksum recorded at training time: not loading it.", metadata=meta)
    if not meta.get("validation", {}).get("passed"):
        return LoadResult(FAILED_VALIDATION, "The model did not pass validation.", metadata=meta)
    if expected_features is not None and meta.get("input_features") != expected_features:
        return LoadResult(SCHEMA_INCOMPATIBLE, "The model was trained for a different input schema than the application expects. Retrain it.", metadata=meta)
    try:
        pipeline = joblib.load(d / "model.joblib")        # trusted: our own folder, checksum verified above
    except Exception as exc:
        return LoadResult(FAILED_VALIDATION, f"The model file could not be loaded ({type(exc).__name__}).", metadata=meta)
    return LoadResult(READY, "", pipeline, meta)
