"""
Game codes, for example "ABCDEF".

The game shows the code as six letters, but sends it as a single number
(int32) over the network. Here are functions to go back and forth.

The letters are mixed with a special order (V2) that Among Us came up with.
"""

from __future__ import annotations

import secrets

ALPHABET = "QWXRTYLPESDFGHUJKZOCVBINMA"
# For every letter A-Z: which place it has in ALPHABET.
LETTER_INDEX = {letter: ALPHABET.index(letter) for letter in ALPHABET}


def code_to_int(code: str) -> int:
    """'ABCDEF' -> the number the game sends. Returns -1 if the code is invalid."""
    code = code.upper()
    if len(code) != 6 or any(c not in LETTER_INDEX for c in code):
        return -1
    a, b, c, d, e, f = (LETTER_INDEX[ch] for ch in code)
    one = (a + 26 * b) & 0x3FF
    two = c + 26 * (d + 26 * (e + 26 * f))
    value = one | ((two << 10) & 0x3FFFFC00) | 0x80000000
    # Turn it into a negative number just like int32 in the game.
    return value - (1 << 32)


def int_to_code(value: int) -> str:
    """The number from the game -> 'ABCDEF'."""
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
