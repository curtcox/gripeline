# One entry point for people and coding agents. Python 3 standard library only:
# there is no install step. `make check` runs everything CI's `test` job runs.
#
# Optional tools, used when present and skipped (not failed) when absent:
#   dot  (Graphviz)       -- real dot-valid checks; otherwise a brace-check fallback
#   node + ../modl        -- parity with modl's own parser (a curtcox/modl checkout)

PY        ?= python3
GRIPELINE ?= python3 gripeline.py
# Use a sibling curtcox/modl checkout for parity checks if one exists.
MODL_REPO ?= $(if $(wildcard ../modl/js/editor.js),../modl)
export MODL_REPO

.PHONY: help check test test-shim units site

help:
	@echo "make check      conformance fixtures + unit tests (what CI runs)"
	@echo "make test       conformance fixtures only, quiet (FILTER=substring to narrow)"
	@echo "make test-shim  conformance fixtures via the ./gripeline shim"
	@echo "make units      unit tests only"
	@echo "make site       build the GitHub Pages site into site/_site/"

check: test units

test:
	GRIPELINE='$(GRIPELINE)' $(PY) tests/run.py -q $(FILTER)

test-shim:
	GRIPELINE=./gripeline $(PY) tests/run.py -q $(FILTER)

units:
	$(PY) tests/test_units.py

site:
	$(PY) site/build.py
