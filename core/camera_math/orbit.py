"""Orbit camera mathematics, engine independent.

FFX-2 world convention (determined empirically, see docs/games/ffx2/CAMERA_MEMORY_MAP.md):

    +X  right,  +Y  DOWN,  +Z  forward (away from the default camera)

The default field camera sits behind and above the player looking slightly
down, i.e. eye = target + (sin(yaw)cos(pitch), -sin(pitch), cos(yaw)cos(pitch)) * d
with a positive pitch meaning "camera above the target".

All functions here are pure so the GUI and the runtime share exactly one
implementation of the camera model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


@dataclass
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scaled(self, k: float) -> "Vec3":
        return Vec3(self.x * k, self.y * k, self.z * k)

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class CameraPose:
    eye: Vec3
    target: Vec3

    def distance(self) -> float:
        return (self.eye - self.target).length()

    def yaw_pitch(self) -> tuple[float, float]:
        off = self.eye - self.target
        horizontal = math.hypot(off.x, off.z)
        yaw = math.atan2(off.x, off.z)
        pitch = math.atan2(-off.y, horizontal)
        return yaw, pitch


def orbit_pose(target: Vec3, yaw: float, pitch: float, distance: float) -> CameraPose:
    """Position the camera on a sphere around ``target``.

    yaw     radians, 0 keeps the default over-the-shoulder direction
    pitch   radians, positive raises the camera above the target
    """
    cp = math.cos(pitch)
    eye = Vec3(
        target.x + math.sin(yaw) * cp * distance,
        target.y - math.sin(pitch) * distance,
        target.z + math.cos(yaw) * cp * distance,
    )
    return CameraPose(eye=eye, target=target)


def free_pose(eye: Vec3, target: Vec3) -> CameraPose:
    return CameraPose(eye=eye, target=target)


# --- FOV --------------------------------------------------------------
# FFX-2 stores a single master projection scale.  The game's own projection
# block derives  Sx = 0.800 * V  and  Sy = 0.9333 * V, and the renderer maps
# 512 px to 640 virtual pixels, so the horizontal half-angle satisfies
#     tan(fov_h / 2) = 320 / V
# The default field value V0 = 619 therefore reproduces the stock field of
# view (~54.7 deg horizontal).  See docs/games/ffx2/FOV_ANALYSIS.md for the derivation.
FOV_SCALE_REF = 619.0
FOV_HALF_WIDTH_PX = 320.0
FOV_MIN_DEG = 20.0
FOV_MAX_DEG = 110.0


def fov_deg_to_scale(fov_deg: float) -> float:
    fov_deg = clamp(fov_deg, FOV_MIN_DEG, FOV_MAX_DEG)
    return FOV_HALF_WIDTH_PX / math.tan(math.radians(fov_deg) / 2.0)


def scale_to_fov_deg(scale: float) -> float:
    if scale <= 0:
        return 0.0
    return 2.0 * math.degrees(math.atan(FOV_HALF_WIDTH_PX / scale))


def default_fov_deg() -> float:
    return scale_to_fov_deg(FOV_SCALE_REF)


def walk_target(centre: Vec3, base: Vec3, eye: Vec3) -> Vec3:
    """Look-at target that makes the stock walk head away from ``eye``.

    The stock walk heads along ``target - base``, where ``base`` is the game's own
    eye.  Choosing ``target = centre + (base - eye)`` makes that difference equal
    ``centre - eye`` whatever the base is, so the walk follows the rendered camera
    even in areas where the game keeps its own eye (it does not run the field eye
    routine there, so the base stays put).
    """
    return Vec3(centre.x + base.x - eye.x,
                centre.y + base.y - eye.y,
                centre.z + base.z - eye.z)
