"""Remote desktop (VNC, RDP) on a server, in the system's own program.

The program is the one set in the settings (a command with {host}, {port},
{user} and {userat}, i.e. "user@" or nothing), else the first one found:

    Linux    Remmina (both), TigerVNC/TightVNC vncviewer, xfreerdp, KRDC
    Windows  mstsc (RDP, built in), TightVNC / RealVNC viewer
    macOS    the built-in Screen Sharing (vnc://), Microsoft Remote Desktop (rdp://)

Through SSH (the default for Linux computers): an SSH tunnel to the server's
port first, and the program connects to localhost. The tunnel runs
"ssh -L … sleep 30": ssh stays as long as the program's connection is open,
then ends by itself — nothing to clean up.
"""

import shlex
import shutil
import socket
import sys

from qgis.PyQt.QtCore import QObject, QProcess, QTimer, pyqtSignal

from . import ssh_auth

DEFAULT_PORTS = {"vnc": 5900, "rdp": 3389}
TUNNEL_WAIT_MS = 10_000
TUNNEL_HOLD_S = 30   # the tunnel waits this long for the program to connect

# (program to look for, command template), in order of preference
CANDIDATES = {
    "linux": {
        "vnc": [("remmina", "remmina -c vnc://{userat}{host}:{port}"),
                ("vncviewer", "vncviewer {host}::{port}"),
                ("krdc", "krdc vnc://{host}:{port}")],
        "rdp": [("remmina", "remmina -c rdp://{userat}{host}:{port}"),
                ("xfreerdp3", "xfreerdp3 /v:{host}:{port} /u:{user}"),
                ("xfreerdp", "xfreerdp /v:{host}:{port} /u:{user}"),
                ("krdc", "krdc rdp://{userat}{host}:{port}")],
    },
    "windows": {
        "vnc": [("tvnviewer", "tvnviewer {host}::{port}"),
                ("vncviewer", "vncviewer {host}::{port}")],
        "rdp": [("mstsc", "mstsc /v:{host}:{port}")],
    },
    "darwin": {
        "vnc": [("open", "open vnc://{userat}{host}:{port}")],
        "rdp": [("open", "open rdp://full%20address=s:{host}:{port}")],
    },
}


def _platform():
    if sys.platform.startswith("win"):
        return "windows"
    return "darwin" if sys.platform == "darwin" else "linux"


def detected(protocol):
    """The command template of the first program found for a protocol, or ""."""
    for program, template in CANDIDATES[_platform()][protocol]:
        if shutil.which(program):
            return template
    return ""


def command(template, host, port, user=""):
    """The program and its arguments, from a template. "/u:{user}" style arguments
    are left out when there is no user."""
    values = {"host": host, "port": port, "user": user, "userat": f"{user}@" if user else ""}
    args = []
    for part in shlex.split(template, posix=not sys.platform.startswith("win")):
        if "{user}" in part and not user:
            continue
        args.append(part.format(**values))
    return args


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class RemoteDesktop(QObject):
    """Opens one remote desktop; emits failed(reason) if it cannot:
    "no_program", "tunnel" (the SSH tunnel did not come up), "failed"."""

    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._check_tunnel)
        self._pending = None

    def open(self, template, host, port, user="", ssh=None):
        """template: the program's command ("" if none found); ssh: (host, user, port)
        to go through an SSH tunnel, or None to connect directly."""
        if not template:
            self.failed.emit("no_program")
            return
        if ssh is None:
            self._start(command(template, host, port, user))
            return
        local = free_port()
        args = ["-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new",
                "-p", str(int(ssh[2])), "-L", f"{local}:localhost:{int(port)}",
                f"{ssh[1]}@{ssh[0]}" if ssh[1] else ssh[0], f"sleep {TUNNEL_HOLD_S}"]
        # Detached: the session outlives QGIS; ssh ends by itself (see the module doc)
        process = QProcess(self)
        args = ssh_auth.prepare(process, args, *ssh)   # a stored password, if any
        process.setProgram("ssh")
        process.setArguments(args)
        started = process.startDetached()
        if not (started[0] if isinstance(started, tuple) else started):
            self.failed.emit("tunnel")
            return
        self._pending = (command(template, "localhost", local, user), local, 0)
        self._timer.start()

    def _check_tunnel(self):
        if self._pending is None:
            self._timer.stop()
            return
        args, local, waited = self._pending
        if _listening(local):
            self._timer.stop()
            self._pending = None
            self._start(args)
            return
        waited += self._timer.interval()
        self._pending = (args, local, waited)
        if waited >= TUNNEL_WAIT_MS:
            self._timer.stop()
            self._pending = None
            self.failed.emit("tunnel")   # (ssh gives up by itself: ConnectTimeout, sleep)

    def _start(self, args):
        if not args or not QProcess.startDetached(args[0], args[1:]):
            self.failed.emit("failed")
