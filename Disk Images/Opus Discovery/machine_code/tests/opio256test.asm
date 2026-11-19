; test build of the 180K / 720K driver src/opio256.asm (all three pieces, the hole saved and restored)
        DEVICE ZXSPECTRUM48
        ORG #7F00
done:   push af
        ld (res_hl),hl
        ld (res_de),de
        ld (res_bc),bc
        pop hl
        ld (res_af),hl
        ld a,#AA
        ld (res_flag),a
        jr $
res_af  dw 0
res_hl  dw 0
res_de  dw 0
res_bc  dw 0
res_flag db 0

RD_TS   equ #7E00
RD_BUF  equ #7E02
RD_N    equ #7E04
G_VARS  equ #7E10
OP_SAVE equ #7E30
OP_HOLE equ #BFE0

        ORG #8000
        DEFINE OPIO_SAVE
        DEFINE OPIO_CORE
        INCLUDE "../src/opio256.asm"
        DEFINE OPIO_IO
        INCLUDE "../src/opio256.asm"
        DEFINE OPIO_BOOT
        INCLUDE "../src/opio256.asm"
opio_end:
        DISPLAY "opio256: ", /D, opio_end - #8000, " bytes"
        SAVEBIN "opio256test.bin", #7F00, opio_end - #7F00
