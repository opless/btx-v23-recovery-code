#!/usr/bin/env python3
"""Render a CEPT T/CD 06-01 (Bildschirmtext) byte stream to a PNG.

Covers what Btx pages typically use: serial and parallel attribute modes, the four
colour tables incl. redefined colours, G0/G1/G2/G3 + DRCS character sets with
SS2/SS3/locking shifts, DRCS in all resolutions with 2/4/16 colours, repeat, APA,
row/screen colours, and double width/height. Flashing, conceal, scrolling regions
and protected/marked areas are parsed but not displayed.

Usage: cept_render.py page.cept out.png [more.cept out2.png ...]
Needs: Pillow.
"""
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont

ROWS, COLS = 24, 40
CW, CH = 24, 30          # rendered cell: 12x10 CEPT pixels scaled 2x3 -> 960x720 (4:3)
PX, PY = CW // 12, CH // 10

FULL = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (255, 255, 0),
        (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
HALF = [None, (119, 0, 0), (0, 119, 0), (119, 119, 0),
        (0, 0, 119), (119, 0, 119), (0, 119, 119), (119, 119, 119)]   # table 1, colour 0 = transparent

# G2 supplementary set (ISO 6937 right half); 0x41-0x4F are non-spacing diacritics
G2 = {0x21: "¡", 0x22: "¢", 0x23: "£", 0x24: "$", 0x25: "¥", 0x26: "#", 0x27: "§", 0x28: "¤",
      0x29: "‘", 0x2A: "“", 0x2B: "«", 0x2C: "←", 0x2D: "↑", 0x2E: "→", 0x2F: "↓",
      0x30: "°", 0x31: "±", 0x32: "²", 0x33: "³", 0x34: "×", 0x35: "µ", 0x36: "¶", 0x37: "·",
      0x38: "÷", 0x39: "’", 0x3A: "”", 0x3B: "»", 0x3C: "¼", 0x3D: "½", 0x3E: "¾", 0x3F: "¿",
      0x50: "―", 0x51: "¹", 0x52: "®", 0x53: "©", 0x54: "™", 0x55: "♪",
      0x5C: "⅛", 0x5D: "⅜", 0x5E: "⅝", 0x5F: "⅞",
      0x60: "Ω", 0x61: "Æ", 0x62: "Đ", 0x63: "ª", 0x64: "Ħ", 0x66: "Ĳ", 0x67: "Ŀ", 0x68: "Ł",
      0x69: "Ø", 0x6A: "Œ", 0x6B: "º", 0x6C: "Þ", 0x6D: "Ŧ", 0x6E: "Ŋ", 0x6F: "ŉ",
      0x70: "ĸ", 0x71: "æ", 0x72: "đ", 0x73: "ð", 0x74: "ħ", 0x75: "ı", 0x76: "ĳ", 0x77: "ŀ",
      0x78: "ł", 0x79: "ø", 0x7A: "œ", 0x7B: "ß", 0x7C: "þ", 0x7D: "ŧ", 0x7E: "ŋ"}
DIACRITIC = {0x41: "̀", 0x42: "́", 0x43: "̂", 0x44: "̃", 0x45: "̄",
             0x46: "̆", 0x47: "̇", 0x48: "̈", 0x4A: "̊", 0x4B: "̧",
             0x4D: "̋", 0x4E: "̨", 0x4F: "̌"}

# G3 = teletext smooth mosaics and line drawing (code -> Unicode, drawn procedurally)
G3 = dict(zip(range(0x20, 0x2C), [0x1FB3C, 0x1FB3D, 0x1FB3E, 0x1FB3F, 0x1FB40, 0x25E3,
                                   0x1FB41, 0x1FB42, 0x1FB43, 0x1FB44, 0x1FB45, 0x1FB46]))
G3.update({0x2C: 0x1FB68, 0x2D: 0x1FB69, 0x2E: 0x1FB70, 0x2F: 0x2592})
G3.update(zip(range(0x30, 0x3C), [0x1FB47, 0x1FB48, 0x1FB49, 0x1FB4A, 0x1FB4B, 0x25E2,
                                   0x1FB4C, 0x1FB4D, 0x1FB4E, 0x1FB4F, 0x1FB50, 0x1FB51]))
G3.update({0x3C: 0x1FB6A, 0x3D: 0x1FB6B, 0x3E: 0x1FB75, 0x3F: 0x2588})
G3.update(zip(range(0x40, 0x60), [0x2537, 0x252F, 0x251D, 0x2525, 0x1FBA4, 0x1FBA5, 0x1FBA6,
                                   0x1FBA7, 0x1FBA0, 0x1FBA1, 0x1FBA2, 0x1FBA3, 0x253F, 0x2022,
                                   0x25CF, 0x25CB, 0x2502, 0x2500, 0x250C, 0x2510, 0x2514,
                                   0x2518, 0x251C, 0x2524, 0x252C, 0x2534, 0x253C, 0x2B62,
                                   0x2B60, 0x2B61, 0x2B63, 0x00A0]))
G3.update(zip(range(0x60, 0x6E), [0x1FB52, 0x1FB53, 0x1FB54, 0x1FB55, 0x1FB56, 0x25E5,
                                   0x1FB57, 0x1FB58, 0x1FB59, 0x1FB5A, 0x1FB5B, 0x1FB5C,
                                   0x1FB6C, 0x1FB6D]))
G3.update(zip(range(0x70, 0x7E), [0x1FB5D, 0x1FB5E, 0x1FB5F, 0x1FB60, 0x1FB61, 0x25E4,
                                   0x1FB62, 0x1FB63, 0x1FB64, 0x1FB65, 0x1FB66, 0x1FB67,
                                   0x1FB6E, 0x1FB6F]))

POINTS = {"UPPER LEFT": (0, 0), "UPPER CENTRE": (.5, 0), "UPPER RIGHT": (1, 0),
          "UPPER MIDDLE LEFT": (0, 1 / 3), "LOWER MIDDLE LEFT": (0, 2 / 3),
          "UPPER MIDDLE RIGHT": (1, 1 / 3), "LOWER MIDDLE RIGHT": (1, 2 / 3),
          "LOWER LEFT": (0, 1), "LOWER CENTRE": (.5, 1), "LOWER RIGHT": (1, 1),
          "MIDDLE LEFT": (0, .5), "MIDDLE RIGHT": (1, .5)}
QUARTER = {"LEFT": [(0, 0), (0, 1), (.5, .5)], "UPPER": [(0, 0), (1, 0), (.5, .5)],
           "RIGHT": [(1, 0), (1, 1), (.5, .5)], "LOWER": [(0, 1), (1, 1), (.5, .5)]}
# box drawing: (up, down, left, right) weights, 0 none / 1 light / 2 heavy
BOX = {0x2502: (1, 1, 0, 0), 0x2500: (0, 0, 1, 1), 0x250C: (0, 1, 0, 1), 0x2510: (0, 1, 1, 0),
       0x2514: (1, 0, 0, 1), 0x2518: (1, 0, 1, 0), 0x251C: (1, 1, 0, 1), 0x2524: (1, 1, 1, 0),
       0x252C: (0, 1, 1, 1), 0x2534: (1, 0, 1, 1), 0x253C: (1, 1, 1, 1), 0x2537: (1, 0, 2, 2),
       0x252F: (0, 1, 2, 2), 0x251D: (1, 1, 0, 2), 0x2525: (1, 1, 2, 0), 0x253F: (1, 1, 2, 2)}
DIAG = {0x1FBA0: [((.5, 0), (0, .5))], 0x1FBA1: [((.5, 0), (1, .5))],
        0x1FBA2: [((0, .5), (.5, 1))], 0x1FBA3: [((1, .5), (.5, 1))]}
DIAG[0x1FBA4] = DIAG[0x1FBA0] + DIAG[0x1FBA2]
DIAG[0x1FBA5] = DIAG[0x1FBA1] + DIAG[0x1FBA3]
DIAG[0x1FBA6] = DIAG[0x1FBA2] + DIAG[0x1FBA3]
DIAG[0x1FBA7] = DIAG[0x1FBA0] + DIAG[0x1FBA1]

DRCS_RES = {0x46: (12, 12), 0x47: (12, 10), 0x4A: (6, 12), 0x4B: (6, 10), 0x4C: (6, 5), 0x4F: (6, 6)}
DRCS_PLANES = {0x41: 1, 0x42: 2, 0x44: 4}


class Cell:
    __slots__ = ("glyph", "fg", "bg", "size", "misc", "marks")

    def __init__(self, fg=7, bg=None):
        self.glyph = None          # (set, code, diacritic) or None = space
        self.fg, self.bg, self.size = fg, bg, 0   # size: 0 normal, 1 dh, 2 dw, 3 ds
        self.misc = None
        self.marks = set()         # serial attributes placed on this cell


class Terminal:
    def __init__(self):
        self.palette = FULL + HALF + FULL + FULL
        self.dct = [0, 1, 2, 3]            # 4-colour DRCS colour table
        self.drcs = {}                     # code -> (w, h, planes, pixel rows)
        self.drcs_fmt = (12, 10, 1)
        self.screen_bg = 0
        self.row_bg = [None] * ROWS
        self.reset(full=True)

    def reset(self, full, serial=True):
        self.serial = serial
        self.g = ["G0", "G1", "G2", "G3"]  # what is designated into G0..G3
        self.gl, self.gr = 0, 2
        self.ss = None
        self.fg_table = 0
        self.fg, self.bg, self.size = 7, None, 0
        self.diacritic = None
        self.last = None
        if full:
            self.cells = [[Cell() for _ in range(COLS)] for _ in range(ROWS)]
            self.row_bg = [None] * ROWS
            self.r = self.c = 0

    # ---- cursor
    def moved(self):
        if self.serial:            # serial state = what is in effect at this cell
            cell = self.cells[self.r][self.c]
            self.fg, self.bg, self.size = cell.fg, cell.bg, cell.size

    def goto(self, r, c):
        self.r, self.c = r % ROWS, c % COLS
        self.moved()

    def advance(self, step=None):
        if step is None:
            step = 2 if self.size & 2 else 1
        self.c += step
        if self.c >= COLS:
            self.c = 0
            self.r = (self.r + (2 if self.size & 1 else 1)) % ROWS
            if self.serial:
                self.fg, self.bg, self.size = 7, None, 0
        else:
            self.moved()

    # ---- attributes
    def serial_attr(self, name, value):
        row = self.cells[self.r]
        cell = row[self.c]
        cell.marks.add(name)
        cell.glyph = None
        for k in range(self.c, COLS):
            if k > self.c and name in row[k].marks:
                break
            setattr(row[k], name, value)
        self.advance(1)                # the attribute cell itself is never double width

    def set_attr(self, name, value):
        setattr(self, name, value)
        if self.serial:
            self.serial_attr(name, value)

    def put(self, glyph):
        cell = self.cells[self.r][self.c]
        cell.glyph = glyph
        if not self.serial:
            cell.fg, cell.bg, cell.size = self.fg, self.bg, self.size
        self.last = glyph
        self.advance()

    # ---- character output
    def char(self, b):
        if self.ss is not None:
            gset, self.ss = self.g[self.ss], None
        elif b < 0x80:
            gset = self.g[self.gl]
        else:
            gset = self.g[self.gr]
        code = b & 0x7F
        if gset == "G2" and code in DIACRITIC:
            self.diacritic = DIACRITIC[code]
            return
        self.put((gset, code, self.diacritic))
        self.diacritic = None

    def feed(self, data):
        self.data, self.i = data, 0
        while self.i < len(data):
            b = self.next()
            if b < 0x20:
                self.c0(b)
            elif 0x80 <= b < 0xA0:
                self.c1(b)
            else:
                self.char(b)

    def next(self):
        b = self.data[self.i]
        self.i += 1
        return b

    def peek(self):
        return self.data[self.i] if self.i < len(self.data) else None

    def c0(self, b):
        if b == 0x08:
            if self.c == 0:
                self.goto(self.r - 1, COLS - 1)
            else:
                self.goto(self.r, self.c - 1)
        elif b == 0x09:
            self.c += 1
            if self.c >= COLS:
                self.goto(self.r + 1, 0)
            self.moved()
        elif b == 0x0A:
            self.goto(self.r + 1, self.c)
        elif b == 0x0B:
            self.goto(self.r - 1, self.c)
        elif b == 0x0C:
            self.cells = [[Cell() for _ in range(COLS)] for _ in range(ROWS)]
            self.row_bg = [None] * ROWS
            self.goto(0, 0)
        elif b == 0x0D:
            self.goto(self.r, 0)
        elif b == 0x0E:
            self.gl = 1
        elif b == 0x0F:
            self.gl = 0
        elif b == 0x12:
            n = self.next() - 0x40
            for _ in range(max(n, 0)):
                if self.last:
                    self.put(self.last)
        elif b == 0x18:
            for k in range(self.c, COLS):
                self.cells[self.r][k] = Cell()
        elif b == 0x19:
            self.ss = 2
        elif b == 0x1D:
            self.ss = 3
        elif b == 0x1E:
            self.goto(0, 0)
        elif b == 0x1B:
            self.esc()
        elif b == 0x1F:
            self.us()

    def c1(self, b):
        if b == 0x9B:
            return self.csi()
        if self.serial:
            if 0x80 <= b <= 0x87 or 0x90 <= b <= 0x97:   # 90-97: L-set colour, drawn as plain colour
                self.set_attr("fg", self.fg_table * 8 + (b & 7))
            elif b == 0x9D:
                self.set_attr("bg", self.fg)
            elif b == 0x9C:
                self.set_attr("bg", 0)
            elif 0x8C <= b <= 0x8F:
                self.set_attr("size", b - 0x8C)
            else:
                self.serial_attr("misc", b)      # flash, conceal, underline, ...: spacing only
        else:
            if 0x80 <= b <= 0x87:
                self.fg = self.fg_table * 8 + (b & 7)
            elif 0x90 <= b <= 0x97:
                self.bg = self.fg_table * 8 + (b & 7)
            elif b == 0x9D:
                self.fg, self.bg = (self.bg if self.bg is not None else 0), self.fg
            elif b == 0x9E:
                self.bg = None
            elif 0x8C <= b <= 0x8F:
                self.size = b - 0x8C

    def csi(self):
        params = bytearray()
        while self.peek() is not None and 0x30 <= self.peek() <= 0x3F:
            params.append(self.next())
        final = self.next() if self.peek() is not None else 0
        if final == 0x40 and len(params) == 1:
            self.fg_table = params[0] - 0x30

    def esc(self):
        b = self.next()
        if 0x28 <= b <= 0x2B:                     # designate into G0..G3
            f = self.next()
            if f == 0x20:
                self.next()
                self.g[b - 0x28] = "DRCS"
            else:
                self.g[b - 0x28] = {0x40: "G0", 0x63: "G1", 0x62: "G2", 0x64: "G3"}.get(f, "G0")
        elif b == 0x6E:
            self.gl = 2
        elif b == 0x6F:
            self.gl = 3
        elif b == 0x7E:
            self.gr = 1
        elif b == 0x7D:
            self.gr = 2
        elif b == 0x7C:
            self.gr = 3
        elif b == 0x22:
            self.serial = self.next() == 0x40
        elif b == 0x23:
            scope, a = self.next(), self.next()
            colour = self.fg_table * 8 + (a & 7) if 0x50 <= a <= 0x57 else None
            if scope == 0x20 and (0x50 <= a <= 0x57 or a == 0x5E):
                self.screen_bg = colour
            elif scope == 0x21 and (0x50 <= a <= 0x57 or a == 0x5E):
                self.row_bg[self.r] = colour
                for cell in self.cells[self.r]:
                    cell.bg = colour
            elif scope == 0x21 and 0x40 <= a <= 0x47:
                for cell in self.cells[self.r]:
                    cell.fg = self.fg_table * 8 + (a & 7)

    def skip_to_us(self):
        start = self.i
        while self.peek() is not None and self.peek() != 0x1F:
            self.i += 1
        return self.data[start:self.i]

    def us(self):
        b = self.next()
        if 0x40 <= b <= 0x7F:                     # APA
            self.goto(b - 0x41, self.next() - 0x41)
        elif b == 0x23:
            self.us_drcs()
        elif b == 0x26:
            self.us_colours()
        elif b == 0x2D:
            while self.peek() in (0x41, 0x42, 0x70, 0x71):
                self.next()
        elif b == 0x2F:
            mode = self.next()
            self.reset(full=mode in (0x41, 0x42), serial=mode in (0x41, 0x43))
        else:
            self.skip_to_us()

    def us_colours(self):
        b = self.next()
        if b == 0x20:
            self.colour_mode = "dct" if 0x22 in self.skip_to_us() else "palette"
        elif b == 0x21:
            self.palette[16:] = FULL + FULL
        elif 0x30 <= b <= 0x39:
            if getattr(self, "colour_mode", "palette") == "palette":
                idx = (b - 0x30) * 10 + self.next() - 0x30
                d = self.skip_to_us()
                for k in range(0, len(d) - 1, 2):
                    hi, lo = d[k], d[k + 1]
                    rgb = []
                    for sh in (5, 4, 3):       # r, g, b
                        v = (((hi >> sh) & 1) << 3) | (((hi >> (sh - 3)) & 1) << 2) \
                            | (((lo >> sh) & 1) << 1) | ((lo >> (sh - 3)) & 1)
                        rgb.append(v * 17)
                    if idx + k // 2 < 32:
                        self.palette[idx + k // 2] = tuple(rgb)
            else:
                idx = b - 0x30
                for k, v in enumerate(self.skip_to_us()):
                    if idx + k < 4:
                        self.dct[idx + k] = v & 0x1F
        else:
            self.skip_to_us()

    def us_drcs(self):
        b = self.next()
        if b == 0x20:                             # header: [28 20 40] 4p 4q
            hdr = self.skip_to_us()
            if 0x28 in hdr:
                self.drcs.clear()
            p = [x for x in hdr if 0x40 <= x <= 0x4F]
            if len(p) >= 2:
                w, h = DRCS_RES.get(p[-2], (12, 10))
                self.drcs_fmt = (w, h, DRCS_PLANES.get(p[-1], 1))
            return
        code = b
        w, h, nplanes = self.drcs_fmt
        bpr = 2 if w == 12 else 1
        wide = (w, h, nplanes) in ((12, 10, 2), (12, 12, 2), (6, 10, 4), (6, 12, 4))
        planes = None
        plane = rows = cur = None
        seen = set()

        def flush_char():
            nonlocal code, planes
            if planes is not None:
                for pl in planes:
                    while len(pl) < h:
                        pl.append(0)
                self.drcs[code] = (w, h, nplanes, [pl[:h] for pl in planes])
                code += 2 if wide else 1
            planes = None

        for d in self.skip_to_us():
            if 0x30 <= d <= 0x33:
                n = d - 0x30
                # planes may arrive in any order (e.g. 30 33 31 32); a new character
                # starts only when a plane that already has data is sent again
                if planes is None or n in seen:
                    flush_char()
                    planes = [[] for _ in range(nplanes)]
                    seen = set()
                seen.add(n)
                plane, rows, cur = n, (planes[n] if n < nplanes else []), []
                continue
            if rows is None:
                continue
            full = (1 << w) - 1
            if d >= 0x40:
                cur.append(d & 0x3F)
                if len(cur) == bpr:
                    rows.append((cur[0] << 6 | cur[1]) if bpr == 2 else cur[0])
                    cur = []
            elif d == 0x20:
                rows.extend([0] * (h - len(rows)))
            elif 0x21 <= d <= 0x2A:
                rows.extend([rows[-1] if rows else 0] * (d - 0x20))
            elif d == 0x2C:
                rows.append(0)
            elif d == 0x2D:
                rows.append(full)
            elif d == 0x2E:
                rows.extend([rows[-1] if rows else 0] * (h - len(rows)))
            elif d == 0x2F:
                rows.extend([full] * (h - len(rows)))
        flush_char()


# ---------------------------------------------------------------- drawing

def mosaic(draw, x, y, code, fg):
    bits = (code - 0x20) if code < 0x40 else (code - 0x60) | 0x20
    ys = [0, 3, 6, 10]
    for k in range(6):
        if bits >> k & 1:
            col, row = k & 1, k >> 1
            draw.rectangle([x + col * 6 * PX, y + ys[row] * PY,
                            x + (col + 1) * 6 * PX - 1, y + ys[row + 1] * PY - 1], fill=fg)


def g3(draw, img, x, y, code, fg, w=CW, h=CH):
    u = G3.get(code, 0xA0)
    pt = lambda p: (x + p[0] * w, y + p[1] * h)
    name = unicodedata.name(chr(u), "")
    if "BLOCK DIAGONAL" in name or "BLACK" in name and "TRIANGLE" in name:
        if "BLOCK DIAGONAL" in name:
            corner_name, line = name.split(" BLOCK DIAGONAL ")
            a, b = (POINTS[s] for s in line.split(" TO "))
        else:
            corner_name = name.replace("BLACK ", "").replace(" TRIANGLE", "")
            corners = {"LOWER LEFT": ((0, 0), (1, 1)), "LOWER RIGHT": ((1, 0), (0, 1)),
                       "UPPER LEFT": ((1, 0), (0, 1)), "UPPER RIGHT": ((0, 0), (1, 1))}
            a, b = corners[corner_name]
        corner = POINTS[corner_name]
        side = lambda p: (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        ref = side(corner)
        poly = []                              # clip unit square to the corner's half-plane
        sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for k in range(4):
            p, q = sq[k], sq[(k + 1) % 4]
            sp, sq_ = side(p) * ref, side(q) * ref
            if sp >= 0:
                poly.append(p)
            if sp * sq_ < 0:
                t = sp / (sp - sq_)
                poly.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        draw.polygon([pt(p) for p in poly], fill=fg)
    elif "THREE QUARTERS" in name:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=fg)
        missing = ({"LEFT", "UPPER", "RIGHT", "LOWER"} - set(name.split(" TRIANGULAR")[0].split(" AND "))).pop()
        bgcol = img.getpixel((int(x + w * .5), int(y + h * .5)))  # placeholder, replaced below
        return ("cut", [pt(p) for p in QUARTER[missing]])
    elif "ONE QUARTER" in name:
        draw.polygon([pt(p) for p in QUARTER[name.split(" ")[0]]], fill=fg)
    elif u in (0x1FB70, 0x1FB75):
        k = 1 if u == 0x1FB70 else 6
        draw.rectangle([x + k * w / 8, y, x + (k + 1) * w / 8 - 1, y + h - 1], fill=fg)
    elif u == 0x2592:
        for yy in range(0, h, PY):
            for xx in range(0, w, PX):
                if (xx // PX + yy // PY) % 2 == 0:
                    draw.rectangle([x + xx, y + yy, x + xx + PX - 1, y + yy + PY - 1], fill=fg)
    elif u == 0x2588:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=fg)
    elif u in BOX:
        up, down, left, right = BOX[u]
        cx, cy = x + w / 2, y + h / 2
        t = {1: PX, 2: PX * 2}
        if up:
            draw.rectangle([cx - t[up] / 2, y, cx + t[up] / 2 - 1, cy], fill=fg)
        if down:
            draw.rectangle([cx - t[down] / 2, cy, cx + t[down] / 2 - 1, y + h - 1], fill=fg)
        if left:
            draw.rectangle([x, cy - t[left] * 0.75, cx, cy + t[left] * 0.75 - 1], fill=fg)
        if right:
            draw.rectangle([cx, cy - t[right] * 0.75, x + w - 1, cy + t[right] * 0.75 - 1], fill=fg)
    elif u in DIAG:
        for a, b in DIAG[u]:
            draw.line([pt(a), pt(b)], fill=fg, width=PX + 1)
    elif u in (0x2022, 0x25CF, 0x25CB):
        r = 0.18 if u == 0x2022 else 0.38
        box = [x + w * (.5 - r), y + h * .5 - w * r, x + w * (.5 + r), y + h * .5 + w * r]
        if u == 0x25CB:
            draw.ellipse(box, outline=fg, width=PX)
        else:
            draw.ellipse(box, fill=fg)
    elif u in (0x2B60, 0x2B61, 0x2B62, 0x2B63):
        # arrow pointing right in unit coords, then rotate
        shape = [(.1, .42), (.55, .42), (.55, .25), (.9, .5), (.55, .75), (.55, .58), (.1, .58)]
        rot = {0x2B62: lambda p: p, 0x2B60: lambda p: (1 - p[0], p[1]),
               0x2B61: lambda p: (p[1], 1 - p[0]), 0x2B63: lambda p: (p[1], p[0])}[u]
        draw.polygon([pt(rot(p)) for p in shape], fill=fg)
    return None


def render(term, path):
    W, H = COLS * CW, ROWS * CH
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 25)
    font2 = {}
    pal = term.palette

    def colour(i, default=(0, 0, 0), row=None):
        # transparent (None, or table 1 colour 0) shows the layer below:
        # the row background if one is set, otherwise the screen background
        if i is None or pal[i] is None:
            if row is not None and term.row_bg[row] is not None and pal[term.row_bg[row]] is not None:
                return pal[term.row_bg[row]]
            if term.screen_bg is not None and pal[term.screen_bg] is not None:
                return pal[term.screen_bg]
            return default
        return pal[i]

    def drcs_glyph(code, x, y, w, h, fg, bg):
        dw, dh, nplanes, planes = term.drcs[code]
        sx, sy = w / dw, h / dh
        for yy in range(dh):
            for xx in range(dw):
                bit = dw - 1 - xx
                v = 0
                for pl in planes[::-1]:     # block 30 is the LOW bit (checked against real renders)
                    v = (v << 1) | (pl[yy] >> bit & 1)
                if nplanes == 1:
                    c = fg if v else bg
                else:               # transparent DRCS pixels show the character background
                    i = term.dct[v] if nplanes == 2 else 16 + v
                    c = pal[i] if pal[i] is not None else bg
                draw.rectangle([x + xx * sx, y + yy * sy,
                                x + (xx + 1) * sx - 1, y + (yy + 1) * sy - 1], fill=c)

    def glyph(g, x, y, w, h, fg, bg):
        gset, code, dia = g
        if gset == "DRCS":
            if code in term.drcs:
                drcs_glyph(code, x, y, w, h, fg, bg)
            return
        if gset == "G1" and 0x40 <= code <= 0x5F:
            # CEPT G1 columns 4-5 hold the smooth diagonal mosaics, i.e. the same
            # shapes as G3 0x20-0x3F (ISO-IR-71 second mosaic set), not letters
            gset, code = "G3", code - 0x20
        if gset == "G1":
            if w == CW and h == CH:
                mosaic(draw, x, y, code, fg)
            else:
                tmp = Image.new("RGB", (CW, CH), bg)
                mosaic(ImageDraw.Draw(tmp), 0, 0, code, fg)
                img.paste(tmp.resize((w, h), Image.NEAREST), (x, y))
            return
        if gset == "G3":
            tmp = Image.new("RGB", (w, h), bg)
            td = ImageDraw.Draw(tmp)
            res = g3(td, tmp, 0, 0, code, fg, w, h)
            if res:
                td.polygon(res[1], fill=bg)
            img.paste(tmp, (x, y))
            return
        if gset == "G2":
            ch = G2.get(code, " ")
        else:
            ch = chr(code) if code != 0x7F else "■"
        if dia:
            ch = unicodedata.normalize("NFC", ch + dia)
        if ch.strip() == "":
            return
        key = (w, h)
        if key not in font2:
            font2[key] = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 25 * h // CH)
        f = font2[key]
        tmp = Image.new("RGB", (int(f.getlength("M")) + 4, h), bg)
        ImageDraw.Draw(tmp).text((tmp.width / 2, h / 2 + h * 0.04), ch, font=f, fill=fg, anchor="mm")
        if tmp.width != w:
            tmp = tmp.resize((w, h), Image.LANCZOS)
        img.paste(tmp, (x, y))

    draw.rectangle([0, 0, W, H], fill=colour(term.screen_bg))
    big = []
    for r in range(ROWS):
        if term.row_bg[r] is not None:
            draw.rectangle([0, r * CH, W, (r + 1) * CH - 1], fill=colour(term.row_bg[r], row=r))
        skip = 0
        for c in range(COLS):
            cell = term.cells[r][c]
            x, y = c * CW, r * CH
            fg, bg = colour(cell.fg, (255, 255, 255)), colour(cell.bg, row=r)
            if skip:
                skip -= 1
                continue
            draw.rectangle([x, y, x + CW - 1, y + CH - 1], fill=bg)
            if cell.glyph is None:
                continue
            if cell.size:
                w = CW * (2 if cell.size & 2 else 1)
                h = CH * (2 if cell.size & 1 else 1)
                big.append((cell.glyph, x, y, min(w, W - x), min(h, H - y), fg, bg))
                skip = 1 if cell.size & 2 else 0
                if cell.size & 2 and c + 1 < COLS:
                    draw.rectangle([x + CW, y, x + 2 * CW - 1, y + CH - 1], fill=bg)
            else:
                glyph(cell.glyph, x, y, CW, CH, fg, bg)
    for g, x, y, w, h, fg, bg in big:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=bg)
        glyph(g, x, y, w, h, fg, bg)
    img.save(path)


def main():
    args = sys.argv[1:]
    for src, dst in zip(args[::2], args[1::2]):
        t = Terminal()
        t.feed(open(src, "rb").read())
        render(t, dst)
        print(f"{src} -> {dst}  ({len(t.drcs)} DRCS)")


if __name__ == "__main__":
    main()
