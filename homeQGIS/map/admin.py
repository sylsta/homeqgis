"""The robot's map itself: its firmware snapshots, a changed map it found, and
starting it again (Valetudo's capabilities; only what the robot has is offered).

- MapSnapshotCapability: GET -> [{id, timestamp, map?}]; PUT {action: "restore", id}.
- PendingMapChangeHandlingCapability: GET -> {pending}; PUT {action: accept | reject}.
  The robot found that the home has changed and asks whether to keep the new map.
- MappingPassCapability: PUT {action: "start_mapping"}: the robot explores the home
  to draw its map, without cleaning.
- MapResetCapability: PUT {action: "reset"}: the map is deleted, with its rooms,
  names, no-go zones and schedules that use rooms.
"""

from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget,
                                 QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from ..core.i18n import tr

API = "/robot/capabilities/"
SNAPSHOTS = "MapSnapshotCapability"
PENDING = "PendingMapChangeHandlingCapability"
MAPPING_PASS = "MappingPassCapability"
RESET = "MapResetCapability"


def snapshot_label(snapshot):
    stamp = QDateTime.fromString(str(snapshot.get("timestamp") or ""), Qt.DateFormat.ISODate)
    if stamp.isValid():
        return stamp.toLocalTime().toString("dd/MM/yyyy HH:mm")
    return str(snapshot.get("id") or "?")


class SnapshotsDialog(QDialog):
    """The robot's map snapshots: shown on the map (when the robot gives the map with
    them), restored after asking."""

    def __init__(self, client, show_map, parent=None):
        """show_map(map_json, label): draws a snapshot's map (map_layers)."""
        super().__init__(parent)
        self.client, self.show_map = client, show_map
        self.setWindowTitle(tr("Map snapshots"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("The robot keeps copies of its map. Restoring one replaces the "
                          "current map, its rooms and their names."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.status = QLabel(tr("Asking the robot…"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.btn_show = QPushButton(tr("Show on the map"))
        self.btn_restore = QPushButton(tr("Restore…"))
        for button in (self.btn_show, self.btn_restore):
            button.setEnabled(False)
            buttons.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.close)
        self.btn_show.clicked.connect(self._show)
        self.btn_restore.clicked.connect(self._restore)
        self.list.currentItemChanged.connect(self._selected)
        layout.addWidget(buttons)
        self.resize(420, 360)
        client.get_json(API + SNAPSHOTS, self._listed, self._failed)

    def _listed(self, snapshots):
        self.list.clear()
        for snapshot in snapshots if isinstance(snapshots, list) else []:
            item = QListWidgetItem(snapshot_label(snapshot))
            item.setData(Qt.ItemDataRole.UserRole, snapshot)
            self.list.addItem(item)
        self.status.setText(tr("{n} snapshot(s).").format(n=self.list.count())
                            if self.list.count() else tr("The robot has no snapshot."))

    def _failed(self, error):
        self.status.setText(tr("The robot did not answer: {error}").format(error=error))

    def _current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _selected(self, *_):
        snapshot = self._current()
        self.btn_restore.setEnabled(snapshot is not None)
        self.btn_show.setEnabled(bool(snapshot and snapshot.get("map")))

    def _show(self):
        snapshot = self._current()
        if snapshot and snapshot.get("map"):
            self.show_map(snapshot["map"], snapshot_label(snapshot))

    def _restore(self):
        snapshot = self._current()
        if snapshot is None:
            return
        answer = QMessageBox.question(
            self, tr("Restore the map"),
            tr("Replace the robot's map with the one of {date}? Its rooms, their names "
               "and the zones drawn since may change.").format(date=snapshot_label(snapshot)))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.status.setText(tr("Restoring…"))
        self.client.put_json(API + SNAPSHOTS, {"action": "restore", "id": snapshot.get("id")},
                             lambda *_: self.status.setText(tr("Map restored.")),
                             self._failed)


def confirm_mapping_pass(parent):
    return QMessageBox.question(
        parent, tr("New mapping pass"),
        tr("The robot explores the home to draw its map again, without cleaning. Keep "
           "the doors open and the floor clear. Start?")) == QMessageBox.StandardButton.Yes


def confirm_map_reset(parent):
    """Asked twice: nothing brings the map back."""
    first = QMessageBox.warning(
        parent, tr("Reset the map"),
        tr("Delete the robot's map? Its rooms and their names, the no-go zones and "
           "virtual walls, and the schedules that clean given rooms are lost. The robot "
           "draws a new map at its next cleaning or mapping pass."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No)
    if first != QMessageBox.StandardButton.Yes:
        return False
    return QMessageBox.warning(
        parent, tr("Reset the map"), tr("Really delete the map? This cannot be undone."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
