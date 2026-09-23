# CLAUDE.md

このリポジトリで作業する Claude Code セッション向けの規約です。

## リポジトリの位置づけ

- `origin` = `akabee0161/YaneuraOu-ScriptCollection`（本家 `yaneurao/YaneuraOu-ScriptCollection` の fork、public）
- `upstream` = 本家 `yaneurao/YaneuraOu-ScriptCollection`
- 本家に PR・Issue・コメントを送るのは、ユーザーが明示的に頼んだときだけ。デフォルトでは fork 内で完結させる。
- PR・Issue を作るときは `gh pr create -R akabee0161/YaneuraOu-ScriptCollection --base main` のように必ず `-R` で fork を明示する。`gh`・Web UI とも既定の向き先が本家になりやすいので注意。
- fork の `main` が本家と分岐していても正常（本家への追随は必須ではない）。本家の更新を取り込みたい場合は `git fetch upstream && git merge upstream/main`。

## コミットメッセージ規約

既存の慣例に従う。

- スクリプトの変更: `YOSC : <対象>、<変更内容>。`（例: `YOSC : BookMiner、book_to_ki2.pyにCLIを追加`）
- ドキュメント・設定ファイルなど: 簡潔な日本語の説明的タイトル（例: `BookMiner/book/の保存ルールを.gitignoreに明文化`）

## `BookMiner/book/` の git 保存ルール

`BookMiner/book/` 配下は `.gitignore` で丸ごと除外されている。生成される定跡DB・KI2エクスポート・作業用キューファイルは大きく、頻繁に再生成されるため。

**例外**: `peta_start_sfens-YYYYMMDD.txt`（ハイフン区切り日付）だけはコミット対象。これは「どの局面を重点的に掘るか」という小さな意思決定の記録であり、`book_miner-*.db` のような大きい生成データとは性質が異なる。

- `think_sfens*.txt` は日付付きでも**コミット対象外**（使い捨ての投入指示書であり、意思決定記録ではない）
- 新しい掘削起点に切り替えるときは、`book/peta_start_sfens.txt`（実際に使われる設定）と同じ内容を `book/peta_start_sfens-YYYYMMDD.txt` として保存し、後者だけをコミットする

詳細は `.gitignore` 内のコメントを参照。

## BookMiner 運用時の注意

- `book_to_ki2.py` は引数なしで実行できる（最新の `peta_book`、`peta_start_sfens.txt` の1行目、`book/kif/exported.ki2` への上書きをそれぞれ自動選択）
- 自動enqueueが高速に回り続けている間、GUIの「自動enqueue」チェックボックスは無効化されて操作を受け付けない（`BookMiner/docs/08-gui.md` 参照）。止められない場合はプロセスを直接 `kill` する
- `book/backup/` は周回のたびに肥大化しうる（`BookMiner/docs/07-backup-and-recovery.md` 参照）。定期的に最新の `book_miner-*.db`・`peta_book-*.db` の組だけ残してクリーンアップする
