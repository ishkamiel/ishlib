
BUILD_SCRIPT = ./build.pl
SRC_FILES = $(wildcard src/*.sh) $(wildcard src/.bash) src/readme_src.md

all: README.md ishlib.sh verify

.PHONY: verify
verify: ishlib.sh
	prove

ishlib.sh: $(SRC_FILES) $(BUILD_SCRIPT)
	echo $(SRC_FILES)
	$(BUILD_SCRIPT) 
	chmod +x $@

README.md: ishlib.sh
	./ishlib.sh -h --markdown > README.md
