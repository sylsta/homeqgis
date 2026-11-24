"""Optional SSH password for an ssh QProcess.

ssh never reads a password from a pipe: it asks a helper program named by
SSH_ASKPASS (forced by SSH_ASKPASS_REQUIRE=force, OpenSSH 8.4 or newer). The
helper written here only prints an environment variable: the password is
given to that ssh process alone, in its environment, and is never written to
disk or put on a command line.

Passwords are registered per (host, user, port) by the panel, from the
settings (stored encrypted in the QGIS authentication database). Without a
password, ssh runs as before: key only, BatchMode, never prompting.
"""

import os
import stat
import sys
import tempfile

from qgis.PyQt.QtCore import QProcessEnvironment

PASSWORD_ENV = "VALETUDO_QGIS_SSH_PASSWORD"

_passwords = {}   # (host, user, port) -> password


def _key(host, user, port):
    return (str(host), str(user or "root"), int(port))


def set_password(host, user, port, password):
    """Register (or with an empty password, forget) the password of a target."""
    if password:
        _passwords[_key(host, user, port)] = password
    else:
        _passwords.pop(_key(host, user, port), None)


def askpass_script():
    """Path of the helper (written once per session, without the password)."""
    folder = tempfile.gettempdir()
    if sys.platform.startswith("win"):
        path = os.path.join(folder, "homeqgis_askpass.cmd")
        content = ("@powershell -NoProfile -NonInteractive -Command "
                   f"\"[Console]::Out.WriteLine($env:{PASSWORD_ENV})\"\r\n")
    else:
        path = os.path.join(folder, f"homeqgis_askpass_{os.getuid()}.sh")
        content = f"#!/bin/sh\nprintf '%s\\n' \"${PASSWORD_ENV}\"\n"
    try:
        with open(path, encoding="utf-8") as existing:
            if existing.read() == content:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="") as script:
        script.write(content)
    if not sys.platform.startswith("win"):
        os.chmod(path, stat.S_IRWXU)   # 0700: only this user
    return path


def password_arguments(args):
    """ssh arguments allowing one password attempt instead of key-only BatchMode."""
    out = []
    for arg in args:
        out.append("BatchMode=no" if arg == "BatchMode=yes" else arg)
    # Options go before the destination: right after the program's own flags.
    extra = ["-o", "NumberOfPasswordPrompts=1",
             "-o", "PreferredAuthentications=publickey,keyboard-interactive,password"]
    return extra + out


def prepare(process, args, host, user, port):
    """Arguments to start ssh with; sets the process environment if a password is
    registered for this target. Returns args unchanged otherwise."""
    password = _passwords.get(_key(host, user, port))
    if not password:
        return args
    env = QProcessEnvironment.systemEnvironment()
    env.insert("SSH_ASKPASS", askpass_script())
    env.insert("SSH_ASKPASS_REQUIRE", "force")
    if not env.contains("DISPLAY"):
        env.insert("DISPLAY", "none")   # older ssh only uses SSH_ASKPASS with a DISPLAY
    env.insert(PASSWORD_ENV, password)
    process.setProcessEnvironment(env)
    return password_arguments(args)
