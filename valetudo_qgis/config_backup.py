"""Save and load the plugin's configuration as timestamped JSON files.

A file holds every QgsSettings value under "valetudo/", the room groups file,
and, only if asked, the tokens and passwords of the QGIS authentication
database (then in clear in the file):

    {"format": "valetudo-qgis-config", "version": 1,
     "saved": "2026-11-18T21:15:00+01:00", "plugin": "0.2.0",
     "settings": {"valetudo/url": "http://192.168.50.20", …},
     "room_groups": "…", "secrets": {"valetudo/ha_token": "…"}}

Loading replaces the settings (keys absent from the file are removed), the room
groups file if the backup has one, and the secrets the backup has.
"""

import json
import os

from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.core import QgsApplication, QgsSettings

from . import room_groups
from .settings import (HA_SSH_PASSWORD_SETTING, HA_TOKEN_SETTING, KODI_PASSWORD_SETTING,
                       secret, set_secret)

FORMAT = "valetudo-qgis-config"
VERSION = 1
GROUP = "valetudo"
PREFIX = "valetudo_qgis_config_"
KEY_BACKUP_DIR = "valetudo/backup_dir"
SECRET_KEYS = (HA_TOKEN_SETTING, HA_SSH_PASSWORD_SETTING, KODI_PASSWORD_SETTING)


def default_folder():
    return os.path.join(QgsApplication.qgisSettingsDirPath(), "valetudo_backups")


def folder():
    return QgsSettings().value(KEY_BACKUP_DIR, "", type=str) or default_folder()


def file_name(now=None):
    """valetudo_qgis_config_20261118_211500.json"""
    now = now or QDateTime.currentDateTime()
    return f"{PREFIX}{now.toString('yyyyMMdd_HHmmss')}.json"


def plugin_version():
    path = os.path.join(os.path.dirname(__file__), "metadata.txt")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _plain(value):
    """A QgsSettings value as JSON (lists kept, anything exotic as text)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


def export(include_secrets=False):
    s = QgsSettings()
    s.beginGroup(GROUP)
    keys = sorted(s.allKeys())
    s.endGroup()
    data = {
        "format": FORMAT, "version": VERSION,
        "saved": QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate),
        "plugin": plugin_version(),
        "settings": {f"{GROUP}/{key}": _plain(s.value(f"{GROUP}/{key}")) for key in keys},
    }
    path = room_groups.file_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            data["room_groups"] = handle.read()
    if include_secrets:
        data["secrets"] = {key: secret(key) for key in SECRET_KEYS if secret(key)}
    return data


def save(target_folder, include_secrets=False):
    """Write a new timestamped file in target_folder; return its path."""
    os.makedirs(target_folder, exist_ok=True)
    path = os.path.join(target_folder, file_name())
    stem, number = path[:-5], 2
    while os.path.exists(path):   # two saves in the same second
        path, number = f"{stem}_{number}.json", number + 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(export(include_secrets), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if include_secrets and not os.name == "nt":
        os.chmod(path, 0o600)   # passwords in clear: readable by this user only
    return path


def backups(target_folder):
    """[(path, saved QDateTime)] of the backups in target_folder, newest first."""
    try:
        names = os.listdir(target_folder)
    except OSError:
        return []
    found = []
    for name in names:
        if name.startswith(PREFIX) and name.endswith(".json"):
            stamp = QDateTime.fromString(name[len(PREFIX):len(PREFIX) + 15], "yyyyMMdd_HHmmss")
            if stamp.isValid():
                found.append((os.path.join(target_folder, name), stamp))
    return sorted(found, key=lambda entry: entry[1].toMSecsSinceEpoch(), reverse=True)


def read(path):
    """The backup's data; ValueError if it is not one."""
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as exc:
            raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Valetudo plugin configuration")
    if not isinstance(data.get("settings"), dict):
        raise ValueError("no settings in the file")
    return data


def reset():
    """Back to the defaults: every plugin setting (except the backup folder), the
    tokens and passwords, and the room groups file, are removed."""
    s = QgsSettings()
    s.beginGroup(GROUP)
    for key in s.allKeys():
        if f"{GROUP}/{key}" != KEY_BACKUP_DIR:
            s.remove(key)
    s.endGroup()
    for key in SECRET_KEYS:
        set_secret(key, "")
    try:
        os.remove(room_groups.file_path())
    except OSError:
        pass


def apply(data):
    """Replace the configuration by the backup's. Returns (settings, secrets) counts;
    secrets that could not be stored (no master password) are not counted."""
    s = QgsSettings()
    s.beginGroup(GROUP)
    for key in s.allKeys():
        if f"{GROUP}/{key}" != KEY_BACKUP_DIR:   # keep where backups are
            s.remove(key)
    s.endGroup()
    count = 0
    for key, value in data["settings"].items():
        if key.startswith(f"{GROUP}/") and key != KEY_BACKUP_DIR:
            s.setValue(key, value)
            count += 1
    groups = data.get("room_groups")
    if isinstance(groups, str):
        with open(room_groups.file_path(), "w", encoding="utf-8") as handle:
            handle.write(groups)
    stored = 0
    for key, value in (data.get("secrets") or {}).items():
        if key in SECRET_KEYS and isinstance(value, str) and set_secret(key, value):
            stored += 1
    return count, stored
