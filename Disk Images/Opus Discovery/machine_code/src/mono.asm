;==============================================================================
; mono.asm - Opus Discovery "monoblock" loader (like TR-DOS one-file loaders)
;
; The disk holds ONE BASIC file: its header length covers only the BASIC part,
; but its catalog entry covers BASIC + all code blocks, which follow the BASIC
; part sector-aligned. This loader sits in a REM in line 10:
;
;   10 REM <this code>
;   20 CLEAR n: RANDOMIZE USR (PEEK 23635+256*PEEK 23636+5)
;
; After the ROM has LOADed the BASIC part, the WD1770 track and sector
; registers still point at the last sector it read (true for Opus ROM v1.2,
; v2.2, v2.22, EXCOM 2.28 and QuickDOS 2.31). The loader continues from the
; next sector. MONO_POS = 1 finds the file in the catalog by name instead
; (immune to whatever the ROM did last, costs ~70 bytes and a catalog read).
;
; Built by tools/mkmono.py, which writes mono_cfg.inc:
;   LDR_ORG    address the loader body runs at; 0 = in place (REM at 23760 =
;              PROG+5). Otherwise it must not overlap the 15-byte stub.
;   MONO_FAST  1 = rotational-order reader (fast), 0 = compact sequential
;   MONO_POS   0 = FDC registers, 1 = catalog search
;   MONO_TPS   tracks per side of the disk (40 or 80)
;   MONO_SPT   sectors per track (18 or 10), MONO_SPG sector size/256 (1 or 2)
;   MONO_START address to JP to (0 = return to BASIC)
;   MONO_SP    stack pointer to set before the jump (0 = leave)
;   MONO_NB    sectors of the BASIC part (catalog method only)
;   MONO_NAME  10-char file name (catalog method only)
;   MONO_BUF   one-sector buffer for the catalog method (default #5B00)
;   MONO_TABLE macro: blocks as  DB sectors : DW dest : DW tail ... DB 0
;              (tail = bytes in the last sector, 0 = whole: loads are exact)
;   MONO_UNI   1 = UNIVERSAL file: the same file works on SD (256-byte sectors)
;              and DD (512-byte sectors) disks, also when copied from one to
;              the other. Everything after the BASIC part is 512-aligned in the
;              FILE; the table counts 512-byte units (DB units : DW dest : DW
;              bytes in the last unit), MONO_NB too. The geometry comes from the
;              anchor sector at run time (MONO_TPS / SPT / SPG are ignored).
;   MONO_PADU  (MONO_UNI, FDC method) 0/1: on SD the data start this many
;              sectors after the one following the BASIC part (mkmono.py)
;==============================================================================
        DEVICE ZXSPECTRUM48
        INCLUDE "mono_cfg.inc"

        DEFINE OD_FAST  MONO_FAST   ; (opuslib tests these with IFNDEF,
        DEFINE OD_SAVE  0           ;  which only sees DEFINEs / -D)
        DEFINE OD_FILES MONO_POS
        DEFINE OD_TPS0  MONO_TPS
        DEFINE OD_SPT0  MONO_SPT
        DEFINE OD_SPG0  MONO_SPG
        DEFINE OD_BUF MONO_BUF      ; catalog method, Opus without RAM only

;--- position independent stub: copies the body to LDR_ORG ------------------
; entered by USR with BC = address of the first byte after REM
        IF LDR_ORG
        ORG LDR_ORG - (body - stub)
        ELSE
        ORG 23760                       ; in place: PROG(23755) + 5
        ENDIF
stub:   ld hl,body - stub
        add hl,bc
        ld de,body
        ld bc,body_end - body
        ldir
        jp body

body:   di
        call OD_PAGEIN
        call od_init
        ld a,(od_drv)           ; boot drive = the one the ROM used
        or a
        jr z,.d1
        ld (od_unit),a
.d1:
        IF MONO_UNI
        IF MONO_POS = 0
        ld a,(PIA_A)            ; where the ROM stopped: FIRST, before the anchor is read
        and #10
        jr z,.u0
        ld a,1
.u0:    ld (mono_side),a
        ld hl,FDC_SEC
        ld c,(hl)
        dec hl
        ld b,(hl)
        ld (mono_pos),bc
.anc:   ld a,(od_unit)          ; the geometry: bytes 2, 3, 4 of track 0 / sector 0
        ld c,0
        call od_select
        ld hl,5
        ld (od_cnt16),hl
        ld bc,0
        ld de,mono_anc
        call od_rsec
        ld hl,0
        ld (od_cnt16),hl
        jr c,.anc
        ld a,(mono_anc+2)
        ld (od_tps),a
        ld a,(mono_anc+3)
        ld (od_spt),a
        ld a,(mono_anc+4)       ; bits 7-6: 01 = 256, 10 = 512 bytes
        rlca
        rlca
        and 3
        ld (od_spg),a
        ld bc,(mono_pos)
        ld a,(mono_side)
        call od_p2b             ; HL = block of the last BASIC sector
        inc hl
        ld a,(od_spg)
        dec a
        jr nz,.u1               ; DD: the BASIC part ends on a 512-byte boundary of the file
        ld de,MONO_PADU
        add hl,de
.u1:    call OD_PAGEOUT
        ELSE
        call OD_PAGEOUT
        call od_geom            ; (the catalogue is read in the disk's own sectors)
        jr c,mono_err
        ld hl,mono_name
        call od_find            ; HL = first block of this file
        jr c,mono_err
        ld de,MONO_NB           ; 512-byte units of the BASIC part
        add hl,de
        ld a,(od_spg)
        dec a
        jr nz,.u2
        add hl,de               ; SD: two blocks per unit
.u2:
        ENDIF
        ELSE
        IF MONO_POS = 0
        ld a,(PIA_A)
        and #10
        jr z,.s0
        ld a,1
.s0:    ld hl,FDC_SEC
        ld c,(hl)
        dec hl
        ld b,(hl)
        call od_p2b             ; HL = block of the last BASIC sector
        inc hl
        call OD_PAGEOUT
        ELSE
        call OD_PAGEOUT
        ld hl,mono_name
        call od_find            ; HL = first block of this file
        jr c,mono_err
        ld de,MONO_NB
        add hl,de
        ENDIF
        ENDIF
        ld (mono_blk),hl
        ld hl,mono_tab
        IF MONO_UNI
.unx:   ld a,(hl)               ; 512-byte units (0 = end of table)
        or a
        jr z,.done
        ld b,a
        inc hl
        ld e,(hl)               ; destination
        inc hl
        ld d,(hl)
        inc hl
        ld c,(hl)               ; bytes in the last unit (0 = whole)
        inc hl
        ld a,(hl)
        inc hl
        push hl
        push de
        ld h,a
        ld l,c
        ld a,(od_spg)
        dec a
        ld a,b
        jr nz,.ud               ; DD: one sector per unit, the tail as it is
        add a,a                 ; SD: two sectors per unit
        ld b,a
        ld (mono_step),a
        ld a,h
        or l
        jr z,.ut                ; whole: whole sectors
        ld a,h
        or a
        jr nz,.uh
        dec b                   ; 1..255 bytes: the unit's 2nd sector is not needed
        jr .ut
.uh:    ld a,l                  ; 256..511: the 2nd sector holds L bytes (0 = none)
        or a
        jr nz,.uh2
        dec b
.uh2:   ld h,0
        jr .ut
.ud:    ld (mono_step),a
.ut:    ld (od_tail),hl
        pop de
        ld hl,(mono_blk)
        call od_read            ; pages in/out itself; the last sector cut to the tail
        pop hl
        jr c,mono_err
        push hl
        ld hl,(mono_blk)
        ld a,(mono_step)
        ld e,a
        ld d,0
        add hl,de
        ld (mono_blk),hl
        pop hl
        jr .unx
        ELSE
.next:  ld a,(hl)               ; sectors (0 = end of table)
        or a
        jr z,.done
        ld b,a
        inc hl
        ld e,(hl)               ; destination
        inc hl
        ld d,(hl)
        inc hl
        ld a,(hl)               ; bytes wanted from the last sector
        ld (od_tail),a          ; (0 = whole): od_read cuts the block
        inc hl                  ; to its exact length
        ld a,(hl)
        ld (od_tail+1),a
        inc hl
        push hl
        ld c,b
        push bc
        ld hl,(mono_blk)
        call od_read            ; pages in/out itself
        pop bc
        pop hl
        jr c,mono_err
        push hl
        ld hl,(mono_blk)
        ld b,0
        add hl,bc
        ld (mono_blk),hl
        pop hl
        jr .next
        ENDIF
.done:
        IF MONO_SP
        ld sp,MONO_SP
        ENDIF
        IF MONO_START
        jp MONO_START
        ELSE
        ei
        ret
        ENDIF

mono_err:
        ei
        rst 8
        db #1A                  ; R Tape loading error

mono_blk dw 0
        IF MONO_UNI
mono_step db 0
mono_side db 0
mono_pos dw 0
mono_anc ds 5
        ENDIF
        IF MONO_POS
mono_name db MONO_NAME
        ENDIF
mono_tab:
        MONO_TABLE

        INCLUDE "opuslib.asm"
body_end:
        SAVEBIN "mono.bin", stub, body_end - stub
