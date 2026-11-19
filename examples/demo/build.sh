#!/bin/sh
# Build demo.opd: one "run" file = BASIC loader + screen + code, autostarts with RUN
cd "$(dirname "$0")"
/c/sjasmplus/sjasmplus.exe --nologo --msg=err demo.asm || exit 1
python ../../tools/mkmono.py demo.opd --label DEMO \
    --block screen.scr@16384 --block demo.bin@32768 \
    --start 32768 --sp 32767 --clear 32767 "$@"
python ../../tools/opdtool.py cat demo.opd
