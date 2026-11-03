# ザ・ナイトメア・オブ・ドルアーガ — 解析とアダプター

対象: **日本版 SLPS-25377 / CRC B476ED7A**、PCSX2 **fork-B056de99**。解析・実測日: **2026-11-03**。
Serial と CRC の両方を照合する。他地域版・別 CRC は未対応。

実装: [adapter.py](<../../../adapters/nightmaredruaga/adapter.py>)、
[memory_map.py](<../../../adapters/nightmaredruaga/memory_map.py>)、
[caves.py](<../../../adapters/nightmaredruaga/caves.py>)。
実施条件・途中失敗・未確認範囲は [検証記録](<TEST_RESULTS.md>) を参照。
以下は EE physical address。実測した allocation の値は例であり、固定アドレスとして使用しない。

## 1. 対応範囲と方式

- **Town と Dungeon の確認済み gameplay camera** を、別のクラス・別の hook で扱う。
- Orbit の yaw / pitch / distance、相対 look height、位置 XYZ / 注視点 XYZ の独立 offsets、水平 FOV に対応。
- **Free Camera は未対応**。GUI で無効化する。
- 原作の camera update と smoothing は止めず、最終 world matrix builder に渡す eye / target だけを替える。
  native current / goal 座標は元の update が引き続き更新する。描画出力への host 高頻度書込み競争ではない。
- host は actor 相対のパラメーターを二重バッファへ publish し、guest は各更新時の actor 座標を加算する。
  host が保持する数十 ms 前の actor 座標を camera の追従元にしない。
- Orbit 中は原作の processed 右軸とその派生方向入力を中立化する。**raw 右軸は保持**し、MOD 側入力に使える。
- Orbit 中の Town 移動は actual 視線の水平基底、Dungeon D-pad は同基底の最寄り8方向へ補正する（第8節）。

初期接続は保存 mode に関係なく **Original**。設定・preset は既存 GUI のゲーム別保存を使用する。
GUI の有効化は自動適用しない。通常の「Original / 復元」操作で camera・FOV・入力を返す。

## 2. Town と Dungeon の scene / camera layout

| 項目 | Town | Dungeon |
|---|---|---|
| root pointer の格納先 | `006B1DBC` | 同左 |
| active camera pointer の格納先 | `006B1DC0` | 同左 |
| root vtable | `0069FD20` | `006A2D90` |
| camera vtable | `0069FB30` | `0069FB50` |
| root 内の埋込み camera | `root+2040` | `root+2050` |
| root+4 の下位 halfword | `2` | `3` |
| `GAME_STATE` (`006B1DA0`) | `2` | `1` |
| `camera+214` mode | `0` | `1` |
| 追加条件 | — | `camera+2DE == 0`（遷移でない） |
| 観測 allocation 例 | root=`01FD5370`, camera=`01FD73B0` | root=`01FFD9B0`, camera=`01FFFA00` |

camera は **root 内の object** であり、`root+2040/+2050` に保存された pointer ではない。
renderer は `root+40`、その `+320` は `camera+50` を指す必要がある。

共通 camera layout:

| offset | 意味 |
|---|---|
| `+10` / `+50` / `+90` | world / view / projection matrix |
| `+1AC` | renderer に渡る垂直 FOV、float radians |
| `+1B0` | projection の水平換算係数（さらに `0.7` が掛かる） |
| `+214` | camera mode |
| `+218/+21C/+220` | eye / target / FOV smoothing 状態 |
| `+22C` | native FOV degrees |
| `+230/+240/+250` | native eye goal / current / 最終出力用 mirror |
| `+270/+280/+290` | native target goal / current / 最終出力用 mirror |
| `+2A0` | native target 相対 offset |
| `+2E0` | Dungeon の平滑化済み player-follow anchor |
| `+2F0` | Dungeon の最終 eye へ加える collision / obstruction 補正 |

Town は `004BABD0`、Dungeon は `004B9A90` 系列を使う。Dungeon は native eye `+240` に
`+2F0` を加えた `+250` を最終 builder に渡すので、Town の出力箇所へ単純にアドレスを差し替えるだけでは足りない。
`camera+2DE != 0` では別更新 `004BA8C0` へ分岐する。この経路は Orbit 対象としない。

## 3. Player anchor — slot の再利用に注意

entity manager=`0078F140`、table=`0078F240`、64 records、stride=`1C0`。
record は `+0` flags の bit0 が active、`+8` に ID / index、`+10` に renderer pointer、
`+30` に homogeneous float4 position を持つ。host は finite / 範囲 / w≈1 も確認する。

### Town

ID **1000** を持つ active record を table から検索する。renderer は `root+40` と一致する必要がある。
観測時は slot1 の record=`0078F400`、position=`0078F430` だが、slot は固定しない。
移動した提供 state の位置は `(-1.367653, 2, 4.100594)`。

### Dungeon

Town の ID1000 は不在で、同じ slot1 が別 entity へ再利用されていた。
Dungeon entry で slot1 の `(6,50,-4)` を player と誤認すると、native camera の注視点と一致しない。
正しい取得経路は native camera 自身が使用する player actor の所有 pointer:

```text
actor = [006CB7C8]
subentity = [actor + 5E8]
record = subentity - 10
position = subentity + 20 = record + 30
```

`004BA0F0 → 0049A830 → 00506990` の呼出しで確認した。
`0049A830` は non-null subentity の position を返し、null なら actor+650 を返す。
**adapter は未実証の null fallback を使用せず拒否する**。
subentity は table 内 record+10 と正確に対応する必要があり、active / renderer も検査する。
Dungeon の採用条件は **actor が現在所有している record** であって、ID0 や slot0 の固定ではない。

観測 state では actor=`0072D560`、subentity=`0078F250`、position=`0078F270`=`(14,50,-24,1)`。
native target は `(14,51.5,-24)`。`camera+2E0` はこの player へ速度・距離に応じて平滑化して近付く
追従点であり、常に player と一致するわけではない。MOD は平滑化済み target を player master と誤認しない。
Town では同じ actor global の subentity が null だったため、この経路を Town へ共用しない。

## 4. Orbit / offsets / 座標系

Druaga は **+Y が上**。共通 math の内部 pitch は負が俯瞰側なので、adapter の表示・入力 sign は `-1`。
GUI 表示 Pitch `35°` は内部 `−35°`、表示上限 `89.5°` は内部 `−89.5°` に対応する。
真上 `90°` は look-at の特異点を避けて使用しない。

| 制御 | adapter の範囲 |
|---|---|
| 内部 pitch | `−89.5 .. +25°`（表示 `−25 .. +89.5°`） |
| distance | `2 .. 100` |
| relative look height | `−15 .. +15` |
| position / target offset 各成分 | `−30 .. +30`（GUI 入力範囲） |
| 水平 FOV | `20 .. 110°` |

角度 `y,p`、距離 `d`、最新 player `A` として:

```text
T = target_offset + (0, look_height, 0)
R = (sin(y)*cos(p)*d, -sin(p)*d, cos(y)*cos(p)*d)
render_target = A + T
render_eye = A + T + R + position_offset
```

position offset は eye だけを動かし、target を連れ動かさない。offset は world 軸で、camera-local 軸ではない。
position offset がゼロでないとき、最終 eye-target の距離・角度は球面 Orbit の設定値そのものとは異なり得る。
runtime は `accepts_orbit_offsets` 境界から明示的な相対 offsets を渡す。
中心化は現在の native 描画方向を読み、player 基準で再構成する。native 座標へ直接書かない。

## 5. 最終出力の 2 camera caves

| 用途 | hook / stock 2語 | cave / return |
|---|---|---|
| Town | `004BAD40`: `E62001AC 78480000` | `003F0000` / `004BAD78` |
| Dungeon | `004B9C04`: `7C680000 26240010` | `003F0800` / `004B9C34` |

hook は先頭の aligned 1語だけを J へ置換し、delay slot は stock のまま残す。
Town では delay slot が読み込んだ native eye、Dungeon では直前に読み込んだ native eye+collision を使い、
cave 冒頭で元の mirror store を再現する。`+250/+290` へ MOD 座標を保存する方式ではない。

- `00434B80`（translation）/ `004349C0`（look-at）へ渡す引数だけを MOD scratch へ切り替える。
- native eye / target の current・goal、Dungeon collision 計算、既存の後続処理を維持する。
  MOD の自由な eye に対し native collision を再計算するわけではない。
- guest も root / camera pointer 対応・vtable・process / mode・renderer source・event・render suspension を確認する。
  Dungeon はさらに +2DE と actor-owned subentity を照合。Town は anchor record の ID1000 を再確認する。
- 拒否時は native eye / target の builder 呼出しへ戻る。native update 自体を停止しない。
- parameter bank は `003F1000+100/+140`、1 bank `40` bytes。host が非active bank を完成後、slot と flags を切替える。
  eye / target は actor 相対値。guest が更新時の actor translation を加算する。
- control block=`003F1000`、size=`200`。heartbeat / active camera / native FOV / 適用有無もここに置く。

予約範囲は Town `[003F0000,003F0800)`、Dungeon `[003F0800,003F0C00)`、pad `[003F0C00,003F1000)`。
ELF の load segment は `00400000` から、BSS / heap 境界は `0092D980`。
提供 state のゼロ状態と領域配置を照合したが、**全 MOD と競合しない空き領域の保証ではない**。
生成コードの占有長・hook・control block を preflight し、未知の非zero内容や未知命令は上書きしない。
旧開発版の code bytes も現行コードと一致しなければ未知として扱う。自動強制 cleanup はない。

## 6. FOV — native degrees を保ち、renderer radians を変更

GUI は水平 FOV `h`。原作は垂直 radians `v` と projection scale `s=camera[1B0]` を使う。

```text
v = 2 * atan(0.7 * s * tan(h/2))
measured_scale = projection[0] * 0.7 * s / projection[11]
measured_horizontal_fov = 2 * atan(1 / measured_scale)
```

camera cave 内で native `+1AC` を記録後、FOV flag が有効なら bank の radians を渡す。
**native degree field +22C は変更しない**。host は projection scale の finite / 範囲も確認する。
Town の native vertical25° は horizontal≈35.14668°、Dungeon entry の vertical40° は horizontal≈54.94503°だった。
FOV40 / 60 / 90°は実投影からの読戻しで確認した。設定値や scratch の変化だけを実証根拠にしない。

adapter 自体には FOV-only の所有・適用・復元と単体テストがある。ただし現共通 runtime は **Original 分岐で
FOV service より前に return** する。したがって GUI Original のまま FOV checkbox だけを使う運用は未対応の
既存制限であり、本 adapter で解消したとは扱わない。実機 FOV 確認は Orbit 中に行った。

## 7. 原作右スティックの中立化

raw packet の RX / RY=`006B2074/+1`、LX / LY=`+2/+3`、raw 中立=`127`。
processed signed right X / Y=`006B2200/+4`、left X / Y=`+8/+C`。
原作は右 raw から item / inventory shortcut 用の方向 bit も生成するので、専用 action 3箇所だけの遮断では不十分だった。

| 役割 | stock | Orbit 中 |
|---|---|---|
| 軸 loop hook `0043958C` | `lbu a0,4(v1)` / `90640004` | J `003F0C00` |
| delay slot `00439590` | `addiu a3,a0,-127` / `2487FF81` | **変更しない** |
| 派生 RY load `004396FC` | `92850005` | `2405007F`（a1=127） |
| 派生 RY load `0043972C` | `92840005` | `2404007F`（a0=127） |
| 派生 RX load `00439754` | `92850004` | `2405007F`（a1=127） |
| 派生 RX load `00439784` | `92840004` | `2404007F`（a0=127） |

pad cave は original raw load を行い、loop index `t0 < 2`（RX / RY）だけ a0=127 とし、
元の `a3=a0-127` を再計算して `00439594` へ戻る。LX / LY はそのまま処理する。
raw bytes と buttons を書換えない。実機で **raw RX=255 のまま processed right X=0** を確認した。

全 hook / derived load を先に確認し、未知があれば書込みゼロで拒否。
pad cave はゼロまたは現行 exact code のみ受理し、コード完成後に hook 1語を接続する。
解除時も既知命令だけを stock に返し、cave 内容自体は消去しない。

## 8. Orbit 中の移動方向 — Town continuous / Dungeon tile8方向

2026-11-03 の追加実装。render-only camera では native current が変わらないため、
入力 consumer 側だけへ MOD の **actual eye-target** に対応する方向を渡す。
以下の実装・単体確認と、過去の camera 追従 live 成功は別の根拠である。
今回の実機方向確認は [検証記録](<TEST_RESULTS.md>) の追加結果を参照。

### Town

- `0051B3B0` が analog/D-pad を正規化し、歩行速度・dash を掛けた後の `sp+70` local float4 を回す。
  Up は local **+Z**、Right は **+X**。raw / processed pad、速度、Y/W、actor current / goals は書き換えない。
- `0051B760` の `8E03000C` 1語だけを J `003F1200` にし、delay `24020001` は保持する。
  `s0 == current root+2310`（Town 埋込み player controller）と Town scene / active ID1000 anchor / renderer 所有を確認する。
- 受理時は X/Z だけを置換し `0051B7D0` へ戻る。元の任意 native camera 変換 `0051B768..0051B7CC` を
  skip するため、設定 byte `[[s0+C]+A4]` が1でも二重回転しない。
  拒否時は displaced `lw v1,C(s0)` を再現し `0051B768` から元の処理へ戻る。

```text
F = (target-eye).XZ / horizontal_length
screenRight = (Fz, -Fx)
worldX = Fz*localX + Fx*localZ
worldZ = -Fx*localX + Fz*localZ
```

### Dungeon

- D-pad decoder `0045B7B0` 内の sector helper 呼出し2箇所 `0045B7F0 / 0045BEB0` の JAL 1語だけを
  `003F1800` へ変更する。stock は両方 `0C117040`、delay `0240202D` は保持する。
- wrapper は `a0 == s2 == 006CB790`（gameplay manager、その `+38` が player actor pointer）と
  Dungeon scene / camera transition / actor-owned anchor を再検査する。
  decoder の saved caller `[元sp+40]` は `00452404 / 0045598C` の gameplay 2経路のみ許可する。
  target-selection UI の `0055F4D8` と未知 caller は拒否する。
- actual back=`eye-target` の `theta=atan2(backX,backZ)` を最寄り45°へ量子化し、native sector enum を返す。
  `q=floor((theta+π/8)/(π/4)) & 7`、sector=`(1,5,2,4,0,7,3,6)[q]`。
  既存の8方向 table、held / pressed / repeat、斜め・R1 gate、tile legality と速度をそのまま使う。
  連続的な camera 方向と tile 方向は最大22.5°ずれる仕様であり、任意角度の自由移動にはしない。
- 受理時は `v0=sector; jr ra`、拒否時は native helper `0045C100` へ tail jump し caller RA を保持する。
  左 analog は従来どおり item UI の入力であり、本補正の対象ではない。

### Publish・領域・解除

- host は camera と同じ bank 内 `+28/+2C` に Fx/Fz、`+30/+34` に root/camera、`+38` に valid と sector を置く。
  position offset 適用後の eye と target から計算し、Orbit yaw 値だけからは作らない。
- `MOD_BLOCK+1C` は movement 用 sequence。host は odd → 非active bank全体 → slot → flags → even の順に publish。
  guest は読取り前後の同一 even sequence を要求する。host が中断して odd が残れば native fallback。
  原作 camera cave の code bytes は今回変更しない。
- ±89.5°の pitch 近傍も水平成分があれば正規化する。offset によって水平 eye-target が消えた場合
  （水平長 `<=1e-6`）は valid を出さず native fallback。FOV-only は移動 hook を接続しない。
- 専用予約は Town movement `[003F1200,003F1800)`、Dungeon movement `[003F1800,003F1E00)`。
  提供 Town base / moved / wait の静的 RAM で `003F1200..003F2200` が zero と確認した。
  他 MOD / 全 scene の未使用保証ではない。使用する全生成 bytes と3 hook / delay を camera resource と一括 preflight し、
  未知の非zero cave・未知命令は最初の書込み前に拒否する。
- Orbit 解除（FOV が残る場合も含む）で movement 3 hook を stock に返す。無効 scene 内の復元も可能。
  stock state reload / 既知 mixed hook は bank を再 publish し復旧する。cave 自体は消去しない。
  native goals と pad raw / processed は維持し、menu/event/所有不一致は guest で native fallback。

## 9. 安全・復元・未確認範囲

- 書込みは渡された `self.backend` のみ。GUI は既存 `GuardedBackend` と Serial+CRC を使用する。
  別ゲーム / 不明 identity への teardown は restore せず runtime を abandon する。
  identity lease の検出時間窓は既存仕様で、即時・完全遮断の保証ではない。
- 同一ゲームの通常復元では両 camera hook・movement 3 hook・pad hook / 4 derived load を返す。
  Orbit / FOV が片方残る場合は必要 flag のみ維持する。menu 等で scene が無効でも、片方の解除が例外になり
  残りの解除を飛ばさない。matrix は次の stock update が再構築する。
- FOV は同じ所有 camera で、現在値が最後の自分の値のままのときだけ native +22C から戻す。
  別 allocation / ゲーム側が変更した未知の値を、古い保存座標や FOV で強制復元しない。
- stock state reload 後は約1秒周期の再確認でパラメーター / 両 camera site / pad を再適用する。
  Town / Dungeon hook の既知混在も修復する。未知の命令や古い自作 code は強制上書きしない。
- scene guard は全メニュー判定器ではない。Orbit 中の pad 遮断は scene が拒否された時にも残り得る。
  原作の右入力が必要な menu / UI では Original へ戻す。
- **全階層・全イベント・全メニュー・長時間・死亡 / 再開・入力録画再生・他 MOD との共存は未確認**。
  城内のleft analog／B1FのD-pad歩行追従は実証。詳細は [検証記録](<TEST_RESULTS.md>) を参照。
- MOD eye の壁抜け / terrain clipping 対策、map / HUD 用追加 patch、Free Camera は実装していない。
  native collision 計算を維持することと、自由な MOD eye の collision 解決は別である。
