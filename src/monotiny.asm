;==============================================================================
; monotiny.asm - minimal Opus Discovery monoblock loader
;
; Same job as mono.asm (continue reading after the BASIC part, position taken
; from the WD1770 track/sector registers the ROM left behind), but standalone
; and small. Trade-offs: no timeouts (no disk = hang), uses the drive and side
; the ROM left selected, retries a bad sector MONO_RETRY times then reports
; "R Tape loading error".
;
; Speed: each track is visited in rotational order - sector s, s+STEP, ...
; (mod SPT). STEP 7 matches disks formatted by the Opus ROM (physical order
; 7,14,3,10,... for 18x256 and 7,4,1,8,... for 10x512), so a track is read in
; about one revolution. Any other layout still loads correctly, just slower.
; STEP must be coprime with SPT: then every sector of a track is visited
; exactly once in SPT steps and no bitmap is needed.
;
; Exact: a block's last sector is cut to the block's real length by the NMI
; handler (it counts bytes in BC), so nothing after a block is ever written.
;
; Config (mono_cfg.inc, written by tools/mkmono.py --tiny): LDR_ORG, MONO_TPS,
; MONO_SPT (sectors/track), MONO_SPG (sector size / 256: 1, 2 or 4),
; MONO_START, MONO_SP, MONO_TABLE (DB sectors : DW dest : DW tail ... DB 0),
; optionally MONO_STEP (default 11), MONO_RETRY (default 8), OD_RATE.
;==============================================================================
        DEVICE ZXSPECTRUM48
        INCLUDE "mono_cfg.inc"
        IFNDEF MONO_STEP
        DEFINE MONO_STEP 7
        ENDIF
        IFNDEF MONO_RETRY
        DEFINE MONO_RETRY 8
        ENDIF
        IFNDEF OD_RATE
        DEFINE OD_RATE 0
        ENDIF

FDC_CMD = #2800
FDC_TRK = #2801
FDC_SEC = #2802
FDC_DAT = #2803
PIA_A   = #3000
SPT     = MONO_SPT

        IF LDR_ORG
        ORG LDR_ORG - (body - stub)
        ELSE
        ORG 23760
        ENDIF
stub:   ld hl,body - stub       ; BC = USR address (first byte after REM)
        add hl,bc
        ld de,body
        ld bc,body_end - body
        ldir
        jp body

body:   di
        call #1708              ; page the Opus in
        ; Opus RAM present? Then run the NMI handler from it (uncontended).
        ; Two cells with different values: a floating bus cannot fake both.
        ld hl,#26FE
        ld d,(hl)
        inc hl
        ld e,(hl)
        ld (hl),#A5
        dec hl
        ld (hl),#5A
        ld a,(hl)
        cp #5A
        jr nz,.noram
        inc hl
        ld a,(hl)
        cp #A5
        jr nz,.noram
        ld (hl),e
        dec hl
        ld (hl),d
        ld hl,nmi
        ld de,#2100
        ld bc,nmiend - nmi
        ldir
        ld hl,#2100
        ld (nmiptr),hl
.noram:
        ld a,(FDC_SEC)
        ld (sec),a              ; last sector the ROM read = last BASIC sector
        ld (phys),a
        ld ix,table
blk:    ld a,(ix+0)
        or a
        jp z,done
        ld (left),a
        ld l,(ix+1)
        ld h,(ix+2)
        ld (dst),hl
        ld l,(ix+3)             ; bytes wanted from the block's last sector
        ld h,(ix+4)             ; (0 = whole sector)
        ld (tail),hl
track:  ; first sector of this track part
        ld a,(sec)
        inc a
        cp SPT
        jr c,.same
        call nexttrk
        xor a
.same:  ld (first),a
        ld b,a
        ld a,SPT                ; n = min(left, SPT - first)
        sub b
        ld b,a
        ld a,(left)
        cp b
        jr c,.n
        ld a,b
.n:     ld (cnt),a
        ; visit the 18 sectors in rotational order
        ld b,SPT
        ld hl,(nmiptr)          ; HL = NMI handler from here on
.visit: ld a,(phys)
        add a,MONO_STEP
        cp SPT
        jr c,$+4
        sub SPT
        ld (phys),a
        ld c,a
        ld a,(first)
        ld e,a
        ld a,c
        sub e                   ; s - first
        jr c,.skip
        ld e,a
        ld a,(cnt)
        dec a
        cp e
        jr c,.skip              ; s >= first + cnt
        push bc
        ; bytes to keep: the block's last sector -> (tail), else whole
        ld a,(left)
        ld d,a
        ld a,(cnt)
        cp d                    ; last track part of the block?
        jr nz,.full
        dec a
        cp e                    ; and its last sector?
        jr nz,.full
        ld bc,(tail)
        ld a,b
        or c
        jr nz,.cnt
.full:  ld bc,MONO_SPG*256
.cnt:   ld (bytes),bc
        ld a,e
        REPT MONO_SPG/2         ; * sector size in pages (1, 2 or 4)
        add a,a
        ENDR
        ld e,a
        ld a,(dst+1)
        add a,e
        ld d,a
        ld a,(dst)
        ld e,a                  ; DE = dst + (s-first)*size
        ld a,(phys)
        ld (FDC_SEC),a
        ld a,MONO_RETRY
        ld (rtry),a
.retry: push de
        ld bc,(bytes)
        ld a,#80
        call cmd
        pop de
        and #1C
        jr nz,.bad
        ld a,b                  ; every wanted byte arrived?
        or c
        jr z,.ok
.bad:   ld a,(rtry)
        dec a
        ld (rtry),a
        jr nz,.retry
        jp err
.ok:    pop bc
.skip:  djnz .visit
        ; track part done: sec = first + cnt - 1, dst += cnt*256, left -= cnt
        ld a,(cnt)
        ld c,a
        ld a,(first)
        add a,c
        dec a
        ld (sec),a
        ld hl,dst+1
        ld a,c
        REPT MONO_SPG/2
        add a,a
        ENDR
        add a,(hl)
        ld (hl),a
        ld a,(left)
        sub c
        ld (left),a
        jp nz,track
        ld de,5
        add ix,de
        jp blk

done:   call #1748              ; page the Opus out
        IF MONO_SP
        ld sp,MONO_SP
        ENDIF
        IF MONO_START
        jp MONO_START
        ELSE
        ei
        ret
        ENDIF

err:    call #1748
        ei
        rst 8
        db #1A                  ; R Tape loading error

; next track (side 1 after the last track of side 0), seek with verify
nexttrk:
        ld a,(FDC_TRK)
        inc a
        cp MONO_TPS
        jr c,.seek
        ld a,(PIA_A)
        or #10                  ; side 1
        ld (PIA_A),a
        xor a
.seek:  ld (target),a
        ld (FDC_DAT),a
        ld a,#14|OD_RATE
        call cmd
        and #18
        ret z
        ld a,#00|OD_RATE        ; lost: restore, then seek again
        call cmd
        ld a,(target)
        ld (FDC_DAT),a
        ld a,#14|OD_RATE
        ; fall through

cmd:    ld (FDC_CMD),a
        push af
        pop af
        push af
        pop af
.w:     ld a,(FDC_CMD)
        rra
        jr c,.w
        ld a,(FDC_CMD)
        ret

; one byte per DRQ; BC = bytes still wanted, the rest of the sector is
; taken from the FDC and dropped (~84 T)
nmi:    ex af,af'
        ld a,b
        or c
        ld a,(FDC_DAT)
        jr z,.drop
        ld (de),a
        inc de
        dec bc
.drop:  ex af,af'
        retn
nmiend:
nmiptr  dw nmi

sec     db 0
phys    db 0
first   db 0
cnt     db 0
left    db 0
dst     dw 0
tail    dw 0
bytes   dw 0
rtry    db 0
target  db 0
table:  MONO_TABLE
body_end:
        SAVEBIN "mono.bin", stub, body_end - stub
