"""
QR-koder, skrivna från grunden (bara det som följer med Python).

En QR-kod är ett rutnät av svarta och vita rutor ("moduler"). Så här byggs den:

  1. Texten blir bytes, och framför läggs "läge" (bytes) och längden.
  2. Felkorrigering (Reed-Solomon) läggs till, så att koden går att läsa
     även om en del av den är smutsig eller skymd.
  3. Fasta mönster ritas: de tre stora fyrkanterna i hörnen (så att kameran
     hittar koden), tidsrandarna och de små justeringsrutorna.
  4. Datan ritas i sicksack nerifrån och upp, två kolumner i taget.
  5. Ett av åtta "masker" läggs över datan så att det inte blir stora
     enfärgade fält. Vi provar alla åtta och tar den som ser bäst ut.

Används för att visa serverns adress som QR-kod i terminalen och på
startsidan, så att man kan skanna den med mobilkameran.

    from server.qrkod import QrKod
    qr = QrKod.skapa("https://exempel.ngrok-free.dev")
    print(qr.terminal())
    svg = qr.svg()
"""

from __future__ import annotations

from typing import List, Tuple

# Felkorrigeringsnivå: hur stor del av koden som kan vara förstörd.
# L ~7 %, M ~15 %, Q ~25 %, H ~30 %. Siffran är nivåns bitar i formatinfon.
NIVAER = {"L": 1, "M": 0, "Q": 3, "H": 2}
NIVA_INDEX = {"L": 0, "M": 1, "Q": 2, "H": 3}

# Ur QR-standarden: antal felkorrigeringsbytes per block, och antal block,
# för version 1-10 (index 0 används inte).
ECC_PER_BLOCK = [
    [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18],  # L
    [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26],  # M
    [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24],  # Q
    [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28],  # H
]
ANTAL_BLOCK = [
    [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4],  # L
    [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5],  # M
    [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8],  # Q
    [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8],  # H
]
MAX_VERSION = 10


# --- Reed-Solomon i GF(256) --------------------------------------------------

def _gf_mul(x: int, y: int) -> int:
    """Multiplikation i den ändliga kroppen GF(2^8) med polynomet 0x11D."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> List[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: List[int], divisor: List[int]) -> List[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _raw_modules(version: int) -> int:
    """Hur många moduler som blir över för data när de fasta mönstren är ritade."""
    result = (16 * version + 128) * version + 64
    if version >= 2:
        n = version // 7 + 2
        result -= (25 * n - 10) * n - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version: int, niva: str) -> int:
    i = NIVA_INDEX[niva]
    return _raw_modules(version) // 8 - ECC_PER_BLOCK[i][version] * ANTAL_BLOCK[i][version]


def _alignment_positions(version: int, size: int) -> List[int]:
    if version == 1:
        return []
    n = version // 7 + 2
    step = (version * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    result = [size - 7 - i * step for i in range(n - 1)] + [6]
    return list(reversed(result))


class QrKod:
    def __init__(self, version: int, niva: str):
        self.version = version
        self.niva = niva
        self.size = version * 4 + 17
        self.moduler = [[False] * self.size for _ in range(self.size)]
        self._fast = [[False] * self.size for _ in range(self.size)]

    # --- Skapa -----------------------------------------------------------

    @classmethod
    def skapa(cls, text: str, niva: str = "M") -> "QrKod":
        """Gör en QR-kod av texten, i den minsta versionen som räcker."""
        data = text.encode("utf-8")
        for version in range(1, MAX_VERSION + 1):
            length_bits = 8 if version <= 9 else 16
            needed = 4 + length_bits + 8 * len(data)
            capacity = _data_codewords(version, niva) * 8
            if needed <= capacity:
                break
        else:
            raise ValueError(f"Texten är för lång för en QR-kod här ({len(data)} bytes)")

        bits: List[int] = []

        def add(value: int, count: int) -> None:
            bits.extend((value >> i) & 1 for i in reversed(range(count)))

        add(0b0100, 4)  # läge: bytes
        add(len(data), length_bits)
        for b in data:
            add(b, 8)
        add(0, min(4, capacity - len(bits)))  # avslut
        add(0, (-len(bits)) % 8)
        codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
        pad = 0xEC
        while len(codewords) < capacity // 8:
            codewords.append(pad)
            pad ^= 0xEC ^ 0x11

        qr = cls(version, niva)
        qr._draw_function_patterns()
        qr._draw_codewords(qr._add_ecc(codewords))
        qr._choose_mask()
        return qr

    def _add_ecc(self, data: List[int]) -> List[int]:
        i = NIVA_INDEX[self.niva]
        num_blocks = ANTAL_BLOCK[i][self.version]
        ecc_len = ECC_PER_BLOCK[i][self.version]
        raw = _raw_modules(self.version) // 8
        num_short = num_blocks - raw % num_blocks
        short_len = raw // num_blocks
        divisor = _rs_divisor(ecc_len)
        blocks = []
        k = 0
        for b in range(num_blocks):
            take = short_len - ecc_len + (0 if b < num_short else 1)
            dat = data[k:k + take]
            k += take
            ecc = _rs_remainder(dat, divisor)
            if b < num_short:
                dat = dat + [0]
            blocks.append(dat + ecc)
        result = []
        for col in range(len(blocks[0])):
            for b, block in enumerate(blocks):
                if col != short_len - ecc_len or b >= num_short:
                    result.append(block[col])
        return result

    # --- Rita ------------------------------------------------------------

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.moduler[y][x] = dark
        self._fast[y][x] = True

    def _draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):  # tidsrandar
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):  # hörnfyrkanter
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _alignment_positions(self.version, size)
        last = len(positions) - 1
        for a, ax in enumerate(positions):  # justeringsrutor
            for b, ay in enumerate(positions):
                if (a, b) in ((0, 0), (0, last), (last, 0)):
                    continue  # där sitter hörnfyrkanterna
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format(0)  # reservera platsen, ritas om när masken är vald
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self._set(a, b, bit)
                self._set(b, a, bit)

    def _draw_format(self, mask: int) -> None:
        size = self.size
        data = NIVAER[self.niva] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, size - 15 + i, bit(i))
        self._set(8, size - 8, True)  # alltid svart

    def _draw_codewords(self, data: List[int]) -> None:
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5  # hoppa över den lodräta tidsranden
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = size - 1 - vert if upward else vert
                    if not self._fast[y][x] and i < len(data) * 8:
                        self.moduler[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    # --- Masker ------------------------------------------------------------

    @staticmethod
    def _mask_bit(mask: int, x: int, y: int) -> bool:
        return [
            (x + y) % 2 == 0,
            y % 2 == 0,
            x % 3 == 0,
            (x + y) % 3 == 0,
            (x // 3 + y // 2) % 2 == 0,
            x * y % 2 + x * y % 3 == 0,
            (x * y % 2 + x * y % 3) % 2 == 0,
            ((x + y) % 2 + x * y % 3) % 2 == 0,
        ][mask]

    def _apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self._fast[y][x] and self._mask_bit(mask, x, y):
                    self.moduler[y][x] = not self.moduler[y][x]

    def _choose_mask(self) -> None:
        best: Tuple[int, int] = (1 << 30, 0)
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format(mask)
            best = min(best, (self._penalty(), mask))
            self._apply_mask(mask)  # ta bort igen (XOR två gånger)
        mask = best[1]
        self._apply_mask(mask)
        self._draw_format(mask)
        self.mask = mask

    def _penalty(self) -> int:
        """Poäng för hur svår koden är att läsa (lägre är bättre), som i standarden."""
        size = self.size
        m = self.moduler
        score = 0
        lines = [m[y] for y in range(size)] + [[m[y][x] for y in range(size)] for x in range(size)]
        pattern_a = [True, False, True, True, True, False, True, False, False, False, False]
        pattern_b = pattern_a[::-1]
        for line in lines:
            run, color = 0, None
            for dark in line:
                if dark == color:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run, color = 1, dark
            if run >= 5:
                score += 3 + run - 5
            for i in range(size - 10):
                window = line[i:i + 11]
                if window == pattern_a or window == pattern_b:
                    score += 40
        for y in range(size - 1):
            for x in range(size - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(row.count(True) for row in m)
        total = size * size
        score += abs(dark * 20 - total * 10) // total * 10
        return score

    # --- Visa ------------------------------------------------------------

    def rutor(self, kant: int = 4) -> List[List[bool]]:
        """Rutnätet med en vit kant runt (standarden vill ha minst 4 rutor)."""
        size = self.size + 2 * kant
        rows = [[False] * size for _ in range(size)]
        for y in range(self.size):
            for x in range(self.size):
                rows[y + kant][x + kant] = self.moduler[y][x]
        return rows

    def svg(self, kant: int = 4) -> str:
        """Koden som SVG-bild (skalar till vilken storlek som helst)."""
        rows = self.rutor(kant)
        size = len(rows)
        parts = []
        for y, row in enumerate(rows):
            x = 0
            while x < size:
                if row[x]:
                    start = x
                    while x < size and row[x]:
                        x += 1
                    parts.append(f"M{start},{y}h{x - start}v1h-{x - start}z")
                else:
                    x += 1
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'shape-rendering="crispEdges" role="img" aria-label="QR-kod">'
            f'<rect width="{size}" height="{size}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(parts)}"/></svg>'
        )

    def terminal(self, kant: int = 2) -> str:
        """
        Koden för Terminal-fönstret. Varje tecken är två rutor ovanför varandra
        (halvblocket ▀ med olika för- och bakgrundsfärg). Färgerna är alltid
        svart på vitt, även om terminalen har mörk bakgrund.
        """
        rows = self.rutor(kant)
        if len(rows) % 2:
            rows.append([False] * len(rows[0]))
        black, white = 16, 231
        out = []
        for y in range(0, len(rows), 2):
            line = []
            last = None
            for top, bottom in zip(rows[y], rows[y + 1]):
                colors = (black if top else white, black if bottom else white)
                if colors != last:  # byt färg bara när det behövs
                    line.append(f"\x1b[38;5;{colors[0]};48;5;{colors[1]}m")
                    last = colors
                line.append("▀")
            out.append("".join(line) + "\x1b[0m")
        return "\n".join(out)
