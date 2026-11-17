"""Follow Valetudo's log file on the robot over SSH (``tail -f``).

Same SSH rules as ssh_reboot.py: QProcess (non-blocking), key-based login only
(BatchMode: ssh fails instead of asking for a password). If the connection
drops (robot rebooting, Wi-Fi lost), it is opened again after a pause.

This module contains no user-facing text: it emits state keys (see STATES)
that the UI layer turns into translated messages.
"""

import shlex
import shutil

from qgis.PyQt.QtCore import QObject, QProcess, QTimer, pyqtSignal

from .ssh_reboot import CONNECT_TIMEOUT_S

LOG_PATH = "/tmp/valetudo.log"
INITIAL_LINES = 200
RETRY_MS = 10_000
STATES = ("connecting", "following", "ssh_missing", "failed", "stopped")
MARKER = "__valetudo_qgis_log__"   # printed first: the login worked, even if the log is empty


COMMAND_PREFIX = "|"   # a "path" starting with it is a command to follow, e.g. "|ha core logs -f"


def remote_command(path=LOG_PATH, lines=INITIAL_LINES):
    if path.startswith(COMMAND_PREFIX):
        # Through a login shell: e.g. Home Assistant's `ha` needs the environment
        # set up by the profile (an SSH command alone does not read it).
        command = shlex.quote(path[len(COMMAND_PREFIX):] + " 2>&1")
        return f"echo {MARKER}; sh -lc {command}"
    # -F follows the file again when Valetudo truncates it; plain -f if the
    # robot's tail does not know -F.
    return (f"echo {MARKER}; tail -n {lines} -F {path} 2>/dev/null"
            f" || tail -n {lines} -f {path}")


def ssh_arguments(host, user="root", port=22, path=LOG_PATH):
    return [
        "-n",                                        # no stdin
        "-o", "BatchMode=yes",                       # key only, never prompt
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
        "-o", "ServerAliveInterval=15",              # notice a dead link
        "-o", "ServerAliveCountMax=3",
        "-p", str(int(port)),
        f"{user}@{host}",
        remote_command(path),
    ]


class LogTail(QObject):
    linesReceived = pyqtSignal(list)    # new complete lines (str)
    stateChanged = pyqtSignal(str, str)  # state key (see STATES), detail

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._target = None      # (host, user, port, path) while it should run
        self._buffer = b""
        self._stderr = b""
        self._following = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self._connect)

    def is_running(self):
        return self._target is not None

    def start(self, host, user="root", port=22, path=LOG_PATH):
        """Follow path (absolute, or relative to the user's home) on host."""
        target = (host, user or "root", int(port), path)
        if target == self._target:
            return
        self.stop(quiet=True)
        self._target = target
        self._connect()

    def stop(self, quiet=False):
        was_running = self._target is not None
        self._target = None
        self._retry.stop()
        self._following = False
        process, self._process = self._process, None
        if process is not None:
            process.finished.disconnect(self._on_finished)
            process.errorOccurred.disconnect(self._on_error)
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
        if was_running and not quiet:
            self.stateChanged.emit("stopped", "")

    def _connect(self):
        if self._target is None or self._process is not None:
            return
        program = shutil.which("ssh")
        if not program:
            self._target = None
            self.stateChanged.emit("ssh_missing", "")
            return
        host, user, port, path = self._target
        self._buffer = self._stderr = b""
        process = QProcess(self)
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.errorOccurred.connect(self._on_error)
        process.finished.connect(self._on_finished)
        self._process = process
        self.stateChanged.emit("connecting", host)
        process.start(program, ssh_arguments(host, user, port, path))

    def _on_stdout(self):
        if self._process is None:
            return
        data = self._buffer + bytes(self._process.readAllStandardOutput())
        *complete, self._buffer = data.split(b"\n")
        lines = [line.decode("utf-8", "replace").rstrip("\r") for line in complete]
        if not self._following and MARKER in lines:
            self._following = True
            self.stateChanged.emit("following", self._target[0] if self._target else "")
        lines = [line for line in lines if line != MARKER]
        if lines:
            self.linesReceived.emit(lines)

    def _on_stderr(self):
        if self._process is not None:
            self._stderr = (self._stderr + bytes(self._process.readAllStandardError()))[-2000:]

    def _detail(self):
        lines = [l.strip() for l in self._stderr.decode("utf-8", "replace").splitlines()]
        return next((l for l in reversed(lines) if l), "")

    def _on_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._drop_process()
            self._target = None
            self.stateChanged.emit("ssh_missing", "")

    def _on_finished(self, exit_code, *_):
        if self._process is None:
            return
        detail = self._detail() or f"exit code {exit_code}"
        self._drop_process()
        if self._target is not None:   # not stopped by us: try again shortly
            self.stateChanged.emit("failed", detail)
            self._retry.start()

    def _drop_process(self):
        process, self._process = self._process, None
        self._following = False
        if process is not None:
            process.deleteLater()
