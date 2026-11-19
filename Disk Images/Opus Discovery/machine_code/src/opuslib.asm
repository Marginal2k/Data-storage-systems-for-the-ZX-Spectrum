;==============================================================================
; opuslib.asm - Opus Discovery disk access from machine code (sjasmplus)
;
; ROM-independent: talks to the WD1770 + MC6821 directly. The only things taken
; from the Opus ROM are the ones identical in every version (v1.2, v2.2, v2.22,
; EXCOM 2.28, QuickDOS 2.31):
;     CALL #1708  - page the Opus in   (all registers preserved)
;     CALL #1748  - page the Opus out  (#1748 holds RET)
;     #0066       - NMI vector = JP (HL)   (WD1770 DRQ is wired to NMI)
;
; While the Opus is paged in, #0000-#3FFF is ROM/RAM/IO, so all code, buffers
; and the stack must be at #4000 or above. Routines return with DI.
;
; EXACT TRANSFERS: the NMI handlers count bytes in BC. A read stores exactly
; the requested number of bytes and drops the rest of the sector, so nothing
; after a file or block is ever written - not even temporarily. od_load and
; od_save never touch memory outside the file either.
;
; TIMING (real hardware): a byte arrives every 32 us = 112 T. The read NMI
; costs ~84 T. In #4000-#7FFF the ULA can stretch it past 112 T, so:
;
; OPUS RAM: most Opus units carry an optional 2K RAM (#2000-#27FF, visible
; only while the Opus is paged in - exactly when NMIs happen). Every ROM
; version uses only #2000-#208F (tables) and #2780-#27FF (anchor code). When
; od_init finds the RAM it copies the NMI handlers to OD_RAMNMI (#2100) and
; uses OD_RAMBUF (#2200, 1K) as the sector buffer: then this library may sit
; anywhere, contended memory included, and needs no Spectrum RAM buffer.
; Without the RAM the handlers run in place (keep the library at #8000+ on
; real hardware) and the buffer is OD_BUF.
;
; Configuration (DEFINE before INCLUDE, or sjasmplus -DNAME=value;
; IFNDEF only sees DEFINEs, not labels set with '='):
;   OD_BUF     one-sector buffer in Spectrum RAM, used when there is no Opus
;              RAM (DEFINE OD_BUF #xxxx). Not defined: the file routines
;              return CY, A=#FE on an Opus without RAM.
;   OD_ORAM    1 = use the Opus RAM when present                        (def 1)
;   OD_FAST    1 = read/write in rotational order (step autodetected) (def 1)
;   OD_SAVE    1 = include od_write / od_save                          (def 1)
;   OD_FILES   1 = include od_find / od_load / od_geom (need OD_BUF)   (def 1)
;   OD_RAW     1 = include od_rload / od_rsave: raw files               (def 1)
;              (part of OD_FILES; od_rsave also needs OD_SAVE)
;   OD_RATE    step rate bits 0..3 (6/12/20/30 ms)                      (def 0)
;   OD_RETRY   retries per sector                                      (def 6)
;   OD_TOUT    timeout per FDC command, units of ~1.1 s                (def 3)
;   OD_TPS0 / OD_SPT0 / OD_SPG0   initial geometry (40 / 18 / 1)
;   OD_MAXSPT  largest sectors/track the fast reader handles           (def 24)
;
; Geometry: od_geom reads the anchor sector (as the ROM does), or set
; od_tps/od_spt/od_spg. Formats seen in practice:
;   "SD": 40 tracks, 1 side, 18 x 256   (anchor flags #40)
;   "DD": 80 tracks, 2 sides, 10 x 512  (anchor flags #90)
; Block B -> real=B+1, sector=real%SPT, t=real/SPT, track=t%TPS, side=t/TPS.
; A logical block is one sector. Buffers hold one sector (256/512/1024).
;==============================================================================

        IFNDEF OD_FAST
OD_FAST  = 1
        ENDIF
        IFNDEF OD_SAVE
OD_SAVE  = 1
        ENDIF
        IFNDEF OD_FILES
OD_FILES = 1
        ENDIF
        IFNDEF OD_RAW
OD_RAW   = 1
        ENDIF
        IFNDEF OD_RATE
OD_RATE  = 0
        ENDIF
        IFNDEF OD_RETRY
OD_RETRY = 6
        ENDIF
        IFNDEF OD_TOUT
OD_TOUT  = 3
        ENDIF
        IFNDEF OD_TPS0
OD_TPS0  = 40
        ENDIF
        IFNDEF OD_SPT0
OD_SPT0  = 18
        ENDIF
        IFNDEF OD_SPG0
OD_SPG0  = 1
        ENDIF
        IFNDEF OD_MAXSPT
OD_MAXSPT = 24
        ENDIF
        IFNDEF OD_ORAM
OD_ORAM  = 1
        ENDIF
        IFDEF OD_BUF
OD_SBUF  = OD_BUF
        ELSE
OD_SBUF  = 0
        ENDIF

OD_RAMNMI  = #2100              ; NMI handlers in the Opus RAM
OD_RAMBUF  = #2200              ; 1K sector buffer in the Opus RAM
OD_RAMTST1 = #26FE              ; presence test cells
OD_RAMTST2 = #26FF

OD_PAGEIN  = #1708
OD_PAGEOUT = #1748

FDC_CMD = #2800                 ; write: command   read: status
FDC_TRK = #2801
FDC_SEC = #2802
FDC_DAT = #2803
PIA_A   = #3000                 ; b0/b1 drive select, b4 side, b5 FM, b7 joy
PIA_CA  = #3001                 ; control A, b2=1 -> PIA_A is the data reg

;------------------------------------------------------------------------------
; State. od_unit and the geometry may be changed by the caller at any time.
;------------------------------------------------------------------------------
od_unit db 1                    ; drive for logical ops: 1 or 2
od_tps  db OD_TPS0              ; tracks per side
od_spt  db OD_SPT0              ; sectors per track
od_spg  db OD_SPG0              ; sector size / 256 (1, 2 or 4)
od_tail dw 0                    ; od_read: bytes wanted from the LAST sector
                                ; (0 = whole); cleared after every od_read
od_step db 0                    ; physical sector step (0 = autodetect)
od_drv  db 0                    ; drive currently owning the track register
od_otrk db #FF                  ; track register of the other drive (#FF=?)
od_tc   db 0                    ; timeout counter
od_rc   db 0                    ; retry counter
od_op   db 0                    ; #80 read / #A0 write
od_st   db 0                    ; last status
od_ts   dw 0                    ; od_xsec: sector (lo), track (hi)
od_cnt16 dw 0                   ; bytes for the current transfer
od_rem  dw 0                    ; BC left after a transfer (0 = complete)
od_ram  db 0                    ; 1 = Opus RAM present (set by od_init)
od_buf  dw OD_SBUF              ; sector buffer in use (0 = none)
od_hrd  dw od_nmird             ; NMI handlers in use
od_hwr  dw od_nmiwr

;------------------------------------------------------------------------------
; od_init - make sure the PIA is set up, adopt the drive/track the ROM left.
; Call with the Opus paged in. Keeps the track register (needed by monoloaders).
;------------------------------------------------------------------------------
od_init:
        ld a,(PIA_CA)
        and 4
        jr nz,.pia_ok
        ld a,#BF                ; DDR: everything output except b6 (printer)
        ld (PIA_A),a
        ld a,(PIA_CA)
        or 4
        ld (PIA_CA),a
        ld a,#80
        ld (PIA_A),a
.pia_ok:
        ld a,(PIA_A)
        and 3
        ld (od_drv),a
        IF OD_ORAM
        push bc
        push de
        push hl
        ; Opus RAM? Write two different values, read both back (two cells, so
        ; that a floating bus holding the last value cannot fake a match).
        ld hl,OD_RAMTST1
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
        ld (hl),e               ; restore
        dec hl
        ld (hl),d
        ld hl,od_nmird          ; copy the handlers (position independent)
        ld de,OD_RAMNMI
        ld bc,od_nmiend - od_nmird
        ldir
        ld hl,OD_RAMNMI
        ld (od_hrd),hl
        ld hl,OD_RAMNMI + od_nmiwr - od_nmird
        ld (od_hwr),hl
        ld hl,OD_RAMBUF
        ld a,1
        jr .set
.noram: ld hl,od_nmird
        ld (od_hrd),hl
        ld hl,od_nmiwr
        ld (od_hwr),hl
        ld hl,OD_SBUF
        xor a
.set:   ld (od_ram),a
        ld (od_buf),hl
        pop hl
        pop de
        pop bc
        ENDIF
        ret

;------------------------------------------------------------------------------
; od_cmd - send command A, wait until not busy.
; Out: A = status, NC = finished, CY = timeout (command aborted, A=#10).
; Uses AF only (IX saved): BC/DE/HL belong to the NMI handler meanwhile.
;------------------------------------------------------------------------------
od_cmd:
        ld (FDC_CMD),a
        push ix
        ex (sp),ix              ; ~100 T so that BUSY is up before polling
        ex (sp),ix
        ex (sp),ix
        ex (sp),ix
        ld ix,0
        ld a,OD_TOUT
        ld (od_tc),a
.wait:  ld a,(FDC_CMD)
        rra
        jr nc,.done
        dec ix
        ld a,ixh
        or ixl
        jr nz,.wait
        ld a,(od_tc)
        dec a
        ld (od_tc),a
        jr nz,.wait
        ld a,#D0                ; force interrupt
        ld (FDC_CMD),a
        ex (sp),ix
        ex (sp),ix
        pop ix
        ld a,#10
        scf
        ret
.done:  pop ix
        ld a,(FDC_CMD)
        or a
        ret

;------------------------------------------------------------------------------
; od_select - A = drive (1/2), C = side (0/1). Keeps a track register per drive.
; Uses AF,B.
;------------------------------------------------------------------------------
od_select:
        ld b,a
        ld a,(od_drv)
        cp b
        jr z,.same
        or a
        jr z,.adopt             ; nobody owned it: keep TR as is
        ld a,(FDC_TRK)          ; swap TR with the other drive's copy
        push af
        ld a,(od_otrk)
        ld (FDC_TRK),a
        pop af
        ld (od_otrk),a
.adopt: ld a,b
        ld (od_drv),a
.same:  ld a,c
        and 1
        rlca
        rlca
        rlca
        rlca
        or b
        or #80                  ; joystick "unformatted", MFM (b5=0)
        ld (PIA_A),a
        ret

;------------------------------------------------------------------------------
; od_restore - head to track 0.   od_seek - D = track (verified).
; Out: NC ok, CY error, A = status. Uses AF.
;------------------------------------------------------------------------------
od_restore:
        ld a,#00|OD_RATE
        call od_cmd
        ret c
        xor a
        ld (FDC_TRK),a
        ret

od_seek:
        ld a,(FDC_TRK)
        cp d
        ret z                   ; already there (NC)
        inc a                   ; unknown (#FF)?
        call z,od_restore
        call .go
        ret nc
        call od_restore         ; lost: recalibrate and try once more
        ret c
.go:    ld a,d
        ld (FDC_DAT),a
        ld a,#14|OD_RATE        ; seek, verify, spin-up if needed
        call od_cmd
        ret c
        and #18                 ; seek error / CRC in ID
        ret z
        scf
        ret

;------------------------------------------------------------------------------
; NMI handlers, one byte per DRQ. HL holds the handler address during the
; command (the Opus ROM has JP (HL) at #0066), DE = memory pointer,
; BC = bytes still wanted. Reading: bytes beyond BC are taken from the FDC
; and dropped. ~84 T including the NMI response.
;------------------------------------------------------------------------------
od_nmird:
        ex af,af'
        ld a,b
        or c
        ld a,(FDC_DAT)
        jr z,.drop
        ld (de),a
        inc de
        dec bc
.drop:  ex af,af'
        retn

od_nmiwr:                       ; (always assembled: tiny, keeps the copy simple)
        ex af,af'
        ld a,(de)
        ld (FDC_DAT),a
        inc de
        dec bc
        ex af,af'
        retn
od_nmiend:

; od_xfer - run the read/write command (od_op) on sector A of the current
; track: BC = bytes, DE = memory. Out: NC + Z ok (DE advanced, all bytes moved)
; or CY with A = status. Saves HL.
od_xfer:
        ld (FDC_SEC),a
        push hl
        ld hl,(od_hrd)
        ld a,(od_op)
        cp #80
        jr z,.rd
        ld hl,(od_hwr)
.rd:    call od_cmd
        ld (od_rem),bc
        pop hl
        ret c
        ld (od_st),a
        bit 6,a                 ; write protected? (only meaningful on write)
        jr z,.nowp
        ld a,(od_op)
        cp #80
        ld a,(od_st)
        scf
        ret nz
.nowp:  and #1C                 ; RNF / CRC / lost data
        jr nz,.bad
        ld a,(od_rem)           ; all bytes moved?
        ld c,a
        ld a,(od_rem+1)
        or c
        ret z
        ld a,#04                ; no: "lost data"
.bad:   scf
        ret

; bytes in one sector -> BC
od_secsize:
        ld a,(od_spg)
        ld b,a
        ld c,0
        ret

;------------------------------------------------------------------------------
; od_rsec / od_wsec - one physical sector on the selected drive/side.
; In: B = track, C = sector, DE = memory, (od_cnt16) = bytes (0 = whole sector).
; Out: NC ok (DE advanced), CY error with A = status (b6 = write protected).
; Retries OD_RETRY times.
;------------------------------------------------------------------------------
od_rsec:
        ld a,#80
        IF OD_SAVE
        jr od_xsec
od_wsec:
        ld a,#A0
        ENDIF
od_xsec:
        ld (od_op),a
        ld (od_ts),bc
        ld a,OD_RETRY
        ld (od_rc),a
.again: push de
        ld a,(od_ts+1)
        ld d,a
        call od_seek
        pop de
        jr c,.fail
        push de
        ld bc,(od_cnt16)
        ld a,b
        or c
        call z,od_secsize
        ld a,(od_ts)
        call od_xfer
        jr c,.err
        inc sp                  ; drop the saved DE (keep the flags!)
        inc sp
        ld bc,(od_ts)
        ret
.err:   pop de
        ld (od_st),a
        bit 6,a
        jr z,.notwp
        ld c,a
        ld a,(od_op)
        cp #80
        ld a,c
        jr nz,.fail             ; write protected: no point retrying
.notwp: and #10
        call nz,od_restore      ; RNF: maybe on the wrong track
        ld a,(od_rc)
        dec a
        ld (od_rc),a
        jr nz,.again
        ld a,(od_st)
.fail:  ld bc,(od_ts)
        scf
        ret

;------------------------------------------------------------------------------
; od_b2p - HL = logical block -> B = track, C = sector, A = side. Keeps DE.
;------------------------------------------------------------------------------
od_b2p:
        push de
        inc hl
        ld a,(od_spt)
        ld e,a
        ld d,0
        ld b,-1
.div:   inc b
        or a
        sbc hl,de
        jr nc,.div
        add hl,de
        ld c,l
        pop de
        ld a,(od_tps)
        ld l,a
        ld a,b
        sub l
        jr c,.s0
        ld b,a
        ld a,1
        ret
.s0:    xor a
        ret

;------------------------------------------------------------------------------
; od_p2b - B = track, C = sector, A = side -> HL = logical block
;------------------------------------------------------------------------------
od_p2b:
        ld h,0
        ld l,b
        or a
        jr z,.s0
        ld a,(od_tps)
        add a,l
        ld l,a
        jr nc,.s0
        inc h
.s0:    push de
        push bc
        ex de,hl
        ld hl,0
        ld a,(od_spt)
        ld b,a
.mul:   add hl,de               ; * sectors per track
        djnz .mul
        pop bc
        ld e,c
        ld d,0
        add hl,de
        dec hl                  ; real -> logical
        pop de
        ret

;------------------------------------------------------------------------------
; od_read  - HL = first block, B = count (1..255), DE = destination,
;            (od_tail) = bytes wanted from the last block (0 = whole block).
; od_write - same, writes whole blocks (needs OD_SAVE).
; Drive = (od_unit). Out: NC ok, DE after the data; CY error, A = status.
; Pages the Opus in and out itself. Returns with DI. Clears od_tail.
;------------------------------------------------------------------------------
        IF OD_SAVE
od_write:
        ld a,#A0
        jr od_rw
        ENDIF
od_read:
        ld a,#80
od_rw:  call OD_PAGEIN
        di
        push af
        call od_init
        pop af
        call od_rwin
        jp OD_PAGEOUT           ; flags survive (RET at #1748)

; paged-in core of od_read / od_write: A = #80 / #A0
od_rdin:
        ld a,#80
od_rwin:
        ld (od_op),a
        call od_blocks
        push af
        xor a
        ld (od_tail),a
        ld (od_tail+1),a
        pop af
        ret

; wrapper for the file routines: page in, init, run (IX), page out.
; The routine runs entirely paged in, so its buffer may be in the Opus RAM.
od_paged:
        call OD_PAGEIN
        di
        call od_init
        push hl
        ld hl,(od_buf)          ; a buffer at all?
        ld a,h
        or l
        pop hl
        ld a,#FE
        scf
        jr z,.out
        call .go
.out:   jp OD_PAGEOUT
.go:    jp (ix)

; od_cnt16 for a sector: whole, or (od_tail) for the last one. A = 1 if last.
od_setcnt:
        or a
        ld hl,0
        jr z,.set
        ld hl,(od_tail)
.set:   ld (od_cnt16),hl
        ret

        IF OD_FAST = 0
;--- compact: sector IDs in ascending order -----------------------------------
od_blocks:
.lp:    push bc
        push hl
        ld a,b
        dec a
        jr z,$+4
        ld a,1                  ; A = 0 on the last block ...
        xor 1                   ; ... -> 1
        call od_setcnt
        pop hl
        push hl
        call od_b2p
        push bc
        ld c,a
        ld a,(od_unit)
        call od_select
        pop bc
        ld a,(od_op)
        call od_xsec
        pop hl
        pop bc
        ret c
        inc hl
        djnz .lp
        ret
        ELSE
;--- fast: per track, sectors in rotational order -----------------------------
; Read Address finds where the head is and (once per call) the sector step of
; the format (Opus ROM format: 0,7,14,3,... = step 7 for 18x256 and 10x512);
; then every needed sector of the track is read as it comes under the head:
; ~1 revolution per track.
od_blocks:
        ld a,b
        ld (od_cnt),a
        ld (od_dst),de
        ld (od_blk),hl
.track: ld hl,(od_blk)
        call od_b2p             ; B=track C=first sector A=side
        ld (od_trk),bc          ; +0 first sector, +1 track
        push bc
        ld c,a
        ld a,(od_unit)
        call od_select
        pop bc
        ld d,b
        call od_seek
        ret c
        ; sectors on this track: n = min(count, spt - first)
        ld a,(od_trk)
        ld c,a
        ld a,(od_spt)
        sub c
        ld b,a
        ld a,(od_cnt)
        cp b
        jr c,.nok
        ld a,b
.nok:   ld (od_n),a
        ; mark need[]
        ld hl,od_need
        ld a,(od_spt)
        ld b,a
.clr:   ld (hl),0
        inc hl
        djnz .clr
        ld hl,od_need
        ld a,(od_trk)
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        ld a,(od_n)
        ld b,a
.mark:  ld (hl),1
        inc hl
        djnz .mark
        ; where are we? (also measures the step once per call)
        call od_raddr
        ret c
        ld a,(od_step)
        or a
        jr nz,.havestep
        ld a,(od_id)
        ld c,a
        push bc
        call od_raddr
        pop bc
        ret c
        ld a,(od_spt)
        ld b,a
        ld a,(od_id)
        sub c
        jr nc,$+3
        add a,b
        or a
        jr nz,$+4
        ld a,1                  ; could not tell (emulator): sequential
        ld (od_step),a
.havestep:
        ld a,OD_RETRY*OD_MAXSPT
        ld (od_guard),a
        ld a,(od_n)
        ld (od_left),a
        ld a,(od_id)
        ld c,a                  ; C = current sector
.next:  ld a,(od_spt)
        ld b,a
        ld a,(od_step)
        add a,c
        cp b
        jr c,$+3
        sub b
        ld c,a
        ld hl,od_need
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        ld a,(hl)
        or a
        jr z,.next              ; not needed (or done): next slot
        push hl                 ; need[] entry
        ld a,c
        ld (od_curs),a
        ; last sector of the whole call?  (this track is the final part and
        ; sector - first = n - 1)
        ld a,(od_trk)
        ld b,a
        ld a,c
        sub b
        ld e,a                  ; E = sector - first
        ld a,(od_n)
        ld b,a
        ld a,(od_cnt)
        cp b
        ld a,0
        jr nz,.nl
        ld a,e
        inc a
        cp b
        ld a,1
        jr z,.nl
        xor a
.nl:    call od_setcnt          ; od_cnt16 = tail or 0 (whole)
        ld a,e                  ; DE = dst + (sector - first) * sector size
        call od_mulspg
        ld de,(od_dst)
        add a,d
        ld d,a
        ld bc,(od_cnt16)
        ld a,b
        or c
        call z,od_secsize
        ld a,(od_curs)
        call od_xfer
        pop hl
        push af
        ld a,(od_curs)
        ld c,a
        pop af
        jr c,.err
        ld (hl),0               ; done
        ld a,(od_left)
        dec a
        ld (od_left),a
        jr nz,.next
        ; track finished: advance
        ld a,(od_n)
        call od_mulspg
        ld hl,(od_dst)
        add a,h
        ld h,a
        ld (od_dst),hl
        ld a,(od_n)
        ld b,a
        ld hl,(od_blk)
        ld e,b
        ld d,0
        add hl,de
        ld (od_blk),hl
        ld a,(od_cnt)
        sub b
        ld (od_cnt),a
        jp nz,.track
        ld de,(od_dst)          ; (last sector may be partial: DE = end of
        ret                     ;  the last whole sector)
.err:   ld b,a
        bit 6,a                 ; write protect: give up at once
        jr z,.e1
        ld a,(od_op)
        cp #80
        ld a,b
        scf
        ret nz
.e1:    ld a,(od_guard)
        dec a
        ld (od_guard),a
        ld a,b
        scf
        ret z                   ; too many failures
        and #10
        jp z,.next
        push bc                 ; RNF: re-seek
        call od_restore
        ld a,(od_trk+1)
        ld d,a
        call od_seek
        pop bc
        jp .next

; Read Address: 6 ID bytes -> od_idbuf; od_id = sector byte. NC ok.
od_raddr:
        push hl
        ld hl,(od_hrd)
        ld de,od_idbuf
        ld bc,6
        ld a,#C0
        call od_cmd
        pop hl
        ret c
        and #18
        scf
        ret nz
        ld a,(od_idbuf+2)
        ld (od_id),a
        or a
        ret

od_cnt   db 0
od_n     db 0
od_left  db 0
od_guard db 0
od_id    db 0
od_curs  db 0
od_trk   dw 0                   ; +0 first sector, +1 track
od_dst   dw 0
od_blk   dw 0
od_idbuf ds 6
od_need  ds OD_MAXSPT
        ENDIF

; A = A * sector pages (1, 2 or 4). Keeps BC, DE, HL.
od_mulspg:
        push bc
        ld c,a
        ld a,(od_spg)
        ld b,a
        ld a,c
.m:     srl b
        jr z,.done
        add a,a
        jr .m
.done:  pop bc
        ret

        IF OD_FILES
;------------------------------------------------------------------------------
; File routines. Each public entry pages the Opus in, runs the "_in" version
; entirely paged in (so the sector buffer may live in the Opus RAM) and pages
; out. Without Opus RAM and without OD_BUF they return CY, A = #FE.
;------------------------------------------------------------------------------

; od_geom - read the anchor sector (track 0, side 0, sector 0) of (od_unit)
; and set od_tps / od_spt / od_spg from its bytes 2,3,4 (tracks, sectors,
; flags: b7-6 size 01=256 10=512 11=1024, b4 two sides). Only 5 bytes are
; stored. Out: NC ok, A = flags; CY error.
od_geom:
        ld ix,od_geom_in
        jp od_paged

; od_find - HL -> 10-char name (space padded).
; Out: NC found: HL = first block, DE = last block, A = bytes in last block - 1
;      (low byte); CY not found / error.
od_find:
        ld ix,od_find_in
        jp od_paged

; od_load - load a file by name, byte-exact.
; In: HL -> name (10 chars), DE = address (0 = the address in the header).
; Out: NC ok, HL = length, DE = start address, A = file type; CY error.
; Nothing outside [address, address+length) is written: the first block (with
; the 7-byte header) goes through the buffer, the rest straight to memory,
; the last block cut to the exact length.
od_load:
        ld ix,od_load_in
        jp od_paged

        IF OD_SAVE
; od_save - overwrite an EXISTING file in place (save-game slots etc).
; In: HL -> name, DE = address, BC = length. The file must already have
; enough blocks for 7 + length bytes. Writes a CODE header (type 3, length,
; address). The catalog is not changed. Memory is only read, never written.
; Out: NC ok / CY error (A=#FF: file too small).
od_save:
        ld ix,od_save_in
        jp od_paged
        ENDIF

;--- paged-in versions --------------------------------------------------------
od_geom_in:
        ld a,(od_unit)
        ld c,0
        call od_select
        ld hl,5
        ld (od_cnt16),hl
        ld bc,0                 ; track 0, sector 0
        ld de,(od_buf)
        call od_rsec
        push af
        ld hl,0
        ld (od_cnt16),hl
        pop af
        ret c
        ld ix,(od_buf)
        ld a,(ix+4)
        and #C0
        scf
        ret z                   ; 128-byte sectors: not supported
        rlca
        rlca                    ; 1, 2, 3
        cp 3
        jr nz,$+4
        ld a,4
        ld (od_spg),a
        ld a,(ix+2)
        ld (od_tps),a
        ld a,(ix+3)
        ld (od_spt),a
        ld a,(ix+4)
        or a
        ret

od_find_in:
        ld (od_fname),hl
        ld hl,0
.blk:   push hl
        ld de,(od_buf)
        ld b,1
        call od_rdin
        pop hl
        ret c
        push hl
        ld ix,(od_buf)
        ld a,h
        or l
        jr nz,.nb0
        ld a,(ix+4)             ; entry 0: last block of the catalog
        ld (od_catend),a
.nb0:   ld a,(od_spg)
        rlca
        rlca
        rlca
        rlca
        ld b,a                  ; entries per block = size/16
.ent:   ld a,(ix+5)             ; end block = #FFFF: end marker
        and (ix+4)
        inc a
        jr z,.notf
        push bc
        ld de,(od_fname)
        push ix
        pop hl
        ld bc,6
        add hl,bc
        ld b,10
.cmp:   ld a,(de)
        cp (hl)
        jr nz,.nx
        inc de
        inc hl
        djnz .cmp
        pop bc                  ; found
        pop hl
        ld (od_fcblk),hl        ; (the catalogue block stays in the buffer, IX -> entry)
        ld a,(ix+1)
        ld (od_flast+1),a
        ld a,(ix+0)
        ld (od_flast),a
        ld l,(ix+2)
        ld h,(ix+3)
        ld e,(ix+4)
        ld d,(ix+5)
        ld a,(ix+0)
        or a
        ret
.nx:    pop bc
        ld de,16
        add ix,de
        djnz .ent
        pop hl
        ld a,(od_catend)
        cp l
        inc hl
        jr nz,.blk
        scf
        ret
.notf:  pop hl
        scf
        ret

od_fname  dw 0
od_catend db 6
od_fcblk  dw 0                  ; od_find: catalogue block of the entry found
od_flast  dw 0                  ; od_find: bytes in the last block - 1 (word)

; HL = byte count -> HL = blocks (rounded up), DE = bytes in the last block
; (0 if it is full). Uses A.
od_bytes2blk:
        ld a,(od_spg)
        dec a
        and h                   ; high bits of (count mod size)
        ld d,a
        ld e,l
        ld a,l                  ; HL = ceil(count / 256) pages
        or a
        jr z,$+3
        inc h
        ld l,h
        ld h,0
        ld a,(od_spg)
.pg:    rra                     ; / spg, rounding up
        ret c
        inc hl
        srl h
        rr l
        jr .pg

; HL = sector size - 7 (bytes of file data in the first block)
od_first:
        ld a,(od_spg)
        ld h,a
        ld l,0
        ld a,l
        sub 7
        ld l,a
        dec h
        ret

; BC = min(length, size - 7) -> od_lchunk;  DE = buffer + 7
od_chunk:
        call od_first
        ld de,(od_llen)
        or a
        sbc hl,de
        add hl,de
        jr c,.big               ; size-7 < length
        ex de,hl                ; the whole file fits in the first block
.big:   ld b,h
        ld c,l
        ld (od_lchunk),bc
        ld hl,(od_buf)
        ld de,7
        add hl,de
        ex de,hl
        ret

od_load_in:
        ld (od_ldst),de
        call od_find_in
        ret c
        ld (od_lfirst),hl
        ld de,(od_buf)
        ld b,1
        call od_rdin            ; first block -> buffer
        ret c
        ld ix,(od_buf)
        ld a,(ix+0)
        ld (od_ltype),a
        ld l,(ix+1)
        ld h,(ix+2)
        ld (od_llen),hl
        ld hl,(od_ldst)
        ld a,h
        or l
        jr nz,.addr
        ld l,(ix+3)
        ld h,(ix+4)
        ld (od_ldst),hl
.addr:  call od_chunk           ; BC = chunk, DE = buffer + 7
        ld a,b
        or c
        jr z,.nocpy
        ex de,hl
        ld de,(od_ldst)
        ldir
.nocpy: ld hl,(od_llen)         ; the rest: length - chunk
        ld de,(od_lchunk)
        or a
        sbc hl,de
        jr z,.done
        call od_bytes2blk       ; HL = blocks, DE = tail bytes
        ld (od_tail),de
        ld b,l
        ld hl,(od_ldst)
        ld de,(od_lchunk)
        add hl,de
        ex de,hl                ; DE = where the 2nd block goes
        ld hl,(od_lfirst)
        inc hl
        call od_rdin
        ret c
.done:  ld hl,(od_llen)
        ld de,(od_ldst)
        ld a,(od_ltype)
        or a                    ; NC
        ret

od_ldst   dw 0
od_lfirst dw 0
od_llen   dw 0
od_lchunk dw 0
od_ltype  db 0

;------------------------------------------------------------------------------
; RAW FILES: everything about the file is in its catalogue entry (first / last
; block, bytes in the last block); the data start at the first byte of the first
; block - no 7-byte header. A 6912-byte screen takes 27 blocks of 256, not 28.
; The ROM lists them (CAT) but cannot LOAD them; these routines can.
;------------------------------------------------------------------------------
        IF OD_RAW
; od_rload - load a raw file by name, all of it, byte-exact.
; In: HL -> name (10 chars), DE = address. Out: NC ok, HL = length, DE = address;
; CY error (A = #FF: longer than 255 blocks). Nothing after the data is written.
od_rload:
        ld ix,od_rload_in
        jp od_paged

        IF OD_SAVE
; od_rsave - save BC bytes (1..65535) at DE as the raw file HL -> name.
; The file exists and has blocks enough: overwritten in place, its length in the
; catalogue updated (blocks it no longer needs become free). It does not exist:
; created in the first gap of the disk that is big enough (the catalogue entries
; after it move one place on). Memory is only read.
; Out: NC ok, HL = first block; CY error: A = #FF the existing file is too small,
; #FD no room on the disk, #FC the catalogue is full, else the FDC status.
od_rsave:
        ld ix,od_rsave_in
        jp od_paged
        ENDIF

od_rload_in:
        ld (od_ldst),de
        call od_find_in
        ret c
        ld (od_lfirst),hl
        ex de,hl
        or a
        sbc hl,de               ; blocks - 1
        ld a,h
        or a
        jr nz,.big
        ld a,l
        inc a
        jr z,.big
        push af                 ; A = blocks
        ld h,l                  ; length = (blocks - 1) * size + last + 1
        ld l,0
        ld a,(od_spg)
.mul:   rra
        jr c,.m1
        add hl,hl
        jr .mul
.m1:    ld de,(od_flast)
        inc de
        add hl,de
        ld (od_llen),hl
        call od_last2tail       ; od_tail = bytes of the last block (0 = whole)
        pop af
        ld b,a                  ; B = blocks
        ld hl,(od_lfirst)
        ld de,(od_ldst)
        call od_rdin
        ret c
        ld hl,(od_llen)
        ld de,(od_ldst)
        or a
        ret
.big:   ld a,#FF
        scf
        ret

; DE = last + 1 -> od_tail (0 when the last block is full)
od_last2tail:
        ld a,(od_spg)
        cp d
        jr nz,.t
        ld a,e
        or a
        jr nz,.t
        ld d,a                  ; = the sector size: whole
.t:     ld (od_tail),de
        ret

        IF OD_SAVE
od_rsave_in:
        ld (od_fname),hl
        ld (od_ldst),de
        ld (od_llen),bc
        ld h,b
        ld l,c
        call od_bytes2blk       ; HL = blocks needed, DE = bytes in the last (0 = full)
        ld (od_cneed),hl
        ld a,d
        or e
        jr nz,.l1
        ld a,(od_spg)
        ld d,a                  ; full: last + 1 = size
.l1:    dec de
        ld (od_nlast),de        ; the new "bytes in the last block - 1"
        ld a,h
        or a
        ld a,#FF
        scf
        ret nz                  ; > 255 blocks
        ld hl,(od_fname)
        call od_find_in
        jr c,.new
        ld (od_lfirst),hl       ; exists: room?
        ex de,hl
        or a
        sbc hl,de
        inc hl                  ; blocks it has
        ld de,(od_cneed)
        or a
        sbc hl,de
        ld a,#FF
        ret c
        ld hl,(od_nlast)        ; the new length in the entry (still in the buffer, IX -> entry)
        ld (ix+0),l
        ld (ix+1),h
        ld hl,(od_lfirst)
        add hl,de
        dec hl
        ld (ix+4),l
        ld (ix+5),h
        ld hl,(od_fcblk)
        ld de,(od_buf)
        ld b,1
        ld a,#A0
        call od_rwin
        ret c
        jr .data
.new:   call od_create_in       ; (a read error shows up again there)
        ret c
.data:  ld a,(od_cneed)
        ld b,a
        ld hl,(od_lfirst)
        ld de,(od_ldst)
        ld a,#A0
        call od_rwin            ; whole blocks: memory after the data is read, never written
        ret c
        ld hl,(od_lfirst)
        ret

; a new entry: name (od_fname), od_cneed blocks, od_nlast -> od_lfirst; NC ok
od_create_in:
        xor a
        ld (od_cfound),a
        ld hl,0
.blk:   ld (od_cblk),hl
        ld de,(od_buf)
        ld b,1
        call od_rdin
        ret c
        ld ix,(od_buf)
        call .epb               ; B = entries per block
        ld hl,(od_cblk)
        ld a,h
        or l
        jr nz,.ent
        ld a,(ix+4)             ; entry 0: the last block of the catalogue = the end of "file 0"
        ld (od_catend),a
        ld l,(ix+4)
        ld h,(ix+5)
        ld (od_cprev),hl
        ld de,16
        add ix,de
        dec b
.ent:   ld a,(od_cfound)
        or a
        jr nz,.cnt
        ld l,(ix+2)             ; the gap before this entry: first - prev - 1 >= need?
        ld h,(ix+3)
        ld de,(od_cprev)
        scf
        sbc hl,de
        ld de,(od_cneed)
        sbc hl,de
        jr c,.cnt
        ld a,1
        ld (od_cfound),a
        ld hl,(od_cblk)
        ld (od_ciblk),hl
        push ix
        pop hl
        ld de,(od_buf)
        or a
        sbc hl,de
        ld (od_cioff),hl
        ld hl,(od_cprev)
        inc hl
        ld (od_lfirst),hl
.cnt:   ld a,(ix+4)
        and (ix+5)
        inc a
        jr z,.sent              ; the end marker
        ld l,(ix+4)
        ld h,(ix+5)
        ld (od_cprev),hl
        ld de,16
        add ix,de
        djnz .ent
        ld hl,(od_cblk)
        ld a,(od_catend)
        cp l
        jr z,.full
        inc hl
        jp .blk
.sent:  ld a,(od_cfound)
        or a
        ld a,#FD
        scf
        ret z                   ; no gap big enough
        dec b
        jr nz,.room             ; a free slot after the marker in this block
        ld hl,(od_cblk)
        ld a,(od_catend)
        cp l
        jr nz,.room
.full:  ld a,#FC
        scf
        ret
.room:  ld ix,od_carry          ; the new entry
        ld hl,(od_nlast)
        ld (ix+0),l
        ld (ix+1),h
        ld hl,(od_lfirst)
        ld (ix+2),l
        ld (ix+3),h
        ld de,(od_cneed)
        add hl,de
        dec hl
        ld (ix+4),l
        ld (ix+5),h
        ld hl,(od_fname)
        ld de,od_carry+6
        ld bc,10
        ldir
        ld hl,(od_ciblk)        ; insert: every entry from there moves one place on
        ld de,(od_cioff)
.ib:    ld (od_cblk),hl
        push de
        ld de,(od_buf)
        ld b,1
        call od_rdin
        pop de
        ret c
        call .epb
        ld a,e                  ; entries left in this block = per block - offset / 16
        rrca
        rrca
        rrca
        rrca
        and #0F
        ld c,a
        ld a,d
        rlca
        rlca
        rlca
        rlca
        or c
        neg
        add a,b
        ld b,a
        ld hl,(od_buf)
        add hl,de
.sw:    push bc
        ld de,od_carry          ; swap the 16 bytes at HL with od_carry
        ld b,16
.sx:    ld a,(de)
        ld c,(hl)
        ld (hl),a
        ld a,c
        ld (de),a
        inc hl
        inc de
        djnz .sx
        pop bc
        ld de,-11               ; was the entry just put there the end marker? (end = +4, +5)
        add hl,de
        ld a,(hl)
        dec hl
        and (hl)
        ld de,12
        add hl,de
        inc a
        jr z,.last
        djnz .sw
        call .wr
        ret c
        ld hl,(od_cblk)
        ld a,(od_catend)        ; (never past the catalogue; the room was checked)
        cp l
        ld a,#FC
        scf
        ret z
        inc hl
        ld de,0
        jp .ib
.last:  call .wr
        ret c
        ld hl,(od_lfirst)
        or a
        ret
.wr:    ld hl,(od_cblk)
        ld de,(od_buf)
        ld b,1
        ld a,#A0
        jp od_rwin
.epb:   ld a,(od_spg)           ; B = entries per block (size / 16)
        rlca
        rlca
        rlca
        rlca
        ld b,a
        ret

od_cneed  dw 0
od_nlast  dw 0                  ; od_rsave: bytes in the new last block - 1
od_cprev  dw 0
od_cblk   dw 0
od_ciblk  dw 0
od_cioff  dw 0
od_cfound db 0
od_carry  ds 16
        ENDIF
        ENDIF

        IF OD_SAVE
od_save_in:
        ld (od_ldst),de
        ld (od_llen),bc
        call od_find_in
        ret c
        ld (od_lfirst),hl
        ex de,hl
        or a
        sbc hl,de
        inc hl                  ; blocks available
        push hl
        ld hl,(od_llen)
        ld de,7
        add hl,de
        call od_bytes2blk       ; HL = blocks needed
        ex de,hl
        pop hl
        or a
        sbc hl,de
        ld a,#FF
        ret c
        ld ix,(od_buf)          ; first block: header + data in the buffer
        ld (ix+0),3
        ld hl,(od_llen)
        ld (ix+1),l
        ld (ix+2),h
        ld hl,(od_ldst)
        ld (ix+3),l
        ld (ix+4),h
        ld (ix+5),0
        ld (ix+6),#80
        call od_chunk           ; BC = chunk, DE = buffer + 7
        ld a,b
        or c
        jr z,.nocpy
        ld hl,(od_ldst)
        ldir
.nocpy: ld hl,(od_lfirst)
        ld de,(od_buf)
        ld b,1
        ld a,#A0
        call od_rwin
        ret c
        ld hl,(od_llen)
        ld de,(od_lchunk)
        or a
        sbc hl,de
        ret z
        call od_bytes2blk
        ld b,l
        ld hl,(od_ldst)
        ld de,(od_lchunk)
        add hl,de
        ex de,hl
        ld hl,(od_lfirst)
        inc hl
        ld a,#A0
        jp od_rwin              ; (writes whole blocks: reads, never writes,
                                ;  up to a sector beyond the data)
        ENDIF
        ENDIF
