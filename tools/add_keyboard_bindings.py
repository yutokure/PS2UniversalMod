"""Add keyboard bindings to PCSX2's Pad1 section without touching the existing
SDL (physical controller) bindings.

Rationale: the automated harness needs a deterministic way to walk the
character, and the MCP's keyboard backend is the only input path available in
this PCSX2 build (the native qPcsx2 `input_set` verb is broken, see
BLOCKERS B-02).  Physical pad bindings are preserved verbatim.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

INI = _paths.PCSX2_DIR / "inis" / "PCSX2.ini"

KEYBOARD = {
    "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
    "Triangle": "I", "Circle": "L", "Cross": "K", "Square": "J",
    "Select": "Backspace", "Start": "Return",
    "L1": "Q", "L2": "1", "R1": "E", "R2": "3",
    "L3": "Z", "R3": "C",
    "LUp": "W", "LDown": "S", "LLeft": "A", "LRight": "D",
    "RUp": "T", "RDown": "G", "RLeft": "F", "RRight": "H",
}


def main() -> None:
    text = INI.read_text(encoding="utf-8")
    backup = INI.with_suffix(".ini.padkey-backup")
    if not backup.exists():
        shutil.copy2(INI, backup)
    out = []
    in_pad = False
    seen_keyboard = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_pad = stripped == "[Pad1]"
        if in_pad and "= Keyboard/" in line:
            key = line.split("=")[0].strip()
            seen_keyboard.add(key)
        out.append(line)
    if not in_pad and "[Pad1]" not in text:
        sys.exit("no [Pad1] section")

    # rebuild: insert keyboard lines right after the matching SDL line
    result = []
    in_pad = False
    added = 0
    for line in out:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_pad = stripped == "[Pad1]"
        result.append(line)
        if in_pad and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in KEYBOARD and key not in seen_keyboard and "SDL-" in line:
                result.append(f"{key} = Keyboard/{KEYBOARD[key]}")
                added += 1
    INI.write_text("\n".join(result) + "\n", encoding="utf-8")
    print(f"added {added} keyboard bindings to {INI}")
    print("backup:", backup)


if __name__ == "__main__":
    main()
