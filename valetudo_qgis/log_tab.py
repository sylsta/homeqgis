"""One log view of the Terminal tab: a file followed over SSH (tail -F).

Follows its file only while its page is shown and the panel visible; the
target (host, user, port) comes from the settings, so a change reconnects.
Lines with a level ("[ERROR]", "[WARN]"…) are coloured.
"""

import html
import re

from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QFontDatabase

from .i18n import tr
from .log_tail import COMMAND_PREFIX, LogTail

LOG_LEVEL_COLORS = {"error": "#c62828", "warn": "#ef6c00", "debug": "#757575",
                    "trace": "#9e9e9e"}


def log_line_html(line):
    """One log line, coloured by its level ("[ERROR]", "[WARN]"…) when it has one."""
    match = re.search(r"\[(ERROR|WARN|WARNING|DEBUG|TRACE)\]", line, re.IGNORECASE)
    text = html.escape(line) or "&nbsp;"
    level = match.group(1).lower()[:5] if match else ""
    color = LOG_LEVEL_COLORS.get("warn" if level.startswith("warn") else level)
    return f"<span style='white-space:pre; color:{color}'>{text}</span>" if color \
        else f"<span style='white-space:pre'>{text}</span>"


class LogTab(QObject):
    def __init__(self, page, widgets, target, path, no_target_text, parent=None):
        """widgets: dict of status, follow, clear, output; target(): (host, user, port)
        or None; path: the file, absolute or relative to the user's home, or a
        command to follow ("|" + command, see log_tail); or a function returning it."""
        super().__init__(parent)
        self.page, self.w, self._target, self.path = page, widgets, target, path
        self._no_target_text = no_target_text
        self.tail = LogTail(self)
        self.tail.linesReceived.connect(self._on_lines)
        self.tail.stateChanged.connect(self._on_state)
        w = widgets
        w["output"].setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        w["clear"].clicked.connect(w["output"].clear)
        w["follow"].toggled.connect(self._on_follow_toggled)
        w["status"].setText(tr("Shown while this tab is open."))

    def update(self, visible, current_page):
        target = self._target()
        if visible and current_page is self.page:
            if target is None:
                self.tail.stop(quiet=True)
                self.w["status"].setText(self._no_target_text)
                return
            self.tail.start(*target, self._path())
        else:
            self.tail.stop()

    def _path(self):
        return self.path() if callable(self.path) else self.path

    def shutdown(self):
        self.tail.stop(quiet=True)

    def _on_state(self, state, detail):
        colors = {"following": "#2e7d32", "failed": "#c62828", "ssh_missing": "#c62828"}
        texts = {
            "connecting": tr("Connecting to {host} over SSH…").format(host=detail),
            "following": tr("Following {path} on {host}.").format(
                path=self._path().removeprefix(COMMAND_PREFIX), host=detail),
            "failed": tr("SSH connection lost or refused: {error}. Retrying in 10 s…")
                .format(error=detail),
            "ssh_missing": tr("ssh was not found: install an SSH client."),
            "stopped": tr("Shown while this tab is open."),
        }
        status = self.w["status"]
        status.setStyleSheet(f"color: {colors[state]};" if state in colors else "")
        status.setText(texts.get(state, state))
        target = self._target()
        status.setToolTip(
            tr("Needs key-based SSH login: ssh-copy-id {user}@{host}").format(
                user=target[1], host=target[0])
            if state in ("failed", "ssh_missing") and target else "")

    def _on_lines(self, lines):
        output = self.w["output"]
        bar = output.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        keep = None if at_bottom or self.w["follow"].isChecked() else bar.value()
        for line in lines:
            output.appendHtml(log_line_html(line))
        bar.setValue(bar.maximum() if keep is None else keep)   # reading older lines: no jump

    def _on_follow_toggled(self, checked):
        if checked:
            bar = self.w["output"].verticalScrollBar()
            bar.setValue(bar.maximum())
