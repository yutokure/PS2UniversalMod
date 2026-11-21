# ゲーム切替時の誤書き込み防止と Git 監査（PR #1 独立レビュー P1 / P2 への対応）

## P1: ゲームの切替を検知したら旧アダプターの書き込みを止める

### 原因

PINE のソケットはゲームが替わっても維持されます。GUI がゲームを確認するのは「接続」と「接続が戻った瞬間」だけだったため、
幻想水滸伝V のアダプターが動いている最中に別のディスクを起動すると、

1. カメラ制御スレッド（約 1.2 kHz）が旧ゲームのアドレスへ書き続け、
2. 画面を閉じる・「再接続」を押すと `_teardown()` → `CameraRuntime.restore()` が旧ゲームの純正値（コード語を含む）を新ゲームへ書く、

という経路がありました。接続が戻ったときの不一致処理（`_show_link`）も、同じ `restore()` を通っていました。

### 仕組み（`core/memory_backend/guard.py`）

* アダプターは `GuardedBackend` 経由でだけ書き込みます。読み出しは素通しです。ガードは接続時に確認した **Serial と CRC の組** に結び付きます。
* **リース**: 書き込みは「直近 0.25 秒以内にゲームを確認できた」間だけ許可されます。リースは GUI の状態取得スレッド（`StatusPoller`、約 0.4 秒周期、PINE 2 回）が更新します。
  GUI が止まっていても、書き込み側スレッドがリースの 60 % を過ぎたところで自分で確認します（PINE 2 回 × 毎秒 約 7 回）。書き込み 1 回あたりの追加は約 0.3 µs で、通常の更新ループで Serial/CRC は読みません。
* **不一致（別ゲーム）**: ガードは「取り消し」になり、以降の書き込みは `WriteBlocked` で拒否されます。取り消しは実行中の書き込み 1 件の完了を待ってから戻るため、戻った後に旧ゲームへ届く書き込みはありません。
  ブロック書き込みは 1 語ごとにフラグを見るので、途中でも次の語で止まります。
* **確認できない状態**: Serial または CRC が空（ゲーム終了〜起動の間など）なら書き込みを一時停止し、同じ組を再確認すると再開します。読取り例外やタイムアウトはリースを更新しないため、直前のリースが切れた後は書き込めません。
* **接続の世代**: `PineBackend.epoch` は再接続のたびに増えます。ゲーム確認後、ガードは書き込みをその世代に固定し（`write_epoch`）、
  ソケットが張り直された（別の PCSX2 かもしれない）場合は、`PineBackend` が自分のロックの中で書き込みを拒否します（`PineStaleSession`）。再確認が済むと再開します。
* **破棄**: GUI は取り消しを検知すると `_reconnect(restore=False)`。`CameraRuntime.abandon()` はスレッドを止めるだけで、ゲームには何も書きません（`stop()` と `restore()` は書き込みます）。
  その後、新しいゲームの Serial/CRC に合うアダプターを選び直します。未対応ゲームなら書き込み不可のまま「未対応」と表示し、あとで対応ゲームが起動すれば自動で切り替わります。
* 画面を閉じるとき・「再接続」を押したときにも `_teardown()` が再確認します。元と同じ Serial・CRC を確認できた場合だけ復元し、不一致・識別不能・切断時は `abandon()` で旧ランタイムを破棄します。

2026-11-03 イクサ追加: `SLPM-66646 / 8B383FDF` を独立登録。ネオとイクサを相互に識別しないこと、
稼働中 Orbit からの相互切替で旧runtimeを復元せず破棄すること、設定／presetのゲーム別分離、
誤ったCRCを拒否することをfake PINEで確認しました。ガード自体の時間窓・仕様は変更していません。
中心化の任意native境界をcoreへ追加しましたが、イクサの書込も全て同じGuardedBackendを通ります。

2026-11-07 イノセントライフ追加: `SLPS-25763 / 9AC21F92` を独立登録。
時計停止も同じ `GuardedBackend` を通し、カメラとは独立した runtime lane で扱います。
起動・再接続・presetは時計停止を有効にしません。Original選択はカメラだけを復元し、
同一ゲームの無効化・正常teardownは時計も解除、別ゲーム・不明時の `abandon()` は時計解除も書き込みません。
時計解除をカメラcleanupエラーで飛ばさない境界、誤CRCの書込み拒否、未対応control、例外後の再開通知をfakeで検証しています。
FOV追加も同じbackendを通し、描画コピーの焦点距離だけを変更します。原作cameraは保持し、ゲーム不明時のabandonはFOV解除も書き込みません。
FOV serviceは復旧成功時に自身の完全一致する古いエラーだけを解除し、新しい時計・scene・patchエラーは消しません。
lease仕様と残る時間窓は変更していません。

2026-11-07 マグナカルタ追加: `SLPS-25401 / EB925207` を独立登録。
走行時広域表示／エンカウント無効（オレンジ丸枠も非表示）も既存GuardedBackend経由、
2つの独立session-only runtime laneで扱います。Originalは保持、無効化・通常終了は解除、
別game／不明時はabandonし解除書込みもしません。起動・再接続・presetは有効化しません。
誤CRC、preflight no-write、片方の失敗・retry・partial ownership、preset保存除外を合成memoryで確認。
real GUIではOriginalで2toggleを保持し、無効化で全5site stockへ戻ることを確認しました。
field rendererのdata callbackからEE threadでcode hookを適用復元しますが、
lease時間窓・ゲーム切替検知までの制約を変更したものではありません。
11月8日版のエリア修正では、既知の旧版と完全一致した場合だけ、EEで全hookの解除を確認して到達不能になったrenderer caveを移行しました。
11月21日版ではローカルプレイヤーの所有を確認し、既知の旧renderと移動caveの**両方**を検査・移行します（[マグナカルタの適用・復元条件](../games/magnacarta/CAMERA.md#適用と復元の安全)）。どちらも同じガードを通り、別ゲーム・識別不能時の復元はしません。

RPGツクール5 (`SLPS-20143 / BB78C51D`) は同じGuardedBackendを使い、編集／テストプレイの間でもカメラを取り違えないよう、接続世代・活動中のマップと描画タスク・場面・角度と距離の期待値を照合します。不一致なら古いカメラ値は復元しません。FOVは固定位置の署名を検査し、同じ世代で自分が書いた命令だけを解除します。[同一ゲーム内のロード実測と限界](../games/rpgmaker5/TEST_RESULTS.md#復帰ステート切替)。

### 残る時間窓

PINE にはゲーム切替の通知がありません。ゲームを替えるときは、元のゲームを起動したまま GUI で MOD を無効化し、元のカメラに戻してから切り替えてください。

直前の識別がまだ有効な間（最大 0.25 秒）は、旧アダプターの通常の書き込みが新ゲームのメモリへ届く可能性があります。終了・再接続時の復元はそのリースに頼らず、同じ Serial・CRC を再確認してから行います。

## P2: `tools/audit_repo.py` が実際のコミット内容を検査する

### 原因

`--staged` は `git diff --cached --name-only` で名前だけ取り、中身は作業ツリーのファイルを読んでいました。`git add` の後でファイルを書き換えたり消したりすると、
監査した内容とコミットされる内容が食い違いました。

### 仕組み

| モード | 検査対象 |
|---|---|
| （指定なし） | 追跡ファイルの **作業ツリー上の内容** |
| `--staged` | **Git インデックス** の blob（`git diff --cached --raw -z` で得た blob を `git cat-file` で読む）。HEAD に対して追加・変更されたものだけ。削除は対象外、リネームは新しいパスと中身で検査。HEAD が無い最初のコミットでは全ステージ分 |
| `--commit REV` | そのコミットのツリー全体（`git ls-tree`） |
| `--history` | 履歴に一度でも入ったすべての blob（消したファイルも） |
| `--repo PATH` | ほかのリポジトリ（テストが一時リポジトリに使う） |

パスは `-z` で受け取るので、空白・日本語・引用符を含んでいても正しく扱えます。大きな blob は全部読まず、先頭 4 KiB と ISO9660 の目印だけを読みます。
検査項目（拡張子・データ用ディレクトリ・マジックナンバー・ISO・NUL・サイズ・認証情報らしい文字列）は従来のままです。

### コミット前フック（任意）

フックは標準では無効です。このクローンの補助チェックとして使う場合に設定します。

```bash
git config core.hooksPath tools/git-hooks     # 有効化（コミット前に --staged 監査）
```

フックは監査失敗時にはコミットを止めますが、Python が見つからない場合は警告だけで監査を実行しません。
フックの有無にかかわらず、コミット前に `git diff --cached --name-only`、`git diff --cached --stat` で対象を確認し、`python tools/audit_repo.py --staged` が成功してからコミットします。再ステージしたら監査もやり直します。

## テスト

| ID | 内容 | テスト |
|---|---|---|
| P1-01 | 同じゲームで動作継続、不要な再接続なし | `tests/test_gui.py::test_same_game_keeps_its_runtime_and_the_orbit` |
| P1-02 | 同一接続でゲームだけ替わる → 書き込み停止 | `tests/test_game_guard.py`、`tests/test_gui.py::test_switching_to_an_unsupported_game_stops_all_writes` |
| P1-03 | 旧アダプターの `restore()` が新ゲームへ書かない | `test_old_runtime_writes_nothing_after_the_game_changes_and_restore_is_inert`、`test_closing_after_a_silent_game_switch_...` |
| P1-04 | 対応ゲーム間の切替で新アダプター | `test_switching_between_supported_games_selects_the_new_adapter`、`test_neo_exa_switch_discards_the_old_runtime_without_restore`、`test_switching_from_active_suikoden_to_exa_selects_its_own_adapter` |
| P1-05 | 未対応ゲームは書き込み禁止・表示あり | `test_switching_to_an_unsupported_game_...`、`test_unsupported_game_is_noticed_when_a_supported_one_starts` |
| P1-06 | PCSX2 再起動 | `test_pcsx2_restart_with_*`、実機 `tools/game_switch_check.py`、`tools/gui_freeze_check.py --kill --relaunch` |
| P1-07 | 性能 | `test_the_lease_costs_two_identity_reads_per_expiry_not_per_write`、`test_the_status_poller_checks_the_game_...` |
| P2-01〜06 | 監査 | `tests/test_audit_repo.py`（一時 Git リポジトリ、ダミーデータのみ） |
