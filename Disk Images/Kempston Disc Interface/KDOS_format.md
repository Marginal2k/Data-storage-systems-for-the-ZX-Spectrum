# Kempston K-DOS disk format (Kempston Disc Interface / Sandy "Disco Vers.3")

Reverse-engineered from four images + KEMPSTON DOS V2.1 ROM (KD21) and the Sandy
manual. FDC: **WD1770**. DOS: **KEMPSTON DOS V2.1 (C) Abbeydale Designers 1985**.
Verified end-to-end: extraction, .tap rebuild, and write-back (with bitmap update).

## Container
All four images are **Extended CPC DSK** (`.dsk`/`.kdi`, SAMdisk/HxC). The real KDOS
sectors are unwrapped from the DSK track/sector blocks first.

## Geometry
80 cyl x 2 sides x 10 sectors x 512 B = **800 KB**. Sector IDs 0..9 (0-based).
Logical **block = 1024 B = 2 sectors**. Ordering: sectors by id, tracks cylinder-major
(C0H0, C0H1, C1H0, ...). Block N lives at linear offset N x 1024.

## Directory  (fixed at block 200, reserved 5 blocks 200..204 = 5 KB)
- **Sector 0 (0x32000):**
  - `0x32003` : disk label, 10 ASCII bytes (set by FORMAT; e.g. "KDOS TOOLS").
  - `0x32060` : **free-block bitmap**, 100 bytes = 800 bits, LSB first, **1 = used**.
    (Verified bit-exact against catalog usage on all four disks.)
- **0x32200 .. 0x33400:** 144 file entries x 32 bytes. Unused slots filled with 0xA5.

## Entry (32 bytes)
| off | field | notes |
|-----|-------|-------|
| 2   | type  | 0=BASIC, 1=num array, 2=char array, 3=bytes (CODE/SCREEN$) |
| 3:13| name  | 10 bytes, space padded |
| 13:15| length | u16 LE, bytes |
| 15:17| param1 | BASIC autostart line / CODE load address |
| 17:19| param2 | BASIC vars-start / CODE 0 |
| 22  | nblk  | block count (= ceil(length/1024)) |
| 23:25| start block | u16 LE. **File data is contiguous** from here. |

Fields 13..19 are the ZX-Spectrum tape header, so .tap can be rebuilt from the catalog.

## Free space & write-back
KDOS tracks free space with the **bitmap at 0x32060** (CAT's "FREE SPACE" counts its
zero bits). Adding a file therefore means: find a contiguous run of free blocks, write
the data, add a 32-byte entry in the first 0xA5 slot, **and set the bitmap bits**.
`kdos.py add` does all of this and self-checks (readback + bitmap==catalog).

## Notes / to verify on hardware
- Header bytes at 0x32010-0x32020 (e.g. `... 50 09 01`, `20 03`=800=total blocks) look
  like fixed disk parameters; a possible free-*count* counter was not identified, so on
  the first hardware write confirm CAT shows the right free figure.
- Extended-DSK sector interleave is irrelevant at image level (SAMdisk already stores
  sectors in id order); it would only matter writing to a physical floppy via the WD1770.
