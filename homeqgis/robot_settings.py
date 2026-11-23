"""The robot's own settings, as Valetudo offers them, in the Maintenance tab.

Only what the robot has (its capabilities) is shown:
- switches (Valetudo's SimpleToggleCapability family: GET {enabled}, PUT {action});
- choices (GET {<key>}, GET /properties {supported<Keys>}, PUT {<key>});
- the speaker volume (0-100) and its test sound;
- Do not disturb (enabled, start and end times);
- quirks (robot-specific options Valetudo describes itself: id, title,
  description, options, value).

Values are read when the section is shown (at most every RELOAD_S) and after each
change; a change the robot refuses is put back as it was, with the reason.
"""

import time

from qgis.PyQt.QtCore import Qt, QTime
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                                 QLabel, QPushButton, QSlider, QTimeEdit, QWidget)

from qgis.gui import QgsCollapsibleGroupBox

from .i18n import tr

RELOAD_S = 60
API = "/robot/capabilities/"

# Switches, in this order. (The camera light is in the Camera tab; the persistent map
# is left alone: Valetudo itself advises against turning it off.)
TOGGLES = (
    "KeyLockCapability",
    "ObstacleAvoidanceControlCapability",
    "PetObstacleAvoidanceControlCapability",
    "CollisionAvoidantNavigationControlCapability",
    "CarpetModeControlCapability",
    "FloorMaterialDirectionAwareNavigationControlCapability",
    "MopExtensionControlCapability",
    "MopExtensionFurnitureLegHandlingControlCapability",
    "MopTwistControlCapability",
    "MopDockMopAutoDryingControlCapability",
)
# Choices: capability -> (key of the value, key of the supported values)
CHOICES = {
    "CleanRouteControlCapability": ("route", "supportedRoutes"),
    "CarpetSensorModeControlCapability": ("mode", "supportedModes"),
    "MopDockMopWashTemperatureControlCapability": ("temperature", "supportedTemperatures"),
    "MopDockMopDryingTimeControlCapability": ("duration", "supportedDurations"),
    "AutoEmptyDockAutoEmptyIntervalControlCapability": ("interval", "supportedIntervals"),
    "AutoEmptyDockAutoEmptyDurationControlCapability": ("duration", "supportedDurations"),
}
VOLUME = "SpeakerVolumeControlCapability"
TEST_SOUND = "SpeakerTestCapability"
DND = "DoNotDisturbCapability"
QUIRKS = "QuirksCapability"


def setting_labels():
    return {
        "KeyLockCapability": tr("Child lock"),
        "ObstacleAvoidanceControlCapability": tr("Obstacle avoidance"),
        "PetObstacleAvoidanceControlCapability": tr("Pet waste avoidance"),
        "CollisionAvoidantNavigationControlCapability": tr("Collision-avoidant navigation"),
        "CarpetModeControlCapability": tr("Carpet mode (more suction)"),
        "FloorMaterialDirectionAwareNavigationControlCapability":
            tr("Follow the floor's direction (wood)"),
        "MopExtensionControlCapability": tr("Mop extension (edges)"),
        "MopExtensionFurnitureLegHandlingControlCapability":
            tr("Mop extension around furniture legs"),
        "MopTwistControlCapability": tr("Mop twist"),
        "MopDockMopAutoDryingControlCapability": tr("Automatic mop drying"),
        "CleanRouteControlCapability": tr("Cleaning route"),
        "CarpetSensorModeControlCapability": tr("On carpets"),
        "MopDockMopWashTemperatureControlCapability": tr("Mop wash water"),
        "MopDockMopDryingTimeControlCapability": tr("Mop drying time"),
        "AutoEmptyDockAutoEmptyIntervalControlCapability": tr("Auto-empty"),
        "AutoEmptyDockAutoEmptyDurationControlCapability": tr("Auto-empty duration"),
        VOLUME: tr("Speaker volume"),
        DND: tr("Do not disturb"),
    }


def value_labels():
    """Valetudo's values, readable (unknown ones are shown as they come)."""
    return {
        "normal": tr("Normal"), "quick": tr("Quick"), "intensive": tr("Intensive"),
        "deep": tr("Deep"), "off": tr("Off"), "avoid": tr("Avoid carpets"),
        "lift": tr("Lift the mops"), "detach": tr("Leave the mops in the dock"),
        "cold": tr("Cold"), "warm": tr("Warm"), "hot": tr("Hot"),
        "scalding": tr("Very hot"), "boiling": tr("Boiling"),
        "2h": tr("2 h"), "3h": tr("3 h"), "4h": tr("4 h"), "5h": tr("5 h"),
        "quiet": tr("Quiet"), "auto": tr("Automatic"), "short": tr("Short"),
        "medium": tr("Medium"), "long": tr("Long"), "infrequent": tr("Infrequent"),
        "frequent": tr("Frequent"),
    }


class RobotSettingsBox(QgsCollapsibleGroupBox):
    """Built again for each robot (set_robot); load() reads the values."""

    def __init__(self, parent=None):
        super().__init__(tr("Robot settings"), parent)
        self.client = None
        self.capabilities = set()
        self.form = QFormLayout(self)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: palette(mid);")
        self._widgets = {}   # capability (or quirk id) -> widget
        self._loaded_at = 0.0
        self.setVisible(False)

    # -- building ----------------------------------------------------------------------

    def set_robot(self, client, capabilities):
        self.client, self.capabilities = client, set(capabilities or [])
        while self.form.rowCount():
            self.form.removeRow(0)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self._widgets = {}
        self._loaded_at = 0.0
        labels, caps = setting_labels(), self.capabilities
        for capability in TOGGLES:
            if capability in caps:
                box = QCheckBox(labels[capability])
                box.setEnabled(False)   # until its value is read
                box.toggled.connect(lambda on, c=capability: self._set_toggle(c, on))
                self.form.addRow(box)
                self._widgets[capability] = box
        for capability in CHOICES:
            if capability in caps:
                combo = QComboBox()
                combo.setEnabled(False)
                combo.activated.connect(lambda _i, c=capability: self._set_choice(c))
                self.form.addRow(labels[capability], combo)
                self._widgets[capability] = combo
        if VOLUME in caps:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setEnabled(False)
            slider.sliderReleased.connect(self._set_volume)
            line.addWidget(slider)
            if TEST_SOUND in caps:
                test = QPushButton(tr("Test"))
                test.clicked.connect(self._test_sound)
                line.addWidget(test)
            self.form.addRow(labels[VOLUME], row)
            self._widgets[VOLUME] = slider
        if DND in caps:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            enabled = QCheckBox()
            start, end = QTimeEdit(), QTimeEdit()
            for edit in (start, end):
                edit.setDisplayFormat("HH:mm")
            line.addWidget(enabled)
            line.addWidget(start)
            line.addWidget(QLabel("→"))
            line.addWidget(end)
            line.addStretch(1)
            for widget in (enabled, start, end):
                widget.setEnabled(False)
            enabled.toggled.connect(self._set_dnd)
            start.editingFinished.connect(self._set_dnd)
            end.editingFinished.connect(self._set_dnd)
            self.form.addRow(labels[DND], row)
            self._widgets[DND] = (enabled, start, end)
        self.form.addRow(self.lbl_status)
        self.setVisible(bool(self._widgets) or QUIRKS in caps)

    # -- reading -----------------------------------------------------------------------

    def load(self, force=False):
        """Read every value (when shown; at most every RELOAD_S unless forced)."""
        if self.client is None or not self.isVisible():
            return
        if not force and time.monotonic() - self._loaded_at < RELOAD_S:
            return
        self._loaded_at = time.monotonic()
        for capability in TOGGLES:
            if capability in self._widgets:
                self.client.get_json(API + capability,
                                     lambda d, c=capability: self._show_toggle(c, d),
                                     self._failed)
        for capability in CHOICES:
            if capability in self._widgets:
                self.client.get_json(API + capability + "/properties",
                                     lambda d, c=capability: self._show_options(c, d),
                                     self._failed)
        if VOLUME in self._widgets:
            self.client.get_json(API + VOLUME, self._show_volume, self._failed)
        if DND in self._widgets:
            self.client.get_json(API + DND, self._show_dnd, self._failed)
        if QUIRKS in self.capabilities:
            self.client.get_json(API + QUIRKS, self._show_quirks, self._failed)

    def _show_toggle(self, capability, data):
        box = self._widgets.get(capability)
        if box is None:
            return
        box.blockSignals(True)
        box.setChecked(bool((data or {}).get("enabled")))
        box.blockSignals(False)
        box.setEnabled(True)

    def _show_options(self, capability, data):
        """The supported values first, then the current one."""
        key, supported = CHOICES[capability]
        combo = self._widgets.get(capability)
        if combo is None:
            return
        names = value_labels()
        if capability == "MopDockMopDryingTimeControlCapability":
            names["cold"] = tr("Cold air")   # (not the wash water's "cold")
        combo.blockSignals(True)
        combo.clear()
        for value in (data or {}).get(supported) or []:
            combo.addItem(names.get(value, value), value)
        combo.blockSignals(False)
        self.client.get_json(API + capability, lambda d: self._show_choice(capability, d),
                             self._failed)

    def _show_choice(self, capability, data):
        key, _supported = CHOICES[capability]
        combo = self._widgets.get(capability)
        if combo is None:
            return
        index = combo.findData((data or {}).get(key))
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        combo.setEnabled(combo.count() > 0)

    def _show_volume(self, data):
        slider = self._widgets.get(VOLUME)
        if slider is not None:
            slider.setValue(int((data or {}).get("volume") or 0))
            slider.setEnabled(True)

    def _show_dnd(self, data):
        widgets = self._widgets.get(DND)
        if widgets is None:
            return
        data = data or {}
        enabled, start, end = widgets
        for widget in widgets:
            widget.blockSignals(True)
        enabled.setChecked(bool(data.get("enabled")))
        for edit, key in ((start, "start"), (end, "end")):
            moment = data.get(key) or {}
            edit.setTime(QTime(int(moment.get("hour") or 0), int(moment.get("minute") or 0)))
        for widget in widgets:
            widget.blockSignals(False)
            widget.setEnabled(True)

    def _show_quirks(self, quirks):
        for quirk in quirks if isinstance(quirks, list) else []:
            qid = quirk.get("id")
            if not qid or not quirk.get("options"):
                continue
            combo = self._widgets.get(("quirk", qid))
            if combo is None:   # added the first time, before the status line
                combo = QComboBox()
                combo.activated.connect(lambda _i, q=qid: self._set_quirk(q))
                label = QLabel(str(quirk.get("title") or qid))
                label.setToolTip(str(quirk.get("description") or ""))
                combo.setToolTip(str(quirk.get("description") or ""))
                self.form.insertRow(self.form.rowCount() - 1, label, combo)
                self._widgets[("quirk", qid)] = combo
            combo.blockSignals(True)
            combo.clear()
            for option in quirk["options"]:
                combo.addItem(str(option), option)
            combo.setCurrentIndex(combo.findData(quirk.get("value")))
            combo.blockSignals(False)
        if any(isinstance(k, tuple) for k in self._widgets):
            self.setVisible(True)

    # -- changing --------------------------------------------------------------------------

    def _done(self, *_):
        self.lbl_status.setText(tr("Saved on the robot."))
        self._loaded_at = 0.0
        self.load(force=True)   # what the robot now says

    def _failed(self, error):
        self.lbl_status.setText(tr("The robot did not accept it: {error}").format(error=error))
        self._loaded_at = 0.0
        self.load(force=True)   # back to what it has

    def _set_toggle(self, capability, on):
        self.client.put_json(API + capability, {"action": "enable" if on else "disable"},
                             self._done, self._failed)

    def _set_choice(self, capability):
        key, _supported = CHOICES[capability]
        value = self._widgets[capability].currentData()
        if value is not None:
            self.client.put_json(API + capability, {key: value}, self._done, self._failed)

    def _set_volume(self):
        self.client.put_json(API + VOLUME, {"action": "set_volume",
                                            "value": self._widgets[VOLUME].value()},
                             self._done, self._failed)

    def _test_sound(self):
        self.client.put_json(API + TEST_SOUND, {"action": "play_test_sound"},
                             None, self._failed)

    def _set_dnd(self, *_):
        enabled, start, end = self._widgets[DND]
        self.client.put_json(API + DND, {
            "enabled": enabled.isChecked(),
            "start": {"hour": start.time().hour(), "minute": start.time().minute()},
            "end": {"hour": end.time().hour(), "minute": end.time().minute()},
        }, self._done, self._failed)

    def _set_quirk(self, qid):
        value = self._widgets[("quirk", qid)].currentData()
        if value is not None:
            self.client.put_json(API + QUIRKS, {"id": qid, "value": value},
                                 self._done, self._failed)
