# Opus Discovery: disk access from machine code

Everything needed to put a game or program onto Opus Discovery disks and to use the disk from
your own code, independent of the ROM version (v1.2, v2.2, v2.22, EXCOM 2.28, QuickDOS 2.31):

* the library `opuslib`: sectors and blocks, files by name (with the 7-byte header, and raw
  files whose whole description is in the catalogue), loads exact to the byte, the Opus 2K RAM
  optional;
* compact drivers for resident loaders: `opio256` (the standard 180K/720K disks, 355 bytes) and
  `opio` (any format, 469 bytes);
* the monoblock, as known from TR-DOS: one BASIC file holding the loader and all the data;
  `mkmono.py` builds it in one command;
* the launcher `run`: a menu of the programs on a disk;
* tools for disk images (`.opd`, `.dsk`) and automated tests in the ZX-M8XXX emulator;
* two finished ports, Sea Dragon and Terminator 2 (48K/128K, high scores), taken apart in
  [`PORTING.md`](PORTING.md).

**Release formats: 180K (40×1×18×256) and 720K (80×2×18×256).** One and the same file works on
both (`mkmono --std`, `opio256`). Details in §2.

**Porting a game? Start with [`PORTING.md`](PORTING.md)**: the order of work, the rules a port
breaks without, a checklist. This file is the reference.
Русская версия: [`README.ru.md`](README.ru.md), [`PORTING.ru.md`](PORTING.ru.md).

```
src/opuslib.asm     the library (sjasmplus): blocks, files, raw files
src/opio256.asm     compact driver for 180K/720K (256-byte sectors, no anchor), 355 bytes
src/opio.asm        compact driver for any format (256/512, geometry from the anchor), 469 bytes
src/mono.asm        monoblock loader on the library (--std, --universal)
src/monotiny.asm    minimal monoblock loader (~290 bytes with its table)
src/shell.asm       the launcher run: choose a program on the disk
tools/mkmono.py     builds a monoblock: BASIC loader + blocks in one file
tools/mkshell.py    builds run and adds it to existing images
tools/opdtool.py    .opd/.dsk images: create, catalogue, files, BASIC tokenizer
tools/dskinfo.py    CPCEMU .dsk dump: sector IDs in physical order
tools/romdis.py     ROM disassembler (research)
tools/zxharness.py  headless ZX-M8XXX: load, keys, memory, screenshots
tests/              automated tests: library, raw files, drivers, monoblocks, launcher, games
examples/demo/      example: screen + code, starts with RUN
```

## Quick start

You need Python 3 and [sjasmplus](https://github.com/z00m128/sjasmplus) (path in `SJASMPLUS`,
default `C:\sjasmplus\sjasmplus.exe`).

```bash
# a screen and code in one file, on a 180K and a 720K disk
python tools/mkmono.py game.opd --std --dsdd-out game720.opd \
    --block screen.scr@16384 --block game.bin@24576 --start 32768 --name GAME
python tools/mkshell.py --add game.opd game720.opd     # the launcher run
```

The tests need the ZX-M8XXX emulator (`ZXM8XXX` = its folder, the Opus ROMs in `roms/`) and a
Chromium browser (`EDGE`); the game tests find the games' repositories via `SEADRAGON` and
`T2_DIR`.

## 1. What is taken from the ROM (the same in every version)

Checked byte by byte in v1.2, v2.2, v2.22, EXCOM 2.28 and QuickDOS 2.31:

| Address | Purpose |
|---|---|
| `CALL #1708` | page the Opus ROM in; all registers preserved |
| `CALL #1748` | page it out (a `RET` there; flags and registers preserved) |
| `#0066` | NMI vector = `JP (HL)`. The FDC's DRQ is wired to the NMI: every byte of a sector raises an NMI, so HL must point at your handler during a transfer |

Everything else the library does itself through the WD1770 and MC6821 PIA registers, so it does
not depend on the ROM version: no `RST #30` jump tables, no ROM system variables.

While the Opus is paged in, `#0000-#3FFF` holds the Opus ROM, RAM and ports: code, buffers and
the stack must be at `#4000` or above.

**Registers** (memory mapped, not ports):

| Address | Read | Write |
|---|---|---|
| `#2800` | status | command |
| `#2801` | track | track |
| `#2802` | sector | sector |
| `#2803` | data | data |
| `#3000` | PIA port A | b0/b1 drive 1/2 select, b4 side, b5 FM (0 = MFM), b7 joystick mode |
| `#3001` | PIA control A | b2 = 1 → `#3000` is the data register (the ROM keeps its own flags in b0/b1) |

## 2. Disk format

The geometry is **not fixed**. The ROM reads the anchor sector (track 0, side 0, sector 0 =
block −1) and takes byte 2 = tracks, byte 3 = sectors per track, byte 4 = flags (b7-6 sector size:
01 = 256, 10 = 512, 11 = 1024; b5 FM; b4 two sides). Formats seen in practice:

| | tracks × sides × sectors × bytes | flags | size | catalogue |
|---|---|---|---|---|
| "SD", SSSD (the Opus standard) | 40 × 1 × 18 × 256 | `#40` | 180K | blocks 0-6 (112 entries), DJr formatter 0-4 |
| DSDD | 80 × 2 × 18 × 256 | `#50` | 720K | blocks 0-6 (112 entries) |
| "DD" | 80 × 2 × 10 × 512 | `#90` | 800K | blocks 0-6 (224 entries) |

All are MFM at 250 kbit/s physically; "SD/DD" are Opus names here, not FM/MFM.

**Releases: 180K and 720K only.** Every machine reads 180K (also one without the 2K RAM, where
the ROM keeps its drive tables) and so does a Gotek; 720K is the other standard format. 800K with
512-byte sectors is outside the spec and a Gotek does not take it. For 180K and 720K the geometry
need not be read: both have 18 sectors of 256 bytes, and side 1 of a 720K disk starts after
track 79, which a file on a 180K disk never reaches (`mkmono --std`, `opio256`; why, in
[`PORTING.md`](PORTING.md) §2.3a). A raw image of a double-sided disk (`.opd`, like a Gotek or
Greaseweazle `.img`) stores the tracks alternating between the sides: cylinder 0 side 0, cylinder 0
side 1, ...

- Sectors are numbered from 0. **A logical block is one sector of whatever size.**
- **Logical block B** (as the ROM computes it, routine at `#11DA` in the disassembly):
  `real = B+1; sector = real mod SPT; t = real div SPT; track = t mod TPS; side = t div TPS`.
  On a double-sided disk **the whole of side 0 is filled first**, then side 1.
- The catalogue takes blocks 0..N, N = "last block" of entry 0. 16-byte entries:
  `DW bytes_in_last_block−1, DW first_block, DW last_block, DS 10 name`. Entry 0 is the disk
  label (blocks 0-6). Files are contiguous and sorted by their first block. End marker: first
  block = number of blocks on the disk, last block = `#FFFF`.
- A file starts with a 7-byte header: `type, length, param1, param2` (BASIC: autostart line and
  program length; CODE: address and `#8000`).
- Physical sector order written by the ROM formatter: **step +7**. 18 × 256: 0, 7, 14, 3, 10,
  17, ..., each next track starting one sector later. 10 × 512: 7, 4, 1, 8, 5, 2, 9, 6, 3, 0, the
  start alternating 7/2. Reading in number order takes about `step` revolutions per track, in
  physical order about one. (Section 4 of the manual says step 11: that is wrong; van Dongen's
  table and real images agree on 7.)

## 3. The library `src/opuslib.asm`

```asm
        DEFINE OD_BUF #7E00     ; a one-sector buffer for an Opus WITHOUT RAM (optional)
        INCLUDE "opuslib.asm"
```

**Exactness.** The NMI handlers count bytes in BC. A read stores exactly the requested number of
bytes and takes the rest of the sector from the controller and drops it, so nothing past the end
of a file or block is ever written, not even for a moment, and no 512-byte buffer is needed for
that. `od_load` and `od_save` touch no memory outside the file at all: the first block (with the
7-byte header) goes through `OD_BUF`.

**Timing (real hardware).** A byte every 32 µs = 112 T-states; the read NMI takes about 84. In
`#4000-#7FFF` the ULA stretches execution while drawing the screen and a byte can be lost (the
emulator does not model this).

**Opus RAM.** Most units carry an optional 2K RAM at `#2000-#27FF`, visible only while the Opus
is paged in, i.e. exactly when the NMIs happen. All five ROMs use only `#2000-#208F` (tables; do
not touch, the ROM's interrupt handler at `#0048` reads them) and `#2780-#27FF` (anchor code).
Every `od_init` checks for the RAM (writes two different bytes to `#26FE/#26FF`, reads them back,
restores them). With the RAM:
- the NMI handlers are copied to `#2100`, and **the library can live anywhere**, contended memory
  included: only the handler is time-critical;
- `#2200` (1K) is the sector buffer, and **no Spectrum memory is needed for a buffer**.

Without the RAM the handlers run from the library code (keep it above `#8000` on real hardware)
and `OD_BUF` is the buffer; without that too, the file routines return CY, A = `#FE`. To never use
the RAM: `DEFINE OD_ORAM 0`.

Configuration (`DEFINE` before the `INCLUDE`, or `sjasmplus -DNAME=value`; **sjasmplus `IFNDEF`
only sees DEFINEs, not labels set with `=`**):

| Name | Default | |
|---|---|---|
| `OD_ORAM` | 1 | use the Opus RAM when present |
| `OD_FAST` | 1 | 1 = read/write in rotational order (the step is detected with two Read Address commands), 0 = in number order |
| `OD_SAVE` | 1 | include writing (`od_write`, `od_wsec`, `od_save`, `od_rsave`) |
| `OD_FILES` | 1 | include `od_find`, `od_load`, `od_geom` (and the raw files) |
| `OD_RAW` | 1 | include `od_rload` / `od_rsave` |
| `OD_RATE` | 0 | step rate: 0..3 = 6/12/20/30 ms |
| `OD_RETRY` | 6 | retries per sector |
| `OD_TOUT` | 3 | command timeout, units of ~1.1 s |
| `OD_TPS0` / `OD_SPT0` / `OD_SPG0` | 40 / 18 / 1 | initial `od_tps` (tracks per side), `od_spt`, `od_spg` (sector size / 256) |
| `OD_MAXSPT` | 24 | most sectors per track for the fast reader |

Set the geometry by calling `od_geom` (reads the anchor as the ROM does) or by writing
`od_tps` / `od_spt` / `od_spg`. `OD_BUF` (a DEFINE, not a label) must hold one sector of the
largest size in use.

Sizes (without raw files, `OD_RAW=0`): everything 1608 bytes (`OD_FAST=1`) or 1246 (`OD_FAST=0`);
without writing 1460 / 1098; block reading only 1037 / 675 (without the Opus RAM support,
`OD_ORAM=0`, the minimum is 592). The raw files add 612 bytes.

### High level (page the Opus in and out themselves, return with DI)

| Routine | In | Out |
|---|---|---|
| `od_read` | HL = first block, B = blocks (1..255), DE = address; `od_tail` = bytes wanted from the last block (0 = whole) | NC ok; CY error, A = status. `od_tail` is cleared |
| `od_write` | the same | the same; write protect = bit 6 of A |
| `od_find` | HL → name (10 chars, space padded) | NC: HL = first block, DE = last, A = bytes in the last − 1; also `od_flast` (word) and `od_fcblk` (catalogue block of the entry) |
| `od_load` | HL → name, DE = address (0 = from the header) | NC: HL = length, DE = address, A = type |
| `od_save` | HL → name, DE = address, BC = length | overwrites an **existing** file in place (a save slot), the catalogue unchanged; CY + A = `#FF` if the file is too small |
| `od_geom` | (drive = `od_unit`) | NC: A = anchor flags; `od_tps`, `od_spt`, `od_spg` set |
| `od_rload` | HL → name, DE = address | raw file: NC: HL = length (from the catalogue), DE = address; writes exactly `[address, address+length)` |
| `od_rsave` | HL → name, DE = address, BC = length (1..65535) | raw file: exists with room enough - overwritten in place, its length in the catalogue updated (blocks no longer needed become free); does not exist - **created** in the first gap big enough. NC: HL = first block. CY: A = `#FF` file too small, `#FD` no room, `#FC` catalogue full |

Variables: `od_unit` = drive (1/2), `od_tps`, `od_spt`, `od_spg` = geometry.

`od_load` writes exactly `[address, address+length)`. `od_save` only reads memory: for a partial
last sector the memory after the data goes to the disk, but memory itself is not changed.

**Raw files** (`OD_RAW`, on by default; writing also needs `OD_SAVE`). Everything about the file is
in its catalogue entry: first and last block, bytes in the last block. There is no 7-byte header;
the data start at the first byte of the first block. A 6912-byte screen takes exactly 27 blocks of
256 (with a header it would be 6919 bytes = 28 blocks) or 14 of 512. The ROM lists such files
(CAT) but cannot LOAD them (it would take the first bytes for a header); use these routines or
`opdtool.py` (`OPD.add_raw`). When creating, `od_rsave` inserts the entry in block order and moves
the following entries one place on, catalogue block by catalogue block through one sector buffer
(the whole catalogue is never in memory). The room in the catalogue is checked first, so on
"catalogue full" the disk is not changed.

### Low level (the Opus already paged in by the caller, DI)

| Routine | |
|---|---|
| `od_init` | sets up the PIA if needed; adopts the drive and track register the ROM left |
| `od_select` | A = drive, C = side; keeps a track register per drive |
| `od_restore`, `od_seek` (D = track) | seek with verify; on error restore and retry |
| `od_rsec`, `od_wsec` | B = track, C = sector, DE = buffer, `od_cnt16` = bytes (0 = whole sector); check that everything was transferred |
| `od_b2p` / `od_p2b` | logical block ↔ track/sector/side |
| `od_cmd` | A = command; waits for the end with a timeout; A = status. Leaves BC/DE/HL alone: they belong to the NMI handler |

## 3a. Compact drivers `src/opio256.asm` and `src/opio.asm`

For resident code that has no room for the library. Both read and write **whole sectors**, retry
until a sector reads, have no timeouts and do not use the Opus RAM. The NMI handler is copied to a
window `OP_HOLE` (≥ `#8000`, 18 bytes) for each operation; with `OPIO_SAVE` the bytes there are
saved and restored. They are included in pieces (`OPIO_CORE`, `OPIO_IO`, `OPIO_BOOT`) that may sit
in different holes of memory; each include inside a `MODULE` is an independent copy.

**`opio256`** (355 bytes with everything) - the two standard formats only, 180K and 720K: geometry
fixed (18 × 256, side 1 after track 79), positions in sectors, any sector count, 12 bytes of
variables. Not for 360K (40×2) or 512-byte formats.

**`opio`** (469 bytes with everything; reading and writing 328) - any format: geometry from the
anchor, positions in units of 256 bytes, even counts only (the universal 512-aligned layout).
Used by the Terminator 2 port ([`PORTING.md`](PORTING.md) §8.2).

| Routine | |
|---|---|
| `op_cap` | right after the ROM loaded a BASIC file: remember the drive and the WD1770 position (call first) |
| `op_geom` | (`opio` only) read the anchor (`RD_BUF` = a 512-byte buffer) |
| `op_base` | → HL = the block (unit) right after the BASIC part (`opio`: 512-aligned, `PADU` is an assembly constant) |
| `op_rd` / `op_wr` | read / write `RD_N` sectors (units) from block (unit) `RD_TS` to / from `RD_BUF` |

Tests: `tests/run_opio256test.py` (180K and 720K, across the side boundary),
`tests/run_opiotest.py`.

## 4. The monoblock (as in TR-DOS)

One BASIC file on the disk. The length in its header covers only the BASIC part; its catalogue
entry covers the BASIC part and all the code blocks that follow it. On the disk every block starts
on a sector boundary; into memory it loads **exact to the byte**: the last sector of a block is cut
to its real length (a 6912-byte screen loads exactly 6912 bytes; `#5B00` stays untouched):

```
10 REM <loader>
20 CLEAR n: RANDOMIZE USR (PEEK 23635+256*PEEK 23636+5)
```

**How the loader knows where to go on.** Checked on all five ROMs: after the ROM has loaded the
BASIC part (`RUN` or `LOAD *"m";1;"run"`), the WD1770 registers hold the track and sector of **the
last sector of the BASIC part**, and the PIA the drive and side. The loader goes on with the next
sector, as TR-DOS loaders do with `23796`. This works across a track boundary, on side 1 and after
the file was copied anywhere on a disk. The fallback `--catalog` finds the file's name in the
catalogue instead (about 250 bytes and one catalogue read more).

```bash
python tools/mkmono.py game.opd --std --dsdd-out game720.opd --block ... --start 32768   # 180K + 720K (recommended)
python tools/mkmono.py game.opd --block screen.scr@16384 --block game.bin@24576 --start 32768
python tools/mkmono.py game.opd --universal --dd-out game.dsk --block ... --start 32768   # one file for SD and DD
```

| Option | |
|---|---|
| `--block file@address` | blocks load in the given order |
| `--start A` | jump after loading (0 = back to BASIC) |
| `--sp A` | set SP before the jump |
| `--clear N` | CLEAR in line 20 (default: lowest address − 1 if above 24000) |
| `--std [--dsdd-out X.opd]` | **one file for 180K and 720K**: 18 × 256, side 1 after track 79, no anchor, no alignment; `--dsdd-out` also writes the same file onto a new 720K disk |
| `--universal [--dd-out X.dsk]` | one file for SD and DD: everything after the BASIC part 512-aligned in the file, the geometry from the anchor, PADU patched in; `--dd-out` also writes it onto a DD disk. Costs < half a sector per block on SD. Not with `--tiny` |
| `--tiny [--step 7]` | the minimal loader `monotiny.asm` (~360 bytes in all); the step must be coprime with the sectors per track |
| `--compact` | library loader, sequential reading (~660 bytes) |
| (default) | library loader, fast reading (~1020 bytes) |
| `--org A` | where the loader body runs; chosen automatically by default, `0` = stay in the REM |
| `--reserve A-B` | memory the loader must not use (repeatable) |
| `--catalog [--buf A]` | find the position through the catalogue; a one-sector buffer (default: the first block's address) |
| `--fmt sd`/`sdds`/`dd` | format of a new image (`sdds` = 720K) |
| `--name run` | file name; `run` loads with `RUN` |
| `--disk base.opd` | add to an existing image instead of a new one |

**Where the loader runs.** With the Opus RAM the NMI handler goes there, as in the library. For an
Opus without RAM a 15-byte relocating stub in the REM copies the body to free **uncontended**
memory: the highest stretch of `#8000-#FFFF` clear of every block, the stack under `CLEAR` (512
bytes), the UDGs (when returning to BASIC) and `--reserve` areas. The tool prints the address. If
there is no such room, the body stays in the REM and a warning is printed. Limits: the memory the
body occupies holds its code when the game starts (use `--reserve` if the game cares); `--tiny` has
no timeouts and uses only the drive and side the ROM left.

## 4a. The launcher `run`

`src/shell.asm` + `tools/mkshell.py`. The file `run` is BASIC:

```
10 IF NOT USR VAL "PEEK 23627+256*PEEK 23628" THEN STOP
20 LOAD *"m";VAL "1";"??????????"
```

Its variables hold an 18-byte stub and the code (2.2K, moved to `#C000`), which
* takes the drive `run` came from (PIA) and the geometry from the anchor - any format;
* reads the catalogue and keeps the BASIC files (type 0 in the 7-byte header) except `run`;
* none: prints NO PROGRAMS, `USR` = 0 → `STOP`; one: takes it at once; more: a menu, keys 1..9,
  A..Z, SPACE back to BASIC;
* writes the name into the string of line 20 and the drive into `VAL "1"` and returns 1: the Opus
  ROM then loads and runs the program as usual.

The text goes straight to the screen in the ROM font (`RST 16` after a `CLS` gave "Out of screen"
at that point).

```bash
python tools/mkshell.py                          # build/run.opus: the file's bytes (with header) for your own builds
python tools/mkshell.py --add disk.opd game.dsk  # add run to existing images
```

## 5. Tools

```bash
python tools/opdtool.py new  disk.opd [--fmt sd|sdds|dd] [--label NAME]
python tools/opdtool.py todsk disk.opd disk.dsk    # and back: fromdsk
python tools/opdtool.py cat  disk.opd
python tools/opdtool.py add  disk.opd name file.bin --code 32768
python tools/opdtool.py addbas disk.opd run loader.bas --line 10
python tools/opdtool.py get  disk.opd name out.bin
python tools/opdtool.py map  disk.opd 1440        # block -> (track, side, sector)
```

Every command takes a `.dsk` instead of an `.opd`; the geometry comes from the anchor. DSK → raw →
DSK of a real 80×2×10×512 FuseX image round-trips byte for byte, track headers and sector order
included.

## 6. Tests (ZX-M8XXX, headless)

```bash
python tests/run_libtest.py      # library: 16 checks x 5 ROMs x OD_FAST 0/1 x Opus RAM yes/no, SD and DD
python tests/run_rawtest.py      # raw files: od_rload / od_rsave, creation in a gap, catalogue shifting
python tests/run_opio256test.py  # opio256 on 180K and 720K
python tests/run_opiotest.py     # opio: op_cap/op_geom/op_base, reads across sides, writes, the NMI window
python tests/run_monotest.py     # monoblocks: all loader variants x layouts x 5 ROMs (guard bytes)
python tests/run_shell.py        # the launcher: menu, choice, a single program
python tests/run_demo.py         # the example end to end
python tests/run_seadragon.py    # Sea Dragon (the game's repository)
python tests/run_t2.py           # Terminator 2: every read compared with the file; 48K and 128K
python tests/run_t2hs.py         # Terminator 2: high scores written and read back
sh tests/run_t2levels.sh         # Terminator 2: every stage on 48K with the DUPE cheat
```

`tools/zxharness.py` starts its own multithreaded static server on port 8765 and a headless browser
with its own profile.

## 7. What is verified and what is not

**Results** (all five ROMs unless said otherwise; only EXCOM + 180K with files past track 0 fails,
see below):
* library: 660 checks (with and without the Opus RAM, both reading modes, SD and DD): exactness
  (guard bytes right after and before every block stay untouched; a negative test proves the check
  catches a stray write), reads and writes across track and side boundaries, two drives, unaligned
  buffers, `od_geom`, load / save by name, no disk (an error, no hang);
* raw files: 400 checks (creation in a gap, catalogue shifted across a block boundary, shorter
  rewrite, no room, catalogue full);
* drivers: `opio` on 180K and 800K with PADU 0 and 1, `opio256` on 180K and 720K across the side
  boundary;
* monoblocks: 384 of 400 cases, plus `--std` (46 of 50) and `--universal` variants;
* the launcher: menu, choice, a single program at once;
* games: Sea Dragon and Terminator 2 on 180K, 720K and 800K, 48K and 128K: every read compared byte
  by byte with the file, every stage of T2 (with the DUPE cheat), high scores written and read back.

**Not verified on real hardware:** speed (the emulator does not rotate the disk, so the gain of the
rotational order is computed, not measured), timeout lengths, motor spin-up, step rates of real
drives. Formatting is not implemented (the emulator has no Write Track).

**EXCOM 2.28 and 40-track disks.** EXCOM's default table for drive 1 is 80 tracks × 2 sides × 18 ×
256 (`50 12 51 ...`, with a stray 15th byte `02`), and it reads a 40-track disk with **double
stepping** (logical track t = physical 2t; after a load the track register holds 2t). Neither
ZX-M8XXX nor FUSE models double stepping: in both, EXCOM itself loads nothing past track 0 of a 180K
disk (the catalogue reads; the BASIC part of a file gives "Disc I/O error" before any loader runs).
720K and 800K work. On real hardware with a 40-track drive set EXCOM to 40 tracks. An 80-track drive
with a 180K disk under EXCOM is not supported by these routines yet (position from the track
register, single stepping) and cannot be tested anywhere.

**ZX-M8XXX quirks** (v26.11.02) found on the way:
0. It does not take DD images (80×2×10×512) itself: `zxharness.insert()` hands it the geometry from
   the anchor, and its WD1770 engine copes.
1. One geometry (sides / tracks) per controller, from the last image inserted: an SS disk in drive 1
   next to a DS disk in drive 2 reads wrongly.
2. ROMs v2.2, v2.22, EXCOM, QuickDOS: `RUN` without a program and `CAT 1` give "C Nonsense in BASIC"
   or loop, while `LOAD *"m";1;"name"` works; v1.2 works fully. The failure is in parsing the
   statement the ROM builds on the machine stack (CHKEND at `#050E` finds CH_ADD not at the end of
   the statement).
3. Read Address returns the sector register and size 2 (512) instead of the next ID on the disk.
4. The DRQ NMI is scheduled with a delay and not re-checked when it fires.
5. The track register is treated as the head position (seek sets it, sectors are taken by it), so
   double stepping and software that writes the track register cannot work.

Another observation: on `LOAD` of a BASIC file the ROM uses the workspace right after the program
(with a 512-byte buffer on DD). This happens before any loader runs, so it is harmless for the
blocks, but memory right after the BASIC part is not preserved.
