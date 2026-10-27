"""
Spelkoder, t.ex. "ABCDEF".

Spelet visar koden som sex bokstäver, men skickar den som ett enda tal
(int32) över nätverket. Här finns funktioner för att gå fram och tillbaka.

Bokstäverna blandas med en speciell ordning (V2) som Among Us hittade på.
"""

from __future__ import annotations

import secrets

ALPHABET = "QWXRTYLPESDFGHUJKZOCVBINMA"
# För varje bokstav A-Z: vilken plats den har i ALPHABET.
LETTER_INDEX = {letter: ALPHABET.index(letter) for letter in ALPHABET}


def code_to_int(code: str) -> int:
    """'ABCDEF' -> talet som spelet skickar. Returnerar -1 om koden är ogiltig."""
    code = code.upper()
    if len(code) != 6 or any(c not in LETTER_INDEX for c in code):
        return -1
    a, b, c, d, e, f = (LETTER_INDEX[ch] for ch in code)
    one = (a + 26 * b) & 0x3FF
    two = c + 26 * (d + 26 * (e + 26 * f))
    value = one | ((two << 10) & 0x3FFFFC00) | 0x80000000
    # Gör om till ett negativt tal precis som int32 i spelet.
    return value - (1 << 32)


def int_to_code(value: int) -> str:
    """Talet från spelet -> 'ABCDEF'."""
    value &= 0xFFFFFFFF
    a = value & 0x3FF
    b = (value >> 10) & 0xFFFFF
    return "".join(
        [
            ALPHABET[a % 26],
            ALPHABET[a // 26],
            ALPHABET[b % 26],
            ALPHABET[(b // 26) % 26],
            ALPHABET[(b // (26 * 26)) % 26],
            ALPHABET[(b // (26 * 26 * 26)) % 26],
        ]
    )


def random_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(6))
