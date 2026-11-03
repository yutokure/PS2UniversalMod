# 最終ステータス — PS2 Universal Camera Controller (FFX-2)

更新: 2026-10-31 / 対象: `SLPS-25250` (CRC `8A6D7F14`) / PCSX2 `v2.7.499-12-g7235a0446`

> **履歴資料**: 以下は 2026-10-31 の測定記録。現行の起動・patch 手順は
> [README](<../../../README.md#51-ffx-2>)、実装と制限は [技術メモ](<ADAPTER_NOTES.md>) を参照。
> `.pnach` 必須・歩行未解決などは後の実装で変更済み。2026-11-02 のルカの高さずれ・
> ミニマップ修正と確認範囲は [メモリマップ訂正](<CAMERA_MEMORY_MAP.md#2026-11-02-訂正-演出カメラ切替時の-orbit-高さ>) に記録。

## 総合判定

**Orbit（ユウナ中心の右スティック旋回）は達成。ただし歩行方向はカメラに追従しない（B-08、未解決）。**
Free Camera も動作（追加機能として扱う）。

2026-10-31 追記（後半）: カメラ切り替えシーンで書き込みが止まる問題を修正（ガードの上限を 120 → 400、
ゲーム視点と注視点の上限を 400 → 2000）。`base_chara_little_moved_and_cam_big_moved.p2s` では
書き込みが始まり、スクリーンショットでユウナが中央に来ることを確認。`base_left_moved.p2s` でも中央。

2026-10-31 追記: 物理パッドの右スティック無反応は修正（XInput スロット 1 を自動検出）。
場面・エリア切り替え後の再書き込みを追加。歩行方向の原因は一部のみ特定（`docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md`）。

根拠は E2E 11/11 PASS と、以下の実測値。

| 項目 | 結果 | 証拠 |
|---|---|---|
| 右スティック水平旋回（360°目標） | yaw -0.58° → -93.39°、画面差分 mean 34.0 | `reports/e2e/e2e_results.json` E2E-03 |
| 右スティック垂直（仰角/俯角） | pitch 21.39° → 85.0°（クランプ動作） | E2E-04 |
| スティックを離すと保持 | hold_delta mean **0.0** | E2E-03 `hold_delta` |
| ユウナ移動への追従 | player が 14.9 単位移動、注視点は常に player+look_height | E2E-05 |
| GUI Yaw/Pitch | 画面差分 mean 40.8 | E2E-06 |
| GUI FOV | scale 619→381（80°）→復帰誤差 mean 1.28 | E2E-07 |
| GUI 距離 | 実測半径 12.000 | E2E-08 |
| GUI XYZ / 注視点オフセット | 5 軸すべて画面変化、復帰誤差 mean 1.29 | E2E-09 |
| 左スティック＋右スティック＋GUI 同時 | yaw +109°、エラーなし | E2E-10 |
| 元カメラへ復帰 | 復帰後の安定性 mean 1.49（ノイズ床） | E2E-11 |
| Free Camera | 画面差分 mean 26.3 | E2E-FREE |
| 既存4セーブステート非破壊 | SHA-256 全て一致 | 下記 |
| 単体テスト（`tests/test_core.py`） | 19/19 PASS（XInput スロット検出 3 件・再書き込み 2 件を追加） | `pytest tests/test_core.py` |

## 既存4ステートの保全

| ファイル | サイズ | SHA-256 |
|---|---|---|
| `base.p2s` | 11,909,651 | `681FFD0C…9BB9B9B` |
| `base_only_wait.p2s` | 11,910,340 | `3DABE251…344BC3` |
| `base_left_moved.p2s` | 11,892,369 | `A214145C…8BCCBC` |
| `base_chara_little_moved_and_cam_big_moved.p2s` | 11,848,974 | `30A9F798…68B99B` |

読み込み専用の複製を `C:\PS2CameraLab\backups\sstates_v2_protected\` に保持。
本 MOD はステートを**書き込みません**（読込のみ）。

## 達成した技術的ブレークスルー

1. **視線の実体を特定** — `forward = normalize(0x33FC10 − 0x340360)`。
   `FUN_001b07a0` が毎フレーム look-at 行列を構築。実測で描画基底と小数5桁一致。
2. **競合の原理的除去** — 視点はゲームの加算項 `0x3403E0` へオフセット注入、
   注視点は `.pnach` 1命令で読み取り先を未使用スロット `0x33FC40` へ移動。
   結果、保持中の書き込みは **35秒で1回**、連続フレーム差分 mean 0.50〜0.56。
3. **誤っていた経路の否定** — `FUN_001b0388` は初期化専用（強制実行すると 1 回ごとに
   視点が `dist` 後退）。`0x53AD80` / `0x33F620` / `0x3403B0` / `0x3312C0` はすべて出力ミラー。

詳細: `docs/games/ffx2/ORBIT_BREAKTHROUGH.md`、`docs/games/ffx2/CAMERA_MEMORY_MAP.md`（v2 追記）。

## 未達・制約（正直な分離）

| 項目 | 状況 |
|---|---|
| **物理ゲームパッドでの右スティック** | 修正済み。パッドは XInput スロット 1 にあり、旧実装はスロット 0 固定だったため無反応だった。自動検出に変更し、実機で `active_slot=1`・中立 (0,0) を確認。スティックを倒した際の実機検証は未実施 |
| **歩行方向のカメラ追従** | ❌ 未解決（BLOCKERS B-08）。歩行は MOD の描画カメラではなくゲーム本来のカメラ状態を基準にしている。詳細は `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md` |
| **場面・エリア切り替え後の復帰** | 追加: 10 ms ごとに視点オフセットと照準スロットを読み戻し、上書きされていれば再書き込み（`resyncs`）。単体テスト追加。実機での各エリア確認は未実施 |
| **壁抜け（E2E-03 の証拠画像）** | `E2E-03` は yaw を -93° まで回すが、その角度はこのマップ（セルシウス甲板）では船体の内側に当たり、`shots/E2E-03_yaw_held.png` は暗い床面になっている。**機構は正しい**が、外部カメラはゲームの衝突判定を通らないため角度によっては遮蔽される。旋回そのものの証拠は `hook/30_static_aim.png`（0°）、`hook/31_static_orbit50_a.png`（+50°）、`hook/40_product_a.png`（+50°, 製品コード経由）を使用すること |
| **壁抜け** | Orbit は球面上にカメラを置くため、狭い通路で 180° 回すと壁・天井の内側に入る。ゲーム側の衝突判定を経由しないため不可避。距離短縮か Pitch 低下で回避 |
| **イベント/戦闘/ムービー** | `is_field_like()` が false のとき書き込みを停止（基準点ゼロ、距離異常、視点-プレイヤー距離 > 120）。スクリプトカメラを完全に支配する実装ではないため、特殊シーンでは MOD が無効化される |
| **`.pnach` 必須** | 注視点注入には `cheats/8A6D7F14.pnach` が必要。無効時は GUI が `Look-at patch: NOT APPLIED` と警告し、位置のみ追従 |
| パッケージ化（exe） | 未実施（Python スクリプト起動）。優先度は低いと判断 |

## 対応範囲

**通常フィールドのみ**。戦闘・イベント・メニュー・ロード中は自動的に無効化されます。

## 起動

```
python gui/camera_controller/app.py
```

PCSX2 側で `EnableCheats` を有効にするか、MCP から
`set_cheats_enabled(true)` + `reload_patches` を実行してください。

## 証拠画像

| ファイル | 内容 |
|---|---|
| `reports/hook/60_gui.png` | GUI 全体（Look-at patch: active） |
| `reports/hook/30_static_aim.png` | 注視点=ユウナ、画面中央 |
| `reports/hook/40_product_a.png` | 製品コード経由で 50° 旋回 |
| `reports/hook/31_static_orbit50_a.png` | 静的注入のみ（書き込み1回）での旋回 |
| `reports/e2e/` | E2E 各シナリオの画面キャプチャ |
