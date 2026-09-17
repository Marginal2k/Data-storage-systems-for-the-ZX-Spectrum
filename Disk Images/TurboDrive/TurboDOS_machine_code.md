# TurboDrive / TurboDOS — machine-code interface
*(the chapter missing from the English manual, reconstructed from the original Serbo-
Croatian articles and **verified against ROM TurboDr_77D5877D**). FDC WD1770.*

## Call mechanism
Every DOS service is invoked with **`RST 8`** followed by a one-byte **function code**:

    RST 8            ; CF
    DEFB code        ; e.g. 21h

`RST 8` (ROM 0008h) takes the return address (which points at the code byte), and the
dispatcher (0x00AA → 0x02BD) reads it: code `< 1Bh` prints a standard error; codes
`1Bh–32h` index a jump table at ROM **0x02E5** (24 entries); `33h–FEh` = "Hook code
error"; `FFh` = "Program finished". Turbo-ROM is paged in automatically because 0008h is
the Spectrum error-restart vector.

## Function codes (verified: code → ROM routine in this dump)
| code | name | routine | notes |
|------|------|---------|-------|
| 1Bh | CONSOLE INPUT   | 0ADA | wait for a key, code→A (needs EI) |
| 1Ch | CONSOLE OUTPUT  | 0AED | print A on channel 2 (screen) |
| 1Dh | JOYSTICK INPUT  | *RET*| **stub in this ROM** (read port 31 yourself) |
| 1Eh | CENTRONICS OUT  | *RET*| **stub in this ROM** |
| 1Fh | ZX PRINTER OUT  | 0AFD | print A to the parallel port |
| 20h | KEYBOARD TEST   | 0B02 | key pressed? → returns Carry set |
| 21h | SELECT DRIVE    | 0978 | A = drive 1-4; A=0 stops motors; "Drive not ready" if absent |
| 22h | OPEN FILE       | 0D38 | opens a channel, **IX = channel base**; file from sysvars D_STR1/N_STR1 |
| 23h | CLOSE FILE      | 0FEA | close channel at IX (flushes last block if writing) |
| 24h | DELETE FILE     | 1040 | delete file named by D_STR1/N_STR1 |
| 25h | READ SEQUENTIAL | 0B0A | read next block of file at IX (bumps CHREC) |
| 26h | WRITE RECORD    | 10D2 | write channel-IX data block to first free sector |
| 27h | READ RANDOM     | 0B18 | read the block whose number is in CHREC |
| 28h | READ SECTOR     | *RET*| **stub in this ROM** — use 2Eh instead |
| 2Ah | WRITE SECTOR    | *RET*| **stub in this ROM** — use 2Dh instead |
| 2Bh | CREATE BUFFER   | 0D38 | build a channel + its folder map in RAM |
| 2Ch | DELETE BUFFER   | 0BFC | free the channel at IX and its map |
| 2Dh | WRITE SECTOR 2  | 0A5D | **BC = track/sector**, writes 512 B from `(TRANSFER)` |
| 2Eh | READ SECTOR 2   | 0A1E | **BC = track/sector**, reads 512 B to `(TRANSFER)` |
| 31h | CREATE SYSVARS  | *RET*| no-op (just guarantees turbo-ROM is paged in) |
| 32h | ENTER TURBO-ROM | 02E0 | page turbo-ROM in and `JP (HD_11)` (sysvar 23789) |

(Codes 29h/2Fh/30h are also RET stubs here.) So on this revision the usable low-level
sector primitives are **2Eh / 2Dh**, driven by the `TRANSFER` system variable — exactly
what the manual's example uses.

## Key system variables (TurboDOS adds 58, base 5CB6h)
| addr | name | meaning |
|------|------|---------|
| 23747 / 5CC3 | TRACK0 | current track, drive 1 |
| 23748 / 5CC4 | TRACK1 | current track, drive 2 |
| 23749 / 5CC5 | LASTDR | last drive used |
| 23750 / 5CC6 | DRIVEON| a drive is spinning |
| **23751 / 5CC7** | **TRANSFER** | memory address for READ/WRITE SECTOR 2 (updated to end+1 after) |
| 23789 / 5CED | HD_11 | auto-start line / entry used by ENTER TURBO-ROM |
Channel fields (from OPEN, IX-relative): +11 CHBYTE(0-511), +13 CHREC(sector no),
+14..23 CHNAME(10), +24 CHFLAG(bit0=open-for-write), +25 CHDRIV, +26 map addr, +41 file#.

## I/O ports (WD1770 + control latch)
| what | port | dir |
|------|------|-----|
| Status / Command | 127 = 007Fh | IN/OUT |
| Track register   | 16511 = 407Fh | IN/OUT |
| Sector register  | 32895 = 807Fh | IN/OUT |
| Data register    | 49279 = C07Fh | IN/OUT |
| Drive/side latch (OUT 63=3Fh): D0=DriveSel1 D1=DriveSel2 D3=SideSel D2=printer STROBE |
| Joystick IN 31 (D0-D4); printer BUSY IN 31 D5; printer data OUT 95 |

Data transfer is **NMI-driven**: DRQ from the 1770 is wired to /NMI, and the handler at
ROM **0066h** does one `OUTI`/`INI` to/from the data port (B=C0h) per byte — that is why
sector transfers need no polling loop in your code when you use 2Dh/2Eh.

## Example — read/write one sector (verified against the manual & ROM)
    TRANSFER equ 23751
    BUF      equ 50000
    ; --- read track 0, sector 1 into BUF ---
             ld   a,1            ; drive 1
             rst  8 : defb 21h   ; SELECT DRIVE (start motor)
             ld   hl,BUF
             ld   (TRANSFER),hl  ; where the 512 bytes go
             ld   bc,0001h       ; B=track 0, C=sector 1
             rst  8 : defb 2Eh   ; READ SECTOR 2
             xor  a
             rst  8 : defb 21h   ; SELECT DRIVE 0 = stop motor
             ret
    ; to WRITE instead: fill BUF, set (TRANSFER)=BUF, BC=track/sector, defb 2Dh.

## Example — read a named file
             ; set D_STR1 (drive) and N_STR1 (name ptr/len) first, then:
             rst 8 : defb 22h    ; OPEN FILE  -> IX = channel
    loop:    rst 8 : defb 25h    ; READ SEQUENTIAL (next 512-byte block into channel)
             ; ... consume (IX+82)..(IX+593) ; CHREC/CHBYTE track position ...
             ; repeat until end; then:
             rst 8 : defb 23h    ; CLOSE FILE

For a fully "raw" path (custom formatters, copy-protection), talk to the 1770 directly
via the ports above and the NMI byte routine at 0066h; the original article lists the
SEEK / WRITE-SECTOR register sequence and an 80-track formatter for that purpose.

---

# Raw WD1770 access (formatters, copy-protection, custom loaders)

Everything below is **disassembled and verified from ROM TurboDr_77D5877D** (the DOS's own
sector engine at 0A0Dh–0AD9h and the NMI handler at 0066h). It is self-contained — you do
not need the magazine scan.

## WD1770 registers (port = high-byte<<8 | 7Fh)
| register | port | dec |
|----------|------|-----|
| Status (r) / Command (w) | 007Fh | 127 |
| Track    | 407Fh | 16511 |
| Sector   | 807Fh | 32895 |
| Data     | C07Fh | 49279 |

Drive/side latch: `OUT (3Fh),A` — D0=Drive1, D1=Drive2, D3=Side, D2=printer strobe.

## WD1770 commands used by TurboDOS
| cmd | value | type |
|-----|-------|------|
| Restore (to track 0) | 00h | I |
| Seek (to Data reg)   | 10h | I |
| Read Sector          | 84h | II (bit2=15 ms head settle) |
| Write Sector         | A4h | II |
| Write Track (format) | F4h | III |
| Force Interrupt      | D0h | IV |

## Status register bits (after a Type II Read/Write)
bit0 BUSY · bit1 DRQ · bit2 LOST DATA · bit3 CRC ERROR · bit4 RECORD NOT FOUND ·
bit5 (write: WRITE FAULT) · bit6 WRITE PROTECT · bit7 MOTOR/NOT READY.
The ROM masks read errors with `AND 1Fh` (then tests bit4 RNF, bit2 Lost) and write
errors with `AND 5Fh` (then tests bit6 Write-Protect); on error it retries the sector 16×.

## Data transfer is NMI-driven
DRQ from the 1770 is wired to the Z80 /NMI. With turbo-ROM paged in, each DRQ vectors to
0066h, which moves exactly one byte and returns. Your code sets HL=buffer, C=7Fh, D=status
port high (00h), E=data port high + direction (C0h read / C1h write) and then just issues
the Read/Write command and waits — the 512 bytes move by themselves. The handler (verified):

```
; ROM 0066h — one byte per NMI
NMIRUT: ex   af,af'          ; save flags in AF'
        ld   b,e             ; B = data-port high (C0h/C1h)
        bit  0,e             ; E bit0 = 1 -> writing (A8 is ignored by the register decode,
        jr   z,NMIRD         ;               so it is reused as the read/write flag)
        outi                 ; (HL)->(C07Fh); HL++; B--
        ld   b,d             ; B = status-port high (00h)
        ex   af,af'
        retn
NMIRD:  ini                  ; (C07Fh)->(HL); HL++; B--
        ld   b,d
        ex   af,af'
        retn
```

## 28 µs settle delay (ROM 0A94h)
```
WT28:   ld   a,5
WT281:  dec  a
        jr   nz,WT281
        ret
```

## SEEK  (A = target track, E = sector)  — from ROM 0A9Ah
```
SEEK:   or   a               ; track 0 ?
        ld   b,#00           ; assume RESTORE (cmd 00h)
        jr   z,SK_CMD
        ld   b,#10           ; else SEEK (cmd 10h)
        ld   c,#7F
        push bc
        ld   bc,#C07F        ; Data register
        out  (c),a           ; Data reg = target track; 1770 will step to it
        pop  bc
SK_CMD: push bc
        ld   bc,#007F        ; Command register
        ld   a,b             ; (00h RESTORE or 10h SEEK held in B above)
        ; ^ load the command you stored; then:
        out  (c),a
        call WT28
SK_WAIT:in   a,(c)           ; status
        rra                  ; bit0 BUSY -> carry
        jr   c,SK_WAIT
        pop  bc
        ld   bc,#807F        ; Sector register
        ld   a,e
        out  (c),a           ; set target sector
        ret
```
(The real ROM also compares the Track register first and skips the step if already there,
and updates the per-drive current-track system variable at 5CC3h/5CC4h.)

## READ one sector — from ROM 0A1Eh (core)
```
; entry: buffer addr in (TRANSFER)=5CC7h; A=track, E=sector; turbo-ROM must be paged in.
RDSEC:  ld   hl,(#5CC7)      ; TRANSFER -> HL (destination)
        call SEEK            ; position head, set sector reg
        ld   d,#00           ; status-port high  (for NMIRUT)
        ld   e,#C0           ; data-port high, bit0=0 => READ
        ld   bc,#007F        ; command register
        ld   a,#84           ; WD1770 READ SECTOR
        out  (c),a
        call WT28
RD_W:   in   a,(c)           ; poll status
        rra                  ; bit0 BUSY
        jr   c,RD_W          ; (512 bytes arrive via NMI meanwhile)
        rla
        and  #1F             ; error bits
        ret  z               ; ok
        ; bit4=RNF, bit2=Lost Data -> handle/retry
        ret
```

## WRITE one sector — from ROM 0A5Dh (core)
Identical to READ except **E = C1h** (bit0=1 => write) and command **A4h**; check status
with `AND 5Fh` and test **bit6 = Write-Protect** afterwards.
```
WRSEC:  ld   hl,(#5CC7)      ; TRANSFER -> HL (source, 512 bytes)
        call SEEK
        ld   d,#00
        ld   e,#C1           ; data-port high, bit0=1 => WRITE
        ld   bc,#007F
        ld   a,#A4           ; WD1770 WRITE SECTOR
        out  (c),a
        call WT28
WR_W:   in   a,(c)
        rra
        jr   c,WR_W
        rla
        and  #5F
        ret  z
        ; bit6=Write-Protect, bit4=RNF -> handle/retry
        ret
```

## Paging turbo-ROM in for the raw path
The NMI byte-mover lives in turbo-ROM, so page it in first and let it jump to your code:
```
        ld   hl,MyRoutine
        ld   (#5CED),hl      ; HD_11 vector (23789)
        rst  8 : defb #32    ; ENTER TURBO-ROM -> JP (HD_11); turbo-ROM stays paged
MyRoutine:
        ; ... now RDSEC/WRSEC/NMIRUT are valid; run raw transfers here ...
```
For simple loading you rarely need this — the high-level `RST 8 : DEFB 2Eh/2Dh`
(READ/WRITE SECTOR 2) already do the paging, SEEK, NMI transfer and retries for you.

---

# Formatting (Write Track) and the 80-track formatter

A TurboDOS track is a standard **IBM System-34, double-density (MFM), 250 kbit/s** track
with **10 sectors of 512 bytes, sector IDs 1..10, size code N=2**. You create it with the
1770 **Write Track (F4h)** command, streaming the whole track image (~6250 bytes) to the
Data register — again via the NMI mover. Write-Track sentinel bytes: **F5h**→writes A1h
(sync, missing clock), **F6h**→C2h, **F7h**→two CRC bytes.

Track image to stream (one track):
```
  Gap4a : 60 x 4Eh
  Index : 12 x 00h, 3 x F6h, FCh, Gap1: 50 x 4Eh
  repeat for sector = 1..10:
        12 x 00h                 ; sync
        3 x F5h, FEh             ; ID address mark
        <track#>,<side 0/1>,<sector 1..10>,<02h=512>
        F7h                      ; ID CRC
        22 x 4Eh                 ; Gap2
        12 x 00h                 ; sync
        3 x F5h, FBh             ; Data address mark
        512 x E5h                ; filler data
        F7h                      ; Data CRC
        24 x 4Eh                 ; Gap3
  Gap4b : 4Eh ... to end of track
```

Formatter algorithm (both sides, tracks 0..N-1):
1. `OUT (3Fh)` select drive/side; motor on.
2. `RST 8 : DEFB 21h` (SELECT DRIVE) to spin up / test ready.
3. For each track: `SEEK` to it, point `(TRANSFER)` at the track image, set `E=C1h`
   (write), issue **Write Track (F4h)**, let the NMI stream the bytes, wait !BUSY,
   check status (bit6 write-protect, bit3 CRC).
4. After all tracks: write track-0 **catalog** (0x3F version + 10-char disk name + 45 empty
   11-byte slots) and the **folder/FAT** sectors (all descriptors 3Fh = free, tail 00h =
   reserved), exactly as decoded in TurboDrive_format.md.

Ready-made alternative: `turbodrive.py build <blank> manifest.json` starts from a verified
blank (`Format0-39.dsk` / `Format0-79.dsk`) whose track-0 catalog+folder are already
correct, so for making releases you normally don't need to run a low-level formatter at all.
