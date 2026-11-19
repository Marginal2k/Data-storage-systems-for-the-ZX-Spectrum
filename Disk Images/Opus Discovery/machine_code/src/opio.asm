; ============================================================================
; opio.asm - a COMPACT Opus Discovery disk driver for programs that are short of
; memory (about 330 bytes for read + write; opuslib.asm is the full library).
; First used by the Terminator 2 port (48K kernel: in #5C00..#5D3A).
; Talks to the WD1770 + MC6821 directly; from the Opus ROM only CALL #1708 (page
; in), JP #1748 (page out) and its NMI vector #0066 = JP (HL) are used - the same
; in every Opus ROM (v1.2 .. QuickDOS 2.31). Call it with the 48K BASIC ROM paged
; (128K: #7FFD bit 4 set): the page-in address is in it.
;
; Positions are "units" of 256 bytes: unit = block * (sector size / 256). Every
; read / write is of WHOLE sectors, so put the data 512-aligned (on SD a read of
; 2 units = 2 sectors, on DD = 1 sector): then the same unit numbers work on SD
; (40x1x18x256) and DD (80x2x10x512) disks - the "universal" layout of mkmono.py.
; Byte-exact loads are the caller's job (stage whole sectors into a free area).
;
;   op_rd    read  RD_N units (even) from unit RD_TS to RD_BUF. RD_TS / RD_BUF / RD_N are not changed.
;   op_wr    write RD_N units (even) at RD_BUF to unit RD_TS (write protected: the FDC refuses, nothing happens)
;   op_cap   right after the ROM LOADed a BASIC file: remember the drive and where the FDC is (the last
;            sector of the BASIC part)            (call FIRST, before any other disk access)
;   op_geom  read the anchor sector (track 0 / sector 0): sectors per track, sector size, tracks per
;            side; RD_BUF = a 512-byte scratch buffer
;   op_base  -> HL = the unit right after the BASIC part, 512-aligned in the file: DD 2*(LB+1),
;            SD LB+1+PADU (PADU = 0/1: 2*ceil(L/512) - ceil(L/256), L = 7-byte header + program)
;
; TIMING: one byte every 32 us = 112 T. The NMI handler (~63 T) must not run in contended RAM, so at every
; operation it is copied to OP_HOLE (>= #8000, 18 bytes, never a read destination). With OPIO_SAVE the
; bytes there are saved and put back afterwards (when the hole holds data of the program).
; Interrupts stay disabled (DI) throughout and on return; the stack may be anywhere (the NMI pushes and
; pops one word per byte). AF' is not preserved (the handler loads the byte through it).
; Rotational order: every track part is read as the sectors pass the head (the Opus format: step 7).
; No timeouts: no disk = hang. Read errors are retried until the sector reads. The Opus RAM is not used.
;
; Needs (equ): RD_TS RD_BUF RD_N  G_VARS (15 bytes)  OP_HOLE  PADU (op_base)
;              OP_SAVE (18 bytes) with OPIO_SAVE
; The file is included once per piece (DEFINE the piece, INCLUDE), so the pieces can sit in different holes
; of memory; each INCLUDE inside a MODULE makes an independent copy:
;   OPIO_CORE (op_in, op_out, handlers, op_cmd, op_b2p, op_seek)  OPIO_IO (op_rd, op_wr; OPIO_NOWR: op_rd only)
;   OPIO_BOOT (op_cap, op_geom, op_base)
; ============================================================================

        IFDEF OPIO_CORE
        UNDEFINE OPIO_CORE
OP_FCMD  equ #2800
OP_FTRK  equ #2801
OP_FSEC  equ #2802
OP_FDAT  equ #2803
OP_PIA   equ #3000
G_SPT    equ G_VARS+0           ; sectors per track (18 / 10)
G_SH     equ G_VARS+1           ; 0 = 256-byte sectors, 1 = 512
G_TPS    equ G_VARS+2           ; tracks per side
G_SEL    equ G_VARS+3           ; PIA value of the boot drive, side 0
G_PHYS   equ G_VARS+4           ; last physical sector (rotational order)
G_FIRST  equ G_VARS+5           ; first sector of the current track part
G_CNT    equ G_VARS+6           ; sectors of the current track part (= G_FIRST+1)
G_LEFT   equ G_VARS+7           ; sectors left                      (= G_CNT+1)
G_BLK    equ G_VARS+8           ; dw: real block (block + 1) of the next track part
G_BUF    equ G_VARS+10          ; dw: memory of the next track part
G_CMD    equ G_VARS+12          ; db: FDC command (#80 read / #A0 write)
G_HND    equ G_VARS+13          ; dw: NMI handler in the hole
G_CAP    equ G_VARS+8           ; 3 bytes (op_cap .. op_base only): track, sector, side flag (#10)
; ---------------------------------------------------------------- entry / exit: DI, page in, handlers into the hole
op_in:  di
        call #1708
        IFDEF OPIO_SAVE
        ld hl,OP_HOLE           ; save the bytes of the hole
        ld de,OP_SAVE
        ld bc,OPH
        ldir
        ld hl,op_nmi            ; copy the handlers
        ld de,OP_HOLE
        ld c,OPH
        ELSE
        ld hl,op_nmi            ; copy the handlers
        ld de,OP_HOLE
        ld bc,OPH
        ENDIF
        ldir
        ret
        IFDEF OPIO_SAVE
op_out: ld hl,OP_SAVE
        ld de,OP_HOLE
        ld bc,OPH
        ldir
        jp #1748
        ELSE
op_out  equ #1748
        ENDIF

; the handlers, run from OP_HOLE (position independent); DE = memory
op_nmi: ex af,af'               ; read
        ld a,(OP_FDAT)
        ld (de),a
        inc de
        ex af,af'
        retn
OP_NMIW equ OP_HOLE+$-op_nmi
        ex af,af'               ; write
        ld a,(de)
        ld (OP_FDAT),a
        inc de
        ex af,af'
        retn
OPH     equ $-op_nmi
        ASSERT OPH <= 32

; ---------------------------------------------------------------- FDC command, A = command -> A = status. Uses AF only.
op_cmd: ld (OP_FCMD),a
        push af                 ; let BUSY come up
        pop af
        push af
        pop af
.w:     ld a,(OP_FCMD)
        rra
        jr c,.w
        ld a,(OP_FCMD)
        ret

; ---------------------------------------------------------------- G_BLK (real block) -> D = track, E = sector (sought; side selected)
op_b2p: ld hl,(G_BLK)
        ld a,(G_SPT)
        ld e,a
        ld d,0
        ld b,d
.dv:    or a
        sbc hl,de
        jr c,.dn
        inc b
        jr .dv
.dn:    add hl,de
        ld e,l                  ; sector
        ld a,(G_TPS)
        ld c,a
        ld a,(G_SEL)
        ld l,a
        ld a,b
        sub c
        jr c,.s0
        ld b,a                  ; side 1: the tracks of side 0 come first
        set 4,l
.s0:    ld a,l
        ld (OP_PIA),a
        ld d,b
; D = track: seek with verify (once more after a restore)
op_seek:
        ld a,(OP_FTRK)
        cp d
        ret z
        call .go
        ret z
        xor a                   ; restore to track 0
        call op_cmd
.go:    ld a,d
        ld (OP_FDAT),a
        ld a,#14                ; seek, verify, spin-up
        call op_cmd
        and #18
        ret
        ENDIF

        IFDEF OPIO_IO
        UNDEFINE OPIO_IO
; ---------------------------------------------------------------- read / write RD_N units from / to unit RD_TS, memory RD_BUF
        IFNDEF OPIO_NOWR
op_wr:  ld a,#a0                ; write sector
        ld hl,OP_NMIW
        jr op_io
        ENDIF
op_rd:  ld a,#80                ; read sector
        ld hl,OP_HOLE
op_io:  ld (G_CMD),a
        ld (G_HND),hl
        call op_in
        ld hl,(RD_BUF)
        ld (G_BUF),hl
        ld hl,(RD_TS)
        ld a,(G_SH)
        or a                    ; (carry 0)
        ld a,(RD_N)
        jr z,.s1
        rra                     ; sectors = units / 2 (even: everything is 512-aligned)
        srl h                   ; block = unit / 2
        rr l
.s1:    ld (G_LEFT),a
        inc hl                  ; real = block + 1 (the anchor is block -1)
        ld (G_BLK),hl
        ld a,(OP_FSEC)          ; the head is near this sector
        ld (G_PHYS),a
.part:  ld a,(G_LEFT)
        or a
        jp z,op_out
        call op_b2p             ; D = track (sought), E = first sector
        ld a,e
        ld (G_FIRST),a
        ld a,(G_SPT)
        sub e
        ld b,a                  ; sectors to the end of the track
        ld a,(G_LEFT)
        cp b
        jr c,.c
        ld a,b
.c:     ld (G_CNT),a
        ld a,(G_SPT)
        ld b,a                  ; visit every sector of the track once, in rotational order (step 7)
.vis:   push bc
        ld a,(G_SPT)
        ld c,a
        ld a,(G_PHYS)
        add a,7
.md:    sub c
        jr nc,.md
        add a,c
        ld (G_PHYS),a
        ld hl,G_FIRST
        sub (hl)
        jr c,.skip              ; before the part
        inc hl
        cp (hl)
        jr nc,.skip             ; after the part
        ld hl,G_SH              ; DE = memory + (sector - first) * sector size
        bit 0,(hl)
        jr z,.b3
        add a,a
.b3:    ld hl,(G_BUF)
        add a,h
        ld d,a
        ld e,l
        ld a,(G_PHYS)
        ld (OP_FSEC),a
        ld hl,(G_HND)
.rt:    push de
        ld a,(G_CMD)
        call op_cmd
        pop de
        and #1c
        jr nz,.rt               ; (until it reads / writes; write protect is not an error here)
.skip:  pop bc
        djnz .vis
        ld hl,G_CNT             ; the part is done
        ld c,(hl)
        inc hl
        ld a,(hl)
        sub c
        ld (hl),a               ; G_LEFT
        ld hl,(G_BLK)
        ld b,0
        add hl,bc
        ld (G_BLK),hl
        ld a,(G_SH)
        or a
        ld a,c
        jr z,.u1
        add a,a
.u1:    ld hl,G_BUF+1
        add a,(hl)
        ld (hl),a
        jp .part
        ENDIF

        IFDEF OPIO_BOOT
        UNDEFINE OPIO_BOOT
; ---------------------------------------------------------------- right after the ROM loaded the head
op_cap: call #1708
        ld a,(OP_PIA)
        ld b,a
        and #ef                 ; boot drive, side 0
        ld (G_SEL),a
        ld a,(OP_FTRK)
        ld (G_CAP),a
        ld a,(OP_FSEC)
        ld (G_CAP+1),a
        ld a,b
        and #10
        ld (G_CAP+2),a
        jp #1748

op_geom:
        call op_in
        ld a,(G_SEL)
        ld (OP_PIA),a
        ld d,0
        call op_seek
        xor a
        ld (OP_FSEC),a
        ld de,(RD_BUF)
        ld hl,OP_HOLE
        ld a,#80                ; the whole anchor sector (256 or 512 bytes) into the scratch buffer
        call op_cmd
        ld hl,(RD_BUF)
        inc hl
        inc hl
        ld a,(hl)
        ld (G_TPS),a
        inc hl
        ld a,(hl)
        ld (G_SPT),a
        inc hl
        ld a,(hl)               ; flags: bits 7-6 = 01 (256) / 10 (512)
        rlca
        rlca
        and 3
        dec a
        ld (G_SH),a
        jp op_out

op_base:
        ld a,(G_CAP)            ; LB + 1 = (side * tps + track) * spt + sector
        ld l,a
        ld h,0
        ld a,(G_CAP+2)
        or a
        jr z,.s0
        ld a,(G_TPS)
        add a,l
        ld l,a
        jr nc,.s0
        inc h
.s0:    ld a,(G_SPT)
        ld b,a
        ex de,hl
        ld hl,0
.mul:   add hl,de
        djnz .mul
        ld a,(G_CAP+1)
        ld e,a
        ld d,0
        add hl,de               ; HL = LB + 1
        ld a,(G_SH)
        or a
        jr z,.sd
        add hl,hl               ; DD: the BASIC part ends on a 512-byte boundary of the file
        ret
.sd:    ld de,PADU              ; SD: the data start on the next 512-byte boundary of the file
        add hl,de
        ret
        ENDIF
