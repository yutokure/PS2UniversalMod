# DQⅤ — 実行した確認と制限

実施日: **2026-11-05**。対象: 日本版 **SLPM-65555 / B64E9939**、PCSX2 fork `v2.7.499-12-g7235a0446`。
作業ベースHEAD `c5fe59a`、作業ブランチ`feature/dragonquest5-adapter`。
本書は実装側の確認であり、独立reviewのPASSではない。

## データ保護

- ISOからELFを読むだけで解析。ISO・原本4state・カードへ解析コードを書かない。
- 原本4stateを別ディレクトリへコピーし、開始時のVMも別ファイルへ保存した。
  終了時のSHA256照合で原本と保護コピーが一致。
- mounted folder cardの最初のコピーはPCSX2のexclusive lockで一部失敗し、shared-readも拒否された。
  VM状態を保護してPCSX2を正常終了後、完全コピーを作成し、DQ5保存本体のoriginal/backup/test copyのSHA256一致を確認した。
  以降の歩行・GUI試験は複製した2枚のカードで実施。終了時に元カード設定と開始時VMへ戻し、stock hookを読戻し、VMを再開してGDBを切断した。
  元DQ5保存本体は終了時もbackupとSHA256一致。
- RAM、ELF、state、カード、Ghidra出力、画像、実機JSONはリポジトリ外。Gitへは自作コード・テスト・解析要約のみ。

## 4stateでの実機readback

4つは同じ海辺の庭の通常field。別エリア・別camera classの網羅ではない。

| state | 実行内容 | 結果 |
|---|---|---|
| base | 表示pitch55°、yaw約−147.73°、さらにyaw+90°/pitch25°/FOV70°、実RX入力と解除 | 実画面・guest pose・実投影が変化、原作yaw保持、hook復元 |
| base_only_wait | yaw−57.73°、表示pitch55°、距離157.223、FOV70° | yaw−57.730002°、pitch54.999998°、FOV69.999997°、native rig/lens/yaw保持 |
| base_only_camera_move | yaw40°、表示pitch65°、FOV55°→解除 | yaw40.000000°、pitch65.000000°、FOV54.999998°、解除後stock水平FOV41.892142° |
| base_chara_and_camera_move | yaw150°、表示pitch89.5°、FOV40° | yaw149.999987°、pitch89.500001°、FOV40.000001°、変更後player位置へ注視点が追従 |

native eye/target/yaw/lensは原本とbit一致した。native WORLDには原作更新による丸め差があり、
`base_only_camera_move`と移動stateで最大約`1.19e-7`。bit完全一致ではなく、native再計算の微小差として記録した。
実機で一時WORLDの退避・返却が成立することと、synthetic runnerのexact transaction復元を別々に確認した。

qPcsx2のGS screenshotで原作にないpitch、水平回転、広角の実画面を確認した。
一方、GUI実機ツールのWin32 window captureは非表示PCSX2で**黒画像**を返した。
その画像を描画成功の証拠にはせず、GS screenshotとmemory readbackを根拠にする。GUI自身のgrabはフォント登録後に日本語表示を確認。

## GUI/runtime実機試験 — 19/19

実行:

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe tools/dragonquest5_live_check.py `
  --out C:/PS2CameraLab/test_evidence/dragonquest5/gui_run2 --move `
  --reload-handshake C:/PS2CameraLab/test_evidence/dragonquest5/reload2
```

外部MCPで同版stock stateを読み込み、VMをresumeしてhandshakeを完了した。
PINEはMainWindowの1接続だけを使用。APPDATAは一時ディレクトリで、ユーザー設定は変更しない。

- Original起動、Serial+CRC、GUI登録、Free無効と6offset/FOV有効。
- 2hook適用、yaw4条件、表示pitch **25/55/89.5/−25°**、距離130/150/180。
- 独立eye/target XYZとY-up高さ。eye誤差`9.81e-6`、target誤差`4.77e-7`。
- FOV **30/55/80°**をactual projectionから読戻し、native lensが元のまま。
- FOV解除がOrbitを残し、stock水平画角へ復帰。
- scripted右X/Yがyaw/pitchへ積分され、ゼロ入力後に実角度保持。
- 実PCSX2へkeyboard bindingで右RXを入力。processed RX=127を受信してもnative yawは変化しない。
- native eye/target/yaw/lens保持。
- host publicationをfreezeした0.25秒の左軸歩行。player移動 **15.4000**、相対注視点誤差 **0**、
  publication stamp不変かつguest heartbeat増加。**追従**の試験でありOrbit基準移動の成功ではない。
- stock state読込み後、同じcached requestでも2hook、yaw40°/表示pitch65°/距離170/FOV55°を再適用。
- Originalでhook/flags、native camera/projectionを復元し、実右入力で原作左右回転が再び動く。
- finally cleanupでhook/flagsを復元。

最初の`gui_run1`は17/19。offset groupを開く前のenabled判定と、GUIが−57.73°を−57.7°へ丸めるのに
要求値からexpected eyeを計算したテスト側の2箇所を修正した。adapterをその判定に合わせて変更したのではない。
再実行`gui_run2`は19/19、例外・runtimeエラーなし。

## 単体・局所回帰

| 実行 | 結果 |
|---|---|
| `python -m pytest tests/test_dragonquest5.py -q` | **159 passed** |
| `python -m pytest tests/test_gui.py -q` | **90 passed**（offscreen/fake backend、実PCSX2接続なし） |
| `python -m pytest tests/test_dragonquest5.py tests/test_core.py tests/test_game_guard.py tests/test_pine_backend.py -q` | **251 passed**（DQ5を含む。上行と単純加算しない） |
| `git diff --check` | 実行、エラーなし |
| 変更済・新規14ファイルのデータ保護検査（実装完了時） | `tools/audit_repo.py`の`audit(Entry)`でworking file内容を検査、問題0。当時のindexは空。コミット前の必須`--staged`検査とは区別する |

DQ5単体はsynthetic sparse memoryと限定R5900 runner。識別・scene/geometry guard・Y-up符号・matrix直交・relative offset・
最新actor加算・FOV同期・全resource preflight・未知命令/破損/占有拒否・sequence・nested transaction・
WORLD/lens/processed RX復元・state再適用・GuardedBackend・runtime restore/abandonを検査した。
本物のGS、VU精度、PS2 scheduler、全scene対応の実証とは区別する。

## 未実装・未検証

- **Orbit視点基準の移動は未実装**。歩行は原作yawを使う。Free Cameraも未対応。
- 全エリア、室内/屋内外切替、戦闘、全イベント、メニュー、入力録画再生、長時間運転、別版は未検証。
- 手持ち物理XInputパッドの全機種・全軸は未測定。共通入力積分はscripted、原作へのRX入力はkeyboard bindingで検証した。
- 実機で別ゲームへ切替える回帰は今回未実施。共通guardのunit回帰を実行し、coreは変更していない。
- GUIツールのWin32黒画像は上記制約。GS screenshotは取得・目視確認した。
- 原作の壁・屋根のcollisionをOrbitへ適用しない。未描画裏面や画面欠けの可能性は残る。
- 実装・検証完了時点では未コミット。追加依頼に従い、対象を明示してステージし、必須のindex監査を通してローカルコミットする。push/PR/mergeは対象外。
