"""Realtime camera runtime.

The engine owns one background thread.  Each iteration it:

1. reads the *heartbeat* word (the game rewrites the camera eye every frame);
2. when the game has produced a fresh camera, it computes the requested pose
   from the freshest player anchor and writes eye+target in one pipelined PINE
   burst.

That phase-lock is what keeps the override deterministic: we never race the
game's own camera update, we always write immediately *after* it.  When the
game stops writing (paused, menu, movie) the engine simply stops writing too.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from core.camera_math.orbit import (
    CameraPose,
    FOV_MAX_DEG,
    FOV_MIN_DEG,
    Vec3,
    clamp,
    FOV_SCALE_REF,
    fov_deg_to_scale,
    orbit_pose,
    scale_to_fov_deg,
    walk_target,
)

MODE_ORIGINAL = "original"
MODE_ORBIT = "orbit"
MODE_FREE = "free"
#: seconds to wait before retrying a failed PINE patch or projection write
PATCH_RETRY_S = 1.0


@dataclass
class CameraSettings:
    mode: str = MODE_ORIGINAL
    yaw_deg: float = 0.0
    pitch_deg: float = 40.9
    distance: float = 28.7
    # camera-position offsets in world space
    pos_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # look-at offsets relative to the player anchor.  (0,0,0) means "keep the
    # game's own look height", which is the safe default for every scene.
    target_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # free-camera absolute position/target
    free_eye: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    free_target: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov_deg: float = 54.68
    use_fov: bool = False
    #: how far the orbit centre sits from the player anchor, in world units
    #: along +Y.  FFX-2 stores +Y downwards, and the stock camera aims 5 units
    #: below the party anchor, so 5.0 reproduces the vanilla framing.
    look_height: float = -6.0
    # input
    sensitivity: float = 1.0
    rotate_speed_deg: float = 150.0
    deadzone: float = 0.12
    invert_x: bool = False
    invert_y: bool = False
    smoothing: float = 0.35
    pitch_min_deg: float = -20.0
    pitch_max_deg: float = 85.0


@dataclass
class RuntimeStats:
    running: bool = False
    mode: str = MODE_ORIGINAL
    fps: float = 0.0
    writes_per_sec: float = 0.0
    last_write_ms: float = 0.0
    last_error: str = ""
    applied_pose: tuple | None = None
    game_pose: tuple | None = None
    player: tuple | None = None
    fov_now: float = 0.0
    heartbeats: int = 0
    total_writes: int = 0
    #: times the game overwrote our offset/aim and the runtime re-published
    resyncs: int = 0
    #: times the projection centre was pulled back to the field value
    projection_fixes: int = 0
    connected: bool = False


class CameraRuntime:
    def __init__(self, adapter, settings: CameraSettings | None = None,
                 poll_hz: float = 1200.0, strategy: str = "continuous") -> None:
        self.adapter = adapter
        self.settings = settings or CameraSettings()
        self.poll_hz = poll_hz
        #: "continuous" writes the pose as fast as PINE allows (robust against
        #: an unknown render point in the frame); "phase" only writes right
        #: after the game's own camera refresh (lowest bus load).
        self.strategy = strategy
        self.stats = RuntimeStats()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stick = (0.0, 0.0)
        self._fov_dirty = True
        self._last_written: int | None = None
        self._hold_pose: CameraPose | None = None
        self._freeze = False
        self._lock = threading.Lock()
        self._orig_fov: float | None = None
        self._last_hb = None
        self._fov_written: float | None = None
        self._fov_released = False
        self._scene = None
        self._cached_player = None
        self._cached_target = None
        self._scene_time = 0.0
        self._fov_checked = 0.0
        self._target_dirty = True
        self.scene_refresh_ms = 10.0
        self._writes_window: list[float] = []
        #: (offset, aim) as last published, None when a publish is due
        self._last_published = None
        #: last orbit parameters written to the game's slots
        self._last_orbit_key = None
        self._last_pass = 0.0
        #: the eye offset may be non-zero and needs clearing when the orbit is left
        self._offset_dirty = False
        #: look-at and stock-hook words: applied state (None = unknown), when they
        #: were last checked, the manual override (None = follow the mode) and the
        #: mode the override belongs to
        self._patch_on: bool | None = None
        self._patch_checked = 0.0
        self._patch_override: bool | None = None
        self._patch_mode = self.settings.mode
        #: no PINE patch or projection write before this time (set after a failure)
        self._retry_at = 0.0
        self._last_mirror = 0.0
        #: (scale, centre) the area had before the orbit took over the projection
        self._proj_saved: tuple | None = None
        self._scale_forced = False
        #: whether the projection source is redirected to the scale (None = unknown)
        self._redirect_on: bool | None = None
        self._redirect_checked = 0.0
        #: whether the game's right stick is held at centre (the orbit reads it instead)
        self._stick_block = False
        self._stick_retry_at = 0.0
        self._stick_checked_at = 0.0

    # --- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="camera-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self.stats.running = False
        self._sync_stick_block(False)

    def abandon(self) -> None:
        """Stop for good without touching the game.

        ``stop()`` + ``restore()`` write the game's stock words back, which is right for the game
        this runtime was made for and wrong for any other.  When the running game is no longer that
        one (see ``GuardedBackend``), this is the way out: the thread is ended, nothing is written,
        and the runtime must not be used again.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.stats.running = False
        self.stats.connected = False

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- external control ----------------------------------------------
    def set_stick(self, rx: float, ry: float) -> None:
        self._stick = (clamp(rx, -1.0, 1.0), clamp(ry, -1.0, 1.0))

    def freeze(self, flag: bool) -> None:
        """Temporarily pause the per-frame writes (debug / MCP experiments)."""
        self._freeze = flag

    def sync_to_game(self) -> bool:
        """Adopt the game's current pose as the orbit baseline (no snap).

        Yaw/pitch come from the real view axis (eye -> look-at point) so the
        first orbit frame does not spin the camera, while the orbit *radius*
        comes from the party anchor because that is what the camera circles.
        """
        try:
            pose = self.adapter.read_game_pose()
            player = self.adapter.read_player()
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = str(exc)
            return False
        yaw, pitch = pose.yaw_pitch()
        radius = (pose.eye - player).length()
        with self._lock:
            self.settings.yaw_deg = math.degrees(yaw)
            self.settings.pitch_deg = math.degrees(pitch)
            self.settings.distance = max(1.0, radius)
        return True

    def center_on_target(self) -> bool:
        """Move the camera so the party is exactly in the middle of the screen.

        The renderer's view axis is read from the live camera basis and the eye
        is placed ``distance`` units back along it from the party anchor.  This
        is the "move onto Yuna first, then rotate" step: it works even in fields
        whose scripted camera does not point at the party.
        """
        try:
            scene = self.adapter.read_scene()
            if not self.adapter.is_field_like(scene):
                self.stats.last_error = "scene guard: not a field camera"
                return False
            s = self.settings
            target = Vec3(scene.player.x + s.target_offset[0],
                          scene.player.y + s.look_height + s.target_offset[1],
                          scene.player.z + s.target_offset[2])
            native_center = getattr(self.adapter, "center_on_target", None)
            if callable(native_center):
                # Parameter-driven cameras can centre through their native control
                # fields, without racing the eye output or inventing scratch RAM.
                pose = native_center(max(0.5, s.distance), s.look_height)
                eye, target = pose.eye, pose.target
            else:
                eye = self.adapter.place_looking_at(target, max(0.5, s.distance))
                base = self.adapter.read_eye_base()
                self.adapter.write_eye_offset(Vec3(eye.x - base.x, eye.y - base.y, eye.z - base.z))
                self.adapter.backend.write_float_block(self.adapter.CAM_EYE_ADDR,
                                                       (eye.x, eye.y, eye.z))
                # Aim control: the renderer derives its view axis as
                # normalize(aim - eye), so publishing the anchor as the aim point is
                # what actually puts the party in the middle of the screen.
                self.adapter.write_aim(target)
            # adopt the geometry we just produced so a later Orbit starts here
            off = eye - target
            horizontal = math.hypot(off.x, off.z)
            with self._lock:
                self.settings.yaw_deg = math.degrees(math.atan2(off.x, off.z))
                self.settings.pitch_deg = math.degrees(math.atan2(-off.y, horizontal))
                self.settings.distance = max(0.5, off.length())
            self._scene = None
            return True
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = f"center: {exc}"
            return False

    def capture_original_fov(self) -> None:
        """Remember the area's own FOV (used by reset).

        This must not touch ``settings.fov_deg``: that is the value the user asked
        for, and overwriting it with the area's native FOV made the FOV control
        appear dead in areas whose native zoom differs from the field.
        """
        try:
            self._orig_fov = self.adapter.capture_original_fov()
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = str(exc)

    def _hold_projection(self) -> None:
        """Keep the field framing while orbiting, the same in every area.

        Some areas switch the projection: other_area_base uses a centre of 900 (the
        whole image moves off the look-at point) and a scale of 1024 (zoomed).  The
        centre is forced to the field value.  The scale is forced to the stock
        field value unless the user set a FOV, in which case ``_service_fov`` owns
        it.  The area's own values are remembered and handed back on restore.
        """
        try:
            scale, centre = self.adapter.read_projection()
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = f"projection: {exc}"
            return
        if self._proj_saved is None:
            self._proj_saved = (scale, centre)
        target = self.adapter.field_projection_centre
        if abs(centre - target) > 0.5:
            self.adapter.write_projection_centre(target)
            self.stats.projection_fixes += 1
        if not self.settings.use_fov and abs(scale - FOV_SCALE_REF) > 0.5:
            self.adapter.write_projection_scale(FOV_SCALE_REF)
            self._scale_forced = True
            self.stats.projection_fixes += 1

    def _release_projection(self, restore: bool) -> None:
        """Stop holding the projection.  ``restore`` hands back the saved values."""
        saved, self._proj_saved = self._proj_saved, None
        forced, self._scale_forced = self._scale_forced, False
        if restore and saved is not None:
            try:
                self.adapter.write_projection_centre(saved[1])
                if forced:
                    self.adapter.write_projection_scale(saved[0])
            except Exception as exc:  # noqa: BLE001
                self.stats.last_error = f"projection: {exc}"

    def _set_projection_redirect(self, on: bool, force: bool = False) -> None:
        """Point the packet's projection source at the scale only while orbiting.

        In other_area_base the stock packet takes its source from the centre slot,
        so the FOV scale never reaches the image there.  The adapter redirects that
        one load (``set_projection_source``).  That is an instruction change made
        once, not a value rewritten per frame, so the game cannot race it.  The
        state is checked about once a second, so a savestate load is corrected then.
        """
        set_source = getattr(self.adapter, "set_projection_source", None)
        if not callable(set_source):
            return
        now = time.perf_counter()
        if not force and now < self._retry_at:
            return
        if not force and self._redirect_on == on and now - self._redirect_checked < 1.0:
            return
        self._redirect_checked = now
        try:
            set_source(on)
            self._redirect_on = on
        except Exception as exc:  # noqa: BLE001
            self._redirect_on = None
            self._retry_at = now + PATCH_RETRY_S
            self.stats.last_error = f"projection source: {exc}"

    def _leave_orbit_projection(self, force: bool = False) -> None:
        """The orbit no longer drives the projection: hand it back to the area."""
        self._release_projection(restore=True)
        self._set_projection_redirect(False, force=force)

    def set_patch_override(self, on: bool | None) -> None:
        """Load (True) or remove (False) the game patch by hand; None follows the mode.

        The override is dropped as soon as the camera mode changes.
        """
        self._patch_override = on

    def _patch_wanted(self, mode: str) -> bool:
        if self._patch_override is not None:
            return self._patch_override
        return mode in (MODE_ORBIT, MODE_FREE)

    def _sync_patch(self, mode: str, field_ok: bool = True, force: bool = False) -> None:
        """Bring the look-at and stock-hook words in line with the mode or the override.

        They are applied while the orbit or the free camera is on and put back to
        stock in the original camera, so the patched code only runs while the
        runtime is there to feed it.  The words are re-checked about once a second:
        a savestate load restores the stock words, and that is corrected within a
        second.  A failed write waits PATCH_RETRY_S before the next attempt.
        """
        if mode != self._patch_mode:
            self._patch_mode = mode
            self._patch_override = None
        now = time.perf_counter()
        if not force and now < self._retry_at:
            return
        want = self._patch_wanted(mode)
        set_patch = getattr(self.adapter, "set_patch", None)
        if callable(set_patch) and (force or self._patch_on != want
                                    or now - self._patch_checked >= self._recheck_s()):
            self._patch_checked = now
            try:
                if want and self._patch_on is not True:
                    self._seed_slots()
                    # the seed overwrote what the orbit and the aim last published,
                    # so both must be published again even if the pose has not moved
                    self._last_orbit_key = None
                    self._last_published = None
                set_patch(want)
                self._patch_on = want
            except Exception as exc:  # noqa: BLE001
                self._patch_on = None
                self._retry_at = now + PATCH_RETRY_S
                self.stats.last_error = f"patch: {exc}"
                return
        # with the look-at patch applied the renderer reads the aim slot, which
        # only the orbit keeps current; otherwise it has to follow the game's aim
        if self._patch_on is True and not (field_ok and mode in (MODE_ORBIT, MODE_FREE)):
            self._mirror_aim()

    def _sync_stick_block(self, on: bool) -> None:
        """Hold the game's right stick at centre while the orbit runs (adapters that can).

        The orbit takes its stick from the PC side, so the game's own use of the right
        stick (the item bar cursor) is stopped only while the orbit is on.  A failed write
        is retried after PATCH_RETRY_S.
        """
        now = time.perf_counter()
        if now < self._stick_retry_at:
            return
        # While the block is on, the game's memory is checked again every PATCH_RETRY_S: a
        # savestate load or a reset puts the original call site back without telling us.
        if self._stick_block == on and (not on or now < self._stick_checked_at):
            return
        set_block = getattr(self.adapter, "set_stick_block", None)
        if callable(set_block):
            try:
                set_block(on)
            except Exception as exc:  # noqa: BLE001
                self._stick_retry_at = now + PATCH_RETRY_S
                self.stats.last_error = f"stick block: {exc}"
                return
        self._stick_block = on
        self._stick_checked_at = now + self._recheck_s()

    def _seed_slots(self) -> None:
        """Fill the slots the patched loads will read with the stock values first.

        Otherwise the first patched frame would read whatever the slots held last,
        which shows up as a one-frame jump of the camera.
        """
        copy_stock = getattr(self.adapter, "copy_stock_params", None)
        if callable(copy_stock):
            copy_stock()
        restore_aim = getattr(self.adapter, "restore_aim", None)
        if callable(restore_aim):
            restore_aim()

    def _mirror_aim(self) -> None:
        """Copy the game's own look-at point into the slot the patched load reads."""
        restore_aim = getattr(self.adapter, "restore_aim", None)
        if not callable(restore_aim):
            return
        now = time.perf_counter()
        if now - self._last_mirror < self.scene_refresh_ms / 1000.0:
            return
        self._last_mirror = now
        try:
            restore_aim()
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = f"aim: {exc}"

    def _clear_offset(self) -> None:
        """Remove the orbit's eye offset.  The game itself never writes it."""
        self.adapter.backend.write_float_block(self.adapter.CAM_EYE_OFFSET_ADDR, (0.0, 0.0, 0.0))
        self._offset_dirty = False

    def restore(self) -> None:
        """Full restore: stop overriding and hand the camera back to the game."""
        with self._lock:
            self.settings.mode = MODE_ORIGINAL
            self.settings.use_fov = False
        self._patch_override = None
        self._sync_stick_block(False)
        try:
            if getattr(self.adapter, "uses_offset_injection", False):
                self.adapter.clear_eye_offset()
                self._offset_dirty = False
                # put the eye itself back as well: while the controller is idle
                # nobody else would refresh it
                base = self.adapter.read_eye_base()
                self.adapter.backend.write_float_block(self.adapter.CAM_EYE_ADDR,
                                                       (base.x, base.y, base.z))
            # the stock words first: from here on the game reads its own camera
            self._sync_patch(MODE_ORIGINAL, force=True)
            # hand the look-at point back too, otherwise the camera would keep
            # aiming at wherever we left it until the scene reloads
            restore_aim = getattr(self.adapter, "restore_aim", None)
            if callable(restore_aim):
                restore_aim()
            self.adapter.restore_fov()
            self._leave_orbit_projection(force=True)
            self._passthrough(force=True)
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = str(exc)
        self._hold_pose = None
        self._last_written = None
        self._last_published = None
        self._fov_written = None
        self._fov_released = True
        self._scene = None

    def snapshot(self) -> CameraSettings:
        with self._lock:
            return CameraSettings(**{**self.settings.__dict__,
                                     "pos_offset": list(self.settings.pos_offset),
                                     "target_offset": list(self.settings.target_offset),
                                     "free_eye": list(self.settings.free_eye),
                                     "free_target": list(self.settings.free_target)})

    # --- main loop ------------------------------------------------------
    def _loop(self) -> None:
        self.stats.running = True
        period = 1.0 / self.poll_hz
        last = time.perf_counter()
        last_stat = last
        last_pose: CameraPose | None = None
        n_pose = 0
        n_hb = 0
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = min(0.1, now - last)
            last = now
            try:
                self._tick(dt, last_pose)
                last_pose = self.stats_applied_pose()
                self.stats.connected = True
                if "write blocked" in self.stats.last_error:
                    # a refusal by the game guard is temporary unless the GUI abandons us
                    self.stats.last_error = ""
            except Exception as exc:  # noqa: BLE001
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
                self.stats.connected = False
                time.sleep(0.05)
            if now - last_stat >= 0.5:
                self.stats.fps = round(1.0 / max(1e-6, dt), 1) if dt else 0.0
                last_stat = now
            sleep = period - (time.perf_counter() - now)
            if sleep > 0:
                time.sleep(sleep)

    def stats_applied_pose(self) -> CameraPose | None:
        p = self._hold_pose
        return p

    def _integrate(self, dt: float) -> None:
        rx, ry = self._stick
        s = self.settings
        dz = s.deadzone
        mag = math.hypot(rx, ry)
        if mag < dz:
            return
        # re-scale past the deadzone so the response is continuous
        scale = (mag - dz) / (1.0 - dz)
        nx, ny = rx / mag * scale, ry / mag * scale
        if s.invert_x:
            nx = -nx
        if s.invert_y:
            ny = -ny
        # Adapter angles stay in their native/saved convention.  A Y-up game
        # needs the opposite input sign to the core's Y-down default, and its
        # explicit pitch range must also override old saved generic limits.
        ny *= getattr(self.adapter, "PITCH_INPUT_SIGN", 1.0)
        pitch_lo, pitch_hi = getattr(self.adapter, "PITCH_RANGE",
                                     (s.pitch_min_deg, s.pitch_max_deg))
        rate = s.rotate_speed_deg * s.sensitivity
        with self._lock:
            self.settings.yaw_deg += nx * rate * dt
            self.settings.pitch_deg = clamp(
                self.settings.pitch_deg + ny * rate * dt, pitch_lo, pitch_hi)
            self.settings.yaw_deg = (self.settings.yaw_deg + 180.0) % 360.0 - 180.0

    def _tick(self, dt: float, _unused) -> None:
        self._integrate(dt)
        s = self.settings
        mode = s.mode
        self._sync_stick_block(mode == MODE_ORBIT)
        if mode == MODE_ORIGINAL:
            self.stats.mode = mode
            self._hold_pose = None
            self._last_written = None
            self._scene = None
            self._leave_orbit_projection()
            self._sync_patch(mode)
            self._passthrough()
            if self._offset_dirty:
                self._clear_offset()
            return

        if self._freeze:
            return

        # --- hot path -------------------------------------------------------
        # The renderer samples 0x340360 at some point inside the frame and the
        # game rewrites it once per frame.  Winning that race needs the write
        # loop to be as tight as possible, so the hot path performs *no reads*
        # and no per-iteration allocations: the scene (player anchor / look-at
        # height) is refreshed only every ``scene_refresh_ms`` and the pose is
        # recomputed from that cache.
        now = time.perf_counter()
        if (self._cached_player is None
                or (now - self._scene_time) * 1000.0 >= self.scene_refresh_ms):
            scene = self.adapter.read_scene()
            if not self.adapter.is_field_like(scene):
                self.stats.last_error = "scene guard: not a field camera"
                self._scene = None
                self._release_projection(restore=False)
                self._set_projection_redirect(False)
                self._sync_patch(mode, field_ok=False)
                self._passthrough()
                return
            self._scene = scene
            if self.stats.last_error == "scene guard: not a field camera":
                self.stats.last_error = ""  # the scene is accepted again (focus has settled)
            self._cached_player = scene.player
            self._cached_target = scene.game_pose.target
            self._scene_time = now
            self.stats.player = scene.player.as_tuple()
            self.stats.game_pose = (scene.game_pose.eye.as_tuple(), scene.game_pose.target.as_tuple())
            self.stats.fov_now = scene.fov_deg
            self._verify_published()
            self._sync_patch(s.mode)
            if s.mode == MODE_ORBIT and self._patch_on is True:
                self._set_projection_redirect(True)
                self._hold_projection()
            else:
                self._leave_orbit_projection()
            self._service_fov(s, now)

        player = self._cached_player
        game_target = self._cached_target
        yaw_deg, pitch_deg, distance = s.yaw_deg, s.pitch_deg, s.distance
        if mode == MODE_ORBIT:
            # Orbit centre = the *party anchor*, not the game's current look-at
            # point.  Several fields drive the camera from a scripted path, and
            # orbiting around whatever the game happens to look at leaves Yuna
            # off-centre there.  Anchoring on the player keeps her centred in
            # every field.
            ox, oy, oz = s.target_offset
            px = player.x + ox
            py = player.y + s.look_height + oy
            pz = player.z + oz
            cp = math.cos(math.radians(pitch_deg))
            rad_yaw = math.radians(yaw_deg)
            rad_pitch = math.radians(pitch_deg)
            d = distance if distance > 0.5 else 0.5
            ex = px + math.sin(rad_yaw) * cp * d
            ey = py - math.sin(rad_pitch) * d
            ez = pz + math.cos(rad_yaw) * cp * d
            ex += s.pos_offset[0]
            ey += s.pos_offset[1]
            ez += s.pos_offset[2]
            tx, ty, tz = px, py, pz
        elif mode == MODE_FREE:
            ex, ey, ez = s.free_eye
            tx, ty, tz = s.free_target
        else:
            return

        # --- stock camera hook ---------------------------------------------
        # With the .pnach hook the game's own eye routine builds the eye from
        # the orbit slots, so the orbit is published there (the walk reference
        # follows).  Everything below still corrects the render eye with the
        # offset, which covers standstill, where the game does not recompute.
        wrote = False
        if self._hook_ok():
            if mode == MODE_ORBIT:
                wrote = self._publish_orbit((px, py, pz), yaw_deg, pitch_deg, distance)
            else:
                self._passthrough()

        # --- publish --------------------------------------------------------
        # Neither camera word is raced any more:
        #   * the game recomputes 0x340360 = 0x340370 + 0x3403E0 every frame and
        #     never writes 0x3403E0 itself, so publishing the *offset* means the
        #     engine itself places the eye exactly where we want it;
        #   * the look-at load inside FUN_001b07a0 is retargeted by the .pnach to
        #     the dead slot 0x33FC40, which the game never touches.
        # So nothing has to be rewritten per frame: a write is only needed when
        # the pose itself changes (camera input) or when the game moves the base
        # position underneath us (the player walking).  No writes means no race,
        # which is what removes the flicker.
        if getattr(self.adapter, "uses_offset_injection", True):
            wrote = self._publish_offset(mode, (ex, ey, ez), (tx, ty, tz)) or wrote
        if wrote:
            self.stats.total_writes += 1
            self._writes_window.append(now)
            self.stats.last_write_ms = now * 1000.0
        self._filter_now = now
        self.stats.applied_pose = ((ex, ey, ez), (tx, ty, tz))
        self.stats.mode = mode
        w = self._writes_window
        if len(w) > 80:
            self._writes_window = [t for t in w if now - t <= 1.0]
        self.stats.writes_per_sec = float(len(self._writes_window))

    def _service_fov(self, s: CameraSettings, now: float) -> None:
        """FOV is a persistent value; check it at most a few times per second."""
        if now - self._fov_checked < 0.25:
            return
        self._fov_checked = now
        try:
            if s.use_fov:
                if self._fov_written is None:
                    self._fov_written = self.adapter.capture_original_fov()
                in_sync = getattr(self.adapter, "fov_in_sync", None)
                if callable(in_sync):
                    synced = in_sync(s.fov_deg)
                else:
                    want = fov_deg_to_scale(s.fov_deg)
                    got = self.adapter.backend.read_floats(0x340B00, 1)[0]
                    synced = abs(got - want) <= 0.05
                if not synced:
                    self.adapter.write_fov_deg(s.fov_deg)
                    self._fov_written = s.fov_deg
            elif self._fov_written is not None:
                self.adapter.restore_fov()
                self._fov_written = None
            if self._fov_released:
                self.adapter.restore_fov()
                self._fov_released = False
        except Exception as exc:  # noqa: BLE001
            self.stats.last_error = f"fov: {exc}"

    def _recheck_s(self) -> float:
        """How often the patch and the stick block are checked while on (adapters may ask for less)."""
        return float(getattr(self.adapter, "patch_recheck_s", PATCH_RETRY_S))

    def _hook_ok(self) -> bool:
        """Whether the look-at and stock-hook words are applied (see _sync_patch)."""
        return self._patch_on is True

    def _publish_orbit(self, centre: tuple, yaw_deg: float, pitch_deg: float,
                       distance: float) -> bool:
        """Write the orbit parameters to the game's eye-routine slots when they change.

        Returns True when something was written.
        """
        pos = tuple(round(v, 4) for v in self.settings.pos_offset)
        look_height = self.settings.look_height + self.settings.target_offset[1]
        key = (tuple(round(v, 4) for v in centre), round(yaw_deg, 4),
               round(pitch_deg, 4), round(distance, 4), pos, round(look_height, 4))
        if key == self._last_orbit_key:
            return False
        if getattr(self.adapter, "accepts_orbit_offsets", False):
            # Independent eye/target offsets, relative to the SAME sampled anchor.
            # The guest adds its current actor translation at render-update time.
            self.adapter.write_orbit_params(
                Vec3(*centre), yaw_deg, pitch_deg, distance,
                pos_offset=Vec3(*self.settings.pos_offset),
                target_offset=Vec3(self.settings.target_offset[0], look_height,
                                   self.settings.target_offset[2]))
        elif getattr(self.adapter, "accepts_pos_offset", False):
            # an adapter that moves the whole camera rig takes the camera-position offsets too
            self.adapter.write_orbit_params(Vec3(*centre), yaw_deg, pitch_deg, distance,
                                            pos_offset=Vec3(*self.settings.pos_offset))
        elif getattr(self.adapter, "accepts_look_height", False):
            self.adapter.write_orbit_params(Vec3(*centre), yaw_deg, pitch_deg, distance,
                                            look_height=look_height)
        else:
            self.adapter.write_orbit_params(Vec3(*centre), yaw_deg, pitch_deg, distance)
        self._last_orbit_key = key
        return True

    def _publish_offset(self, mode: str, eye: tuple, target: tuple) -> bool:
        """Eye-offset injection, for a game that adds the offset to the eye it builds.

        An adapter whose game places the eye from the orbit slots
        (``uses_offset_injection`` False) skips this: each read and write here is a
        PINE round trip with no effect on the game.  Returns True when the offset or
        the aim changed.
        """
        backend = self.adapter.backend
        base = self.adapter.read_eye_base()
        ex, ey, ez = eye
        tx, ty, tz = target
        if mode == MODE_ORBIT and self._hook_ok():
            # The stock walk heads along target - base.  Aim the target so that the
            # difference is centre - eye, whatever base the game currently has.
            # The game re-copies the target each frame, so this is written per tick.
            aim = walk_target(Vec3(tx, ty, tz), base, Vec3(ex, ey, ez))
            self.adapter.write_walk_target(aim)
        offset = (ex - base.x, ey - base.y, ez - base.z)
        key = (offset, (tx, ty, tz))
        if key == getattr(self, "_last_published", None):
            return False
        backend.write_float_block(self.adapter.CAM_EYE_OFFSET_ADDR, offset)
        backend.write_float_block(self.adapter.CAM_TARGET_ADDR, (tx, ty, tz))
        self._offset_dirty = True
        self._last_published = key
        return True

    def _passthrough(self, force: bool = False) -> None:
        """Keep the game's slots mirroring the stock blend while the orbit is off.

        The stock eye routine reads the slots now, so when the orbit is not in
        use they must carry the stock values or the stock camera would freeze
        at the last orbit.  Throttled to the scene-refresh rate.
        """
        if not self._hook_ok():
            return
        now = time.perf_counter()
        if not force and now - self._last_pass < self.scene_refresh_ms / 1000.0:
            return
        self._last_pass = now
        self._last_orbit_key = None
        self.adapter.copy_stock_params()

    def _verify_published(self) -> None:
        """Re-publish when the game has overwritten what we wrote last.

        Publishing skips a write while the pose key is unchanged, which is right
        as long as our offset and aim survive.  Area changes, cut-ins and camera
        resets can clear the additive offset or the aim slot without changing the
        key, and the camera then falls back to the stock pose until the party
        moves.  Reading both words back once per scene refresh (every 10 ms)
        closes that gap.
        """
        last = self._last_published
        if last is None:
            return
        offset, aim = last
        backend = self.adapter.backend
        off_now = backend.read_floats(self.adapter.CAM_EYE_OFFSET_ADDR, 3)
        aim_now = backend.read_floats(self.adapter.CAM_TARGET_ADDR, 3)
        if (max(abs(a - b) for a, b in zip(off_now, offset)) > 1e-3
                or max(abs(a - b) for a, b in zip(aim_now, aim)) > 1e-3):
            self._last_published = None
            self.stats.resyncs += 1

    @staticmethod
    def _raw_bits(value: float) -> int:
        import struct
        return struct.unpack("<I", struct.pack("<f", float(value)))[0]
