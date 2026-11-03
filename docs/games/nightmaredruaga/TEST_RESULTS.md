# ザ・ナイトメア・オブ・ドルアーガ — 2026-11-03 検証記録

対象: **日本版 SLPS-25377 / CRC B476ED7A**、PCSX2 **fork-B056de99**、Python 3.12。
source: `feature/nightmare-druaga-adapter` の作業ツリー。コミット前の実装検証で、独立 review / gate ではない。
[解析・方式・アドレス・制限](<CAMERA.md>) と、下記の source / 場面 / 入力方式の違いを併せて読む。

**最終結果:** 最新 pad cave 方式で関連回帰 **559 passed**、Town GUI実機 **15/15**、
Dungeon GUI実機 **15/15**、Dungeon→Town stockステート切替付き実機 **16/16**、メニュー復元 **5/5**。
城内・B1Fの確認であり、全階層・全イベントの保証ではない。
途中の移動失敗は、Dungeonの左analogが原作のitem UI操作だったことと壁条件を切り分け、
原作の方向キーで通行可能な隣接タイルへ動かして再検証した。失敗履歴と最終成功を分けて以下に残す。

## 1. オフライン単体・GUI — 最新 pad cave 方式

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest tests/test_gui.py tests/test_druaga.py -q
```

**261 passed / 52.24秒**。内訳: Druaga 単体 **203**、GUI **58**。
Druaga 単体のみは **203 passed / 1.18秒**、GUI の Druaga 抽出は **11 passed / 47 deselected / 2.27秒**。
対象は [Druaga tests](<../../../tests/test_druaga.py>)、[GUI tests](<../../../tests/test_gui.py>)。
両テストファイルに対する `git diff --check` もエラーなし。

最終の関連回帰（最新camera/pad方式）:

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest tests/test_core.py tests/test_sfneo.py tests/test_sfexa.py tests/test_suikoden5.py tests/test_druaga.py tests/test_game_guard.py tests/test_gui.py tests/test_pine_backend.py -q
```

**559 passed / 56.78秒**。共通dispatch変更、既存アダプター数学・GUI登録・identity/connectionガードを含む。
他ゲームのPCSX2実機再実行ではない。

### 検証した境界

- Serial+CRC 両方の照合、transport 失敗の read-only、unknown allocation / vtable / process / mode 拒否。
- Town の ID1000 検索と、Dungeon の global actor → owned subentity → record position の分離。
  Dungeon の slot0 / 7 / 63 への移動を許容し、ID1000 を代替 anchor にしない。
- host の無効 scene 拒否と、host publish 後に scene / actor 所有が変わった場合の guest native fallback。
  event / renderer suspension / camera transition `+2DE` / root state / mode / renderer / subentity 失効を含む。
- 相対 Orbit math・内部 pitch / 距離の clamp・非finite拒否・eye / target の独立 offsets。
  guest が最新 actor 座標を加算し、native current / goals と Dungeon の collision 調整済み出力を保つこと。
- camera 2 caves の領域・branch destination・displaced store・delay slot・return の整合。
  Dungeon の FOV は hook 時の scratch F0 に頼らず native `+1AC` から再取得すること。
- immutable parameter bank を完成してから slot / flags / hook の順に公開すること。
- FOV の水平↔垂直変換、3種類の projection scale、native degree field 保全、FOV-only / Orbit 共有所有、解除。
- 両 camera site の既知 stock / MOD 混在 repair、適用・解除の冪等性、unknown site / cave / control block の no-write 拒否。
- Town→Dungeon / Dungeon→Town / Dungeon→Dungeon の synthetic stock state reload 後の再選択・再適用。
- Orbit+FOV 後に event / process / mode / render suspension / renderer が無効化されても通常 restore が完遂し、
  両 camera hooks・FOV flags・pad code を返すこと。
- identity guard が revoke された後の publish / restore no-write、runtime abandon no-write。
- GUI 登録・CRC 不一致・保存 Orbit / Free でも初期 Original・Free 無効・全6 offsets 有効・sign / limits・ゲーム別設定分離。
- GUI enable→restore で processed 右入力用 hook / derived load を適用・復元し、raw bytes を維持すること。

### 新入力方式の命令モデル

最小 interpreter で **生成された pad cave** を delay slot 込みで実行した。
loop index0 / 1（RX / RY）は a0=127 / signed a3=0、index2 / 3（LX / LY）は raw / signed差分を保持する。
各 axis × raw `0,1,126,127,128,254,255` の **28条件**を確認。
A0 / A3 以外の register と raw memory は不変。

4 derived direction load は対応 register へ127を読み、方向入力を中立にする。
axis hook / delay / derived4箇所すべての unknown preflight、pad cave occupied 拒否、
known mixed normalization、コード完成前に hook を接続しないこと、aligned 1語だけの hook 復元、state reload 再適用も確認した。

**限界:** sparse fake backend と最小 R5900 interpreter の検証である。
projection builder は引数・読戻し用の合成モデルで、renderer、PS2 timing、pad-library 全体、全 gameplay scene の実証ではない。
実機とは区別する。ゲーム由来 RAM / ELF は tests に含めない。

## 2. Town 実機 — live2、16/16 PASS

[実GUIチェックツール](<../../../tools/druaga_live_check.py>) を offscreen Qt GUI + 実 PINE で使用した。
一時 APPDATA に設定を隔離し、実入力は PCSX2 keyboard pad、MOD 回転は runtime の scripted input pump を通した。
ローカル結果: [Town live2 checks](<C:/PS2CameraLab/test_evidence/druaga/live2/checks.json>)。

| 確認 | 実測・結果 |
|---|---|
| GUI 接続・初期状態 | 正しい Serial+CRC / guard、有効化前 Original、Free 無効、全6 offsets 有効 |
| yaw90 / 内部pitch−35 / 距離22 | yaw90、pitch−34.999998、距離21.99999993 |
| yaw−90 / 内部pitch−55 / 距離16 | yaw−90、pitch−54.999998、距離15.99999955 |
| 真上近傍 | 内部pitch−89.500001、距離23.99999843、描画維持 |
| yaw170 / 内部pitch+10 / 距離20 | yaw170.000001、pitch9.999999、距離20.00000112 |
| 位置 XYZ / 注視点 XYZ / look height | 実 eye / target がそれぞれ計算値へ一致 |
| FOV40 / 60 / 90 | 実投影から40.00000087 / 60.00000017 / 89.99999583° |
| 左歩行＋actor追従 | actor X=−1.367653→0.432347、eye-player 相対誤差≈1.10e−6 |
| scripted right input pump | yaw90→114.874952、約24.87°回転 |
| stock state reload | 約2秒待機後 yaw90 / pitch−35 / distance22 / FOV90 を再適用 |
| Original 復元 | native camera / FOV≈35.146684° / 当時の入力命令へ復帰 |

**入力に関する重要な留保:** Town live2 は旧「専用 action 3 loads を遮断」版。
当時の right check は raw RX=255 / processed=`0x7F` で PASS としており、
最終版の **processed signed RX=0** を証明した記録ではない。
後の Dungeon 実験で別 item UI が開く競合が判明し、processed axis + 派生方向 load を遮断する現方式へ変更した。
Town live2 の成功を現方式の全入力 consumer 検証へ読み替えない。

初回 Town live1 での2件の失敗は harness の問題も含んだ:

- offsets 親 group が折り畳まれた状態で child `isEnabled()` を評価した。group 展開後の live2 で再確認。
- active input pump が runtime への直接 stick 設定を上書きした。選択中の scripted source 経由へ修正し再確認。

## 3. Dungeon 実機 — 最終15/15、場面切替込み16/16 PASS

Dungeon は Town の hook / camera class を通らず、別の camera update を使う。
entry state の root=`01FFD9B0`、camera=`01FFFA00`、player position=`(14,50,-24)` を確認し、
[解析文書](<CAMERA.md>) の actor ownership chain と整合した。

### camera 2nd cave の直接 probe

yaw90 / 内部pitch−35 / distance16 / look height1.5:

- target=`(14,51.5,-24)`。
- eye≈`(27.10643,60.67722,-24)`、FOV≈60.0000°。
- **native camera+240 は `(14,57.89899,−31)` のまま**。native current を MOD eye へ固定していない。

この実測は camera の実出力と native state の分離を確認したもので、全 Dungeon での成功保証ではない。

### GUI harness の途中結果

ローカルの [Dungeon live4 checks](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live4/checks.json>) は **15/16**、
[Dungeon live5 checks](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live5/checks.json>) は **14/15**。
live4 は stock state reload handshake を含み、live5 は含まない。
どちらも **唯一の失敗は左移動 / actor追従項目**で、総合 PASS としない。

成功した項目:

- GUI 初期 Original、中心化、有効範囲の yaw / pitch / distance、真上近傍、全6 offsets + look height。
- FOV40 / 60 / 90°の実投影読戻し。Town と同じ約40.00000087 / 60.00000017 / 89.99999583°。
- MOD runtime の scripted 右入力回転。
- 新入力方式で raw=`0x7F7F7FFF`（RX255）を維持しながら **processed right X=`0x0`**。
- live4 の stock state reload 後の camera / FOV / 入力再適用。
- Original で native collision-adjusted eye / native FOV≈54.945025° / 当時の検査対象命令へ復帰。

### 移動失敗の切り分けと最終結果

- 左analogを入れた移動試験ではactorが変わらず、item説明UIが開いた。camera/pad hookなしのstockでも同じ。
  **Dungeonの左analogは原作のitem操作で、歩行はD-pad**。Townのleft analog移動をそのまま適用したharnessの誤りだった。
- D-padであっても通れない隣接tileでは移動しない。live8ではX12からさらに左が不通で、その項目をFAILのまま残した。
- UIを閉じ、X14から左の通行可能tileへD-padで動かした
  [Dungeon live7](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live7/checks.json>)は **15/15 PASS**。
  actor `(14,50,-24)→(12,50,-24)`、eye-player相対誤差 **1.90735e−6**。
- [Dungeon live9 cross](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live9_cross/checks.json>)は **16/16 PASS**。
  同じ歩行追従に加え、GUIのOrbit/FOVを維持したままstockの城内ステートへ切替え、約2秒後に
  yaw90 / pitch−35 / distance22 / FOV90 / pad hook・derived4命令の再適用を確認した。
  Originalで切替先のnative FOV **35.146684°** と全検査対象命令へ復帰。
- 最終[城内再実行](<C:/PS2CameraLab/test_evidence/druaga/town_final/checks.json>)も **15/15 PASS**。
  新方式のraw RX255 / processed RX0、1.8単位の左analog移動、相対誤差1.10e−6、全offset/FOV/復元を再確認した。

### メニューでの復元

[メニュー実機確認](<C:/PS2CameraLab/test_evidence/druaga/menu_check.json>) **5/5 PASS**。
城内Orbit＋FOV60→Start menuでscene guard無効→menu内Originalで両camera hooks/pad hook/derived4命令/flagsを解除、
Crossでmenuを閉じnative FOV35.146684°へ復帰、再度Orbit有効化を確認した。
無効sceneでの通知 `scene guard: not a field camera` は安全退避の記録であり、復元失敗ではない。

### 途中の復旧と測定上の注意

- Dungeon の最終 native eye は `+240` ではなく、collision を加えた `+250`。
  旧 harness の Original 判定を Town と共通にすると誤失敗するため、scene 別に比較するよう修正した。
- 調査用 state に旧開発版 camera cave が残存していた。
  stock hooks / flags0 と exact-old-code 一致を確認した上で、自分が生成した旧 bytes だけを明示的に清掃した。
  **未知内容の強制 overwrite ではなく、adapter に汎用の強制清掃を追加していない**。
- 新方式は raw を127に上書きする方式ではない。host 入力 source と原作 processed 消費側を分離する。
- raw RX255 / processed0 は入力競合修正の実測根拠だが、全 item / inventory / event consumer の実証とは別。

## 4. 再実行時の前提と保護

PINE は **1クライアントのみ**。既存 GUI と別の PINE チェックツールを同時接続しない。
MCP / GDB を併用するときも接続主体を整理し、GDB 接続で VM が停止していないか確認する。
通常 GUI 運用に解析用 MCP / GDB は不要。

```powershell
python tools/druaga_live_check.py --out <lab>/test_evidence/druaga/<new-run>
```

stock reload 試験を行う場合は `--reload-handshake <new-empty-dir>` を付ける。
tool が `ready.json` を出したら、既存 MCP から **同版・stock state** を load / resume し、
handshake directory に `continue.txt` を置く。待機期限は180秒。
これは現在の進行状態を戻す操作なので、先に明示パスの backup を作成し、原本 state を実験結果で上書きしない。
tool は finally で injected input を放し、GUI 通常 close を行う。

**Dungeon では開始画面を確認**する。item説明 / menuを閉じ、D-padの指定方向が通れるか確認する。
`--dungeon-direction left`（既定）またはup/down/rightで通行可能な隣接tileを選ぶ。left analogはitem UIなので移動試験に使わない。
移動しない UI / 壁条件を camera 追従成功・失敗の根拠へ混同しない。
同様に scene guard が通ったことだけで全 UI 判別ができたとは扱わない。

## 5. ローカル証拠とデータ境界

公開 / Git 管理対象は自作 source・tests・ツール・この数値要約のみ。
**ISO / ELF / RAM / state / Ghidra project / 逆コンパイル本体 / ゲーム画像・録画は含めない**。
この文書へ screenshot を埋め込まない。

ローカル参照先:

- [Druaga 解析作業領域](<C:/PS2CameraLab/work/druaga/>) — 提供 state の展開 RAM、関数索引、最小調査用出力。
- [Druaga 実機証拠領域](<C:/PS2CameraLab/test_evidence/druaga/>) — 試験ごとの checks と画像。画像は Git 外。
- [Town live2 checks](<C:/PS2CameraLab/test_evidence/druaga/live2/checks.json>)（旧入力方式）と
  [最終Town](<C:/PS2CameraLab/test_evidence/druaga/town_final/checks.json>)（最新方式15/15）。
- [Dungeon live7](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live7/checks.json>)（15/15）、
  [Dungeon→Town live9](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live9_cross/checks.json>)（16/16）、
  [メニュー復元](<C:/PS2CameraLab/test_evidence/druaga/menu_check.json>)（5/5）。
- [Dungeon live4 checks](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live4/checks.json>)、
  [Dungeon live5 checks](<C:/PS2CameraLab/test_evidence/druaga/dungeon_live5/checks.json>)。
- [保護用 original state](<C:/PS2CameraLab/sstates/ナイトメアオブドルアーガ/session_20261103_1502_original.p2s>) と
  [追加 Dungeon entry state](<C:/PS2CameraLab/sstates/ナイトメアオブドルアーガ/session_20261103_dungeon_entry.p2s>)。
  原本3 state とは別名で保持した。

### セーブデータ保護・環境復帰

初回の城内→Dungeon入場では、確認画面のあとに**原作の自動セーブがslot1の元カードへ1回発生**した。
確認画面で停止したが、slot1のDruagaデータ更新時刻は15:34となっており、原カード未変更とは扱わない。
入場前のカード内容の完全バックアップは無いため、推測でセーブを巻き戻したり別slotのデータを上書きしたりしていない。

マウント中の排他ロックでコピーできなかったためPCSX2を正常終了し、両原カードを
[完全バックアップ](<C:/PS2CameraLab/backups/druaga_cards_complete_20261103_1538/>)した後、複製カードへ設定を切替えた。
それ以降のDungeon検証は複製側で行い、最終に原カードのDruaga各ファイルがバックアップとSHA-256一致することを確認した
（[最終ハッシュ記録](<C:/PS2CameraLab/test_evidence/druaga/original_cards_final_hashes.json>)）。
これは**隔離後の不変性**の証明であり、初回自動セーブ以前と同じという意味ではない。

完了時は両slotの設定を元のカードへ戻し、PCSX2を再起動して初期退避ステートをloadした。
初期の城内座標・native FOV35.146684°・両camera hooks/pad hook/derived4命令stockをread-only確認。
検証GUIは閉じ、入力保持・debug breakpoint/watchpointなし。ステート原本3本は上書きしていない。

## 6. 未確認・対象外

- **Free Camera は未対応**。position / target offsets は対応済みだが Free の代替ではない。
- Original モード単独の FOV checkbox 運用は、共通 runtime が FOV service 前に return する既存制限で未対応。
  adapter API の FOV-only 単体テストを、GUI Original の live 成功と同一視しない。
- Dungeon歩行追従はB1Fの2単位D-pad移動で実証。全地形・全方向の長い移動へ外挿しない。
- 全階層・長時間・全 menu / item UI・全イベント・戦闘の全遷移・死亡 / 再開・入力録画再生は未確認。
- 右原作機能が必要な特殊 UI では Original へ戻す。scene guard 無効時の入力遮断自動解除は実装していない。
- MOD eye に対する collision 再計算、歩行方向の camera 基準化、map / HUD の追加 patch は実装しない。
- 実ディスク間 live switch と他ゲームの live 再実行は、この単体・GUI実行結果に含めない。
- ユーザーの追加指示によりcommit / push / PR / mergeを行う。対象は自作source・tests・文書のみとし、
  Git indexのデータ保護監査を通してから公開する。ゲーム画像・ステート・カード・解析データ本体は含めない。
