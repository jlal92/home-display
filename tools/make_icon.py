"""Draws the Home Screen icon (a simple calendar) with only the Python standard library.

    python tools/make_icon.py        ->  server/static/apple-touch-icon.png  (180x180)

iOS rounds the corners itself, so the artwork is a full square.
"""
import os
import struct
import zlib

SIZE = 180
SS = 4  # supersampling for smooth edges
W = SIZE * SS

BLUE = (31, 95, 139)
DARK = (23, 74, 107)
WHITE = (255, 255, 255)
YELLOW = (255, 210, 77)


def rrect(x, y, x0, y0, x1, y1, r):
    """True if (x, y) is inside the rounded rectangle."""
    if x < x0 or x >= x1 or y < y0 or y >= y1:
        return False
    cx = min(max(x, x0 + r), x1 - r - 1)
    cy = min(max(y, y0 + r), y1 - r - 1)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x, y):
    u = lambda v: v * SS  # design units (180 grid) to supersampled pixels
    # rings on top of the page
    for rx in (58, 112):
        if rrect(x, y, u(rx), u(20), u(rx + 10), u(46), u(5)):
            return WHITE
    # page
    if rrect(x, y, u(22), u(32), u(158), u(152), u(12)):
        if y < u(62):
            return DARK  # header band
        # grid of days: 4 columns x 3 rows
        for row in range(3):
            for col in range(4):
                x0 = 36 + col * 31
                y0 = 74 + row * 25
                if rrect(x, y, u(x0), u(y0), u(x0 + 24), u(y0 + 18), u(4)):
                    return YELLOW if (row, col) == (1, 2) else BLUE
        return WHITE
    return BLUE


def main():
    rows = []
    for py in range(SIZE):
        row = bytearray([0])  # PNG filter type 0
        for px in range(SIZE):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = pixel(px * SS + sx, py * SS + sy)
                    r += c[0]
                    g += c[1]
                    b += c[2]
            n = SS * SS
            row += bytes((r // n, g // n, b // n))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", "static", "apple-touch-icon.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(png)
    print("wrote", os.path.normpath(out), len(png), "bytes")


if __name__ == "__main__":
    main()
