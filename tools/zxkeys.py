"""Turn a 48K BASIC line ("LOAD *\"m\";1;\"run\"") into 48K keystrokes (chords).

The 48K editor is keyword-entry: the first keyword of a statement is a single key
in K mode, other keywords live in E mode (CAPS+SYM, then a key) or behind SYM.
"""
import re

K_MODE = {  # keyword -> key in K mode
    'NEW': 'a', 'BORDER': 'b', 'CONTINUE': 'c', 'DIM': 'd', 'REM': 'e', 'FOR': 'f',
    'GO TO': 'g', 'GO SUB': 'h', 'INPUT': 'i', 'LOAD': 'j', 'LIST': 'k', 'LET': 'l',
    'PAUSE': 'm', 'NEXT': 'n', 'POKE': 'o', 'PRINT': 'p', 'PLOT': 'q', 'RUN': 'r',
    'SAVE': 's', 'RANDOMIZE': 't', 'IF': 'u', 'CLS': 'v', 'DRAW': 'w', 'CLEAR': 'x',
    'RETURN': 'y', 'COPY': 'z',
}
E_MODE = {  # E mode, unshifted
    'READ': 'a', 'BIN': 'b', 'LPRINT': 'c', 'DATA': 'd', 'TAN': 'e', 'SGN': 'f', 'ABS': 'g',
    'SQR': 'h', 'CODE': 'i', 'VAL': 'j', 'LEN': 'k', 'USR': 'l', 'PI': 'm', 'INKEY$': 'n',
    'PEEK': 'o', 'TAB': 'p', 'SIN': 'q', 'COS': 'w', 'INT': 'r', 'RND': 't', 'STR$': 'y',
    'CHR$': 'u', 'LLIST': 'v', 'EXP': 'x', 'LN': 'z',
}
E_SYM = {  # E mode + SYM
    'ASN': 'q', 'ACS': 'w', 'ATN': 'e', 'VERIFY': 'r', 'MERGE': 't', 'IN': 'i', 'OUT': 'o',
    'RESTORE': 's', 'CIRCLE': 'h', 'VAL$': 'j', 'SCREEN$': 'k', 'ATTR': 'l', 'BEEP': 'z',
    'INK': 'x', 'PAPER': 'c', 'FLASH': 'v', 'BRIGHT': 'b', 'OVER': 'n', 'INVERSE': 'm',
    'DEF FN': '1', 'FN': '2', 'LINE': '3', 'OPEN #': '4', 'CLOSE #': '5', 'MOVE': '6',
    'ERASE': '7', 'POINT': '8', 'CAT': '9', 'FORMAT': '0',
}
L_SYM = {  # SYM + key in L mode (keyword tokens)
    'STOP': 'a', 'NOT': 's', 'STEP': 'd', 'TO': 'f', 'THEN': 'g', 'AND': 'y', 'OR': 'u',
    'AT': 'i', '<=': 'q', '<>': 'w', '>=': 'e',
}
SYM_CHARS = {
    ';': 'o', '"': 'p', ':': 'z', ',': 'n', '.': 'm', '=': 'l', '+': 'k', '-': 'j',
    '*': 'b', '/': 'v', '<': 'r', '>': 't', '^': 'h', '?': 'c', '!': '1', '@': '2',
    '#': '3', '$': '4', '%': '5', '&': '6', "'": '7', '(': '8', ')': '9', '_': '0',
}

ALL_KW = sorted(set(K_MODE) | set(E_MODE) | set(E_SYM) | set(L_SYM), key=len, reverse=True)


def keyname(c):
    if c.isdigit():
        return 'Digit' + c
    return 'Key' + c.upper()


def chords(line):
    """List of chords (each a list of ULA key names)."""
    out = []
    i, kmode, in_str = 0, True, False
    while i < len(line):
        c = line[i]
        if in_str:
            if c == '"':
                in_str = False
                out.append(['SYM', 'KeyP'])
            elif c == ' ':
                out.append(['Space'])
            elif c.isalpha() and c.isupper():
                out.append(['CAPS', keyname(c)])
            elif c.isalnum():
                out.append([keyname(c)])
            elif c in SYM_CHARS:
                out.append(['SYM', keyname(SYM_CHARS[c])])
            else:
                raise ValueError('cannot type %r' % c)
            i += 1
            continue
        if c == ' ':
            i += 1; continue
        kw = None
        for k in ALL_KW:
            if line.startswith(k, i) and (not k[-1].isalpha() or i + len(k) >= len(line)
                                          or not line[i + len(k)].isalpha()):
                kw = k; break
        if kw:
            if kmode and kw in K_MODE:
                out.append([keyname(K_MODE[kw])])
            elif kw in E_MODE:
                out.append(['CAPS', 'SYM']); out.append([keyname(E_MODE[kw])])
            elif kw in E_SYM:
                out.append(['CAPS', 'SYM']); out.append(['SYM', keyname(E_SYM[kw])])
            elif kw in L_SYM:
                out.append(['SYM', keyname(L_SYM[kw])])
            else:
                raise ValueError('keyword %s not valid here' % kw)
            kmode = kw == 'THEN'
            i += len(kw)
            continue
        if c == '"':
            in_str = True
            out.append(['SYM', 'KeyP'])
        elif c == ':':
            out.append(['SYM', 'KeyZ']); kmode = True; i += 1; continue
        elif c.isdigit():
            out.append([keyname(c)])
            i += 1
            continue  # line number keeps K mode
        elif c.isalpha():
            out.append(['CAPS', keyname(c)] if c.isupper() else [keyname(c)])
        elif c in SYM_CHARS:
            out.append(['SYM', keyname(SYM_CHARS[c])])
        else:
            raise ValueError('cannot type %r' % c)
        kmode = False
        i += 1
    out.append(['Enter'])
    return out
