#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_common_sh:-}" ] && return 0
ish_SOURCED_common_sh=1 # source guard
###############################################################################

DEBUG=${DEBUG:-0}
DRY_RUN=${DRY_RUN:-0}

export ish_ColorNC='\e[0m'
export ish_ColorBlack='\e[0;30m'
export ish_ColorGray='\e[1;30m'
export ish_ColorRed='\e[0;31m'
export ish_ColorLightRed='\e[1;31m'
export ish_ColorGreen='\e[0;32m'
export ish_ColorLightGreen='\e[1;32m'
export ish_ColorBrown='\e[0;33m'
export ish_ColorYellow='\e[1;33m'
export ish_ColorBlue='\e[0;34m'
export ish_ColorLightBlue='\e[1;34m'
export ish_ColorPurple='\e[0;35m'
export ish_ColorLightPurple='\e[1;35m'
export ish_ColorCyan='\e[0;36m'
export ish_ColorLightCyan='\e[1;36m'
export ish_ColorLightGray='\e[0;37m'
export ish_ColorWhite='\e[1;37m'

ish_ColorNC='\033[0m'
ish_ColorDebug="${ish_ColorNC}"
ish_ColorSay="${ish_ColorBlue}"
ish_ColorWarn="${ish_ColorPurple}"
ish_ColorFail="${ish_ColorRed}"
ish_ColorDryRun="${ish_ColorBrown}"

#------------------------------------------------------------------------------
ish_Version="0.1"
#------------------------------------------------------------------------------
: <<'DOCSTRING'
ishlib 0.1
==========

The following functions are always exposed when sourcing the library and
should be POSIX compliant (e.g., work with sh or dash).

POSIX compliant functions
=========================

DOCSTRING
