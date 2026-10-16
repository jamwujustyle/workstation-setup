"""Curated GNOME preferences. Importing this module never changes settings."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

_EXTENSION_SCHEMAS = {
    "org.gnome.shell.extensions.clipboard-indicator": "clipboard-indicator@tudmotu.com",
    "org.gnome.shell.extensions.dash-to-dock": "ubuntu-dock@ubuntu.com",
    "org.gnome.shell.extensions.ding": "ding@rastersoft.com",
    "org.gnome.shell.extensions.tiling-assistant": "tiling-assistant@ubuntu.com",
}
_CLIPBOARD = "clipboard-indicator@tudmotu.com"
_PROFILES_PATH = "/org/gnome/terminal/legacy/profiles:/"


def _gi():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        return Gio, GLib
    except (ImportError, ValueError) as exc:
        raise RuntimeError("GNOME settings require system Python with python3-gi.") from exc


def _data_dirs() -> list[Path]:
    roots = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))]
    roots.extend(Path(x) for x in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if x)
    return list(dict.fromkeys(roots))


def _installed_extensions() -> dict[str, tuple[dict, Path]]:
    found = {}
    for root in _data_dirs():
        for path in sorted((root / "gnome-shell/extensions").glob("*/metadata.json")):
            try:
                item = json.loads(path.read_text())
                uuid = item["uuid"]
                if isinstance(uuid, str) and uuid == path.parent.name:
                    found.setdefault(uuid, (item, path.parent))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return found


def _source():
    Gio, _ = _gi()
    source = Gio.SettingsSchemaSource.get_default()
    for _, path in reversed(list(_installed_extensions().values())):
        directory = path / "schemas"
        if (directory / "gschemas.compiled").is_file():
            try:
                source = Gio.SettingsSchemaSource.new_from_directory(str(directory), source, False)
            except Exception:
                continue
    return source


def _compatible_extensions() -> tuple[set[str], str | None]:
    try:
        result = subprocess.run(["gnome-shell", "--version"], capture_output=True, text=True, timeout=10, check=True)
        match = re.search(r"\b(\d+)\.(\d+)", result.stdout)
        if not match:
            return set(), "GNOME Shell version is unavailable"
        major, minor = match.groups()
        version = major if int(major) >= 40 else f"{major}.{minor}"
    except (OSError, subprocess.SubprocessError):
        return set(), "GNOME Shell is unavailable"
    available = set()
    for uuid, (meta, _) in _installed_extensions().items():
        versions = meta.get("shell-version", [])
        if isinstance(versions, list) and version in versions:
            available.add(uuid)
    return available, None


def _manifest(repo: Path) -> dict:
    data = json.loads((repo / "config/desktop.json").read_text())
    if not isinstance(data.get("settings"), list):
        raise ValueError("Desktop manifest must contain a settings list.")
    return data


def _label(row: dict) -> str:
    return f"{row.get('schema', '?')}:{row.get('key', '?')}"


def _setting(source, row: dict):
    Gio, _ = _gi()
    schema = source.lookup(row["schema"], True) if source else None
    if not schema:
        raise ValueError(f"{_label(row)}: schema unavailable")
    if not schema.has_key(row["key"]):
        raise ValueError(f"{_label(row)}: key unavailable")
    path = row["path"]
    if not isinstance(path, str) or not path.startswith("/") or not path.endswith("/") or "//" in path:
        raise ValueError(f"{_label(row)}: invalid settings path")
    fixed = schema.get_path()
    if fixed and fixed != path:
        raise ValueError(f"{_label(row)}: path does not match schema")
    return Gio.Settings.new_full(schema, None, path), schema.get_key(row["key"])


def _variant(text: str, schema_key, row: dict):
    _, GLib = _gi()
    try:
        value = GLib.Variant.parse(schema_key.get_value_type(), text, None, None)
    except Exception as exc:
        raise ValueError(f"{_label(row)}: invalid variant") from exc
    if not schema_key.range_check(value):
        raise ValueError(f"{_label(row)}: value is outside schema range")
    return value


def _explicit(setting, key: str) -> str | None:
    value = setting.get_user_value(key)
    return None if value is None else value.print_(True)


def _profile(source) -> str | None:
    row = {"schema": "org.gnome.Terminal.ProfilesList", "key": "default", "path": _PROFILES_PATH}
    try:
        settings, _ = _setting(source, row)
        profile = settings.get_string("default")
        UUID(profile)
        if profile not in settings.get_strv("list"):
            return None
        return profile
    except (ValueError, TypeError):
        return None


def _theme_exists(name: str, kind: str) -> bool:
    if not isinstance(name, str) or "/" in name or name in ("", ".", ".."):
        return False
    roots = [p / kind for p in _data_dirs()]
    roots += [Path.home() / (".themes" if kind == "themes" else ".icons")]
    return any((p / name).is_dir() for p in roots)


def _app_exists(app: str) -> bool:
    if not isinstance(app, str) or "/" in app or not app.endswith(".desktop"):
        return False
    Gio, _ = _gi()
    try:
        return Gio.DesktopAppInfo.new(app) is not None
    except (AttributeError, TypeError):
        return any((root / "applications" / app).is_file() for root in _data_dirs())


def validate(repo: Path) -> dict[str, Any]:
    """Check captured variants against available schemas; never read private state."""
    source = _source()
    checked = 0
    skipped = []
    for row in _manifest(repo)["settings"]:
        schema = source.lookup(row["schema"], True) if source else None
        if not schema or not schema.has_key(row["key"]):
            skipped.append(f"{_label(row)}: schema or key unavailable")
            continue
        key = schema.get_key(row["key"])
        if key.get_value_type().dup_string() != row["type"]:
            raise ValueError(f"{_label(row)}: captured type differs from installed schema")
        _variant(row["value"], key, row)
        checked += 1
    return {"checked": checked, "skipped": skipped}


def plan(repo: Path) -> tuple[list[dict], list[str]]:
    """Return a deterministic plan. Existing values remain only in its private backup."""
    _, GLib = _gi()
    source = _source()
    compatible, version_error = _compatible_extensions()
    profile = _profile(source)
    changes, skipped = [], []
    seen = set()
    for captured in _manifest(repo)["settings"]:
        row = dict(captured)
        name, key = row["schema"], row["key"]
        if name == "org.gnome.Terminal.ProfilesList":
            skipped.append(f"{_label(row)}: keep destination profile list and default")
            continue
        if name == "org.gnome.Terminal.Legacy.Profile":
            if profile is None:
                skipped.append(f"{_label(row)}: no valid destination default profile")
                continue
            row["path"] = _PROFILES_PATH + ":" + profile + "/"
        dependency = _EXTENSION_SCHEMAS.get(name)
        if name == "org.gnome.shell.keybindings" and key == "toggle-message-tray":
            dependency = _CLIPBOARD
        if dependency and dependency not in compatible:
            skipped.append(f"{_label(row)}: compatible {dependency} is required" + (f" ({version_error})" if version_error else ""))
            continue
        try:
            settings, schema_key = _setting(source, row)
        except ValueError as exc:
            skipped.append(str(exc))
            continue
        if schema_key.get_value_type().dup_string() != row["type"]:
            skipped.append(f"{_label(row)}: destination type differs")
            continue
        value = _variant(row["value"], schema_key, row)
        if name == "org.gnome.desktop.interface" and key in ("gtk-theme", "icon-theme", "cursor-theme"):
            kind = "themes" if key == "gtk-theme" else "icons"
            if not _theme_exists(value.unpack(), kind):
                skipped.append(f"{_label(row)}: requested theme is not installed")
                continue
        if name == "org.gnome.shell" and key == "enabled-extensions":
            selected = []
            for uuid in value.unpack():
                if uuid in compatible:
                    selected.append(uuid)
                else:
                    skipped.append(f"{_label(row)}: {uuid} is unavailable or incompatible")
            merged = list(dict.fromkeys(settings.get_strv(key) + selected))
            value = GLib.Variant("as", merged)
        if name == "org.gnome.shell" and key == "favorite-apps":
            selected = []
            for app in value.unpack():
                if _app_exists(app):
                    selected.append(app)
                else:
                    skipped.append(f"{_label(row)}: {app} is not installed")
            merged = list(dict.fromkeys(selected + settings.get_strv(key)))
            value = GLib.Variant("as", merged)
        if not settings.is_writable(key):
            skipped.append(f"{_label(row)}: setting is locked")
            continue
        identity = name, row["path"], key
        if identity in seen:
            raise ValueError(f"{_label(row)}: duplicate planned setting")
        seen.add(identity)
        if settings.get_value(key).equal(value):
            continue
        changes.append({"schema": name, "path": row["path"], "key": key,
                        "before": _explicit(settings, key), "after": value.print_(True)})
    return changes, skipped


def _preflight(changes: list[dict], reverse: bool):
    source = _source()
    prepared = []
    seen = set()
    rows = list(reversed(changes)) if reverse else changes
    for row in rows:
        identity = row["schema"], row["path"], row["key"]
        if identity in seen:
            raise ValueError(f"{_label(row)}: duplicate change")
        seen.add(identity)
        settings, schema_key = _setting(source, row)
        for text in (row["before"], row["after"]):
            if text is not None:
                _variant(text, schema_key, row)
        if not settings.is_writable(row["key"]):
            raise RuntimeError(f"{_label(row)}: setting is locked")
        expected = row["after"] if reverse else row["before"]
        target = row["before"] if reverse else row["after"]
        if _explicit(settings, row["key"]) != expected:
            raise RuntimeError(f"{_label(row)}: setting changed since the plan; re-plan before writing")
        prepared.append((row, settings, schema_key, expected, target))
    return prepared


def preflight(changes: list[dict], reverse: bool = False) -> None:
    """Check all writes without mutating; useful before a combined files/settings restore."""
    _preflight(changes, reverse)


def _write(settings, schema_key, row: dict, target: str | None) -> None:
    Gio, _ = _gi()
    if target is None:
        settings.reset(row["key"])
    elif not settings.set_value(row["key"], _variant(target, schema_key, row)):
        raise RuntimeError(f"{_label(row)}: setting write was rejected")
    Gio.Settings.sync()
    if _explicit(settings, row["key"]) != target:
        raise RuntimeError(f"{_label(row)}: setting write could not be verified")


def apply(changes: list[dict], reverse: bool = False) -> int:
    """Apply guarded writes; recover completed writes on failure without overwriting races."""
    prepared = _preflight(changes, reverse)
    completed = []
    try:
        for row, settings, schema_key, expected, target in prepared:
            if _explicit(settings, row["key"]) != expected:
                raise RuntimeError(f"{_label(row)}: setting changed during apply")
            # Track before writing so a verification failure can also be recovered.
            completed.append((row, settings, schema_key, expected, target))
            _write(settings, schema_key, row, target)
    except Exception as exc:
        failed_recovery = []
        for row, settings, schema_key, expected, target in reversed(completed):
            current = _explicit(settings, row["key"])
            if current == expected:
                continue
            if current != target:
                failed_recovery.append(_label(row))
                continue
            try:
                _write(settings, schema_key, row, expected)
            except Exception:
                failed_recovery.append(_label(row))
        if failed_recovery:
            raise RuntimeError("Desktop apply failed; recovery needs review for: " + ", ".join(failed_recovery)) from exc
        raise RuntimeError("Desktop apply failed; completed changes were restored.") from exc
    return len(completed)


def pending_rollback(changes: list[dict]) -> list[dict]:
    """Return applied rows; tolerate already-restored rows and reject unrelated edits."""
    source = _source()
    pending = []
    for row in changes:
        settings, schema_key = _setting(source, row)
        for text in (row["before"], row["after"]):
            if text is not None:
                _variant(text, schema_key, row)
        current = _explicit(settings, row["key"])
        if current == row["before"]:
            continue
        if current != row["after"]:
            raise RuntimeError(f"{_label(row)}: changed after setup; rollback would overwrite an unrelated edit")
        pending.append(row)
    return pending
