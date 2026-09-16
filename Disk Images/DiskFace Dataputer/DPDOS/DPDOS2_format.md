# DPDOS 2 disk format (ZX DISKFACE PLUS / Dataputer)

Reverse-engineered from two 720K images. Controller FDC: **Intel 8272A** (µPD765-класс,
MFM), 250 kbit/s. Verified end-to-end: extraction + .tap reconstruction, all checksums OK.

## Physical geometry (720K variant)
| param        | value                                   |
|--------------|-----------------------------------------|
| tracks       | 80                                      |
| sides        | 2                                       |
| sectors/track| 9                                       |
| sector size  | 512 bytes                               |
| total        | 80×2×9×512 = 737 280 bytes              |
| image layout | linear dump; **allocation unit = 1 sector (512 B)**, unit N @ byte N×512 |

(Also exists in 180K SS/40 and 360K DS/40 per the manual; same logical scheme, fewer units.)

## Reserved area
- unit 0 (0x000–0x1FF): boot sector (contains `DP-DOS non system disc` on non-system disks)
- units 1–12 (0x200–0x19FF): directory area (~255 entries max)
- unit 13+ : file data

## Disk label
- offset **0x200**: 8 ASCII chars, space-padded (e.g. `GAMES_R `), +1 byte.

## Directory entry — 24 bytes, starting at **0x209**, until name[0]==0x00
| off | size | field | meaning |
|-----|------|-------|---------|
| 0   | 10   | name        | ASCII, space-padded. UPPER = BASIC loader, lower = CODE block |
| 10  | 2    | length      | u16 LE — exact file length in bytes |
| 12  | 2    | param1      | BASIC: autostart line · CODE: load address |
| 14  | 2    | param2      | BASIC: program length (vars start) · CODE: usually 32768 |
| 16  | 2    | start unit  | u16 LE — data at start×512 |
| 18  | 2    | end unit    | u16 LE, inclusive — sectors = end−start+1 |
| 20  | 2    | end−start   | u16 LE (sectors−1) |
| 22  | 1    | file type   | 0x00 = Program (BASIC), 0x03 = Code |
| 23  | 1    | group flag  | 0x03 = more blocks follow · 0x00 = last block of this game |

Fields 10–14 are the original ZX-Spectrum **tape header** params → a .tap can be rebuilt
directly from the catalog (that's what `dpdos.py tap` does).

Allocation observed to be strictly **contiguous & packed**: each file's start = previous
file's end + 1. That makes write-back feasible (append at the first free unit, add a
24-byte catalog entry), though the current tool does read-only extraction.

## Games are groups
`<BASIC loader> + <CODE blocks…>`, the last block carries group flag 0x00. Handy for a
menu/loader that needs to know how many blocks a game spans.

## Confirmed from the DP-DOS 4.05 ROM (DPDQ405)
- 64K ROM = 4×16K banks; banks 0/2 = standard Spectrum ROM, **bank 3 (file 0xC000–0xFFFF,
  paged to 0x0000) = the disk system** (DPDOS + CP/M + MDOS). FDC data/status port = **0xC7**;
  low-level FDC command executor at runtime 0x3891 (READ builds cmd 0xE6=MT|MFM|SK, WRITE 0xC5).
- Format menu strings confirm the four geometries: `1=40 SS 180K · 2=40 DS 360K ·
  3=80 SS 360K · 4=80 DS 720K` (our images = format 4).
- **System vs non-system disc is a boot-sector (unit 0) property**, not a catalog flag: FORMAT
  writes the `"...DP-DOS non sytem disc"` template into unit 0. A *system* disc additionally
  carries the DOS so it can autoboot.
- Note: ROM 4.05 spells the boot text `sytem` (typo); our images say `system` → they were
  formatted by an earlier DPDOS version. Harmless.
- No free-list/superblock with a file count: DPDOS derives file count and free space by
  scanning the catalog. => **safe write-back = append a 24-byte entry + write data at the
  first free unit** (implemented as `dpdos.py add`, with a re-parse self-check).

## Not yet done (needs real-hardware confirmation)
- Physical sector interleave/skew is irrelevant at image level (verified linear), but would
  matter if writing to a *physical* floppy via the FDC.
- MDOS-format disks (the other Czech controller) use a different catalog — not decoded here.
