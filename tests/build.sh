#!/bin/sh
# build.sh FAST -> libtest.bin + libtest.sym
cd "$(dirname "$0")"
/c/sjasmplus/sjasmplus.exe --nologo -DOD_FAST=${1:-1} --sym=libtest.sym --lst=libtest.lst libtest.asm
