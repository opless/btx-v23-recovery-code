#!/usr/bin/env python3
"""Decode V.23 (1200 baud, mark 1300 Hz / space 2100 Hz) recordings into byte parts.

Pipeline: find bursts of carrier, FM-demodulate each burst (band-pass + analytic
signal), slice at the mark/space midpoint, async-UART decode 8N1, then split the
byte stream wherever the carrier idles (mark) for > GAP seconds.

Usage as a script: v23.py audio.flac outdir   (writes <stem>_<burst>_<part>.cept)
Needs: ffmpeg on PATH, numpy, scipy.
"""
import argparse
import os
import subprocess
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt

FS = 48000
BAUD = 1200
SLICE_HZ = 1700     # midpoint between 1300 and 2100, robust to ~±5% tape speed error
GAP = 0.4           # seconds of byte-free carrier that separates two transmissions
MIN_PART = 16       # shorter parts are leader/trailer noise


@dataclass
class Part:
    burst: int
    index: int
    time: float         # seconds from the start of the recording
    baud: float
    data: bytes
    framing_errors: int

    @property
    def name(self):
        return f"{self.burst}_{self.index}"


def load(path, max_seconds=None):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(FS)]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-f", "s16le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768


def find_bursts(x, thr=0.03, hang=1.0):
    """Return (start, end) sample ranges where the signal is above `thr` RMS."""
    w = FS // 10
    n = len(x) // w
    rms = np.sqrt((x[:n * w].reshape(n, w) ** 2).mean(1))
    act = rms > thr
    hang_blocks = int(hang * 10)
    bursts, i = [], 0
    while i < n:
        if act[i]:
            j = i
            while j < n and act[j:j + hang_blocks].any():
                j += 1
            if j - i >= 20:     # ignore clicks shorter than 2 s
                bursts.append((max(0, (i - 5) * w), min(len(x), (j + 5) * w)))
            i = j
        else:
            i += 1
    return bursts


def fm_demod(seg):
    y = sosfiltfilt(butter(4, [800, 2800], "bandpass", fs=FS, output="sos"), seg)
    ph = np.unwrap(np.angle(hilbert(y)))
    f = np.diff(ph) * FS / (2 * np.pi)
    return sosfiltfilt(butter(3, 900, "low", fs=FS, output="sos"), f)


def estimate_bit_period(bits):
    """Pick the bit period (tape speed error) that gives the fewest framing errors.

    Run-length fitting is unreliable here: some recordings have stray 1.5- and
    2.5-bit runs that pull a fit off by several percent, so measure decode quality
    directly on a 10 s sample from the middle of the burst (the start is leader noise).
    """
    nominal = FS / BAUD
    mid = len(bits) // 2
    sample = bits[max(0, mid - FS * 5): mid + FS * 5]
    periods = np.arange(nominal * 0.92, nominal * 1.08, 0.25)
    rates = []
    for T in periods:
        data, _, ferr = uart(sample, T)
        rates.append(sum(ferr) / max(len(data), 1))
    rates = np.array(rates)
    # usually a plateau of equally good periods: take its middle, not an edge
    good = periods[rates <= rates.min() + 0.002]
    return float(np.median(good))


def uart(bits, T):
    """8N1 async decode. bits: 1 = mark (idle). Returns bytes, times, framing errors.

    Each bit boundary is re-synchronised to any transition found near where it is
    expected, so tape wow and a slightly-off T don't push late bits onto an edge.
    """
    out, pos, ferr = [], [], []
    i, n = 1, len(bits)
    win = int(T * 0.35)
    while i < n - int(T * 11):
        if bits[i - 1] == 1 and bits[i] == 0 and bits[int(i + T / 2)] == 0:
            edge, b = float(i), []
            for _ in range(9):
                edge += T
                lo, hi = int(edge) - win, int(edge) + win
                trans = np.flatnonzero(bits[lo:hi] != bits[lo - 1:hi - 1])
                if len(trans):
                    edge = lo + trans[np.argmin(abs(lo + trans - edge))]
                b.append(int(bits[int(edge + T / 2)]))
            out.append(sum(b[j] << j for j in range(8)))
            ferr.append(b[8] != 1)
            pos.append(i / FS)
            i = int(edge + T * 0.6)
        else:
            i += 1
    return out, np.array(pos), ferr


def decode(path, max_seconds=None, log=print):
    """Demodulate one recording. Returns (duration in s, list of Part)."""
    x = load(path, max_seconds)
    bursts = find_bursts(x)
    log(f"{path}: {len(x) / FS:.0f} s, {len(bursts)} carrier bursts")
    parts = []
    for k, (a, z) in enumerate(bursts):
        f = fm_demod(x[a:z])
        bits = (f < SLICE_HZ).astype(np.int64)
        T = estimate_bit_period(bits)
        data, pos, ferr = uart(bits, T)
        if not data:
            continue
        cuts = [0] + [j + 1 for j in np.flatnonzero(np.diff(pos) > GAP)] + [len(data)]
        log(f" burst {k} @ {a / FS:7.1f}s  {(z - a) / FS:5.1f}s  ~{FS / T:.0f} baud")
        for p, (s, e) in enumerate(zip(cuts, cuts[1:])):
            if e - s < MIN_PART:
                continue
            parts.append(Part(k, p, a / FS + pos[s], FS / T, bytes(data[s:e]), sum(ferr[s:e])))
    return len(x) / FS, parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("outdir")
    ap.add_argument("--max-seconds", type=float)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.audio))[0]
    _, parts = decode(args.audio, args.max_seconds)
    for pt in parts:
        name = f"{stem}_{pt.name}.cept"
        with open(os.path.join(args.outdir, name), "wb") as fh:
            fh.write(pt.data)
        flag = f"  FRAMING ERRORS: {pt.framing_errors}" if pt.framing_errors else ""
        print(f"   {name}  @ {pt.time:7.2f}s  {len(pt.data):5d} bytes{flag}")


if __name__ == "__main__":
    main()
