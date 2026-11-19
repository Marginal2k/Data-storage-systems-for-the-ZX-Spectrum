; Demo "game" for the monoblock example: shows that control arrives at START
; with the screen already loaded. Sets a marker, cycles the border.
        DEVICE ZXSPECTRUM48
        ORG #8000
start:  ld a,#5A
        ld (marker),a           ; test harness checks this
        ei
.loop:  ld a,(marker+1)
        inc a
        ld (marker+1),a
        and 7
        out (#FE),a
        halt
        jr .loop
marker: db 0,0
        SAVEBIN "demo.bin", start, $ - start
