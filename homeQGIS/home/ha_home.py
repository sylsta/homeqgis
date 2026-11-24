"""Home Assistant's devices, for the panel's Home tab (pure Python, no Qt).

One POST /api/template returns everything: the areas, the devices (name, maker,
model, area, integration) and the entities with their state. Home Assistant's
REST API has no registry endpoint, but its templates can read the registries.

    data = {"areas": {area_id: name},
            "devices": {device_id: {name, maker, model, area, integration}},
            "entities": [{id, device, area, name, state, unit, class, domain,
                          attrs: {brightness…}}]}

build(data) groups the entities by device and works out what to show: each
device's main values, its battery and Zigbee link quality, whether it is
available, and a summary per area.
"""

# Jinja run by Home Assistant (POST /api/template). Kept to functions documented
# for templates: areas(), area_name(), area_id(), device_id(), device_attr().
TEMPLATE = r"""
{%- set ns = namespace(entities=[], devices={}, areas={}) -%}
{%- for a in areas() -%}{%- set ns.areas = dict(ns.areas, **{a: area_name(a)}) -%}{%- endfor -%}
{%- for s in states -%}
{%- set d = device_id(s.entity_id) -%}
{%- set ns.entities = ns.entities + [{
  "id": s.entity_id, "device": d, "area": area_id(s.entity_id), "name": s.name,
  "state": s.state, "unit": s.attributes.get('unit_of_measurement'),
  "class": s.attributes.get('device_class'), "domain": s.domain,
  "attrs": {"brightness": s.attributes.get('brightness')}}] -%}
{%- if d and d not in ns.devices -%}
{%- set ids = device_attr(d, 'identifiers') | list -%}
{%- set ns.devices = dict(ns.devices, **{d: {
  "name": device_attr(d, 'name_by_user') or device_attr(d, 'name'),
  "maker": device_attr(d, 'manufacturer'), "model": device_attr(d, 'model'),
  "area": device_attr(d, 'area_id'),
  "integration": (ids | first | list | first) if ids else None}}) -%}
{%- endif -%}
{%- endfor -%}
{{ {"areas": ns.areas, "devices": ns.devices, "entities": ns.entities} | to_json }}
"""

UNAVAILABLE = {"unavailable", "unknown", ""}
TOGGLE_DOMAINS = {"light", "switch", "fan", "input_boolean"}   # a toggle button
# Domains of Home Assistant's own, "virtual" entities (shown only on request)
VIRTUAL_DOMAINS = {"automation", "script", "scene", "sun", "weather", "zone", "person",
                   "input_boolean", "input_number", "input_select", "input_text",
                   "input_datetime", "input_button", "timer", "counter", "schedule",
                   "update", "conversation", "tts", "stt", "event", "todo", "calendar"}
LOW_BATTERY = 20   # %

INTEGRATIONS = {"zha": "Zigbee (ZHA)", "mqtt": "MQTT / Zigbee2MQTT", "hue": "Philips Hue",
                "esphome": "ESPHome", "shelly": "Shelly", "tasmota": "Tasmota",
                "mobile_app": "Mobile app", "cast": "Google Cast", "kodi": "Kodi",
                "unifi": "UniFi", "tplink": "TP-Link", "sonos": "Sonos",
                "hassio": "Home Assistant"}

ICONS = {   # (domain, device class) -> symbol; domain alone as fallback
    ("sensor", "temperature"): "🌡", ("sensor", "humidity"): "💧",
    ("sensor", "battery"): "🔋", ("sensor", "power"): "⚡", ("sensor", "energy"): "⚡",
    ("sensor", "illuminance"): "☀", ("sensor", "pressure"): "🌀",
    ("sensor", "carbon_dioxide"): "🫧", ("sensor", "pm25"): "🫧",
    ("binary_sensor", "door"): "🚪", ("binary_sensor", "window"): "🪟",
    ("binary_sensor", "opening"): "🚪", ("binary_sensor", "garage_door"): "🚪",
    ("binary_sensor", "motion"): "🏃", ("binary_sensor", "occupancy"): "🏃",
    ("binary_sensor", "presence"): "🏃", ("binary_sensor", "moisture"): "💦",
    ("binary_sensor", "smoke"): "🔥", ("binary_sensor", "gas"): "🔥",
    ("binary_sensor", "vibration"): "〰",
    "light": "💡", "switch": "🔌", "fan": "🌀", "cover": "🪟", "climate": "🔥",
    "lock": "🔒", "media_player": "📺", "camera": "📷", "vacuum": "🤖",
    "device_tracker": "📍", "button": "🔘", "number": "🔢", "select": "☰",
    "sensor": "📈", "binary_sensor": "●",
}

# Binary sensor states as words: device class -> (on, off)
BINARY_WORDS = {"door": ("open", "closed"), "window": ("open", "closed"),
                "opening": ("open", "closed"), "garage_door": ("open", "closed"),
                "motion": ("motion", "no motion"), "occupancy": ("occupied", "clear"),
                "presence": ("home", "away"), "moisture": ("wet", "dry"),
                "smoke": ("smoke!", "clear"), "gas": ("gas!", "clear"),
                "battery": ("low", "normal"), "problem": ("problem", "OK")}


def icon_for(entity):
    return ICONS.get((entity.get("domain"), entity.get("class"))) \
        or ICONS.get(entity.get("domain"), "•")


def is_link_quality(entity):
    eid = (entity.get("id") or "").lower()
    return entity.get("domain") == "sensor" and (
        eid.endswith("linkquality") or eid.endswith("link_quality") or eid.endswith("_lqi")
        or (entity.get("unit") or "").lower() == "lqi")


def is_battery(entity):
    return entity.get("domain") == "sensor" and entity.get("class") == "battery"


def available(entity):
    return str(entity.get("state", "")).lower() not in UNAVAILABLE


def value_text(entity, words=None):
    """The entity's state as shown: "21.4 °C", "open", "on (80 %)"."""
    state = str(entity.get("state", ""))
    if not available(entity):
        return state or "?"
    if entity.get("domain") == "binary_sensor":
        pair = BINARY_WORDS.get(entity.get("class"))
        if pair:
            text = pair[0] if state == "on" else pair[1]
            return (words or {}).get(text, text)
    if entity.get("domain") == "light" and state == "on":
        brightness = (entity.get("attrs") or {}).get("brightness")
        if isinstance(brightness, (int, float)):
            return f"{state} ({round(brightness / 2.55)} %)"
    unit = entity.get("unit") or ""
    try:
        number = float(state)
        state = f"{number:g}"
    except ValueError:
        pass
    return f"{state} {unit}".strip()


def _number(entity):
    try:
        return float(entity.get("state"))
    except (TypeError, ValueError):
        return None


def build(data, include_virtual=False):
    """Devices and loose entities from the template's answer:

    {"areas": {id: name}, "devices": [device…], "loose": [entity…]}, a device being
    {id, name, maker, model, area, area_name, integration, entities, main (the
    entities to show on its line), battery (%) or None, lqi or None, available,
    problems ([text keys]), toggles ([entity ids])}."""
    data = data if isinstance(data, dict) else {}
    areas = data.get("areas") or {}
    devices_info = data.get("devices") or {}
    by_device, loose = {}, []
    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("device") and entity["device"] in devices_info:
            by_device.setdefault(entity["device"], []).append(entity)
        elif include_virtual or entity.get("domain") not in VIRTUAL_DOMAINS:
            loose.append(entity)
    devices = []
    for device_id, entities in by_device.items():
        info = devices_info.get(device_id) or {}
        battery = next((_number(e) for e in entities if is_battery(e) and available(e)), None)
        lqi = next((_number(e) for e in entities if is_link_quality(e) and available(e)), None)
        main = [e for e in entities if not is_battery(e) and not is_link_quality(e)
                and e.get("domain") not in ("button", "update", "select", "number")]
        area = info.get("area") or next((e.get("area") for e in entities if e.get("area")), None)
        is_up = any(available(e) for e in entities)
        problems = []
        if not is_up:
            problems.append("unavailable")
        if battery is not None and battery < LOW_BATTERY:
            problems.append("low_battery")
        devices.append({
            "id": device_id, "name": info.get("name") or device_id,
            "maker": info.get("maker") or "", "model": info.get("model") or "",
            "area": area, "area_name": areas.get(area, "") if area else "",
            "integration": info.get("integration") or "",
            "entities": entities, "main": main[:3], "battery": battery, "lqi": lqi,
            "available": is_up, "problems": problems,
            "toggles": [e["id"] for e in entities if e.get("domain") in TOGGLE_DOMAINS
                        and available(e)],
        })
    if not include_virtual:   # a device that is only virtual (e.g. Sun): left out
        devices = [d for d in devices if d["main"] or d["battery"] is not None
                   or any(e.get("domain") not in VIRTUAL_DOMAINS for e in d["entities"])]
    devices.sort(key=lambda d: (d["name"] or "").lower())
    return {"areas": areas, "devices": devices, "loose": loose}


def integration_name(key):
    return INTEGRATIONS.get(key, key or "")


def group(model, by="area"):
    """[(group key, group name, [devices])], by area or by integration; devices without
    an area (or integration) in a last group (key None)."""
    groups = {}
    for device in model["devices"]:
        key = device["area"] if by == "area" else device["integration"]
        groups.setdefault(key or None, []).append(device)
    if by == "area":
        name = lambda key: model["areas"].get(key, key)   # noqa: E731
    else:
        name = integration_name
    out = [(key, name(key), devices) for key, devices in groups.items() if key]
    out.sort(key=lambda g: (g[1] or "").lower())
    if None in groups:
        out.append((None, "", groups[None]))
    return out


def area_summary(devices, words=None):
    """"21.4 °C · 58 % · door open · motion" from an area's devices."""
    temps, hums, opened, motion = [], [], 0, False
    for device in devices:
        for entity in device["entities"]:
            if not available(entity):
                continue
            kind, domain = entity.get("class"), entity.get("domain")
            if domain == "sensor" and kind == "temperature" and _number(entity) is not None:
                temps.append(_number(entity))
            elif domain == "sensor" and kind == "humidity" and _number(entity) is not None:
                hums.append(_number(entity))
            elif domain == "binary_sensor" and kind in ("door", "window", "opening") \
                    and entity.get("state") == "on":
                opened += 1
            elif domain == "binary_sensor" and kind in ("motion", "occupancy", "presence") \
                    and entity.get("state") == "on":
                motion = True
    words = words or {}
    parts = []
    if temps:
        parts.append(f"{sum(temps) / len(temps):.1f} °C")
    if hums:
        parts.append(f"{sum(hums) / len(hums):.0f} %")
    if opened:
        parts.append(words.get("open", "{n} open").format(n=opened))
    if motion:
        parts.append(words.get("motion", "motion"))
    return " · ".join(parts)


def matches(device, text):
    text = (text or "").strip().lower()
    if not text:
        return True
    hay = " ".join([device["name"], device["maker"], device["model"], device["area_name"],
                    device["integration"]] + [e.get("id", "") for e in device["entities"]])
    return text in hay.lower()
