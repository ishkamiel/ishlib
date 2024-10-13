
SRC_FILES = $(wildcard src/sh/*.sh) $(wildcard src/bash/*.bash) src/readme_src.md

PYTEST_ARGS = -d -n$(shell nproc)

all: README.md ishlib.sh verify

.PHONY: verify
verify: ishlib.sh $(SRC_FILES)
	$(info === Running tests)
	pytest $(PYTEST_ARGS)

ishlib.sh: $(SRC_FILES) $(BUILD_SCRIPT)
	$(info === Updating $@)
	./build_ishlib.py
	chmod +x $@

README.md: ishlib.sh $(SRC_FILES)
	$(info === Updating $@)
	./ishlib.sh -h --markdown > README.md

print-%:
	@echo $* = $($*)
