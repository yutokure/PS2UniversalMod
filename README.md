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

共通基盤（`core/`・GUI）にゲーム固有のアドレスは入れません。ゲームごとの違いは
`adapters/<game>/` に閉じています。

開発・解析を AI に依頼するときの判断基準は [`AGENTS.md`](AGENTS.md)。親ラボへの配置方法は
[`docs/README.md`](docs/README.md#agentsmd-の配置) を参照してください。

## 1. 対応ゲーム

| ゲーム | アダプター | Serial / CRC | できること | 詳細 |
|---|---|---|---|---|
| FINAL FANTASY X-2 | `adapters/ffx2` | `SLPS-25250` / `8A6D7F14` | Orbit、距離、FOV、カメラ位置・注視点オフセット、Free Camera | [`docs/games/ffx2/`](docs/games/ffx2/) |
| シャイニング・フォース ネオ | `adapters/shiningforceneo` | `SLPM-65908` / `64F241D2` | Orbit、距離、FOV、注視点の高さ、右スティック遮断 | [`docs/games/shiningforceneo/`](docs/games/shiningforceneo/CAMERA_ANALYSIS.md) |
| 幻想水滸伝V | `adapters/suikoden5` | `SLPM-66286` / `7380A572` | Orbit、距離、FOV、カメラ位置・注視点オフセット、右スティックのズーム遮断、R1 ズーム連動 | [`docs/games/suikoden5/`](docs/games/suikoden5/CAMERA.md) |

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
   - FFX-2 だけは追加条件があります: 視線の注入に `.pnach`（§5.1）が必要で、PCSX2 は再起動のたびに
     `EnableCheats` が無効に戻ります。GUI の「ゲームパッチ」欄が「適用中」になっているか確認してください。
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
3. 左スティックで歩く（歩行方向がカメラ基準になるかはゲームによる。§5）
4. 「MOD を無効化して元のカメラに戻す」または「オリジナル」で、ゲーム本来のカメラ・入力に戻ります

### 3.3 GUI 項目

画面は上から「接続」「通知バー」「カメラモード / 操作」「カメラ回転 / カメラ位置」「カメラレンズ / ゲーム標準ズーム」「デバッグ表示」です。
窓が小さいときはスクロールします（スライダー上のマウスホイールは、フォーカスがないと値を変えません）。

| セクション | 項目 |
|---|---|
| 接続 | PCSX2、ゲーム、シリアル / CRC、アダプタ、実行状態、ゲームパッチ、表示言語（日本語 / English、再起動不要）、再接続。「詳細を表示」でパッチを手動で読み込む／外すボタン |
| 通知バー | 今いちばん大事な 1 件を平易な文で表示（PCSX2 に接続できない、未対応の版、フィールドカメラが止まっている、パッチ箇所が想定外、など）。重大度で色分け |
| カメラモード | オリジナル / オービット / フリーカメラ（FFX-2 のみ）、有効化時にキャラクターを中央へ |
| 操作 | **カメラ MOD を有効化**、**MOD を無効化して元のカメラに戻す**、キャラクターを中央に、ゲームの視点に合わせ直す、プリセット（読込 / 保存） |
| カメラ回転 | Yaw、Pitch、回転速度、右スティック感度、デッドゾーン、左右反転、上下反転、入力ソース（auto / xinput / keyboard / scripted） |
| カメラ位置 | 距離、注視点の高さ。「オフセット（詳細）」を開くとカメラ X/Y/Z・注視点 X/Y/Z（0 以外があると見出しに「設定あり」と出ます） |
| カメラレンズ（FOV） | FOV（20〜110°）、上書きの適用、現在値、ゲーム値に戻す |
| ゲーム標準ズーム（対応ゲームのみ） | 現在の段階、段階ボタン、R1 でオービット距離を連動（幻想水滸伝V。連動の設定はゲームごとに保存） |
| デバッグ表示（既定で折りたたみ） | カメラ座標、プレイヤー座標、更新頻度、最終更新 |

挙動のルール:

* **起動時は必ず「オリジナル」**です。保存された設定の値は読み込みますが、MOD は自分で有効にするまで動きません。
* プリセットは**値だけ**を変え、カメラモードや表示言語は変えません。同名の保存は確認してから上書きします。
* 接続がない・未対応の版・接続が切れたときは、カメラ関連の操作がすべて無効になり、通知バーに理由が出ます。
  PCSX2 が戻れば自動で操作できるようになります。
* ゲームの実装が使えない項目は個別に無効になります（例: シャイニング・フォース ネオのオフセット、FFX-2 以外のフリーカメラ）。
* 距離・注視点の高さ・オフセット・Pitch の範囲は**ゲームごと**です（アダプターが決めます）。符号もゲームごとに違うので、
  スライダーの下に説明が出ます（FFX-2・幻想水滸伝V は「注視点の高さ: 正で下、Pitch: 正でカメラが上」、
  シャイニング・フォース ネオは「正で上、Pitch は負がカメラ上」）。
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
- ゲームは視点と注視点を毎フレーム書き戻します。そこで視点は「ゲーム自身の加算フィールド」にオフセットを書き、
  注視点は `.pnach` 1 命令で読み取り先を未使用スロットへ移して、書き込み競合そのものを無くしています。
- `.pnach` は PCSX2 側（`pcsx2\fork-B056de99\cheats\8A6D7F14.pnach`）にあり、このリポジトリには含みません。
  フック方式（ゲーム本体のカメラルーチンに軌道を渡す）のテンプレートは `patches/stock_camera_hook.pnach.txt`、
  切り替えは `python tools/stock_hook.py status|enable|disable` です。
- 歩行方向: フック方式（既定で有効）でオービットに追従します。測定は歩き始めの 0.3 秒のみで、
  長い歩行は未確認です。フックは MOD 動作中だけ正しく働くため、使い終わったら `disable` します。
- 演出カメラのあるエリア（`other_area_base`）では FOV の効果が限定的です。
- 狭い通路で 180° 回すとカメラが壁の内側に入ることがあります（ゲームの衝突判定を経由しないため）。
- 実装メモ・測定値: [`docs/games/ffx2/ADAPTER_NOTES.md`](docs/games/ffx2/ADAPTER_NOTES.md)

### 5.2 シャイニング・フォース ネオ
- カメラの角度（yaw/pitch）・距離・注視点の高さはゲームのフィールドに書き、場所依存のスクリプトカメラ（町の門など）は
  平滑化ゲートの 1 バイトで止めます。FOV と右スティック遮断はコードケーブです。
- カメラ位置・注視点の X/Z オフセットは効きません（注視点の高さのみ）。
- 既知: オービットを戻した直後のカメラ向きは、ゲームが決めるため元の向きと一致しません（既存の挙動）。
- 解析記録: [`docs/games/shiningforceneo/CAMERA_ANALYSIS.md`](docs/games/shiningforceneo/CAMERA_ANALYSIS.md)

### 5.3 幻想水滸伝V
- フィールドカメラ更新（`FUN_00243E10`）の出力処理にコードケーブを差し込み、注視点・距離・ピッチ・ヨー・FOV を上書きします。
  歩行方向はゲームが読むヨーに従うので、**左スティックの進行方向もカメラ基準**になります。
- 原作のカメラは固定角で、右スティックはカメラ回転ではなく**3 段階ズーム**に使われています（R1 も同じズーム、距離 400 → 300 → 200）。
  オービット中は右スティックを MOD が使い、ゲーム側のスティックズームは遮断します。R1 は生きていて、
  「ゲーム標準ズーム」欄のチェックを入れると R1 の段階に合わせてオービット距離も変わります。
- 場所依存のカメラ（ピッチが 13° → 40° に変わる坂など）はオービット中は無視され、マップ移動後も設定が再適用されます。
- オフセットはワールド座標で、リグ全体を動かします。近いズーム段階ほど画面上で大きく見えます。
- 未検証: イベント・戦闘・メニュー（カメラ更新が止まるので MOD は手を出しません）。
- 解析記録とテスト結果: [`docs/games/suikoden5/`](docs/games/suikoden5/)

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
| カメラが動かない | フィールドにいるか確認（戦闘・イベント・ロード中は自動で無効） |
| カメラが元に戻らない | 「MOD を無効化して元のカメラに戻す」を押す。それでも戻らなければゲームを再開 |
| PCSX2 を再起動した | GUI は自動で復帰します（設定は保持）。FFX-2 は `EnableCheats` を再度有効にし、「ゲームパッチ」欄を確認 |
| セーブステートを読み込んだ | MOD のコードパッチが消えますが、約 0.2 秒（FFX-2・SF Neo は約 1 秒）で自動再適用されます |
| 右スティックが効かない | パッドが XInput（Xbox 系）で認識されているか、「入力ソース」が keyboard / scripted になっていないか確認。矢印キーでも回せます |
| 左スティックの向きがカメラと合わない | FFX-2 はフック方式（§5.1）を有効にする。幻想水滸伝V ではカメラ基準になります。SF Neo は未対応 |
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
│  ├─ ffx2/                         memory_map.py（アドレス）、adapter.py
│  ├─ shiningforceneo/              + fov_cave.py、pad_cave.py
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
  `main` には 3 ゲームのアダプターと GUI 修正・ゲーム切替ガードが統合済みです（PR #1）。
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
