"""Where the local, never-committed data lives (games, BIOS, savestates, dumps, tools).

Nothing here is a game file; the module only says where to look.  Each directory comes from, in
order:

1. an environment variable (``PS2_LAB_DIR``, ``PS2_GAME_DIR``, ``PS2_BIOS_DIR``,
   ``PS2_SAVESTATE_DIR``, ``PS2_DUMP_DIR``, ``PS2_PCSX2_DIR``);
2. ``config/local_config.json`` next to the repository (git-ignored; copy
   ``config/local_config.example.json`` and edit it);
3. the layout of the original lab: the repository sits inside ``<lab>/``, with the emulator in
   ``<lab>/pcsx2``, savestates in ``<lab>/sstates``, dumps in ``<lab>/work``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_LOCAL = REPO / "config" / "local_config.json"


def _local() -> dict:
    try:
        return json.loads(_LOCAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _pick(env: str, key: str, default: Path) -> Path:
    value = os.environ.get(env) or _local().get(key)
    return Path(value) if value else default


def lab_dir() -> Path:
    return _pick("PS2_LAB_DIR", "lab_dir", REPO.parent)


def pcsx2_dir() -> Path:
    """The PCSX2 build the lab drives (portable folder with the inis and cheats)."""
    return _pick("PS2_PCSX2_DIR", "pcsx2_dir", lab_dir() / "pcsx2" / "fork-B056de99")


def game_dir() -> Path:
    return _pick("PS2_GAME_DIR", "game_dir", lab_dir() / "pcsx2" / "iso")


def bios_dir() -> Path:
    return _pick("PS2_BIOS_DIR", "bios_dir", lab_dir() / "pcsx2" / "bios")


def savestate_dir() -> Path:
    return _pick("PS2_SAVESTATE_DIR", "savestate_dir", lab_dir() / "sstates")


def dump_dir() -> Path:
    """Scratch space for extracted savestates, RAM dumps and Ghidra projects."""
    return _pick("PS2_DUMP_DIR", "dump_dir", lab_dir() / "work")


def evidence_dir() -> Path:
    return _pick("PS2_EVIDENCE_DIR", "evidence_dir", lab_dir() / "test_evidence")


def lab_scripts_dir() -> Path:
    return lab_dir() / "scripts"


def mcp_src_dir() -> Path:
    return lab_dir() / "vendor" / "PCSX2_MCP" / "src"
