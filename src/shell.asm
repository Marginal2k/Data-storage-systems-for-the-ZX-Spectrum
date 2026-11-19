;==============================================================================
; shell.asm - "run": the program launcher of an Opus Discovery disk.
;
; The BASIC file "run" (made by tools/mkshell.py) is
;   10 IF NOT USR VAL "PEEK 23627+256*PEEK 23628" THEN STOP
;   20 LOAD *"m";VAL "1";"??????????"
; with this code in its variables area (VARS -> an 18-byte stub that copies the
; code to SH_ORG and jumps there). The code
;   * takes the drive "run" was loaded from (the PIA) and the disk geometry
;     (anchor sector) - SD and DD disks alike,
;   * reads the catalogue, keeps the BASIC files (type 0 in the 7-byte file
;     header) except "run" itself,
;   * none: prints NO PROGRAMS, USR = 0 -> STOP
;     one: takes it at once; more: a menu, keys 1..9 A..Z, SPACE = back to BASIC
;   * writes the name into the string of line 20 and the drive into VAL "1";
;     USR = 1 -> line 20: the Opus ROM loads and runs the program as usual.
; Disk access: opuslib (ROM independent; v1.2 .. QuickDOS 2.31).
;==============================================================================
        DEVICE ZXSPECTRUM48
SH_ORG  equ #c000
CAT     equ #d000               ; catalogue (at most 4K)
CATMAX  equ #1000
        DEFINE OD_BUF #e000     ; one sector (512) for od_geom and the file headers
        DEFINE OD_SAVE 0
        DEFINE OD_RAW 0
MAXP    equ 35                  ; menu keys 1..9, A..Z
PROG    equ 23635
VARS    equ 23627
LAST_K  equ 23560
FLAGS   equ 23611

        ORG SH_ORG
start:  exx
        push hl                 ; H'L' and IY must survive for the return to BASIC
        exx
        push iy
        call #1708              ; the drive "run" came from
        di
        call od_init
        ld a,(od_drv)
        ld (od_unit),a
        call #1748
        call od_geom
        jp c,fail
        ld hl,0                 ; block 0: entry 0 says how many blocks the catalogue has
        ld b,1
        ld de,CAT
        call od_read
        jp c,fail
        ld hl,(CAT+4)
        inc hl                  ; catalogue blocks
        ld a,(od_spg)           ; at most CATMAX bytes
        ld b,a
        ld a,CATMAX >> 8
.lim:   dec b
        jr z,.l1
        srl a
        jr .lim
.l1:    cp l
        jr c,.l2
        ld a,l
.l2:    ld b,a
        ld hl,0
        ld de,CAT
        call od_read
        jp c,fail
; ---- the programs
        xor a
        ld (np),a
        ld ix,CAT+16
.ent:   ld a,(ix+4)
        and (ix+5)
        inc a
        jr z,.done              ; end = #FFFF: the end of the disk
        push ix
        pop hl
        ld de,6
        add hl,de
        ld de,s_run
        ld b,10
.cmp:   ld a,(de)
        cp (hl)
        jr nz,.oth
        inc de
        inc hl
        djnz .cmp
        jr .next                ; "run" itself
.oth:   ld l,(ix+2)             ; the file header: type 0 = BASIC
        ld h,(ix+3)
        ld b,1
        ld de,OD_BUF
        push ix
        call od_read
        pop ix
        jr c,.next
        ld a,(OD_BUF)
        or a
        jr nz,.next
        ld a,(np)
        cp MAXP
        jr nc,.done
        ld l,a
        inc a
        ld (np),a
        ld h,0
        add hl,hl
        ld de,lst
        add hl,de
        push ix
        pop de
        ld (hl),e
        inc hl
        ld (hl),d
.next:  ld de,16
        add ix,de
        push ix
        pop hl
        ld de,CAT+CATMAX
        or a
        sbc hl,de
        jr c,.ent
.done:  ei
        ld a,(np)
        or a
        jp z,none
        dec a
        jp z,go                 ; one program: no menu (A = 0)
; ---- the menu
        call cls
        ld hl,s_head
        call pstr
        ld b,0
.it:    ld a,b
        ld hl,np
        cp (hl)
        jr nc,.key
        push bc
        ld a,b                  ; AT 4 + i mod 18, 2 + 16 * (i / 18)
        ld c,2
        cp 18
        jr c,.at
        sub 18
        ld c,18
.at:    add a,4
        ld (row),a
        ld a,c
        ld (col),a
        ld a,b
        call keych
        call pch
        ld a,' '
        call pch
        call pch
        ld a,b
        call entry
        ld de,6
        add hl,de
        ld b,10
.nm:    ld a,(hl)
        and #7f
        cp ' '
        jr nc,.pc
        ld a,'?'
.pc:    call pch
        inc hl
        djnz .nm
        pop bc
        inc b
        jr .it
.key:   ld hl,FLAGS
        res 5,(hl)
.wk:    halt
        bit 5,(hl)
        jr z,.wk
        res 5,(hl)
        ld a,(LAST_K)
        cp ' '
        jr z,back
        cp 'a'
        jr c,.up
        sub 32                  ; lower case -> upper
.up:    sub '1'
        jr c,.wk
        cp 9
        jr c,.ok                ; 1..9 -> 0..8
        sub 'A'-'1'
        jr c,.wk
        add a,9                 ; A..Z -> 9..34
.ok:    ld hl,np
        cp (hl)
        jr nc,.wk
; ---- A = index: patch line 20 and return 1
go:     call entry
        ld de,6
        add hl,de
        push hl
        ld hl,(PROG)            ; the ten '?' of line 20
        ld de,(VARS)
.f1:    ld a,'?'
        ld b,10
        push hl
.f2:    cp (hl)
        jr nz,.f3
        inc hl
        djnz .f2
        pop de
        pop hl
        ld bc,10
        ldir
        ld hl,(PROG)            ; VAL "1": the drive (the first VAL followed by a quoted digit)
.f4:    ld a,(hl)
        inc hl
        cp #b0
        jr nz,.f4
        ld a,(hl)
        cp '"'
        jr nz,.f4
        inc hl
        ld a,(hl)
        sub '0'
        cp 10
        jr nc,.f4
        ld a,(od_unit)
        add a,'0'
        ld (hl),a
        ld bc,1
        jr ret_bc
.f3:    pop hl
        inc hl
        jr .f1

none:   call cls
        ld hl,s_none
        call pstr
back:   ld bc,0
ret_bc: pop iy
        exx
        pop hl
        exx
        ei
        ret
fail:   ei
        call cls
        ld hl,s_err
        call pstr
        jr back

; A = index -> HL = catalogue entry
entry:  ld l,a
        ld h,0
        add hl,hl
        ld de,lst
        add hl,de
        ld a,(hl)
        inc hl
        ld h,(hl)
        ld l,a
        ret
; A = index -> A = key character
keych:  add a,'1'
        cp '9'+1
        ret c
        add a,'A'-'9'-1
        ret
; text: 22, row, col = AT; characters 32..127 (ROM font, straight into the screen: no ROM PRINT, no scrolling)
pstr:   ld a,(hl)
        inc hl
        or a
        ret z
        cp 22
        jr nz,.c
        ld a,(hl)
        ld (row),a
        inc hl
        ld a,(hl)
        ld (col),a
        inc hl
        jr pstr
.c:     call pch
        jr pstr
pch:    push af
        push bc
        push de
        push hl
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,#3c00
        add hl,de
        ex de,hl                ; DE = glyph
        ld a,(row)
        ld b,a
        and #18
        or #40
        ld h,a
        ld a,b
        and 7
        rrca
        rrca
        rrca
        ld l,a
        ld a,(col)
        add a,l
        ld l,a
        ld b,8
.l:     ld a,(de)
        ld (hl),a
        inc de
        inc h
        djnz .l
        ld hl,col
        inc (hl)
        pop hl
        pop de
        pop bc
        pop af
        ret
cls:    ld hl,#4000
        ld de,#4001
        ld bc,6144
        ld (hl),l
        ldir
        ld (hl),#38             ; black on white
        ld bc,767
        ldir
        xor a
        ld (row),a
        ld (col),a
        ret
row:    db 0
col:    db 0

s_run:  db "run       "
s_head: db 22,0,0, "OPUS DISCOVERY",22,1,0, "Press a key to start a program:",22,21,0, "SPACE: BASIC",0
s_none: db "NO PROGRAMS",0
s_err:  db "DISK ERROR",0
np:     db 0
lst:    ds MAXP*2

        INCLUDE "opuslib.asm"
sh_end:
        ASSERT sh_end <= CAT
        SAVEBIN "build/shell.bin", SH_ORG, sh_end-SH_ORG
        DISPLAY "shell ", SH_ORG, "..", sh_end-1, " size ", /D, sh_end-SH_ORG
