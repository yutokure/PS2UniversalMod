"""Tiny runtime translation layer for the camera GUI.

No Qt Linguist toolchain: the catalogue is a plain dict, and widgets register
themselves so the language can be switched without restarting.  That keeps the
packaging story simple (``python run_gui.py`` still works with nothing built).

Keys are stable English identifiers; the value is the display string.
"""
from __future__ import annotations

LANGUAGES: dict[str, str] = {"ja": "日本語", "en": "English"}

#: key -> {lang: text}.  Missing entries fall back to English, then to the key.
TEXT: dict[str, dict[str, str]] = {
    # --- window / connection -------------------------------------------
    "app.title": {"en": "PS2 Universal Camera Controller", "ja": "PS2 ユニバーサル・カメラコントローラー"},
    "group.connection": {"en": "Connection", "ja": "接続"},
    "conn.pcsx2": {"en": "PCSX2:", "ja": "PCSX2："},
    "conn.game": {"en": "Game:", "ja": "ゲーム："},
    "conn.serial": {"en": "Serial / CRC:", "ja": "シリアル / CRC："},
    "conn.adapter": {"en": "Adapter:", "ja": "アダプタ："},
    "conn.runtime": {"en": "Runtime:", "ja": "実行状態："},
    "conn.patch": {"en": "Game patch:", "ja": "ゲームパッチ："},
    "conn.language": {"en": "Language:", "ja": "表示言語："},
    "btn.reconnect": {"en": "Reconnect", "ja": "再接続"},
    "state.disconnected": {"en": "Disconnected", "ja": "未接続"},
    "state.connected": {"en": "Connected", "ja": "接続済み"},
    "state.stopped": {"en": "Stopped", "ja": "停止"},
    "state.running": {"en": "Running", "ja": "実行中"},
    "state.stopped_original": {"en": "Stopped (original camera)", "ja": "停止（ゲーム本来のカメラ）"},
    "patch.active": {"en": "applied — orbit / free camera are patched",
                     "ja": "適用中 — オービット・フリーカメラ用の書き換えが有効"},
    "patch.stock": {"en": "not applied — original camera (the game's own code)",
                    "ja": "未適用 — ゲーム本来のカメラ（ゲームのコードのまま）"},
    "patch.partial": {"en": "PARTLY applied — press Load patch or Remove patch to make them match",
                      "ja": "一部のみ適用 — 「パッチを読み込む」か「パッチを外す」で揃えてください"},
    "patch.unknown": {"en": "UNKNOWN code at a patched address — left untouched; restart the game",
                      "ja": "パッチ箇所に不明なコードがあります — 触れていません。ゲームを再起動してください"},
    "patch.missing": {"en": "state unreadable — PCSX2 is not responding",
                      "ja": "状態を読めません — PCSX2 が応答していません"},
    "btn.patch_load": {"en": "Load patch", "ja": "パッチを読み込む"},
    "btn.patch_remove": {"en": "Remove patch", "ja": "パッチを外す"},
    # --- mode -----------------------------------------------------------
    "group.mode": {"en": "Camera Mode", "ja": "カメラモード"},
    "mode.original": {"en": "Original — game camera (mod off)",
                      "ja": "オリジナル — ゲーム本来のカメラ（MOD 停止）"},
    "mode.orbit": {"en": "Orbit — rotate around Yuna", "ja": "オービット — ユウナを中心に回転"},
    "mode.free": {"en": "Free Camera — detached viewpoint",
                  "ja": "フリーカメラ — キャラクターから切り離した視点"},
    "mode.autocenter": {"en": "Re-centre on Yuna when enabling",
                        "ja": "有効化時にユウナを画面中央へ"},
    "mode.hint": {"en": "Right stick / arrow keys rotate.  Orbit is the primary mode; "
                        "Free Camera ignores the player anchor.",
                  "ja": "右スティックまたは矢印キーで回転。オービットが主機能です。"
                        "フリーカメラはプレイヤー基準点を使いません。"},
    "mode.short.original": {"en": "original", "ja": "オリジナル"},
    "mode.short.orbit": {"en": "orbit", "ja": "オービット"},
    "mode.short.free": {"en": "free", "ja": "フリーカメラ"},
    # --- controls -------------------------------------------------------
    "group.controls": {"en": "Controls", "ja": "操作"},
    "btn.enable": {"en": "Enable Camera Mod", "ja": "カメラ MOD を有効化"},
    "btn.disable": {"en": "Disable Camera Mod", "ja": "カメラ MOD を無効化"},
    "btn.center": {"en": "Center on Yuna", "ja": "ユウナを中央に"},
    "btn.reset": {"en": "Reset Camera", "ja": "カメラをリセット"},
    "btn.restore": {"en": "Restore Original Camera", "ja": "元のカメラに戻す"},
    "btn.save": {"en": "Save Preset…", "ja": "プリセット保存…"},
    "btn.load": {"en": "Load Preset…", "ja": "プリセット読込…"},
    "ctl.preset_tip": {"en": "Pick a preset here, then press “Load Preset…”",
                       "ja": "ここでプリセットを選び、「プリセット読込…」を押します"},
    "ctl.patch_tip": {"en": "The game code is patched only while the orbit or the free camera "
                            "is on. Original puts the stock code back.",
                      "ja": "オービット／フリーカメラの使用中だけゲームのコードを書き換えます。"
                            "オリジナルに戻すと元のコードに戻します。"},
    # --- rotation -------------------------------------------------------
    "group.rotation": {"en": "Camera Rotation", "ja": "カメラ回転"},
    "rot.yaw": {"en": "Yaw (°)", "ja": "水平角 Yaw（°）"},
    "rot.pitch": {"en": "Pitch (°)", "ja": "上下角 Pitch（°）"},
    "rot.speed": {"en": "Rotation speed (°/s)", "ja": "回転速度（°/秒）"},
    "rot.sens": {"en": "Right stick sensitivity", "ja": "右スティック感度"},
    "rot.deadzone": {"en": "Deadzone", "ja": "デッドゾーン"},
    "rot.invert": {"en": "Invert", "ja": "反転"},
    "rot.invert_x": {"en": "Invert horizontal", "ja": "左右を反転"},
    "rot.invert_y": {"en": "Invert vertical", "ja": "上下を反転"},
    "rot.input": {"en": "Input source", "ja": "入力ソース"},
    # --- position -------------------------------------------------------
    "group.position": {"en": "Camera Position (world units, +Y is down in FFX-2 memory)",
                       "ja": "カメラ位置（ワールド単位。FFX-2 のメモリでは +Y が下向き）"},
    "pos.distance": {"en": "Distance from target", "ja": "ターゲットからの距離"},
    "pos.look_height": {"en": "Look-at height (Y)", "ja": "注視点の高さ（Y）"},
    "pos.cam_x": {"en": "Camera X offset", "ja": "カメラ X オフセット"},
    "pos.cam_y": {"en": "Camera Y offset", "ja": "カメラ Y オフセット"},
    "pos.cam_z": {"en": "Camera Z offset", "ja": "カメラ Z オフセット"},
    "pos.tgt_x": {"en": "Target X offset", "ja": "注視点 X オフセット"},
    "pos.tgt_y": {"en": "Target Y offset", "ja": "注視点 Y オフセット"},
    "pos.tgt_z": {"en": "Target Z offset", "ja": "注視点 Z オフセット"},
    "pos.free_eye": {"en": "Free eye X / Y / Z", "ja": "フリー視点 X / Y / Z"},
    "pos.free_target": {"en": "Free target X / Y / Z", "ja": "フリー注視点 X / Y / Z"},
    # --- lens -----------------------------------------------------------
    "group.lens": {"en": "Camera Lens (FOV)", "ja": "カメラレンズ（FOV）"},
    "lens.fov": {"en": "FOV (° horizontal)", "ja": "画角 FOV（°・水平）"},
    "lens.apply": {"en": "Apply FOV override", "ja": "FOV の上書きを適用"},
    "lens.live": {"en": "Live", "ja": "現在値"},
    "lens.reset": {"en": "Reset FOV to game value", "ja": "FOV をゲーム値に戻す"},
    "lens.current": {"en": "current: {fov:.2f}° (scale {scale:.1f})",
                     "ja": "現在: {fov:.2f}°（スケール {scale:.1f}）"},
    "lens.current_none": {"en": "current: -", "ja": "現在: -"},
    "mode.free_unsupported": {"en": "Not available for this game (Orbit follows the character).",
                              "ja": "このゲームでは利用できません（Orbit がキャラクターを追従します）。"},
    # --- native zoom (games with a built-in zoom, e.g. Suikoden V) -------
    "group.zoom": {"en": "Native zoom (game)", "ja": "ゲーム標準ズーム"},
    "zoom.live": {"en": "Game stage", "ja": "現在の段階"},
    "zoom.stages": {"en": "Orbit distance preset", "ja": "オービット距離プリセット"},
    "zoom.stage": {"en": "Stage {n}", "ja": "段階 {n}"},
    "zoom.current": {"en": "stage {n} of 3 (game distance {d:.0f})",
                     "ja": "段階 {n} / 3（ゲーム距離 {d:.0f}）"},
    "zoom.none": {"en": "not seen yet (enable the camera once)",
                  "ja": "未検出（一度カメラを有効にしてください）"},
    "zoom.follow": {"en": "R1 / game zoom steps the orbit distance",
                    "ja": "R1・ゲームのズーム操作でオービット距離を段階変更"},
    "zoom.note": {"en": "While the orbit is on, the right stick turns the camera and the game's "
                        "stick zoom is blocked. R1 still steps the game's three stages; with the "
                        "box above ticked each step also sets the orbit distance (400 / 300 / 200).",
                  "ja": "オービット中は右スティックがカメラ回転になり、ゲーム側のスティックズームは遮断されます。"
                        "R1 は従来どおり 3 段階ズームで、上のチェック時は段階に応じて"
                        "オービット距離（400 / 300 / 200）も切り替わります。"},
    # --- debug ----------------------------------------------------------
    "group.debug": {"en": "Debug", "ja": "デバッグ"},
    "dbg.eye": {"en": "Camera eye", "ja": "カメラ視点"},
    "dbg.aim": {"en": "Look-at point", "ja": "注視点"},
    "dbg.player": {"en": "Player anchor", "ja": "プレイヤー基準点"},
    "dbg.rate": {"en": "Update rate", "ja": "更新頻度"},
    "dbg.last": {"en": "Last update", "ja": "最終更新"},
    "dbg.warn": {"en": "Warning", "ja": "警告"},
    "dbg.rate_value": {"en": "{n:.0f} writes/s", "ja": "{n:.0f} 回/秒"},
    # --- status bar / dialogs -------------------------------------------
    "status.ready": {"en": "Ready", "ja": "準備完了"},
    "status.connected": {"en": "Connected to FFX-2", "ja": "FFX-2 に接続しました"},
    "status.pine_failed": {"en": "PINE connection failed: {err}", "ja": "PINE 接続に失敗：{err}"},
    "status.unsupported": {"en": "Unsupported game: {gid} {crc}",
                           "ja": "未対応のゲームです：{gid} {crc}"},
    "status.preset_saved": {"en": "Preset saved: {name}", "ja": "プリセットを保存しました：{name}"},
    "status.preset_loaded": {"en": "Preset loaded: {name}", "ja": "プリセットを読み込みました：{name}"},
    "status.preset_missing": {"en": "Preset not found: {name}", "ja": "プリセットが見つかりません：{name}"},
    "status.restored": {"en": "Original camera restored", "ja": "元のカメラに戻しました"},
    "status.patch_loaded": {"en": "Patch loaded (until the camera mode changes)",
                            "ja": "パッチを読み込みました（カメラモードを変えるまで）"},
    "status.patch_removed": {"en": "Patch removed (until the camera mode changes)",
                             "ja": "パッチを外しました（カメラモードを変えるまで）"},
    "status.patch_need_connection": {"en": "Connect to PCSX2 first", "ja": "先に PCSX2 に接続してください"},
    "status.centered": {"en": "Camera centred on Yuna", "ja": "ユウナを画面中央に合わせました"},
    "status.center_failed": {"en": "Could not centre: {err}", "ja": "中央合わせに失敗：{err}"},
    "status.language": {"en": "Language: {name}", "ja": "表示言語：{name}"},
    "dlg.preset_title": {"en": "Save preset", "ja": "プリセット保存"},
    "dlg.preset_label": {"en": "Preset name:", "ja": "プリセット名："},
    "dlg.load_title": {"en": "Load preset", "ja": "プリセット読込"},
    "dlg.load_label": {"en": "Preset:", "ja": "プリセット："},
    "err.not_connected": {"en": "not connected", "ja": "未接続"},
    "err.patch": {"en": "look-at patch not applied", "ja": "視線パッチが未適用です"},
    "err.scene": {"en": "scene guard: not a field camera",
                  "ja": "シーン判定：通常フィールドではありません"},
}

_current = "ja"


def set_language(lang: str) -> None:
    global _current
    if lang in LANGUAGES:
        _current = lang


def current_language() -> str:
    return _current


def tr(key: str, **fmt) -> str:
    """Translate ``key`` into the active language, formatting ``fmt`` if given."""
    table = TEXT.get(key, {})
    text = table.get(_current) or table.get("en") or key
    return text.format(**fmt) if fmt else text
