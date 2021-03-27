# ishlib

This is a collection of various scripts and tricks collected along the years.

The script is meant to be sourced elsewhere, but can be invoked as
`./ishlib.sh -h` flag to show the same documentation as below. The source
files in `./src` need not be manually used, they are already in `ishlib.sh`.

The documentation contains references to original sources where available,
but in practice this has been accumulated along the years, so many sources
are likely listed. Feel free to drop me a note if you notice some source or
acknowledgement that is missing.

## FIXME

- dry_run docs are wrong!

## Documentation



export TERM_COLOR_NC='\e[0m'
export TERM_COLOR_BLACK='\e[0;30m'
export TERM_COLOR_GRAY='\e[1;30m'
export TERM_COLOR_RED='\e[0;31m'
export TERM_COLOR_LIGHT_RED='\e[1;31m'
export TERM_COLOR_GREEN='\e[0;32m'
export TERM_COLOR_LIGHT_GREEN='\e[1;32m'
export TERM_COLOR_BROWN='\e[0;33m'
export TERM_COLOR_YELLOW='\e[1;33m'
export TERM_COLOR_BLUE='\e[0;34m'
export TERM_COLOR_LIGHT_BLUE='\e[1;34m'
export TERM_COLOR_PURPLE='\e[0;35m'
export TERM_COLOR_LIGHT_PURPLE='\e[1;35m'
export TERM_COLOR_CYAN='\e[0;36m'
export TERM_COLOR_LIGHT_Cyan='\e[1;36m'
export TERM_COLOR_LIGHT_GRAY='\e[0;37m'
export TERM_COLOR_WHITE='\e[1;37m'

# shellcheck disable=SC2034
ish_ColorNC='\033[0m'
# shellcheck disable=SC2034
ish_ColorDebug="${TERM_COLOR_NC}"
# shellcheck disable=SC2034
ish_ColorSay="${TERM_COLOR_BLUE}"
# shellcheck disable=SC2034
ish_ColorWarn="${TERM_COLOR_PURPLE}"
# shellcheck disable=SC2034
ish_ColorFail="${TERM_COLOR_RED}"
# shellcheck disable=SC2034
ish_ColorDryRun="${TERM_COLOR_BROWN}"

say "${ish_VERSION_NAME} ${ish_VERSION_NUMBER} (${ish_VERSION_VARIANT})"

export ish_VERSION_NAME="__ISHLIB_NAME__"
export ish_VERSION_NUMBER="__ISHLIB_VERSION__"
export ish_VERSION_VARIANT="POSIX"


export ish_VERSION_VARIANT="POSIX+bash"
