# HomeQGIS: checks, translations, manual and the plugin's zip.
#
#   make            this help
#   make check      the same checks as the CI (syntax, names, translations, forms)
#   make zip        dist/homeQGIS-<version>.zip, ready for QGIS
#                   (Plugins › Manage and Install Plugins › Install from ZIP)
#   make release    the zip, from a clean and pushed main, tagged v<version>
#   make install    the plugin into a QGIS profile (PROFILE=default), for testing
#   make clean      remove what the build makes
#
# Needs: python3, zip, Qt's lrelease (qttools5-dev-tools or qt6-l10n-tools), mkdocs
# with mkdocs-material (pip install "mkdocs>=1.6,<2" "mkdocs-material>=9.5,<10").
# PyQt5 for the forms check (python3-pyqt5); without it, that check is skipped.

PLUGIN  := homeQGIS
PYTHON  ?= python3
VERSION := $(shell sed -n 's/^version=//p' $(PLUGIN)/metadata.txt)
DIST    := dist
ZIP     := $(DIST)/$(PLUGIN)-$(VERSION).zip
PROFILE ?= default
# Where QGIS keeps a profile's plugins (Linux; set QGIS_PLUGINS elsewhere)
QGIS_PLUGINS ?= $(HOME)/.local/share/QGIS/QGIS3/profiles/$(PROFILE)/python/plugins

.DEFAULT_GOAL := help
.PHONY: help check translations doc zip release install clean

help:
	@sed -n 's/^#   //p' Makefile
	@echo
	@echo "Version: $(VERSION) (from $(PLUGIN)/metadata.txt)"

check:
	$(PYTHON) -m compileall -q $(PLUGIN) scripts pi
	$(PYTHON) scripts/check_names.py
	$(PYTHON) scripts/check_translations.py
	@if $(PYTHON) -c "import PyQt5" 2>/dev/null; then \
		$(PYTHON) scripts/check_ui.py; \
	else \
		echo "PyQt5 not found: Qt Designer forms not checked (python3-pyqt5)."; \
	fi

translations:
	scripts/compile_translations.sh

# The manual, also copied into the plugin (its "User manual" entry opens it)
doc:
	mkdocs build --strict -q -d site
	rm -rf $(PLUGIN)/doc
	cp -r site $(PLUGIN)/doc

zip: check translations doc
	@test -n "$(VERSION)" || { echo "No version in $(PLUGIN)/metadata.txt"; exit 1; }
	mkdir -p $(DIST)
	rm -f $(ZIP)
	zip -qr $(ZIP) $(PLUGIN) \
		-x '*__pycache__*' '*.py[cod]' '$(PLUGIN)/i18n/*.ts' '*.swp' '*.autosave' '*/.DS_Store'
	@echo "$(ZIP): $$(du -h $(ZIP) | cut -f1), $$(unzip -l $(ZIP) | tail -1 | awk '{print $$2}') files"

# A release: the zip of a committed, pushed main, and its tag (pushed after asking).
release:
	@test "$$(git rev-parse --abbrev-ref HEAD)" = main || { echo "Not on main."; exit 1; }
	@test -z "$$(git status --porcelain)" || { echo "Uncommitted changes: commit first."; exit 1; }
	@git fetch -q origin main
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" \
		|| { echo "main is not the same as origin/main: push or pull first."; exit 1; }
	@! git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null \
		|| { echo "Tag v$(VERSION) exists: raise the version in $(PLUGIN)/metadata.txt."; exit 1; }
	$(MAKE) zip
	git tag -a "v$(VERSION)" -m "HomeQGIS $(VERSION)"
	@echo
	@echo "Tagged v$(VERSION). To publish it: git push origin v$(VERSION)"
	@echo "then attach $(ZIP) to a GitHub release (gh release create v$(VERSION) $(ZIP))."

install: translations
	mkdir -p "$(QGIS_PLUGINS)"
	rm -rf "$(QGIS_PLUGINS)/$(PLUGIN)"
	cp -r $(PLUGIN) "$(QGIS_PLUGINS)/"
	find "$(QGIS_PLUGINS)/$(PLUGIN)" -name __pycache__ -prune -exec rm -rf {} +
	@echo "Installed in $(QGIS_PLUGINS)/$(PLUGIN): restart QGIS, or reload the plugin."

clean:
	rm -rf $(DIST) site $(PLUGIN)/doc
	rm -f $(PLUGIN)/i18n/*.qm
	find . -name __pycache__ -prune -exec rm -rf {} +
