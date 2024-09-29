
SRC_FILES = $(wildcard src/*.sh) $(wildcard src/*.bash) src/readme_src.md

PYTEST_ARGS = -n$(shell nproc)

all: README.md ishlib.sh verify

.PHONY: verify
verify: ishlib.sh $(SRC_FILES)
	$(info === Running tests)
	pytest $(PYTEST_ARGS)

ishlib.sh: $(SRC_FILES) $(BUILD_SCRIPT)
	$(info === Updating $@)
	./build.pl
	chmod +x $@

README.md: ishlib.sh $(SRC_FILES)
	$(info === Updating $@)
	./ishlib.sh -h --markdown > README.md
