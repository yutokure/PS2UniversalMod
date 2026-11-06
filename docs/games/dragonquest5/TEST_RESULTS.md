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

## 現在の未実装・未検証

以下の初期試験は`c5fe59a`ベースのv1記録。後の移動対応・lifecycle変更の確認は追記を優先する。

- **Free Cameraは未対応**。通常fieldのOrbit視点基準移動は後述のv2で対応。
- **特殊固定／イベントcameraの360°解除は未対応**。ユーザーの追加回答「別途対応とします。今回はやらなくていいです」により別件・今回対象外。将来の個別確認には場所名／stateが必要。
- 全エリア、戦闘、全イベント、メニュー、入力録画再生、長時間運転、別版は未検証。
  屋内外の移動は後述の庭→建物内のみ確認で、全切替経路の保証ではない。
- 手持ち物理XInputパッドの全機種・全軸は未測定。共通入力積分はscripted、原作へのRX入力はkeyboard bindingで検証した。
- 実機で別ゲームへ切替える回帰は今回未実施。共通guardのunit回帰を実行し、coreは変更していない。
- GUIツールのWin32黒画像は上記制約。GS screenshotは取得・目視確認した。
- 原作の壁・屋根のcollisionをOrbitへ適用しない。未描画裏面や画面欠けの可能性は残る。
- v1は後に`411277f`としてローカルコミットされた。v2の機能検証完了時点では未コミットだった。
  その後2026-11-06にユーザーからcommit/push/PR/mergeの依頼を受けた。Git操作の確定結果はコミット履歴・PRを参照する。

## 追記 — Orbit基準移動と安全な適用／解除（2026-11-05〜06）

対象HEAD **`411277f`**からの作業差分、同版／同PCSX2 fork。初期試験と結果を混同しない。

### 移動とyaw

- 原作yawがforward向き、GUI yawがeye-around-target向きで180°違うことを4stateから確認。
  独立eye offsetを含む実視線の`atan2(target-eye)`を、原作のvector／actor-facing consumerへ渡す方式を実装。
- 庭`sbout`でyaw **0/90/180/−90°**それぞれ前後0.2秒の実左入力を送信。
  実変位方向dotは最小**0.999999999975**、native速度と向きのdotは**0.999999999999**以上、
  移動約**11〜13.2**、guest相対target誤差**0**。host発行停止中もguest heartbeatが進み、追従した。
- 通常入力時のoriginal camera eye/target/global yaw/lens保持、実processed RX受信と原作回転の遮断・解除後再開を確認。
- 庭から建物内（map ID `sbf1a`）へ通常歩行で入り、室内Orbit90°で上入力→world −X、
  velocity `[-2.1999998,0,約0]`、向き約π/2を確認。原作global yawは不変。
  室内では屋根・床が視線を隠す位置があり、camera collisionを提供する確認ではない。

### 回転制限の確認範囲

- `0x57D630`のnative map veto／yaw boundsを解析。ISO内291個の有効FLSC headerはraw limitsが全て`0,0`。
  これらのlimitsが実際の報告場所の原因という証拠はない。
- 保護した庭stateへ**条件注入**して、veto=1/bounds=0でもOrbit **0/90/180/270°**、
  finite bounds±15°でもyaw45°へ回せることをPCSX2 readbackで確認。
  native movement gate=0でもyaw90°の上入力でworld−Xへ進んだ。
- eye offset `(35,7,−22)`時は実yaw約**98.06453°**となり、native velocity `[-2.1782434,0,0.3086343]`、
  actor heading約**1.7115493 rad**がその視線と一致した。注入値は元へ戻し、4hook stockを確認。
- **これは実在する制限場所の解消試験ではない**。固定mode1/2/3と別camera familyは同じevent setterを使うため、
  guardを一律に削除しない。native permission=0／suspend状態も拒否する。特殊場所の個別対応はユーザー指示で今回は実施しない。

### PCSX2異常終了とlifecycle対策

- 最初のstrict runは方向8条件とstock state再適用が通ったが、その後の解除時にPCSX2自体が異常終了。
  ログは`[EE] Impossible block clearing failure`、Windows exception `0xC0000005`。
- 原作stateから再起動した通常のGUI試験は**26/26**通過。
- 解除をguest EE threadへ移す修正後、同じreload→再適用→Originalが**27/27**通過。
  しかし別stateでの追加試験がreload直後に同エラーで停止し、**解除だけでは再適用側の競合を解消しない**ことが分かった。
- [公式issue #14589](https://github.com/PCSX2/pcsx2/issues/14589)はPINE threadとCPU threadによるprotected-page書込み競合で同診断を報告。
  ログとsource経路は一致するが、本Windows crashの完全stackは未取得。
- 最終方式はrender bootstrap1word以外の3hookをguest EE threadで適用し、4hook解除もguestで行う。
  全hook/delayを最初のguest書込み前に再検査し、ACK＋全hook読戻し後にMODを有効化する。
  初回bootstrapのPINE code書込みは残り、エミュレータ全競合の解決保証ではない。
- 最終方式のGUI試験1（`yawfix_guest_both1`）は**27/27**、試験2（`yawfix_guest_both2`、歩行測定なし）は**19/19**。
  前に失敗した2つのstock state（wait／camera_move）を別々に再読込みし、cached要求の再適用、Originalで全4hook／flags復元、
  原作RX回転復帰とfinally cleanupを確認。ログに同再コンパイラ診断なし。全試行／長時間の安定保証ではない。

### 最終単体・局所回帰

- DQ5の3suiteは**736 passed**。最小R5900 runnerによるnative yaw入力、8方位×8入力、map movement gate0/1、
  native veto/bounds時の全周、同一yaw latch、128bit register、sequence、unknown資源拒否、
  guest適用／解除ACK、pause・途中transaction・nested・conflict・data-only host解除を検査。
- 共通math/runtime、GuardedBackend、PINE、GUIを含む直接integration回帰は**918 passed**。
  実行: `python -m pytest tests/test_dragonquest5.py tests/test_dragonquest5_movement.py tests/test_dragonquest5_lifecycle.py tests/test_core.py tests/test_game_guard.py tests/test_pine_backend.py tests/test_gui.py -q`。
- 実PS2 scheduler／PCSX2 JITのrace保証と、synthetic memory/命令contractを混同しない。
- 機能検証完了時に変更11ファイルを`audit(Entry)`でworking-file監査し、問題0。当時のindexは空・未ステージ。
  これは後続のcommit/push依頼で実施する必須`--staged`検査とは別の記録。
- 終了時に原本4stateの全ファイルSHA256が初期manifestと一致、元DQ5保存本体が保護backupと一致。
  元カード設定と開始時stock VMへ戻した。
