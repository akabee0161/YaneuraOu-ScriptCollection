"""
定跡DB(.db / .ybb)を、変化付きのKI2棋譜に書き出す閲覧用ツール。

各局面の先頭候補(best)を本線、2番目以降の候補を変化として出力する。
仕様: docs/superpowers/specs/2026-09-23-book-to-ki2-design.md
"""
from __future__ import annotations

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


class BookTreeBuilder:
    """
    board を push/pop しながら定跡DBを DFS し、KifuNode 木を作る。
    先頭候補から深く潜るので、合流局面は本線寄りの手順で先に展開される。
    """

    def __init__(self, book: dict[str, list[BookLib.BookMove]], board: cshogi.Board, max_depth: int | None):
        self.book = book
        self.board = board
        self.max_depth = max_depth
        self.expanded: set[str] = set()
        self.warnings: list[str] = []

    def candidates(self, depth: int, path: set[str], skip_move: str | None = None) -> list[KifuNode]:
        """現局面の定跡候補(skip_move を除く)をノード化し、それぞれの子局面を展開する。"""
        board = self.board
        nodes: list[KifuNode] = []
        for book_move in self.book.get(book_key(board), []):
            if book_move.move in ("none", skip_move):
                continue
            move = usi_to_move(board, book_move.move)
            if move is None:
                self.warnings.append(f"skip illegal move {book_move.move} / {board.sfen()}")
                continue

            node = KifuNode(KI2.move_to_ki2(move, board), format_comment(book_move, board.turn))
            board.push(move)
            child_key = book_key(board)
            if child_key in path:
                node.comment += " 循環のため打ち切り"
            elif child_key in self.expanded:
                node.comment += " 既出局面に合流"
            elif self.max_depth is None or depth + 1 < self.max_depth:
                node.children = self.expand(depth + 1, path | {child_key})
            board.pop()
            nodes.append(node)
        return nodes

    def expand(self, depth: int, path: set[str]) -> list[KifuNode]:
        key = book_key(self.board)
        if key not in self.book:
            return []
        self.expanded.add(key)
        return self.candidates(depth, path)


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
        levels.append([node] + builder.candidates(0, path, skip_move=usi))
        board.push(move)

    path.add(book_key(board))
    roots = builder.candidates(0, path)
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
            lines.append("*" + head.comment)
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
