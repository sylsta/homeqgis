"""Room groups for the panel's rooms tree, read from a small text file.

The file lives in the QGIS profile folder (never overwritten by a plugin
update). Format, INI-like but read line by line so room names may contain
any character:

    # comment            (or ; comment)
    [Water]              a group
    Kitchen              one room per line, as named on the robot
    #16                  ...or a room id

Room names are matched without regard to case or surrounding spaces.
"All rooms" is always shown first and is not part of the file.

This module has no user-facing text except the template's comments, which
are written in English on purpose (the file is a technical config file).
"""

import os

from qgis.core import QgsApplication

FILE_NAME = "valetudo_room_groups.ini"

TEMPLATE = """\
# Room groups for the Valetudo panel (QGIS plugin).
#
# One [Group] per section, then one room per line, written as the robot
# names it (case does not matter), or #<id> for a room id.
# Lines starting with # or ; are comments. The panel reloads this file
# as soon as it is saved. "All rooms" is always shown, you don't need it.
#
# Example:
#
# [Water]
# Kitchen
# Bathroom
#
# [Evening]
# Living room
# #16
"""


def file_path():
    return os.path.join(QgsApplication.qgisSettingsDirPath(), FILE_NAME)


def ensure_file():
    """Create the file from the template if it does not exist; return its path."""
    path = file_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(TEMPLATE)
    return path


def parse(text):
    """[(group title, [entry, …]), …] in file order; entries are raw strings."""
    groups = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("#") and not line[1:].strip().isdigit():
            continue   # comment (but "#16" is a room id)
        if line.startswith("[") and line.endswith("]"):
            title = line[1:-1].strip()
            if title:
                groups.append((title, []))
            continue
        if groups:
            groups[-1][1].append(line)
    return groups


def load():
    """Groups from the file, or [] if it does not exist or cannot be read."""
    try:
        with open(file_path(), encoding="utf-8") as handle:
            return parse(handle.read())
    except OSError:
        return []


def resolve(entry, segments):
    """Room id for a file entry, or None. segments: [(id, name), …]."""
    entry = entry.strip()
    if entry.startswith("#") and entry[1:].strip().isdigit():
        wanted = entry[1:].strip()
        return wanted if any(seg_id == wanted for seg_id, _ in segments) else None
    key = entry.casefold()
    for seg_id, name in segments:
        if name.strip().casefold() == key:
            return seg_id
    return None
