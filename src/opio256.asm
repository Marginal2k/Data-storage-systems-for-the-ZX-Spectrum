; ============================================================================
; opio256.asm - the compact Opus Discovery driver for the two STANDARD formats
; only: 180K (40x1x18x256) and 720K (80x2x18x256). Smaller and simpler than
; opio.asm: no anchor, no sector size, no 512-byte alignment.
;
; Why no geometry is needed: both formats have 18 sectors of 256 bytes per
; track. The Opus fills side 0 first (all its tracks), then side 1, so the only
; thing that differs is where side 1 starts: after track 79 on 720K. On 180K a
; file never gets past track 39, so "side 1 after track 79" is right for both.
; (Not for the non-standard 360K 40x2 or any 512-byte format: use opio.asm.)
;
; From the Opus ROM only CALL #1708 (page in), JP #1748 (page out) and the NMI
; vector #0066 = JP (HL) are used - the same in every Opus ROM (v1.2 .. QuickDOS
; 2.31). Call it with the 48K BASIC ROM paged (128K: #7FFD bit 4 set).
;
; Positions are blocks (= sectors) of 256 bytes: block B is "real" sector B+1
; (block -1 is the anchor), track = real / 18, sector = real mod 18, side 1 from
; track 80 on. Reads and writes are of WHOLE sectors: stage them into a free area
; when the bytes after a block matter.
;
;   op_rd    read  RD_N sectors (1..255) from block RD_TS to RD_BUF. RD_TS / RD_BUF / RD_N are not changed.
;   op_wr    write RD_N sectors at RD_BUF to block RD_TS (write protected: the FDC refuses, nothing happens)
;   op_cap   right after the ROM LOADed a BASIC file: remember the drive and where the FDC is (the last
;            sector of the BASIC part)            (call FIRST, before any other disk access)
;   op_base  -> HL = the block right after the BASIC part (the data of a monoblock)
;
; TIMING: one byte every 32 us = 112 T. The NMI handler (~63 T) must not run in contended RAM, so at every
; operation it is copied to OP_HOLE (>= #8000, 18 bytes, never a read destination). With OPIO_SAVE the
; bytes there are saved and put back afterwards (when the hole holds data of the program).
; Interrupts stay disabled (DI) throughout and on return; the stack may be anywhere. AF' is not preserved.
; Rotational order: every track part is read as the sectors pass the head (the Opus format: step 7).
; No timeouts: no disk = hang. Read errors are retried until the sector reads. The Opus RAM is not used.
;
; Needs (equ): RD_TS RD_BUF RD_N  G_VARS (12 bytes)  OP_HOLE   OP_SAVE (18 bytes) with OPIO_SAVE
; The file is included once per piece (DEFINE the piece, INCLUDE); inside a MODULE each INCLUDE is an
; independent copy:  OPIO_CORE (op_in, op_out, handlers, op_cmd, op_b2p, op_seek)
;                    OPIO_IO (op_rd, op_wr; OPIO_NOWR: op_rd only)   OPIO_BOOT (op_cap, op_base)
; ============================================================================

        IFDEF OPIO_CORE
        UNDEFINE OPIO_CORE
OP_SPT   equ 18
OP_TPS   equ 80                 ; side 1 starts after this many tracks (720K; never reached on 180K)
OP_FCMD  equ #2800
OP_FTRK  equ #2801
OP_FSEC  equ #2802
OP_FDAT  equ #2803
OP_PIA   equ #3000
G_SEL    equ G_VARS+0           ; PIA value of the boot drive, side 0
G_PHYS   equ G_VARS+1           ; last physical sector (rotational order)
G_FIRST  equ G_VARS+2           ; first sector of the current track part
G_CNT    equ G_VARS+3           ; sectors of the current track part (= G_FIRST+1)
G_LEFT   equ G_VARS+4           ; sectors left                      (= G_CNT+1)
G_BLK    equ G_VARS+5           ; dw: real block (block + 1) of the next track part
G_BUF    equ G_VARS+7           ; dw: memory of the next track part
G_CMD    equ G_VARS+9           ; db: FDC command (#80 read / #A0 write)
G_HND    equ G_VARS+10          ; dw: NMI handler in the hole
G_CAP    equ G_VARS+5           ; 3 bytes (op_cap .. op_base only): track, sector, side flag (#10)
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
        ld de,OP_SPT
        ld b,d
.dv:    or a
        sbc hl,de
        jr c,.dn
        inc b
        jr .dv
.dn:    add hl,de
        ld e,l                  ; sector
        ld a,(G_SEL)
        ld l,a
        ld a,b
        sub OP_TPS
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
; ---------------------------------------------------------------- read / write RD_N sectors from / to block RD_TS, memory RD_BUF
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
        ld a,(RD_N)
        ld (G_LEFT),a
        ld hl,(RD_TS)
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
        ld a,OP_SPT
        sub e
        ld b,a                  ; sectors to the end of the track
        ld a,(G_LEFT)
        cp b
        jr c,.c
        ld a,b
.c:     ld (G_CNT),a
        ld b,OP_SPT             ; visit every sector of the track once, in rotational order (step 7)
.vis:   push bc
        ld a,(G_PHYS)
        add a,7
        cp OP_SPT
        jr c,.md
        sub OP_SPT
.md:    ld (G_PHYS),a
        ld hl,G_FIRST
        sub (hl)
        jr c,.skip              ; before the part
        inc hl
        cp (hl)
        jr nc,.skip             ; after the part
        ld hl,(G_BUF)           ; DE = memory + (sector - first) * 256
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
        ld hl,G_BUF+1
        ld a,(hl)
        add a,c
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

; -> HL = the block after the last sector the ROM read = (side * 80 + track) * 18 + sector
op_base:
        ld a,(G_CAP)
        ld l,a
        ld h,0
        ld a,(G_CAP+2)
        or a
        jr z,.s0
        ld de,OP_TPS
        add hl,de
.s0:    add hl,hl               ; * 18 = * 16 + * 2
        ld d,h
        ld e,l
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,de
        ld a,(G_CAP+1)
        ld e,a
        ld d,0
        add hl,de
        ret
        ENDIF
