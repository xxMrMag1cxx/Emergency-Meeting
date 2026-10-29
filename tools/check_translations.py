"""
Finds text in the server's terminal window that has no translation yet.

    python3 tools/check_translations.py          (Swedish)
    python3 tools/check_translations.py sv

It looks through server/*.py for
  - log messages:  log.info("...")  (not log.debug, those are never translated)
  - tr("...")
  - the commands' usage and explanation: console.add("name", "/usage", "Explanation", ...)
and checks that every text is in server/locales/<language>.json, and that
the placeholders (%s and {name}) are the same in both languages.
"""

import ast
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LEVELS = {"info", "warning", "error", "exception", "critical"}
PERCENT = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdifrxX%]")
BRACES = re.compile(r"\{(\w*)[^{}]*\}")


def texts(path: Path):
    """(line, kind, text) for every translatable text in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in LEVELS and isinstance(func.value, ast.Name) \
                and func.value.id == "log":
            yield node.lineno, "log", first.value
        elif isinstance(func, ast.Name) and func.id == "tr":
            yield node.lineno, "tr", first.value
        elif isinstance(func, ast.Attribute) and func.attr == "add" and isinstance(func.value, ast.Name) \
                and func.value.id == "console" and len(node.args) >= 3:
            for arg in node.args[1:3]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield node.lineno, "tr", arg.value


def main() -> int:
    language = sys.argv[1] if len(sys.argv) > 1 else "sv"
    catalog = json.loads((PROJECT / "server" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    missing = broken = 0
    for path in sorted((PROJECT / "server").glob("*.py")):
        for line, kind, text in texts(path):
            where = f"{path.relative_to(PROJECT)}:{line}"
            if text not in catalog:
                missing += 1
                print(f"Missing  {where}  {text!r}")
                continue
            pattern = PERCENT if kind == "log" else BRACES
            if pattern.findall(text) != pattern.findall(catalog[text]):
                broken += 1
                print(f"Placeholders differ  {where}\n    {text!r}\n    {catalog[text]!r}")
    print(f"\n{missing} missing, {broken} with different placeholders ({len(catalog)} translations in {language}.json)")
    return 1 if missing or broken else 0


if __name__ == "__main__":
    sys.exit(main())
