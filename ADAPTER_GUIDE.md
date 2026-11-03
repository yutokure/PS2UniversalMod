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

`adapters/<game>/adapter.py` に次のインターフェースを実装します。

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
- `PITCH_DISPLAY_SIGN` は内部角度から表示値への係数（±1、既定 +1）。`PITCH_INPUT_SIGN` は
  入力積分の係数（±1、既定 +1）。内部数学・保存値の意味を変えずに、表示と操作方向を合わせます。
  `PITCH_POSITIVE_IS` の説明は表示値に合わせてください。`invert_y` はこの基準に対する追加反転です。
- `accepts_look_height = True` の adapter は `write_orbit_params(..., look_height=...)` で
  設定の相対高さを受け取ります。SF Neo / Exa はこれを使い、異なるフレームのキャラクター Y と中心座標を
  引き算して移動量を高さ設定へ混入させないようにします。指定しない adapter の呼出しは従来どおりです。
- `center_on_target(distance, look_height) -> CameraPose` は任意の native 中心化境界です。
  SF Exa は出力 eye の直接上書きや scratch を使わず、原作の角度・距離・高さの入力で中心化します。
  runtime は返された pose から設定を同期し、この method が無い既存 adapter は従来の中心化を使います。

---

## 3. 手順

### 3.1 アドレスを特定する

まず ISO / Serial / CRC、既存接続・解析・ステートを確認します。以下は FFX-2 の手法の例です。
`analysis/` はリポジトリ内、`scripts/ps2lab/`・`scripts/sweep_*.py` は親ラボにあります。

1. **既存ステートを探し、不足する状態だけ用意する**
   * FFX-2 の例: 基準 / 時間経過のみ / キャラのみ移動 / カメラ大移動（4 個を毎回作る義務ではない）
2. **展開する** — `scripts/ps2lab/sstate_zip.py` で EE RAM を取り出す
   （PCSX2 2.x の `.p2s` は ZIP + ZSTD）
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

### 3.4 アダプターを登録する

```python
# gui/camera_controller/app.py（3 か所）
from adapters.mygame.adapter import MyGameAdapter
ADAPTERS = {"FFX2": FFX2Adapter, "MYGAME": MyGameAdapter}
ADAPTER_BY_GAME_ID = {"SLPS-25250": FFX2Adapter, "SLPS-00000": MyGameAdapter}   # Serial -> クラス
SUPPORTED_IDS = {"SLPS-25250", "SLPS-00000"}                                    # 対応する Serial
```

`identify()` が一致しなければ GUI は書き込みを行いません。

GUI はアダプターを `GuardedBackend`（`core/memory_backend/guard.py`）越しに動かし、`identify()` が返した Serial / CRC を約 0.25 秒ごとに再確認します。
ゲームが替わると書き込みは自動で止まり、アダプターは `restore()` なしで破棄されます。アダプターは**必ず `self.backend` 経由**で書き込んでください
（PINE のソケットや別のバックエンドを自分で持つと、この保護の外になります）。

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
| PINE はパイプライン不可 | 1 リクエストずつ送る（サーバは 1 パケットずつ read する） |
| GDB 接続は VM を止める | 解析時のみ使う。制御には PINE を使う |
| PINE のステート復元 opcode は壊れている | ステートは qPcsx2 / GDB 経由でロードする |
| 描画ウィンドウの取得が古いフレームを返す | 2 回取得して 2 枚目を使う。ノイズ床を測ってから判定する |
| カメラ制御が静止時に走らないゲームがある | 差分注入と直接書き込みの併用でカバーする |

---

## v2 追記: FFX-2 の視線（注視点）フック

以下は FFX-2 の差分注入方式の条件です。他ゲームへ同じフィールド・フックを強制せず、
SF Neo の制御値方式や幻想水滸伝V のコードケーブ方式（v3）も参照してください。

v1 の「注視点は `0x340380` に直接書き込み」は**誤り**でした。`0x340380` は
演出依存のカメラ追従点です。現行 Orbit の基準は actor `0x3312D0` + 固定 Y `+5` で、
描画の注視点は `0x33FC10`、実際の視線は

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
`patch_active()` は GUI の `Look-at patch` 行に表示され、パッチ未適用を
「動かない MOD」ではなく**明示的な警告**にします。

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

## Git での追加手順（新しいゲーム）

```bash
git switch -c feature/<game>-adapter                # main は動作確認済みベースライン
mkdir adapters/<game>                               # __init__.py / memory_map.py / adapter.py (+ caves.py)
# アドレスは memory_map.py の定数にだけ書く。共通基盤（core/）にゲーム固有値を入れない
git add adapters/<game> tests/test_<game>.py docs/games/<game>/CAMERA.md   # 明示的に指定する
git diff --cached --name-only && git diff --cached --stat
python tools/audit_repo.py --staged                  # Git インデックスの中身にゲームデータ・秘密情報・大きなファイルが無いこと
git commit -m "<Game>: camera adapter ..."
```

GUI への登録は `gui/camera_controller/app.py` の 3 か所（`ADAPTERS`・`ADAPTER_BY_GAME_ID`・
`SUPPORTED_IDS`）。解析で作ったスクリーンショット・ダンプ・Ghidra プロジェクトは
`test_evidence/`・`work/` に置き（Git 無視）、文書にはアドレス・関数名・数値だけを書きます。
