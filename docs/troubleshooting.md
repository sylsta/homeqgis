# Troubleshooting

## SSH: key-based login

The reboot, consoles, logs, server status and the recorder use SSH with your key; no
password is stored (except Home Assistant's optional one). To set it up once per
machine:

```sh
ssh-keygen -t ed25519            # if you have no key yet
ssh-copy-id root@192.168.50.20   # the robot (or user@host for the others)
ssh root@192.168.50.20 true      # must log in without asking anything
```

The SSH button's tooltip shows the exact command used.

## QGIS asks for a master password

Tokens and passwords are stored encrypted in the QGIS authentication database, which
is protected by a master password. QGIS asks for it once per session, the first time
the plugin needs one of them.

## Home Assistant says "No token"

It answers, but without a long-lived access token the plugin can do nothing else.
Create one in Home Assistant (your profile › *Security*) and paste it in the server's
*Access token* (settings, Servers tab).

## A clock is shown in orange

That server's clock is more than 2 minutes off the computer's. Wrong clocks shift the
schedule, the history and the graphs. Turn on NTP on it (for the robot: Valetudo's
NTP settings).

## The camera stays black

- Is **ffmpeg** found? *About › Copy system information* says so.
- The first image waits for the robot's next full image: give it a few seconds.
- Check the stream URL (settings, *Robot* tab, *Camera*).

## A Home Assistant room and a robot room do not match

The robot's cleanings in the Home graphs and *▶ Map* match Home Assistant areas and
robot rooms **by name** (case does not matter). Rename one of them so they match.

## The map is loaded twice

Reopening a project reuses its layers; duplicates left by older versions are removed
when the project is opened. If you still see two sets, remove the *Valetudo* group and
click *Show on map* again.

## Reporting a problem

*⋮ › About… › Copy system information*, then open an issue on
[GitHub](https://github.com/sylsta/qgis-valetudo/issues) with it, and what you did.
The *DomotiQGIS* tab of the QGIS *Log Messages* panel often says more.
