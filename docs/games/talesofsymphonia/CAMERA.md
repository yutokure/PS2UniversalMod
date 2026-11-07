# テイルズ オブ シンフォニア — camera / movement / compass

対象: 日本PS2版 `SLPS-25400 / 830B6FB1`。解析・実装日: 2026-11-07。
実装の正本は [adapter](<../../../adapters/talesofsymphonia/adapter.py>)、
[map](<../../../adapters/talesofsymphonia/memory_map.py>)、
[caves](<../../../adapters/talesofsymphonia/caves.py>)。
確認条件と失敗を含む履歴は [TEST_RESULTS](<TEST_RESULTS.md>)。

## 対象と座標

- `MODE 0x469DC0` が `0x87`: 町・通常マップ系。提供stateは町の同一地区4つ。
- `0x8A`: 徒歩ワールドフィールド。提供stateは同一地域4つ。
- `SUBMODE 0x469DB8=0`、scene別native owner／script／vehicle flagsをhostとguestで確認する。
  これらは通常場面の限定predicateであり、全menu/event/battleの分類保証ではない。
- 原作は **XY水平、Z上**。runtime/GUI境界だけ `canonical=(native X,-native Z,native Y)` に変換する。
  共有core数学は変更しない。GUI高さとoffset Yは負が上、offset Zはnative Y。
- 町player alias `0x47E754`、actor callback `0x47E750=0x13BA20`。
  world playerは `*(0x46A1D0)+4`。world rootは町にもstale値が残るのでpointer単独判定しない。
- view `0x4A0A00`、camera world/inverse `0x4A0C80`、projection `0x4A0A40`。
  全8stateでview×world≃I、view×projection≃VP `0x4A0BC0` を照合。
  world行列row0/1/2はright/up/backward、row3はeye。町の視線はplayer+(0,0,87)へ一致。

## 描画用コピー方式

共通look-at builder `0x1F8C70` は町 `0x178920`、world `0x28E800` から呼ばれる。
内部 `0x1F8C88` の `jal 0x1F8D20 / addiu a0,sp,0x10` をwrapperへ置換する。
元caller RAとscene/ownerを検証し、player相対eye/targetから**そのguest frameのplayer**を加算してstackコピーを作る。
元eye/targetとrig・smoothing・native camera yawは変更しない。
最終native view builderが逆行列・view projection・clip関連を更新するため、出力ミラーだけの上書きではない。

hostのdouble-bankはsequence odd→payload→even→slotで公開する。
look wrapperはmode/playerを確認し、even sequenceの全bankをsnapshotへコピーして再照合後に受理する。
移動・compass・map consumerは同じaccepted snapshotの実視線を使い、hostが次bankを書いても未受理のyawを混在させない。
ホストは原作actorの絶対座標を毎フレーム書き続けない。

## FOV

- 水平FOV `20..110°`。lookとは別の投影builder内 `0x1F8C3C` の `jal 0x1FC520 / swc1 f0,sp,0x68` をwrapper化。
- caller RA whitelistは町 `0x17890C`、world 3D `0x2892F0 / 0x289324`。
  HUD投影 `0x28AC64` 等へ適用しない。
- 原作projection引数64Bをstackコピーし、`sx=cot(hFOV/2)`、`sy=sx*(native sy/native sx)` の2値だけ変更。
  near/far・aspect・その他matrix係数を保持してnative builderを呼ぶ。
- `MB_NATIVE_LENS/MB_RENDER_LENS` は**実際に渡した3D引数**の診断値。
  worldではframe末尾にshared projectionがHUDへ戻るため、global projectionだけで画角判定しない。
- Original/native resetの原作値はselected town rig `0x4810F0 + index*0x94 + 0x58` のvertical degree、
  worldはmap ID `0x4806F6` に応じnative lens 16bit-turn `0x1684 / 0x0D70`、aspect `10/7` から計算する。
  native builderの整数角切捨ても反映。測定した町35.4918°／普通world44.1046°。
- FOVはOrbit付随。OriginalのFOV-onlyはruntime対象外。

## 移動・右入力・コンパス

| consumer | 境界 | 変更する引数のみ |
|---|---|---|
| 町移動 | `0x142994 / 0x142D54` → native `0x1DDDB0` | `f12/f13 = actual forward XY` |
| world徒歩heading | `0x2890CC` load＋sub | `f2 = atan2(forward X,forward Y) mod 2π` |
| world compass | `0x28AC94` → `0x27E6E0` | `f12 = actual yaw` |
| minimap / fullmap | `0x28AD4C / 0x28AE08` | 同じ `f12`、map座標等はnative |
| world streaming | `0x281C08 / 0x2825AC` | 地形chunk選択の `f4 yaw` |
| native right X | `0x286E3C` → getter `0x243E10` | 通常world Orbit時だけreturn 0 |

原作町には右cameraなし、worldでは右Xのみcamera横回転。
raw pad／左軸／ボタン／右Yを全体で無効化しない。worldの乗り物・飛行cameraはpredicateで対象外。
native actor headingはworldで `(sin heading,-cos heading)`、移動の速度・clamp・向き・衝突はnative処理を流用する。
コンパスのdiskとN/E/S/W配置はnative `0x27E6E0`、地図の視線扇形はnative `0x27EB00` が描く。

## TOS2: host実行コード書込みを避けるlifecycle

初期案TOS1はPINEからlens callへ1word bootstrapしたが、繰返し試験でPCSX2に
`[EE] Impossible block clearing failure` とprocess crashが発生した。TOS2はその経路を廃止する。
旧TOS1 cave/magicを現行所有として認めずfail-closed。stock stateか再起動で消してから使用する。

1. 全11hook＋delay、全13code resource、空control／magicをread-only preflight。
2. **all-stockかつ未到達**のempty caveだけ準備。active zero／unknown codeを補修・強制復元しない。
3. hostは一時的な**data callback pointerだけ**を変更する。
   - 町: `0x47E750` のexact native `0x13BA20` → bootstrap。
   - world: `0x469DA0` のexact `0x14DC20`（又は0）→ bootstrap。
     normal fieldではnative `0x27FD5C` が描画後に呼ぶ。元handlerを消してはならない。
4. bootstrapは128bit T0..T4/RAを保持、共通EE lifecycleを実行する。
   lifecycleは**全11 exact stock/hook pairを先に確認してから**guest内で適用。
   callback pointerを元へ戻し、元handlerへtail callする（world元0の場合だけreturn）。
5. 通常の解除はlens wrapperから共通EE lifecycleへ。全11siteをnativeへ戻しACKする。
   hostはACK＋全pair＋data callback返却を読戻す。**cave本体は消去しない**。

実行コード13resourceは4page `0xF5000/F9000/FD000/FE000` 内、controlは `0xFF000` の別pageに置く。
全9snapshotで選択pageはゼロ、file-backed ELFのaligned canonical pointer literalは無し。
動的resourceの整数/命令誤検出を含む全RAMscanは参照なしを証明しない。永久空き保証ではない。

Hot publicationは同一adapter/backend/epoch内だけ、全11exact hook pair・magic・flags・ACKを検査。
full body auditは初回・backend/epoch変更・state消失・周期約1秒・`set_patch(True)`・解除時。
**bodyのみの損傷検知は次のfull auditまで遅れる**。初期full ~160msに対しhot実測約3.7ms（単発参考値）。
一時停止中はguest ACK不能。timeoutは強制復元せず再開後再試行する。
paused enableの途中でOriginalへ戻す場合も、flags0でinstallを取り消してからEEのcallback返却を待つ。
siteがまだstockでもpending callbackが残るうちは解除完了と偽らず、pause中はtimeoutを報告する。
GUI書込みは既存GuardedBackend経由で、別ゲーム／識別不能ではrestoreせずabandonする。

## 制限

- scene predicateは全イベント・menu・battle・vehicleを網羅する保証ではない。特殊場面はOriginalへ。
- 通常非フィールド対応の実証範囲は提供町。全ダンジョン・全マップの同構造を実証したわけではない。
- 原作geometryの無いmap外・屋根裏面・壁越し・黒背景は残る。Orbit collisionは追加しない。
- world yaw streaming選択は同期するが全frustum／LOD／sort／billboard／particlesの解除・最適化を保証しない。
- controller/GUIの値だけを成功とはしない。実画面・投影係数・frame進行・原作復帰の確認条件は結果文書を参照。
