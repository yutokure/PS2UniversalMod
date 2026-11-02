"""Audit what git holds for game data, binaries, large files and secrets.

What is inspected depends on the mode (the report names it):

    python tools/audit_repo.py                  # WORKING TREE: every tracked file, as it is on disk now
    python tools/audit_repo.py --staged         # INDEX: what the next commit will contain
    python tools/audit_repo.py --commit REV     # COMMIT: every file of that commit's tree
    python tools/audit_repo.py --history        # HISTORY: every blob ever committed, deleted ones too
    python tools/audit_repo.py --repo PATH ...  # audit another repository (the tests use temporary ones)

``--staged`` is the mode to run before committing.  It reads the blobs the index holds
(``git ls-files --stage`` + ``git cat-file``), not the files on disk, so editing or deleting a file
after ``git add`` can neither hide a forbidden file from the audit nor trigger a false alarm.  Only
entries that are new or changed against HEAD are audited (a deletion adds nothing to the commit, and
a rename is audited as its new path); with no HEAD yet, everything staged is.

Exit status 1 when anything looks like game data or a secret.  The checks look at the file
*content* as well as the name: magic numbers of images, archives and ELF/ISO files, NUL bytes in
a file that is not a known text type, size, and credential-looking text.  Large blobs are only read
as far as the checks need (the first 4 KiB and the ISO9660 marker), never in full.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator

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
          b"GIF8": "gif", b"7z\xbc\xaf": "7z", b"(\xb5/\xfd": "zstd", b"\x1f\x8b": "gzip"}
#: an ISO9660 image carries its identifier at byte 0x8001
ISO_OFFSET, ISO_ID = 0x8001, b"CD" + b"001"
TEXT_EXT = {".py", ".md", ".txt", ".json", ".bat", ".java", ".ini", ".yml", ".yaml", ".toml", ".cfg", ""}
SECRET = re.compile(r"(api[_-]?key|secret|passwd|password|bearer\s+[A-Za-z0-9]|token\s*[:=]\s*['\"][A-Za-z0-9]{16,})",
                    re.IGNORECASE)
SECRET_OK = {"tools/audit_repo.py", ".gitignore"}
#: bytes read from the start of a file for the magic-number and NUL checks
HEAD_BYTES = 4096
GITLINK = "160000"


class AuditError(RuntimeError):
    pass


class NotABlob(AuditError):
    pass


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True)
    if proc.returncode != 0:
        raise AuditError(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def _path(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


class Entry:
    """One file to audit: its name, size and a way to read a byte range of its content."""

    def __init__(self, name: str, size: int | None, read: Callable[[int, int], bytes]) -> None:
        self.name = name
        self.size = size
        self._read = read

    def read(self, offset: int, count: int) -> bytes:
        return self._read(offset, count)


class Blobs:
    """Reads blobs from the object database with two long-lived ``git cat-file`` processes."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self._check = subprocess.Popen(["git", "cat-file", "--batch-check"], cwd=repo,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._batch = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def close(self) -> None:
        for proc in (self._check, self._batch):
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()

    def info(self, sha: str) -> tuple[str, int]:
        """(object type, size) without reading the object."""
        self._check.stdin.write(sha.encode() + b"\n")
        self._check.stdin.flush()
        parts = self._check.stdout.readline().split()
        if len(parts) != 3 or parts[1] == b"missing":
            raise AuditError(f"object {sha} not found")
        return parts[1].decode(), int(parts[2])

    def read_all(self, sha: str) -> bytes:
        """The whole blob; only used for blobs no larger than MAX_BYTES."""
        self._batch.stdin.write(sha.encode() + b"\n")
        self._batch.stdin.flush()
        parts = self._batch.stdout.readline().split()
        if len(parts) != 3:
            raise AuditError(f"object {sha} not found")
        size = int(parts[2])
        data = self._batch.stdout.read(size)
        self._batch.stdout.read(1)               # the newline that ends each reply
        return data

    def read_range(self, sha: str, offset: int, count: int) -> bytes:
        """A slice of a large blob: stream it and stop after the bytes needed."""
        proc = subprocess.Popen(["git", "cat-file", "blob", sha], cwd=self.repo,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            data = proc.stdout.read(offset + count)
        finally:
            proc.kill()
            proc.wait()
        return data[offset:offset + count]

    def entry(self, name: str, sha: str) -> Entry:
        kind, size = self.info(sha)
        if kind != "blob":
            raise NotABlob(sha)
        cache: list[bytes] = []

        def read(offset: int, count: int) -> bytes:
            if size <= MAX_BYTES:
                if not cache:
                    cache.append(self.read_all(sha))
                return cache[0][offset:offset + count]
            return self.read_range(sha, offset, count)

        return Entry(name, size, read)


# --- where the entries come from ------------------------------------------------------------------
def worktree_entries(repo: Path) -> tuple[str, list[Entry]]:
    names = [_path(n) for n in _git(repo, "ls-files", "-z").split(b"\0") if n]
    entries = []
    for name in names:
        path = repo / name
        if not path.exists():                    # tracked but deleted on disk: only the name is checked
            entries.append(Entry(name, None, lambda o, c: b""))
            continue

        def read(offset: int, count: int, path=path) -> bytes:
            with path.open("rb") as fh:
                fh.seek(offset)
                return fh.read(count)
        entries.append(Entry(name, path.stat().st_size, read))
    return "tracked files (working tree content)", entries


def index_entries(repo: Path, blobs: Blobs) -> tuple[str, list[Entry]]:
    """Files the next commit adds or changes, with the content the index holds for them."""
    has_head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo,
                              capture_output=True).returncode == 0
    entries = []
    if has_head:
        # --no-renames: a rename shows as delete + add, so the new path is always audited
        raw = _git(repo, "diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev",
                   "--diff-filter=ACMT").split(b"\0")
        # records: ":oldmode newmode oldsha newsha S" NUL path NUL
        for meta, path in zip(raw[0::2], raw[1::2]):
            fields = meta.lstrip(b":").split()
            if len(fields) < 5 or fields[1].decode() == GITLINK:
                continue
            entries.append(blobs.entry(_path(path), fields[3].decode()))
    else:
        for record in _git(repo, "ls-files", "--stage", "-z").split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, sha, _stage = meta.decode().split()
            if mode != GITLINK:
                entries.append(blobs.entry(_path(path), sha))
    return "staged changes (Git index content)", entries


def commit_entries(repo: Path, blobs: Blobs, rev: str) -> tuple[str, list[Entry]]:
    out = _git(repo, "ls-tree", "-r", "-z", rev)
    entries = []
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, kind, sha = meta.decode().split()
        if kind == "blob":
            entries.append(blobs.entry(_path(path), sha))
    return f"commit {rev} (committed content)", entries


def history_entries(repo: Path, blobs: Blobs) -> tuple[str, list[Entry]]:
    """Every blob reachable from any ref, under every path it was ever committed as."""
    seen: set[tuple[str, str]] = set()
    entries = []
    for line in _git(repo, "rev-list", "--objects", "--all").splitlines():
        sha, _, name = line.decode("utf-8", "surrogateescape").partition(" ")
        if not name or (sha, name) in seen:
            continue
        seen.add((sha, name))
        try:
            entries.append(blobs.entry(name, sha))
        except NotABlob:                        # the listing holds trees too
            continue
    return "all history (every committed blob)", entries


# --- the checks ----------------------------------------------------------------------------------
def check(entry: Entry) -> list[str]:
    name = entry.name
    problems: list[str] = []
    # data directories are top-level (docs/games/ is documentation, not a game folder)
    parts = {p.lower() for p in Path(name).parts[:1]} if len(Path(name).parts) > 1 else set()
    ext = Path(name).suffix.lower()
    if ext in BAD_EXT:
        problems.append(f"{name}: extension {ext}")
    if parts & BAD_PARTS:
        problems.append(f"{name}: in a data directory ({sorted(parts & BAD_PARTS)})")
    size = entry.size
    if size is None:
        return problems
    if size > MAX_BYTES:
        problems.append(f"{name}: {size} bytes")
    head = entry.read(0, HEAD_BYTES) if size else b""
    for magic, kind in MAGICS.items():
        if head.startswith(magic):
            problems.append(f"{name}: content looks like {kind}")
    if size > ISO_OFFSET + 8 and entry.read(ISO_OFFSET, 5) == ISO_ID:
        problems.append(f"{name}: content looks like an ISO9660 image")
    if b"\x00" in head and ext not in TEXT_EXT - {""}:
        problems.append(f"{name}: binary content (NUL bytes)")
    if ext in TEXT_EXT and name not in SECRET_OK and size <= MAX_BYTES:
        text = entry.read(0, size).decode("utf-8", errors="replace")
        m = SECRET.search(text)
        if m:
            problems.append(f"{name}: secret-like text '{m.group(0)[:30]}'")
    return problems


def audit(entries: Iterable[Entry]) -> tuple[int, int, list[str]]:
    count = total = 0
    problems: list[str] = []
    for entry in entries:
        count += 1
        total += entry.size or 0
        problems.extend(check(entry))
    return count, total, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], add_help=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="audit the Git index (run before committing)")
    mode.add_argument("--commit", metavar="REV", help="audit the tree of an existing commit")
    mode.add_argument("--history", action="store_true", help="audit every blob in the repository history")
    ap.add_argument("--repo", type=Path, default=REPO, help="repository to audit (default: this one)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:  # noqa: BLE001
            pass
    repo = args.repo.resolve()
    blobs = None
    try:
        if args.staged or args.commit or args.history:
            blobs = Blobs(repo)
        if args.staged:
            label, entries = index_entries(repo, blobs)
        elif args.commit:
            label, entries = commit_entries(repo, blobs, args.commit)
        elif args.history:
            label, entries = history_entries(repo, blobs)
        else:
            label, entries = worktree_entries(repo)
        count, total, problems = audit(entries)
    except AuditError as exc:
        print(f"AUDIT ERROR {exc}")
        return 2
    finally:
        if blobs is not None:
            blobs.close()
    print(f"{count} files, {total / 1024:.0f} KiB  [{label}]")
    for p in problems:
        print("  PROBLEM", p)
    print("AUDIT", "FAILED" if problems else "PASSED")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
