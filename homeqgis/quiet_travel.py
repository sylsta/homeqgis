"""'Go to' without cleaning, for robots whose go-to is a tiny zone clean.

Before the trip: read the robot's current presets, then switch to the
quietest ones it offers (mode "vacuum" so the mops stay up, water off, fan
off or lowest). After the trip, whatever its end: put the saved ones back.

This module has no user-facing text: it reports (capability, value) pairs
and error details that the plugin turns into translated messages.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal

# (capability, attribute type in PresetSelectionStateAttribute, quiet values in
# order of preference). Order matters: the mode first (it may reset the others).
QUIET_PRESETS = [
    ("OperationModeControlCapability", "operation_mode", ["vacuum"]),
    ("WaterUsageControlCapability", "water_grade", ["off", "min", "low"]),
    ("FanSpeedControlCapability", "fan_speed", ["off", "min", "low"]),
]
TIMEOUT_MS = 5000


def quiet_choice(presets, preferences):
    """First quiet value the robot offers, or None."""
    return next((value for value in preferences if value in presets), None)


class QuietTravel(QObject):
    ready = pyqtSignal(list)    # [(capability, quiet value)] actually set ([] if none)
    failed = pyqtSignal(str)    # error detail: nothing was changed or restored
    restored = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self.saved = []          # [(capability, value before the trip)]
        self._run = 0            # ignores answers of an older run

    def is_active(self):
        return bool(self.saved)

    # -- before the trip --------------------------------------------------------------

    def prepare(self, client, capabilities):
        """Read the current presets, then switch to quiet ones; emits ready or failed."""
        self._run += 1
        run = self._run
        self._client, self.saved = client, []
        steps = [(cap, kind, prefs) for cap, kind, prefs in QUIET_PRESETS
                 if capabilities is None or cap in capabilities]
        if not steps:
            self.ready.emit([])
            return

        def got_attributes(attributes):
            if run != self._run:
                return
            current = {a.get("type"): a.get("value") for a in attributes or []
                       if isinstance(a, dict) and a.get("__class") == "PresetSelectionStateAttribute"}
            self._read_presets(run, steps, current, [])

        client.probe("/robot/state/attributes", got_attributes,
                     lambda error: run == self._run and self.failed.emit(error),
                     timeout_ms=TIMEOUT_MS)

    def _read_presets(self, run, steps, current, plan):
        """One capability at a time: its presets, then the quiet choice."""
        if not steps:
            self._apply(run, plan, [])
            return
        (capability, kind, prefs), rest = steps[0], steps[1:]

        def got_presets(presets):
            if run != self._run:
                return
            quiet = quiet_choice(presets if isinstance(presets, list) else [], prefs)
            before = current.get(kind)
            if quiet is not None and before is not None and before != quiet:
                plan.append((capability, quiet, before))
            self._read_presets(run, rest, current, plan)

        self._client.probe(f"/robot/capabilities/{capability}/presets", got_presets,
                           lambda error: run == self._run and self.failed.emit(error),
                           timeout_ms=TIMEOUT_MS)

    def _apply(self, run, plan, done):
        if not plan:
            self.ready.emit([(cap, quiet) for cap, quiet, _ in done])
            return
        step, rest = plan[0], plan[1:]
        capability, quiet, before = step

        def applied():
            if run != self._run:
                return
            self.saved.append((capability, before))
            self._apply(run, rest, done + [step])

        def refused(error):
            if run != self._run:
                return
            self.restore()   # undo what was already changed
            self.failed.emit(error)

        self._client.put_preset(capability, quiet, applied, refused)

    # -- after the trip ---------------------------------------------------------------

    def restore(self, client=None):
        """Put the saved presets back, in reverse order; emits restored at the end."""
        client = client or self._client
        saved, self.saved = list(self.saved), []
        self._run += 1
        if client is None or not saved:
            return

        def step(remaining):
            if not remaining:
                self.restored.emit()
                return
            capability, value = remaining[0]
            client.put_preset(capability, value, lambda: step(remaining[1:]),
                              lambda _error: step(remaining[1:]))   # restore the others anyway

        step(list(reversed(saved)))

    def forget(self):
        """The client is gone: nothing can be restored."""
        self._run += 1
        self.saved, self._client = [], None
