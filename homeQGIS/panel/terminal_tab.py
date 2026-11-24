"""Terminal tab of the panel: SSH consoles and logs of the robot and servers."""

from qgis.PyQt.QtCore import QDateTime, QUrl
from qgis.core import QgsSettings

from ..core.i18n import tr
from ..core.settings import NUC_AUTO_LOG_COMMAND, load_settings
from ..servers import model as servers_model
from ..servers.console_tab import ConsoleTab
from ..servers.frames import build_console_page, build_log_page
from ..servers.log_tab import LogTab
from ..servers.log_tail import COMMAND_PREFIX, LOG_PATH

KEY_TERMINAL = "valetudo/panel_terminal"     # "robot/console", "pi/log"…
PI_LOG_PATH = "valetudo/collect.log"         # the Pi collector's log (README's cron line)


class TerminalMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _build_terminal(self):
        """Terminal: robot or Pi, console or log."""
        def console_widgets(p):
            return {"status": getattr(self, f"lbl_{p}console_status"),
                    "connect": getattr(self, f"btn_{p}console_connect"),
                    "clear": getattr(self, f"btn_{p}console_clear"),
                    "output": getattr(self, f"txt_{p}console"),
                    "prompt": getattr(self, f"lbl_{p}console_prompt"),
                    "edit": getattr(self, f"edit_{p}console"),
                    "run": getattr(self, f"btn_{p}console_run"),
                    "stop": getattr(self, f"btn_{p}console_stop")}

        def log_widgets(p):
            return {"status": getattr(self, f"lbl_{p}log_status"),
                    "follow": getattr(self, f"chk_{p}log_follow"),
                    "clear": getattr(self, f"btn_{p}log_clear"),
                    "output": getattr(self, f"txt_{p}log")}
        # The robot's console and log (from the .ui); the servers' ones are added with
        # their frames (_build_server_frames)
        self.consoles = [ConsoleTab(self.tab_console, console_widgets(""), self._ssh_target,
                                    tr("No robot configured."), self)]
        self.logs = [LogTab(self.tab_log, log_widgets(""), self._ssh_target, LOG_PATH,
                            tr("No robot configured."), self)]
        # The Terminal tab is opened on a server from its >_ menu in the Status tab,
        # and hidden again with its ✕.
        choice = QgsSettings().value(KEY_TERMINAL, "robot/console", type=str) or "robot/console"
        device, _, mode = str(choice).partition("/")
        self._term_device = device or "robot"   # checked once the servers are built
        (self.btn_term_log if mode == "log" else self.btn_term_console).setChecked(True)
        for button in (self.btn_term_console, self.btn_term_log):
            button.toggled.connect(self._on_terminal_switch)
        self.btn_term_close.clicked.connect(self.close_terminal)
        self._show_terminal_page()

    def _on_terminal_switch(self, checked):
        if not checked:   # the other button of the pair is being checked
            return
        device, mode = self._terminal_choice()
        QgsSettings().setValue(KEY_TERMINAL, f"{device}/{mode}")
        self._show_terminal_page()
        self._update_console()

    def open_terminal(self, device, mode="console"):
        """Show the Terminal tab on a server's console or log."""
        self._term_device = device
        (self.btn_term_log if mode == "log" else self.btn_term_console).setChecked(True)
        QgsSettings().setValue(KEY_TERMINAL, f"{device}/{mode}")
        self._set_tab_shown("terminal", True)
        self._show_terminal_page()
        self.show_tab("terminal")
        self._update_console()

    def close_terminal(self, *_):
        """Hide the Terminal tab; its sessions stop (they run only while shown)."""
        self._set_tab_shown("terminal", False)
        if self._page_shown(self.tab_terminal):
            self.show_tab("status")
        self._update_console()

    def _show_terminal_page(self):
        device, mode = self._terminal_choice()
        entry = self._entry(device) if device != "robot" else None
        if device != "robot" and (entry is None or not entry["pages"]):
            device = self._term_device = "robot"
        name = tr("Robot") if device == "robot" else entry["name"]
        if "terminal" in self._tab_titles:   # (empty on the first call, see _build_ui)
            self._tab_titles["terminal"][0].setText(tr("Terminal · {server}").format(server=name))
        if device == "robot":
            pages = {"console": self.tab_console, "log": self.tab_log}
        else:
            pages = entry["pages"]
        self.btn_term_log.setEnabled("log" in pages)
        self.terminal_stack.setCurrentWidget(pages.get(mode) or pages["console"])

    def _terminal_choice(self):
        """(device, mode) of the Terminal tab."""
        return self._term_device, ("log" if self.btn_term_log.isChecked() else "console")

    @staticmethod
    def _ssh_target():
        """(host, user, port) of the robot from the settings, or None without an address."""
        cfg = load_settings()
        host = QUrl(cfg["url"]).host() if cfg["url"] else ""
        return (host, cfg["ssh_user"] or "root", int(cfg["ssh_port"])) if host else None

    @staticmethod
    def _local_time(epoch):
        return QDateTime.fromSecsSinceEpoch(int(epoch)).toString("dd/MM/yyyy HH:mm")

    def _update_console(self):
        """Consoles and logs run only while their page of the Terminal tab is shown."""
        self._update_servers()
        self._update_server_buttons()
        page = (self.terminal_stack.currentWidget()
                if self._page_shown(self.tab_terminal) else None)
        for view in self.consoles + self.logs:
            view.update(self.isVisible(), page)

    def _add_terminal_pages(self, entry, fresh):
        """Console and log pages in the Terminal tab, for a server with SSH."""
        server = entry["server"]
        kind = server["type"]
        if kind not in ("rpi", "linux", "ha") and not (kind == "windows"
                                                        and servers_model.value(server, "ssh")):
            return
        name = entry["name"]
        none = tr("No SSH address for {name} in the settings.").format(name=name)
        target = lambda: self._ssh_for(fresh())   # noqa: E731
        page, widgets = build_console_page(tr(
            "Runs on {name}, one command at a time, without a terminal: interactive "
            "programs (vi, top, less…) do not work. cd is kept from one command to the "
            "next, variables are not.").format(name=name))
        console = ConsoleTab(page, widgets, target, none, self)
        self.terminal_stack.addWidget(page)
        self.consoles.append(console)
        entry["pages"]["console"] = page
        entry["views"].append(console)
        if kind == "windows":
            return   # no log command there
        if kind == "rpi":
            path = PI_LOG_PATH
        elif kind == "ha":
            path = lambda: COMMAND_PREFIX + servers_model.value(fresh(), "log_command")  # noqa
        else:
            path = lambda: COMMAND_PREFIX + (servers_model.value(fresh(), "log_command")  # noqa
                                             or NUC_AUTO_LOG_COMMAND)
        page, widgets = build_log_page()
        log = LogTab(page, widgets, target, path, none, self)
        self.terminal_stack.addWidget(page)
        self.logs.append(log)
        entry["pages"]["log"] = page
        entry["views"].append(log)

    def _term_pages_devices(self):
        return [entry["id"] for entry in self._server_entries if entry["pages"]]
