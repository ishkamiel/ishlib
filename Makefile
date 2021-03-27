
BUILD_SCRIPT = ./build.pl
SRC_FILES = $(wildcard src/*.sh) $(wildcard src/.bash)

build_and_verify: ishlib.sh
	prove

ishlib.sh: $(SRC_FILES) $(BUILD_SCRIPT) README.md
	$(BUILD_SCRIPT) 
	chmod +x $@
