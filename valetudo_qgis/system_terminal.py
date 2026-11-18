"""Open an SSH session in the system's own terminal window (not in QGIS).

Linux: the terminal named by $TERMINAL, else Debian's x-terminal-emulator /
sensible-terminal, else the first known terminal found. Each family takes its
command its own way (-e, -x, --). macOS: Terminal.app. Windows: Windows
Terminal, else a console window.

On Linux and macOS the window stays open after ssh ends ("Press Enter to
close"), so that an error (refused key, wrong address) can be read.

No user-facing text here except the closing prompt, passed in by the caller.
"""

import os
import shlex
import shutil
import sys

from qgis.PyQt.QtCore import QProcess

# How each terminal runs a program with its arguments
DOUBLE_DASH = ("gnome-terminal", "kgx", "ptyxis", "tilix", "terminator")
DASH_X = ("xfce4-terminal", "mate-terminal", "lxterminal", "qterminal")
DASH_E = ("konsole", "xterm", "uxterm", "alacritty", "kitty", "foot", "wezterm", "urxvt",
          "st", "terminology", "deepin-terminal", "sakura", "roxterm", "lxqt-terminal")
DEBIAN = ("x-terminal-emulator", "sensible-terminal")


def ssh_command(host, user, port):
    """["ssh", "-p", "22", "root@host"]"""
    return ["ssh", "-p", str(int(port)), f"{user}@{host}" if user else host]


def describe(host, user, port):
    """The command as text, for tooltips: ssh -p 22 root@192.168.50.20"""
    return " ".join(ssh_command(host, user, port))


def _family(program):
    """Which convention a terminal program follows. Debian's x-terminal-emulator must
    accept "-e program args" whatever terminal it points to (Debian policy 11.8.3)."""
    if os.path.basename(program) in DEBIAN:
        return DASH_E
    name = os.path.basename(os.path.realpath(program))
    name = name.split(".")[0]   # gnome-terminal.wrapper, konsole.bin…
    for family in (DOUBLE_DASH, DASH_X, DASH_E):
        if name in family:
            return family
    return DASH_E   # x-terminal-emulator and most others accept -e program args


def linux_terminal():
    """(program path, family) of the terminal to use, or (None, None)."""
    preferred = os.environ.get("TERMINAL", "").strip()
    if preferred:
        path = shutil.which(preferred)
        if path:
            return path, _family(path)
    for name in DEBIAN + DOUBLE_DASH + DASH_X + DASH_E:
        path = shutil.which(name)
        if path:
            return path, _family(path)
    return None, None


def linux_arguments(family, program_args):
    if family is DOUBLE_DASH:
        return ["--", *program_args]
    if family is DASH_X:
        return ["-x", *program_args]
    return ["-e", *program_args]


def held(command, close_prompt):
    """sh -c "<command>; echo; printf prompt; read": the window stays open."""
    script = (f"{shlex.join(command)}; echo; printf '%s' {shlex.quote(close_prompt)}; "
              "read answer")
    return ["sh", "-c", script]


def open_ssh(host, user, port, close_prompt="Press Enter to close."):
    """Open the session; returns "" on success, else a short reason (key)."""
    command = ssh_command(host, user, port)
    if sys.platform.startswith("win"):
        if shutil.which("wt.exe") or shutil.which("wt"):
            ok = QProcess.startDetached("wt.exe", command)
        else:
            ok = QProcess.startDetached("cmd.exe", ["/c", "start", "", "cmd", "/k", *command])
        return "" if ok else "failed"
    if sys.platform == "darwin":
        script = shlex.join(held(command, close_prompt))
        apple = f'tell application "Terminal" to do script {_apple_string(script)}'
        ok = QProcess.startDetached("osascript", ["-e", apple,
                                                  "-e", 'tell application "Terminal" to activate'])
        return "" if ok else "failed"
    program, family = linux_terminal()
    if program is None:
        return "no_terminal"
    ok = QProcess.startDetached(program, linux_arguments(family, held(command, close_prompt)))
    return "" if ok else "failed"


def _apple_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
