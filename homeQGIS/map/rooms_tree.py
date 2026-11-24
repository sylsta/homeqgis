"""Checkable rooms tree: "All rooms", then the room groups of the groups file.

Shared by the status panel (rooms to clean) and the schedule editor. A group
line ticks or unticks its rooms (partial when only some are ticked); a room
listed in several groups is the same room, ticked everywhere at once.
The order in which rooms were ticked is kept (for "clean in this order").
"""

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QTreeWidgetItem
from qgis.core import QgsSettings

from . import room_groups
from ..core.i18n import tr

ID_ROLE = Qt.ItemDataRole.UserRole


class RoomsTree(QObject):
    checkedChanged = pyqtSignal()

    def __init__(self, tree, expanded_key=None, parent=None):
        """tree: a QTreeWidget. expanded_key: QgsSettings prefix remembering which
        groups are open (None: groups holding ticked rooms are opened)."""
        super().__init__(parent or tree)
        self.tree = tree
        self.rows = []        # [(segment id, name)], sorted by name
        self.groups = []      # [(title, [entry, …])] from the groups file
        self.checked = []     # ticked segment ids, in the order they were ticked
        self._expanded_key = expanded_key
        self._syncing = False
        tree.setHeaderHidden(True)
        tree.setColumnCount(1)
        tree.itemChanged.connect(self._on_item_changed)
        if expanded_key:
            tree.itemExpanded.connect(lambda item: self._remember(item, True))
            tree.itemCollapsed.connect(lambda item: self._remember(item, False))

    # -- content ----------------------------------------------------------------------

    def set_rooms(self, rows):
        self.rows = list(rows)
        known = {seg_id for seg_id, _ in self.rows}
        self.checked = [s for s in self.checked if s in known]
        self.rebuild()

    def set_groups(self, groups):
        self.groups = list(groups)
        self.rebuild()

    def set_checked(self, ids):
        self.checked = [str(s) for s in ids]
        self.rebuild()
        self.checkedChanged.emit()

    def uncheck(self, ids):
        self.checked = [s for s in self.checked if s not in set(ids)]
        self.rebuild()
        self.checkedChanged.emit()

    def checked_ids(self, ticked_order=False):
        """Ticked rooms, in list order or in the order they were ticked."""
        if ticked_order:
            return list(self.checked)
        ticked = set(self.checked)
        return [seg_id for seg_id, _ in self.rows if seg_id in ticked]

    def name(self, seg_id):
        return dict(self.rows).get(str(seg_id), f"#{seg_id}")

    def clear(self):
        self.rows, self.checked = [], []
        self.rebuild()

    # -- tree -------------------------------------------------------------------------

    def _room_item(self, seg_id, name):
        item = QTreeWidgetItem([name])
        item.setData(0, ID_ROLE, seg_id)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemNeverHasChildren | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsDragEnabled)   # can be dropped on the week view
        # The check state must be set for Qt to draw the checkbox at all.
        item.setCheckState(0, Qt.CheckState.Checked if seg_id in self.checked
                           else Qt.CheckState.Unchecked)
        return item

    @staticmethod
    def _group_item(title):
        # Ticks / unticks its rooms; partial when only some are ticked.
        item = QTreeWidgetItem([title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsDragEnabled)
        return item

    def rebuild(self):
        """"All rooms" first, then the groups of the room groups file, in file order."""
        rows, names = self.rows, dict(self.rows)
        self.tree.blockSignals(True)
        self.tree.clear()
        if rows:
            groups = [(tr("All rooms"), [f"#{seg_id}" for seg_id, _ in rows])] + self.groups
            for title, entries in groups:
                parent = self._group_item(title)
                self.tree.addTopLevelItem(parent)
                seen, has_checked = set(), False
                for entry in entries:
                    seg_id = room_groups.resolve(entry, rows)
                    if seg_id is None:
                        # Typo or room renamed on the robot: show it, greyed.
                        missing = QTreeWidgetItem([f"{entry}  ({tr('not found on the robot')})"])
                        missing.setFlags(Qt.ItemFlag.ItemNeverHasChildren)
                        missing.setToolTip(0, tr("Not found on the robot."))
                        parent.addChild(missing)
                    elif seg_id not in seen:
                        seen.add(seg_id)
                        has_checked |= seg_id in self.checked
                        parent.addChild(self._room_item(seg_id, names[seg_id]))
                if self._expanded_key:
                    parent.setExpanded(QgsSettings().value(
                        f"{self._expanded_key}/{title}", False, type=bool))  # collapsed by default
                else:
                    parent.setExpanded(has_checked)
        self.tree.blockSignals(False)

    def room_items(self):
        """Every room line of the tree (a room can be in several groups)."""
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.data(0, ID_ROLE) is not None:
                    yield child

    def _on_item_changed(self, item, *_):
        """A room line changed: same state for that room in every group, then read back."""
        seg_id = item.data(0, ID_ROLE) if item is not None else None
        if self._syncing or seg_id is None:
            return
        state = item.checkState(0)
        self._syncing = True
        try:
            for other in self.room_items():
                if other is not item and other.data(0, ID_ROLE) == seg_id \
                        and other.checkState(0) != state:
                    other.setCheckState(0, state)
        finally:
            self._syncing = False
        ticked = {child.data(0, ID_ROLE) for child in self.room_items()
                  if child.checkState(0) == Qt.CheckState.Checked}
        # Keep the ticking order: drop unticked rooms, add new ones at the end.
        order = [s for s in self.checked if s in ticked]
        order += [seg_id for seg_id, _ in self.rows if seg_id in ticked and seg_id not in order]
        if seg_id in ticked and seg_id in order:   # the room just ticked goes last
            if seg_id not in self.checked:
                order.remove(seg_id)
                order.append(seg_id)
        self.checked = order
        self.checkedChanged.emit()

    def _remember(self, item, expanded):
        if item.parent() is None:
            QgsSettings().setValue(f"{self._expanded_key}/{item.text(0)}", expanded)
