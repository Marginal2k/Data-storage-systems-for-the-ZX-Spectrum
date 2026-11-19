"""128K helpers for the ZX-M8XXX tests: the 128K menu, entering 128 BASIC, typing a command there."""


def menu_rows(zx):
    """Rows of the 128K menu box whose attribute has cyan paper (the highlight)."""
    attrs = zx.peek(0x5800, 768)
    return [r for r in range(24) if (attrs[r * 32 + 14] & 0x38) == 0x28]


def boot_128basic(zx):
    """128K menu -> 128 BASIC: press DOWN until the highlight sits one row below where
    it started (Tape Loader -> 128 BASIC), then ENTER. Not "48 BASIC": that option
    locks the paging port, so the game would rightly see a 48K machine."""
    zx.frames(200)
    start = None
    for _ in range(40):
        rows = menu_rows(zx)
        if rows:
            start = rows[0]
            break
        zx.frames(10)
    for _ in range(10):
        if start is not None and menu_rows(zx)[:1] == [start + 1]:
            break
        zx.key('ArrowDown', frames=10)
        zx.frames(25)
    zx.key('Enter', frames=10)
    zx.frames(150)


def enter_128basic(zx, insert=None):
    """128K menu -> 128 BASIC, (insert the disk: that may reset the machine), and make sure we are in 128 BASIC
    (the menu walk of the harness sometimes lands on Tape Loader): retry from a reset"""
    for attempt in range(4):
        boot_128basic(zx)
        if insert:
            insert()
            zx.frames(20)
            if menu_rows(zx) or zx.js('zxDebug.captureRegisters().pc') < 0x100:
                boot_128basic(zx)
        zx.frames(150)                  # (an inserted image may reset the machine a little later)
        txt = zx.screen_text()
        if not menu_rows(zx) and 'Tape Loader' not in txt and 'Calculator' not in txt:
            return True
        zx.reset()
        zx.frames(50)
    return False


def command_128(zx, typer):
    """Type a command in 128 BASIC (typer() types it without ENTER) and press ENTER - but only when the
    128K menu is not on the screen: M8XXX sometimes drops back to the menu after 128 BASIC was entered,
    and ENTER would then start the Tape Loader. If the menu is there: into 128 BASIC again, type again."""
    for attempt in range(4):
        typer()
        zx.frames(30)
        if not menu_rows(zx):
            zx.type(chr(10), hold=6, gap=6)
            return True
        boot_128basic(zx)
        zx.frames(30)
    return False
