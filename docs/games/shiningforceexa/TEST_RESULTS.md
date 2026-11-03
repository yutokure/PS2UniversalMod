# イクサ — 2026-11-03 検証記録

対象: **SLPM-66646 / 8B383FDF**、PCSX2 **fork-B056de99**、Python3.12。
source: `feature/shiningforceexa-adapter`（基点 `509dda9`）のイクサ追加実装。以下はコミット前の作業ツリーで実行した記録。
[解析・方式・アドレス](CAMERA.md)。この記録は独立review/gateではなく、実装に伴う検証。

## 実施した確認

### オフライン・単体・統合

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider `
  tests/test_sfexa.py tests/test_core.py tests/test_sfneo.py tests/test_suikoden5.py `
  tests/test_game_guard.py tests/test_pine_backend.py tests/test_gui.py
```

**345 passed / 55.19秒**（この実行時点）。イクサ単体は124 case。

- 独自のイクサ数値要約を使用。RAM/ELF本体をテストに含めない。
- Serial+CRC、camera/actor pointer、非finite、mode/source拒否、focus平滑化lag受理。
- yaw180°差、signed pitch、相対height、distance、中心化でeye出力へ書かないこと。
- 垂直角↔水平FOV、aspect、roll保存、実投影読取り、FOV例外preflight。
- 入力2命令の全箇所preflight、未知命令で書込ゼロ、混在・冪等・再適用・復元。
- FOV-only／Orbit共有gate、stateの元値へ復元基準更新、FOV先行の再適用順序。
- native center以外の既存adapter経路、ネオのアドレスへ書かないこと。
- GUIの3登録、未対応Free/offsetsの無効化、設定/preset分離、CRC不一致。
- Neo↔Exaの稼働Orbit切替では旧runtimeをrestoreせず破棄するfake PINE試験。
  **実ディスク間のlive切替はこの作業では未実施**。

### PCSX2: 実adapterとCameraRuntime

[実機ツール](../../../tools/sfexa_live_check.py)を提供baseおよび実歩行後の隣室で実行。
どちらも**9/9 PASS**。同じ値が全場所で有効という意味ではない。

| 条件 | 読戻し・結果 |
|---|---|
| yaw90 / pitch−30 / 距離1200 / 高さ300 | yaw90.000、pitch−29.998、距離1199.9999、focus.y=actor.y+300 |
| FOV40 / 60 / 90 | 実VPから39.9988 / 59.9994 / 89.9988° |
| FOV解除、Orbit継続 | 元のFOVへ戻りgateはOrbitが保持 |
| shared runtime 右入力(0.7,0.4) 約0.8秒 | 約81°水平回転、pitch上昇、runtime error空 |
| runtime FOV70 | 実投影70.0005° |
| Original／停止後 | gate1、入力2命令stock、投影stockへ復帰 |
| 隣室のnative camera | FOV31.0311°、距離2000、高さ100（baseのFOV54.9396°／1000／250と異なる） |

FOV成功はGUI設定値だけで判定していない。実VPと画像で画角が広がり、HUD/mapが拡縮しないことを確認。

### PCSX2: 実GUI・実pad経路

[GUI実機ツール](../../../tools/sfexa_gui_check.py)をoffscreen Qtウィンドウ＋実PINEで使用。
実設定を保護するためAPPDATAを一時ディレクトリにし、入力はscripted＋PCSX2 keyboard pad。
**修正後11/11 PASS**。

- GUI enable → native center、Orbit、距離1200／相対高さ50、表示Pitch30°が内部−30°。
- 右raw RX=255を残しながらprocessed RX/RY=127。左stickとbutton loadは未変更。
- 実左stick入力でキャラクターが324〜360程度移動。
- GUI FOV80 → 実投影 **80.0016°**。
- GUI真上端89.5° → 実内部pitch **−89.5001°**、描画を維持。
- yaw180→90°で方位N:上→右、W:左→上、マップ地形も90°回転。
  マップ用追加パッチなし。map関数自体の同定までは行っていない。
- Orbit+FOV中にMCPからstock `base` をload → 1.8秒後yaw90／pitch−29.998／FOV80.0016、
  pad2命令の再適用。Original後はstock入力・FOV・gateへ戻る。

**この試験で見つけて直した問題**: 最初のreloadではFOV処理が先にgateを閉じ、
パラメーター再publishが省略されyaw/pitchだけstockへ戻った。共有gateでstock resetを検知し、
FOV-firstでもOrbitの再publishを要求するよう修正。同一条件を再実行しPASS。
単体テストでもFOV-onlyと両方の処理順序を再現した。

### 原作右入力・4方向の遮断と復元

keyboard padを右・上・左・下の各方向へ送り、stock → mask → stock の順に12サンプル。
stockの `held & 00F00000` は `00200000 / 00400000 / 00100000 / 00800000`、
mask中は全方向0、processed unsignedは `7F/7F`、signedは0。
復元後は元の4方向bitと軸値へ戻った。左軸／button命令は不変。
quickbarの専用選択indexは未特定で、提供baseで撮った画像だけではカーソルの移動を明瞭に区別できなかった。
したがって**原作へ渡る右入力と派生方向bitの遮断・復元を実証**したのであり、
全クイックバー状態／全メニューの挙動まで実証したとは扱わない。
ローカル証拠は `quickbar/samples.json` と12枚の画像。

### 短い歩行・実エリア遷移

baseから左stick(0.7,0)を7秒、yawを±8°連続変化させて160サンプル採取。

- 開始anchor `(-908.98,-61.11,-57.36)` → 終了 `(2612.66,171.91,-50.27)`。
- 約2.8〜6.5秒はactorが0になり83サンプルでscene guardが拒否。画面遷移と整合する。
- 再開後77個の有効サンプルを通算し、同じcamera allocationとactor pointer経路で再受理。
  有効区間の最大採取間隔0.047秒。ロード中を「カメラfreeze不具合」とは数えない。
- 隣室でadapter9項目を再実行しPASS。長距離／長時間試験ではない。
- 全yawでの左stick歩行方向の角度測定や、歩行のカメラ基準化の追加実装は行っていない。

## 再実行の注意

PINEは1クライアントのみ。GUIとチェックツールを同時接続しない。解析MCP/GDBは通常GUIには不要。

```powershell
python tools/sfexa_live_check.py --out <lab>/test_evidence/exa/live.json
python tools/sfexa_gui_check.py --out <lab>/test_evidence/exa/gui
```

stock state再適用を試す場合はGUIツールへ未使用の `--reload-handshake <dir>` を指定。
`ready.json` が生成された後、別のMCPから**同版stock state**をloadしVMをresume、そのdirに
`continue.txt` を作る。古いhandshake dirを再利用しない。ツールは90秒でtimeoutしfinallyで通常復元する。
この試験は現在のゲーム状態をloadするので、先に明示パスへbackupを保存する。

## 保護・ローカル証拠

開始時のプレイ状態は `<lab>/test_evidence/sfexa_20261103/pre_analysis.p2s` に保存。
提供4ステートとISOは読取りのみ。4ステートのSHA256は展開時manifestと作業後のhash確認が一致。
作業終了時は開始時backupをloadし、RX/RYのstock命令とgate1を読み戻して確認した。VMは一時停止状態。
追跡ファイル148個と新規ソース／文書9個のデータ監査、文書リンク確認、`git diff --check`も成功。
実装検証時点ではstageしなかった。後続のユーザー指示によりcommit／pushへ進む際は、明示パスをstageし、
indexの対象一覧・統計・`tools/audit_repo.py --staged`を確認する。実施結果とcommit IDはGit操作の報告に記載する。
抽出ELFのSHA256: `BC5EE157FA4E61E34895652EC623754EC2BF5787B28B30AC8E060F2257882548`。

画像、状態、RAM、Ghidra project／逆コンパイルはGit外の `<lab>/work/sf_exa_analysis/` と
`<lab>/test_evidence/sfexa_20261103/` のみ。原本ステートを実験結果で上書きしていない。

- `gui_fixed/gui_checks.json`、`gui_fixed/yaw180.png`、`yaw90.png`、`fov80.png`、`overhead.png`
- `live_adapter.json`、`transition_adapter.json`、`moving.json`
- 失敗履歴 `gui_live/gui_checks.json` も修正前の証拠として保持。

解析ツールの既知問題: native analog `input_set` はこのforkでusage errorのためkeyboardを使用。
conditional qPcsx2 breakpoint試行でPCSX2が終了したが、保護済stateと既存構成で再起動した。
以後は通常GDB breakpoint/watchpointのみ。これはadapter運用には不要。
Qtのfont-directory警告が出るが検証は完了。GUIの日本語表示をこの警告だけで成功判定したわけではない。

## 制限・未実施

- Free Camera、カメラ位置／注視点XYZ offsetは未対応（GUI無効）。ネオ相当の範囲を対象とした。
- 全エリア、イベント、戦闘、全メニュー、パーティ切替、長時間、録画／再生pad経路は未確認。
- scene guardで拒否しても、Orbit中のpad mask・gateは残る場合がある。
  特殊sceneで原作入力が必要ならOriginalを選ぶ。全演出の安全な自動退避は未実装。
- FOV-onlyにもgate停止の副作用がある。場所依存の原作カメラを保ったFOV-onlyではない。
- stock state reloadの再適用は実証済み。別process作成MOD stateや異なるallocationへの自動追従は保証しない。
- 遷移先でゲーム自身の値が変わった場合は未知の値を強制復元しない。常に元のyawへ完全一致する保証はしない。
- ネオ／FFX-2／幻想水滸伝Vのlive再実行は未実施。共通center境界の既存経路は単体・GUI回帰で確認。
- 実装検証後にcommit／pushの追加指示を受領。PR作成／mergeは依頼範囲外。Git操作結果は別途報告する。
