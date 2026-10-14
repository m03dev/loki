"""QR codes with no dependencies: byte mode, error correction level M, versions 1-25.

Used by Settings > Connections: "scan with your phone" pop-ups (a provider's sign-up page,
a sign-in code, or the one-time page that sends a key from the phone to this computer).

    svg("https://openrouter.ai/keys")  -> an <svg> string, crisp at any size
    matrix("hello")                    -> list of rows of booleans (True = dark)

Standard library only, so it works on the Mac and the PC without installing anything.
Checked against an independent decoder (jsQR) in tests/test_connect_portal.py's fixtures.
"""
from __future__ import annotations

# --- tables (ISO/IEC 18004), level M: (ec codewords per block, [(blocks, data per block), ...])
_EC_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
    5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]), 11: (30, [(1, 50), (4, 51)]),
    12: (22, [(6, 36), (2, 37)]), 13: (22, [(8, 37), (1, 38)]), 14: (24, [(4, 40), (5, 41)]),
    15: (24, [(5, 41), (5, 42)]), 16: (28, [(7, 45), (3, 46)]), 17: (28, [(10, 46), (1, 47)]),
    18: (26, [(9, 43), (4, 44)]), 19: (26, [(3, 44), (11, 45)]), 20: (26, [(3, 41), (13, 42)]),
    21: (26, [(17, 42)]), 22: (28, [(17, 46)]), 23: (28, [(4, 47), (14, 48)]),
    24: (28, [(6, 45), (14, 46)]), 25: (28, [(8, 47), (13, 48)]),
}
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
    8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58],
    13: [6, 34, 62], 14: [6, 26, 46, 66], 15: [6, 26, 48, 70], 16: [6, 26, 50, 74],
    17: [6, 30, 54, 78], 18: [6, 30, 56, 82], 19: [6, 30, 58, 86], 20: [6, 34, 62, 90],
    21: [6, 28, 50, 72, 94], 22: [6, 26, 50, 74, 98], 23: [6, 30, 54, 78, 102],
    24: [6, 28, 54, 80, 106], 25: [6, 32, 58, 84, 110],
}
MAX_VERSION = 25

# --- GF(256) with polynomial 0x11d
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11d
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gmul(c, _EXP[i])
        poly = nxt
    return poly


def _ec_bytes(data: list, degree: int) -> list:
    gen = _generator(degree)
    rem = list(data) + [0] * degree
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gmul(gen[j], coef)
    return rem[len(data):]


def _capacity(version: int) -> int:
    return sum(n * k for n, k in _EC_M[version][1])


def _pick_version(nbytes: int) -> int:
    for v in range(1, MAX_VERSION + 1):
        count_bits = 8 if v <= 9 else 16
        if 4 + count_bits + 8 * nbytes <= 8 * _capacity(v):
            return v
    raise ValueError("text is too long for a QR code here (%d bytes)" % nbytes)


def _codewords(data: bytes, version: int) -> list:
    bits = []

    def put(value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                                  # byte mode
    put(len(data), 8 if version <= 9 else 16)
    for b in data:
        put(b, 8)
    total = 8 * _capacity(version)
    put(0, min(4, total - len(bits)))               # terminator
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    i = 0
    while len(words) < _capacity(version):
        words.append(pad[i % 2])
        i += 1
    # split into blocks, add error correction, interleave
    ec_len, groups = _EC_M[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(words[pos:pos + size])
            pos += size
    ecs = [_ec_bytes(b, ec_len) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for e in ecs:
            out.append(e[i])
    return out


def _bch(value: int, poly: int, poly_bits: int) -> int:
    value <<= poly_bits - 1
    top = poly.bit_length()
    while value.bit_length() >= top:
        value ^= poly << (value.bit_length() - top)
    return value


def _format_bits(mask: int) -> int:
    data = (0b00 << 3) | mask                       # level M = 00
    return ((data << 10) | _bch(data, 0b10100110111, 11)) ^ 0b101010000010010


def _version_bits(version: int) -> int:
    return (version << 12) | _bch(version, 0b1111100100101, 13)


_MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _base(version: int) -> tuple:
    size = 17 + 4 * version
    grid = [[None] * size for _ in range(size)]

    def finder(r0: int, c0: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < size and 0 <= cc < size:
                    dark = (0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6)) or \
                           (2 <= r <= 4 and 2 <= c <= 4)
                    grid[rr][cc] = dark

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)
    for i in range(8, size - 8):                   # timing patterns
        grid[6][i] = grid[i][6] = (i % 2 == 0)
    centers = _ALIGN[version]
    last = len(centers) - 1
    for i, r in enumerate(centers):
        for j, c in enumerate(centers):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue                            # these three overlap the finders
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    grid[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    grid[size - 8][8] = True                        # the dark module
    # reserve format areas (filled later)
    for i in range(9):
        if grid[8][i] is None:
            grid[8][i] = False
        if grid[i][8] is None:
            grid[i][8] = False
    for i in range(8):
        if grid[8][size - 1 - i] is None:
            grid[8][size - 1 - i] = False
        if grid[size - 1 - i][8] is None:
            grid[size - 1 - i][8] = False
    if version >= 7:
        bits = _version_bits(version)
        for i in range(18):
            dark = bool((bits >> i) & 1)
            r, c = i // 3, size - 11 + i % 3
            grid[r][c] = dark
            grid[c][r] = dark
    reserved = [[cell is not None for cell in row] for row in grid]
    return grid, reserved


def _place(grid: list, reserved: list, words: list) -> None:
    size = len(grid)
    bits = [(w >> (7 - i)) & 1 for w in words for i in range(8)]
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1                                # skip the vertical timing column
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not reserved[r][c]:
                    grid[r][c] = bool(bits[idx]) if idx < len(bits) else False
                    idx += 1
        upward = not upward
        col -= 2


def _apply_format(grid: list, mask: int) -> None:
    size = len(grid)
    bits = _format_bits(mask)
    for i in range(15):
        dark = bool((bits >> i) & 1)
        # around the top-left finder
        if i < 6:
            grid[i][8] = dark
        elif i < 8:
            grid[i + 1][8] = dark
        else:
            grid[8][14 - i if i >= 9 else 7] = dark
        # the copy split between the other two finders
        if i < 8:
            grid[8][size - 1 - i] = dark
        else:
            grid[size - 15 + i][8] = dark
    grid[size - 8][8] = True


def _penalty(g: list) -> int:
    size = len(g)
    score = 0
    for lines in (g, [list(col) for col in zip(*g)]):
        for line in lines:
            run, prev = 0, None
            for cell in line:
                if cell == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, cell
            if run >= 5:
                score += run - 2
            text = "".join("1" if x else "0" for x in line)
            score += 40 * (text.count("10111010000") + text.count("00001011101"))
    for r in range(size - 1):
        for c in range(size - 1):
            if g[r][c] == g[r][c + 1] == g[r + 1][c] == g[r + 1][c + 1]:
                score += 3
    dark = sum(cell for row in g for cell in row)
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


def matrix(text: str) -> list:
    """The QR code for `text` as rows of booleans (True = dark), quiet zone not included."""
    data = text.encode("utf-8")
    version = _pick_version(len(data))
    words = _codewords(data, version)
    base, reserved = _base(version)
    _place(base, reserved, words)
    best, best_score = None, None
    for mask in range(8):
        grid = [row[:] for row in base]
        fn = _MASKS[mask]
        for r in range(len(grid)):
            for c in range(len(grid)):
                if not reserved[r][c] and fn(r, c):
                    grid[r][c] = not grid[r][c]
        _apply_format(grid, mask)
        score = _penalty(grid)
        if best_score is None or score < best_score:
            best, best_score = grid, score
    return best


def svg(text: str, scale: int = 6, border: int = 4, dark: str = "#0d1117", light: str = "#ffffff") -> str:
    """An SVG image of the QR code (one path, crisp at any size)."""
    grid = matrix(text)
    size = len(grid) + 2 * border
    parts = []
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                parts.append("M%d %dh1v1h-1z" % (c + border, r + border))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'shape-rendering="crispEdges" role="img" aria-label="QR code">'
            '<rect width="100%%" height="100%%" fill="%s"/><path fill="%s" d="%s"/></svg>'
            % (size, size, size * scale, size * scale, light, dark, "".join(parts)))
