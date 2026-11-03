# PS2UniversalMod 作業ガイド

短い依頼から、現行実装と確認済みの知見を使って目的を完了するための判断基準。
設計の詳細・コマンド一覧・過去の実測は参照先に置く。

## 適用範囲と正本

- Git 管理する唯一の正本は `PS2UniversalMod/AGENTS.md`。
  親ラボの `AGENTS.md` は相対シンボリックリンク `PS2UniversalMod/AGENTS.md` とする。
  配置・読取り一致の確認は [文書索引](docs/README.md) を参照。編集は必ず正本へ行う。
- 本書のパス・リンク・コマンドの基準はリポジトリルート `PS2UniversalMod/`。
  親ラボから読む場合も同ルートへ移動して解決する。
- PS2UniversalMod の開発には本書全体を適用する。
  親ラボの PCSX2 / MCP / Ghidra / 解析には安全・既存資産活用・復旧の共通ルールを適用する。
  Git・アダプター・GUI 固有の規則はこのリポジトリ用で、別の独立プロジェクトの規則を上書きしない。
- ユーザーの Global Multi-Agent 指示と割り当てられた役割・Skill に従う。
  Implementer が Reviewer へ移るなどの役割変更をしない。
  ユーザーが gate / manual-batch Skill を明示しない限り、Gate や独立レビューを自動追加しない。

## 進め方

- 明示された目的の範囲で調査・設計・実装・修正を自律的に進め、細かな判断ごとに質問しない。
  ユーザー目的・scope・権限・安全制限を守り、不可逆な操作や範囲外の判断は区別する。
- 合理的な改善は目的との関係と根拠を記録する。過剰設計より実際に動く成果を優先する。
  無関係なリファクタリング・機能追加・全体監査へ広げない。
- まず現在の Git 状態と対象コードを読む。既存コード・解析・テスト・Git 履歴・ステートを探し、
  使えるものを再利用する。既存ゲームの成功例を参照しても構造が同じとは仮定しない。
- 現行コード・現在の Git 状態・対象 source / 場面が分かる確認済み動作を古い設計書より優先する。
  コード上の実装と実機での実証は別。食い違いは調べ、未検証を実証済みに言い換えない。
- 不調時は合理的な復旧を試す。同じ失敗を根拠なく繰り返さず、復旧不能な原因・制約を報告する。

## 最初に読む場所

| 目的 | 参照先 |
|---|---|
| 起動・操作・対応ゲーム・設定・検証・Git | [README.md](README.md) |
| 文書の入口、ゲーム別・GUI・ラボ資料 | [docs/README.md](docs/README.md) |
| 新ゲームの解析・方式選択・登録 | [ADAPTER_GUIDE.md](ADAPTER_GUIDE.md) |
| 接続・デバッガ・Ghidra の既存構成 | [ラボ構成](docs/lab/ARCHITECTURE.md)、[準備状況](docs/lab/CAMERA_RESEARCH_READINESS.md)、[CLI](docs/lab/CLI_REFERENCE.md) |
| 障害・既知の制限 | [KB](docs/lab/TROUBLESHOOTING_KB.md)、[BLOCKERS](docs/lab/BLOCKERS.md)、[復旧手順](docs/lab/AUTONOMOUS_TROUBLESHOOTING.md) |
| GUI の挙動・制限・安全 | [GUI 監査記録](docs/gui/GUI_AUDIT_2026-11-02.md)、[ゲーム切替ガード](docs/gui/GAME_IDENTITY_GUARD.md) |

ラボ資料は当時の構築・検証記録を含む。過去の Gate、テスト件数、PASS、再試行回数は
現在の作業に対する実行ノルマや保証ではない。日付・source・対象ゲーム・場面を確認して使う。

### ゲームごとの実績を使い分ける

| ゲーム / Serial / CRC | 現行方式・参照先 | 使う際の注意 |
|---|---|---|
| FFX-2（FF10-2） / `SLPS-25250` / `8A6D7F14` | 差分注入・注視点パッチ・ゲーム本来のカメラルーチンへのフック。[技術メモ](docs/games/ffx2/ADAPTER_NOTES.md)、[歩行調査](docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md) | Free Camera 対応。歩行追従の実測は歩き始め 0.3 秒、長時間は未確認。演出エリアの FOV 制限は README・最新追記で確認 |
| シャイニング・フォース ネオ / `SLPM-65908` / `64F241D2` | 角度・距離・高さの制御値、平滑化ゲート、FOV / 右スティック用コードケーブ。[解析](docs/games/shiningforceneo/CAMERA_ANALYSIS.md) | Free Camera・位置/注視点オフセット未対応。復帰後の yaw は原作が決め、元の角度との一致は既知の制限 |
| シャイニング・フォース イクサ / `SLPM-66646` / `8B383FDF` | 原作の角度・距離・高さ・垂直 FOV 入力＋平滑化ゲート、右軸 load 2 命令の中立化。[解析](docs/games/shiningforceexa/CAMERA.md) | ネオに近いが actor offset・既定値・入力方式は別。Free Camera / offsets 非対応。FOV-only も gate を保持。全イベント・入力再生は未検証 |
| 幻想水滸伝V / `SLPM-66286` / `7380A572` | カメラ更新の出力ストアをコードケーブで置換。[解析](docs/games/suikoden5/CAMERA.md)、[テスト結果](docs/games/suikoden5/TEST_RESULTS.md) | 原作右スティックは 3 段階ズーム。Orbit 中は競合を遮断し R1 は維持。Free Camera 未対応。イベント・戦闘・メニューは未検証 |
| ナイトメア オブ ドルアーガ / `SLPS-25377` / `B476ED7A` | 城内・Dungeon別の最終行列出力cave、native状態を保持。右processed軸と派生bitのみ中立化。[解析](docs/games/nightmaredruaga/CAMERA.md)、[テスト結果](docs/games/nightmaredruaga/TEST_RESULTS.md) | Orbit・6軸offset・FOV対応、Free未対応。Dungeon playerは専用actor所有pointer（城内ID1000とは別）。Dungeon移動は方向キー、左analogはitem UI。全floor/イベントは未網羅 |

FFX-2 の [FINAL_STATUS](docs/games/ffx2/FINAL_STATUS.md) は 2026-10-31 の測定記録。
歩行未解決などの当時の結論を、後のフック実装・測定より優先しない。
幻想水滸伝V の長時間試験・他ゲーム回帰も記載された条件の実績であり、全場面の保証ではない。

## 責務と安全条件

- `core/` は共通 camera 計算・runtime・入力・設定・メモリ接続、`adapters/<game>/` はゲーム固有の
  アドレス・座標系・カメラ方式を担当する。既存 `gui/camera_controller/` を再利用する。
- 新ゲームを既存ゲームの内部構造へ無理に合わせない。必要なインターフェース改善は可能だが、
  根拠のない抽象化やゲーム固有アドレスの共通基盤への持込みを避ける。
  共通基盤変更では既存ゲームと直接の integration boundary への影響を評価する。
- `identify()` は Serial と CRC の両方を確認する。Serial だけで対応版と認めない。
- GUI のアダプター書込みは `core/memory_backend/guard.py` の `GuardedBackend` を通した
  `self.backend` 経由。独自 PINE 接続・内部 backend の直接利用でガードを迂回しない。
- 未対応・識別不能・接続世代変更では安全側に倒し、別ゲームを検出した旧アダプターは破棄する。
  同一ゲームと積極的に確認できない teardown では `restore()` も書込みになるため実行せず、
  `CameraRuntime.abandon()` を使う。ガードのリースによる検出までの時間窓は
  [ゲーム切替ガード](docs/gui/GAME_IDENTITY_GUARD.md) にあり、即時・完全遮断と誇張しない。
- 同一ゲームで通常終了・無効化するときは、原作 camera・FOV・入力・patch を正常に返す。
  保存値・適用済み命令・復元対象を確認し、未知の命令を強制上書きしない。
  FFX-2 の外部 `.pnach` / stock hook の操作・後始末は README とゲーム資料も確認する。
- 右スティックの原作機能との競合、場所依存/イベント camera、ロード・ステート復元を考慮する。
  `is_field_like()` や heartbeat の判定だけで全特殊シーン対応済みとしない。
- FOV は実際の投影処理・画角が変わることを確認する。GUI 値や無効な出力ミラーの変化だけで成功にしない。
- 未対応機能は adapter の `features` と GUI の disable・理由表示に反映する。
  設定はゲーム別、起動時は Original、プリセットは値のみという現行挙動を守る。

## 新ゲームの追加

詳細は [ADAPTER_GUIDE.md](ADAPTER_GUIDE.md) と最も近いゲーム資料を読む。

1. ISO の所在・版・Serial / CRC を確認する。原本を変更しない。
2. 既存 PCSX2 MCP / PINE / Ghidra の構成と使える接続を確認し、作り直さない。
3. 既存ステート・解析・関数索引を探す。基準・時間経過・移動・ズームなど必要な状態だけ追加する。
   原本ステートは保護し、複製・明示スロットで扱う。
4. Python のメモリ差分解析でノイズと候補を絞る。`analysis/savestate_diff/`、
   `analysis/suikoden5/`、親ラボの `scripts/ps2lab/` を参照する。
5. MCP のオンライン読取り・最小の安全な書込み/読戻しで候補と実画面の関係を確かめる。
6. GDB watchpoint で書込み命令を捕まえ、Ghidra で関数・入力・出力・投影経路を特定する。
7. 差分注入・制御値・コードケーブ等から、そのゲームに合い競合と復元を扱える方式を選ぶ。
8. `adapters/<game>/` に実装し、Serial + CRC、場面判定、patch 適用/復元、機能制限を定義する。
9. 既存 GUI の `ADAPTERS`・`ADAPTER_BY_GAME_ID`・`SUPPORTED_IDS` に登録し、機能・範囲・説明を反映する。
10. 要求範囲の動作確認を行い、関連文書を確認・更新し、指示された範囲で Git 操作を行う。

PINE は同時 1 クライアント。GUI と検証スクリプトを同時に接続しない。
GDB も MCP と raw RSP を併用せず、接続で VM が停止していないか確認する。
解析用 MCP / GDB は通常の GUI 実行には不要。設定や起動の詳細は README・ラボ資料を参照する。

## 検証を選ぶ

- テスト一覧は参照手順と判断基準であり、全件の自動実行義務ではない。
  指示・変更の性質・影響範囲に合わせ、目的の確認に必要なものを選ぶ。
- 「テストして」「動作確認まで」「実装検証まで」なら、目的を満たす範囲を実行する。
  メモリ書込み・patch 復元・データ保護など高影響の変更は、最小限の安全確認を優先する。
- 既存のシャドウ A/B の区分は、必要時に確認範囲を選ぶために使う。
  A = 局所単体・アドレス・GUI・変更箇所の確認。
  B = PCSX2 実機・複数ゲーム回帰・長時間・ゲーム切替・ステート復元。
  通常は A を優先し、B は要求・リスク次第。毎回 A+B を完走するノルマではない。
- コマンド・前提条件は README の「検証」、ADAPTER_GUIDE と既存 `tests/` / `tools/` を参照する。
  `tests/test_core.py`、`tests/test_sfneo.py`、`tests/test_suikoden5.py` は数学・各方式、
  `tests/test_game_guard.py` / `tests/test_pine_backend.py` は書込み・接続、`tests/test_gui.py` は表示・操作の手掛かり。
  実機手順の雛形は `tools/su5_*_check.py` と `tools/regression_check.py`。
- 小タスクで全テスト、文書誤字で PCSX2、GUI 文言で全ゲーム実機検証は不要。
  固定回数の反復や独立レビューを自動追加せず、未実施を理由に無関係な scope を増やさない。
- 実行済み・未実行・適用外を区別する。実行していないものを PASS にせず、
  不要な未実施を失敗扱いしない。過去の結果には対象 source と条件がある。
- `python tools/audit_repo.py --staged` はコミット前のデータ保護手順で、機能テストとは別に必須。

## 文書への影響を毎回確認する

コード・機能・仕様・設定・運用を変えるたび、次を同じ作業内で行う。

1. 関連用語・パス・機能名を検索して既存文書を見つける。
2. 記述が現行実装・今回の変更と一致するか確認する。
3. 必要な箇所を更新し、新仕様・制限・確認済みの範囲を記録する。
4. 廃止機能・古い手順・対応表・リンクが残らないか確認する。
5. 実装と文書、文書同士の整合を確認する。

確認の結果、更新不要なら編集しない。毎回文書ファイルを変更する義務ではない。
既存箇所への追記・修正を優先し、全文の重複や別の正本を増やさない。

| 変更 | 影響確認先 |
|---|---|
| アダプター | `docs/games/<game>/` の解析・対応機能・制限、README の対応一覧、必要なら ADAPTER_GUIDE |
| GUI | README の操作・設定入力、`docs/gui/`、表示言語の `gui/camera_controller/i18n.py` |
| core の安全・復元 | README / ADAPTER_GUIDE の安全・復元説明、`docs/gui/GAME_IDENTITY_GUARD.md`、必要ならラボ architecture の該当範囲 |
| 解析手順の改善 | 使用手順・有効条件・既存方式との差・再利用できる知見を該当ゲーム/ラボ資料へ |

未実装・未検証の項目を完了済み・実証済みにしない。
過去の測定記録は条件・日付を残し、現在の案内と混同させない。
文書変更の確認から無関係なテストや実機操作を起動しない。

## Git とデータ保護

- Git root は `C:/PS2CameraLab/PS2UniversalMod`。親ラボ全体を `git init` しない。
  親 `AGENTS.md` はリンクで Git 管理外。private リポジトリの非公開設定を維持する。
- 管理対象は自作コード・adapter・GUI・tests・解析スクリプト・設定テンプレート・docs・最小の解析要約。
  アドレス・関数名・測定値・ハッシュの要約を使い、ゲーム由来データ本体を含めない。
- ISO / CHD / BIOS / 抽出 ELF・素材 / ステート / メモリーカード / RAM・VRAM dump /
  Ghidra project / 大量の逆コンパイル出力 / スクリーンショット / 録画 / 秘密情報は禁止。LFS も使わない。
  保存場所は README のローカルデータ表と `core/config/paths.py`、除外は `.gitignore` を確認する。
- Git 操作前に `git status --short --branch` を確認し、HEAD・ブランチ・既存ユーザー変更を把握する。
  他者変更を削除・上書きしない。`git reset --hard` / `git restore .` / `git clean -fd` は禁止。
- 新機能は作業ブランチを使い、既存 PR と適切なブランチを確認する。main へ直接混ぜない。
  ステージは `git add <明示した対象パス>`。無条件の `git add .` / `git add -A` を避ける。
- コミット前は必ず次の 3 点を確認する。監査失敗時は原因を解消して再確認し、保護を迂回しない。

  ```powershell
  git diff --cached --name-only
  git diff --cached --stat
  python tools/audit_repo.py --staged
  ```

- index のパス・内容が今回の対象のみで、ゲームデータ・秘密情報を含まないことを確認する。
  audit は作業ツリーでなく index を読む。再ステージしたら監査もやり直す。
- commit / push / PR 作成 / 独立 review / merge は別の操作。指示された範囲のみ行う。
  「push」から merge や独立 review を推測しない。指示外 merge は禁止。
- merge が許可されたときは対象 PR・head/base・作業ツリー・remote 状態・競合・必要 checks を確認する。
  required protections を回避しない。merge 後は remote main への反映と local の状態を確認する。

## 障害からの復旧

状態確認 → 原因調査 → 必要なら Web → 局所修正 → 必要な確認 → 元の作業へ再開。

- まず README の troubleshooting、ラボ KB / BLOCKERS、既存解析・ログを使う。
  Web が必要なら公式 docs / source / issues を優先し、対象バージョンを照合する。
- MCP 切断、PCSX2 再起動、Ghidra error、未知 camera は自律的に切り分ける。
  単一クライアント、VM の停止、Serial / CRC、パッチ状態、接続世代、場面の違いを確認する。
- reconnect・安全な再起動・既知ステートへの復元など、原因に合う限定的な復旧を試す。
  ユーザーの保存データと作業中状態を守り、権限・安全・データ保護制限を越えない。
- 同じ失敗を反復せず、新しい根拠がなければ止めて原因・制約・必要な次の判断を報告する。
  復旧後は元の目的へ戻り、無関係な改善や大量回帰に拡大しない。

## 短い依頼を受けたとき

| 依頼例 | 判断の起点 |
|---|---|
| 「新 game 解析追加」 | 既存解析・ステートと版を確認し、新ゲーム手順へ。既存 3 本と同じ構造とは決めない |
| 「GUI button 名を変更」 | `app.py` / `i18n.py` と操作説明を検索し、関連表示を確認。全ゲーム実機検証は不要 |
| 「camera bug を直す」 | ゲーム・版・場面を既存情報から特定し、原因と直接影響を確認。書込み/復元は安全確認を優先 |
| 「docs と実装を整合」 | 現行 source と根拠を照合し、関連する古い説明を修正。未検証の実機成功を追加しない |
| 「push」 | 対象 branch / commit・既存 PR・remote と許可範囲を確認して push。merge は含めない |
| 「merge」 | 明示対象と必要 checks / protections・状態の安全を確認して実施し、main 反映を確認 |

## 最終報告

変更内容、文書への影響（更新不要ならその判断）、実行した確認と必要な未実行項目、問題・制約、
commit / PR の状態、必要な次作業を簡潔に返す。
PASS は実行した確認に、CHANGES REQUESTED は残る要修正に、BLOCKED は継続できない具体的理由に使う。
実装側の自己点検を独立 review の PASS と呼ばない。担当範囲を完了したら Parent / ユーザーへ返す。
