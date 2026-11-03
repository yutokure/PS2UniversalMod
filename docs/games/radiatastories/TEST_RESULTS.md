# Radiata Stories — 実行した検証と制限

対象 **SLPM-65800 / AC73005E**、日付 **2026-11-03**。
検証時の作業ブランチ `feature/radiatastories-adapter`、基点 `5c176c5` + 本機能追加の変更。
対応するコミット・PRは Git 履歴を参照。
PCSX2 `fork-B056de99`（既存プロセス）、PINE、既存 PySide6 GUI を使用。
以下は実装側の検証記録であり、独立レビュー結果ではない。

実装方式・アドレス・安全根拠は [CAMERA.md](<CAMERA.md>)。
実行ツールは [radiata_live_check.py](<../../../tools/radiata_live_check.py>)。

## 1. 自動テスト

最終実行:

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest tests/test_radiata.py tests/test_gui.py tests/test_core.py tests/test_game_guard.py tests/test_pine_backend.py tests/test_druaga.py -q
git diff --check
```

**451 passed / 58.57秒**、`git diff --check` は出力なしで成功。

- Radiata の Serial + CRC、一意の player alias→record→node 所有、scene flag0/99、無効な geometry/lens。
- 全3 hook/delay slot と cave/control block の preflight、未知語への無書込み、接続/解除順。
- local R5900 subset interpreter で view→tan→frustum call 境界を模擬。
  最新 guest player 位置の加算、独立 offsets、native world の一時代入・完全復元、別camera/scene拒否。
- host 二重bankに sequence lock、guest専用snapshotを使用。view と tan の間に host が2回publishして
  元bankを再利用しても FOV が変わらない。コピー途中のsequence変更・奇数・不正magicは拒否。
- Orbit/FOV独立所有、stock state 再適用、pending中の解除拒否→cleanup後の回復、ゲーム変更ガード、abandon。
- GUI の3辞書登録、日英表示、範囲/符号、Free無効理由、6offset、Original起動、ゲーム別設定/プリセット分離、
  synthetic field で本物の adapter を使う enable/restore。
- 直接影響する共通 runtime / PINE / guard と Druaga の既存テストを同時実行。

interpreter は PS2 の実タイミング・描画・frustumの数学を再現するものではない。
他タイトルの実機再起動回帰・全repository suiteは今回実行していない。

## 2. 実機 GUI / runtime

実機ツールは一時 APPDATA、GUI実インスタンス、単一 GuardedBackend/PINE を使用。
右軸テストは GUI の `scripted` source→通常入力pump→runtime経路。物理 XInput pad の操作そのものではない。
左歩行だけは既存 keyboard backend の仮想 PS2 左軸を使用した。

```powershell
python tools/radiata_live_check.py --out <lab>/test_evidence/radiata/live_v1 --move --reload-handshake <lab>/work/radiata/reload_v1
python tools/radiata_live_check.py --out <lab>/test_evidence/radiata/live_final --move
```

`live_v1` **18/18**、snapshot hardening後の `live_final` **17/17** 成功。
さらに最終sourceで元のユーザーsceneから `live_user_final` **17/17** 成功。
こちらは歩行なし、別比較stateからstock baseへの再読込・再適用を含む。
JSONと画像はすべてリポジトリ外の `<lab>/test_evidence/radiata/`。

| 項目 | 実測・結果 |
|---|---|
| 版・初期化 | GUIが日本版/CRCを認識、guard有効、Originalで開始、Free無効 |
| Orbit | yaw/pitch/distance = 140/20/1500、−140/35/1800、180/75/1000、175/15/1500 をreadback。角誤差約0.00002°以下、距離誤差0.001未満 |
| 主役中心・画面 | 建物側面からの視点、上方視点、画角変化を実画面で確認。行列値だけで成功にしていない |
| 独立 offsets | eye=(30,−20,15)、target=(−25,10,20)、look height=−80。guest出力が期待eye/targetと0.01未満で一致 |
| FOV | 25→24.999999°、40→40.000000°、65→64.999999°。最終focalからreadbackし実画面の視野拡大も確認 |
| FOV無効化 | Orbitを残したまま原作約28.84°へ復帰 |
| 右軸入力経路 | scripted (0.7,0.2) を約0.3秒入力、yaw約170→−159°。離して保持、出力とruntime設定一致 |
| 左軸歩行 | 約0.28秒。player (−1854.508,1026.096,−4221.372)→(−1727.751,1024.165,−4205.634)。eye−playerの追従誤差0.000123未満 |
| state再適用 | stockの別比較stateをMCPでload/resume。2秒待機後 yaw150/pitch25/d1500/FOV40が再適用され、runtime error空 |
| Original/終了 | 3site stock復元、pending=0、native camera/lensへ復帰、入力release |

### reload handshake

ツールが空directoryへ `ready.json` を書いたら、既存 MCP で **stockの比較state** をloadしresumeする。
その後同directoryへ `continue.txt` を作る。ツールは2秒待機して確認する。
ツール自身はstateのload/saveをせず、既存stateを上書きしない。

### ステータスメニュー

既存 keyboard backendで triangleを押しメニュー画面を目視。host `read_scene.valid=False`、理由は
`Radiata player processing is suspended`。scene flag0=1、flag99=0。

Orbit/FOV有効のままmenuへ入った別確認では、guest heartbeat 2552→2552（約0.3秒）で増えずpending=0。
menu中の描画cameraのnative角は原作が約40°へ切替えており、これをMODのFOV継続と誤認しない。
triangleで戻るとflag0=0、field valid、原作約28.84°へ復帰。全menu/eventの保証ではない。

## 3. データ保護・復元

- 開始時のVMをリポジトリ外の明示ファイルへ保護。提供base/wait/moved stateは読取りのみ。
- ISOは読取り専用でboot ELFを抽出し、static解析後size/mtime不変を確認。
- ソース内には独自assembler・アドレス/語数・数値要約のみ。ELF/RAM/画像/ステート/Ghidra/decompiler出力はGit外。
- 起動中ゲームを終了・ディスク切替・メモリーカード編集せずに解析。最後に開始時VMへ戻しOriginalで再開する。
- 変更・新規14ファイルを既存auditの同じ内容検査で検証し問題なし、ゲーム別文書リンク切れ0。
  これは作業ツリー（未追跡ファイルを含む）の検査であり、未実施のstaged監査を実施済としない。
- 終了時、開始時VMをloadしadapterの全3siteと解析用一時probe2siteがstock、watchpointなしをreadback確認。
- 初期の実装検証終了時点ではコミット・push・PR作成・mergeを行っていない。
  後続のユーザー依頼により Git での公開・統合を進める。最終状態は Git/PR 履歴を正本とする。

## 4. 既知の制約・未実施

- 日本版このCRCのみ。別版をSerialだけで受理しない。
- Free Camera未対応。OriginalでFOV-onlyは現行共通runtimeの対象外。
- 通常フィールドの提供比較stateとステータスメニュー中心。戦闘・cutscene・全map遷移・全menu・長時間は未検証。
- 原作camera collisionをOrbitに適用しない。壁内部・裏面・描画欠けが見える可能性。
- viewとfrustumは一致させるが、native +570派生値の全consumer/反射/特殊effectまでは未解析。
- 原作の歩行入力処理は変更しない。短い歩行追従は実測、全yawのカメラ相対方向は未測定。
- 低位caveは3state zero、ELF/BSS/通常heap/stack外。OSの将来用途・全overlayで未使用という保証ではない。
- VMを描画transaction内部でpauseすると、cleanupを失わないため解除はtimeout拒否する。resume後Originalへ戻す。
- 物理右スティックのXInputデバイス/driverは今回変更しておらず、当該ハードでの入力確認は未実施。
- Qtのfont directory警告が出たが、GUI操作・描画・終了は成功した。環境警告をcamera失敗と扱わない。
