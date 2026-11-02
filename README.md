# PS2 Universal Camera Controller

PS2 ゲームの通常フィールドで、**右スティックによる自由回転カメラ**と
**外部 Windows GUI からのリアルタイム制御**を実現する MOD コントローラー。
共通基盤（`core/`・GUI）とゲーム別アダプター（`adapters/`）で構成され、
**FF10-2・シャイニング・フォース ネオ・幻想水滸伝V** に対応しています（一覧は §12）。
以下 §1〜§11 の詳細記述は FF10-2 を例に書かれています（ゲーム別の記録は `docs/games/`）。

文書の入口は [`docs/README.md`](docs/README.md) です。

DeepSeek Harness を起動し続ける必要はありません。GUI 単体で動きます。

```
┌────────────────────────┐        PINE (TCP 127.0.0.1:28011)
│  GUI (PySide6)         │  ───────────────────────────────►  PCSX2  ──►  FFX-2
│  CameraRuntime(thread) │        ~800 回/秒のメモリ読み書き
└────────────────────────┘
```

---

## 1. できること

> **前提**: 注視点の注入には `.pnach`（`pcsx2\fork-B056de99\cheats\8A6D7F14.pnach`）が必要です。
> このファイルは本フォルダではなく PCSX2 側にあります（本フォルダに同梱はありません）。
> これが無効だと位置・距離・FOV は効きますが、**視線だけ回りません**。
> GUI の `Connection → Look-at patch` が `active` になっているか確認してください。

| 機能 | 状態 |
|---|---|
| **Orbit** — ユウナを中心に水平360°旋回（注視点=ユウナ） | ✅ 実機動作 |
| **GUI Yaw/Pitch** — スライダーで視点が回る | ✅ |
| **右スティック** — 左右/上下回転、離すと保持、感度・反転・デッドゾーン。XInput は接続中のパッドを自動検出（スロット 1 でも可） | ✅ 入力系 |
| **カメラ位置移動** — ワールド座標 / 相対オフセット | ✅ |
| **距離** — 1〜200 単位、追従維持 | ✅ |
| **注視点の高さ** — ユウナのフレーミング調整 | ✅ |
| **FOV** — 20°〜110°、スライダー＋数値、即時反映、復帰 | ✅ |
| **プレイヤー追従** — 移動中もカメラが追従 | ✅ |
| **Original** — ゲーム本来のカメラへ復帰 | ✅ |
| **Free Camera** — キャラクタから切り離した視点 | ✅（追加機能） |
| 設定の保存／読込（プリセット、ゲーム別） | ✅ 同梱プリセット2種 |
| 接続状態・Game ID/CRC・パッチ状態・エラー表示 | ✅ |
| 安全な終了とカメラ復帰 | ✅ |
| 場面・エリア切り替え後の復帰（オフセット／照準の読み戻し再書き込み） | ✅ 追加（実機確認は未実施） |
| カメラ切り替えシーンでも中央維持（ガードを緩和） | ✅ セーブステートで確認（カメラ切り替え・左寄りの 2 場面） |
| **歩行方向のカメラ追従** — オービット中、左スティックの進行方向がカメラ基準にならない | ❌ 未解決（`docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md`、BLOCKERS B-08） |

ちらつきは**原理的に解消**しています。ゲームは eye と注視点を毎フレーム書き戻すため、
毎フレーム上書きし続ける方式では必ず競合します。本 MOD は

* eye → ゲーム自身の加算フィールド `0x3403E0` に**オフセット**を書く
* 注視点 → `.pnach` で読み取り先を `0x33FC10` から未使用スロット `0x33FC40` へ移す

ことで**書き込みを1回で済ませ**、競合そのものを無くしています（保持中の実測: 35秒で書き込み1回、
連続フレーム差分 mean 0.50〜0.56 / frac>40 0.002 ＝静止時ノイズ以下）。

---

## 2. 動作環境

| 項目 | 要件 |
|---|---|
| OS | Windows 10/11 |
| エミュレータ | PCSX2 2.7.x（`EnablePINE = true` / `PINESlot = 28011`） |
| ゲーム | FINAL FANTASY X-2 (Japan) `SLPS-25250` / CRC `8A6D7F14` |
| Python | 3.12（`PySide6`, `numpy`, `zstandard`） |

PINE は PCSX2 標準機能です（`PCSX2.ini` の `[EmuCore]`）:

```ini
EnablePINE = true
PINESlot = 28011
```

GDB サーバは不要です（解析時のみ使用）。

---

## 3. 起動方法

### 3.1 ゲームと PCSX2

1. PCSX2 で FFX-2 を起動し、フィールド（例: カシル船内）まで進める
2. `EnablePINE` が有効であることを確認（上記）

### 3.2 GUI の起動

**かんたん**: `PS2UniversalCamera.bat` をダブルクリック（またはコマンドプロンプトから実行）。

```powershell
C:\PS2CameraLab\PS2UniversalMod\PS2UniversalCamera.bat
```

このランチャーは PySide6 が入っている Python を自動で探します（探索順:
`<project>\.venv` → `<project>\..\python\venv` → 実行中の Python → PATH の `python`）。

**どの Python からでも起動できます:**

```powershell
python run_gui.py
```

`python gui\camera_controller\app.py` を直接叩く方法は、**その Python に
PySide6 が入っている場合のみ**動きます（本ラボでは
`C:\PS2CameraLab\python\venv\Scripts\python.exe` にのみ入っています）。
入っていない場合は、何をすればよいかを示すメッセージを出して終了します。

**依存関係を入れ直す場合:**

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

起動すると自動的に PINE へ接続し、`SLPS-25250 / 8A6D7F14` を確認して
`Connected` になります。ゲームが違う場合は書き込みを行いません。

> **必ず `Connection → Look-at patch` が `active` になっていることを確認してください。**
> `NOT APPLIED` の場合は PCSX2 側で `EnableCheats` を有効にするか、
> `set_cheats_enabled(true)` + `reload_patches` を実行してください。
> **PCSX2 を再起動すると `EnableCheats` は既定の無効に戻ります**（fork の `PCSX2.ini` は `false`）。
> 再起動のたびに有効化が必要です。

### 3.3 表示言語

接続欄の **「表示言語 / Language」** で `日本語` と `English` を切り替えられます。
**再起動は不要**で、選択はゲーム別に保存されます（既定は日本語）。

翻訳は `gui/camera_controller/i18n.py` の辞書にあり、Qt Linguist のビルド工程は不要です。
言語を追加する場合は `TEXT` に 1 列足すだけです。

GUI のレビュー結果（見つけた不具合と未対応項目）は
[`docs/gui/GUI_REVIEW.md`](docs/gui/GUI_REVIEW.md) にまとめてあります。

### 3.4 操作

1. **Camera Mode → Orbit** を選ぶ
2. **右スティック**を左右に倒す → ユウナの周囲を回転
3. 上下に倒す → 仰角・俯角
4. 離す → その角度を保持
5. 左スティックで歩く。**注意**: オービット中は進行方向がカメラ基準になりません（B-08、未解決）。
   カメラを回した後は、キャラの向きを見ながら操作してください
6. **Original** を押すとゲーム本来のカメラへ戻る

キーボードでも操作できます（パッド未接続時は矢印キー）。

---

## 4. GUI 項目一覧

| セクション | 項目 |
|---|---|
| Connection | PCSX2 / Game / Serial・CRC / Adapter / Runtime |
| Camera Mode | Original・Orbit・Free Camera |
| Camera Rotation | Yaw、Pitch、回転速度、感度、デッドゾーン、左右反転、上下反転、入力ソース |
| Camera Position | 距離、Camera X/Y/Z オフセット、Target X/Y/Z オフセット |
| Camera Lens | FOV（20〜110°）、FOV 有効化、現在値表示、FOV リセット |
| Controls | Enable / Disable / Reset / Restore Original / Save Preset / Load Preset |
| Native Zoom（対応ゲームのみ） | ゲーム標準ズームの段階表示、段階ボタン、R1 でオービット距離を連動 |
| Debug | カメラ座標、プレイヤー座標、更新頻度、最終更新、警告 |

スライダーと数値入力は同期しており、「適用」ボタンは不要です。
変更は次フレーム（約 16 ms 以内）に反映されます。

---

## 5. 設定ファイル

```
%APPDATA%\PS2UniversalCamera\settings.json     … ゲームIDごとの設定
%APPDATA%\PS2UniversalCamera\presets\*.json    … 名前付きプリセット
```

`settings.json` はゲーム ID をキーにした構造なので、
別タイトルのアダプターを追加しても設定が混ざりません。

---

## 6. 実装上の制約（重要）

### 6.1 視線の実体は `normalize(注視点 − 視点)`

描画用の向きは、毎フレーム呼ばれる look-at 行列ビルダ `FUN_001b07a0` が

```
0x1B07F8  lqc2 $vf4, 0x00($s2)   ; 視点    0x340360
0x1B07FC  lqc2 $vf5, 0x00($s1)   ; 注視点  0x33FC10   ← .pnach で 0x33FC40 へ
0x1B0800  lqc2 $vf8, 0x00($s0)   ; up     0x33FBC0 = (0, -1, 0)
```

から組み立てています。実測で `normalize(注視点 − 視点)` は描画基底 `0x53ADA0` と
小数5桁まで一致しました。つまり**注視点を書けば視線が回ります**。

`0x53AD80`（基底）・`0x33F620`（ビュー行列）・`0x3403B0`（yaw/pitch）はすべて
**出力のミラー**で、書いても描画は変わりません。これが以前「回らない」原因でした。

### 6.2 競合を無くす（ちらつき対策）

ゲームは視点 `0x340360` と注視点 `0x33FC10` を**毎フレーム書き戻します**
（外部から書いた値は 50 ms 以内に消える）。毎フレーム上書きし続ける方式では、
レンダラがゲーム値を読むフレームが混ざってちらつきます（実測: 連続フレーム差分 mean 46.4）。

本 MOD は競合を「勝つ」のではなく「無くします」。

| 対象 | 方法 |
|---|---|
| 視点 | ゲームが毎フレーム計算する `0x340360 = 0x340370 + 0x3403E0` の**加算項にオフセットを書く**。ゲーム自身が毎フレーム再現するので競合しない |
| 注視点 | `.pnach` 1命令で読み取り先を `0x33FC10` → 未使用スロット `0x33FC40` へ変更。ゲームは `0x33FC40` を一切触らない |

結果、**書き込みは値が変わったときだけ**（プレイヤーが歩いて基準点が動いたとき等）。
保持中の実測は 35 秒で 1 回、連続フレーム差分 mean 0.50〜0.56 / frac>40 0.002。

### 6.2.1 パッチ

```
pcsx2\fork-B056de99\cheats\8A6D7F14.pnach
    patch=1,EE,001B07FC,word,DA250030
```

PCSX2 側で `EnableCheats` を有効にするか、`set_cheats_enabled(true)` +
`reload_patches` を実行してください。無効だと視線が回りません
（GUI の `Look-at patch` 行が `NOT APPLIED` と警告します）。

### 6.2.2 回転中心

回転中心は**プレイヤー基準点 `0x340380`**、注視点も同じ点（+ `look_height`）です。
ゲーム側の注視点がどこを向いていても、回転中心と注視点は常にユウナになります。
`look_height` は既定 `-6.0`（+Y が下向きなので「基準点より 6 単位上」）。

### 6.3 シーン判定

`is_field_like()` が以下を満たさない場合は書き込みを停止します。

* プレイヤー基準点が (0,0,0) でない（ロード中でない）
* 視点-注視点距離が 1〜2000
* 視点-プレイヤー距離が 400 以下

カメラ切り替え（カットイン・エリア移動）ではゲーム本来の視点がプレイヤーから約 170 単位離れます。
旧しきい値（120）ではここで書き込みが止まり、ユウナが中央に来ませんでした。
現在は、オービットの視点を毎回プレイヤー基準で置くため、ゲーム側の視点は「妥当な値か」だけを見ます。
（`base_chara_little_moved_and_cam_big_moved.p2s` で確認。ユウナは画面中央に来ます）

戦闘・イベント・メニューでは自動的に無効化されます。

書き込み中は約 10 ms ごとに視点オフセット `0x3403E0` と照準スロット `0x33FC40` を読み戻します。
ゲームに上書きされていれば（場面切り替えや動画の後など）、次フレームに再書き込みします
（`RuntimeStats.resyncs` で回数を確認できます）。

### 6.5 既知の制限: 歩行方向はカメラに追従しない（B-08）

ゲームの歩行は、MOD が動かしている描画カメラ（`0x3403E0`・`0x33FC40`）ではなく、
ゲーム本来のカメラ状態から方向を決めています。そのため、オービットで視点を回しても
左スティックの進行方向は変わりません。書き込み実験の詳細は
[`docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md`](docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md) を参照してください。

### 6.4 壁抜け

Orbit は球面上にカメラを置くため、狭い通路で 180° 回すとカメラが壁や天井の
内側に入り、床や壁で画面が埋まることがあります。ゲーム側のカメラ衝突判定を
経由しないため避けられません。距離を短くするか Pitch を下げてください。

---

## 7. ディレクトリ構成

```
PS2UniversalMod/
├─ core/
│  ├─ camera_math/orbit.py        Orbit 計算・FOV 変換（ゲーム非依存）
│  ├─ camera_runtime/engine.py    毎フレーム書き込みエンジン
│  ├─ controller/sources.py       XInput / キーボード / スクリプト入力
│  ├─ memory_backend/pine_backend.py  PINE クライアント
│  ├─ config/settings.py          設定・プリセット
│  ├─ config/paths.py             ローカルデータの場所（環境変数 / local_config.json）
│  └─ mips_asm.py                  MIPS 命令エンコーダ（コードケーブ用）
├─ adapters/
│  ├─ ffx2/                       FFX-2（memory_map.py にアドレス、adapter.py に実装）
│  ├─ shiningforceneo/            シャイニング・フォース ネオ（+ FOV / パッドのコードケーブ）
│  └─ suikoden5/                  幻想水滸伝V（memory_map.py / caves.py / adapter.py）
├─ gui/camera_controller/         PySide6 GUI（app.py、i18n.py）
├─ analysis/                      差分解析・Ghidra スクリプト（suikoden5/ ghidra/ savestate_diff/）
├─ tools/                         実機検証ツール（su5_*_check.py、regression_check.py、audit_repo.py ほか）
├─ tests/                         pytest（実機なしで動く単体テスト）
├─ docs/                          文書（lab/ games/ gui/）。入口は docs/README.md
├─ reports/                       生成物の要約（JSON・差分表）。画像・ダンプは Git 管理外
├─ config/                        local_config.example.json（実体は Git 管理外）
├─ presets/                       同梱プリセット
└─ README.md
```

---

## 8. 検証

```powershell
# 単体テスト
python -m pytest tests -q

# 実機 E2E（PCSX2 + ゲーム起動中）
python tools/e2e.py

# ちらつき検査
python tools/flicker_test.py --yaw 120 --frames 24

# サバステート照合
python tools/verify_state.py --state base
```

結果は `reports/e2e/e2e_results.json`、`reports/flicker/flicker_result.json` に残ります。

---

## 9. 解析資料

| ファイル | 内容 |
|---|---|
| `docs/games/ffx2/SAVESTATE_INVENTORY.md` | 既存4ステートの同定・情景・差分条件 |
| `docs/games/ffx2/CAMERA_MEMORY_MAP.md` | カメラ／プレイヤーの全アドレスと根拠 |
| `docs/games/ffx2/FOV_ANALYSIS.md` | FOV の導出と角度換算 |
| `docs/games/ffx2/` | FFX-2 の解析記録一式（ORBIT_BREAKTHROUGH、WALK_DIRECTION_INVESTIGATION ほか） |
| `docs/games/shiningforceneo/CAMERA_ANALYSIS.md` | シャイニング・フォース ネオの解析記録 |
| `docs/games/suikoden5/` | 幻想水滸伝Vの解析記録（CAMERA.md）とテスト結果（TEST_RESULTS.md） |
| `reports/*.json`, `reports/SUIKODEN5_STATE_DIFF.md` | 生成された数値の要約（画像・逆コンパイル出力は Git 管理外） |

---

## 10. トラブルシューティング

| 症状 | 対処 |
|---|---|
| `Disconnected` のまま | PCSX2 の `EnablePINE` を確認。ゲームが起動しているか確認 |
| `unsupported game` | Serial/CRC が違う。書き込みは行わない（安全） |
| カメラが動かない | フィールドにいるか確認（戦闘・イベント中は無効） |
| カメラが元に戻らない | GUI で **Restore Original Camera** を押す。それでも戻らない場合はゲームを再開 |
| PCSX2 再起動後 | GUI の **Reconnect** を押す（設定は保持）。`Look-at patch` が `NOT APPLIED` なら `EnableCheats` を再度有効にする |
| 右スティックが効かない | パッドが XInput（Xbox 系）で認識されているか確認。接続後は自動検出されます。`rot.input` が `keyboard` や `scripted` になっていないか確認 |
| 場面・エリア移動後にオービットが外れる | 自動で再書き込みされます（`resyncs` が増えます）。外れたままならエリアが戦闘・イベント扱いの可能性があります |
| 左スティックの向きがカメラと合わない | 既知の制限（§6.5、B-08）です（幻想水滸伝V ではカメラ基準になります） |
| PCSX2 を突然終了するとウィンドウが固まる | 修正済み（2026-11-02）。PINE の読み取りは別スレッドで行い、接続できない間は即座に失敗します。ウィンドウは「未接続」を表示し、PCSX2 が戻れば自動で復帰します（`tools/gui_freeze_check.py --kill --relaunch`） |

## 11. ゲーム本体のカメラを使う方式（フック、既定で有効）

オービットの視点・中心・歩行の向きを、ゲーム本体のカメラルーチンに任せる方式です。
`.pnach` の差し替え（`patches/stock_camera_hook.pnach.txt`）で、ゲームの視点計算（`FUN_001B0388`）の
入力を MOD 専用のスロットへ向けます。

- 視点の角度・距離・中心（ユウナ）が指定どおりになることを確認済み（軌道 0/90/180°、距離 28.7、
  ユウナは床・エリア切り替え・左寄りの 3 場面で中央）。
- **歩行方向も軌道に追従**: 軌道 0° で直進（進行方向 −0.2°）、軌道 +90° で −90.2°、−90° で +89.8°
  （いずれも歩き始めの 0.3 秒の実測。その後は壁で止まるため、広い場所での長い歩行は未確認）。

### 有効・無効

```bash
python tools/stock_hook.py status
python tools/stock_hook.py disable
python tools/stock_hook.py enable
```

切り替えたら PCSX2 でゲームを再起動するか、パッチを再読込してください。

### 注意

この方式は、MOD が動いている間だけ正しく働きます。MOD を閉じた状態でフックが有効なままだと、
ゲーム本来のカメラがスロットの古い値のまま崩れます。MOD を使い終わったら `disable` を実行してください。
MOD 単体の起動中は、通常どおり操作できます（停止中のオービット補正は従来どおりの方式で行います）。

詳細: `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md` §9。

### 既知の制限（other_area_base）

- 演出カメラのあるエリア（`other_area_base`）では、オービット中に FOV 制御の効果がまだありません。
  視点・中心・歩行方向は軌道どおりになります。FOV は通常のフィールドでは効きます。
  詳細は `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md` §11。

---

## 12. 対応ゲーム一覧

| ゲーム | アダプター | Serial / CRC | 状態 |
|---|---|---|---|
| FINAL FANTASY X-2 | `adapters/ffx2` | SLPS-25250 / 8A6D7F14 | Orbit・FOV・オフセット |
| シャイニング・フォース ネオ | `adapters/shiningforceneo` | SLPM-65908 / 64F241D2 | Orbit・FOV・右スティック遮断 |
| 幻想水滸伝V | `adapters/suikoden5` | SLPM-66286 / 7380A572 | Orbit（yaw/pitch/距離）・FOV・注視点/カメラ位置オフセット・右スティックのズーム遮断・R1 3段階ズーム連携 |

幻想水滸伝V の解析記録は [`docs/games/suikoden5/CAMERA.md`](docs/games/suikoden5/CAMERA.md)、
5 ステートの差分は [`reports/SUIKODEN5_STATE_DIFF.md`](reports/SUIKODEN5_STATE_DIFF.md)、
検証結果は [`docs/games/suikoden5/TEST_RESULTS.md`](docs/games/suikoden5/TEST_RESULTS.md) にあります。

### 幻想水滸伝V の使い方

1. PCSX2 で `suikoden5.iso` を起動し、フィールドまで進める（`EnablePINE = true`）
2. `PS2UniversalCamera.bat` で GUI を起動 → 自動で `SLPM-66286 / 7380A572` を確認して接続
3. **Camera Mode → Orbit**（または「有効化」）。右スティックで水平・垂直回転、
   左スティックで歩くと進行方向もカメラ基準になる（ゲームの歩行処理が回転後の yaw を読むため）
4. **ゲーム標準ズーム**欄: R1 の 3 段階（400/300/200）の現在段階を表示。チェック時は
   R1 でオービット距離も段階変更。オービット中は右スティックのゲーム側ズームは遮断
5. **Original / 純正カメラ復帰** でフックを外し、右スティックズーム・R1・エリアのカメラが元に戻る

注意: PINE クライアントは同時に 1 つだけにしてください（GUI とスクリプトを同時に動かすと
タイムアウトします）。

## 13. ローカルデータの場所（Git 管理外）

ISO・BIOS・セーブステート・ダンプはリポジトリに含めません。場所は次の順で解決されます
（`core/config/paths.py`）。

| 環境変数 | 既定（旧ラボ構成） | 内容 |
|---|---|---|
| `PS2_LAB_DIR` | リポジトリの親 | ラボのルート |
| `PS2_PCSX2_DIR` | `<lab>/pcsx2/fork-B056de99` | PCSX2（ini・cheats） |
| `PS2_GAME_DIR` | `<lab>/pcsx2/iso` | ゲームイメージ |
| `PS2_BIOS_DIR` | `<lab>/pcsx2/bios` | BIOS |
| `PS2_SAVESTATE_DIR` | `<lab>/sstates` | `.p2s` |
| `PS2_DUMP_DIR` | `<lab>/work` | 展開したステート・RAM ダンプ・Ghidra プロジェクト |

`config/local_config.example.json` をコピーして `config/local_config.json`（Git 無視）にすれば、
環境変数なしでも指定できます。ほかの PC への移行はこの設定だけで再構築できます。

## 14. リポジトリ運用（Git）

* リポジトリのルートは `PS2UniversalMod/` だけです。ゲームデータの置き場
  （`pcsx2/`・`sstates/`・`work/` など）はこの外にあり、親ディレクトリを `git init` してはいけません。
* コミット対象はコード・テスト・文書・アドレス/関数名/ハッシュなどの要約のみ。
  ISO・BIOS・`.p2s`・RAM ダンプ・スクリーンショット・Ghidra プロジェクトと逆コンパイル出力・
  ログは `.gitignore` で除外済みです（Git LFS でも管理しません）。
* ステージングは `git add <明示的なパス>`。`git add .` / `-A` は使いません。
* コミット前の確認: `git diff --cached --name-only`、`git diff --cached --stat`、
  `python tools/audit_repo.py`（追跡ファイルの種別・サイズ・秘密情報パターンを検査）。
* 作業は機能ブランチで行い、ベースライン（`main` の最初のコミット）は FF10-2 と
  シャイニング・フォース ネオの動作確認済み状態です。リモートの作成・push は明示指示があるまで行いません。
* 新しいゲームの追加手順は [`ADAPTER_GUIDE.md`](ADAPTER_GUIDE.md) の「Git での追加手順」を参照。
