#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

SHELL_SRC_FILES = $(wildcard src/sh/*.sh) $(wildcard src/bash/*.bash)
DOC_SRC_FILES = src/readme_src.md

PYTEST_ARGS = -d -n$(shell nproc)

all: docs/ishlib_shell.md ishlib.sh verify

.PHONY: verify
verify: ishlib.sh $(SHELL_SRC_FILES)
	$(info === Running tests)
	pytest $(PYTEST_ARGS)

ishlib.sh: $(SHELL_SRC_FILES) $(DOC_SRC_FILES) $(BUILD_SCRIPT)
	$(info === Updating $@)
	./build_ishlib.py
	chmod +x $@

docs/ishlib_shell.md: ishlib.sh $(SHELL_SRC_FILES) $(DOC_SRC_FILES) | docs
	$(info === Updating $@)
	./ishlib.sh -h --markdown | head -n -1 > $@

docs:
	mkdir -p docs

print-%:
	@echo $* = $($*)
