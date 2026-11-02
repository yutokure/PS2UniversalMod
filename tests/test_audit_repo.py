"""tools/audit_repo.py must judge what git will commit, not what happens to be on disk (review finding P2).

Every test builds a throw-away repository and fills it with artificial data (dummy "ISO", "ELF" and
"zip" headers made of a few bytes); no real game file is ever read or copied.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[1] / "tools" / "audit_repo.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

#: bytes that look like a PS2 disc image: ISO9660 marker at 0x8001
FAKE_ISO = b"\0" * 0x8001 + b"CD001" + b"\0" * 64
FAKE_ELF = b"\x7fELF" + b"\x01" * 60
FAKE_ZIP = b"PK\x03\x04" + b"\0" * 30
# built from pieces so that this file does not trip the very audit it tests
CRED_WORD = "pass" + "word"
CRED_LINE = f'{CRED_WORD} = "hunter2hunter2"\n'


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.invalid"],
                     ["config", "core.autocrlf", "false"], ["config", "core.quotepath", "true"]):
            self.git(*args)

    def git(self, *args: str) -> str:
        out = subprocess.run(["git", *args], cwd=self.path, capture_output=True, check=True)
        return out.stdout.decode("utf-8", "replace")

    def write(self, rel: str, data: bytes | str) -> Path:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return p

    def add(self, *rels: str) -> None:
        self.git("add", "--", *rels)

    def commit(self, msg: str = "c") -> None:
        self.git("commit", "-q", "-m", msg)

    def audit(self, *flags: str) -> tuple[int, str]:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, "-X", "utf8", str(AUDIT), "--repo", str(self.path), *flags],
                              capture_output=True, env=env)
        return proc.returncode, proc.stdout.decode("utf-8", "replace")


@pytest.fixture()
def repo(tmp_path):
    return Repo(tmp_path / "r")


def staged(repo):
    return repo.audit("--staged")


# --- TEST-P2-01 ---------------------------------------------------------------------------------
def test_own_source_code_passes(repo):
    repo.write("core/a.py", "print('hello')\n")
    repo.write("README.md", "# readme\n")
    repo.add("core/a.py", "README.md")
    code, out = staged(repo)
    assert code == 0 and "AUDIT PASSED" in out and "Git index content" in out


def test_nothing_staged_passes(repo):
    repo.write("a.py", "x = 1\n")
    repo.add("a.py")
    repo.commit()
    code, out = staged(repo)
    assert code == 0 and out.startswith("0 files")


# --- TEST-P2-02 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("name, data, why", [
    ("game.iso", b"x", "extension .iso"),
    ("slot.p2s", b"x", "extension .p2s"),
    ("card.mcd", b"x", "extension .mcd"),
    ("shot.png", b"x", "extension .png"),
    ("notes.txt", FAKE_ISO, "ISO9660"),
    ("tool.py", FAKE_ELF, "looks like ELF"),
    ("data.json", FAKE_ZIP, "looks like zip"),
    ("bios/scph.rom", b"abc", "data directory"),
    ("work/dump.txt", b"abc", "data directory"),
    ("blob.dat", b"ab\0cd", "NUL"),
    ("big.txt", b"a" * 1_100_000, "bytes"),
])
def test_forbidden_staged_data_fails(repo, name, data, why):
    repo.write(name, data)
    repo.add(name)
    code, out = staged(repo)
    assert code == 1 and "AUDIT FAILED" in out and why in out and name in out


def test_first_commit_with_forbidden_data_fails_too(repo):
    """No HEAD yet: everything staged is new."""
    repo.write("disc.iso", b"x")
    repo.write("ok.py", "x = 1\n")
    repo.add("disc.iso", "ok.py")
    code, out = staged(repo)
    assert code == 1 and "disc.iso" in out and "ok.py" not in out


# --- TEST-P2-03 / 04: the index decides, not the disk -------------------------------------------------
def test_forbidden_content_stays_flagged_after_the_worktree_is_cleaned(repo):
    repo.write("ok.py", "x = 1\n")
    repo.add("ok.py")
    repo.commit()
    repo.write("tool.py", FAKE_ELF)
    repo.add("tool.py")
    repo.write("tool.py", "print('safe now')\n")             # the disk copy is harmless; the index copy is not
    code, out = staged(repo)
    assert code == 1 and "tool.py: content looks like ELF" in out
    assert repo.audit()[0] == 0, "the working-tree mode should see only the safe file (and prove the difference)"


def test_forbidden_file_deleted_from_disk_after_staging_is_still_flagged(repo):
    repo.write("data.json", FAKE_ZIP)
    repo.add("data.json")
    (repo.path / "data.json").unlink()
    code, out = staged(repo)
    assert code == 1 and "data.json: content looks like zip" in out


def test_safe_index_with_a_dirty_worktree_passes(repo):
    repo.write("a.py", "x = 1\n")
    repo.add("a.py")
    repo.commit()
    repo.write("a.py", "x = 2\n")
    repo.add("a.py")
    repo.write("a.py", FAKE_ELF)                                # unstaged: not part of the commit
    repo.write("new.iso", b"x")                                 # untracked: not part of the commit
    code, out = staged(repo)
    assert code == 0 and "AUDIT PASSED" in out
    code, out = repo.audit()
    assert code == 1 and "a.py: content looks like ELF" in out  # worktree mode does see the disk


def test_partially_staged_file_is_judged_by_its_staged_version(repo):
    repo.write("a.py", "x = 1\n")
    repo.add("a.py")
    repo.write("a.py", f"x = 1\n{CRED_LINE}")                   # credential only on disk
    assert staged(repo)[0] == 0
    repo.add("a.py")
    repo.write("a.py", "x = 1\n")                               # now only in the index
    assert staged(repo)[0] == 1


# --- TEST-P2-05 ---------------------------------------------------------------------------------
def test_credential_text_staged_fails(repo):
    repo.write("config/local.json", '{"%s": "hunter2hunter2"}\n' % CRED_WORD)
    repo.add("config/local.json")
    code, out = staged(repo)
    assert code == 1 and "secr" + "et-like text" in out and "config/local.json" in out


def test_long_token_assignment_fails(repo):
    repo.write("tools/x.py", "tok" + "en = '" + "A" * 24 + "'\n")
    repo.add("tools/x.py")
    assert staged(repo)[0] == 1


# --- TEST-P2-06 ---------------------------------------------------------------------------------
def test_japanese_and_spaces_in_paths(repo):
    repo.write("ドキュメント/設計 メモ.md", "# メモ\n")
    repo.write("ドキュメント/悪い データ.iso", b"x")
    repo.add("ドキュメント/設計 メモ.md", "ドキュメント/悪い データ.iso")
    code, out = staged(repo)
    assert code == 1
    assert "ドキュメント/悪い データ.iso: extension .iso" in out
    assert "設計 メモ.md" not in out.split("PROBLEM")[-1]
    assert out.splitlines()[0].startswith("2 files")


def test_deleting_a_file_is_not_audited_and_cannot_fail(repo):
    repo.write("old.iso", b"x")
    repo.write("ok.py", "x = 1\n")
    repo.git("add", "-f", "--", "old.iso", "ok.py")
    repo.commit()
    repo.git("rm", "-q", "--", "old.iso")
    code, out = staged(repo)
    assert code == 0 and out.startswith("0 files")


def test_rename_is_audited_under_its_new_name_and_content(repo):
    repo.write("docs/plan.md", "# plan\n" * 20)
    repo.write("tools/helper.py", "x = 1\n" * 20)
    repo.add("docs/plan.md", "tools/helper.py")
    repo.commit()
    repo.git("mv", "docs/plan.md", "docs/計画 メモ.md")          # safe rename
    code, out = staged(repo)
    assert code == 0 and out.startswith("1 files")
    repo.git("mv", "tools/helper.py", "tools/helper.iso")      # rename to a forbidden name
    code, out = staged(repo)
    assert code == 1 and "tools/helper.iso: extension .iso" in out


def test_rename_with_changed_content_is_audited_on_the_new_blob(repo):
    repo.write("a.py", "x = 1\n" * 50)
    repo.add("a.py")
    repo.commit()
    repo.git("mv", "a.py", "b.py")
    repo.write("b.py", FAKE_ELF + b"x = 1\n" * 50)
    repo.add("b.py")
    code, out = staged(repo)
    assert code == 1 and "b.py: content looks like ELF" in out


def test_mode_change_only_is_harmless(repo):
    repo.write("run.sh", "#!/bin/sh\n")
    repo.add("run.sh")
    repo.commit()
    repo.git("update-index", "--chmod=+x", "run.sh")
    assert staged(repo)[0] == 0


# --- the other modes -------------------------------------------------------------------------------------
def test_commit_and_history_modes_see_what_was_committed(repo):
    repo.write("ok.py", "x = 1\n")
    repo.add("ok.py")
    repo.commit("one")
    repo.write("dump.p2s", b"x")
    repo.git("add", "-f", "--", "dump.p2s")
    repo.commit("two")
    first = repo.git("rev-parse", "HEAD~1").strip()
    assert repo.audit("--commit", first)[0] == 0
    code, out = repo.audit("--commit", "HEAD")
    assert code == 1 and "dump.p2s" in out and "committed content" in out
    repo.git("rm", "-q", "--", "dump.p2s")
    repo.commit("three")
    assert repo.audit("--commit", "HEAD")[0] == 0               # gone from the tree ...
    code, out = repo.audit("--history")
    assert code == 1 and "dump.p2s" in out                      # ... but not from history


def test_a_large_staged_blob_is_not_read_in_full(repo):
    repo.write("huge.txt", b"a" * 40_000_000)
    repo.add("huge.txt")
    t0 = time.time()
    code, out = staged(repo)
    assert code == 1 and "40000000 bytes" in out and time.time() - t0 < 20
    repo.write("huge2.dat", FAKE_ISO + b"\0" * 20_000_000)      # the ISO marker in a big blob is still found
    repo.add("huge2.dat")
    assert "ISO9660" in staged(repo)[1]


def test_bad_revision_is_an_error_not_a_pass(repo):
    repo.write("a.py", "x = 1\n")
    repo.add("a.py")
    repo.commit()
    code, out = repo.audit("--commit", "no-such-rev")
    assert code == 2 and "AUDIT ERROR" in out


def test_this_repository_passes_its_own_audit():
    root = AUDIT.parents[1]
    proc = subprocess.run([sys.executable, str(AUDIT), "--repo", str(root)], capture_output=True)
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")


# --- the optional pre-commit hook ----------------------------------------------------------------------
def _with_hook(repo):
    shutil.copytree(AUDIT.parent, repo.path / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    repo.git("config", "core.hooksPath", "tools/git-hooks")


def _try_commit(repo):
    return subprocess.run(["git", "commit", "-m", "x"], cwd=repo.path, capture_output=True,
                          env={**os.environ, "PS2CAM_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8"})


def test_hook_blocks_a_bad_commit_and_lets_a_good_one_through(repo):
    repo.write("ok.py", "x = 1\n")
    _with_hook(repo)
    repo.git("add", "-f", "--", "ok.py", "tools/audit_repo.py", "tools/git-hooks/pre-commit")
    assert _try_commit(repo).returncode == 0
    repo.write("disc.iso", b"x")
    repo.git("add", "-f", "--", "disc.iso")
    bad = _try_commit(repo)
    assert bad.returncode != 0 and b"disc.iso" in bad.stderr
    assert repo.git("log", "--oneline").count("\n") == 1          # nothing new was committed


def test_hook_is_inactive_unless_the_user_turns_it_on(repo):
    repo.write("ok.py", "x = 1\n")
    _with_hook(repo)
    repo.git("config", "--unset", "core.hooksPath")
    repo.write("disc.iso", b"x")
    repo.git("add", "-f", "--", "disc.iso")
    assert _try_commit(repo).returncode == 0
