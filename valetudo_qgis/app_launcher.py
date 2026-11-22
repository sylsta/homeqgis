"""DomotiQGIS as an app: QGIS started with a profile of its own, the robot project
and only what the plugin needs on screen.

create() sets up, from the profile in use:

    <profiles>/DomotiQGIS/                     the profile (QGIS treats any folder there as one)
        python/plugins/valetudo_qgis           the plugin: a link to this one (a copy where
                                               links are not possible)
        QGIS/QGIS3.ini                         the plugin enabled, "app mode" on, the robot
                                               project opened with the map; the plugin's
                                               settings copied, if asked
        domotiqgis.png / .ico                  the launcher's icon

and a launcher: a .desktop file (Linux), a .lnk shortcut (Windows) or a small .app
(macOS), on the desktop and in the applications menu. It runs

    qgis --profile DomotiQGIS --profiles-path <path> --nologo
         --authdbdirectory <this profile> --project <robot project>

(--authdbdirectory: the tokens and passwords of this profile, shared if asked.)

In the profile, the plugin sees "app mode" (KEY_APP_MODE) and hides QGIS's other
toolbars and panels (plugin.py, _apply_app_mode).
"""

import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys

from qgis.PyQt.QtCore import QCoreApplication, QProcess, QSettings, QStandardPaths
from qgis.core import QgsApplication, QgsSettings

from .icons import APP_ICON, icon

APP_NAME = "DomotiQGIS"
DEFAULT_PROFILE = "DomotiQGIS"
PLUGIN_FOLDER = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
# This profile is the app: only the plugin on screen. Outside "valetudo/", so that it
# is never copied to another profile nor saved in a configuration backup.
KEY_APP_MODE = "domotiqgis/app_mode"
# The profile the launcher was created from, and the one used before the app was last
# started: QGIS started alone opens the latter again, not the app's
KEY_HOME_PROFILE = "domotiqgis/home_profile"
KEY_PREVIOUS_PROFILE = "domotiqgis/previous_profile"
SETTINGS_GROUP = "valetudo/"
PROFILE_FILES = ("valetudo_room_groups.ini",)   # the plugin's own files in a profile


def current_profile_folder():
    """The folder of the profile in use (…/profiles/default)."""
    return os.path.normpath(QgsApplication.qgisSettingsDirPath())


def profiles_root():
    """The folder holding the profiles (…/QGIS3/profiles)."""
    return os.path.dirname(current_profile_folder())


def qgis_command():
    """How to start this QGIS: [program, arguments…]."""
    flatpak = os.environ.get("FLATPAK_ID")
    if flatpak:
        return ["flatpak", "run", flatpak]
    program = QCoreApplication.applicationFilePath() or sys.executable
    return [program]


def _profile_exists(name):
    return bool(name) and "/" not in name and "\\" not in name \
        and os.path.isdir(os.path.join(profiles_root(), name))


def _profiles_ini():
    return QSettings(os.path.join(profiles_root(), "profiles.ini"), QSettings.Format.IniFormat)


def remember_previous_profile():
    """At the app's start: the last profile QGIS recorded is still the one used before
    the app (QGIS records it when it exits). Keep it, to give it back at exit."""
    this = os.path.basename(current_profile_folder())
    last = _profiles_ini().value("core/lastProfile", "")
    if last and last != this and _profile_exists(last):
        QgsSettings().setValue(KEY_PREVIOUS_PROFILE, last)


def previous_profile():
    """The profile used before the app: remembered at start, else the one the launcher
    was created from, else "default" (launchers of the first version)."""
    settings = QgsSettings()
    for name in (settings.value(KEY_PREVIOUS_PROFILE, "", type=str),
                 settings.value(KEY_HOME_PROFILE, "", type=str), "default"):
        if _profile_exists(name):
            return name
    return ""


def restore_last_profile_after_exit():
    """QGIS remembers the last profile used (profiles.ini, core/lastProfile) and opens
    it when started alone; it writes it while it exits, after any plugin could: after
    the app, that would be the app's profile. A small process, detached, waits for
    this QGIS to be gone and writes back the profile used before the app.
    Connected to QApplication.aboutToQuit."""
    home = previous_profile()
    if not home:
        return
    path = os.path.join(profiles_root(), "profiles.ini")
    pid = QCoreApplication.applicationPid()
    if platform.system() == "Windows":
        def ps(text):
            return "'" + text.replace("'", "''") + "'"
        script = (f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
                  f"$f = {ps(path)}; "
                  "(Get-Content -LiteralPath $f) -replace '^lastProfile=.*', "
                  f"{ps('lastProfile=' + home)} | Set-Content -LiteralPath $f")
        program, arguments = "powershell", ["-NoProfile", "-NonInteractive",
                                            "-WindowStyle", "Hidden", "-Command", script]
    else:
        file = shlex.quote(path)
        script = (f"while kill -0 {pid} 2>/dev/null; do sleep 1; done; "
                  f"t=$(mktemp) && sed 's/^lastProfile=.*/lastProfile={home}/' {file} > \"$t\" "
                  f"&& cat \"$t\" > {file}; rm -f \"$t\"")
        program, arguments = "sh", ["-c", script]
    QProcess.startDetached(program, arguments)


def launch_command(profile, project, auth_folder=""):
    """auth_folder: the folder of the authentication database to use (that of the
    usual profile: same tokens and passwords, same master password in the wallet)."""
    root = profiles_root()
    # --profiles-path takes the folder that contains "profiles"
    base = os.path.dirname(root) if os.path.basename(root) == "profiles" else root
    command = qgis_command() + ["--profile", profile, "--profiles-path", base, "--nologo"]
    if auth_folder:
        command += ["--authdbdirectory", auth_folder]
    return command + ["--project", project]


# -- the profile ----------------------------------------------------------------------

def _link_plugin(target):
    """The plugin in the new profile: a link to this one, so that it stays up to date.
    Returns "link" or "copy"."""
    source = os.path.dirname(os.path.abspath(__file__))
    if os.path.lexists(target):
        if os.path.islink(target) or not os.path.isdir(target):
            os.remove(target)
        else:
            shutil.rmtree(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        os.symlink(source, target, target_is_directory=True)
        return "link"
    except (OSError, NotImplementedError):
        pass
    if platform.system() == "Windows":   # a junction needs no administrator rights
        result = subprocess.run(["cmd", "/c", "mklink", "/J", target, source],
                                capture_output=True, text=True)
        if result.returncode == 0 and os.path.isdir(target):
            return "link"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    return "copy"


def _settings_file(profile_folder):
    path = os.path.join(profile_folder, "QGIS", "QGIS3.ini")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return QSettings(path, QSettings.Format.IniFormat)


def create(profile, project, copy_settings=True, copy_secrets=True, desktop=True,
           menu=True):
    """Set up the app's profile and its launcher. Returns a dict: profile (folder),
    plugin ("link" or "copy"), secrets (copied or not), launchers (paths)."""
    folder = os.path.join(profiles_root(), profile)
    if os.path.normcase(folder) == os.path.normcase(current_profile_folder()):
        raise ValueError("same_profile")
    os.makedirs(folder, exist_ok=True)
    result = {"profile": folder, "launchers": [], "secrets": False}
    result["plugin"] = _link_plugin(os.path.join(folder, "python", "plugins", PLUGIN_FOLDER))

    target = _settings_file(folder)
    if copy_settings:
        source = QgsSettings()
        for key in source.allKeys():
            if key.startswith(SETTINGS_GROUP):
                target.setValue(key, source.value(key))
        for name in PROFILE_FILES:
            path = os.path.join(current_profile_folder(), name)
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(folder, name))
    target.setValue(f"PythonPlugins/{PLUGIN_FOLDER}", True)
    target.setValue("PythonPlugins/processing", True)   # the Wi-Fi map's interpolation
    target.setValue(KEY_APP_MODE, True)
    target.setValue(KEY_HOME_PROFILE, os.path.basename(current_profile_folder()))
    target.setValue("valetudo/live_at_start", True)
    target.setValue("valetudo/robot_project", project)
    target.sync()

    # Tokens and passwords: the app uses this profile's authentication database itself
    # (QGIS's --authdbdirectory): kept in step, and the master password stored in the
    # wallet for it serves both (QGIS names its wallet entry after that folder).
    auth_folder = current_profile_folder() if copy_secrets else ""
    result["secrets"] = bool(auth_folder)
    command = launch_command(profile, project, auth_folder)
    result["command"] = command
    png, ico = _write_icons(folder)
    if desktop:
        result["launchers"] += _launchers(_location(QStandardPaths.StandardLocation
                                                    .DesktopLocation), command, png, ico)
    if menu:
        result["launchers"] += _launchers(_location(QStandardPaths.StandardLocation
                                                    .ApplicationsLocation), command, png, ico)
    return result


def _location(kind):
    path = QStandardPaths.writableLocation(kind)
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def _write_icons(folder):
    pixmap = icon(APP_ICON).pixmap(256, 256)
    png, ico = os.path.join(folder, "domotiqgis.png"), os.path.join(folder, "domotiqgis.ico")
    pixmap.save(png, "PNG")
    if platform.system() == "Windows" and not pixmap.save(ico, "ICO"):
        ico = ""
    return png, ico


# -- launchers ---------------------------------------------------------------------

def desktop_entry(command, icon_path):
    """A freedesktop .desktop file (Linux)."""
    def quote(arg):
        if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
            return arg
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") \
            .replace("$", "\\$") + '"'
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Robot vacuum, home and servers, in QGIS\n"
            f"Exec={' '.join(quote(a) for a in command)}\n"
            f"Icon={icon_path}\nTerminal=false\nCategories=Utility;\n")


def _launchers(folder, command, png, ico):
    if not folder:
        return []
    system = platform.system()
    if system == "Windows":
        return [_windows_shortcut(os.path.join(folder, f"{APP_NAME}.lnk"), command, ico)]
    if system == "Darwin":
        return [_mac_app(os.path.join(folder, f"{APP_NAME}.app"), command)]
    path = os.path.join(folder, "domotiqgis.desktop")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(desktop_entry(command, png))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # GNOME: a launcher on the desktop runs only once trusted
    if shutil.which("gio"):
        subprocess.run(["gio", "set", path, "metadata::trusted", "true"],
                       capture_output=True)
    return [path]


def _windows_shortcut(path, command, ico):
    def ps(text):
        return "'" + text.replace("'", "''") + "'"
    arguments = subprocess.list2cmdline(command[1:])
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut({path}); "
              "$s.TargetPath = {target}; $s.Arguments = {args}; "
              "$s.WorkingDirectory = {work}; {icon}$s.Save()").format(
        path=ps(path), target=ps(command[0]), args=ps(arguments),
        work=ps(os.path.dirname(command[0])),
        icon=f"$s.IconLocation = {ps(ico)}; " if ico else "")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0 or not os.path.exists(path):
        raise OSError((result.stderr or result.stdout or "PowerShell").strip())
    return path


def _mac_app(path, command):
    """A minimal application bundle that runs the command."""
    macos = os.path.join(path, "Contents", "MacOS")
    os.makedirs(macos, exist_ok=True)
    script = os.path.join(macos, APP_NAME)
    with open(script, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\nexec " + " ".join(shlex.quote(a) for a in command) + "\n")
    os.chmod(script, 0o755)
    with open(os.path.join(path, "Contents", "Info.plist"), "w", encoding="utf-8") as handle:
        handle.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            f"<key>CFBundleName</key><string>{APP_NAME}</string>"
            f"<key>CFBundleExecutable</key><string>{APP_NAME}</string>"
            "<key>CFBundleIdentifier</key><string>io.github.sylsta.domotiqgis</string>"
            "<key>CFBundlePackageType</key><string>APPL</string>"
            "</dict></plist>\n")
    return path
