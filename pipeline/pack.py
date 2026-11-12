"""Pack the binary building files for the web page: web/public/data/*.pack.

build.py and lost.py write plain arrays (*.bin), which the other pipeline steps read. The page
loads these smaller copies instead (web/src/pack.js unpacks them); the .bin files stay out of the
upload (web/public/.assetsignore). Each .pack file is gzip data:
  - positions: lon/lat rounded to STEP degrees (under 25 cm), as the difference from the vertex
    before, int32 with the four bytes of all values stored one after the other
  - counts: vertices per building, uint16 (in place of the start indices)
  - bases, heights: decimetres, uint16
  - years, tiers, info: as they are

Run last: uv run pipeline/pack.py
"""
import gzip
import pathlib

import numpy as np

OUT = pathlib.Path(__file__).resolve().parent.parent / "web" / "public" / "data"
STEP = 2e-6


def write(name, arr):
    data = gzip.compress(np.ascontiguousarray(arr).tobytes(), 9, mtime=0)
    (OUT / name).write_bytes(data)
    return len(data)


def deltas(xy):
    q = np.round(xy.astype(float) / STEP).astype(np.int64)
    d = np.diff(q, axis=0, prepend=0).astype("<i4").reshape(-1)
    return d.view("u1").reshape(-1, 4).T     # low bytes first, then the next, ...


def decimetres(metres):
    dm = np.round(np.asarray(metres, float) * 10)
    assert dm.min() >= 0 and dm.max() < 65536
    return dm.astype("<u2")


def counts(starts):
    n = np.diff(starts)
    assert n.max() < 65536
    return n.astype("<u2")


def pack(prefix, size):
    read = lambda name, dtype: np.fromfile(OUT / f"{prefix}{name}.bin", dtype)
    pos = read("positions", "<f4").reshape(-1, size)
    starts = read("starts", "<u4")
    before = sum((OUT / f"{prefix}{n}.bin").stat().st_size for n in ("positions", "starts", "heights", "years"))
    after = write(f"{prefix}positions.pack", deltas(pos[:, :2]))
    after += write(f"{prefix}counts.pack", counts(starts))
    after += write(f"{prefix}heights.pack", decimetres(read("heights", "<f4")))
    after += write(f"{prefix}years.pack", read("years", "<u2"))
    if size == 3:   # the ground level, one per building
        after += write(f"{prefix}bases.pack", decimetres(pos[starts[:-1], 2]))
    for name in ("tiers", "info"):
        if (OUT / f"{prefix}{name}.bin").exists():
            before += (OUT / f"{prefix}{name}.bin").stat().st_size
            after += write(f"{prefix}{name}.pack", read(name, "u1"))
    print(f"{prefix or 'buildings.'} {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    pack("", 3)
    if (OUT / "lost.positions.bin").exists():
        pack("lost.", 2)
