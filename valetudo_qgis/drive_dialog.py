"""Drive the robot by hand (Valetudo's manual control), with the arrow keys or the
buttons, held down.

HighResolutionManualControlCapability: while a direction is held, a movement
vector (velocity -1…1, angle -180…180) is sent every SEND_MS, as Valetudo's own
web interface does; letting go sends a stop. ManualControlCapability (older robots):
a step (forward, backward, rotate) is sent every STEP_MS instead.

Manual control is switched on when the window opens and off when it closes (the
robot then stays where it is: Return to dock sends it home).
"""

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QSlider,
                                 QToolButton, QVBoxLayout)

from .i18n import tr

HIGH_RES = "HighResolutionManualControlCapability"
STEPS = "ManualControlCapability"
SEND_MS = 250
STEP_MS = 500
TURN_ANGLE = 120   # as Valetudo's keyboard control
KEYS = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down", Qt.Key.Key_Left: "left",
        Qt.Key.Key_Right: "right", Qt.Key.Key_W: "up", Qt.Key.Key_S: "down",
        Qt.Key.Key_A: "left", Qt.Key.Key_D: "right",
        Qt.Key.Key_Z: "up", Qt.Key.Key_Q: "left"}   # (Z Q S D on an AZERTY keyboard)


def vector(held, speed):
    """(velocity, angle) for the directions held (a set of up, down, left, right)."""
    velocity = speed * ((1 if "up" in held else 0) - (1 if "down" in held else 0))
    angle = TURN_ANGLE * ((1 if "right" in held else 0) - (1 if "left" in held else 0))
    return round(velocity, 2), angle


def step(held):
    """The step for an older robot: one direction at a time, forward first."""
    for direction, command in (("up", "forward"), ("down", "backward"),
                               ("right", "rotate_clockwise"),
                               ("left", "rotate_counterclockwise")):
        if direction in held:
            return command
    return None


class DriveDialog(QDialog):
    def __init__(self, client, capability, parent=None):
        super().__init__(parent)
        self.client, self.capability = client, capability
        self.held = set()
        self._moving = False
        self.setWindowTitle(tr("Drive the robot"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        hint = QLabel(tr("Hold the arrow keys (or W A S D, Z Q S D), or the buttons. The robot stops "
                         "when you let go, and stays where it is when this window closes."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        pad = QGridLayout()
        self.buttons = {}
        for direction, text, row, column in (("up", "▲", 0, 1), ("left", "◀", 1, 0),
                                             ("right", "▶", 1, 2), ("down", "▼", 2, 1)):
            button = QToolButton()
            button.setText(text)
            button.setFixedSize(56, 56)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # the keys stay with the window
            button.pressed.connect(lambda d=direction: self._press(d))
            button.released.connect(lambda d=direction: self._release(d))
            pad.addWidget(button, row, column)
            self.buttons[direction] = button
        layout.addLayout(pad)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel(tr("Speed")))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(20, 100)
        self.speed.setValue(60)
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed.setEnabled(capability == HIGH_RES)   # older robots: fixed steps
        speed_row.addWidget(self.speed)
        layout.addLayout(speed_row)
        self.status = QLabel(tr("Switching manual control on…"))
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(SEND_MS if capability == HIGH_RES else STEP_MS)
        self.timer.timeout.connect(self._send)
        self.client.manual_control(capability, "enable", on_done=self._enabled,
                                   on_error=self._failed)

    # -- keys and buttons -----------------------------------------------------------

    def keyPressEvent(self, event):
        direction = KEYS.get(event.key())
        if direction is None:
            super().keyPressEvent(event)
        elif not event.isAutoRepeat():
            self._press(direction)

    def keyReleaseEvent(self, event):
        direction = KEYS.get(event.key())
        if direction is not None and not event.isAutoRepeat():
            self._release(direction)

    def _press(self, direction):
        self.held.add(direction)
        self.buttons[direction].setDown(True)
        if not self.timer.isActive():
            self._send()
            self.timer.start()

    def _release(self, direction):
        self.held.discard(direction)
        self.buttons[direction].setDown(False)
        if not self.held:
            self.timer.stop()
            self._stop_moving()

    # -- robot -------------------------------------------------------------------------

    def _enabled(self, *_):
        self.status.setText(tr("Manual control on."))

    def _failed(self, error):
        self.status.setText(tr("The robot refused: {error}").format(error=error))

    def _send(self):
        if not self.held:
            return
        if self.capability == HIGH_RES:
            velocity, angle = vector(self.held, self.speed.value() / 100)
            self.client.manual_control(self.capability, "move", velocity=velocity,
                                       angle=angle, on_error=self._failed)
        else:
            command = step(self.held)
            if command:
                self.client.manual_control(self.capability, "move", command=command,
                                           on_error=self._failed)
        self._moving = True

    def _stop_moving(self):
        if self._moving and self.capability == HIGH_RES:
            self.client.manual_control(self.capability, "move", velocity=0, angle=0)
        self._moving = False

    def closeEvent(self, event):
        self.timer.stop()
        self.held.clear()
        self._stop_moving()
        self.client.manual_control(self.capability, "disable")
        super().closeEvent(event)
