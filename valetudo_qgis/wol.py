"""Wake-on-LAN: the "magic packet" that wakes a computer from sleep or power-off,
sent as a UDP broadcast on the local network.

The computer must allow it: Wake-on-LAN on in its BIOS/UEFI and on its network
card (on Linux: ethtool -s <card> wol g), and usually a wired connection.
"""

import ipaddress
import re
import socket

PORT = 9


def parse_mac(text):
    """b"…" (6 bytes) of a MAC address typed as aa:bb:cc:dd:ee:ff, aa-bb-…,
    aabb.ccdd.eeff or aabbccddeeff; None if it is not one."""
    digits = re.sub(r"[\s:.\-]", "", text or "")
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", digits):
        return None
    return bytes.fromhex(digits)


def format_mac(mac):
    return ":".join(f"{b:02x}" for b in mac)


def magic_packet(mac):
    return b"\xff" * 6 + mac * 16


def broadcasts(host=""):
    """Where to send: everywhere on the local network, and the broadcast of the
    computer's /24 network when its address is an IPv4 one (other networks)."""
    targets = ["255.255.255.255"]
    try:
        address = ipaddress.IPv4Address((host or "").strip())
    except ValueError:
        return targets
    directed = str(ipaddress.IPv4Network(f"{address}/24", strict=False).broadcast_address)
    if directed not in targets:
        targets.append(directed)
    return targets


def wake(mac_text, host=""):
    """Send the magic packet. Returns None, or what went wrong."""
    mac = parse_mac(mac_text)
    if mac is None:
        return "bad_mac"
    packet = magic_packet(mac)
    sent, error = 0, ""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in broadcasts(host):
            try:
                sock.sendto(packet, (target, PORT))
                sent += 1
            except OSError as exc:
                error = str(exc)
    return None if sent else error or "not_sent"
