# BookMiner

BookMiner は、将棋AIによって、大規模定跡を自動生成するためのスクリプトです。

使い方は次のチュートリアルを順に読んでください。

- [1. 用語説明](docs/01-terms.md)
- [2. セットアップ](docs/02-setup.md)
- [3. USI と position コマンド](docs/03-usi.md)
- [4. 定跡を掘るための基礎](docs/04-basics.md)
- [5. BookMiner.py の主要コマンド](docs/05-commands.md)
- [6. 生成された定跡をやねうら王で使うには](docs/06-use-with-yaneuraou.md)
- [7. バックアップと復旧](docs/07-backup-and-recovery.md)
- [8. GUI で操作する](docs/08-gui.md)
- [9. 既存のやねうら王定跡から掘り始める](docs/09-import-existing-book.md)
- [10. peta shock 化](docs/10-peta-shock.md)
- [11. peta book を使って次に掘る局面を作る](docs/11-peta-operations.md)

GUI で操作したい場合は、次のように起動します。

```bash
python3 BookMiner-gui.py
```

venv に `cshogi` / `json5` をインストールしている場合は、その venv の python で起動してください（詳細は [8. GUI で操作する](docs/08-gui.md) を参照）。

```bash
../venv/bin/python BookMiner-gui.py
```

GUI は `BookMiner.py` を子プロセスとして起動し、既存のコマンドを送信する wrapper です。

## 定跡を棋譜(KI2)に書き出す

掘った定跡DBを、変化付きの KI2 棋譜（cp932）に書き出せます。引数なしで実行すると、`book/backup/` 内の最新の `peta_book-*.db`（無ければ `book_miner-*.db`）を、`book/peta_start_sfens.txt` の1行目の局面から展開し、`book/kif/exported.ki2` に上書きします。

```bash
# 両者の全候補手を辿る
../venv/bin/python book_to_ki2.py

# 先手(black)/後手(white)の手番では最善手だけを辿る（自分が指す側の研究用）
# 出力は book/kif/exported-black.ki2 / exported-white.ki2
../venv/bin/python book_to_ki2.py --side black
../venv/bin/python book_to_ki2.py --side white
```

DB・開始局面・出力先・手数の上限は `--book` / `--root` / `--output` / `--max-depth` で変えられます（`--help` 参照）。全候補版は DB が大きいと数百MBになり、作成に数分かかります。

指定した手数の局面一覧を閲覧用 HTML（1ファイル）に書き出す場合は `book_to_html.py` を使います。`--ply`（開始局面からの手数）は必須で、それ以外の既定値は `book_to_ki2.py` と同じです。

```bash
# 30手目の局面一覧を book/kif/exported.html に書き出す
../venv/bin/python book_to_html.py --ply 30

# --side も指定できる（出力は exported-black.html / exported-white.html）
../venv/bin/python book_to_html.py --ply 30 --side black
../venv/bin/python book_to_html.py --ply 30 --side white
```
