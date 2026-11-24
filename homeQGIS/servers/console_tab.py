"""One SSH console tab of the status panel (robot, Raspberry Pi…).

Wires the tab's widgets (from ui/status_panel.ui) to an SshConsole session:
status line, Connect/Disconnect, output, prompt, command line with history
(↑ ↓), Run and Stop. The session opens when the tab is first shown, stays open
while the panel is visible (the working directory is kept) and closes when
the panel is hidden or the target (host, user, port) changes.
"""

import html

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QFontDatabase

from ..core.i18n import tr
from .ssh_console import SshConsole

HISTORY = 100


class ConsoleTab(QObject):
    def __init__(self, page, widgets, target, no_target_text, parent=None):
        """page: the tab page; widgets: dict of status, connect, clear, output, prompt,
        edit, run, stop; target(): (host, user, port) or None."""
        super().__init__(parent)
        self.page = page
        self.w = widgets
        self._target = target
        self._no_target_text = no_target_text
        self.session = SshConsole(self)
        self.session.output.connect(self._on_output)
        self.session.commandFinished.connect(self._on_command_finished)
        self.session.stateChanged.connect(self._on_state)
        w = widgets
        w["output"].setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        w["edit"].returnPressed.connect(self.run)
        w["edit"].installEventFilter(self)   # ↑ ↓: history
        w["run"].clicked.connect(self.run)
        w["stop"].clicked.connect(self.stop_command)
        w["connect"].clicked.connect(self.toggle)
        w["clear"].clicked.connect(w["output"].clear)
        self._history, self._index = [], 0
        self._on_state("closed", "")

    # -- session ----------------------------------------------------------------------

    def update(self, visible, current_page):
        """Panel visibility or tab changed, or settings may have changed."""
        if not visible:
            self.session.stop()
            return
        target = self._target()
        if self.session.is_open():
            if target != self.session.target:   # settings changed: new session
                self.connect(target)
        elif current_page is self.page and self.session.state == "closed":
            self.connect(target)

    def connect(self, target):
        if target is None:
            self.session.stop(quiet=True)
            self.w["status"].setText(self._no_target_text)
            return
        self.w["output"].clear()   # a new session starts with an empty console
        self.session.start(*target)

    def toggle(self, *_):
        if self.session.is_open():
            self.session.stop()
        else:
            self.connect(self._target())

    def stop_command(self, *_):
        """No terminal, so no Ctrl+C: end the session and open a new one."""
        target = self.session.target
        self.append(tr("Command stopped."), "note")
        self.session.stop(quiet=True)
        if target is not None:
            self.session.start(*target)

    def shutdown(self):
        self.session.stop(quiet=True)

    # -- commands ---------------------------------------------------------------------

    def prompt(self):
        target = self.session.target
        if target is None or not self.session.is_open():
            return "$"
        sign = "#" if target[1] == "root" else "$"
        return f"{target[1]}@{target[0]}:{self.session.cwd or '~'} {sign}"

    def run(self, *_):
        edit = self.w["edit"]
        command = edit.text().strip()
        if not command or self.session.state != "ready":
            return
        prompt = self.prompt()
        if self.session.run(command):
            self.append(f"{prompt} {command}", "command")
            if not self._history or self._history[-1] != command:
                self._history.append(command)
                del self._history[:-HISTORY]
            self._index = len(self._history)
            edit.clear()

    def _history_step(self, step):
        if not self._history:
            return
        self._index = max(0, min(len(self._history), self._index + step))
        self.w["edit"].setText(self._history[self._index]
                               if self._index < len(self._history) else "")

    def eventFilter(self, obj, event):
        if obj is self.w["edit"] and event.type() == QEvent.Type.KeyPress \
                and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._history_step(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(obj, event)

    # -- output -----------------------------------------------------------------------

    def append(self, text, kind="out"):
        styles = {"command": "font-weight: bold;", "err": "color: #c62828;",
                  "note": "color: #757575; font-style: italic;"}
        style = "white-space:pre; " + styles.get(kind, "")
        output = self.w["output"]
        output.appendHtml(f"<span style='{style}'>{html.escape(text) or '&nbsp;'}</span>")
        bar = output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_output(self, lines, kind):
        for line in lines:
            self.append(line, kind)

    def _on_command_finished(self, code):
        if code:
            self.append(tr("(exit code {code})").format(code=code), "note")

    def _on_state(self, state, detail):
        w = self.w
        texts = {
            "connecting": tr("Connecting to {host} over SSH…").format(host=detail),
            "ready": tr("Connected to {host}.").format(host=detail),
            "busy": tr("Running…"),
            "failed": tr("SSH session ended: {error}").format(error=detail),
            "ssh_missing": tr("ssh was not found: install an SSH client."),
            "closed": tr("Not connected."),
        }
        colors = {"ready": "#2e7d32", "busy": "#1565c0", "failed": "#c62828",
                  "ssh_missing": "#c62828"}
        w["status"].setStyleSheet(f"color: {colors[state]};" if state in colors else "")
        w["status"].setText(texts.get(state, state))
        target = self.session.target or self._target()
        w["status"].setToolTip(
            tr("Needs key-based SSH login: ssh-copy-id {user}@{host}").format(
                user=target[1], host=target[0])
            if state in ("failed", "ssh_missing") and target else "")
        if state == "failed" and detail:
            self.append(texts["failed"], "err")
        w["connect"].setText(tr("Disconnect") if self.session.is_open() else tr("Connect"))
        w["edit"].setEnabled(state in ("ready", "busy"))
        w["run"].setEnabled(state == "ready")
        w["stop"].setEnabled(state == "busy")
        w["prompt"].setText(self.prompt())
        if state == "ready":
            w["edit"].setFocus()
