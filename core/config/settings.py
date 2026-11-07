"""Settings, presets and per-game configuration for the camera controller."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "PS2 Universal Camera Controller"
APP_VERSION = "2.0.0"

#: Explicit session opt-ins: never inherit adapter defaults, saved settings or presets.
SESSION_ONLY_SETTINGS = frozenset({"pause_game_time", "wide_view_running", "no_encounters"})

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PRESET_DIR = ROOT / "presets"


def _config_home() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "PS2UniversalCamera"


def config_path() -> Path:
    return _config_home() / "settings.json"


def presets_dir() -> Path:
    path = _config_home() / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    """Everything the GUI persists (per game id)."""
    version: str = APP_VERSION
    game_id: str = "SLPS-25250"
    mode: str = "original"
    yaw_deg: float = 0.0
    pitch_deg: float = 40.9
    distance: float = 28.7
    pos_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    target_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    free_eye: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    free_target: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov_deg: float = 54.68
    use_fov: bool = False
    #: how far above the party anchor (towards -Y) the camera aims.  This is what
    #: keeps Yuna framed while orbiting, so it is persisted with the preset.
    look_height: float = -6.0
    sensitivity: float = 1.0
    rotate_speed_deg: float = 150.0
    deadzone: float = 0.12
    invert_x: bool = False
    invert_y: bool = False
    smoothing: float = 0.35
    pitch_min_deg: float = -25.0
    pitch_max_deg: float = 85.0
    input_source: str = "auto"
    #: games with a built-in zoom: a zoom step of the game also steps the orbit distance
    zoom_follow: bool = True
    #: UI language for the controller window ("ja" or "en")
    language: str = "ja"

    def to_dict(self) -> dict:
        return asdict(self)


class SettingsStore:
    """JSON store keyed by game id so several titles can coexist."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = payload.get("games", payload if isinstance(payload, dict) else {})
            except (OSError, json.JSONDecodeError):
                self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"app": APP_NAME, "version": APP_VERSION, "games": self.data}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, game_id: str) -> AppSettings:
        raw = self.data.get(game_id) or {}
        known = {f for f in AppSettings().__dict__}
        clean = {k: v for k, v in raw.items() if k in known}
        st = AppSettings(**clean)
        st.game_id = game_id
        return st

    def put(self, settings: AppSettings) -> None:
        self.data[settings.game_id] = settings.to_dict()
        self.save()


class PresetStore:
    """Named presets stored as individual JSON files."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or presets_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        #: presets shipped with the repo.  They are read-only and appear in the
        #: GUI list next to the user's own, so a fresh install already has a
        #: working "orbit default" to load.
        self.bundled = PRESET_DIR

    def _files(self) -> list[Path]:
        seen: dict[str, Path] = {}
        for d in (self.bundled, self.dir):
            try:
                for p in sorted(d.glob("*.json")):
                    seen.setdefault(p.stem, p)   # user dir wins over bundled
            except OSError:
                continue
        return [seen[k] for k in sorted(seen)]

    def list(self, game_id: str | None = None) -> list[str]:
        names = []
        for p in self._files():
            if game_id is None:
                names.append(p.stem)
            else:
                try:
                    payload = json.loads(p.read_text(encoding="utf-8"))
                    if payload.get("game_id") == game_id:
                        names.append(p.stem)
                except (OSError, json.JSONDecodeError):
                    continue
        return names

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "preset"

    def exists(self, name: str) -> bool:
        """True when saving under ``name`` would overwrite the user's own preset."""
        return (self.dir / f"{self._safe_name(name)}.json").exists()

    def save(self, name: str, settings: AppSettings) -> Path:
        safe = self._safe_name(name)
        path = self.dir / f"{safe}.json"
        payload = {"name": safe, "game_id": settings.game_id, "settings": settings.to_dict()}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load(self, name: str, game_id: str) -> AppSettings | None:
        path = self.dir / f"{name}.json"
        if not path.exists():
            path = self.bundled / f"{name}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        raw = payload.get("settings", {})
        known = {f for f in AppSettings().__dict__}
        st = AppSettings(**{k: v for k, v in raw.items() if k in known})
        st.game_id = game_id
        return st
