# 新しいゲーム用アダプターの追加ガイド

`PS2 Universal Camera Controller` は「ゲーム非依存の共通基盤」＋
「ゲーム別アダプター」で構成されています。新しい PS2 タイトルを追加するとき、
ゲーム固有の処理は **アダプターとメモリマップ** を中心に追加し、既存 GUI へ登録します。
必要な共通インターフェース改善は既存ゲームへの影響を評価して行い、構造の無理な統一はしません。
作業範囲・検証の選択・文書更新の判断基準は [`AGENTS.md`](AGENTS.md) を参照してください。

---

## 1. 共通基盤（既存を再利用）

| モジュール | 役割 |
|---|---|
| `core/memory_backend/pine_backend.py` | PINE によるメモリ読み書き。接続断から自動再接続 |
| `core/camera_math/orbit.py` | Orbit 計算、FOV ↔ 投影スケール変換 |
| `core/camera_runtime/engine.py` | 毎フレーム書き込みスレッド、モード管理、復帰処理 |
| `core/controller/sources.py` | XInput / キーボード / スクリプト入力の抽象化 |
| `core/config/settings.py` | ゲーム ID ごとの設定・プリセット保存 |
| `gui/camera_controller/app.py` | PySide6 GUI（`ADAPTERS`・`ADAPTER_BY_GAME_ID`・`SUPPORTED_IDS` の 3 か所に登録） |

設計方針として、ゲーム固有の処理・アドレスは原則 `adapters/<game>/` へ分離します。
ただし、現在の共通エンジン（[`core/camera_runtime/engine.py`](core/camera_runtime/engine.py)）には、
FFX-2（FF10-2）由来の FOV 同期確認用フォールバックが残っています。
アダプターに呼び出し可能な `fov_in_sync()` がない場合、`0x340B00` を読み取って同期を確認します。
新しいゲームを追加するときは、共通基盤（`core/`・GUI）へ新たなゲーム固有アドレスを持ち込みません。

---

## 2. アダプターが実装するもの

以下は FFX-2 のメソッドを参考にした読み書きの例です。全ゲーム共通の抽象基底クラスではありません。たとえば[ツクール5のアダプター](adapters/rpgmaker5/adapter.py)は固定の視点・注視点を直接書かず、`write_orbit_params()` を使います。新しいゲームでは[共通エンジン](core/camera_runtime/engine.py)と GUI が実際に使う経路、`features` と復元処理を確認してください。

```python
class MyGameAdapter:
    name = "MYGAME"
    CAM_EYE_ADDR = ...          # 視点（書き込み先）
    CAM_TARGET_ADDR = ...
    uses_offset_injection = False   # True なら差分注入方式を利用

    def identify(self) -> AdapterInfo: ...
    def read_scene(self) -> SceneState: ...
    def read_player(self) -> Vec3: ...
    def read_game_pose(self) -> CameraPose: ...
    def read_fov_deg(self) -> float: ...
    def write_fov_deg(self, deg: float) -> None: ...
    def restore_fov(self) -> None: ...
    def capture_original_fov(self) -> float: ...
    def write_pose(self, pose: CameraPose) -> None: ...
    def is_field_like(self, scene: SceneState) -> bool: ...
    def heartbeat_addr(self) -> int: ...
```

`SceneState` / `AdapterInfo` は `adapters/ffx2/adapter.py` の定義を
そのまま import して構いません（共通化候補）。

任意の座標系・制御値境界（既定では既存ゲームの挙動を維持）:

- `PITCH_RANGE = (lo, hi)` は内部角度の可動域。指定時は GUI・右スティック双方が優先し、
  古い保存値・プリセットの範囲では上書きしません。GUI は範囲外の読込角度を補正します。
- `FOV_RANGE = (lo, hi)` は任意の水平 FOV 境界（度）。GUI はスライダーだけでなく、接続時の保存値と
  プリセット読込値を runtime・保存設定の両方で補正します。未指定は従来の `20..110` 度です。
  adapter の `write_fov_deg()` / `fov_in_sync()` も同じ境界を使い、GUI 外からの要求を制限してください。
  グランディアIIの現行範囲も `20..110` 度です。旧3hook版では100度のnative packet buffer fatalを受け `20..60` 度に制限していました。
  現行7site版はclosed payload入口で事前reserveし原作bank内で分割送信します。容量拡張・上限検査の迂回ではなく、全scene安全保証でもありません
  （[Grandia IIのpacket方式・前提](<docs/games/grandia2/CAMERA.md#packet-streaming--2mibを拡張せず事前reserveする>)、[今回結果](<docs/games/grandia2/TEST_RESULTS.md#現行追記--7siteg2c2packet-streaming-2026-11-07>)）。
- `PITCH_DISPLAY_SIGN` は内部角度から表示値への係数（±1、既定 +1）。`PITCH_INPUT_SIGN` は
  入力積分の係数（±1、既定 +1）。内部数学・保存値の意味を変えずに、表示と操作方向を合わせます。
  `PITCH_POSITIVE_IS` の説明は表示値に合わせてください。`invert_y` はこの基準に対する追加反転です。
- `accepts_look_height = True` の adapter は `write_orbit_params(..., look_height=...)` で
  設定の相対高さを受け取ります。SF Neo / Exa はこれを使い、異なるフレームのキャラクター Y と中心座標を
  引き算して移動量を高さ設定へ混入させないようにします。指定しない adapter の呼出しは従来どおりです。
- 原作だけが注視点の高さを決める場合は `features["look_height"] = False` とします。GUIは高さを無効にし、保存設定・プリセットの高さも0に補正します（未指定は従来どおり）。
  Orbit中だけFOVを変更できる場合は `features["fov_requires_orbit"] = True` でGUIの説明を切り替えます。これは表示用で、書込み条件は[アダプター側](adapters/rpgmaker5/adapter.py)でも照合します。
- `accepts_orbit_offsets = True` は `write_orbit_params(..., pos_offset=Vec3, target_offset=Vec3)` で
  独立したeyeオフセットと、`look_height + target_offset.y` を含む相対注視点を受け取ります。
  ドルアーガはguest内で最新actor位置を加算し、別frameのactorを引き算して移動量を混入させません。
  既存の `accepts_pos_offset` / `accepts_look_height` 経路の契約は変えません。
- `center_on_target(distance, look_height) -> CameraPose` は任意の native 中心化境界です。
  SF Exa は出力 eye の直接上書きや scratch を使わず、原作の角度・距離・高さの入力で中心化します。
  runtime は返された pose から設定を同期し、この method が無い既存 adapter は従来の中心化を使います。

---

## 3. 手順

### 3.1 アドレスを特定する

まず ISO / Serial / CRC、既存接続・解析・ステートを確認します。以下は FFX-2 の手法の例です。
[FFX-2 の差分解析](analysis/savestate_diff/run.py)は公開ソースに含まれますが、特定の4ステート名と親ラボの入出力配置を前提とします。以下の `scripts/ps2lab/`・`scripts/sweep_*.py`、入力ステート、実測画像は同梱していません。これは[当時の親ラボ](docs/lab/README.md)での絞り込み例で、チェックアウトだけで実行できるコマンド一覧ではありません。

1. **既存ステートを探し、不足する状態だけ用意する**
   * FFX-2 の例: 基準 / 時間経過のみ / キャラのみ移動 / カメラ大移動（4 個を毎回作る義務ではない）
2. **展開する** — 親ラボでは `scripts/ps2lab/sstate_zip.py` で EE RAM を取り出した。当時の FFX-2 ステートは ZIP 内のデータが Zstandard 圧縮された形式で、全ビルドの `.p2s` を同じ方法で読めるわけではない。
3. **ノイズを除去する** — 「時間経過のみ」でビット一致する値だけ残す
4. **署名で分類する** — カメラだけ動いた状態で大きく変化する値を候補に
5. **実画面スイープで確定する** — `scripts/sweep_camera.py` /
   `scripts/sweep_range.py` で候補を実際に書き換え、
   描画ウィンドウのピクセル差分で判定する
   （ノイズ床は `tools/capture_stability.py` で測る。FFX-2 では 1.5 %）

> 「変化したアドレスを全部見る」だけでは 50 万バイト規模になり機能しません。
> 必ず 4→5 の実画面検証まで行ってください。

### 3.2 書き込み方式を選ぶ

| 方式 | 条件 | ちらつき |
|---|---|---|
| **差分注入**（推奨） | ゲームが `出力 = A + B` を毎フレーム計算し、`B` を外部から書ける | なし（決定的） |
| 直接上書き | 上記が無い場合。描画直前に間に合えば反映 | 出ることがある |

差分注入が見つかるかどうかは、**書き込みウォッチポイント**で
「出力を書いている命令」を捕まえ、その直前のオペランドを
Ghidra で逆コンパイルすると分かります（FFX-2 の `FUN_001b0008` が実例）。

直接上書きしか無い場合は、`tools/flicker_test.py` でリーク率を必ず測ってください。
10 % を超えるならゲーム側の更新タイミングを再調査したほうが良いです。

### 3.3 FOV を特定する

FFX-2 の投影スケールを調べた例（他ゲームでは投影行列・更新関数を調べる）:

* 探すのは「毎フレーム再計算されない」スケール値
  （`writecheck` で 500 ms 後も値が残るか確認）
* 見つけたら `0.8 × V` `0.9333 × V` のような**派生値が別にあるか**を確認し、
  比率が一致すればそれがマスター値
* 角度換算は `tan(fov/2) = 画面半幅 / V`。
  画面半幅の根拠を必ず記録すること

SF Neo は view-projection のスケーリング、幻想水滸伝V は更新関数の FOV 引数を使います。
SF Exa は原作の垂直角制御フィールドを使い、aspect で水平 FOV へ換算します。ネオに似た
エンジンでも cave 不要の入力経路を別途確認しました。全ゼロの領域でも静的 pool の内部なら
cave に使えません（イクサで実例あり）。同じ数式や永続値を前提にせず、実投影と描画への効果を
確認します（各 `docs/games/` 参照）。

イノセントライフでは描画用cameraコピーのfocalを元builderへ渡し、投影・clip副行列を一括再生成します。
水平FOVは `2*atan(256/(focal*X倍率))`。半幅256は512×448初期化と正規化投影の分母で確認し、
表示アスペクト補正後のスクリーンショット幅は使いません。native cameraを保持するため、解除はコピーの上書きflagを落とし、
その時点の原作値から再生成します。旧値の直接書戻しは不要です（[解析](docs/games/innocentlife/CAMERA.md#fov--校正と投影経路)）。

### 描画packet予算と解除境界 — Grandia IIの実例

広角で増える可視geometryを扱う場合、FOV数値の読戻しだけではpacket安全性を確認できません。
Grandia IIではnative END生成後の2MiB検査が遅く、bank0/1が隣接し直後に管理globalがあるため、
容量定数・fatal分岐を変更するbypassや無根拠なbuffer拡張は使いません。

- 現行版はclosed DIRECT／UNPACK／CONTROL入口をhookし、各payloadを開く前にprotocol上限＋終端等の余裕をreserveします。
  使用量はraw putから固定bank baseを引きます。open payload内でのflush、queue／projection cacheの消去、描画順序変更はしません。
- 原作のEND→finalize→FlushCache→send→reset→newCNTを使い、CPU側VU indexも戻します。
  DIRECTには別CNT境界を追加し、bank容量とは別のDMA tag 16-bit QWC制約も守ります。
  valid native field writerのprotocolとsource boundsが前提で、破損・任意巨大DIRECTを有効化する仕組みではありません。
- leaf入口をhookしてnative helperを追加callする場合、C ABIの下位64bitだけでは不十分です。
  R5900のfull128bit user GPR、HI／LO／HI1／LO1／SA、全FPU registerとFCSRを保持し、kernel k0/k1は触りません。
  no-flush CONTROL／UNPACKのhot pathは使用するscratchだけを保存し、full-save callが必要な経路と分離します。
- queue構築tailは最終geometry送信前です。解除はframe submit帰還後まで待ち、現行の全7siteをguestで復元します。
  first one-word bootstrap、GuardedBackend、hot全7exact確認と周期full auditは維持します。
  magicはG2C2へ更新し旧G2C1混在をfail-closedにします。旧adapterを正常解除して終了し、さらにstock state読込みかゲーム再起動で旧cave/controlを消してから新版へ切り替えます。
  正常解除だけでは旧G2C1が残り新版は拒否します。MOD入りstateはstockではなく、clean stockがなければ再起動します。pause中のACKは不能です。

具体的なsite／5 resources・conditional empty/exact所有は[Grandia IIの安全条件](<docs/games/grandia2/CAMERA.md#所有適用解除と安全>)、
実測と未網羅範囲は[検証記録](<docs/games/grandia2/TEST_RESULTS.md>)を参照してください。他ゲームに同じnative protocolを仮定しません。

### 3.4 アダプターを登録する

[GUI の登録表](gui/camera_controller/app.py)に新クラスの import を追加し、**既存エントリを残して**次の3か所に追記します。以下の名前と Serial は説明用です。

| 追記先 | 追加する項目の例 |
|---|---|
| import 群 | `from adapters.mygame.adapter import MyGameAdapter` |
| `ADAPTERS`（名前 → クラス） | `"MYGAME": MyGameAdapter` |
| `ADAPTER_BY_GAME_ID`（Serial → クラス） | `"SLPS-00000": MyGameAdapter` |
| `SUPPORTED_IDS`（対応 Serial の集合） | `"SLPS-00000"` |

Serial はクラスを選ぶためのキーです。`identify()` で Serial と CRC の**両方**が一致して初めて書込みを許可します。[GuardedBackend](core/memory_backend/guard.py) は、確認済みの接続世代に限り、再確認まで最長 0.25 秒の書込みを許可します。ゲーム切替を瞬時に検知する仕組みではありません。

別ゲームを検出したら旧アダプターを `restore()` せず破棄します。復元も書込みなので、切替後のゲームには行いません。すべての書込みには **`self.backend`** を使い、独自の PINE ソケットでガードを迂回しないでください（[ガードの仕様](docs/gui/GAME_IDENTITY_GUARD.md)）。

---

## 4. チェックリスト

安全・復元は実装条件です。試験は依頼と変更リスクに必要な範囲を選び、全件の自動実行義務とはしません。
局所確認を先に行い、PCSX2・複数ゲーム・長時間などは必要時に追加します（`AGENTS.md`「検証を選ぶ」）。

- [ ] `identify()` が Serial と CRC の**両方**を検証している
- [ ] 書き込みはすべて `self.backend` 経由（ゲーム切替ガードの対象にするため）
- [ ] `is_field_like()` が戦闘・イベント・ロード中を弾く
- [ ] 同一ゲームと確認できるときに原作へ復帰できる（ゲーム切替・識別不能時は `restore()` せず破棄）
- [ ] 「元の値」を保存し、FOV を確実に戻せる
- [ ] 既存セーブステートを書き換えない（複製してスロット経由で使う）
- [ ] 競合・ちらつきの確認が必要なら `tools/flicker_test.py` 相当をそのゲームに合わせて実行
- [ ] 実画面の検証が必要なら `tools/e2e.py` 相当やゲーム別ツールで証拠を残し、未実行と区別

---

## 5. 既知の落とし穴

| 落とし穴 | 対策 |
|---|---|
| PINE の連続書込みを1回の不可分な更新とみなす | 現行の [PineBackend](core/memory_backend/pine_backend.py) は float 配列も1語ずつ順に送る。複数語の一貫性が必要ならゲーム側で判定する |
| 解析用 GDB に接続すると VM が停止することがある | 進行状態を確認する。通常の GUI 制御には PINE を使う |
| 親ラボのフォークでは PINE のスロット保存要求が失敗した | 当時は qPcsx2 で保存・復元を確認した（[KB-11](docs/lab/TROUBLESHOOTING_KB.md#kb-11--pine-savestate-command-returns-0xff)）。全 PCSX2 版の制限や GUI の必須手順ではない |
| 描画ウィンドウの取得が古いフレームを返す | 2 回取得して 2 枚目を使う。ノイズ床を測ってから判定する |
| カメラ制御が静止時に走らないゲームがある | 差分注入と直接書き込みの併用でカバーする |

---

## FFX-2 の視線（注視点）フック

以下の v1・v2・v3 は開発段階を区別する当時の呼称で、公開版のタグやブランチではありません。ここでは FFX-2 の差分注入方式を扱います。他ゲームへ同じフィールド・フックを強制せず、
SF Neo の制御値方式や幻想水滸伝V のコードケーブ方式（v3）も参照してください。

v1 の「注視点は `0x340380` に直接書き込み」は**誤り**でした。`0x340380` は
演出依存のカメラ追従点で、actor 座標でも描画の注視点でもありません。現行の `read_player()` は actor `0x3312D0` を基準とし、ロード中など原点付近を除いて Y に `+5` を加えます。原作カメラの読み取りは `CAM_EYE_BASE` と `CAM_AIM`（`0x33FC10`）です。フックが有効なメイン描画では注視点の読み先を専用スロット `CAM_AIM_SLOT`（`0x33FC40`）に切り替えます。いずれも実際の視線は

```
forward = normalize(注視点 - 視点)
```

で、`FUN_001b07a0`（look-at 行列ビルダ）が毎フレーム計算します。

そのため、FFX-2 のこの方式で「視線を制御できる」と宣言する場合、次の 2 点が必要です。

1. `uses_offset_injection` 相当の**加算フィールド**（FFX-2 では `0x3403E0`）を持ち、
   視点はゲーム自身に再現させる（競合しない）。
2. 注視点は**ゲームが書かないスロット**へ読み取り先を移すコードパッチを持つ。
   FFX-2 はメイン呼出 `0x1AE0F0` に条件付き cave を挟み、出力・eye・target のポインタが
   メインカメラと一致した場合だけ target を `0x33FC40` へ向けます。
   旧 `0x1B07FC` の `lqc2` 一律 `+0x30` はミニマップ等も壊したため廃止しました。
   共有 builder を変更する前に、他の呼出元・補助カメラへの影響を分離してください。
   [修正・確認範囲](<docs/games/ffx2/CAMERA_MEMORY_MAP.md#ルカのミニマップ-共有-look-at-ビルダへの副作用>)。

新しいゲームへ移植するときは、まず

* 視線を作る関数（look-at ビルダ）を特定する
* その関数が読む「視点」「注視点」「up」の 3 アドレスを特定する
* 注視点アドレスが毎フレーム上書きされるか確認する（`tools/probe_revert.py` が雛形）
* 上書きされるなら、近傍の未使用スロットへ読み取り先を移せるか確認する

の順で調べてください。アダプター側の追加 API は
`read_aim()` / `write_aim()` / `restore_aim()` / `patch_active()` です。
`patch_active()` は FFX-2 の注視点フックが完全かを調べます。GUI のパッチ状態行は別の `patch_state()` を読み、原作状態・適用・部分適用・不明を区別します。通常の GUI 操作で外部 `.pnach` を用意する必要はありません。

---

## v3 追記: ゲーム内のカメラ更新に「コードケーブ」を差し込む方式

FFX-2（差分注入）、シャイニング・フォース ネオ（角度フィールド＋ゲート）、幻想水滸伝V の
3 本で、ゲームごとにカメラの作りが異なることがわかりました。移植時は次の順に判断します。

1. **カメラの更新関数を特定する**（書き込みウォッチポイントのバックトレース → Ghidra）。
   外部から書いた値が 1 フレームで戻るなら、そのアドレスは出力であって入力ではありません。
2. 更新関数が **入力（角度・距離・注視点・FOV）を出力へコピーする箇所**を探す。
   幻想水滸伝V では `FUN_00243E10` の 8 個のストアがそれでした。
3. その区間を **2 ワードのジャンプ**（`j cave; nop`）で置き換え、ケーブ内で同じストアを再現する。
   ケーブは MOD ブロック（フラグ・上書き値・ハートビート・ゲーム本来の値・オブジェクトポインタ）を
   読み書きする。フラグが全部 0 のときはゲームと同じ値を書く（実機で「何も変わらない」ことを確認）。
4. 入力の競合（原作の右スティック機能など）は、**その入力を読む関数の入口**に小さなケーブを置き、
   フラグ中だけ読まれるバイトを中立値にする。
5. アダプターは `core/mips_asm.py` でケーブを組み立て、`caves.py` に compare-and-swap の
   install/uninstall を持たせる（未知のワードが入っていたら例外・上書きしない）。
6. 実機確認が必要なときは `tools/su5_*_check.py` が雛形: 単体（PINE）→ エンジン → 実入力 → エリア遷移 →
   GUI → 長時間から必要な段階を選ぶ。実行した段階で「ゲームの値が実際に変わったか」を読み戻す。

ケーブ領域は、ELF と全セーブステートでゼロだった連続領域から選び、重ならないことをテストで検査します
（`tests/test_suikoden5.py`）。

## ゲーム内時計停止の任意境界

イノセントライフ追加（2026-11-07）で、カメラとは独立した時計専用レーンを追加しました。
`features['game_time_pause'] = True` の adapter は `set_time_paused(bool)` を実装し、既知命令・所有を検証して適用／解除と読戻しを行います。
任意の `read_game_time() -> str` と `time_paused() -> bool` は GUI の StatusPoller が読みます。
未対応 adapter は feature を宣言せず、GUI では理由付きで無効になります。

- `CameraSettings.pause_game_time` はセッション中の明示的な選択だけです。AppSettings・プリセットへ保存せず、起動・再接続時は必ず false。
- runtime は Original／Orbit・カメラ場面判定と独立に最大4Hzでサービスし、失敗は時計専用エラーとして表示、1秒後から再試行します。
- Original ラジオは `restore(release_game_time=False)`、無効化ボタン・正常 teardown は既定の `restore()` で時計も解除します。
  カメラ復元の失敗で時計解除を飛ばさないよう独立して処理します。
- ゲーム切替・識別不能時の `abandon()` は時計も含め書込み禁止。すべて adapter の `self.backend` 経由で、独自接続を追加しません。
- 実際の時計値ではなく表示だけを止める、VM・入力・全アニメーションを止める、停止時間を解除時にまとめて加算する実装を時計専用停止と呼ばないでください。
  睡眠・イベント等の時刻設定まで止めるかはゲーム別仕様とし、未検証の対象を保証しません。

FOV 非対応は `features['fov'] = False` で GUI のスライダー・上書き・リセットを無効化します。
未校正なら現在値を捏造せず、`read_fov_deg()` は0を返して未取得表示にします。

## 独立したゲーム固有スイッチ

マグナカルタ追加で `features['wide_view_running']` / `features['no_encounters']` と
`set_wide_view_running(bool)` / `set_no_encounters(bool)`、readback getters
`wide_view_running()` / `no_encounters()` を追加しました。
アドレス・原作復元・パッチ所有検証は adapter の責務で、共通runtimeにゲーム固有アドレスを追加しません。

- `CameraSettings` の同名boolは session-only。`SESSION_ONLY_SETTINGS` に集約し、AppSettings・preset・adapter defaultsから保存/復元しません。
- 2レーンは Original/Orbit・camera scene guard と独立して最大4Hz、失敗時1秒後retry。片方の失敗で他方を停止しません。
- Original は `restore(release_game_time=False, release_game_toggles=False)`、無効化・正常終了は既定の `restore()` で全解除。
- adapter の camera cleanup は独立toggleを暗黙解除しないこと。game switchの `abandon()` は書込み禁止です。
- setterが部分適用で失敗した場合もruntimeは解除責任を保持します。readback/errorはGUIで独立表示。
- 未対応gameはfeatureを宣言せず理由付き無効。マグナカルタのno-encountersは丸枠も非表示、wideだけでは隠しません。

## Git での追加手順（新しいゲーム）

例の `mygame` は実際のゲーム名に置き換えます。チェックアウトのルートで、作業開始時のブランチと変更を確認します。以下は新規アダプターをコミットする場合の例で、解析成果物を一括追加する手順ではありません。

```powershell
git status --short --branch
git switch -c feature/mygame-adapter
# 実装・検証・文書更新後。関連して変更したパスだけを列挙する
git add -- adapters/mygame gui/camera_controller/app.py tests/test_mygame.py docs/games/mygame/CAMERA.md
git diff --cached --name-only
git diff --cached --stat
python tools/audit_repo.py --staged
# ステージの内容を確認し、監査に成功した場合だけコミットする
git commit -m "MyGame: camera adapter"
```

ゲーム固有アドレスは `adapters/mygame/` に置き、共通基盤に加えません。ステート、スクリーンショット、ダンプ、Ghidra プロジェクトは Git 管理外に保管し、文書には検証条件、アドレス・関数名・数値、確認できなかった範囲を残します。
