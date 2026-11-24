"""Constants and translated labels shared by the panel's modules.

Labels are functions: evaluated after the translator is installed. Unknown values
fall back to the raw value."""

import re

from qgis.PyQt.QtCore import QDateTime, Qt

from ..core.i18n import tr

KEY_ONCE_TIMERS = "valetudo/once_timers"     # "label|due Unix time" of one-off cleanings
KEY_GOTO_QUIET = "valetudo/goto_quiet"   # "Go to" without cleaning (emulated go-to only)
KEY_PI_MAP_FULL = "valetudo/pi_map_full"   # "Load Wi-Fi map from the Pi": all runs
IDLE_INTERVAL_MS = 30_000
ACTIVE_STATES = {"cleaning", "returning", "moving", "manual_control"}


def state_labels():
    return {
        "idle": tr("Idle"), "cleaning": tr("Cleaning"), "returning": tr("Returning to dock"),
        "docked": tr("Docked"), "paused": tr("Paused"), "error": tr("Error"),
        "manual_control": tr("Manual control"), "moving": tr("Moving"),
    }


def dock_labels():
    """DockStatusStateAttribute values: what the dock is doing."""
    return {
        "idle": tr("Idle"), "pause": tr("Paused"), "emptying": tr("Emptying"),
        "cleaning": tr("Washing mops"), "washing": tr("Washing mops"), "drying": tr("Drying"),
        "error": tr("Error"),
    }


def flag_labels():
    return {
        "segment": tr("Rooms"), "zone": tr("Zone"), "spot": tr("Spot"),
        "target": tr("Target"), "resumable": tr("Resumable"), "mapping": tr("Mapping"),
        "charging": tr("Charging"), "discharging": tr("Discharging"), "charged": tr("Charged"),
    }


def preset_labels():
    return {
        "off": tr("Off"), "min": tr("Minimum"), "low": tr("Low"), "medium": tr("Medium"),
        "high": tr("High"), "max": tr("Maximum"), "turbo": tr("Turbo"), "custom": tr("Custom"),
        # operation modes
        "vacuum": tr("Vacuum"), "mop": tr("Mop"), "vacuum_and_mop": tr("Vacuum and mop"),
        "vacuum_then_mop": tr("Vacuum, then mop"),
    }


def attachment_labels():
    return {"dustbin": tr("Dust bin"), "watertank": tr("Water tank"), "mop": tr("Mop")}


def consumable_label(ctype, subtype):
    labels = {
        ("brush", "main"): tr("Main brush"),
        ("brush", "side_right"): tr("Side brush"),
        ("brush", "side_left"): tr("Side brush"),
        ("filter", "main"): tr("Filter"),
        ("sensor", "all"): tr("Sensors"),
        ("mop", "main"): tr("Mop pad"),
        ("detergent", "main"): tr("Detergent"),
        ("bin", "main"): tr("Dust bag"),
    }
    return labels.get((ctype, subtype)) or " ".join(p for p in (ctype, subtype) if p)


DOCK_COMPONENT_PROBLEMS = {"missing", "empty", "full"}


def dock_component_labels():
    return {
        "water_tank_clean": tr("Fresh water"),
        "water_tank_dirty": tr("Waste water"),
        "detergent": tr("Detergent"),
        "dustbag": tr("Dust bag"),
    }


def dock_component_values():
    return {
        "ok": tr("OK"), "missing": tr("Missing"), "empty": tr("Empty"),
        "full": tr("Full"), "unknown": tr("Unknown"),
    }


def dock_component_advice():
    return {"missing": tr("Put it back in place."), "empty": tr("Refill it."),
            "full": tr("Empty it.")}


def humanize_capability(capability):
    """'CarpetSensorModeControlCapability' -> 'Carpet sensor mode control' (fallback)."""
    name = capability[:-len("Capability")] if capability.endswith("Capability") else capability
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()
    return " ".join([words[0]] + [w.lower() for w in words[1:]]) if words else capability


def capability_labels():
    return {
        "AutoEmptyDockAutoEmptyControlCapability": tr("Auto-empty dock"),
        "AutoEmptyDockAutoEmptyDurationControlCapability": tr("Auto-empty duration"),
        "AutoEmptyDockAutoEmptyIntervalControlCapability": tr("Auto-empty interval"),
        "CameraLightControlCapability": tr("Camera light"),
        "CarpetModeControlCapability": tr("Carpet mode"),
        "CarpetSensorModeControlCapability": tr("Carpet sensor mode"),
        "CleanRouteControlCapability": tr("Cleaning route"),
        "CollisionAvoidantNavigationControlCapability": tr("Collision-avoidant navigation"),
        "CombinedVirtualRestrictionsCapability": tr("Virtual walls and no-go zones"),
        "DoNotDisturbCapability": tr("Do not disturb"),
        "FloorMaterialDirectionAwareNavigationControlCapability":
            tr("Floor-direction-aware navigation"),
        "HighResolutionManualControlCapability": tr("Manual control (high resolution)"),
        "KeyLockCapability": tr("Child lock"),
        "ManualControlCapability": tr("Manual control"),
        "MapResetCapability": tr("Map reset"),
        "MapSegmentEditCapability": tr("Room editing"),
        "MapSegmentMaterialControlCapability": tr("Floor materials"),
        "MapSegmentRenameCapability": tr("Room renaming"),
        "MapSnapshotCapability": tr("Map snapshots"),
        "MappingPassCapability": tr("Mapping pass"),
        "MopDockCleanManualTriggerCapability": tr("Mop washing"),
        "MopDockDryManualTriggerCapability": tr("Mop drying"),
        "MopDockMopAutoDryingControlCapability": tr("Automatic mop drying"),
        "MopDockMopDryingTimeControlCapability": tr("Mop drying time"),
        "MopDockMopWashTemperatureControlCapability": tr("Mop wash temperature"),
        "MopExtensionControlCapability": tr("Mop extension"),
        "MopExtensionFurnitureLegHandlingControlCapability":
            tr("Mop extension around furniture legs"),
        "MopTwistControlCapability": tr("Mop twist"),
        "ObstacleAvoidanceControlCapability": tr("Obstacle avoidance"),
        "ObstacleImagesCapability": tr("Obstacle images"),
        "OperationModeControlCapability": tr("Operation mode"),
        "PendingMapChangeHandlingCapability": tr("Pending map changes"),
        "PetObstacleAvoidanceControlCapability": tr("Pet waste avoidance"),
        "QuirksCapability": tr("Quirks"),
        "SpeakerTestCapability": tr("Speaker test"),
        "SpeakerVolumeControlCapability": tr("Speaker volume"),
        "VoicePackManagementCapability": tr("Voice packs"),
        "WifiScanCapability": tr("Wi-Fi scan"),
        "BasicControlCapability": tr("Basic control"),
        "MapSegmentationCapability": tr("Room cleaning"),
        "ZoneCleaningCapability": tr("Zone cleaning"),
        "GoToLocationCapability": tr("Go to location"),
        "FanSpeedControlCapability": tr("Fan speed"),
        "WaterUsageControlCapability": tr("Water usage"),
        "ConsumableMonitoringCapability": tr("Consumables"),
        "CurrentStatisticsCapability": tr("Current statistics"),
        "TotalStatisticsCapability": tr("Total statistics"),
        "LocateCapability": tr("Locate"),
        "AutoEmptyDockManualTriggerCapability": tr("Empty dock"),
        "WifiConfigurationCapability": tr("Wi-Fi"),
    }


def event_label(event):
    cls = event.get("__class", "")
    if cls == "DustBinFullValetudoEvent":
        return tr("Dust bin full")
    if cls == "ConsumableDepletedValetudoEvent":
        return tr("Consumable depleted: {name}").format(
            name=consumable_label(event.get("type"), event.get("subType")))
    if cls == "ErrorStateValetudoEvent":
        return tr("Error: {message}").format(message=event.get("message", ""))
    if cls == "MissingResourceValetudoEvent":
        return tr("Missing resource: {message}").format(message=event.get("message", ""))
    if cls == "MopAttachmentReminderValetudoEvent":
        return tr("Mop attachment reminder")
    if cls == "PendingMapChangeValetudoEvent":
        return tr("Pending map change")
    return cls.replace("ValetudoEvent", "") or "?"


def state_label(state):
    """Translated robot state ("docked" -> "Docked" / "À la base")."""
    return label_or_raw(state_labels(), state)


def label_or_raw(mapping, value):
    return mapping.get(value, value) if value is not None else "—"


def format_seconds(seconds):
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    return tr("{minutes} min").format(minutes=minutes)


def format_area_cm2(value):
    return tr("{area} m²").format(area=f"{value / 10_000:.1f}")


def format_iso_time(iso):
    dt = QDateTime.fromString(iso or "", Qt.DateFormat.ISODateWithMs)
    if not dt.isValid():
        dt = QDateTime.fromString(iso or "", Qt.DateFormat.ISODate)
    return dt.toLocalTime().toString("dd/MM HH:mm") if dt.isValid() else ""
