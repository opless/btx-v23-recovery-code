# tapedecode

Turns cassette recordings of Bildschirmtext (Btx) modem transmissions into CEPT pages,
annotated dumps and PNG renderings.

    ./tapedecode IN OUT

- `IN`: one audio file, or a folder of them (`.flac .wav .aiff .ogg .m4a .mp3`). If a
  folder has the same recording in several formats (`01a.flac` and `01a.mp3`), only
  the best one is decoded, with lossless formats preferred.
- `OUT`: gets one subfolder per recording. A subfolder is replaced if it already exists.

```
OUT/63a/
  page01.cept  page01.txt  page01.png
  page02.cept  ...
  raw/63a_<burst>_<part>.cept     everything the demodulator found
  index.md                        tape position, size, which copy was used
  contact_sheet.png
```

The first run creates `.venv/` here with numpy, scipy and Pillow. It also needs
`ffmpeg` on `PATH`. The renderer uses the macOS Menlo font.

## How it works

1. `v23.py`: finds carrier bursts, FM-demodulates V.23 (mark 1300 Hz, space 2100 Hz),
   estimates the tape speed from framing errors, decodes async 8N1, and splits the
   byte stream at pauses longer than 0.4 s.
2. `tapedecode.py`: drops leader/trailer noise, meaning parts under 64 bytes or with
   more than half their bytes having bit 7 set. Consecutive parts that are at least 90%
   alike count as copies of one page (Btx pages were usually recorded twice). It keeps
   one copy per page, in this order of preference: the copy most other copies match
   byte for byte; then fewest framing errors; then fewest bit-7 bytes, since tape
   dropouts tend to set bit 7; then the longest.
3. `cept_annotate.py`: annotated hex dump. It is a Python port of
   `bildschirmtext/tools/decode_cept.c` with identical output, except that it doesn't
   print bytes from past the end of the file the way the C tool can.
4. `cept_render.py`: CEPT T/CD 06-01 renderer (DRCS, colour tables, G0-G3, mosaics).

Each script also runs on its own:

    .venv/bin/python v23.py 63a.flac rawdir
    .venv/bin/python cept_annotate.py page.cept > page.txt
    .venv/bin/python cept_render.py page.cept page.png

Check the `notes` column in `index.md`. "copies differ" means the tape was damaged in
at least one copy, and you should look at the chosen page. "single copy" means there
was nothing to cross-check it against.

### Potential issue
You might want to change this to something suitable for your system:
```python
584:             font2[key] = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 25 * h // CH)
```
