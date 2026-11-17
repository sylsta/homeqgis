"""A command console on the robot over SSH, one command at a time.

QProcess cannot give ssh a terminal, so this is not a full terminal: one
``sh`` runs on the robot (``ssh -T``) and each command is sent to it wrapped
like this::

    cd '<cwd>'; ( eval '<command>'; s=$?; printf '\\n%s %s\\n' CWD_MARKER "$PWD"; exit $s ) \\
        </dev/null; printf '\\n%s %s\\n' DONE_MARKER $?

- the subshell keeps a syntax error or an ``exit`` from ending the remote shell;
- ``</dev/null`` keeps a command that reads its input from waiting forever;
- the first marker gives the new working directory, so ``cd`` carries over to
  the next command (variables do not); the second one, always printed, ends
  the command with its exit code.

Interactive programs (vi, top, less…) need a terminal and do not work.
Same SSH rules as ssh_reboot.py: key-based login only (BatchMode).
This module contains no user-facing text: it emits state keys (see STATES).
"""

import re
import shutil

from qgis.PyQt.QtCore import QObject, QProcess, pyqtSignal

from . import ssh_auth
from .ssh_reboot import CONNECT_TIMEOUT_S

DONE_MARKER = "__valetudo_qgis_done__"
CWD_MARKER = "__valetudo_qgis_cwd__"
DONE_RE = re.compile(rf"^{DONE_MARKER} (\d+)$")
CWD_RE = re.compile(rf"^{CWD_MARKER} (.*)$")
STATES = ("connecting", "ready", "busy", "ssh_missing", "failed", "closed")


def _quote(text):
    """Single-quote for sh: 'it'\\''s'."""
    return "'" + text.replace("'", "'\\''") + "'"


def wrap(command, cwd=""):
    cd = f"cd {_quote(cwd)} 2>/dev/null; " if cwd else ""
    return (f"{cd}( eval {_quote(command)}; s=$?; "
            f"printf '\\n%s %s\\n' {CWD_MARKER} \"$PWD\"; exit $s ) </dev/null; "
            f"printf '\\n%s %s\\n' {DONE_MARKER} $?\n")


def ssh_arguments(host, user="root", port=22):
    return [
        "-T",                                        # no terminal: a plain pipe
        "-o", "BatchMode=yes",                       # key only, never prompt
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-p", str(int(port)),
        f"{user}@{host}",
        "sh",
    ]


class SshConsole(QObject):
    output = pyqtSignal(list, str)        # lines, "out" or "err"
    commandFinished = pyqtSignal(int)     # exit code of the last command
    stateChanged = pyqtSignal(str, str)   # state key (see STATES), detail

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self.target = None       # (host, user, port) of the open session
        self.cwd = ""            # remote working directory ("" = home)
        self._state = "closed"
        self._quiet = False      # the hidden first command (login check)
        self._out = self._err = b""
        self._pending_blank = False
        self._stderr_tail = b""

    @property
    def state(self):
        return self._state

    def _set_state(self, state, detail=""):
        self._state = state
        self.stateChanged.emit(state, detail)

    def is_open(self):
        return self._process is not None

    def start(self, host, user="root", port=22):
        target = (host, user or "root", int(port))
        if self._process is not None and target == self.target:
            return
        self.stop(quiet=True)
        program = shutil.which("ssh")
        if not program:
            self._set_state("ssh_missing")
            return
        self.target, self.cwd = target, ""
        self._out = self._err = self._stderr_tail = b""
        self._pending_blank = False
        process = QProcess(self)
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.errorOccurred.connect(self._on_error)
        process.finished.connect(self._on_finished)
        self._process = process
        self._set_state("connecting", host)
        process.start(program, ssh_auth.prepare(process, ssh_arguments(*target), *target))
        # Hidden first command: its marker says the login worked and gives the home dir.
        self._quiet = True
        process.write(wrap("true").encode("utf-8"))

    def run(self, command):
        """Send one command; False if the session is not ready for it."""
        if self._process is None or self._state != "ready" or not command.strip():
            return False
        self._quiet = False
        self._set_state("busy", command)
        self._process.write(wrap(command, self.cwd).encode("utf-8"))
        return True

    def stop(self, quiet=False):
        process, self._process = self._process, None
        if process is not None:
            process.finished.disconnect(self._on_finished)
            process.errorOccurred.disconnect(self._on_error)
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
            if not quiet:
                self._set_state("closed")
        elif not quiet and self._state != "closed":
            self._set_state("closed")

    # -- output ---------------------------------------------------------------------

    def _on_stdout(self):
        if self._process is None:
            return
        data = self._out + bytes(self._process.readAllStandardOutput())
        *complete, self._out = data.split(b"\n")
        lines = []
        for raw in complete:
            line = raw.decode("utf-8", "replace").rstrip("\r")
            cwd, done = CWD_RE.match(line), DONE_RE.match(line)
            if cwd or done:
                self._pending_blank = False   # the blank line was the marker's own "\n"
                if cwd:
                    self.cwd = cwd.group(1) or self.cwd
                    continue
                if lines and not self._quiet:
                    self.output.emit(lines, "out")
                lines = []
                self._command_done(int(done.group(1)))
                continue
            if self._pending_blank:
                lines.append("")
            self._pending_blank = line == ""
            if not self._pending_blank:
                lines.append(line)
        if lines and not self._quiet:
            self.output.emit(lines, "out")

    def _command_done(self, code):
        was_quiet, self._quiet = self._quiet, False
        if was_quiet:   # login check
            self._set_state("ready", self.target[0] if self.target else "")
            return
        self.commandFinished.emit(code)
        self._set_state("ready", self.target[0] if self.target else "")

    def _on_stderr(self):
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError())
        self._stderr_tail = (self._stderr_tail + chunk)[-2000:]
        data = self._err + chunk
        *complete, self._err = data.split(b"\n")
        lines = [l.decode("utf-8", "replace").rstrip("\r") for l in complete]
        if lines and not self._quiet and self._state in ("busy", "ready"):
            self.output.emit(lines, "err")

    def _detail(self):
        lines = [l.strip() for l in self._stderr_tail.decode("utf-8", "replace").splitlines()]
        return next((l for l in reversed(lines) if l), "")

    def _on_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.stop(quiet=True)
            self._set_state("ssh_missing")

    def _on_finished(self, exit_code, *_):
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self._set_state("failed", self._detail() or f"exit code {exit_code}")
