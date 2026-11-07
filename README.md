# PS2 Universal Camera Controller

PS2 ゲームの通常フィールドで、**右スティックによる自由回転カメラ**と
**外部 Windows GUI からのリアルタイム制御**を実現する MOD コントローラーです。
PCSX2 の PINE（メモリ読み書き IPC）で動き、**DeepSeek Harness・MCP サーバ・GDB は不要**です。
GUI 単体で動きます（それらは解析・自動テストのときだけ使います）。

```
┌──────────────────────────┐   PINE (TCP 127.0.0.1:28011)   ┌────────┐
│ GUI (PySide6)            │ ─────────────────────────────► │ PCSX2  │ ► ゲーム
│  └ CameraRuntime (thread)│    メモリ読み書き + コードパッチ  └────────┘
│     └ ゲーム別アダプター  │
└──────────────────────────┘
```

設計方針として、ゲーム固有の処理・アドレスは原則 `adapters/<game>/` へ分離します。
ただし、現在の共通エンジン（[`core/camera_runtime/engine.py`](core/camera_runtime/engine.py)）には、
FFX-2（FF10-2）由来の FOV 同期確認用フォールバック（`0x340B00` の読み取り）が残っています。
新しいゲームを追加するときは、共通基盤（`core/`・GUI）へ新たなゲーム固有アドレスを持ち込みません。

開発・解析を AI に依頼するときの判断基準は [`AGENTS.md`](AGENTS.md)。親ラボへの配置方法は
[`docs/README.md`](docs/README.md#agentsmd-の配置) を参照してください。

## 1. 対応ゲーム

| ゲーム | アダプター | Serial / CRC | できること | 詳細 |
|---|---|---|---|---|
| FINAL FANTASY X-2 | `adapters/ffx2` | `SLPS-25250` / `8A6D7F14` | Orbit、距離、FOV、カメラ位置・注視点オフセット、Free Camera | [`docs/games/ffx2/`](docs/games/ffx2/) |
| シャイニング・フォース ネオ | `adapters/shiningforceneo` | `SLPM-65908` / `64F241D2` | Orbit、距離、FOV、注視点の高さ、右スティック遮断 | [`docs/games/shiningforceneo/`](docs/games/shiningforceneo/CAMERA_ANALYSIS.md) |
| シャイニング・フォース イクサ | `adapters/shiningforceexa` | `SLPM-66646` / `8B383FDF` | Orbit、距離、FOV、注視点の高さ、右スティック遮断、原作マップ回転連動 | [解析・確認範囲](docs/games/shiningforceexa/CAMERA.md) |
| 幻想水滸伝V | `adapters/suikoden5` | `SLPM-66286` / `7380A572` | Orbit、距離、FOV、カメラ位置・注視点オフセット、右スティックのズーム遮断、R1 ズーム連動 | [`docs/games/suikoden5/`](docs/games/suikoden5/CAMERA.md) |
| ザ・ナイトメア・オブ・ドルアーガ | `adapters/nightmaredruaga` | `SLPS-25377` / `B476ED7A` | 城内／ダンジョンの Orbit、カメラ基準移動、距離、FOV、独立した位置・注視点6軸オフセット、右入力競合遮断 | [解析・確認範囲](docs/games/nightmaredruaga/CAMERA.md) |
| ラジアータ ストーリーズ | `adapters/radiatastories` | `SLPM-65800` / `AC73005E` | Orbit、カメラ基準移動、距離、FOV、独立した位置・注視点6軸オフセット（原作右スティックの遮断不要） | [解析・確認範囲](docs/games/radiatastories/CAMERA.md) |
| ロマンシング サガ -ミンストレルソング- | `adapters/minstrelsong` | `SLPM-65920` / `2B9AF3C5` | Orbit、コンパス方位盤・キャラの針の連動、カメラ基準移動、距離、FOV、独立した位置・注視点6軸オフセット（右入力遮断なし） | [解析・確認範囲](docs/games/minstrelsong/CAMERA.md) |
| ドラゴンクエストV 天空の花嫁 | `adapters/dragonquest5` | `SLPM-65555` / `B64E9939` | 右スティックyaw＋pitchのOrbit、カメラ基準移動、距離、FOV、独立した位置・注視点6軸オフセット、原作右回転との競合抑止（特殊cameraの回転解除は未対応） | [解析・確認範囲](docs/games/dragonquest5/CAMERA.md) |
| 新牧場物語 ピュア イノセントライフ | `adapters/innocentlife` | `SLPS-25763` / `9AC21F92` | 右スティックOrbit、カメラ基準移動・向き、距離、FOV、独立した位置・注視点6軸オフセット、ゲーム内時計の停止（Free非対応） | [解析・確認範囲](docs/games/innocentlife/CAMERA.md) |
| グランディアII | [Grandia II adapter](<adapters/grandia2/adapter.py>) | `SLPM-65081` / `B6AB7BC2` | 屋外／屋内の右スティックOrbit、カメラ基準移動・向き、距離、FOV20〜110°、独立した位置・注視点6軸オフセット（Free・時計停止非対応、実機の確認範囲・制限は詳細参照） | [解析・確認範囲](<docs/games/grandia2/CAMERA.md>) |
| テイルズ オブ シンフォニア | [Symphonia adapter](<adapters/talesofsymphonia/adapter.py>) | `SLPS-25400` / `830B6FB1` | 町等の通常マップ／徒歩ワールドフィールドのOrbit、移動方向、フィールドコンパス・地図視線、FOV20〜110°、距離・独立6軸オフセット（Free・時計停止・特殊車両非対応） | [解析・確認範囲](<docs/games/talesofsymphonia/CAMERA.md>) |
| マグナカルタ | [Magna Carta adapter](<adapters/magnacarta/adapter.py>) | `SLPS-25401` / `EB925207` | Orbit、FOV20〜110°、距離・独立6軸オフセット、カメラ基準移動・原作ミニマップ矢印追従、走行時の広域表示、接触エンカウント無効＋オレンジ丸枠非表示（各切替可） | [解析・確認範囲](<docs/games/magnacarta/CAMERA.md>) |

Serial と CRC の**両方**が一致しないゲームには何も書き込みません（日本版のみ対応）。
「Free Camera」は FFX-2 だけで使えます。他のゲームでは GUI のラジオボタンが無効になります。

## 2. 動作環境

| 項目 | 要件 |
|---|---|
| OS | Windows 10/11 |
| エミュレータ | PCSX2 2.7.x。`PCSX2.ini` の `[EmuCore]` に `EnablePINE = true`・`PINESlot = 28011` |
| Python | 3.12。`pip install -r requirements.txt`（PySide6、numpy、zstandard） |
| 実機検証ツール（`tools/`）を使う場合 | 上に加えて pywin32、psutil、Pillow |

> **PINE クライアントは同時に 1 つだけ**です。GUI とスクリプトを同時に動かすと、どちらかが
> タイムアウトします。

## 3. 使い方

### 3.1 起動

1. PCSX2 で対応ゲームを起動し、フィールドまで進めます。
   - FFX-2 のカメラパッチは runtime が管理します。外部 `.pnach` や `EnableCheats` は不要です。
     Orbit / Free Camera で自動適用し、Original では外します。「ゲームパッチ」欄はモードに応じた表示になります。
     旧版の外部カメラパッチが残っている場合は、競合しないよう §5.1 の手順で無効化してください。
2. `PS2UniversalCamera.bat` をダブルクリック（または `python run_gui.py`）。
   PySide6 の入った Python を `.venv` → `..\python\venv` → 実行中の Python → PATH の順に探します。
   依存関係を入れ直すには:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. 起動すると PINE に接続し、ゲームを識別して「接続済み」になります。未対応のゲームでは書き込みません。

### 3.2 操作

1. **カメラモード → オービット**（または「カメラ MOD を有効化」）
2. **右スティック**: 左右で水平回転、上下で仰角。離すとその角度を保持します（矢印キーでも同じ操作。
   XInput とキーボードは併用でき、先に入力のあった方が使われます）
3. 左スティックで歩く（ドルアーガのダンジョンは方向キー）。ラジアータ・ドルアーガ・ミンストレルソング・DQⅤ・イノセントライフ・グランディアIIも Orbit のカメラ基準で移動します（ダンジョンは最寄り8方向）。ゲーム別の確認範囲は §5 を参照
4. 「オリジナル」はカメラ・移動入力だけを原作へ戻し、独立した時計停止・ゲーム固有機能の選択は保持します。
   「MOD を無効化して元のカメラに戻す」は時計停止・ゲーム固有機能も解除します。
5. イノセントライフでは「ゲーム内時間を停止」で通常の時計進行を止められます。移動・アニメーションは続き、PCSX2 の一時停止ではありません。
   起動・再接続時は必ずオフで、プリセットにも保存しません。睡眠・イベント等の明示的な時刻変更は止めません。
6. マグナカルタでは「走行中も広い範囲を表示」と「エンカウントを無効化」を個別に選べます。
   前者は歩行相当の敵の視認範囲、後者は通常接触エンカウントとキャラ周囲のオレンジ丸枠を無効化します。
   カメラモードと独立し、起動・再接続時はオフ、設定・プリセットへ保存しません。強制戦闘は対象外です。

### 3.3 GUI 項目

画面は上から「接続」「通知バー」「カメラモード / 操作」「カメラ回転 / カメラ位置」「カメラレンズ / ゲーム標準ズーム」「ゲーム内時間」「ゲーム固有機能」「デバッグ表示」です。
窓が小さいときはスクロールします（スライダー上のマウスホイールは、フォーカスがないと値を変えません）。

| セクション | 項目 |
|---|---|
| 接続 | PCSX2、ゲーム、シリアル / CRC、アダプタ、実行状態、ゲームパッチ、表示言語（日本語 / English、再起動不要）、再接続。「詳細を表示」でパッチを手動で読み込む／外すボタン |
| 通知バー | 今いちばん大事な 1 件を平易な文で表示（PCSX2 に接続できない、未対応の版、フィールドカメラが止まっている、パッチ箇所が想定外、など）。重大度で色分け |
| カメラモード | オリジナル / オービット / フリーカメラ（FFX-2 のみ）、有効化時にキャラクターを中央へ |
| 操作 | **カメラ MOD を有効化**、**MOD を無効化して元のカメラに戻す**、キャラクターを中央に、ゲームの視点に合わせ直す、プリセット（読込 / 保存） |
| ゲーム内時間 | 対応ゲームのみ「ゲーム内時間を停止」、現在の時刻・パッチ読戻し状態。カメラモードから独立、起動時はオフ。未対応ゲームは理由を表示して無効化 |
| ゲーム固有機能 | マグナカルタの走行時広域表示・エンカウント無効（ON時オレンジ丸枠非表示）、各読戻し状態。独立したセッション専用切替。未対応ゲームは理由付き無効 |
| カメラ回転 | Yaw、Pitch、回転速度、右スティック感度、デッドゾーン、左右反転、上下反転、入力ソース（auto / xinput / keyboard / scripted） |
| カメラ位置 | 距離、注視点の高さ。「オフセット（詳細）」を開くとカメラ X/Y/Z・注視点 X/Y/Z（0 以外があると見出しに「設定あり」と出ます） |
| カメラレンズ（FOV） | FOV（通常20〜110°。グランディアIIも20〜110°）、上書きの適用、現在値、ゲーム値に戻す |
| ゲーム標準ズーム（対応ゲームのみ） | 現在の段階、段階ボタン、R1 でオービット距離を連動（幻想水滸伝V。連動の設定はゲームごとに保存） |
| デバッグ表示（既定で折りたたみ） | カメラ座標、プレイヤー座標、更新頻度、最終更新 |

挙動のルール:

* **起動時は必ず「オリジナル」**です。保存された設定の値は読み込みますが、MOD は自分で有効にするまで動きません。
* プリセットは**値だけ**を変え、カメラモードや表示言語は変えません。同名の保存は確認してから上書きします。
* 接続がない・未対応の版・接続が切れたときは、カメラ関連の操作がすべて無効になり、通知バーに理由が出ます。
  PCSX2 が戻れば自動で操作できるようになります。
* ゲームの実装が使えない項目は個別に無効になります（例: シャイニング・フォース ネオのオフセット、FFX-2 以外のフリーカメラ、他ゲームの時計停止）。
* 距離・注視点の高さ・オフセット・Pitch・FOV の範囲は**ゲームごと**です（アダプターが決めます）。
  Pitch の表示は対応ゲームとも**正でカメラが上**です。注視点の高さは FFX-2・幻想水滸伝V では正で下、
  シャイニング・フォース ネオ／イクサ・ドルアーガ・DQⅤ・グランディアIIでは正で上、ラジアータ・ミンストレルソング・イノセントライフでは負が上となり、スライダーの下にも説明が出ます。
* 矢印キーは、PCSX2 かこの画面が前面にあるときだけカメラを回します（他のアプリで押しても動きません）。
* 同時に起動できるのは 1 つだけです（PCSX2 の PINE は 1 クライアントのため、2 つ目は起動時に断ります）。
* 設定にない操作の失敗（例: 途中で PCSX2 が終了）は例外にならず通知バーに出て、`%APPDATA%\PS2UniversalCamera\gui.log` に記録されます。

スライダーと数値入力は同期しており、「適用」ボタンはありません。変更は次フレーム（約 16 ms 以内）に反映されます。

PCSX2 を閉じる・終了させても GUI は固まりません（「未接続」を表示し、PCSX2 が戻れば自動で復帰します）。
監査の記録: [`docs/gui/GUI_AUDIT_2026-11-02.md`](docs/gui/GUI_AUDIT_2026-11-02.md)。

---

## 4. 設定とプリセット

```
%APPDATA%\PS2UniversalCamera\settings.json     ゲーム ID ごとの設定（ゲーム間で混ざりません）
%APPDATA%\PS2UniversalCamera\presets\*.json    名前付きプリセット
presets\*.json                                  同梱プリセット（orbit-default、close-up）。読み取り専用
```

プリセットは**ゲーム ID ごと**に絞って表示されます。同梱の 2 つは FFX-2 用です。

## 5. ゲーム別の要点

### 5.1 FFX-2
- ゲームは視点と注視点を毎フレーム書き戻します。視点には「ゲーム自身の加算フィールド」のオフセットと
  ゲーム本来のカメラルーチンへのフックを使い、注視点は **メインカメラだけ**未使用スロットへ向けます。
  共通の視線計算関数は stock のままにし、ミニマップ・補助カメラの注視点を変更しません。
- パッチは runtime が **Orbit / Free Camera で適用、Original / 通常終了で stock に復元**します。
  外部 `.pnach`・`EnableCheats`・毎回の手動 `disable` は不要です。ステート読込後は約 1 秒で再適用し、
  未知の命令や使用中のコードケーブを検出した場合は命令を書き換える前に拒否します。MOD の強制終了では復元できません。
- **旧版の外部パッチがある場合**: [`stock_hook.py`](<tools/stock_hook.py>) の `status` / `disable` は
  PCSX2 側の旧 stock-hook ブロックを確認・除去するためのものです（`enable` は廃止）。
  旧 look-at パッチ `001B07FC / DA250030` はこのツールの検出・除去対象外なので、別途無効化してください。
  外部定義を無効化したらゲームを再起動するのが確実です。PCSX2 のパッチ再読込で運用を続ける場合は、
  外部からの再適用を止めたうえで GUI を Original にして既知の命令を復元し、表示を確認してください。
  外部パッチの再適用が残ると runtime の復元と競合します。
- 歩行方向はフック方式でオービットに追従します。以前の方向測定は歩き始め 0.3 秒で、
  広い場所での長い歩行は未確認です。
- Orbit の中心はキャラクター基準点 + 固定 Y `+5` + 注視点の高さです。既定 `-6` ではキャラクター相対 Y `-1`。
  演出カメラの追従点を使わないため、通常フィールドの既存設定値を保ちつつ、実際の高低差に追従します。
  ルカの演出切替を 20 秒往復し、高さ維持とミニマップの位置安定を確認しました。
  ただし全ルカマップ・イベント・戦闘・長時間を網羅した確認ではありません。
- 演出カメラのあるエリアの FOV には場所・描画経路による制限があります。
  `other_area_base` の従来の制限と後の投影元変更による確認範囲は、下記技術メモを参照してください。
- 狭い通路で 180° 回すとカメラが壁の内側に入ることがあります（ゲームの衝突判定を経由しないため）。
- 実装メモ・測定値: [FFX-2 技術メモ](<docs/games/ffx2/ADAPTER_NOTES.md>)

### 5.2 シャイニング・フォース ネオ
- カメラの角度（yaw/pitch）・距離・注視点の高さはゲームのフィールドに書き、場所依存のスクリプトカメラ（町の門など）は
  平滑化ゲートの 1 バイトで止めます。FOV と右スティック遮断はコードケーブです。
- 階段の高さ追従には原作の平滑化があるため、注視点とキャラクターの高さの瞬間的な差では書込みを止めません。
  フィールド追従モードとパーティ注視モードを確認し、固定・遷移・スクリプト用モードでは書込みを控えます。
- Pitch の表示・右スティックの可動域は **−25〜+89.5°**。反転なしではスティック上でカメラが上がり、
  ほぼ真上（90°の0.5°手前）まで動きます。真下側への回り込みは −25°で止めます。
  旧設定・プリセットの内部角度の符号は維持し、範囲外だけ補正します。「上下を反転」の設定はそのまま残ります。
- カメラ位置・注視点の X/Z オフセットは効きません（注視点の高さのみ）。
- 既知: オービットを戻した直後のカメラ向きは、ゲームが決めるため元の向きと一致しません（既存の挙動）。
- 解析記録: [`docs/games/shiningforceneo/CAMERA_ANALYSIS.md`](docs/games/shiningforceneo/CAMERA_ANALYSIS.md)

### 5.3 シャイニング・フォース イクサ
- 日本版 `SLPM-66646 / 8B383FDF` の通常パーティ追従カメラに対応。ネオと角度・距離・高さの配置は似ていますが、
  キャラクター座標、既定値、入力・投影処理を個別に解析しています。単なるアドレス一括置換ではありません。
- Orbit、距離 **300〜6000**、注視点高さ **−400〜400**、Pitch 表示 **−25〜+89.5°**、水平 FOV **20〜110°**。
  Free Camera・位置／注視点 X/Z オフセットは非対応として無効表示します。
- FOV は原作の垂直角パラメーターを水平画角へ換算して制御し、投影行列と実画面の変化を確認済みです。
  ネオの FOV コードケーブは使いません。FOV 上書きも Orbit と同じ平滑化ゲートを保持するため、
  **FOV だけの上書き中も場所依存の原作カメラ制御が止まります**。
- Orbit 中は右スティックの専用 load **2 命令のみ**を中立値へ置換。原作クイックバーとの競合を抑え、
  左スティック・ボタン・raw 入力は残します。Original／通常終了で 2 命令とカメラ・FOV を返します。
- マップは原作処理でカメラ回転に連動（同じ場所で yaw 180→90°、方位と地形の90°回転を確認）。FOV ではマップを拡縮しません。
- stock ステート読込み後は約 1 秒の再確認で再適用。別ゲーム／識別不能なら既存ガードに従い復元書込みせず破棄します。
- 確認は提供ステートの拠点内と短い移動が中心です。全エリア・イベント・戦闘・メニュー・長時間、
  入力録画／再生の別経路は未検証。右スティック遮断は Orbit 中のメニューにも残るため、必要時は Original へ戻してください。
- [解析](docs/games/shiningforceexa/CAMERA.md)・[実行した確認と制限](docs/games/shiningforceexa/TEST_RESULTS.md)

### 5.4 幻想水滸伝V
- フィールドカメラ更新（`FUN_00243E10`）の出力処理にコードケーブを差し込み、注視点・距離・ピッチ・ヨー・FOV を上書きします。
  歩行方向はゲームが読むヨーに従うので、**左スティックの進行方向もカメラ基準**になります。
- 原作のカメラは固定角で、右スティックはカメラ回転ではなく**3 段階ズーム**に使われています（R1 も同じズーム、距離 400 → 300 → 200）。
  オービット中は右スティックを MOD が使い、ゲーム側のスティックズームは遮断します。R1 は生きていて、
  「ゲーム標準ズーム」欄のチェックを入れると R1 の段階に合わせてオービット距離も変わります。
- 場所依存のカメラ（ピッチが 13° → 40° に変わる坂など）はオービット中は無視され、マップ移動後も設定が再適用されます。
- オフセットはワールド座標で、リグ全体を動かします。近いズーム段階ほど画面上で大きく見えます。
- 未検証: イベント・戦闘・メニュー（カメラ更新が止まるので MOD は手を出しません）。
- 解析記録とテスト結果: [`docs/games/suikoden5/`](docs/games/suikoden5/)

### 5.5 ザ・ナイトメア・オブ・ドルアーガ
- 日本版 `SLPS-25377 / B476ED7A`。城内と通常ダンジョンは別クラス・別更新経路として解析し、両方を登録しています。
- Orbit、距離 **2〜100**、Pitch 表示 **−25〜+89.5°**、注視点高さ **−15〜15**、水平 FOV **20〜110°**。
  カメラ位置 XYZ と注視点 XYZ は独立して動きます。Free Camera は非対応として無効表示します。
- 原作のカメラ目標値・平滑化・衝突出力は更新させ続け、最終描画用の行列だけを差し替えます。
  プレイヤー座標をゲーム内で毎フレーム加算するので、ホストが止まっても古い絶対座標へ固定しません。
- Orbit 中は processed RX/RY と派生方向ビットを中立化。raw 入力・左軸・ボタンは保ち、アイテム操作との競合を抑えます。
  原作で右軸を使うメニューでは Original に戻してください。ダンジョンの歩行は原作の方向キー操作です。
- Orbit 中の城内移動は実際の視点→注視点の水平方向へ変換します。ダンジョンは同じ方位を最寄り8方向へ丸め、
  原作のタイル移動へ渡します。位置オフセットで変わった視線も反映し、左アナログのアイテム操作や対象選択UIは変更しません。
- Original／通常終了で両 camera hook・移動3 hook・pad hook・派生入力4命令・FOVを原作へ返します。
  stock ステート読込み後は約1秒で再適用。未確認クラス・ロード・演出状態は host と guest の両方で拒否します。
- 壁の内部／未描画の裏面が見える場合があります（Orbit に原作のカメラ衝突補正は適用しません）。
  城内・B1Fでの確認であり、全フロア・ボス・全イベント・入力録画再生の保証ではありません。
- FOV は Orbit に付随して使います。現行共通runtimeは Original の FOV-only を実行しません。
- [解析・安全条件](docs/games/nightmaredruaga/CAMERA.md)・[実行した確認と制限](docs/games/nightmaredruaga/TEST_RESULTS.md)

### 5.6 ラジアータ ストーリーズ
- 日本版 `SLPM-65800 / AC73005E` の通常フィールドに対応。右スティックは原作では未割当なので、入力遮断パッチを追加しません。
- Orbit、距離 **150〜6000**、Pitch **−25〜+89.5°**、注視点高さ **−500〜500**、水平 FOV **20〜110°**。
  視点 XYZ と注視点 XYZ は独立したオフセットです。高さは **負が上**、Free Camera は非対応です。
- 原作の位置・回転・画角・スクリプト更新を保持し、描画用 view と frustum を生成する間だけ行列を置き換えて返します。
  プレイヤーの最新座標を guest が加算するため、歩行追従をホストの連続座標書込みに依存しません。
- メニューの player停止 flag と camera/actor 所有を host・guest の両方で確認。確認したステータスメニューでは抑止しましたが、
  全イベント・戦闘・全ロード経路の判定保証ではありません。特殊場面では Original に戻してください。
- 移動計算が参照するカメラ forward も Orbit の実際の視線へ差し替えるため、左アナログ・方向キーの進行方向は
  カメラ基準になります。原作の入力・速度・移動制限は保ち、メニュー停止時や所有不一致では原作へ戻します。
- Original／通常終了で描画3フックと移動1フックを復元。stock ステート読込み後も再適用します。
  FOV は Orbit に付随し、Original の FOV-only は共通runtimeの対象外です。
- 原作のカメラ衝突補正は Orbit に適用しません。壁・未描画の裏面が見える場合があります。
  歩行にも原作の地形・衝突制限が残ります。限定場面の短い方向測定であり、全 yaw・全地形・長時間の保証ではありません。
- [解析・安全条件](docs/games/radiatastories/CAMERA.md)・[実行した確認と制限](docs/games/radiatastories/TEST_RESULTS.md)

### 5.7 ロマンシング サガ -ミンストレルソング-
- 日本版 `SLPM-65920 / 2B9AF3C5`、通常フィールド追従モード2に対応。原作の右スティックにカメラ回転機能はなく、入力遮断は追加しません。
- Orbit、距離 **1〜80**、Pitch **−25〜+89.5°**、注視点高さ **−10〜10**、水平FOV **20〜110°**。
  視点XYZ・注視点XYZは独立オフセット。高さは**負が上**、Free Cameraは非対応です。
- 原作リグの視点・注視点・平滑化を保持し、field専用のlook-at引数だけを差し替えます。
  guestが最新player位置を加算するため、ホストの連続座標書込みなしでも追従します。
- 原作のcamera yawを実際のOrbit視線から計算し、**コンパスの方位盤・キャラの針・歩行方向**を連動させます。
  キャラheadingは変更しません。カメラ回転とキャラの方向転換は別々に反映されます。
- Original／通常終了で3hook・原作投影scale・camera yaw/distanceを返します。stock state読込み後は約1秒で再適用。
  FOVはOrbitに付随し、OriginalのFOV-onlyは共通runtimeの対象外です。
- イスマス城内の4提供state・GUI実機22項目・短い歩行で確認。全エリア・戦闘・全イベント・長時間は未検証です。
  hostの場面判定はメニューを識別できません。確認したメニューではfield hookは実行されませんが、特殊場面ではOriginalへ戻してください。
- Orbitに原作の衝突補正は適用しません。壁・柱の内側や裏面が見える場合は距離を縮めるか角度を調整してください。
- [解析・安全条件](docs/games/minstrelsong/CAMERA.md)・[実行した確認と制限](docs/games/minstrelsong/TEST_RESULTS.md)

### 5.8 ドラゴンクエストV 天空の花嫁
- 日本版 `SLPM-65555 / B64E9939` の通常パーティ追従場面に対応。原作の右スティックは左右回転だけですが、
  Orbitでは**左右でyaw、上下でpitch**を操作し、離した角度を保持します。
- 距離 **20〜600**、Pitch表示 **−25〜+89.5°**、注視点高さ **−50〜80**（正が上）、水平FOV **20〜110°**。
  eye/target XYZは独立offset。Free Cameraは非対応です。
- nativeリグは更新させ続け、描画用行列と画角を一時差替えして処理後に返します。guestが最新player位置を加算するため、
  hostの連続座標書込みなしでも追従します。原作右RXはcamera専用関数の実行中だけ中立化し、raw入力・左軸・ボタンは保持します。
- **歩行とキャラの向きはOrbitの実際の視線基準**です。原作Y回転・速度・衝突・向き計算を流用し、移動と向きのyaw入力だけを同じ角度へ合わせます。
  eye offsetで変わった視線も反映し、原作のglobal camera yawは保持します。スクリプト歩行・別locomotionは変換しません。
- 通常field用の原作yaw上限・下限・入力vetoは描画Orbitへ適用しません。ただし固定視点・イベント・別camera classは安全guardを残し、
  **特殊cameraの360°回転解除は未対応**です。ユーザーの追加指示により、その個別対応は別件・今回対象外です。
- Original／通常終了で描画・右入力・移動・向きの4hookを復元し、原作右スティックの左右回転へ戻ります。stock state読込み後は約1秒で再適用。
  追加3hookの適用と全4hookの解除はguest EE threadが実行します。pause中は完了できないため、再開してから再試行してください。
  描画hookの初回bootstrapはPINE書込みが残り、PCSX2の全code-page競合を解消する保証ではありません。
  FOVはOrbitに付随し、OriginalのFOV-onlyは共通runtimeの対象外です。
- 提供4stateは同じ海辺の庭の通常場面。GUI・4yawの前後歩行と向き・屋内への移動・state再適用／解除を確認しましたが、全エリア・イベント・戦闘・メニュー・
  長時間は未検証です。特殊場面ではOriginalへ戻してください。壁・屋根・未描画の裏面が見える場合があります。
- [解析・安全条件](docs/games/dragonquest5/CAMERA.md)・[実行した確認と制限](docs/games/dragonquest5/TEST_RESULTS.md)

### 5.9 新牧場物語 ピュア イノセントライフ
- 日本版 `SLPS-25763 / 9AC21F92` の通常プレイヤー追従場面向けです。原作には右スティックカメラがないため、入力遮断パッチは追加しません。
- Orbit の yaw/pitch、距離 **10〜600**、Pitch **−25〜+89.5°**、注視点高さ **−100〜100**（負が上）、eye/target 独立6軸オフセット。
  水平 **FOV 20〜110°** に対応。現在値は実際の投影行列から読み、原作は約 **71.635°** です。Free Camera は非対応として理由付きで無効化します。
- FOV は描画用コピーの焦点距離へ適用し、原作の投影・クリッピング行列をまとめて再生成します。native camera は変更せず、
  「ゲーム値に戻す」・Original・正常終了でその時点の原作画角へ戻します。FOV は Orbit に付随し、Original の FOV-only は対象外です。
  FOV非対応だった旧版のコードケーブは自動上書きしません。旧GUIを正常終了し、ゲームを再起動するかstock stateを読込んでから新GUIを起動してください。
- 原作カメラの追従・地形補正は更新させ続け、描画に渡す camera struct のコピーだけを Orbit へ差し替えます。
  guest が現在のプレイヤー座標を加算するため、ホストの絶対座標連続書込みに依存しません。
- 左スティック／方向キーの入力角に足す camera yaw だけを実際の Orbit 視線へ合わせ、原作の速度・衝突・向きの平滑化を維持します。
- **ゲーム内時間を停止**はカメラから独立した、通常時計への加算秒だけをゼロにする機能です。移動・アニメーションは続きます。
  原作の基準更新は続けるため解除時に停止時間をまとめて加算しません。睡眠・イベント等の明示的な時刻設定は対象外です。
- 起動・再接続時は Original＋時計停止オフ。時計停止は設定・プリセットに保存しません。
  Original ラジオはカメラだけを戻し、**MOD 無効化ボタン／正常終了は時計停止も解除**します。
- 移動・時計命令の適用／復元と最後の描画フック解除は guest EE thread が行い、読戻しで確認します。
  **PCSX2 一時停止中は完了できません**。再開してから再試行してください。強制終了時の自動復元は保証しません。
- 通常追従以外の camera、所有不一致・イベント停止等は host/guest で拒否しますが、全メニュー・全マップ・イベントを保証する判定ではありません。
  Orbit の壁衝突は適用しないため、壁・木・地形の裏側が見える場合は距離・角度を調整してください。
- [解析・安全条件](docs/games/innocentlife/CAMERA.md)・[実行した確認と制限](docs/games/innocentlife/TEST_RESULTS.md)

### 5.10 グランディアII
- 日本版 `SLPM-65081 / B6AB7BC2`。通常fieldの屋外追従mode8と屋内固定mode0を対象にします。
  原作には右スティックcameraがなく、入力遮断は追加しません。確認した屋外の原作yaw操作はL1/R1、屋内は固定視点です。
- 右スティックyaw／pitchのOrbit、距離 **100〜10000**、Pitch表示 **−25〜+89.5°**、注視点高さ **−1000〜+1000**（正が上）、
  eye／target独立6軸オフセット各 **−3000〜+3000**、水平 **FOV20〜110°**。Free Camera・時計停止は非対応です。
- 原作cameraを更新した後、描画用NJ cameraのコピーへeye／単位forwardを渡し、native builderでview・逆行列・frustumを作ります。
  最終focalとfield focalを一致させ、field tailでnative数値・current projection pointerへ戻します。queued projection records/countは消しません。
  native camera structは書き換えず、guestが最新player位置を加算して追従します。
- 左analog／方向キーは、camera引数のコピーに実視線yawだけを設定して原作移動関数へ渡す方式です。
  offsetで変化した視線も反映し、速度・向き・衝突・ボタン入力は原作に任せます。旧3hook版の短い歩行測定では屋内の横滑り／停止があり、実方向キー入力は未検証です。
- 原作の屋外は距離2400／pitch30°／高さ180／水平FOV約19.995°、屋内は距離1400／pitch12°／水平FOV約29.993°。
  FOVはangle fieldだけではなく最終focalで制御し、「ゲーム値に戻す」はその時点の原作focalを選びます。OriginalのFOV-onlyは対象外です。
- 旧版で100°時に停止した原因は、原作がpacketのEND生成**後**に2MiB上限を検査していたことです。現行版はclosed DIRECT／UNPACK／CONTROL入口で事前reserveし、
  足りなければ原作のEND→finalize→FlushCache→send→reset→newCNTで分割送信します。原作2bank・上限・fatal検査を変更せず、queue・projection・順序・CPU側VU indexを保持します。
  DIRECT前には別CNT境界も作りDMA tagのQWCを保護します。valid native field writerのprotocol／source boundsが前提で、破損データの巨大DIRECTを救済する機能ではありません。
- 現行はrender／tail／move＋finish＋packet3入口の**全7site、5 code resources、G2C2**です。Original／正常終了では最後のOrbit frameのsubmit帰還後に全7siteをguestが復元します。
  native queue tailでの解除は早すぎるため行いません。hostは初回render1wordだけをbootstrapし、**一時停止中はguest ACKできません**。
  各bank公開は全7exact hook pair・control magic・flags・ACKを確認し、全cave検査は初回／backend・epoch変更／state消失／約1秒の周期確認／解除時です。
  cave本体だけの破損は即時検知しません。GUI書込みは既存GuardedBackend経由です。
- **旧G2C1と現行版の混在はfail-closed**です。旧adapterを正常解除して終了し、さらにstock state読込みまたはゲーム再起動で旧cave／controlを消してから新版を使ってください。
  正常解除だけでは旧cave／G2C1 magicが残ります。MODを含むstateはstockではないため、clean stockがなければ再起動してください。未知hook／caveを強制上書きしません。
- 最終最適化後のraw実機runでは両sceneでFOV110°、4yaw×内部pitch4種の各約0.5秒でフレーム進行を確認。yaw45°水平の各約20秒では屋外239frame／718flush、屋内600frame／0flushでした。
  boundary highwaterは屋外1126008B／屋内1023844B（reserve入口の観測値で、全write最高水位の証明ではありません）。FOV20／40／60／100／110°読戻し・native reset・全7site解除・stock state再適用も確認。
  MainWindowの別runは14項目成功（Original起動0write・GUI範囲／入力・FOV・reset pose保持・6offset・全7site復元）。独立レビューではありません。
  屋外110°水平画像はgeometry／HUD表示を親担当が確認。屋内は距離2000で小さな室内geometryと黒い空間が見えており、全scene描画成功とはしません。
  壁・裏面・屋内geometry外の黒い空間は距離・角度で回避してください。全エリア・イベント・戦闘・メニュー・長時間は未網羅で、大可視量による負荷増は残ります。
  旧3hook／20〜60°実績とcleanupは過去記録です。今回の測定条件・制限・最終テスト／cleanup追記欄は[検証記録の現行追記](<docs/games/grandia2/TEST_RESULTS.md#現行追記--7siteg2c2packet-streaming-2026-11-07>)を参照してください。
- 再現用の限定GUI試験は [grandia2_live_check.py](<tools/grandia2_live_check.py>)。通常fieldを実行中に、他PINE clientを閉じ、開始stateを退避してから別々の場面で実行します（`--help`参照）。移動入力・state操作は行わず、任意の外部state読込みはhandshakeで待ちます。
- [解析・安全条件](<docs/games/grandia2/CAMERA.md>)・[実行した確認と制限](<docs/games/grandia2/TEST_RESULTS.md>)

### 5.11 テイルズ オブ シンフォニア
- 日本版 `SLPS-25400 / 830B6FB1`。通常の町・ダンジョン系マップ（mode `0x87`）と徒歩ワールドフィールド（mode `0x8A`）向けです。
  提供8stateは同じ町4つ／ワールド4つで、全ダンジョン・戦闘・イベント・乗り物を確認したものではありません。
- 右スティック yaw/pitch の Orbit、距離 **50〜6000**、Pitch **−25〜+89.5°**、注視点高さ **−1000〜+1000**（負が上）、
  eye／target 独立6軸オフセット各 **−3000〜+3000**、水平 **FOV20〜110°**。Free Camera・時計停止は非対応です。
- 原作の非フィールドには右camera操作なし、ワールドでは右Xの横回転のみです。Orbit中は通常徒歩ワールドのcamera専用RX取得callだけを中立化し、
  左入力・ボタン・native input bufferを変更しません。特殊車両・飛行cameraは受理しません。
- 原作rigを更新させ、共通look-atと投影生成に渡す引数コピーだけを差し替えます。移動は実視線XY、ワールドのコンパス／地図視線と地形streaming選択も同じyawに同期します。
  速度・衝突・キャラの向きは原作の計算を使います。GUI座標は既存Y-downへ変換し、表示Yの負はnative上方向です。
- FOVは実3D投影copyのsx/syを変更し、native aspect・near/farを保持します。ワールドframe末尾のHUD投影を原作FOVと誤認せず、
  「ゲーム値に戻す」はその時点のnative lens入力へ戻します（確認した町約35.492°／通常ワールド約44.105°）。Original FOV-onlyは対象外です。
- **TOS2ではPINEからゲームの実行命令へ書き込みません。** 一時的な町actor／ワールドframe callbackのdata pointerからEE lifecycleを呼び、
  全11hook+delayを検査してguestが適用・復元し、callbackもnativeへ返します。**PCSX2一時停止中はACKできないため再開して操作してください。**
  全13code resourceの完全検査は初回・接続世代変更・stock state後・約1秒周期・解除時です。通常publicationはexact hook/magic/flags/ACKを毎回検査し、cave本体だけの損傷は次の完全検査で検知します。
- 8stateのOrbit／FOV／全hook解除、両sceneの広角110°と4yaw×4pitchでフレーム進行を確認しています。町ではマップ外の黒背景や屋根裏面が見えるため、距離・画角・角度を調整してください。
  カメラの壁衝突は追加しません。全scene・長時間・全culling／補助描画は未網羅です。
- [解析・安全条件](<docs/games/talesofsymphonia/CAMERA.md>)・[実行した確認と制限](<docs/games/talesofsymphonia/TEST_RESULTS.md>)

## 6. ローカルデータの場所（Git 管理外）

ISO・BIOS・セーブステート・ダンプはリポジトリに含めません。場所は次の順で解決されます（`core/config/paths.py`）。

| 環境変数 | 既定（元のラボ構成） | 内容 |
|---|---|---|
| `PS2_LAB_DIR` | リポジトリの親フォルダ | ラボのルート |
| `PS2_PCSX2_DIR` | `<lab>/pcsx2/fork-B056de99` | PCSX2（ini・cheats） |
| `PS2_GAME_DIR` | `<lab>/pcsx2/iso` | ゲームイメージ |
| `PS2_BIOS_DIR` | `<lab>/pcsx2/bios` | BIOS |
| `PS2_SAVESTATE_DIR` | `<lab>/sstates` | `.p2s` |
| `PS2_DUMP_DIR` | `<lab>/work` | 展開したステート・RAM ダンプ・Ghidra プロジェクト |
| `PS2_EVIDENCE_DIR` | `<lab>/test_evidence` | スクリーンショットとテスト証跡 |

環境変数の代わりに `config/local_config.example.json` を `config/local_config.json`（Git 無視）へコピーして書いても構いません。
ほかの PC へ移すときはこの設定だけで再構築できます。

## 7. 検証

```powershell
python -m pytest tests -q          # 単体テスト（実機・エミュレータ不要。GUI は offscreen、Git 監査は一時リポジトリで試験）
python tools/audit_repo.py --staged   # コミット前: Git インデックスの内容を監査（ゲームデータ・秘密情報・大きなファイル）
python tools/audit_repo.py            # 追跡ファイルの作業ツリー上の内容（--commit REV / --history もあります）
```

実機検証は PCSX2 でゲームを起動し、そのゲームの `base.p2s` を読み込んでから実行します（PINE クライアントは 1 つだけ）。

| 対象 | コマンド |
|---|---|
| 全ゲーム共通の回帰（Orbit・FOV・復帰） | `python tools/regression_check.py` |
| GUI を PCSX2 の強制終了・再起動で試す | `python tools/gui_freeze_check.py --kill --relaunch` |
| PCSX2 が別のゲームで戻ったとき旧ゲームへ書かないか | `python tools/game_switch_check.py`（幻想水滸伝V → SF Neo。ディスクとセーブステートは読むだけ） |
| 幻想水滸伝V | `tools/su5_live_check.py`、`su5_engine_check.py`、`su5_input_check.py`、`su5_zone_check.py`、`su5_transition_check.py`、`su5_gui_check.py`、`su5_zoom_check.py`、`su5_soak.py` |
| シャイニング・フォース イクサ | `python tools/sfexa_live_check.py --out <lab>/test_evidence/exa/live.json`、`python tools/sfexa_gui_check.py --out <lab>/test_evidence/exa/gui`（GUI 検証は一時設定を使用、実キーボードpad入力あり。state再適用は解析文書参照） |
| ドルアーガ | `python tools/druaga_live_check.py --out <lab>/test_evidence/druaga/run`（実入力あり。Dungeonは方向キーの通れる隣接タイルを `--dungeon-direction left` 等で指定。reload手順はゲーム別検証記録参照） |
| ラジアータ | `python tools/radiata_live_check.py --out <lab>/test_evidence/radiata/run`（一時設定・GUI/Orbit/FOV/復元。`--move` は短い左スティック歩行、`--reload-handshake <empty-dir>` は外部state読込との同期。詳細はゲーム別検証記録） |
| ミンストレルソング | `python tools/minstrelsong_live_check.py --out <lab>/test_evidence/minstrelsong/run --move`（GUI/Orbit/コンパス/FOV/復元、`--move` は短い左スティック歩行。`--reload-handshake <empty-dir>` は外部stock state読込みと同期。複製カード・保護したステートを使用） |
| DQⅤ | `python tools/dragonquest5_live_check.py --out <lab>/test_evidence/dragonquest5/run --move`（GUI/Orbit/FOV/右入力競合・復元。`--move`は4yawで短い前後移動・native速度/向き・guest追従を測定。障害物のない場所で実施。外部state読込みは`--reload-handshake <empty-dir>`。複製カード・保護したステートを使用） |
| イノセントライフ | `python tools/innocentlife_live_check.py --out <lab>/test_evidence/innocentlife/run --move`（GUI/Orbit/FOV/独立時計停止/復元。`--move`は4yawで短い前後移動と向きを測定。複製カード・保護したステートを使用し、通れる場所で実行。外部stock state読込みは`--reload-handshake <empty-dir>`） |
| テイルズ オブ シンフォニア | `python tools/talesofsymphonia_live_check.py --out <lab>/work/symphonia/gui-run`（実行中の通常町／worldへMainWindowから接続、scriptedカメラ入力・FOV・6offset・全hook/callback復元。state・移動操作なし。freshなGit外出力先、開始状態退避、他PINE client終了が必要。`--help`参照） |
| ラジアータ／ドルアーガの移動方向 | `python tools/orbit_movement_check.py --game radiata --yaw 180 --direction up --out <lab>/test_evidence/radiata/movement.json`（複製カードと安全な同版ステートを用意。`--game druaga` は城内／Dungeonを識別、Dungeonは方向キー。壁・狭い足場による無移動や横滑りは別途切り分ける） |
| FFX-2 | `tools/e2e.py`、`tools/flicker_test.py --yaw 120 --frames 24`、`tools/verify_state.py --state base` |

結果は表示と `reports/`（JSON）に出ます。スクリーンショットなどの証跡は Git 管理外です。幻想水滸伝V の結果一覧は
[`docs/games/suikoden5/TEST_RESULTS.md`](docs/games/suikoden5/TEST_RESULTS.md) にあります。

## 8. トラブルシューティング

| 症状 | 対処 |
|---|---|
| 「未接続」のまま | PCSX2 が起動していて `EnablePINE = true` か確認。GUI とスクリプトを同時に使っていないか確認 |
| 起動時に「すでに起動しています」 | 別のカメラコントローラーが開いています。閉じてから起動してください |
| 未対応ゲームと表示される | Serial / CRC が違います。書き込みは行いません（安全） |
| PCSX2 でゲームを切り替えた | GUI は約 0.25〜0.4 秒で気づき、前のゲームには何も書き込まず（元に戻す処理も行わず）、新しいゲーム用に選び直します。未対応ゲームなら書き込み不可の表示になります。詳細は [`docs/gui/GAME_IDENTITY_GUARD.md`](docs/gui/GAME_IDENTITY_GUARD.md) |
| カメラが動かない | 対応するフィールドか確認。scene guardで書込みを控える場合がありますが、全戦闘・イベントの判別は保証しません。特殊場面ではOriginalへ戻してください |
| カメラが元に戻らない | 「MOD を無効化して元のカメラに戻す」を押す。それでも戻らなければゲームを再開 |
| PCSX2 を再起動した | GUI は自動で復帰します（設定は保持）。FFX-2 のパッチはモードに応じて runtime が管理します。`EnableCheats` は不要で、「ゲームパッチ」欄と旧外部パッチの競合を確認 |
| セーブステートを読み込んだ | MOD のコードパッチが消えますが、約 0.2 秒（FFX-2・SF Neo・SF Exa・ドルアーガ・ラジアータ・ミンストレルソング・DQⅤは約 1 秒）で自動再適用されます |
| 右スティックが効かない | パッドが XInput（Xbox 系）で認識されているか、「入力ソース」が keyboard / scripted になっていないか確認。矢印キーでも回せます |
| 左スティックの向きがカメラと合わない | FFX-2 は Orbit と「ゲームパッチ」の適用状態、旧外部パッチの競合を確認（§5.1）。手動 `enable` は不要。幻想水滸伝V ではカメラ基準になります。SF Neo は未対応、SF Exa は歩行保持を確認したものの全 yaw の方向測定は未実施。DQⅤの通常field歩行はOrbit視線基準へ対応（スクリプト歩行・別locomotionは対象外）。特殊cameraで回らない場合は場所名／stateでの個別調査が必要 |
| 狭い場所で画面が壁で埋まる | 距離を縮めるか Pitch を下げる（ゲームの衝突判定を通らないため） |

詳しい不具合記録: [`docs/lab/TROUBLESHOOTING_KB.md`](docs/lab/TROUBLESHOOTING_KB.md)、未解決事項: [`docs/lab/BLOCKERS.md`](docs/lab/BLOCKERS.md)。

## 9. ディレクトリ構成

```
PS2UniversalMod/
├─ core/
│  ├─ camera_math/orbit.py          Orbit 計算・FOV 変換（ゲーム非依存）
│  ├─ camera_runtime/engine.py      毎フレーム書き込みエンジン
│  ├─ controller/sources.py         XInput / キーボード / スクリプト入力
│  ├─ memory_backend/pine_backend.py  PINE クライアント（PCSX2 が無いときは即座に失敗）
│  ├─ memory_backend/guard.py       書き込みガード（Serial/CRC が違うゲームへは書かない）
│  ├─ config/settings.py            設定・プリセット
│  ├─ config/paths.py               ローカルデータの場所
│  └─ mips_asm.py                   MIPS 命令エンコーダ（コードケーブ用）
├─ adapters/
│  ├─ ffx2/                         memory_map.py（アドレス）、adapter.py、lookat_cave.py
│  ├─ shiningforceneo/              + fov_cave.py、pad_cave.py
│  ├─ shiningforceexa/              制御値＋局所 pad 命令（cave 不要）
│  └─ suikoden5/                    + caves.py
├─ gui/camera_controller/           PySide6 GUI（app.py、i18n.py）
├─ analysis/                        差分解析・Ghidra スクリプト
├─ tools/                           実機検証・監査ツール
├─ tests/                           pytest
├─ docs/                            文書（入口: docs/README.md）
├─ reports/                         生成された数値の要約（JSON・差分表）
├─ config/                          local_config.example.json
├─ presets/                         同梱プリセット（FFX-2 用）
├─ patches/                         FFX-2 の .pnach テンプレート
├─ ADAPTER_GUIDE.md                 新しいゲームの追加方法
└─ run_gui.py / PS2UniversalCamera.bat
```

## 10. リポジトリ運用（Git）

* **GitHub のプライベートリポジトリ** `yutokure/PS2UniversalMod` に置いています（非公開のまま運用します）。
  基盤 3 ゲームと GUI 修正・ゲーム切替ガードは PR #1 で `main` に統合済みです。イクサの追加状況は現在の作業ブランチを確認してください。
  新しい作業は既存 PR と現在の Git 状態を確認して作業ブランチで進めます。
* リポジトリのルートは `PS2UniversalMod/` だけです。ゲームデータの置き場（`pcsx2/`・`sstates/`・`work/` など）はこの外にあり、
  親フォルダを `git init` してはいけません。
* コミット対象はコード・テスト・文書・アドレス／関数名／ハッシュなどの要約のみ。ISO・BIOS・`.p2s`・RAM ダンプ・
  スクリーンショット・Ghidra プロジェクトと逆コンパイル出力・ログは `.gitignore` で除外済みです（Git LFS も使いません）。
* ステージングは `git add <明示的なパス>`。`git add .` / `-A` は使いません。
  コミット前に `git diff --cached --name-only`、`git diff --cached --stat`、`python tools/audit_repo.py --staged` で確認します。
  `--staged` は作業ツリーではなく **Git インデックスの中身** を検査します（`git add` の後で書き換えても結果は変わりません）。
* 任意のコミット前フック: `git config core.hooksPath tools/git-hooks` で有効化、`git config --unset core.hooksPath` で解除
  （標準では無効。1 回だけ飛ばすには `git commit --no-verify`）。詳細は [`docs/gui/GAME_IDENTITY_GUARD.md`](docs/gui/GAME_IDENTITY_GUARD.md)。
* 新しいゲームの追加手順は [`ADAPTER_GUIDE.md`](ADAPTER_GUIDE.md)（末尾の「Git での追加手順」）。

## 11. 文書

入口は [`docs/README.md`](docs/README.md)（ゲーム別の解析、GUI レビュー、開発ラボの構築・トラブルシュート記録）。
