"""E2E evidence harness for PS2-CAM-01 / FFX-2.

Every scenario drives the *real* runtime against the *real* emulator, captures
the PCSX2 render window before and after, measures the pixel delta and stores
both the images and a machine-readable verdict.

    python tools/e2e.py                 # full suite
    python tools/e2e.py --only E2E-03   # one scenario
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_FREE, MODE_ORBIT, MODE_ORIGINAL, CameraRuntime, CameraSettings  # noqa: E402
from core.controller.sources import ScriptedSource  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "e2e"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)


class Ctx:
    def __init__(self) -> None:
        self.backend = PineBackend()
        self.backend.connect()
        self.adapter = FFX2Adapter(self.backend)
        self.info = self.adapter.identify()
        self.settings = CameraSettings()
        self.rt = CameraRuntime(self.adapter, self.settings, strategy="continuous")
        self.stick = ScriptedSource()
        self.window = Window()
        self.results: list[dict] = []
        self.pump = None

    def start(self) -> None:
        from core.controller.sources import InputPump
        self.rt.capture_original_fov()
        self.rt.start()
        self.pump = InputPump(self.rt, self.stick, hz=120)
        self.pump.start()

    def shot(self, name: str) -> np.ndarray:
        """Capture the render window.

        PrintWindow was validated as a stable evidence source (static-scene
        frame-to-frame noise stays below 1.5 % of pixels, see
        tools/capture_stability.py).  It also avoids opening a second GDB
        session, which would fight this harness for the emulator.
        """
        self.window.grab()                    # discard a possibly stale paint
        time.sleep(0.06)
        arr = self.window.grab()
        Image.fromarray(arr.astype(np.uint8)).save(SHOTS / f"{name}.png")
        return arr

    def close(self) -> None:
        try:
            if self.pump:
                self.pump.stop()
            self.rt.restore()
            time.sleep(0.3)
        finally:
            self.rt.stop()
            self.backend.close()

    def record(self, ident: str, name: str, ok: bool, detail: dict) -> None:
        self.results.append({"id": ident, "name": name, "pass": bool(ok), **detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {ident} {name}: {detail}")


def settle(seconds: float = 0.45) -> None:
    time.sleep(seconds)


def capture_diff(ctx: Ctx, ident: str, before: np.ndarray, name: str,
                 threshold: float = 0.15) -> dict:
    after = ctx.shot(f"{ident}_{name}_after")
    score = diffscore(before, after)
    ok = score["frac_gt16"] >= threshold
    return {"ok": ok, "score": score, "after": after}


# ------------------------------------------------------------------ scenarios
def e2e_01(ctx: Ctx) -> None:
    ok = ctx.info.matched
    ctx.record("E2E-01", "startup & connection", ok,
               {"game_id": ctx.info.game_id, "crc": ctx.info.crc, "matched": ok})


def e2e_03(ctx: Ctx) -> None:
    """Right stick yaw: orbit around Yuna horizontally."""
    before = ctx.shot("E2E-03_before")
    base_yaw, base_pitch = ctx.adapter.read_game_pose().yaw_pitch()
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.yaw_deg = math.degrees(base_yaw)
    st.pitch_deg = math.degrees(base_pitch)
    st.distance = ctx.adapter.read_game_pose().distance()
    st.target_offset = [0.0, 0.0, 0.0]
    settle()
    frames = []
    for step in (1, 2, 3):
        ctx.stick.set(1.0, 0.0)          # full right stick to the right
        time.sleep(0.35)
        frames.append(ctx.shot(f"E2E-03_yawstep{step}"))
    ctx.stick.set(0.0, 0.0)
    time.sleep(0.25)
    held = ctx.shot("E2E-03_yaw_held")
    time.sleep(0.5)
    held2 = ctx.shot("E2E-03_yaw_held2")
    yaw_after = ctx.rt.settings.yaw_deg
    moved = diffscore(before, frames[-1])
    still = diffscore(held, held2)
    ok = moved["frac_gt16"] > 0.15 and abs(yaw_after - math.degrees(base_yaw)) > 30.0
    ctx.record("E2E-03", "right stick horizontal orbit", ok,
               {"yaw_before": round(math.degrees(base_yaw), 2), "yaw_after": round(yaw_after, 2),
                "visual_delta": moved, "hold_delta": still,
                "writes_per_sec": ctx.rt.stats.writes_per_sec,
                "mode": ctx.rt.settings.mode, "last_error": ctx.rt.stats.last_error})


def e2e_04(ctx: Ctx) -> None:
    """Right stick pitch: raise/lower the camera."""
    before = ctx.shot("E2E-04_before")
    p0 = ctx.rt.settings.pitch_deg
    ctx.stick.set(0.0, 1.0)
    time.sleep(0.6)
    ctx.stick.set(0.0, 0.0)
    time.sleep(0.2)
    after = ctx.shot("E2E-04_after")
    p1 = ctx.rt.settings.pitch_deg
    score = diffscore(before, after)
    ok = score["frac_gt16"] > 0.12 and abs(p1 - p0) > 8.0
    ctx.record("E2E-04", "right stick vertical orbit", ok,
               {"pitch_before": round(p0, 2), "pitch_after": round(p1, 2), "visual_delta": score})


def e2e_05(ctx: Ctx) -> None:
    """Follow the player: orbit must track the anchor as it moves."""
    p0 = ctx.adapter.read_player()
    ctx.stick.set(0.0, 0.0)
    settle()
    # walk forward with a short key hold (long walks cross a map boundary and
    # invalidate every later scenario, so this stays deliberately small)
    walk(steps=2, pause=0.15)
    time.sleep(0.4)
    p1 = ctx.adapter.read_player()
    tgt = ctx.rt.stats.applied_pose[1] if ctx.rt.stats.applied_pose else None
    dist = None
    if tgt:
        dist = math.dist(tgt, p1.as_tuple())
    ok = math.dist(p0.as_tuple(), p1.as_tuple()) > 0.5 and (dist is None or dist < 20.0)
    ctx.record("E2E-05", "camera follows moving player", ok,
               {"player_before": p0.as_tuple(), "player_after": p1.as_tuple(),
                "target_minus_player": dist})


_BRIDGE = None


def walk(steps: int = 3, y: float = -1.0, pause: float = 0.22) -> None:
    """Walk the character with a direct PostMessageW key hold.

    Uses PCSX2's own keyboard binding for the left stick (LUp = Keyboard/W),
    which the lab configured additively next to the physical controller
    bindings.  No MCP/GDB session is involved, so the VM stays running.
    """
    try:
        from pcsx2_input import walk as _walk
        _walk(steps=steps, ms=int(pause * 1000))
    except Exception as exc:  # noqa: BLE001
        print("   (walk unavailable:", exc, ")")


def import_mcp_walk(ctx: Ctx) -> None:
    walk(steps=2, pause=0.15)


def e2e_06(ctx: Ctx) -> None:
    """GUI yaw/pitch changes are reflected on screen."""
    before = ctx.shot("E2E-06_before")
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.yaw_deg += 40.0
    st.pitch_deg = max(-20.0, st.pitch_deg - 15.0)
    settle(0.6)
    res = capture_diff(ctx, "E2E-06", before, "gui_rotation")
    ctx.record("E2E-06", "GUI yaw/pitch changes the view", res["ok"],
               {"visual_delta": res["score"], "yaw": st.yaw_deg, "pitch": st.pitch_deg})


def e2e_07(ctx: Ctx) -> None:
    """GUI FOV changes the projection."""
    st = ctx.rt.settings
    st.use_fov = False
    ctx.adapter.restore_fov()
    settle(0.3)
    before = ctx.shot("E2E-07_before")
    st.use_fov = True
    st.fov_deg = 80.0
    settle(0.7)
    res = capture_diff(ctx, "E2E-07", before, "fov80")
    scale = ctx.backend.read_floats(0x340B00, 1)[0]
    st.fov_deg = 40.0
    settle(0.7)
    res2 = capture_diff(ctx, "E2E-07", before, "fov40")
    st.use_fov = False
    ctx.adapter.restore_fov()
    settle(0.3)
    restored = ctx.shot("E2E-07_restored")
    back = diffscore(before, restored)
    ok = res["ok"] and res2["ok"] and back["frac_gt16"] < 0.10
    ctx.record("E2E-07", "GUI FOV changes the view and restores", ok,
               {"fov80_delta": res["score"], "fov40_delta": res2["score"],
                "restore_delta": back, "scale_seen": scale})


def e2e_08(ctx: Ctx) -> None:
    """GUI distance changes the orbit radius."""
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.distance = 28.0
    settle(0.5)
    before = ctx.shot("E2E-08_before")
    st.distance = 12.0
    settle(0.6)
    res = capture_diff(ctx, "E2E-08", before, "near")
    eye = ctx.rt.stats.applied_pose[0] if ctx.rt.stats.applied_pose else None
    d = None
    if eye and ctx.rt.stats.applied_pose:
        d = math.dist(eye, ctx.rt.stats.applied_pose[1])
    st.distance = 28.0
    settle(0.5)
    ok = res["ok"] and d is not None and abs(d - 12.0) < 1.0
    ctx.record("E2E-08", "GUI distance changes radius", ok,
               {"visual_delta": res["score"], "measured_distance": d})


def e2e_09(ctx: Ctx) -> None:
    """GUI XYZ offsets move the camera and the look-at point."""
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.pos_offset = [0.0, 0.0, 0.0]
    st.target_offset = [0.0, 0.0, 0.0]
    settle(0.5)
    before = ctx.shot("E2E-09_before")
    st.pos_offset = [8.0, 0.0, 0.0]
    settle(0.6)
    res_x = capture_diff(ctx, "E2E-09", before, "posX")
    st.pos_offset = [0.0, 8.0, 0.0]
    settle(0.6)
    res_y = capture_diff(ctx, "E2E-09", before, "posY")
    st.pos_offset = [0.0, 0.0, 8.0]
    settle(0.6)
    res_z = capture_diff(ctx, "E2E-09", before, "posZ")
    st.pos_offset = [0.0, 0.0, 0.0]
    st.target_offset = [20.0, 0.0, 0.0]
    settle(0.6)
    res_t = capture_diff(ctx, "E2E-09", before, "targetX")
    st.target_offset = [0.0, 20.0, 0.0]
    settle(0.6)
    res_ty = capture_diff(ctx, "E2E-09", before, "targetY")
    st.target_offset = [0.0, 0.0, 0.0]
    settle(0.5)
    back = diffscore(before, ctx.shot("E2E-09_restored"))
    ok = all(r["ok"] for r in (res_x, res_y, res_z, res_t, res_ty)) and back["frac_gt16"] < 0.12
    ctx.record("E2E-09", "GUI XYZ / target offsets", ok,
               {"posX": res_x["score"], "posY": res_y["score"], "posZ": res_z["score"],
                "targetX": res_t["score"], "targetY": res_ty["score"], "restore": back})


def e2e_10(ctx: Ctx) -> None:
    """Left stick movement and right stick rotation at the same time."""
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    before = ctx.shot("E2E-10_before")
    y0 = st.yaw_deg
    ctx.stick.set(1.0, 0.0)
    for _ in range(2):
        walk(steps=1, pause=0.16)
        time.sleep(0.2)
    ctx.stick.set(0.0, 0.0)
    time.sleep(0.3)
    after = ctx.shot("E2E-10_after")
    score = diffscore(before, after)
    y1 = ctx.rt.settings.yaw_deg
    ok = abs(y1 - y0) > 10.0 and ctx.rt.stats.writes_per_sec > 100
    ctx.record("E2E-10", "simultaneous move + rotate", ok,
               {"yaw_delta": round(y1 - y0, 2), "visual_delta": score,
                "writes_per_sec": ctx.rt.stats.writes_per_sec,
                "last_error": ctx.rt.stats.last_error})


def e2e_11(ctx: Ctx) -> None:
    """Disabling the mod returns the game camera."""
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.yaw_deg += 50
    settle(0.6)
    modded = ctx.shot("E2E-11_modded")
    ctx.rt.restore()
    settle(0.6)
    original = ctx.shot("E2E-11_original")
    # the game camera must differ from our override and be stable
    d = diffscore(modded, original)
    time.sleep(0.4)
    original2 = ctx.shot("E2E-11_original2")
    stable = diffscore(original, original2)
    ok = d["frac_gt16"] > 0.10 and stable["frac_gt16"] < 0.10
    ctx.record("E2E-11", "restore original camera", ok,
               {"modded_vs_original": d, "original_stability": stable})


def e2e_free(ctx: Ctx) -> None:
    """Bonus: detached free camera."""
    st = ctx.rt.settings
    before = ctx.shot("FREE_before")
    sc = ctx.adapter.read_scene()
    eye = sc.game_pose.eye
    tgt = sc.game_pose.target
    st.free_eye = [eye.x, eye.y - 8.0, eye.z + 14.0]
    st.free_target = [tgt.x, tgt.y, tgt.z]
    st.mode = MODE_FREE
    settle(0.7)
    res = capture_diff(ctx, "FREE", before, "detached")
    ctx.record("E2E-FREE", "free camera detached viewpoint", res["ok"],
               {"visual_delta": res["score"]})
    st.mode = MODE_ORBIT


SCENARIOS = {
    "E2E-01": e2e_01,
    "E2E-03": e2e_03,
    "E2E-04": e2e_04,
    "E2E-05": e2e_05,
    "E2E-06": e2e_06,
    "E2E-07": e2e_07,
    "E2E-08": e2e_08,
    "E2E-09": e2e_09,
    "E2E-10": e2e_10,
    "E2E-11": e2e_11,
    "E2E-FREE": e2e_free,
}


def normalise(ctx: Ctx) -> None:
    """Put the runtime back into a neutral orbit before each scenario."""
    st = ctx.rt.settings
    st.mode = MODE_ORBIT
    st.pos_offset = [0.0, 0.0, 0.0]
    st.target_offset = [0.0, 0.0, 0.0]
    st.use_fov = False
    ctx.adapter.restore_fov()
    ctx.stick.set(0.0, 0.0)
    ctx.rt.sync_to_game()
    time.sleep(0.45)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--out", default=str(OUT / "e2e_results.json"))
    args = ap.parse_args()
    names = args.only or list(SCENARIOS)
    ctx = Ctx()
    if not ctx.info.matched:
        print("ABORT: adapter does not match the running game:", ctx.info)
        return 2
    ctx.start()
    t0 = time.time()
    try:
        for name in names:
            fn = SCENARIOS.get(name)
            if fn is None:
                continue
            print(f"--- {name} ---")
            try:
                if name != "E2E-01":
                    normalise(ctx)
                fn(ctx)
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                ctx.record(name, "exception", False, {"error": f"{type(exc).__name__}: {exc}"})
            time.sleep(0.3)
    finally:
        ctx.close()
    payload = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.time() - t0, 1),
        "game": {"id": ctx.info.game_id, "crc": ctx.info.crc, "title": ctx.info.title},
        "pass": sum(1 for r in ctx.results if r["pass"]),
        "fail": sum(1 for r in ctx.results if not r["pass"]),
        "results": ctx.results,
    }
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{payload['pass']} passed / {payload['fail']} failed -> {args.out}")
    return 0 if payload["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
