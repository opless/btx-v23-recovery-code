#!/usr/bin/env python3
"""Decode Bildschirmtext pages recorded on audio tape.

    tapedecode.py IN OUT

IN is an audio file or a folder of them (flac, wav, mp3, ...). For every recording
<stem>, OUT/<stem>/ gets:

    pageNN.cept     reconstructed CEPT T/CD 06-01 byte stream
    pageNN.txt      annotated hex dump
    pageNN.png      rendering, 960x720
    raw/            every part the demodulator found (all copies, leader/trailer noise)
    index.md        what was found where, and which copy each page came from
    contact_sheet.png

Pages are usually transmitted twice in a row. Consecutive parts with near-identical
content are treated as copies of one page, and the cleanest copy is kept: the one
other copies agree with byte for byte, else the one with the fewest framing errors,
then the fewest bytes with bit 7 set (tape dropouts tend to flip it), then the longest.
"""
import argparse
import difflib
import os
import shutil
import sys

from PIL import Image, ImageDraw

import cept_annotate
import cept_render
import v23

AUDIO_EXT = [".flac", ".wav", ".aiff", ".aif", ".ogg", ".m4a", ".mp3"]   # preferred first
NOISE_MIN_LEN = 64      # leader/trailer fragments are 20-60 bytes
NOISE_HIGH_RATIO = 0.5  # ...and ~75% of their bytes have bit 7 set; real pages <= ~40%
SAME_PAGE = 0.9         # similarity above which two consecutive parts are copies


def find_audio(path):
    if os.path.isfile(path):
        return [path]
    best = {}
    for name in sorted(os.listdir(path)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in AUDIO_EXT:
            continue
        rank = AUDIO_EXT.index(ext.lower())
        if stem not in best or rank < best[stem][0]:
            best[stem] = (rank, os.path.join(path, name))
    return [p for _, p in sorted(best.values(), key=lambda v: v[1])]


def high(data):
    return sum(b >= 0x80 for b in data)


def is_noise(part):
    d = part.data
    return len(d) < NOISE_MIN_LEN or high(d) > NOISE_HIGH_RATIO * len(d)


def same_page(a, b):
    if min(len(a), len(b)) < SAME_PAGE * max(len(a), len(b)):
        return False
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= SAME_PAGE and m.quick_ratio() >= SAME_PAGE \
        and m.ratio() >= SAME_PAGE


def group_copies(parts):
    groups = []
    for p in parts:
        if groups and same_page(groups[-1][-1].data, p.data):
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def pick(copies):
    def key(p):
        agree = sum(q.data == p.data for q in copies)
        return (-agree, p.framing_errors, high(p.data), -len(p.data), -p.time)
    best = min(copies, key=key)
    agree = sum(q.data == best.data for q in copies)
    return best, agree


def render(data, txt_path, png_path):
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(cept_annotate.annotate(data))
    term = cept_render.Terminal()
    term.feed(data)
    cept_render.render(term, png_path)


def contact_sheet(pngs, path, cols=3, w=320, h=240, label=20):
    if not pngs:
        return
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + label)), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    for k, (name, png) in enumerate(pngs):
        x, y = k % cols * w, k // cols * (h + label)
        sheet.paste(Image.open(png).resize((w, h), Image.LANCZOS), (x, y + label))
        draw.text((x + 4, y + 4), name, fill=(220, 220, 220))
    sheet.save(path)


def process(audio, out_root):
    stem = os.path.splitext(os.path.basename(audio))[0]
    out = os.path.join(out_root, stem)
    raw = os.path.join(out, "raw")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(raw)

    duration, parts = v23.decode(audio, log=lambda s: print(s, flush=True))
    for p in parts:
        with open(os.path.join(raw, f"{stem}_{p.name}.cept"), "wb") as fh:
            fh.write(p.data)

    real = [p for p in parts if not is_noise(p)]
    groups = group_copies(real)
    rows, pngs = [], []
    for n, copies in enumerate(groups, 1):
        best, agree = pick(copies)
        page = f"page{n:02d}"
        base = os.path.join(out, page)
        with open(base + ".cept", "wb") as fh:
            fh.write(best.data)
        render(best.data, base + ".txt", base + ".png")
        pngs.append((page, base + ".png"))
        if len(copies) == 1:
            note = "single copy"
        elif agree == len(copies):
            note = f"{len(copies)} identical copies"
        elif agree == 1:
            note = f"{len(copies)} copies all differ, kept the cleanest"
        else:
            note = f"{len(copies)} copies, kept the one {agree} of them agree on"
        if best.framing_errors:
            note += f", {best.framing_errors} framing errors"
        src = ", ".join(("**" + p.name + "**") if p is best else p.name for p in copies)
        rows.append(f"| {page} | {best.time:6.1f} s | {len(best.data):5d} | ~{best.baud:.0f} | "
                    f"{src} | {note} |")
        print(f"   {page}: {len(best.data)} bytes from part {best.name} ({note})", flush=True)
    contact_sheet(pngs, os.path.join(out, "contact_sheet.png"))

    noise = len(parts) - len(real)
    with open(os.path.join(out, "index.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {os.path.basename(audio)}\n\n")
        fh.write(f"{duration:.0f} s of audio, {len({p.burst for p in parts})} carrier bursts, "
                 f"{len(parts)} parts ({noise} leader/trailer noise), {len(groups)} pages.\n\n")
        if rows:
            fh.write("| page | tape pos | bytes | baud | parts (used in bold) | notes |\n")
            fh.write("|------|---------:|------:|-----:|----------------------|-------|\n")
            fh.write("\n".join(rows) + "\n")
        else:
            fh.write("No modem transmissions found.\n")
    return len(groups)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="audio file or folder of audio files")
    ap.add_argument("output", help="output folder (one subfolder per recording)")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("tapedecode: ffmpeg not found on PATH")
    files = find_audio(args.input)
    if not files:
        sys.exit(f"tapedecode: no audio files in {args.input}")
    os.makedirs(args.output, exist_ok=True)
    total, failed = 0, []
    for f in files:
        try:
            total += process(f, args.output)
        except Exception as e:      # one bad file shouldn't stop a whole folder
            print(f"{f}: FAILED: {e}", file=sys.stderr)
            failed.append(f)
    print(f"{total} pages from {len(files) - len(failed)} recordings -> {args.output}")
    if failed:
        sys.exit(f"{len(failed)} recordings failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
