#!/usr/bin/env python3
"""Annotated hex dump of a CEPT byte stream.

A Python port of bildschirmtext/tools/decode_cept.c
(https://github.com/bildschirmtext/bildschirmtext) with the same output format:
16 hex bytes per line, then "# description" on the first line of each sequence.
Unlike the C tool, it never reads past the end of the input.

Usage: cept_annotate.py page.cept [> page.txt]
"""
import sys

HEX_PER_LINE = 16

C0 = {0x08: "cursor left", 0x09: "cursor right", 0x0A: "cursor down", 0x0B: "cursor up",
      0x0C: "clear screen", 0x0D: "cursor to beginning of line",
      0x0E: "G1 into left charset", 0x0F: "G0 into left charset",
      0x11: "show cursor", 0x14: "hide cursor", 0x18: "clear line",
      0x19: "switch to G2 for one character", 0x1A: "end of page",
      0x1D: "switch to G3 for one character", 0x1E: "cursor home"}
C1 = {0x88: "blink on", 0x89: "blink off", 0x8A: "transparency on", 0x8B: "transparency off",
      0x8C: "normal size", 0x8D: "double height", 0x8E: "double width",
      0x8F: "double width and height", 0x98: "hide", 0x99: "underline off", 0x9A: "underline on",
      0x9C: "Hintergrundfarbe schwarz bzw. normale Polarita\u0308t",
      0x9D: "Hintergrundfarbe setzen bzw. inverse Polarita\u0308t",
      0x9E: "Mosaikzeichenwiederholung bzw. Hintergrund transparent"}
CSI = {(0x30, 0x40): "select palette #0", (0x30, 0x41): "invert blinking",
       (0x31, 0x40): "select palette #1", (0x31, 0x41): "blink palettes 0/1 or 2/3",
       (0x31, 0x51): "unprotect line", (0x31, 0x50): "protect line",
       (0x32, 0x40): "select palette #2", (0x32, 0x41): "fast blinking (on, off, off)",
       (0x32, 0x53): "start selection", (0x32, 0x54): "end selection",
       (0x33, 0x40): "select palette #3", (0x33, 0x41): "fast blinking (off, on, off)",
       (0x34, 0x41): "fast blinking (off, off, on)", (0x35, 0x41): "blinking shift right",
       (0x36, 0x41): "blinking shift left"}
SETS = {0x40: "G0", 0x62: "G2", 0x63: "G1", 0x64: "G3"}
TARGET = {0x28: "G0", 0x29: "G1", 0x2A: "G2", 0x2B: "G3"}
SHIFTS = {0x6E: "G2 into left charset", 0x6F: "G3 into left charset",
          0x7C: "G3 into right charset", 0x7D: "G2 into right charset",
          0x7E: "G1 into right charset"}
RES = {6: "12x12", 7: "12x10", 0xA: "6x12", 0xB: "6x10", 0xC: "6x5", 0xF: "6x6"}
COLS = {1: 2, 2: 4, 4: 16}


def printable(c):
    return 0x20 <= c <= 0x7F or c >= 0xA0


def ch(c):
    return chr(c) if c < 0x80 else "."


def palette(data):
    out = []
    for i in range(0, len(data) - 1, 2):
        a, b = data[i], data[i + 1]
        r = (b >> 2 & 1) | (b >> 5 & 1) << 1 | (a >> 2 & 1) << 2 | (a >> 5 & 1) << 3
        g = (b >> 1 & 1) | (b >> 4 & 1) << 1 | (a >> 1 & 1) << 2 | (a >> 4 & 1) << 3
        bl = (b & 1) | (b >> 3 & 1) << 1 | (a & 1) << 2 | (a >> 3 & 1) << 3
        out.append(f'"#{r:x}{g:x}{bl:x}"')
    return ", ".join(out)


def describe(buf, i):
    """Return (length, description) of the sequence starting at buf[i]."""
    n = len(buf)

    def p(k):
        return buf[i + k] if i + k < n else 0

    def until_us(start):
        q = i + start
        while q < n and buf[q] != 0x1F:
            q += 1
        return q - i

    b0, b1, b2, b3 = p(0), p(1), p(2), p(3)
    if printable(b0) and b1 == 0x12 and b2 >= 0x41:
        return 3, f"repeat '{ch(b0)}' {b2 - 0x40} times"
    if b0 in C0:
        return 1, C0[b0]
    if b0 == 0x1B:
        if b1 == 0x22 and b2 in (0x40, 0x41):
            return 3, "serial mode" if b2 == 0x40 else "parallel mode"
        if b1 == 0x23 and b2 == 0x20 and b3 & 0xF0 == 0x50:
            return 4, f"set bg color of screen to {b3 - 0x50}"
        if b1 == 0x23 and b2 == 0x21 and b3 & 0xF0 == 0x40:
            return 4, f"set fg color of line to {b3 - 0x40}"
        if b1 == 0x23 and b2 == 0x21 and b3 & 0xF0 == 0x50:
            return 4, f"set bg color of line to {b3 - 0x50}"
        if b1 in TARGET:
            if b2 == 0x20 and b3 == 0x40:
                return 4, f"load DRCs into {TARGET[b1]}"
            if b2 in SETS:
                return 3, f"load {SETS[b2]} into {TARGET[b1]}"
        if b1 in SHIFTS:
            return 2, SHIFTS[b1]
    if b0 == 0x1F:
        if b1 == 0x23 and b2 == 0x20 and b3 & 0xF0 == 0x40 and p(4) & 0xF0 == 0x40:
            return 5, (f"define characters {RES.get(b3 - 0x40, '???')}, "
                       f"{COLS.get(p(4) - 0x40, -1)} colors")
        if (b1 == 0x23 and b2 == 0x20 and b3 == 0x28 and p(4) == 0x20 and p(5) == 0x40
                and p(6) & 0xF0 == 0x40 and p(7) & 0xF0 == 0x40):
            return 8, (f"clear character set {RES.get(p(6) - 0x40, '???')}, "
                       f"{COLS.get(p(7) - 0x40, -1)} colors")
        if b1 == 0x23 and b3 == 0x30:
            return until_us(4), f"define characters 0x{b2:02x}+"
        if b1 == 0x26 and b2 == 0x20 and b3 == 0x22 and p(4) == 0x20 and p(5) == 0x35 and p(6) == 0x40:
            return 7, "start defining colors for DRCs"
        if b1 == 0x26 and b2 == 0x20:
            return 3, "start defining colors"
        if b1 == 0x26 and b2 == 0x21:
            return 3, "reset palette"
        if b1 == 0x26 and b2 & 0xF0 == 0x30 and b3 & 0xF0 == 0x30:
            l = until_us(4)
            return l, f"define colors {chr(b2)}{chr(b3)}+: {palette(buf[i + 4:i + l])}"
        if b1 == 0x26 and b2 & 0xF0 == 0x30:
            return until_us(3), f"define DRC color {b2 - 0x30}"
        if b1 == 0x2D:
            return 2, "set resolution to 40x24"
        if b1 == 0x2F:
            if b2 == 0x40:
                return 4, f"service break to row {b3 - 0x40}"
            modes = {0x4F: "service break back", 0x41: "serial mode", 0x42: "parallel mode",
                     0x43: "serial limited mode", 0x44: "parallel limited mode"}
            if b2 in modes:
                return 3, modes[b2]
        if b1 == 0x3D and b2 & 0xF0 >= 0x30:
            if b3 == 0x1F:
                return 3, f"define shortcut #{b2 - 0x30}"
            return 5, f'define shortcut #{b2 - 0x30} "{ch(b3)}{ch(p(4))}"'
        if b1 >= 0x41 and b2 >= 0x41:
            return 3, f"set cursor to line {b1 - 0x40}, column {b2 - 0x40}"
    if printable(b0) and b1 != 0x12:
        l = 0
        while l < HEX_PER_LINE and printable(p(l)) and p(l + 1) != 0x12 and i + l < n:
            l += 1
        return l, '"' + "".join(ch(c) for c in buf[i:i + l]) + '"'
    if 0x80 <= b0 <= 0x87:
        return 1, f"set fg color to #{b0 - 0x80}"
    if 0x90 <= b0 <= 0x97:
        return 1, f"set bg color to #{b0 - 0x90}"
    if b0 in C1:
        return 1, C1[b0]
    if b0 == 0x9B and (b1, b2) in CSI:
        return 3, CSI[(b1, b2)]
    return 1, "unknown"


def annotate(buf):
    lines, i = [], 0
    while i < len(buf):
        l, d = describe(buf, i)
        l = max(1, min(l, len(buf) - i))
        first = True
        while l > 0:
            chunk = buf[i:i + min(l, HEX_PER_LINE)]
            line = "".join(f"{c:02x} " for c in chunk) + "   " * (HEX_PER_LINE - len(chunk))
            lines.append(line + (f"# {d}" if first else ""))
            first = False
            i += len(chunk)
            l -= len(chunk)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(annotate(open(sys.argv[1], "rb").read()))
