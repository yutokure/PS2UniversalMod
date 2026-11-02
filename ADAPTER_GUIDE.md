# 新しいゲーム用アダプターの追加ガイド

`PS2 Universal Camera Controller` は「ゲーム非依存の共通基盤」＋
「ゲーム別アダプター」で構成されています。新しい PS2 タイトルを追加するとき、
書き換えるのは **アダプターとメモリマップだけ** です。

---

## 1. 共通基盤（変更不要）

| モジュール | 役割 |
|---|---|
| `core/memory_backend/pine_backend.py` | PINE によるメモリ読み書き。接続断から自動再接続 |
| `core/camera_math/orbit.py` | Orbit 計算、FOV ↔ 投影スケール変換 |
| `core/camera_runtime/engine.py` | 毎フレーム書き込みスレッド、モード管理、復帰処理 |
| `core/controller/sources.py` | XInput / キーボード / スクリプト入力の抽象化 |
| `core/config/settings.py` | ゲーム ID ごとの設定・プリセット保存 |
| `gui/camera_controller/app.py` | PySide6 GUI（`ADAPTERS` に登録するだけ） |

共通基盤にゲーム固有のアドレスは **一切埋め込まれていません**。

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

---

## 3. 手順

### 3.1 アドレスを特定する

FFX-2 で実際に使った手法（`analysis/` と `scripts/ps2lab/`）:

1. **セーブステートを4つ用意する**
   * 基準 / 時間経過のみ / キャラのみ移動 / カメラ大移動
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

* 探すのは「毎フレーム再計算されない」スケール値
  （`writecheck` で 500 ms 後も値が残るか確認）
* 見つけたら `0.8 × V` `0.9333 × V` のような**派生値が別にあるか**を確認し、
  比率が一致すればそれがマスター値
* 角度換算は `tan(fov/2) = 画面半幅 / V`。
  画面半幅の根拠を必ず記録すること

### 3.4 アダプターを登録する

```python
# gui/camera_controller/app.py
from adapters.mygame.adapter import MyGameAdapter
ADAPTERS = {"FFX2": FFX2Adapter, "MYGAME": MyGameAdapter}
```

`identify()` が一致しなければ GUI は書き込みを行いません。

---

## 4. チェックリスト

- [ ] `identify()` が Serial と CRC の**両方**を検証している
- [ ] `is_field_like()` が戦闘・イベント・ロード中を弾く
- [ ] `restore()` でゲーム本来のカメラに戻る
- [ ] 「元の値」を保存し、FOV を確実に戻せる
- [ ] 既存セーブステートを書き換えない（複製してスロット経由で使う）
- [ ] `tools/flicker_test.py` 相当のリーク率測定を行った
- [ ] `tools/e2e.py` 相当のシナリオで画面差分の証拠を残した

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

## v2 追記: 視線（注視点）フックの実装義務

v1 の「注視点は `0x340380` に直接書き込み」は**誤り**でした。`0x340380` は
プレイヤー基準点であり、描画の注視点は `0x33FC10`、実際の視線は

```
forward = normalize(注視点 - 視点)
```

で、`FUN_001b07a0`（look-at 行列ビルダ）が毎フレーム計算します。

そのため、アダプターが「視線を制御できる」と宣言する場合、次の 2 点が必要です。

1. `uses_offset_injection` 相当の**加算フィールド**（FFX-2 では `0x3403E0`）を持ち、
   視点はゲーム自身に再現させる（競合しない）。
2. 注視点は**ゲームが書かないスロット**へ読み取り先を移すコードパッチを持つ
   （FFX-2 では `0x1B07FC` の `lqc2` オフセット `0x00` -> `0x30`）。

新しいゲームへ移植するときは、まず

* 視線を作る関数（look-at ビルダ）を特定する
* その関数が読む「視点」「注視点」「up」の 3 アドレスを特定する
* 注視点アドレスが毎フレーム上書きされるか確認する（`tools/probe_revert.py` が雛形）
* 上書きされるなら、近傍の未使用スロットへ読み取り先を移せるか確認する

の順で調べてください。アダプター側の追加 API は
`read_aim()` / `write_aim()` / `restore_aim()` / `patch_active()` です。
`patch_active()` は GUI の `Look-at patch` 行に表示され、パッチ未適用を
「動かない MOD」ではなく**明示的な警告**にします。
