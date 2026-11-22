#!/usr/bin/env python3
"""Load every Qt Designer form of the plugin and check the names the code uses.

Usage: python3 scripts/check_ui.py
Needs PyQt5 (Debian/Ubuntu: python3-pyqt5), not QGIS: the QGIS widgets used in
the forms are replaced by plain Qt stand-ins. Exit code 1 on any problem.

For each module that calls load_ui("<form>.ui", ...), the object names listed
in its UI_WIDGETS tuple (and the keys of its SECTIONS dict, if any) must exist
in the form. Every form's <class> must be the plugin's translation context.
"""

import ast
import os
import pathlib
import sys
import types
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "valetudo_qgis"
CONTEXT = "ValetudoQgis"


def module_constants():
    """Module-level literal assignments of every plugin module: {name: value}."""
    found = {}
    for path in PLUGIN.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                found.setdefault(node.targets[0].id, node.value)
    return found


def names_in(node, constants):
    """String names of a tuple/list/dict literal; *NAME is looked up in constants."""
    if isinstance(node, ast.Dict):
        return [k.value for k in node.keys if isinstance(k, ast.Constant)]
    names = []
    for elt in getattr(node, "elts", []):
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            names.append(elt.value)
        elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name) \
                and elt.value.id in constants:
            names += names_in(constants[elt.value.id], constants)
    return names


def required_names():
    """{form file name: [object names the code needs]}."""
    constants = module_constants()
    required = {}
    for path in PLUGIN.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forms = [node.args[0].value for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "load_ui" and node.args
                 and isinstance(node.args[0], ast.Constant)]
        local = {n.targets[0].id: n.value for n in tree.body
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name)}
        for form in forms:
            names = required.setdefault(form, [])
            for const in ("UI_WIDGETS", "SECTIONS"):
                if const in local:
                    names += names_in(local[const], constants)
    return required


def install_qgis_stand_ins(QtWidgets):
    """The forms import their QGIS widgets from qgis.gui: plain Qt look-alikes."""
    gui = types.ModuleType("qgis.gui")
    gui.QgsCollapsibleGroupBox = type("QgsCollapsibleGroupBox", (QtWidgets.QGroupBox,), {})
    gui.QgsAuthConfigSelect = type("QgsAuthConfigSelect", (QtWidgets.QWidget,), {})
    gui.QgsFileWidget = type("QgsFileWidget", (QtWidgets.QWidget,), {})
    qgis = types.ModuleType("qgis")
    qgis.gui = gui
    sys.modules["qgis"] = qgis
    sys.modules["qgis.gui"] = gui


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5 import QtWidgets, uic
    except ImportError:
        print("PyQt5 is needed (python3-pyqt5).")
        return 1
    install_qgis_stand_ins(QtWidgets)
    app = QtWidgets.QApplication([])   # noqa: F841 (widgets need it)

    ok = True
    required = required_names()
    forms = sorted((PLUGIN / "ui").glob("*.ui"))
    for path in forms:
        root = ET.parse(path).getroot()
        if root.findtext("class") != CONTEXT:
            print(f"{path.name}: <class> must be {CONTEXT!r} (translation context)")
            ok = False
        base_class = root.find("widget").get("class")
        base = getattr(QtWidgets, base_class)()
        try:
            uic.loadUi(str(path), base)
        except Exception as exc:   # report every form, not just the first failure
            print(f"{path.name}: cannot be loaded: {exc}")
            ok = False
            continue
        missing = [n for n in required.get(path.name, []) if getattr(base, n, None) is None]
        if missing:
            print(f"{path.name}: missing object(s) {', '.join(missing)}")
            ok = False
        else:
            print(f"{path.name}: OK ({len(required.get(path.name, []))} names checked)")
    for form in required:
        if not (PLUGIN / "ui" / form).exists():
            print(f"{form}: loaded by the code but not found in valetudo_qgis/ui/")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
