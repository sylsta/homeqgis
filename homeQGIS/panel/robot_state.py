"""The robot's state in the panel: header, attributes, consumables, dock,
statistics, events (what the client reports)."""

import html
import math
import time

from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtWidgets import QLabel, QProgressBar

from ..core.i18n import tr
from ..core.ui_loader import set_row_visible as _set_row_visible
from ..servers import host_info
from .common import (
    ACTIVE_STATES,
    DOCK_COMPONENT_PROBLEMS,
    IDLE_INTERVAL_MS,
    attachment_labels,
    capability_labels,
    consumable_label,
    dock_labels,
    event_label,
    flag_labels,
    format_area_cm2,
    format_seconds,
    format_iso_time,
    humanize_capability,
    label_or_raw,
    state_labels,
    dock_component_advice,
    dock_component_labels,
    dock_component_values,
)
ACTIVE_INTERVAL_MS = 5_000
LOW_PERCENT = 10
LOW_MINUTES = 600  # 10 h
MAX_EVENTS = 10
PRESET_ROWS = {  # capability -> attribute type in PresetSelectionStateAttribute
    "FanSpeedControlCapability": "fan_speed",
    "WaterUsageControlCapability": "water_grade",
    "OperationModeControlCapability": "operation_mode",
}

# Dock components (DockComponentStateAttribute), in display order.
DOCK_COMPONENT_ORDER = ["water_tank_clean", "water_tank_dirty", "detergent", "dustbag"]

# Capabilities listed with ✗ when missing (the ones the plugin uses).
CORE_CAPABILITIES = [
    "BasicControlCapability", "MapSegmentationCapability", "ZoneCleaningCapability",
    "GoToLocationCapability", "FanSpeedControlCapability", "WaterUsageControlCapability",
    "ConsumableMonitoringCapability", "CurrentStatisticsCapability",
    "TotalStatisticsCapability", "LocateCapability", "AutoEmptyDockManualTriggerCapability",
    "WifiConfigurationCapability", "CameraLightControlCapability",
]


class RobotStateMixin:
    """Part of ValetudoPanel (see status_panel.py)."""

    def _show_disconnected(self):
        self.lbl_connection.setText(f"<span style='color:#9e9e9e'>●</span> {tr('Not connected')}")
        self.lbl_robot.setText("")
        self.lbl_robot.setToolTip("")
        self._wifi_html, self._wifi_tip = "", ""
        self._robot_ip, self._host = "", {}
        self.lbl_robot_info.setText("")
        self._update_strip_tip()
        self.lbl_wifi_now.setText(tr("Not connected."))
        self.sparkline.clear()
        self._state, self._job, self._battery = None, None, None
        self._update_primary()
        self._update_job()
        for key in ("error", "dock", "consumables", "robot_clock"):
            self._set_problem(key, None)

    def _on_reachable(self, ok):
        self._reachable = ok
        if not ok:
            self._show_unreachable()
        if ok and self.client is not None and not self._robot_text:
            self.client.fetch_robot_info(quiet=True)   # robot was off when we connected
            self.client.fetch_version(quiet=True)
        if ok:
            self._last_ok = time.monotonic()
            self._last_ok_clock = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._update_header()

    def _show_unreachable(self):
        """The robot no longer answers: its last state, battery, Wi-Fi, clock and
        uptime are no longer true, so they are not shown (they come back with the
        next answer)."""
        for badge in (self.lbl_badge, self.lbl_badge_details):
            badge.setText(tr("Unreachable"))
            badge.setStyleSheet("background-color: #9e9e9e; color: white; font-weight: bold;"
                                "border-radius: 9px; padding: 2px 10px;")
        for bar in (self.bar_battery, self.bar_battery_details):
            bar.setValue(0)
            bar.setFormat("—")
            bar.setEnabled(False)
        self.lbl_state.setText(tr("Unreachable"))
        self._wifi_html, self._wifi_tip = "", ""
        self._update_strip_tip()
        self.lbl_wifi_now.setText(tr("The robot does not answer."))
        self._host = {}
        self._update_robot_info()
        self._update_robot_label()
        self._state, self._job, self._battery = None, None, None
        self._update_primary()
        self._update_job()

    def _update_header(self):
        for entry in self._server_entries:
            entry["block"].render()   # "updated N s ago"
        self._update_strip_servers()
        self._apply_server_state()
        if self.client is None or self._reachable is None:
            return
        if self._reachable:
            seconds = int(time.monotonic() - (self._last_ok or time.monotonic()))
            text = tr("Connected · updated {seconds} s ago").format(seconds=seconds)
            self.lbl_connection.setText(f"<span style='color:#2e7d32'>●</span> {text}")
        else:
            text = tr("Unreachable · last update {time}").format(
                time=self._last_ok_clock or "—")
            self.lbl_connection.setText(f"<span style='color:#c62828'>●</span> {text}")

    def _on_robot_info(self, info):
        self._robot_text = " ".join(
            p for p in (info.get("manufacturer"), info.get("modelName")) if p)
        self._update_robot_label()

    def _on_version(self, version):
        release = version.get("release")
        self._version_text = f"Valetudo {release}" if release else ""
        self._update_robot_label()

    def _on_host_info(self, info):
        self._host = info or {}
        self._update_robot_info()

    def _update_robot_info(self):
        """Third header line: robot IP · robot's own date and time · uptime."""
        host = self._host
        ip = self._robot_ip or ((self._ssh_target() or [""])[0])
        line, wrong = host_info.info_line(ip, host.get("robot_time"), host.get("received_at"),
                                          host.get("uptime"), self._local_time)
        self.lbl_robot_info.setText(line)
        self.lbl_robot_info.setStyleSheet("color: #ef6c00;" if wrong else "")
        self.lbl_robot_info.setToolTip(
            tr("The robot's clock is wrong: check Valetudo's NTP settings.") if wrong else "")
        self._set_problem("robot_clock", tr("The robot's clock is wrong: check Valetudo's "
                                            "NTP settings.") if wrong else None, "maintenance")

    def _update_robot_label(self):
        """Second header line: robot model · Valetudo version · Wi-Fi signal."""
        parts = [html.escape(p) for p in (self._robot_text, self._version_text) if p]
        if self._wifi_html:
            parts.append(self._wifi_html)
        self.lbl_robot.setText(" · ".join(parts))
        self.lbl_robot.setToolTip(self._wifi_tip)

    def _on_capabilities(self, capabilities):
        self.capabilities = set(capabilities)
        caps = self.capabilities
        self.chk_goto_quiet.setVisible("GoToLocationCapability" not in caps
                                       and "ZoneCleaningCapability" in caps)

        any_preset = False
        for capability, combo in self.preset_combos.items():
            supported = capability in caps
            _set_row_visible(self.settings_form, combo, supported)
            any_preset |= supported
            if supported:
                self.client.fetch_presets(capability, quiet=True)
        self.box_settings.setVisible(any_preset)
        self.box_consumables.setVisible("ConsumableMonitoringCapability" in caps)
        self.box_current.setVisible("CurrentStatisticsCapability" in caps)
        self.box_total.setVisible("TotalStatisticsCapability" in caps)

        labels = capability_labels()
        name = lambda c: labels.get(c) or humanize_capability(c)
        lines = [f"✓ {n}" for n in sorted(name(c) for c in caps)]
        lines += [f"✗ {name(c)}" for c in CORE_CAPABILITIES if c not in caps]
        if self.camera_light.isVisibleTo(self) != ("CameraLightControlCapability" in caps):
            self.camera_light.setVisible("CameraLightControlCapability" in caps)
        if "CameraLightControlCapability" in caps:
            self.client.fetch_toggle("CameraLightControlCapability")
        self.lbl_features.setText("\n".join(lines))
        self.box_robot_settings.set_robot(self.client, caps)
        self._update_maintenance()
        self._update_rooms_button()
        if self.isVisible():   # nothing is fetched while the panel is hidden
            self.refresh()
            self._timer.start()

    def _on_attributes(self, attributes):
        states, flags = state_labels(), flag_labels()
        attachments = []
        dock_value = None
        components = {}
        error_text = ""
        state = None
        for attr in attributes:
            cls = attr.get("__class")
            if cls == "StatusStateAttribute":
                state = attr.get("value")
                flag = attr.get("flag")
                text = label_or_raw(states, state)
                if flag and flag != "none":
                    text += f" ({label_or_raw(flags, flag)})"
                self.lbl_state.setText(text)
                self._set_badge(state)
                previous = (self._state, self._flag)
                self._state, self._flag = state, flag
                self._follow_recording(state, flag, *previous)
                err = attr.get("error") or {}
                error_text = (err.get("message") if isinstance(err, dict) else "") \
                    or (attr.get("metaData") or {}).get("error_description", "")
                if state != "error" and not err:
                    error_text = ""
            elif cls == "BatteryStateAttribute":
                level = int(attr.get("level") or 0)
                flag = attr.get("flag")
                self._battery, self._battery_flag = level, flag
                suffix = f" · {label_or_raw(flags, flag)}" if flag and flag != "none" else ""
                for bar in (self.bar_battery, self.bar_battery_details):
                    bar.setEnabled(True)
                    bar.setValue(level)
                    bar.setFormat(f"{level} %{suffix}")
            elif cls == "PresetSelectionStateAttribute":
                for capability, ptype in PRESET_ROWS.items():
                    if attr.get("type") == ptype:
                        combo = self.preset_combos[capability]
                        index = combo.findData(attr.get("value"))
                        if index >= 0:
                            combo.setCurrentIndex(index)
            elif cls == "AttachmentStateAttribute":
                name = label_or_raw(attachment_labels(), attr.get("type"))
                attachments.append(f"{name} {'✓' if attr.get('attached') else '✗'}")
            elif cls == "DockStatusStateAttribute":
                dock_value = attr.get("value")
            elif cls == "DockComponentStateAttribute":
                components[attr.get("type")] = attr.get("value")

        _set_row_visible(self.status_form, self.lbl_dock, dock_value is not None)
        self.lbl_dock.setText(label_or_raw(dock_labels(), dock_value))
        self._dock_value = dock_value
        self._set_badge(self._state)   # docked: with what it is doing
        self.lbl_error.setVisible(bool(error_text))
        self.lbl_error.setText(f"⚠ {error_text}" if error_text else "")
        self._set_problem("error", error_text or None)
        self._update_primary()
        self._update_job()
        self._emit_summary()
        _set_row_visible(self.status_form, self.lbl_attachments, bool(attachments))
        self._update_dock_components(components)
        self.lbl_attachments.setText("   ".join(attachments))

        self._timer.setInterval(ACTIVE_INTERVAL_MS if state in ACTIVE_STATES
                                else IDLE_INTERVAL_MS)

    def _update_dock_components(self, components):
        """One row per dock component; problems (missing/empty/full) in red with advice."""
        form = self.dock_form
        while form.rowCount():
            form.removeRow(0)
        self._has_components = bool(components)
        self._update_dock_group()
        names, values, advice = (dock_component_labels(), dock_component_values(),
                                 dock_component_advice())
        issues = [f"{label_or_raw(names, c)}: {advice[v]}" for c, v in components.items()
                  if v in DOCK_COMPONENT_PROBLEMS]
        self._set_problem("dock", " · ".join(issues) or None, "maintenance")
        order = DOCK_COMPONENT_ORDER + sorted(c for c in components
                                              if c not in DOCK_COMPONENT_ORDER)
        for component in order:
            if component not in components:
                continue
            value = components[component]
            label = QLabel(label_or_raw(values, value))
            name = label_or_raw(names, component)
            if value in DOCK_COMPONENT_PROBLEMS:
                name = f"{name} ⚠"
                label.setStyleSheet("color: #c62828; font-weight: bold;")
                label.setToolTip(advice[value])
                label.setText(f"{label.text()} · {advice[value]}")
            elif value == "ok":
                label.setStyleSheet("color: #2e7d32;")
            form.addRow(name, label)

    def _on_consumables(self, consumables):
        form = self.consumables_form
        while form.rowCount():
            form.removeRow(0)
        worn = []
        for item in consumables:
            remaining = item.get("remaining") or {}
            value, unit = remaining.get("value"), remaining.get("unit")
            if value is None:
                continue
            label = consumable_label(item.get("type"), item.get("subType"))
            if unit == "percent":
                widget = QProgressBar()
                widget.setRange(0, 100)
                widget.setValue(int(value))
                widget.setFormat(f"{int(value)} %")
                low = value < LOW_PERCENT
            else:  # minutes
                widget = QLabel(tr("{hours} h left").format(hours=int(value) // 60))
                low = value < LOW_MINUTES
            if low:
                worn.append(label)
                label = f"{label} ⚠"
                widget.setToolTip(tr("Replace soon"))
            form.addRow(label, widget)
        self._set_problem("consumables", tr("Replace soon: {parts}").format(
            parts=", ".join(worn)) if worn else None, "maintenance")

    @staticmethod
    def _stats(items):
        return {s.get("type"): s.get("value") for s in items if isinstance(s, dict)}

    def _on_current_statistics(self, items):
        stats = self._stats(items)
        self.lbl_cur_time.setText(format_seconds(stats["time"]) if "time" in stats else "—")
        self.lbl_cur_area.setText(format_area_cm2(stats["area"]) if "area" in stats else "—")
        self._job = (stats.get("time"), stats.get("area"))
        self._update_job()

    def _on_total_statistics(self, items):
        stats = self._stats(items)
        self.lbl_tot_count.setText(str(stats["count"]) if "count" in stats else "—")
        self.lbl_tot_time.setText(format_seconds(stats["time"]) if "time" in stats else "—")
        self.lbl_tot_area.setText(format_area_cm2(stats["area"]) if "area" in stats else "—")

    def _on_events(self, events):
        self.list_events.clear()
        events = sorted((e for e in events if isinstance(e, dict)),
                        key=lambda e: e.get("timestamp") or "", reverse=True)[:MAX_EVENTS]
        if not events:
            self.list_events.addItem(tr("No recent events."))
            return
        for event in events:
            stamp = format_iso_time(event.get("timestamp"))
            self.list_events.addItem(f"{stamp}  {event_label(event)}".strip())

    def update_map(self, map_json):
        """Called with each map: from the plugin (show map / live tracking) or peeked."""
        self._last_map = time.monotonic()
        robot = dock = None
        for ent in map_json.get("entities", []):
            pts = ent.get("points") or []
            if len(pts) < 2:
                continue
            if ent.get("type") == "robot_position":
                robot = (pts[0], pts[1], (ent.get("metaData") or {}).get("angle"))
            elif ent.get("type") == "charger_location":
                dock = (pts[0], pts[1])
        if robot is None:
            return
        x, y, angle = robot
        text = tr("x {x} cm · y {y} cm · heading {angle}°").format(
            x=round(x), y=round(y), angle=round(angle) if angle is not None else "?")
        if dock is not None:
            distance = math.hypot(x - dock[0], y - dock[1]) / 100
            text += "\n" + tr("{distance} m from the dock").format(distance=f"{distance:.1f}")
        self.lbl_position.setText(text)
