# ラジアータ ストーリーズ — camera 解析とアダプター

対象: **日本版 SLPM-65800 / CRC AC73005E**。解析・初期実測日: **2026-11-03**。
Serial と CRC の両方を照合する。他地域版・別 CRC は未対応。

実装: [adapter.py](<../../../adapters/radiatastories/adapter.py>)、
[memory_map.py](<../../../adapters/radiatastories/memory_map.py>)、
[caves.py](<../../../adapters/radiatastories/caves.py>)。
以下のアドレスは EE physical address。allocation の値は提供 base state の例であり、固定して使わない。

## 1. 対応範囲と現時点の実証

- 実装上の対応機能は **Orbit / 水平 FOV / 位置 XYZ・注視点 XYZ の独立 offsets**。
  **Free Camera は未対応**。
- 原作の script camera 更新・native pose は止めず、render camera の world matrix を
  **view と frustum の生成中だけ**差し替える。生成後に native matrix を戻す。
- Orbit 中は player の移動方向を計算する専用 forward getter 呼出しに、描画と同じ実 eye→target の
  forward を渡す。原作 camera/pad の永続値、速度・deadzone・analog/D-pad の処理は変更しない。
  この追加の静的根拠・実機未検証の区分は「移動方向 consumer」を参照。
- host は player 相対の matrix・FOV 引数・actor の識別情報を二重バッファへ publish する。
  guest が camera 更新時点の player 座標を加えるため、追従を host の高頻度座標書込みに頼らない。
- 確認場面では原作の右スティックは camera 等に割り当てられていない。
  原作 pad 読取り命令・processed 右軸・派生 bit の抑制 patch は追加しない。
  `set_stick_block()` は no-op。全メニュー・特殊場面の原作割当までは網羅していない。

**実証済みの範囲は限定的**。提供された base / 時間経過のみ / character・camera 移動の
比較 state と、その base に対応する live 場面が起点である。
live では **yaw 140° / pitch 20° / distance 1500 / look height -90 / 水平 FOV 40°** を適用し、
主役を中心に保った建物側面からの視点と画角変化を画面で確認した。
同時に view 出力の変化、guest heartbeat の増加、処理後の native `camera+90` 復元を readback した。
その後の GUI 実機確認では4組の Orbit、独立6 offsets、FOV 25/40/65°、短い左スティック歩行、
比較 state の再読込・再適用、Original 復元、ステータスメニューの抑止も確認した。
条件と実行結果は [TEST_RESULTS.md](<TEST_RESULTS.md>)。機能一覧は全範囲・全 scene の試験完了を意味しない。

初期調査では frame advance 直後の screenshot が古いままで、matrix / FOV 出力が変わっても
画面不変に見えた。通常 resume 後の更新された画面で視覚確認できたため、
このケースを「hook 無効」とは扱わない。逆に heartbeat や mirror の変化だけを描画成功の証拠にもしない。

## 2. 音源 listener と描画 camera を分ける

最初の差分候補は listener 用 node だった。

```text
listener root = [0037EF88]             例: 0018D540
listener node = [listener root+1390]   例: 00616650
listener world output = node+150      例: 006167A0
listener view output  = node+190      例: 006167E0
```

`0012E3E0` は node の `+90..C0` を transpose して `+150..180` へ出力し、
`001CE6B0` で inverse を作る。その後、距離減衰・方向角に応じた値を計算する。
caller `0012F240` を含む音源制御系であり、この見かけ上の camera matrix を最終描画 camera と誤認しない。
`root+139C..13A8` は 4 方向の角度区間テーブルであり、**FOV ではない**。
`0012E4CC` / `0012E57C` の listener inverse 呼出しは現行 render hook ではない。

また `001F0050` は src の native position / rotation / scale (`+20/+30/+40`) を
宛先 vtable の setters へ渡す copy 関数であり、listener の `+150` を描画 camera へ渡す処理ではない。

## 3. Active render camera の所有経路

```text
field manager = [0037FBF8]
owner         = [field manager+1514]
camera        = [owner+10]
target node   = [owner+14]
renderer      = [0037EFE8]
active camera = [renderer+94]
```

host は `camera == active camera`、camera vtable=`0014E9A0`、
target node vtable=`0014F970` を検査する。guest も field 所有 camera と renderer の active camera の
一致、および camera class を確認し、別 camera の更新は原作どおり通す。
同じ camera class の object は複数存在するため、class 一致だけでは対象を決めない。

base の観測例:

| 項目 | allocation |
|---|---|
| field manager | `0062F100` |
| owner | `00630650` |
| camera | `007BA350` |
| target node | `007BADF0` |
| renderer | `004D7620` |

owner 経由の camera と renderer+94 は同じ `007BA350` だった。
actor 描画に近い caller が使用するという理由だけで、これを別の shadow camera と決めつけない。
`0029BD20` は renderer+94 の view / focal を world↔screen 補正に使い、
`002C0620` は owner の camera / target から距離・yaw を計算する。
live の FOV 書込みによる画角変化でも、この camera が実画面に関係することを確認した。

共通 node と render camera の主要 field:

| offset | 意味 |
|---|---|
| `+20/+30/+40` | native position / quaternion 等の rotation / scale 入力 |
| `+90..CF` | native row-major world matrix。translation は `+9C/+AC/+BC` |
| `+254/+258` | 投影の scale 要素 |
| `+260` | native FOV-angle 入力、radians |
| `+278` | 最終 focal length |
| `+27C` | aspect |
| `+290/+2A0` | viewport の左右端 |
| `+2C0` | view matrix 出力 |
| `+340` | projection matrix 出力 |
| `+400..490` | frustum corners 等 |
| `+4A0..530` | frustum planes 等 |

## 4. Player alias と actor record の対応

player の位置を camera target や固定 allocation から推測しない。
原作の player alias（resolver の識別値 `26AC`）が参照する scene 内の current ID を使う。

```text
scene       = [0037F734]
player ID   = u16[scene+830]
actor mgr   = [0037FC08]
count       = [actor mgr+10]       許容: 1..196
records     = [actor mgr+14]
record[i]   = records + i*80
record+00   = actor ID
record+58   = actor object pointer
record+5C   = node pointer
position    = node+20             float4, w≈1
```

host は ID が一致する record が **一つだけ**あること、record table の範囲、object / node pointer、
node vtable=`0014F970`、座標の finite / 範囲 / w≈1 を検査する。
確認場面の player node は `006E7090`、actor record は `00631720`（record+58 の object は `006E8100`）だったが、これらの値は固定しない。

host は採用した record index と ID を slot へ publish する。
guest は current scene ID、slot ID、現在の record ID が一致すること、index<count、
count の上限、object / node の範囲・alignment、node class を更新時に再確認し、
その node の**最新 position**を相対 world matrix の translation へ加算する。
ID 不在や別 record への再利用を、以前の pointer のまま追従する理由にしない。

scene+10 の bit0 または scene+1C の bit3 が立つ player-processing 停止状態は拒否する。
この条件を満たすことは「全イベントで gameplay camera」と同義ではない。

## 5. 3 hook の render transaction

描画経路の中心は `001B4E20`。
vtable+60 で native 更新し、vtable+64 (`001B3E40`) から `camera+90` を取得して view を作る。
末尾の `001B3F70` も **world+90 を直接読む**ため、view 引数だけの差替えでは culling と不整合になる。

| hook | stock 2語（命令 / delay slot） | cave |
|---|---|---|
| `001B4F84` | `0C07AC5C / 27A400D0` — `jal 001EB170; addiu a0,sp,D0` | `000F0000` |
| `001B500C` | `0C04856E / 00000000` — `jal 001215B8; nop` | `000F0800` |
| `001B51FC` | `0C06CFDC / 7FA200C0` — `jal 001B3F70; sq v0,C0(sp)` | `000F0C00` |

呼出し側の original delay slot は保持し、接続・解除は各 hook の aligned 1語だけを変更する。

1. **view cave**: outstanding transaction がないことと対象の所有・scene・actor 条件を確認。
   publish 済み slot を sequence lock で guest 専用 snapshot へコピーし、Orbit なら native world+90 の 64 bytes を保存する。
   player 相対 matrix にその時点の player position を加えた world を作り、+90へ一時コピー。
   元の `001EB170` へ tail jump し、元の return address を保って view を生成する。
2. **FOV cave**: 同じ pending camera / latch を使い、FOV flag がある場合だけ tan の `f12` 引数を変更。
   元の tan `001215B8` へ tail jump する。native `camera+260` は書き換えない。
3. **finish cave**: 元の `001B3F70` を呼び、変更した world と focal から frustum を生成する。
   対応する camera の native world+90 を保存から戻し、pending を解除して復帰する。

これにより native position / rotation / scale / FOV-angle は原作が更新し続け、
world+90 も transaction 外では native に戻る。Orbit と FOV は独立 flags。
FOV-only でも対象判定・slot latch・cleanup のため同じ 3 hook を使用する。

`001B4510` は view 前に native world から `camera+570` の派生値も作る。
この派生値の全 consumer は未網羅。view / projection / frustum の整合だけで、
全描画・反射・特殊 effect の完全対応としない。

### 移動方向 consumer（2026-11-03 追加）

旧3hookでは native world を描画後に復元するため、移動処理が読む方向は原作 camera のままだった。
player の analog / D-pad 処理 `00387C10` で、次の呼出しだけを追加 hook する。

| hook | stock 2語（命令 / delay slot） | cave |
|---|---|---|
| `00388140` | `0C06D1F0 / 27A40160` — `jal 001B47C0; addiu a0,sp,160` | `000F1400` |

静的な根拠（既存 base RAM / Ghidra `radiata_ram`）:

- `001B47C0` は `a1=camera` の vtable+64 から world matrix を得て、`+08/+18/+28` の
  第3列を `a0` の float4 へ書く forward getter。第4成分は1。
- `00388140` の結果を `00388154` で `atan2(z,x)`、`00388174` で
  `(3π/2-angle) mod 2π` に変換し、`f20` へ保持する。
- 同じ関数内の analog は `00388244..54` で `stick_angle + (f20-π/2)`、
  D-pad は `003882D8..00388410` で `f20` に cardinal/diagonal の定数角を加減する。
  得た `f22` を `003885AC..B4` から quaternion 作成へ渡し、actor の移動に使用する。
  任意の共通 atan/getter や別 camera consumer は変更しない。
- 追加 hook の2語は提供された3つの比較 RAM で一致し、追加 cave は既存の zero survey 範囲内。
  `00388140` は RAM の動的 code 領域にあるため、他 scene/overlay で異なる語なら拒否する。

movement cave は `a0`/`a1` と saved registers を維持し、current `s0=actor record` が
publish 済み player index に対応することを確認する。magic、Orbit global/bank flags、
field camera==引数 camera==active renderer camera、camera class、scene 停止 flags、
current player ID==bank ID==record ID、record count/index、object/node pointer と node class を再検査する。
同じ偶数 sequence の間に bank の world 第3列を読み、**実際の offsets 適用後の eye→target** を返す。
nominal yaw 値や前 frame の render latch に依存せず、native matrix / quaternion / pad は変更しない。
拒否時、FOV-only、Orbit 解除時は元の `001B47C0` へ tail jump する。

単体では cardinal/diagonal yaw、独立 eye offsets、別actor/scene/menu停止・不安定bank、
FOV-only、解除・stock reload・未知語拒否を確認した。後続の実機でyaw180/270°のUpとyaw90°のRightが
実視線基準へ変わること、getterのforward、全4hookのstock reload／Original復元を確認した。
一方、狭い橋の反対方向には横ずれ・ほぼ無移動もあり、地形／衝突／旋回初動は未分離。
数値と失敗条件は [検証記録](<TEST_RESULTS.md#5-orbit-のカメラ相対移動追加2026-11-03>) を参照。
従来の短い追従測定を、この方向補正の実証として流用しない。

## 6. FOV と座標・パラメーター

`001B4E20` の focal 算式は次のとおり。

```text
half_width = (camera[+2A0] - camera[+290]) / 2
scale      = camera[+254] * camera[+258]
focal      = scale * half_width / tan(camera[+260] / 2)
FOV_h      = 2 * atan(half_width / focal)
```

MOD は desired horizontal FOV に対して `atan(scale*tan(desired/2))` を slot に保持し、
tan 引数だけを置き換える。native angle 入力と実画角は scale を通して区別する。
FOV readback は native+260 ではなく最終 focal / half_width から求める。
提供 base 付近の native 水平画角は約 **28.84°**。40°設定では最終 focal と画面変化を確認した。

Orbit は既存の数学を利用し **Y+が下、pitch+が上から、look height+が下**。
world matrix は row-major、forward は第3列、translation は第4列。
相対 target と eye の独立 offsets を host で basis / translation に反映し、guest で player を加える。

| 項目 | 現行範囲 / 既定値 |
|---|---|
| pitch | `-25..89.5°` / `20°` |
| distance | `150..6000` / `1500` |
| look height | `-500..500` / `-90` |
| position / target offsets | 各軸 `-1500..1500` |
| 水平 FOV | `20..110°` / 約 `28.84°` |
| yaw 既定値 | `180°` |

## 7. Cave の所有・解除・低位メモリ制約

control block は `000F1000`、サイズ `300`、magic=`52414431` (`RAD1`)。
二つの publish slot は block+100 / +180。block には pending owner、saved world、render world/target、
guest snapshot（+200）、heartbeat を保持する。slot 内 sequence は host 更新中に奇数、完了後に偶数へ進め、
guest はコピー前後の同じ偶数値を確認する。1 frame 中に host が2回以上 publish しても、tan は再利用される
host bank でなく guest snapshot の FOV/flags を使う。新しい nested transaction は pending がある間拒否する。

適用前に render3箇所とmovement1箇所の全4hookの stock / 現行 exact code と cave 全語を確認する。
cave は **全ゼロまたは現行 exact code のみ**、control block も magic と空き状態を検査する。
未知の hook 命令・占有データへ強制上書きしない。cleanup hook を entry より先に接続し、最後に entry を接続する。
解除は flag を落とし entry / tan / movement hook を先に戻し、既存 pending の cleanup 完了後に finish hook を戻す。
movement getter は永続値を変更せず、FOV-only では装着済みでも native pass-through になる。
VM が transaction 内で止まり pending が解消しなければ、短い timeout 後に拒否し、resume 後の解除を要求する。

低位領域の根拠は次の**確認条件付き**である。

- `000F0000..000F1FFF` は提供 3 state の全 8192 bytes がゼロ。
- boot ELF 最小 PT_LOAD は `00100000`、BSS clear は `0017E300..0041A900`。
- boot の SetupHeap は `0041A900` 以降、SetupThread の初期 stack は
  top=`01FE0000` / size=`20000`。この通常 heap / stack と cave は非重複。
- 提供 base の低位メモリでは `0008xxxx..00095060` 付近にも OS 等の実データがある。
  他ゲームで使った `00080000` を空き領域として流用してはいけない。
- **OS の全将来用途・別 scene / overlay / ロードでの未使用保証ではない**。
  未知語拒否と runtime の所有確認を維持し、異なる状態で再確認する。

## 8. 解析資産と未確認項目

ゲーム由来 ELF / RAM / Ghidra project / 大量の逆コンパイル・画面は Git に置かず、
ローカル `C:/PS2CameraLab/work/radiata/` に分離する。
持続 Ghidra project は `radiata`、language は `r5900:LE:32:default`。
boot ELF と、既存 base RAM の `00100000..0042FFFF` の別 program を解析した。
boot index は560関数、初期調査後の RAM index は3178関数。
ELF に有用な元 symbol はなく、camera / lookat / projection の名前付き symbol も見つかっていない。
これらは解析した program / window の件数であり、全 overlay・全関数の発見数ではない。

現時点で未確認: 全 map / 戦闘 / cutscene / 全メニュー / 通常ロードの全経路、
長時間歩行と camera 遷移、offset・可動域の全組合せ、複数 camera / 特殊 effect、
全 scene の右スティック機能、ゲーム切替を含む GUI 長時間実機回帰。
主役中心の camera と歩行方向の全 yaw 対応は別項目。専用移動 hook の実機確認は上記の限定条件であり、
offset込み歩行・広い場所の全方向・連続回転は未網羅。提供 state と限定 live 実証を、これらの保証へ一般化しない。
