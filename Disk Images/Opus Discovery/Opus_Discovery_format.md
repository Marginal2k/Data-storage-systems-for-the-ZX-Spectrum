# Opus Discovery disk format

Opus Discovery (Opus Supplies, 1985): WD1770 + MC6821 PIA, memory-mapped, ROM paged in at
`#0008`/`#0048`/`#1708`. ROMs: v1.2, v2.2, v2.22, EXCOM 2.28 (Paul Cheffing), QuickDOS 2.31.
Verified against all five ROMs and real images.

Machine-code routines, tools, tests and a porting guide are in [`machine_code/`](machine_code/README.md)
(Russian: [`README.ru.md`](machine_code/README.ru.md)).

## Geometry
Not fixed: the ROM reads the **anchor sector** (track 0, side 0, sector 0) on every access.
Byte 2 = tracks per side, byte 3 = sectors per track, byte 4 = flags
(bits 7-6 sector size: 01 = 256, 10 = 512, 11 = 1024; bit 5 FM; bit 4 two sides).

| | tracks × sides × sectors × bytes | flags | size | in this folder |
|---|---|---|---|---|
| SSSD (the standard) | 40 × 1 × 18 × 256 | `#40` | 180K | `Blank/opus_discovery_sssd.opd` |
| DSDD | 80 × 2 × 18 × 256 | `#50` | 720K | `Blank/opus_discovery_dsdd.opd` |
| "DD" (special formatter) | 80 × 2 × 10 × 512 | `#90` | 800K | — (non-standard, Gotek does not take it) |

All MFM, 250 kbit/s, sector IDs from 0. Every Opus reads 180K; formats other than the standard
need the 2K RAM on the board (the ROM keeps its drive tables there). `Blank/diskdefs.cfg` holds
Greaseweazle definitions of SSSD and DSDD.

## Logical blocks
A block is one sector. Block B (ROM routine `#11DA`):
`real = B + 1; sector = real mod SPT; t = real div SPT; track = t mod TPS; side = t div TPS`.
Block −1 is the anchor. **Side 0 is filled completely first, then side 1** (unlike TR-DOS, where
logical tracks alternate between the sides).

Physical sector order written by the ROM formatter: step +7 (18 × 256: 0, 7, 14, 3, 10, 17, ...;
each next track starts one sector later). The "interleave = 13" of the Greaseweazle definitions
is the same order seen from the other side (13 × 7 ≡ 1 mod 18).

## Catalogue
Blocks 0..N, N = "last block" of entry 0 (usually 0-6). 16-byte entries:

    DW bytes in the last block - 1
    DW first block
    DW last block
    DS 10 name (space padded)

Entry 0 is the disk label. Files are contiguous and sorted by first block. End marker: first
block = number of blocks on the disk, last block = `#FFFF`.

## Files
A file starts with a 7-byte header: `type, length, param1, param2`
(type 0 BASIC: param1 = autostart line, param2 = program length; type 3 CODE: param1 = address).
The header length of a BASIC file may be shorter than the file's catalogue entry: a **monoblock**
(one BASIC file whose catalogue entry also covers the code blocks after it) is loaded by the ROM up
to the end of the BASIC part only; its loader continues from the WD1770 registers, which still
point at the last sector the ROM read. "Raw" files (no header, everything in the catalogue) are
listed by the ROM but cannot be LOADed by it.

## Image files
* `.opd` — raw sectors. Double-sided: tracks alternate between the sides (cylinder 0 side 0,
  cylinder 0 side 1, ...), the same as a Gotek / Greaseweazle `.img`. 180K = 184320 bytes,
  720K = 737280 bytes.
* `.dsk` (CPCEMU) — used for the 512-byte-sector "DD" format.

## Samples
* `Samples/*.opd` — original disks (Astrum, HiSoft Pascal 4, Masterfile, the Discovery Club
  newsletters, games).
* `Samples/monoblock_loader/` — Sea Dragon and Terminator 2 as monoblocks (made with the
  routines in `machine_code/`).
