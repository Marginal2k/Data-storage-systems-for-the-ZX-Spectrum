# Porting a game or program to the Opus Discovery

A guide for moving a game (usually a tape or TR-DOS version) onto Opus Discovery disks.
Everything here was proven on two ports, Sea Dragon and Terminator 2 (walkthroughs in §8).
The reference for routines, the disk format and the tools is [`README.md`](README.md); this file
is the order of work and the rules whose violation breaks a port.
Русская версия: [`PORTING.ru.md`](PORTING.ru.md).

## 0. Which way to go

| Situation | Use |
|---|---|
| 48K, a few blocks loaded once to their addresses, then `JP` | `tools/mkmono.py --std` (180K + 720K): a ready monoblock; the loader finds free uncontended memory itself (§3) |
| Your own loading logic: 128K banks, depacking, a progress bar, 48/128 choice, levels loaded during the game | your own loader on `src/opuslib.asm` (like Sea Dragon, §8.1) |
| Almost no memory (a resident level loader of a few hundred bytes) | the compact driver `src/opio256.asm` (180K/720K) or `src/opio.asm` (any format, like Terminator 2, §8.2) |
| Saved games, high scores, pictures without a header | raw files: `od_rload` / `od_rsave` (README §3) |
| Several programs on one disk | the launcher `run`: `tools/mkshell.py` (README §4a) |

**Release formats: 180K and 720K only.** The Opus standard is 180K (40×1×18×256): every
machine reads it (also one without the 2K RAM) and so does a Gotek. The other sensible format
is 720K (80×2×18×256). Formats with 512-byte sectors (80×2×10×512, 800K) are outside the spec,
and a Gotek does not take them. For 180K + 720K build **one file** with a fixed geometry
(§2.3a): `mkmono --std`, `opio256`. The universal SD/DD layout (§2.3) is only needed when
512-byte sectors must be supported too (Sea Dragon and Terminator 2 were done that way).

## 1. What you need

* Python 3 and `sjasmplus` (path in `SJASMPLUS`, default `C:\sjasmplus\sjasmplus.exe`).
* For the tests: the ZX-M8XXX emulator (`ZXM8XXX` = its folder with `index.html` and `roms/`
  holding the five Opus ROMs listed in `tests/run_libtest.py: ROMS`) and a Chromium browser
  (`EDGE`). `tools/zxharness.py` starts everything itself, headless.
* Images: 180K (40×1×18×256) = `.opd` of 184320 bytes; 720K (80×2×18×256) = `.opd` of 737280
  bytes (tracks alternate between the sides, like a Gotek `.img`). 800K (80×2×10×512) only for
  the older universal builds, and only as `.dsk`.

## 2. Rules (each of them has already bitten someone)

### 2.1 The position of the data comes from the WD1770, before anything else
After the Opus ROM has loaded the BASIC part of a file, the WD1770 track and sector registers
still point at its last sector, and the PIA at the drive and side. This holds in all five ROMs
(v1.2, v2.2, v2.22, EXCOM 2.28, QuickDOS 2.31). The data of a monoblock start with the next
sector. **Read those registers first**, before any disk access (reading the anchor included):
a seek overwrites the track register. No track or sector numbers belong in the code. The
fallback is to find your own file in the catalogue by name (`od_find`, `mkmono --catalog`).

### 2.2 The geometry comes from the anchor (when 512-byte sectors are supported)
The anchor is track 0, sector 0. Bytes 2, 3, 4: tracks per side, sectors per track, flags
(bits 7-6: 01 = 256 bytes, 10 = 512; bit 4 = two sides). `od_geom` / `op_geom` read it. Do not
hard-code the geometry if you support 512-byte sectors: the disk may be another format. For
180K + 720K the geometry is known in advance (§2.3a).

### 2.3 Universal layout: everything after the BASIC part 512-aligned within the file
* The BASIC part (7-byte header + program) is padded to a 512-byte boundary **of the file**;
  each data block starts on a 512-byte boundary and is padded to the next one.
* Block offsets count 512-byte units of the file: 2 sectors on SD, 1 on DD.
* The base (first data block) is the block after the last sector of the BASIC part, on SD plus
  PADU: `PADU = 2*ceil(L/512) - ceil(L/256)` (L = length of the BASIC part with its header; 0 or
  1). The build computes PADU and patches it into the loader (the code length does not depend
  on it, so a second pass is enough). On DD it is always 0.
* Result: one file works on SD and DD, also after a file copy; the cost is half a sector per
  block on average (2K out of 133K for Terminator 2).

### 2.3a 180K and 720K only: no geometry needed
Both formats have 18 sectors of 256 bytes. Unlike TR-DOS, the Opus fills the whole of side 0
first, then side 1 (TR-DOS alternates logical tracks between the sides, which is why the disk
size does not matter to a TR-DOS loader). The only difference is after which track side 1
starts: after track 79 on 720K; on 180K a file never gets that far. So "18 × 256, side 1 after
track 79" is right for both: no anchor, the data follow the BASIC part directly, base = the
sector after the last one the ROM read, then straight on. Not valid for the non-standard 360K
(40×2), where side 1 starts after track 39.

### 2.4 Exact loading: not one byte past the end of a block
Neither for good nor for a moment. Do not read whole sectors straight to the destination if
something that matters lies after the block (system variables, the stack, code, another block).
* `od_read` with `od_tail` cuts the last sector; `od_load` / `od_rload` / `mkmono` do it
  themselves.
* If you read whole sectors (`opio`), read into a free staging area and depack / copy from
  there. The build must prove that the staging area, padding included, touches nothing (as in
  T2: `t48.layout`, `legal_stage`).
* The test must put guard bytes right after and before every block and check them
  (`tests/run_monotest.py`; `tests/neg_guard.py` is a negative test of the check itself).

### 2.5 The NMI handler lives in uncontended memory
The FDC's DRQ is wired to the NMI: a byte arrives every 32 µs = 112 T-states. A handler in
`#4000-#7FFF` (on 128K: in banks 1, 3, 5, 7) is stretched by the ULA and bytes are lost. An
emulator does not show it; real hardware does.
* `mkmono` moves the loader body to `#8000+` itself.
* `opuslib` keeps its handlers inside itself: put the library at `#8000+`, or it uses the Opus
  RAM when the unit has it.
* `opio` / `opio256` copy the handler to `OP_HOLE` (≥ `#8000`, 18 bytes) for each operation;
  with `OPIO_SAVE` the bytes there are saved and restored.
* The stack and the destination may be in contended memory (a few T-states, not tens).

### 2.6 Do not rely on the Opus RAM
Not every unit has the 2K RAM. The library uses it when present and works without it. A port
must work without it (all tests run both ways).

### 2.7 Interrupts and the ROM
* `DI` during disk operations (the routines return with `DI`; enable them yourself).
* From the Opus ROM only `CALL #1708` (page in), `CALL/JP #1748` (page out, a `RET` there) and
  the NMI vector `#0066` = `JP (HL)` are used. Call nothing else: the versions differ.
* 128K: at `#1708` the 48 BASIC ROM must be paged (`#7FFD` bit 4 = 1). Any bank may be at
  `#C000` (the pages are loaded with `#17` = 48 ROM + bank 7).
* While the Opus is paged in, `#0000-#3FFF` belongs to it: code, buffers and stack above `#4000`.

### 2.8 The BASIC part and starting
* The file is a BASIC program with autostart. The loader code fits nicely in the variables
  area: `10 RANDOMIZE USR VAL "PEEK 23627+256*PEEK 23628"` (PEEK inside the string is the token
  `#BE`). A stub at the start of the variables copies the loader where it will run.
* On `LOAD` the ROM uses the workspace right after the program: memory just after the BASIC
  part is not preserved until the loader runs.
* Name the file after the game (`T2`, …). Start it through the launcher `run` (a single program
  on the disk starts at once). On v1.2 `RUN` loads `run`; `LOAD *"m";1;"run"` works everywhere.
* 128 BASIC types lower case: a file name with capitals needs CAPS SHIFT there (or use lower
  case names).

### 2.9 Writing (high scores, saved games)
* Writes are whole sectors too. A write-protected disk: the WD1770 refuses, the game goes on
  (do not turn this into an error).
* Reserve the space in your own file (the last 512 bytes of the monoblock, as in T2) or use a
  raw file (`od_rsave` creates it). Keep a checksum: an unsaved sector is all zeros and must be
  told from a table.
* Write only when the data changed (compare the checksum).

## 3. The simple case: `mkmono.py`

```bash
python tools/mkmono.py game.opd --std --dsdd-out game720.opd \
    --block screen.scr@16384 --block game.bin@24576 --start 32768 --name GAME
python tools/mkshell.py --add game.opd game720.opd        # the launcher run
```

* Blocks load in order, exact to the byte. `--start` = jump address, `--sp` = stack, `--clear` =
  CLEAR in the BASIC line, `--reserve A-B` = memory the loader must not use (the game's stack,
  its variables if they are already in memory).
* The loader body (~1.2K) is placed in free uncontended memory clear of every block. If the game
  takes everything above `#8000`, `mkmono` warns: then you need your own loader.
* `--catalog` = find itself in the catalogue by name instead of the WD1770 registers.
* `mkmono` does not do 128K banks or depacking: that needs your own loader (§4).

## 4. Your own loader: order of work

1. **Take the original apart.** Its tape loader: which blocks, where to, in what order, what is
   depacked, where the stack is, what happens on 48K and on 128K, which memory is free at each
   moment. Write down the memory map: who lives where at each step of loading and in the game.
2. **Decide where the loader and the NMI handler live** at each moment (§2.5). Usually the loader
   runs from an area the game overwrites last.
3. **Disk layout.** The build (Python) lays out the BASIC part and the blocks and hands the
   offsets to the assembler (a generated include, or constants in a shared layout file like
   `DiskLayoutOpus.asm`). For 180K + 720K: blocks one after another from sector boundaries,
   offsets in sectors (§2.3a); if 512-byte sectors are needed too, by §2.3 (512-byte units, PADU).
4. **Loader:** take the WD1770 position → (512-byte sectors only: read the anchor) → compute the
   base → read the blocks at their offsets (`od_read` with `od_tail`, or `op_rd` into a staging
   area) → depack / copy → start the game.
5. **Loading during the game** (levels on 48K): a resident driver (`opio256` or `opio`) in memory
   the game leaves free, a block table `offset, count, destination` in the resident part, the base
   in a variable the loader fills in.
6. **Do not break the other versions.** Everything disk-related behind `IFDEF OPUS` or in separate
   files; after the changes the tape and other disk builds must be byte-identical to the old ones
   (check the `md5`).
7. **Tests** (§5) on all five ROMs, 180K and 720K (or SD and DD), 48K and 128K.

## 5. Testing

Examples: `tests/run_seadragon.py` and `tests/run_t2.py`. A port's test should:
* boot the image in ZX-M8XXX (`ZX(rom=..., machine='48k'|'128k')`, `zx.insert`, `zx.basic(...)`;
  on 128K `zx128.enter_128basic`, `zx128.command_128`);
* catch the start of the game (`zxDebug.onAccess({onFetch})` on its entry) and compare memory
  with the built blocks (`peekBlock`, on 128K `peekBank`);
* for loading during the game, compare what was read with the file's bytes at every call of the
  depacker (`run_t2.py: hook/check`);
* check guard bytes around the blocks;
* high scores: change the table, run the write path, check the sector in the image (`zx.disk()`),
  boot again and check the table was read back (`run_t2hs.py`);
* all levels: test builds "start at level N" plus the game's cheat if it has one
  (`run_t2levels.sh`).

## 6. Emulator quirks (not to be taken for bugs of the port)

ZX-M8XXX:
* It does not take DD images itself: `zxharness.insert()` hands it the geometry from the anchor.
* One geometry per controller: an SS disk in one drive and a DS disk in the other read wrongly.
* ROMs v2.2+: `RUN` without a program and `CAT` fail; use `LOAD *"m";1;"name"`.
* 128K: choosing "128 BASIC" with a 40-track disk inserted drops back to the menu. Workaround: the
  emulated drive gets 80 tracks (the disk and its anchor stay as they are) - `run_t2.py`. The menu
  sometimes comes back later too: `zx128.command_128` checks the screen before ENTER.
* Inserting a DSK resets a 128K machine. "48 BASIC" from the 128K menu locks the paging port (the
  game rightly sees a 48K machine).
* The disk does not rotate: the gain from reading in rotational order is not visible.

ZX-M8XXX and FUSE: **EXCOM 2.28** is set up for an 80-track double-sided drive by default and
reads a 40-track disk with **double stepping** (after a load the track register holds twice the
track number). Neither emulator models double stepping: in both, EXCOM itself loads nothing past
track 0 of a 180K disk (the catalogue reads, the BASIC part of a file gives "Disc I/O error" before
any loader runs). Not a bug of the port. On real hardware with a 40-track drive set EXCOM to 40
tracks; an 80-track drive with a 180K disk is not supported by these routines yet (position from
the track register, single stepping) and cannot be tested anywhere.

## 7. Release checklist

- [ ] 180K (`.opd`, 184320 bytes) and 720K (`.opd`, 737280 bytes) images with the same file
      (or, if 512-byte sectors are needed, one file for SD and DD).
- [ ] Position from the WD1770 (or the catalogue); geometry fixed for 180K + 720K or taken from
      the anchor; no track numbers in the code.
- [ ] Not one byte outside the blocks (guard bytes in the test).
- [ ] NMI handler at `#8000+` (or in the Opus RAM); the Opus RAM is not required.
- [ ] Tested on all five ROMs × 180K/720K (or SD/DD) × 48K/128K; only EXCOM + 180K is expected
      to fail (§6).
- [ ] Every level / every block loaded during the game checked; writing (if any) checked and read
      back.
- [ ] The other builds of the game (tape, TR-DOS) are byte-identical to before.
- [ ] The image holds `run`; the game's file carries the game's name.
- [ ] What was not checked on real hardware is listed in the release notes.

## 8. Walkthroughs of finished ports

Both ports were made before the "180K and 720K only" rule, so they use the universal SD/DD layout
(§2.3): one file for 180K, 720K and 800K (checked on all three). Make new ports simpler with
`mkmono --std` / `opio256` (§2.3a): the loaders work the same, only the anchor, PADU and the
512-byte alignment go away.

### 8.1 Sea Dragon (repository `seadragon`): own loader on `opuslib`
* `src/loader/Loader.asm` (`LOADER_OPUS`): WD1770 position → anchor (`od_rsec`, 5 bytes) → base
  with `OpusPadu` → `LoadFile` in 4K chunks through `od_read` with `od_tail` (progress bar).
  The 128K pages are loaded to `#7000` and depacked to `#C000` of their bank.
* `src/loader/DiskLayoutOpus.asm`: offsets in 512-byte units; `platform/opus/boot.bas`,
  `disk.txt`: the BASIC part and the layout; `build.py: opus_file()`: the file, PADU, the same
  file on the SD and DD images.
* Test: `tests/run_seadragon.py` (`SEADRAGON=<path to the repository>`).

### 8.2 Terminator 2 (repository `T2`): levels loaded on 48K, everything at once on 128K
* `src/disk_opus.asm`: the head of the file `T2`: `op_cap` → detection → `op_geom` → `op_base` →
  intro → 48K: reads the kernel and starts it; 128K: reads all 13 blocks in one pass (the loader
  in `#5B00..` and `#6C00..`, which the 128K image does not touch - the build checks that).
* `src/kern48_body.asm` (`IFDEF OPUS`): the `opio` driver in `#5C00..#5D3A` (on the Opus there
  are neither DOS variables nor an IM 1 handler there), the NMI handler in unused bytes of the
  level descriptor at `#BF8E`, the block table `blk_tab` in 256-byte units from the base.
* `src/res128_opus.asm`: the resident high-score write on 128K: the loader computes the sector
  positions in advance, so the resident part needs no geometry.
* `tools/build_opus.py`: 512 layout, staging areas, the check that the 128K image leaves the
  loader alone, PADU, images. Tests: `tests/run_t2.py`, `run_t2hs.py`, `run_t2levels.sh`
  (`T2_DIR=<path to the repository>`).
