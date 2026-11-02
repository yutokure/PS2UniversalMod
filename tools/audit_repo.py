"""Audit what git tracks (or has staged) for game data, binaries, large files and secrets.

    python tools/audit_repo.py            # every tracked file
    python tools/audit_repo.py --staged   # only what is staged for the next commit

Exit status 1 when anything looks like game data or a secret.  The checks look at the file
*content* as well as the name: magic numbers of images, archives and ELF/ISO files, NUL bytes in
a file that is not a known text type, size, and credential-looking text.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAX_BYTES = 1_000_000
BAD_EXT = {".iso", ".chd", ".cso", ".zso", ".cue", ".mdf", ".nrg", ".img", ".bin", ".elf", ".irx",
           ".p2s", ".ps2", ".mcd", ".psu", ".max", ".cbs", ".xps", ".sav", ".srm", ".dmp", ".raw",
           ".gpr", ".rep", ".gzf", ".zip", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".bmp", ".gif",
           ".mp4", ".webm", ".avi", ".exe", ".dll", ".pyd", ".log", ".bak", ".tmp", ".zst", ".gz"}
BAD_PARTS = {"bios", "games", "savestates", "sstates", "memcards", "memory_dumps", "dumps",
             "ghidra_projects", "extracted", "extracted_data", "screenshots", "recordings",
             "test_evidence", "work", "shots"}
MAGICS = {b"\x7fELF": "ELF", b"PK\x03\x04": "zip", b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg",
          b"GIF8": "gif", b"7z\xbc\xaf": "7z", b"(\xb5/\xfd": "zstd", b"\x1f\x8b": "gzip",
          b"CD001": "iso9660"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".bat", ".java", ".ini", ".yml", ".yaml", ".toml", ".cfg", ""}
SECRET = re.compile(r"(api[_-]?key|secret|passwd|password|bearer\s+[A-Za-z0-9]|token\s*[:=]\s*['\"][A-Za-z0-9]{16,})",
                    re.IGNORECASE)
SECRET_OK = {"tools/audit_repo.py", ".gitignore"}


def files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    out = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    staged = "--staged" in sys.argv
    names = files(staged)
    problems: list[str] = []
    total = 0
    for name in names:
        path = REPO / name
        parts = {p.lower() for p in Path(name).parts[:-1]}
        ext = path.suffix.lower()
        if ext in BAD_EXT:
            problems.append(f"{name}: extension {ext}")
        if parts & BAD_PARTS:
            problems.append(f"{name}: in a data directory ({sorted(parts & BAD_PARTS)})")
        if not path.exists():
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_BYTES:
            problems.append(f"{name}: {size} bytes")
        head = path.read_bytes()[:4096] if size else b""
        for magic, kind in MAGICS.items():
            if head.startswith(magic) or (kind == "iso9660" and magic in head[:40000]):
                problems.append(f"{name}: content looks like {kind}")
        if b"\x00" in head and ext not in TEXT_EXT - {""}:
            problems.append(f"{name}: binary content (NUL bytes)")
        if ext in TEXT_EXT and name not in SECRET_OK:
            text = path.read_text(encoding="utf-8", errors="replace")
            m = SECRET.search(text)
            if m:
                problems.append(f"{name}: secret-like text '{m.group(0)[:30]}'")
    print(f"{len(names)} {'staged' if staged else 'tracked'} files, {total / 1024:.0f} KiB")
    for p in problems:
        print("  PROBLEM", p)
    print("AUDIT", "FAILED" if problems else "PASSED")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
