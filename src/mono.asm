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
        ld (mono_blk),hl
        ld hl,mono_tab
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
        IF MONO_POS
mono_name db MONO_NAME
        ENDIF
mono_tab:
        MONO_TABLE

        INCLUDE "opuslib.asm"
body_end:
        SAVEBIN "mono.bin", stub, body_end - stub
