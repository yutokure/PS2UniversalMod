# ゲーム切替時の誤書き込み防止と Git 監査（PR #1 独立レビュー P1 / P2 への対応）

## P1: PCSX2 でゲームを切り替えても旧アダプターが書き込まない

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
* **確認できない状態**: シリアルが空（ゲーム終了〜起動の間）なら書き込みを一時停止し、同じゲームが答えれば再開します。読めない・タイムアウトのときはリースが切れるため書き込みません（安全側）。
* **接続の世代**: `PineBackend.epoch` は再接続のたびに増えます。ゲーム確認後、ガードは書き込みをその世代に固定し（`write_epoch`）、
  ソケットが張り直された（別の PCSX2 かもしれない）場合は、`PineBackend` が自分のロックの中で書き込みを拒否します（`PineStaleSession`）。再確認が済むと再開します。
* **破棄**: GUI は取り消しを検知すると `_reconnect(restore=False)`。`CameraRuntime.abandon()` はスレッドを止めるだけで、ゲームには何も書きません（`stop()` と `restore()` は書き込みます）。
  その後、新しいゲームの Serial/CRC に合うアダプターを選び直します。未対応ゲームなら書き込み不可のまま「未対応」と表示し、あとで対応ゲームが起動すれば自動で切り替わります。
* 画面を閉じる・「再接続」を押す直前にも `_teardown()` が自分でゲームを確認します。不一致なら `restore()` をしません。

### 残る時間窓

ゲーム切替から検知までの間（最大でリース 0.25 秒）は、旧アダプターの書き込みを止められません。PINE にはゲーム切替の通知がないためです。
この間に、新しいゲームの起動直後のメモリへ旧アドレスの書き込みが届く可能性は残ります（旧ランタイムの通常の書き込みが最大 0.25 秒分。`restore()` のような一括の復元書き込みは、確認が済むまで行われません）。時間窓の短縮は確認頻度と PINE 負荷のトレードオフです。

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

標準では有効になりません。このクローンで使うときだけ:

```bash
git config core.hooksPath tools/git-hooks     # 有効化（コミット前に --staged 監査）
git config --unset core.hooksPath             # 解除
git commit --no-verify                        # 1 回だけ飛ばす
```

Python が見つからない環境ではフックは警告だけ出してコミットを妨げません。

## テスト

| ID | 内容 | テスト |
|---|---|---|
| P1-01 | 同じゲームで動作継続、不要な再接続なし | `tests/test_gui.py::test_same_game_keeps_its_runtime_and_the_orbit` |
| P1-02 | 同一接続でゲームだけ替わる → 書き込み停止 | `tests/test_game_guard.py`、`tests/test_gui.py::test_switching_to_an_unsupported_game_stops_all_writes` |
| P1-03 | 旧アダプターの `restore()` が新ゲームへ書かない | `test_old_runtime_writes_nothing_after_the_game_changes_and_restore_is_inert`、`test_closing_after_a_silent_game_switch_...` |
| P1-04 | 対応ゲーム間の切替で新アダプター | `test_switching_between_supported_games_selects_the_new_adapter` |
| P1-05 | 未対応ゲームは書き込み禁止・表示あり | `test_switching_to_an_unsupported_game_...`、`test_unsupported_game_is_noticed_when_a_supported_one_starts` |
| P1-06 | PCSX2 再起動 | `test_pcsx2_restart_with_*`、実機 `tools/game_switch_check.py`、`tools/gui_freeze_check.py --kill --relaunch` |
| P1-07 | 性能 | `test_the_lease_costs_two_identity_reads_per_expiry_not_per_write`、`test_the_status_poller_checks_the_game_...` |
| P2-01〜06 | 監査 | `tests/test_audit_repo.py`（一時 Git リポジトリ、ダミーデータのみ） |
