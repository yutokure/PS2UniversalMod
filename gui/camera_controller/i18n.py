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
    "mode.original": {"en": "Original — game camera (game options independent)",
                      "ja": "オリジナル — ゲーム本来のカメラ（ゲーム固有設定は独立）"},
    "mode.orbit": {"en": "Orbit — rotate around the character", "ja": "オービット — キャラクターを中心に回転"},
    "mode.free": {"en": "Free Camera — detached viewpoint",
                  "ja": "フリーカメラ — キャラクターから切り離した視点"},
    "mode.autocenter": {"en": "Re-centre on the character when enabling",
                        "ja": "有効化時にキャラクターを画面中央へ"},
    "mode.hint": {"en": "Right stick (or the arrow keys while PCSX2 or this window has the focus) rotates. "
                        "The window always starts in Original; switch the mod on yourself.",
                  "ja": "右スティック（PCSX2 かこの画面が前面のときは矢印キーも）で回転します。"
                        "起動時は必ずオリジナルです。MOD は自分で有効にしてください。"},
    "mode.short.original": {"en": "original", "ja": "オリジナル"},
    "mode.short.orbit": {"en": "orbit", "ja": "オービット"},
    "mode.short.free": {"en": "free", "ja": "フリーカメラ"},
    # --- controls -------------------------------------------------------
    "group.controls": {"en": "Controls", "ja": "操作"},
    "btn.enable": {"en": "Enable Camera Mod", "ja": "カメラ MOD を有効化"},
    "btn.disable": {"en": "Disable Camera Mod", "ja": "カメラ MOD を無効化"},
    "btn.center": {"en": "Center on the character", "ja": "キャラクターを中央に"},
    "btn.reset": {"en": "Reset to the game view", "ja": "ゲームの視点に合わせ直す"},
    "btn.restore": {"en": "Disable and restore the original camera", "ja": "MOD を無効化して元のカメラに戻す"},
    "btn.save": {"en": "Save…", "ja": "保存…"},
    "btn.load": {"en": "Load", "ja": "読込"},
    "ctl.preset_tip": {"en": "Pick a preset here, then press “Load”. A preset changes values only, never the camera mode.",
                       "ja": "ここでプリセットを選び、「読込」を押します。プリセットは値だけを変え、カメラモードは変えません。"},
    "ctl.patch_tip": {"en": "Camera patches follow Orbit / Free Camera; Original restores them. "
                            "Independent clock and game-specific options may keep their own patches active.",
                      "ja": "カメラ用パッチはオービット／フリーカメラで適用し、オリジナルで戻します。"
                            "独立した時計停止・ゲーム固有パッチは、それぞれの選択に従います。"},
    # --- independent game clock (not emulator pause) --------------------
    "group.game_time": {"en": "In-game clock", "ja": "ゲーム内時間"},
    "time.pause": {"en": "Pause in-game clock", "ja": "ゲーム内時間を停止"},
    "time.explanation": {"en": "Stops only the in-game clock. Movement and animation continue; PCSX2 is not paused.",
                         "ja": "ゲーム内の時計だけを停止します。移動・アニメーションは続き、PCSX2 は一時停止しません。"},
    "time.supported": {"en": "Independent of camera mode. Off on startup/reconnect; presets never enable it.",
                       "ja": "カメラモードとは独立しています。起動・再接続時はオフで、プリセットでは有効になりません。"},
    "time.unsupported": {"en": "Unavailable: this adapter has no verified clock-only pause patch.",
                         "ja": "未対応：このアダプターには検証済みの時計専用停止パッチがありません。"},
    "time.paused": {"en": "Clock paused (observed)", "ja": "時計停止中（読戻し）"},
    "time.running": {"en": "Clock running (observed)", "ja": "時計進行中（読戻し）"},
    "time.unknown": {"en": "Clock state unconfirmed", "ja": "時計の状態は未確認"},
    # --- independent, session-only game options -------------------------
    "group.game_toggles": {"en": "Game-specific options", "ja": "ゲーム固有設定"},
    "toggle.wide_view_running": {"en": "Keep the wide view while running", "ja": "走行中も広い視界を維持"},
    "toggle.wide_view_running.explanation": {
        "en": "Keeps the wide walking view while running (the game's walking/running modes, not camera modes). Independent of Original / Orbit.",
        "ja": "ゲーム固有の歩行／走行モード差に対し、走行中も歩行時の広い視界を維持します。Original／Orbit とは独立です。"},
    "toggle.no_encounters": {"en": "Disable contact encounters and orange ring", "ja": "接触エンカウントとオレンジの丸枠を無効化"},
    "toggle.no_encounters.explanation": {
        "en": "Disables contact encounters and the orange ring around the character, as when walking in town. Independent of the wide-view and camera settings.",
        "ja": "町での歩行時のように、接触エンカウントとキャラ周囲のオレンジの丸枠を無効化します。広い視界・カメラ設定とは独立です。"},
    "toggle.supported": {
        "en": "Independent of camera mode. Off on startup/reconnect; never saved in presets. Disable-all and normal exit release it.",
        "ja": "カメラモードとは独立。起動・再接続時はオフで、プリセットには保存しません。無効化ボタン・正常終了で解除します。"},
    "toggle.wide_view_running.unsupported": {
        "en": "Unavailable: this adapter has no verified wide-view-while-running patch.",
        "ja": "未対応：このアダプターには検証済みの走行中の広い視界パッチがありません。"},
    "toggle.no_encounters.unsupported": {
        "en": "Unavailable: this adapter has no verified contact-encounter / orange-ring disable patch.",
        "ja": "未対応：このアダプターには検証済みの接触エンカウント・丸枠無効化パッチがありません。"},
    "toggle.on": {"en": "Enabled (observed)", "ja": "有効（読戻し）"},
    "toggle.off": {"en": "Disabled (observed)", "ja": "無効（読戻し）"},
    "toggle.unknown": {"en": "State unconfirmed", "ja": "状態は未確認"},
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
    "group.position": {"en": "Camera Position (world units; the Y direction depends on the game)",
                       "ja": "カメラ位置（ワールド単位。Y の向きはゲームによる）"},
    "pos.distance": {"en": "Distance from target", "ja": "ターゲットからの距離"},
    "pos.look_height": {"en": "Look-at height", "ja": "注視点の高さ"},
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
    "lens.unsupported": {"en": "Unavailable: FOV override is not verified for this adapter.",
                         "ja": "未対応：このアダプターの FOV 上書きは検証されていません。"},
    "lens.live": {"en": "Live", "ja": "現在値"},
    "lens.reset": {"en": "Reset FOV to game value", "ja": "FOV をゲーム値に戻す"},
    "lens.current": {"en": "{fov:.2f}° (scale {scale:.1f})",
                     "ja": "{fov:.2f}°（スケール {scale:.1f}）"},
    "lens.current_none": {"en": "-", "ja": "-"},
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
    # --- added by the 2026-11-02 GUI audit ---------------------------------
    "title.game": {"en": "{app} — {game}", "ja": "{app} — {game}"},
    "game.radiata": {"en": "Radiata Stories", "ja": "ラジアータ ストーリーズ"},
    "game.minstrelsong": {"en": "Romancing SaGa -Minstrel Song-", "ja": "ロマンシング サガ -ミンストレルソング-"},
    "game.dragonquest5": {"en": "Dragon Quest V", "ja": "ドラゴンクエストV 天空の花嫁"},
    "game.innocentlife": {"en": "Innocent Life: A Futuristic Harvest Moon", "ja": "新牧場物語 ピュア イノセントライフ"},
    "game.grandia2": {"en": "Grandia II", "ja": "グランディアII"},
    "game.talesofsymphonia": {"en": "Tales of Symphonia", "ja": "テイルズ オブ シンフォニア"},
    "game.magnacarta": {"en": "Magna Carta", "ja": "マグナカルタ"},
    "game.rpgmaker5": {"en": "RPG Maker 5", "ja": "RPGツクール5"},
    "group.offsets": {"en": "Offsets (advanced)", "ja": "オフセット（詳細）"},
    "group.offsets_set": {"en": "Offsets (advanced) - in use", "ja": "オフセット（詳細）― 設定あり"},
    "btn.advanced": {"en": "Show advanced", "ja": "詳細を表示"},
    "hint.look_down": {"en": "Look-at height: a positive value moves the aim point DOWN.",
                       "ja": "注視点の高さ: 正の値で注視点が下へ動きます。"},
    "hint.look_up": {"en": "Look-at height: a positive value moves the aim point UP.",
                     "ja": "注視点の高さ: 正の値で注視点が上へ動きます。"},
    "hint.pitch_above": {"en": "Pitch: a positive value puts the camera ABOVE the character.",
                         "ja": "Pitch: 正の値でカメラがキャラクターより上に来ます。"},
    "hint.pitch_below": {"en": "Pitch: a positive value puts the camera BELOW (the game's own sign: negative = above).",
                         "ja": "Pitch: 正の値でカメラが下に来ます（このゲーム本来の符号。負が上）。"},
    "tip.enable": {"en": "Turn the camera mod on: the camera orbits the character and the right stick rotates it.",
                   "ja": "カメラ MOD を有効にします。カメラがキャラクターの周りを回り、右スティックで回転できます。"},
    "tip.restore": {"en": "Turn all mods off: restore the camera, right stick, zoom, in-game clock and game-specific options.",
                    "ja": "すべての MOD を止め、カメラ・右スティック・ズーム・ゲーム内時計・ゲーム固有設定を元に戻します。"},
    "tip.center": {"en": "Put the character in the middle of the screen, then rotate.",
                   "ja": "キャラクターを画面の中央に置いてから回転します。"},
    "tip.reset": {"en": "Take yaw, pitch and distance from the game's current view and clear the offsets.",
                  "ja": "ゲームの現在の視点から Yaw・Pitch・距離を取り直し、オフセットを 0 に戻します。"},
    "tip.distance": {"en": "Distance between the camera and the aim point.", "ja": "カメラと注視点の距離です。"},
    "tip.look_height": {"en": "Moves the aim point up or down (the sign depends on the game, see the line below).",
                        "ja": "注視点を上下に動かします（符号はゲームによります。下の説明を参照）。"},
    "tip.look_height_unsupported": {"en": "This game controls the aim height; it cannot be adjusted here.",
                                    "ja": "このゲームでは注視点の高さをゲーム側が決めるため、ここでは変更できません。"},
    "tip.cam_offset": {"en": "Moves the whole camera in the world; the viewing direction stays.",
                       "ja": "カメラ全体をワールド座標で動かします（向きは変わりません）。"},
    "tip.cam_eye_offset": {"en": "Moves only the camera eye along world axes; the aim point stays in place, so the viewing direction changes.",
                           "ja": "ワールド軸に沿って視点だけを動かします。注視点はそのままなので、見る方向も変わります。"},
    "tip.tgt_offset": {"en": "Moves the aim point in the world (the camera follows it).",
                       "ja": "注視点をワールド座標で動かします（カメラも付いていきます）。"},
    "tip.offsets_unsupported": {"en": "This game's adapter cannot use these offsets.",
                                "ja": "このゲームのアダプターはこのオフセットを使えません。"},
    "tip.fov": {"en": "Horizontal field of view. It only applies while the box below is ticked.",
                "ja": "水平方向の画角です。下のチェックを入れている間だけ反映されます。"},
    "tip.fov_orbit_only": {"en": "The selected field of view applies only in Orbit mode, with the override checked.",
                           "ja": "「FOV の上書きを適用」にチェックすると、オービット中だけ指定した画角を使います。"},
    "tip.speed": {"en": "How fast a full stick push turns the camera.", "ja": "スティックを倒し切ったときの回転の速さです。"},
    "tip.sens": {"en": "Multiplies the rotation speed.", "ja": "回転速度に掛かる倍率です。"},
    "tip.deadzone": {"en": "Stick movement below this is ignored (drift).",
                     "ja": "これ以下のスティックの動きは無視します（ドリフト対策）。"},
    "tip.input": {"en": "auto = pad and arrow keys. Arrow keys only count while PCSX2 or this window is in front.",
                  "ja": "auto = パッドと矢印キー。矢印キーは PCSX2 かこの画面が前面のときだけ有効です。"},
    "tip.autocenter": {"en": "When you enable the mod, move the camera so the character is in the middle.",
                       "ja": "MOD を有効にするとき、キャラクターが中央に来るようにカメラを合わせます。"},
    "tip.patch_load": {"en": "Advanced: apply the game patch by hand (it is applied automatically while the mod is on).",
                       "ja": "詳細: ゲームパッチを手動で適用します（MOD 有効中は自動で適用されます）。"},
    "tip.patch_remove": {"en": "Advanced: remove the game patch by hand.", "ja": "詳細: ゲームパッチを手動で外します。"},
    "tip.zoom_stage": {"en": "Orbit mode only: use the distance of this stage of the game's zoom.",
                       "ja": "オービット中のみ: ゲーム標準ズームのこの段階の距離を使います。"},
    "tip.zoom_stage_off": {"en": "Enable the camera mod first.", "ja": "先にカメラ MOD を有効にしてください。"},
    "notice.lost": {"en": "PCSX2 is not reachable. The controls come back when it is.",
                    "ja": "PCSX2 に接続できません。復帰すると操作が使えるようになります。"},
    "notice.no_game": {"en": "Start a supported game in PCSX2 (PINE must be enabled), then press Reconnect.",
                       "ja": "PCSX2 で対応ゲームを起動し（PINE を有効に）、「再接続」を押してください。"},
    "notice.unsupported": {"en": "Unsupported game or disc version: {gid} / {crc}. Nothing is written.",
                           "ja": "未対応のゲームまたは版です：{gid} / {crc}。何も書き込みません。"},
    "notice.not_field": {"en": "The game's field camera is not running now (loading, event or menu). "
                               "The mod waits and continues by itself.",
                         "ja": "ゲームのフィールドカメラが動いていません（ロード・イベント・メニュー中）。"
                               "MOD は待機し、戻れば自動で続けます。"},
    "notice.patch_unknown": {"en": "The game code at a patched address is not what the mod expects; it was left untouched. Restart the game.",
                             "ja": "パッチ箇所のゲームコードが想定と違うため、触れていません。ゲームを再起動してください。"},
    "notice.action_failed": {"en": "That did not work: {err}", "ja": "操作に失敗しました：{err}"},
    "dlg.overwrite_title": {"en": "Overwrite preset?", "ja": "プリセットを上書きしますか？"},
    "dlg.overwrite_text": {"en": "A preset named \u201c{name}\u201d already exists. Overwrite it?",
                           "ja": "「{name}」という名前のプリセットが既にあります。上書きしますか？"},
    "dlg.single_title": {"en": "Already running", "ja": "すでに起動しています"},
    "dlg.single_text": {"en": "Another camera controller window is already open. Two of them would fight over PCSX2's single PINE connection.",
                        "ja": "別のカメラコントローラーが起動中です。2 つ同時に使うと PCSX2 の PINE 接続を奪い合います。"},
    # --- debug ----------------------------------------------------------
    "group.debug": {"en": "Debug", "ja": "デバッグ表示"},
    "dbg.eye": {"en": "Camera eye", "ja": "カメラ視点"},
    "dbg.aim": {"en": "Look-at point", "ja": "注視点"},
    "dbg.player": {"en": "Player anchor", "ja": "プレイヤー基準点"},
    "dbg.rate": {"en": "Update rate", "ja": "更新頻度"},
    "dbg.last": {"en": "Last update", "ja": "最終更新"},
    "dbg.warn": {"en": "Warning", "ja": "警告"},
    "dbg.rate_value": {"en": "{n:.0f} writes/s", "ja": "{n:.0f} 回/秒"},
    # --- status bar / dialogs -------------------------------------------
    "status.ready": {"en": "Ready", "ja": "準備完了"},
    "status.connected": {"en": "Connected", "ja": "接続しました"},
    "status.pcsx2_lost": {"en": "PCSX2 is not reachable. Waiting for it to come back...",
                          "ja": "PCSX2 に接続できません。復帰を待っています..."},
    "status.game_changed": {"en": "The game in PCSX2 changed. The previous game was left untouched; the camera was set up again for the new one.",
                            "ja": "PCSX2 のゲームが切り替わりました。前のゲームには何も書き込まず、新しいゲーム用に設定し直しました。"},
    "status.pcsx2_back": {"en": "PCSX2 is back; the camera settings are re-applied.",
                          "ja": "PCSX2 が復帰しました。カメラ設定を再適用します。"},
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
    "status.centered": {"en": "Camera centred on the character", "ja": "キャラクターを画面中央に合わせました"},
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
