#!/bin/sh
# Terminator 2 on the Opus, 48K: every stage from the disk. For N in 1..8 build a test image whose game starts at stage N
# (build_opus.py --start N --nointro), turn the DUPE cheat on, play a while (fights are won by #7E0F = 0, so the next stage
# loads too) and compare every read with the file.      sh run_t2levels.sh [ROM] [stages]    -> log_levels.log
T2=${T2_DIR:-/c/Users/User/Claude-Fable/T2}
ROM=${1:-"Opus Discovery 1 v2.22 (1985)(Opus Supplies).rom"}
LV=${2:-"1 2 3 4 5 6 7 8"}
RUNPY=$(cd "$(dirname "$0")" && pwd)/run_t2.py
for N in $LV; do
  (cd "$T2" && python tools/build_opus.py --nointro --start $N --extra run=$(cd "$(dirname "$RUNPY")/.." && pwd)/build/run.opus > build/opus/levels_build_$N.log 2>&1) || { echo "stage $N: build failed"; continue; }
  D="$T2/build/opus/s$N"; mkdir -p "$D"
  for f in T2.bin layout.json kern48.sym disk.sym T2_opus_sd.opd T2_opus_dd.dsk; do cp "$T2/build/opus/$f" "$D/"; done
  case $N in 1|4|7) F=1 ;; *) F= ;; esac
  echo "== stage $N"
  T2_OB="$D" T2_DUPE=1 T2_FIGHT=$F T2_TAG=_s$N T2_MACHINES=48k T2_PLAY=${T2_PLAY:-3000} python "$RUNPY" "$ROM" 2>&1 | grep -v "^harness\|^==\|^FAIL"
done
