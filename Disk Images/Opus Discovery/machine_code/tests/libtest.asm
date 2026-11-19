; test build of opuslib: entry points are found via the .sym file
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

        ORG #6000
        DEFINE OD_BUF #7800
        INCLUDE "../src/opuslib.asm"
lib_end:
        SAVEBIN "libtest.bin",#6000,#2000
