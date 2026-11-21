# シャイニング・フォース イクサ — 解析とアダプター

対象: **日本版 SLPM-66646 / CRC 8B383FDF**、PCSX2 fork-B056de99。解析・実測日: **2026-11-03**。
Serial と CRC は起動中 VM と PINE の双方で確認した。他版は未対応。

実装: [adapter.py](../../../adapters/shiningforceexa/adapter.py)、
[memory_map.py](../../../adapters/shiningforceexa/memory_map.py)。
[検証結果と未確認範囲](TEST_RESULTS.md)。すべて EE physical offset。

## 1. 「ネオに近いエンジンか」という仮説の結論

カメラの構造・角度単位・投影ロード処理に強い共通性がある。ただし、**アドレスだけの置換ではない**。
ネオの adapter を継承して module-global memory map を差し替えるような移植はしていない。

| 項目 | ネオ | イクサで得た証拠・差異 |
|---|---|---|
| camera layout | eye+0、focus+10、view+20、VP+60、距離+184、yaw+188、pitch+18A、高さ+158 | 4 ステート差分・eye/yaw watchpoint・Ghidra と実機制御で同じ offset を確認 |
| camera allocation | `01104900` | `010FE800`、active pointer `00451144` を確認。未知の allocation は書込拒否 |
| actor position | actor+510 | **actor+520**。`001DAB38` で実 actor `00C65880` を観測。毎回 actor pointer `00451140` を読む |
| 提供 base の距離／高さ | 2000／100 | **1000／250**。同じイクサ内でも隣室では 2000／100 と変わる |
| yaw / pitch | signed short、65536/turn、eye yaw=field+180° | 同じ式。base yaw=0、pitch=−364（eye yaw180°、pitch−1.9995°） |
| yaw 等の平滑化 | gate で制御 | 別の block/gate。イクサでは同一関数が距離・高さ・FOV も publish |
| FOV | VP を cave で拡縮 | **原作の垂直角入力 +18E** を直接使える。aspect で水平 FOV に換算。cave 不要 |
| 右スティック | 汎用 copy loop の cave | **pad 専用 RX/RY load 2 命令**の局所置換。raw / left / buttons を残す |
| VP loader | `001AA080` | `001AC4A0` の128 bytesがネオと一致。call 周辺32命令は relocation 等を正規化すると32/32一致 |

エンジン全体が同一であると証明したわけではない。上表はカメラ・入力・投影の調べた範囲の結論。

## 2. 発見方法と根拠

提供された `base`、`base_only_wait`、`base_chara_move`、`base_chara_and_cam_move` を
原本に書き込まず展開。待機で不変かつ移動／カメラ変更で変わる正規直交 view 行列を抽出した。

- view `010FE820` の直前に eye `010FE800` と focus `010FE810` が存在。
- base eye `(-908.983,223.781,-1056.751)`、focus `(-908.983,188.890,-57.360)`、距離 ≈1000。
- yaw write watchpoint `010FE988` → **`001DACDC: sh a0,188(v1)`**。
  backtrace: `001DACD0 ← 00295AC0 ← 00295CF0`。
- eye write watchpoint `010FE800` → **`001D9ECC`** in **`001D9DA0`**。
- focus source **`001DAAD0`** は actor `+520/+524/+528` と高さ `camera+158` を使い、
  **`001DB6C0 / 001DB7C0`** の平滑化を経由する。
- **`00295C80`** は state block **`004D29C0+16`** が非ゼロのとき publish を許す。
- gate を0、yaw90°／pitch−30°／距離1200／高さ300に設定後、実 eye/focus から
  yaw90.000°、pitch−29.998°、距離1199.9999、focus.y=actor.y+300を確認。実画面も回転した。

## 3. 使用する制御フィールド

| 項目 | アドレス | 型・意味 |
|---|---|---|
| active camera pointer | `00451144` | u32、`010FE800` と一致する必要あり |
| actor pointer | `00451140` | u32、妥当なEE RAM範囲・16-byte alignmentを確認 |
| actor anchor | `actor+520` | float xyz、focusの書換えから独立 |
| eye / focus | `010FE800` / `010FE810` | float xyz、**読むだけ** |
| mode / focus source | `010FE940` / `010FE944` | mode0/1、party source0のみ受理 |
| height | `010FE958` | float、実装は基準250+GUI相対高さ |
| distance | `010FE984` | float |
| yaw / pitch | `010FE988` / `010FE98A` | signed halfword、1回のu32書込で両方publish |
| vertical FOV | `010FE98E` | halfword、65536 units / 360° |
| smoothing gate | `004D29D6` | byte、stock1／MOD0。隣接byteを保つRMW |
| VP | `010FE860` | 描画側の4×4行列。**読むだけ** |

mode0/1・party source0の dispatch は Ghidraで確認した。固定／遷移／スクリプトmode2..5や
他actor sourceは拒否する。focus の高さが actor+height と一致するかは guard にしない。
階段等で原作の平滑化が遅れるためで、ネオの過去障害と同じ落とし穴を避ける。

actor が0になるロード中は書込を控える。7秒の歩行で実際に隣室へ遷移し、ロード中83サンプルを拒否、
復帰後は同じ camera allocation と有効 actor を再受理した。ただし、この判定だけで全イベントを識別できるわけではない。

## 4. FOV: 投影元を制御する

**`001DAD30`** は `camera+18E` に角度を書き、controller が `+A2` へコピー。
**`001ABD70`** が view と投影を作り、**`001ABE98`** の `jal 001AC4A0` が VP を VU へロードする。
実 breakpoint の `a0=010FE860` を確認した。この共有callは変更しない。

`camera+AC` の aspect（提供状態は640/448）を用い、GUI の水平 FOV `h` を
原作の垂直 FOV `v` に換算する。

```text
v = 2 * atan(tan(h/2) / aspect)
input = round(degrees(v) * 65536 / 360)
sx = norm(VP column 0 xyz)
measured horizontal FOV = 2 * atan(1 / sx)
```

`+18C` のrollと同じu32にあるため、下位halfwordを保って上位halfwordだけ変更する。
FOV成功判定はcontrol値や `+A2` mirrorだけでなく、**実VPの列ノルムと描画**を使う。
40／60／90°は各々39.9988／59.9994／89.9988°、GUI80°は80.0016°を測定した。

アダプターでFOVだけを書き込む場合も、同じ平滑化ゲートを止める必要があり、原作が場所に応じてカメラを更新する処理は止まる。これはGUIの独立モードではない。GUIでOriginalを選ぶとFOVを復元し、Originalのままスライダーを変更しても画角は変わらない。

## 5. 右スティック: 入力専用2命令

**`001AD810`** は2ポートをstride180で処理し、`001AD590 → 001AD240` へ入る。
raw packet は `0049361A / 0049369A`、RX/RYは各+4/+5、中立127。
raw RX read watchpointで `00123C6C`、a1=`0049361E`、destination=`00493766`、
pad SDK `0011BF80 ← 001AD240` の実呼出を確認した。

| 場所 | stock | Orbit中 |
|---|---|---|
| `001AD27C` | `lbu v0,166(s3)` / `92620166` | `addiu v0,zero,127` / `2402007F` |
| `001AD290` | `lbu v0,167(s3)` / `92620167` | 同上 |

両箇所を先に検査し、どちらかが未知なら**1語も書かない**。既知のstock／MOD混在は再適用・復元可能。
ゲームが見るprocessed RX/RY `00493748/+1` は127、raw RXは255のまま。
左軸のload `001AD298 / 001AD2A0` とbuttonの組立は変更しない。

Orbitで遮断、Original／通常終了で復元。右軸から作られる派生方向bitも中立になる。
録画／再生には `001AD070` へ別処理があり、この経路は未対応・未検証。
Orbit中はメニューでも入力パッチが残る。scene guardに落ちただけでは右入力が自動復帰しないため、
メニューで原作の右入力が必要ならOriginalへ戻す。

## 6. マップ連動

同じ場所でGUI yawを180→90°に変更し、実カメラ角と画面を比較。
Nが上→右、Wが左→上となり、地形・方位が90°連動した。これは**原作の連動処理**で、
MODでマップへ別yawや位置を注入していない。FOV変更でもマップの円／方位の大きさは維持した。
マップ固有関数までは確定していない。yaw getterの参照にはbillboard処理もあり、それをマップ関数とは呼ばない。

## 7. 適用・復元・ロードと安全

- Serial+CRC、GUI GuardedBackend、接続世代・ゲーム切替の既存保護を使用する。
  別ゲームの旧adapterはrestoreしない。identity leaseの検出時間窓は既存仕様のまま。
- Orbit／FOVがgateを共有。両方offになったらgateを返す。
- Orbit前のyaw/pitch・距離・高さを保存。復元時は「最後に自分が書いた値」のままのものだけ戻し、
  新sceneの未知の値を強制復元しない。FOVもhalfword単位で所有値を比較しrollを保つ。
- stock stateがgateを1に戻したら、その状態の元値を新たな復元基準とし、約1秒の再確認で
  回転・距離・高さ・padを再適用する。FOV処理が先にgateを閉じる順序でもOrbitを再publishする。
- GUIの中心化は任意adapter境界 `center_on_target(distance, look_height)` を使い、
  eye出力の競合書込や架空のscratch領域を避ける。他adapterは従来の経路を使う。
- FOV source・2命令以外の投影／入力コードを変えず、**コードケーブは一切使わない**。
  ELFと4ステートでゼロだった `003BC600` は32要素pool内部で、初期化／解放で4700 bytesをclearする。
  「全ゼロだから空き」という仮説を棄却し、この領域もネオのcaveアドレスも使用しなかった。

通常終了でカメラを返すことと、途中で場面が切り替わった場合の**完全に同じ角度への復帰**は別。
隣室への遷移でnative値が変わるため、元の拠点値を無条件に書き戻さない。詳細は検証記録へ。
