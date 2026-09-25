"""
定跡DB(.db / .ybb)を、変化付きのKI2棋譜に書き出す閲覧用ツール。

各局面の先頭候補(best)を本線、2番目以降の候補を変化として出力する。
未探索(depth 0)の2番目以降の候補は変化にせず、本線の手のコメントに列挙する。
既出局面に合流するだけの変化は出力しない。
仕様: docs/superpowers/specs/2026-09-23-book-to-ki2-design.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cshogi
from cshogi import KI2, KIF

COMMON_LIB_DIR = Path(__file__).resolve().parent.parent / "CommonLib"
sys.path.insert(0, str(COMMON_LIB_DIR))

import YaneuraOuBookLib as BookLib  # noqa: E402

SFEN_START_PLY1 = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"


def parse_root(s: str) -> tuple[str, list[str]]:
    """
    root指定文字列を (手数つき開始sfen, USI手のリスト) に分解する。
    think_sfens.txt の行をそのまま渡せるよう、最初の ',' 以降は無視する。
    """
    s = s.split(",", 1)[0].strip()
    if s.startswith("position "):
        s = s[len("position "):].strip()

    sfen, sep, moves_str = s.partition(" moves ")
    moves = moves_str.split() if sep else []

    sfen = sfen.strip()
    if sfen == "startpos":
        sfen = SFEN_START_PLY1
    elif sfen.startswith("sfen "):
        sfen = sfen[len("sfen "):].strip()
    else:
        raise ValueError(f"root must start with 'startpos' or 'sfen': {s}")

    return sfen, moves


def book_key(board: cshogi.Board) -> str:
    """定跡DB(ignore_book_ply=True で読んだもの)を引くための、手数なしsfen。"""
    return BookLib.trim_number(board.sfen())


@dataclass
class KifuNode:
    """棋譜木の1手。children[0] が本線、children[1:] が変化。"""
    ki2: str
    comment: str | None = None
    children: list["KifuNode"] = field(default_factory=list)


@dataclass
class KifuTree:
    start_board: cshogi.Board
    roots: list[KifuNode]
    positions: int
    warnings: list[str]


class RootNotInBookError(ValueError):
    pass


def make_board(sfen: str) -> cshogi.Board:
    # Board().set_sfen() は不正sfenで C++ 例外がプロセスを abort させる。
    # コンストラクタ経由なら RuntimeError として捕捉できる。
    try:
        return cshogi.Board(sfen)
    except RuntimeError as exc:
        raise ValueError(f"invalid sfen: {sfen}") from exc


def usi_to_move(board: cshogi.Board, usi: str) -> int | None:
    """合法手なら move32、そうでなければ None。"""
    try:
        move = board.move_from_usi(usi)
    except Exception:
        return None
    if not move or not board.is_legal(move):
        return None
    return move


def format_comment(book_move: BookLib.BookMove, turn: int) -> str:
    # DBの value は手番側視点。棋譜ビューアの慣習に合わせて先手視点で表示する。
    value = book_move.value if turn == cshogi.BLACK else -book_move.value
    return f"評価値 {value:+d} depth {book_move.depth}"


def add_unexplored(node: KifuNode, unexplored: list[str]) -> None:
    if unexplored:
        line = "他候補(未探索): " + " / ".join(unexplored)
        node.comment = f"{node.comment}\n{line}" if node.comment else line


class BookTreeBuilder:
    """
    board を push/pop しながら定跡DBを DFS し、KifuNode 木を作る。
    先頭候補から深く潜るので、合流局面は本線寄りの手順で先に展開される。
    既出局面に合流する手と、その先が合流だけの手は木に入れない。
    """

    def __init__(self, book: dict[str, list[BookLib.BookMove]], board: cshogi.Board, max_depth: int | None):
        self.book = book
        self.board = board
        self.max_depth = max_depth
        self.expanded: set[str] = set()
        self.warnings: list[str] = []

    def candidates(
        self, depth: int, path: set[str], skip_move: str | None = None
    ) -> tuple[list[KifuNode], list[str], bool]:
        """
        現局面の定跡候補(skip_move を除く)をノード化し、それぞれの子局面を展開する。
        返り値は (ノード, 変化にしなかった未探索候補の表記, 合流で落とした手があったか)。
        skip_move が None なら先頭の候補は本線なので、depth 0 でもノードにする。
        """
        board = self.board
        nodes: list[KifuNode] = []
        unexplored: list[str] = []
        dropped_merge = False
        is_main = skip_move is None
        for book_move in self.book.get(book_key(board), []):
            if book_move.move in ("none", skip_move):
                continue
            move = usi_to_move(board, book_move.move)
            if move is None:
                self.warnings.append(f"skip illegal move {book_move.move} / {board.sfen()}")
                continue

            ki2 = KI2.move_to_ki2(move, board)
            comment = format_comment(book_move, board.turn)
            if book_move.depth == 0 and not is_main:
                unexplored.append(f"{ki2} {comment.split()[1]}")
                continue
            is_main = False

            node = KifuNode(ki2, comment)
            board.push(move)
            child_key = book_key(board)
            keep = True
            if child_key in path:
                node.comment += " 循環のため打ち切り"
            elif child_key in self.expanded:
                keep = False
            elif self.max_depth is None or depth + 1 < self.max_depth:
                children = self.expand(depth + 1, path | {child_key})
                if children is None:
                    keep = False
                else:
                    node.children = children
            board.pop()
            if keep:
                nodes.append(node)
            else:
                dropped_merge = True
        return nodes, unexplored, dropped_merge

    def expand(self, depth: int, path: set[str]) -> list[KifuNode] | None:
        """現局面の子ノード。None は候補がすべて合流で落ち、この局面へ至る手を出す意味がないことを示す。"""
        key = book_key(self.board)
        if key not in self.book:
            return []
        self.expanded.add(key)
        nodes, unexplored, dropped_merge = self.candidates(depth, path)
        if not nodes:
            return None if dropped_merge else []
        add_unexplored(nodes[0], unexplored)
        return nodes


def build_kifu(
    book: dict[str, list[BookLib.BookMove]],
    start_sfen: str,
    prefix_moves: list[str],
    max_depth: int | None = None,
) -> KifuTree:
    """
    開始局面から prefix を本線として進め、その先を定跡DBで展開した棋譜木を作る。
    prefix 上の局面がDBにあれば、その局面の他の候補も変化として展開する。
    """
    # prefix の合法性確認と、prefix 上の全局面キーの収集
    board = make_board(start_sfen)
    moves: list[int] = []
    line_keys = [book_key(board)]
    for usi in prefix_moves:
        move = usi_to_move(board, usi)
        if move is None:
            raise ValueError(f"illegal root move: {usi} / {board.sfen()}")
        moves.append(move)
        board.push(move)
        line_keys.append(book_key(board))

    if not any(key in book for key in line_keys):
        raise RootNotInBookError(
            f"no position on the root line is in the book: {board.sfen()} "
            "(--root で定跡DBに含まれる局面を指定してください)"
        )

    builder = BookTreeBuilder(book, make_board(start_sfen), max_depth)
    # prefix 上の局面は本線で表示されるので、変化側から到達したら合流扱いにする
    builder.expanded.update(key for key in line_keys if key in book)
    board = builder.board

    # 本線の続きを prefix 上の変化より先に展開する。
    # 後にすると、手順前後で本線の局面に先に到達した変化に続きを取られ、本線が合流で切れる。
    for move in moves:
        board.push(move)
    roots, unexplored, _ = builder.candidates(0, set(line_keys))
    if roots:
        add_unexplored(roots[0], unexplored)
    for _ in moves:
        board.pop()

    path: set[str] = set()
    levels: list[list[KifuNode]] = []
    for usi, move in zip(prefix_moves, moves):
        key = book_key(board)
        path.add(key)
        comment = None
        if key in book:
            book_move = next((m for m in book[key] if m.move == usi), None)
            comment = format_comment(book_move, board.turn) if book_move else "定跡候補外"
        node = KifuNode(KI2.move_to_ki2(move, board), comment)
        alternatives, unexplored, _ = builder.candidates(0, path, skip_move=usi)
        add_unexplored(node, unexplored)
        levels.append([node] + alternatives)
        board.push(move)

    for level in reversed(levels):
        level[0].children = roots
        roots = level
    return KifuTree(make_board(start_sfen), roots, len(builder.expanded), builder.warnings)


def header_lines(board: cshogi.Board) -> list[str]:
    if book_key(board) == BookLib.trim_number(SFEN_START_PLY1):
        lines = ["手合割：平手"]
    else:
        lines = KIF.board_to_bod(board).split("\n")
    return lines + ["先手：", "後手：", ""]


def write_line(lines: list[str], nodes: list[KifuNode], ply: int) -> None:
    """
    nodes[0] から本線を辿って書き、その後で途中の分岐を手数の大きい順に書く。
    ビューアは「変化：N手」を直前に書かれた手順を遡って接続するため、この順序が必要。
    """
    branches: list[tuple[int, list[KifuNode]]] = []
    while nodes:
        head = nodes[0]
        lines.append(head.ki2)
        if head.comment:
            lines.extend("*" + c for c in head.comment.split("\n"))
        if len(nodes) > 1:
            branches.append((ply, nodes[1:]))
        nodes = head.children
        ply += 1

    for branch_ply, alternatives in reversed(branches):
        for alternative in alternatives:
            lines.append("")
            lines.append(f"変化：{branch_ply}手")
            write_line(lines, [alternative], branch_ply)


def render_ki2(tree: KifuTree) -> str:
    lines = header_lines(tree.start_board)
    write_line(lines, tree.roots, 1)
    return "\n".join(lines) + "\n"


def count_moves(nodes: list[KifuNode]) -> int:
    return sum(1 + count_moves(n.children) for n in nodes)


def positive_int(s: str) -> int:
    value = int(s)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


DEFAULT_BACKUP_DIR = Path("book/backup")
DEFAULT_PETA_START_SFENS_PATH = Path("book/peta_start_sfens.txt")
DEFAULT_OUTPUT_PATH = Path("book/kif/exported.ki2")


def find_latest_book(backup_dir: Path = DEFAULT_BACKUP_DIR) -> Path:
    """
    backup_dir から最新の peta_book-*.db を選ぶ。無ければ最新の book_miner-*.db にフォールバックする。
    ファイル名末尾のタイムスタンプは文字列ソートで新しい順に並ぶ。
    """
    for pattern in ("peta_book-*.db", "book_miner-*.db"):
        matches = sorted(backup_dir.glob(pattern))
        if matches:
            return matches[-1]
    raise ValueError(f"no book_miner-*.db or peta_book-*.db found in {backup_dir} "
                      "(--book で定跡DBを指定してください)")


def default_root(path: Path = DEFAULT_PETA_START_SFENS_PATH) -> str:
    """path の1行目(空行を除く)を root として使う。無ければ startpos。"""
    if not path.exists():
        return "startpos"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line
    return "startpos"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="定跡DBを変化付きKI2に書き出す")
    parser.add_argument("--book", default=None,
                        help=f"定跡DB (.db / .ybb)。省略時は {DEFAULT_BACKUP_DIR} 内の最新の "
                             "peta_book-*.db (無ければ book_miner-*.db) を自動選択")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH),
                        help=f"出力KI2ファイル (cp932)。省略時は {DEFAULT_OUTPUT_PATH} に上書き")
    parser.add_argument("--root", default=None,
                        help="展開開始局面。'startpos moves ...' / 'sfen ... moves ...' (think_sfens.txtの行も可)。"
                             f"省略時は {DEFAULT_PETA_START_SFENS_PATH} の1行目、無ければ startpos")
    parser.add_argument("--max-depth", type=positive_int, default=None,
                        help="root から出力する定跡手の手数 (省略時は無制限)")
    args = parser.parse_args(argv)

    try:
        book_path = args.book if args.book is not None else str(find_latest_book())
        root = args.root if args.root is not None else default_root()
        start_sfen, prefix_moves = parse_root(root)
        book = BookLib.read_yaneuraou_book(book_path, ignore_book_ply=True)
        tree = build_kifu(book, start_sfen, prefix_moves, args.max_depth)
        text = render_ki2(tree)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="cp932")
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in tree.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    unreachable = len(book) - tree.positions
    if unreachable > 0:
        print(f"note: {unreachable} positions in the book are not reachable from root "
              "(use --root to start from them)", file=sys.stderr)
    print(f"wrote {args.output}: {count_moves(tree.roots)} moves, {tree.positions}/{len(book)} positions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
