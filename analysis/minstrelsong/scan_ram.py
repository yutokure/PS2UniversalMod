"""Offline float/affine candidate scanner for four extracted PS2 EE RAM images.

No emulator, savestate extraction, game-data copying, or memory writes. The first
pair is reference/wait-only; exact word stability removes observed time noise.
A third state is actor movement; a fourth includes a larger camera movement.
These labels are hints for ranking, not proof that a candidate owns the camera.

Example (from the repository root)::

    python analysis/minstrelsong/scan_ram.py --states-root C:/PS2CameraLab/work/minstrelsong/states
    python analysis/minstrelsong/scan_ram.py --validate-pose 0x417410 0x417460 0x417450 0x3910C0 0x3910B4
    python analysis/minstrelsong/scan_ram.py --self-test

All large numeric reports go outside the repository. numpy is the only dependency.
Exact wait stability removes observed temporal noise only, not all animation noise.
Stale scene matrices and model-bone matrices can rank above the active view; use
look-at cross-checks and the separate live writer investigation before patching.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

NAMES = ("base", "base_only_wait", "base_chara_move", "base_chara_move_and_camera_big_move")
REPO = Path(__file__).resolve().parents[2]
DEFAULT_WORK = REPO.parent / "work" / "minstrelsong"


def plausible(a: np.ndarray, limit: float = 1e6) -> np.ndarray:
    """Reject NaN, infinities, subnormal/integer-as-float garbage and huge values."""
    return np.isfinite(a) & (np.abs(a) < limit) & ((a == 0) | (np.abs(a) > 1e-7))


def rotation_error(r: np.ndarray) -> np.ndarray:
    identity = np.eye(3)
    return np.max(np.abs(r @ r.swapaxes(-1, -2) - identity), axis=(-2, -1))


def rotation_angle(a: np.ndarray, b: np.ndarray) -> float:
    # PS2 approximate normalization leaves trace(R R.T) just below 3 even for
    # identical matrices. Project onto SO(3) before computing the angle.
    ua, _, va = np.linalg.svd(a)
    ub, _, vb = np.linalg.svd(b)
    x = (np.trace((ua @ va) @ (ub @ vb).T) - 1) / 2
    return math.degrees(math.acos(float(np.clip(x, -1, 1))))


def as_numbers(a: np.ndarray) -> list:
    rounded = np.round(a.astype(np.float64), 7)
    # Adjacent untyped words (for example W after a vec3) may be non-finite.
    return np.where(np.isfinite(rounded), rounded.astype(object), None).tolist()


def scan_matrices(words: list[np.ndarray], tolerance: float) -> list[dict]:
    """Find affine 4x4 matrices at every 4-byte alignment, both transpositions."""
    floats = [w.view("<f4") for w in words]
    base, wait, move, big = words
    results = []
    for start in range(0x100000 // 4, len(base) - 15, 262144):
        stop = min(start + 262144, len(base) - 15)
        indices = np.arange(start, stop)
        for convention, homogeneous in (("row-vector", (3, 7, 11)), ("column-vector", (12, 13, 14))):
            with np.errstate(invalid="ignore"):
                ok = np.abs(floats[0][indices + 15] - 1) < tolerance
            for offset in homogeneous:
                ok &= floats[0][indices + offset] == 0
            ix = indices[ok]
            if not len(ix):
                continue
            offsets = np.arange(16)
            raw = [w[ix[:, None] + offsets] for w in words]
            stable = np.all(raw[0] == raw[1], axis=1)
            changed = np.any(raw[0] != raw[3], axis=1)
            ix = ix[stable & changed]
            if not len(ix):
                continue
            mats = np.stack([f[ix[:, None] + offsets].reshape(-1, 4, 4) for f in floats])
            finite = np.all(np.isfinite(mats) & (np.abs(mats) < 1e7), axis=(0, 2, 3))
            errors = rotation_error(mats[:, :, :3, :3].astype(np.float64))
            valid = finite & np.all(errors < tolerance, axis=0)
            # Homogeneous layout must hold in ALL four states, not just the base.
            for offset in homogeneous:
                valid &= np.all(mats.reshape(4, -1, 16)[:, :, offset] == 0, axis=0)
            valid &= np.all(np.abs(mats[:, :, 3, 3] - 1) < tolerance, axis=0)
            for j in np.flatnonzero(valid):
                m = mats[:, j].astype(np.float64)
                # Normalize to row-vector layout: rows = right/up/forward, row 3 = translation.
                if convention == "column-vector":
                    m = m.swapaxes(-1, -2)
                r = m[:, :3, :3]
                t = m[:, 3, :3]
                small = rotation_angle(r[0], r[2])
                large = rotation_angle(r[0], r[3])
                if max(np.max(np.abs(t)), small, large) < 1e-6:
                    continue
                results.append({
                    "address": f"0x{int(ix[j]) * 4:08X}", "layout": convention,
                    "max_orthogonal_error": float(np.max(errors[:, j])),
                    "determinants": as_numbers(np.linalg.det(r)),
                    "move_angle_deg": round(small, 5), "big_angle_deg": round(large, 5),
                    "rotation_ratio": round(large / max(small, 0.1), 4),
                    "translation": as_numbers(t),
                    "translation_move_distance": float(np.linalg.norm(t[2] - t[0])),
                    "translation_big_distance": float(np.linalg.norm(t[3] - t[0])),
                    "inverse_translation": as_numbers(-np.einsum("si,sji->sj", t, r)),
                    "row_normalized_matrices": as_numbers(m),
                })
    results.sort(key=lambda x: (-x["rotation_ratio"], -x["big_angle_deg"], x["address"]))
    return results


def scan_scalars(words: list[np.ndarray], top: int) -> tuple[list[dict], list[dict], dict]:
    floats = [w.view("<f4") for w in words]
    stable = words[0] == words[1]
    changed_move = words[0] != words[2]
    changed_big = words[0] != words[3]
    valid = stable & (changed_move | changed_big)
    for f in floats:
        valid &= plausible(f)
    valid[:0x100000 // 4] = False
    ix = np.flatnonzero(valid)
    a = np.stack([f[ix] for f in floats]).astype(np.float64)
    angles = []
    angle_ix = np.flatnonzero(np.all(np.abs(a) <= 2 * math.pi + 0.1, axis=0) & (np.abs(a[3] - a[0]) > 0.05))
    for j in angle_ix:
        small, big = abs(a[2, j] - a[0, j]), abs(a[3, j] - a[0, j])
        angles.append({"address": f"0x{int(ix[j]) * 4:08X}", "values": as_numbers(a[:, j]),
                       "move_delta": float(small), "big_delta": float(big),
                       "ratio": float(big / max(small, 0.005))})
    angles.sort(key=lambda x: (-x["ratio"], -x["big_delta"], x["address"]))
    # Triples must be bit-stable during wait in all three components. Avoid
    # float reinterpretations of pointers/integers by testing plausible numbers.
    starts = np.flatnonzero(valid[:-2] | valid[1:-1] | valid[2:])
    starts = starts[starts >= 0x100000 // 4]
    offsets = np.arange(3)
    triples = np.stack([f[starts[:, None] + offsets] for f in floats]).astype(np.float64)
    keep = np.all(stable[starts[:, None] + offsets], axis=1)
    keep &= np.all(plausible(triples, 1e5), axis=(0, 2))
    keep &= np.all(np.count_nonzero(np.abs(triples) > 0.01, axis=2) >= 2, axis=0)
    delta_move = np.linalg.norm(triples[2] - triples[0], axis=1)
    delta_big = np.linalg.norm(triples[3] - triples[0], axis=1)
    keep &= (delta_big > 0.1) & (delta_move > 0.01)
    candidates = []
    for j in np.flatnonzero(keep):
        v = triples[:, j]
        candidates.append({"address": f"0x{int(starts[j]) * 4:08X}", "values": as_numbers(v),
                           "norms": as_numbers(np.linalg.norm(v, axis=1)),
                           "move_distance": float(delta_move[j]), "big_distance": float(delta_big[j]),
                           "ratio": float(delta_big[j] / max(delta_move[j], 0.01)),
                           "w_values": as_numbers(np.array([f[starts[j] + 3] for f in floats])) if starts[j] + 3 < len(words[0]) else []})
    candidates.sort(key=lambda x: (-x["ratio"], x["address"]))
    counts = {"wait_changed_words": int(np.count_nonzero(~stable)),
              "move_changed_words": int(np.count_nonzero(changed_move)),
              "big_changed_words": int(np.count_nonzero(changed_big)),
              "wait_stable_changed_plausible_floats": len(ix),
              "angle_candidates": len(angles), "triple_candidates": len(candidates)}
    return angles[:top], candidates[:top], counts


def validate_pose(words: list[np.ndarray], addresses: list[int]) -> dict:
    """Cross-check an externally chosen view/eye/target/actor/heading tuple."""
    view_addr, eye_addr, target_addr, actor_addr, heading_addr = addresses
    floats = [w.view("<f4") for w in words]
    poses = []
    for f in floats:
        view = f[view_addr // 4:view_addr // 4 + 16].astype(np.float64).reshape(4, 4)
        eye = f[eye_addr // 4:eye_addr // 4 + 3].astype(np.float64)
        target = f[target_addr // 4:target_addr // 4 + 3].astype(np.float64)
        actor = f[actor_addr // 4:actor_addr // 4 + 3].astype(np.float64)
        heading = float(f[heading_addr // 4])
        direction = target - eye
        distance = float(np.linalg.norm(direction))
        forward = direction / distance
        right = np.cross((0, 1, 0), forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        reconstructed = np.eye(4)
        reconstructed[:3, :3] = np.stack((right, up, forward), axis=1)
        reconstructed[3, :3] = -eye @ reconstructed[:3, :3]
        inverse = np.linalg.inv(view)
        poses.append({
            "eye": as_numbers(eye), "target": as_numbers(target), "actor": as_numbers(actor),
            "actor_heading_radians": float(heading), "actor_heading_degrees": math.degrees(heading),
            "target_minus_actor": as_numbers(target - actor),
            "forward_yaw_degrees": math.degrees(math.atan2(forward[0], forward[2])),
            "forward_pitch_degrees": math.degrees(math.atan2(forward[1], math.hypot(forward[0], forward[2]))),
            "orbit_yaw_radians": math.atan2(-direction[0], -direction[2]),
            "distance": distance, "view_rotation": as_numbers(view[:3, :3]),
            "view_translation": as_numbers(view[3, :3]),
            "inverse_world_matrix": as_numbers(inverse),
            "lookat_max_rotation_error": float(np.max(np.abs(view[:3, :3] - reconstructed[:3, :3]))),
            "lookat_max_translation_error": float(np.max(np.abs(view[3, :3] - reconstructed[3, :3]))),
            "inverse_eye_max_error": float(np.max(np.abs(inverse[3, :3] - eye))),
            "orthogonal_max_error": float(rotation_error(view[:3, :3])),
        })
    return {"addresses": dict(zip(("view", "eye", "target", "actor", "heading"),
                                  (f"0x{x:08X}" for x in addresses))), "poses": poses}


def self_test() -> None:
    r = np.eye(4, dtype="<f4")
    a = math.pi / 3
    b = np.array([[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0],
                  [-math.sin(a), 0, math.cos(a), 0], [12, 34, 56, 1]], dtype="<f4")
    arrays = [np.zeros(0x100100 // 4, dtype="<u4") for _ in range(4)]
    for arr, mat in zip(arrays, (r, r, r, b)):
        arr[0x100000 // 4:0x100000 // 4 + 16] = mat.reshape(-1).view("<u4")
    found = scan_matrices(arrays, 0.002)
    assert any(x["address"] == "0x00100000" and abs(x["big_angle_deg"] - 60) < 0.01 for x in found)
    arrays[1][0x100000 // 4] ^= 1
    assert not any(x["address"] == "0x00100000" for x in scan_matrices(arrays, 0.002))
    pose = np.zeros(32, dtype="<f4")
    pose[:16] = np.eye(4).reshape(-1)
    pose[0x50 // 4 + 2] = 2
    tested = validate_pose([pose.view("<u4")] * 4, [0, 0x40, 0x50, 0x60, 0x70])
    assert all(p["lookat_max_rotation_error"] == 0 and p["inverse_eye_max_error"] == 0
               and p["distance"] == 2 for p in tested["poses"])
    print("self-test: affine detection, 60-degree angle, wait-noise rejection, look-at validation PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states-root", type=Path, default=DEFAULT_WORK / "states")
    parser.add_argument("--names", nargs=4, default=NAMES, metavar=("BASE", "WAIT", "MOVE", "BIG"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_WORK / "offline_scan")
    parser.add_argument("--top", type=int, default=5000, help="maximum scalar/triple rows in the JSON")
    parser.add_argument("--tolerance", type=float, default=0.002)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-pose", nargs=5, type=lambda value: int(value, 0),
                        metavar=("VIEW", "EYE", "TARGET", "ACTOR", "HEADING"),
                        help="also validate a chosen row-vector look-at/actor tuple")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    out = args.output_root.resolve()
    if out.is_relative_to(REPO):
        parser.error("numeric scan reports must be outside the source repository")
    paths = [args.states_root / n / "eeMemory.bin" for n in args.names]
    words = [np.fromfile(p, dtype="<u4") for p in paths]
    if len({len(w) for w in words}) != 1 or len(words[0]) < 0x100000 // 4 + 16:
        parser.error("RAM images must have the same size, and exceed 1 MiB")
    matrices = scan_matrices(words, args.tolerance)
    angles, triples, counts = scan_scalars(words, args.top)
    result = {"states": list(args.names), "input_files": [str(p.resolve()) for p in paths],
              "sha256": [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths],
              "counts": counts, "affine_matrix_count": len(matrices),
              "affine_matrices": matrices, "angles": angles, "triples": triples,
              "warning": "Offline mathematical/differential candidates, not live ownership/write-safety proof."}
    if args.validate_pose:
        if any(a < 0 or a % 4 or a + 64 > words[0].nbytes for a in args.validate_pose):
            parser.error("pose addresses must be in-image, 4-byte-aligned physical addresses")
        result["pose_validation"] = validate_pose(words, args.validate_pose)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "candidates.json"
    target.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(counts, indent=2))
    print(f"affine candidates: {len(matrices)}; report: {target}")
    for m in matrices[:35]:
        print(m["address"], m["layout"], "move/big deg", m["move_angle_deg"], m["big_angle_deg"],
              "ratio", m["rotation_ratio"], "t(base/big)", m["translation"][0], m["translation"][3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
