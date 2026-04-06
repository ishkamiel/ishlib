#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

SHELL_SRC_FILES = $(wildcard src/sh/*.sh) $(wildcard src/bash/*.bash)
PY_SRC_FILES = $(wildcard src/pyishlib/*.py)
DOC_SRC_FILES = src/docs/ishlib_shell.md
BUILD_SCRIPT = scripts/build_ishlib.py

PYTEST_ARGS = -d -n$(shell nproc)

all: docs/ishlib_shell.md docs/pyishlib/index.md ishlib.sh verify

.PHONY: verify
verify: ishlib.sh $(SHELL_SRC_FILES)
	$(info === Running tests)
	pytest $(PYTEST_ARGS)

ishlib.sh: $(SHELL_SRC_FILES) $(DOC_SRC_FILES) $(BUILD_SCRIPT)
	$(info === Updating $@)
	./scripts/build_ishlib.py
	chmod +x $@

docs/ishlib_shell.md: ishlib.sh $(SHELL_SRC_FILES) $(DOC_SRC_FILES) | docs
	$(info === Updating $@)
	./ishlib.sh -h --markdown | head -n -1 > $@

docs/pyishlib/index.md: $(PY_SRC_FILES) scripts/build_pydocs.py | docs
	$(info === Updating $@)
	./scripts/build_pydocs.py

docs:
	mkdir -p docs

print-%:
	@echo $* = $($*)
