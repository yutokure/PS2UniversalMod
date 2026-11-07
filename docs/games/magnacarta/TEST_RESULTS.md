# マグナカルタ — 今回の確認と制限

2026-11-07、SLPS-25401 / EB925207、作業branch `feat/magnacarta-orbit`。
実装側の自己検証であり独立レビューではない。[方式](CAMERA.md)参照。

## 実行したこと

- 提供4stateを読み取り専用の解析元として展開。元stateは上書きしない。
  `walking_base`、`walking_base_only_wait`、`walking_base_chara_and_camera_move`、`running_base` の
  全5hook stock pair と選択cave空き、camera geometry／mode差を照合。
- 開始時のユーザー場面を別パスへ保存。実験はstock stateへ繰り返し戻し、ISO/メモリーカードを変更しない。
- camera eye/view の書込みwatchpoint → native call stack → Ghidra 関数の対応を確認。
- temporary data vtable bootstrapからEE threadで全5site適用・復元。PINEからゲーム命令の直接bootstrap書換えはしない。
- Orbitの回転と水平FOV20 / 55 / 80 / 110°で、画面・実builder readback・heartbeat進行を確認。
  値だけ変わる無効mirrorではない。Original／解除でnative55°、全hook stock、vtable `0x2B3940`へ復帰。
- real keyboard-backed left analog「上」をwalking/running × yaw0/90/180/270°で各約0.35秒入力。
  nativeの逆基底を補正後、7条件で移動ベクトルは期待forwardとdot約0.998以上。
  yaw270°は障害物近傍でwalking約0.708 / running約0.787、native headingは両方0°へ変化。
  これは衝突を迂回しない確認で、全方向・長時間を保証しない。
- ミニマップは原作のPawn headingを使うことを逆コンパイル・命令から確認し、上記4yaw入力時の
  実heading（49152 / 32768 / 16384 / 0）と画面上の矢印追従を確認。静止camera回転だけでactor矢印を書換えない。
- 走行時の広域表示：既存monsterから約700unitsの位置で、同じalpha consumer入口の実引数をbreakpoint測定。
  OFF=`f1=240.0, distance≈701.13`、ON=`f1=960.0, distance≈699.35`。
  原作mode=1／Pawn range=5／native sight240は保持。ON/OFFで敵の可視・minimap反応差を確認。
- エンカウント：同じ最寄monsterの位置へ一時的にplayer位置を置く接触比較。
  stock時は戦闘へ移行する実画面を確認。ONではフィールドに留まり、OFFに戻すと
  active stateが `0xCCA0C0`→`0xCC9EC0`となり戦闘遷移エフェクトが出る。
  frame境界と接触姿勢によりstockで即座に移行しない試行もあり、常に固定秒数以内の発火とは主張しない。
  位置変更は解析用の一時実験のみ、製品機能にteleportはない。
- 最終sourceで4stateそれぞれにOrbit/FOV70/両toggleを適用し、同じadapterを保ったまま
  stock stateを読み直して再適用、cameraだけ解除→flags12、両toggle解除→全site stockを確認。
  最終的に開始時に退避したユーザー場面へ戻し、control blockゼロ・全hook stock・vtable native、
  入力中立・GUI終了・解析socket解放とした。
- no-encounters ONでオレンジのrange meshを描画しない。OFFで再表示。
  Orbit／wideだけでは隠さない。native radius／playerモード値は保持。

## GUI／共通安全

実際の MainWindow + GuardedBackend + PINE + runtime/status worker で次を順に実行。
APPDATAとQt geometryはローカル実験profileへ隔離し、ユーザー設定を上書きしない。

| 操作 | flags | FOV | 確認 |
|---|---:|---:|---|
| 起動 | 0 | 55 | Original、2toggle OFF、scene有効 |
| 有効化／中央へ | 1 | 55 | パラメータ方式のcentering、heartbeat進行 |
| FOV70 | 3 | 70 | spin/slider/runtime/readback同期 |
| 両toggle ON | 15 | 70 | cameraと独立laneが同居 |
| Original | 12 | 55 | toggle保持、camera/FOVはnative |
| 無効化 | 0 | 55 | 全5site stock、vtable元、toggle OFF |
| 通常close | 0 | 55 | 解除状態維持、PINE解放 |

最終の追加script-state guard入りsourceでも上記全段階成功。
ローカル証跡は `C:/PS2CameraLab/work/magnacarta/gui_evidence/20261107_174315_197687/`。
初回GUI試験でcentering method不足を検知し修正。次の試験でOriginal中FOV診断値残留を修正し、
最終再試験ではOriginal55°まで確認。初期試験を最終成功へ読み替えていない。

最終の下記12ファイル指定runは **369 passed / 61.92秒**、`git diff --check` も成功。
その後テストだけを追加し、centeringでnative eyeへ書かないこと／移動の逆基底補正を含む
`tests/test_magnacarta.py` は **76 passed / 0.82秒**。source本体はこの追加時に変更していない。
他ゲームのGUI境界は合成backendの回帰であり、他ゲームのPCSX2実機回帰ではない。

単体テストは合成memory／tiny R5900 interpreterを使い、native renderer自体はstub。
Serial+CRC誤版、GuardedBackend拒否、unknown hook/delay、cave/control破損、部分適用防止、
full128bit scratch、local yawだけの変更、scene/script-state失効、session-only／preset除外、
独立toggle failure/retry/cleanupと既存GUI境界を対象とする。実機成功の代用ではない。

## 未網羅・既知の制限

- 同一field付近の4提供state。全map、event、menu、battle特殊camera、長時間、地雷の別alpha consumerは未網羅。
- camera sceneはselector1/2に加えGameMagiのfull FName `0x31CC/0x31D3`とplayer所有を確認するが、
  すべてのscript状況を判別する保証ではない。
- no-encountersは通常のmonster接触遷移。既に開始した戦闘を中断せず、強制/script戦闘は無効化しない。
- 広域表示は原作の敵alpha consumerを歩行相当へ拡張するもので、地形の全域描画／無制限draw distanceではない。
- 樹木・壁の遮蔽、map外、camera collisionなし。移動衝突による横ずれは原作処理を保持する。
- guest lifecycle ACKはpause中完了不能。再開後retryが必要。
- 旧code caveが残るMOD入りstateはclean stockではない。source変更版間はstock state／ゲーム再起動が必要。

## ローカル確認コマンド

```powershell
python -m pytest -o addopts= tests/test_magnacarta.py tests/test_magnacarta_directions.py tests/test_magnacarta_gameplay.py tests/test_game_toggles.py tests/test_game_toggles_registration.py tests/test_game_time.py tests/test_gui.py tests/test_core.py tests/test_game_guard.py tests/test_talesofsymphonia_gui.py tests/test_innocentlife_gui.py tests/test_grandia2_gui.py -q
git diff --check
```

親ラボpytest.iniの `--timeout=300` に対しローカル環境にpytest-timeoutがないため、
環境を書き換えず `-o addopts=` で指定テストを実行した。
