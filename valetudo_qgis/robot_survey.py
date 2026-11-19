"""Wi-Fi survey recorded on the robot itself (robot/valetudo_wifi_survey.sh).

The plugin only installs, starts, reads and removes the script, over SSH
(key-based login, same settings as the reboot). Once started, the script runs
on the robot without QGIS and records whenever the robot moves; its readings
are imported into the "Wi-Fi survey" layer on demand.

The script is kept in the first writable folder among PERSISTENT_DIRS, so that
it and its readings survive a reboot when the robot has such a folder. It is
not started at boot by the robot: the plugin starts it again when it connects
(see ensure()), and the README tells how to add it to the robot's boot script.

This module contains no user-facing text: it emits result keys and values.
"""

import os
import shutil

from qgis.PyQt.QtCore import QObject, QProcess, pyqtSignal

from .ssh_reboot import CONNECT_TIMEOUT_S
from . import ssh_auth

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "robot", "valetudo_wifi_survey.sh")
SCRIPT_NAME = "valetudo_wifi_survey.sh"
DATA_NAME = "valetudo_wifi_survey.csv"
PID_FILE = "/tmp/valetudo_wifi_survey.pid"
PERSISTENT_DIRS = ("/data", "/mnt/UDISK", "/mnt/data", "/userdata", "/tmp")
OPERATIONS = ("install", "ensure", "import", "remove")

_PICK_DIR = (
    "d=; for c in " + " ".join(PERSISTENT_DIRS) + "; do "
    'if [ -d "$c" ] && touch "$c/.vq_test" 2>/dev/null; then rm -f "$c/.vq_test"; d=$c; break; fi; '
    "done"
)
_STOP = (
    f'if [ -f {PID_FILE} ]; then p=$(cat {PID_FILE}); kill "$p" 2>/dev/null; sleep 1; '
    f'kill -9 "$p" 2>/dev/null; rm -f {PID_FILE}; fi'
)


def _start(directory, interval_s, min_step_cm):
    script, data = f"{directory}/{SCRIPT_NAME}", f"{directory}/{DATA_NAME}"
    run = f'sh "{script}" "{data}" {int(max(1, round(interval_s)))} {int(min_step_cm)}'
    # Detached from the SSH session: no input, no output, nohup when it exists.
    return (f"if command -v nohup >/dev/null 2>&1; then nohup {run} </dev/null >/dev/null 2>&1 & "
            f"else {run} </dev/null >/dev/null 2>&1 & fi; echo started=1")


def install_command(interval_s, min_step_cm):
    """Reads the script on stdin, saves it, checks what it can read, (re)starts it."""
    return (f'{_PICK_DIR}; [ -n "$d" ] || {{ echo error=no_writable_dir; exit 1; }}; '
            f'cat > "$d/{SCRIPT_NAME}" && chmod +x "$d/{SCRIPT_NAME}" || exit 1; echo dir=$d; '
            f'{_STOP}; sh "$d/{SCRIPT_NAME}" --check; '
            + _start("$d", interval_s, min_step_cm))


def ensure_command(directory, interval_s, min_step_cm):
    """Start the installed script if it is not running (e.g. after a robot reboot)."""
    return (f'[ -f "{directory}/{SCRIPT_NAME}" ] || {{ echo missing=1; exit 0; }}; '
            f'if [ -f {PID_FILE} ] && kill -0 "$(cat {PID_FILE})" 2>/dev/null; '
            f"then echo running=1; else {_start(directory, interval_s, min_step_cm)}; fi")


def history_command(directory):
    """The readings, after the robot's clock (now=…), for the robot's history."""
    return f'echo now=$(date +%s); cat "{directory}/{DATA_NAME}" 2>/dev/null; true'


def import_command(directory):
    return f'cat "{directory}/{DATA_NAME}" 2>/dev/null; true'


def remove_command(directory):
    return f'{_STOP}; rm -f "{directory}/{SCRIPT_NAME}" "{directory}/{DATA_NAME}"; echo removed=1'


def parse_keys(text):
    """'key=value' lines -> dict (other lines are ignored); repeated keys
    (tool=…) are joined with commas."""
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.isidentifier():
            value = value.strip()
            values[key] = f"{values[key]},{value}" if key in values else value
    return values


def parse_rows(text):
    """CSV lines of the script -> [dict(session, time, x, y, signal, state, ssid, frequency)]."""
    rows = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 5:
            continue
        try:
            row = {"session": int(parts[0]), "time": int(parts[1]), "x": float(parts[2]),
                   "y": float(parts[3]), "signal": int(parts[4])}
        except ValueError:
            continue
        row["state"] = parts[5] if len(parts) > 5 else ""
        row["ssid"] = parts[6] if len(parts) > 6 else ""
        row["frequency"] = parts[7] if len(parts) > 7 else ""
        rows.append(row)
    return rows


class RobotSurvey(QObject):
    """Runs one SSH operation at a time and reports its output."""

    finished = pyqtSignal(str, bool, str, str)   # operation, ok, stdout, error detail

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._operation = ""
        self._out = self._err = b""
        self.output_bytes = b""   # raw stdout of the last operation (binary-safe)

    def is_busy(self):
        return self._process is not None

    def run(self, operation, host, user, port, command, stdin=b""):
        """False if another operation is running (nothing is started then)."""
        if self._process is not None:
            return False
        program = shutil.which("ssh")
        if not program:
            self.finished.emit(operation, False, "", "ssh_missing")
            return True
        self._operation, self._out, self._err = operation, b"", b""
        process = QProcess(self)
        process.readyReadStandardOutput.connect(
            lambda: setattr(self, "_out", self._out + bytes(process.readAllStandardOutput())))
        process.readyReadStandardError.connect(
            lambda: setattr(self, "_err", (self._err + bytes(process.readAllStandardError()))[-2000:]))
        process.errorOccurred.connect(self._on_error)
        process.finished.connect(self._on_finished)
        self._process = process
        process.start(program, ssh_auth.prepare(process, [
            "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
            "-p", str(int(port)), f"{user or 'root'}@{host}", command,
        ], host, user or "root", port))
        if stdin:
            process.write(stdin)
        process.closeWriteChannel()
        return True

    def stop(self):
        process, self._process = self._process, None
        if process is not None:
            process.finished.disconnect(self._on_finished)
            process.errorOccurred.disconnect(self._on_error)
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()

    def _done(self, ok, detail):
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self.output_bytes = self._out
        self.finished.emit(self._operation, ok, self._out.decode("utf-8", "replace"), detail)

    def _on_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._done(False, "ssh_missing")

    def _on_finished(self, exit_code, *_):
        if self._process is None:
            return
        lines = [l.strip() for l in self._err.decode("utf-8", "replace").splitlines() if l.strip()]
        self._done(exit_code == 0, lines[-1] if lines else f"exit code {exit_code}")
