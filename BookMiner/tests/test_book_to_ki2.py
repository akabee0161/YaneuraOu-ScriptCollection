import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cshogi  # noqa: E402

import book_to_ki2 as bk  # noqa: E402


class ParseRootTest(unittest.TestCase):
    def test_startpos(self):
        self.assertEqual(bk.parse_root("startpos"), (bk.SFEN_START_PLY1, []))

    def test_startpos_moves(self):
        self.assertEqual(
            bk.parse_root("startpos moves 7g7f 3c3d"),
            (bk.SFEN_START_PLY1, ["7g7f", "3c3d"]),
        )

    def test_position_prefix_and_sfen(self):
        sfen = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL w - 2"
        self.assertEqual(
            bk.parse_root(f"position sfen {sfen} moves 3c3d"),
            (sfen, ["3c3d"]),
        )

    def test_think_sfens_meta_is_ignored(self):
        line = "startpos moves 7g7f 4a3b, book_extend_ply=6, eval_limit=400, game_ply_limit=200"
        self.assertEqual(bk.parse_root(line), (bk.SFEN_START_PLY1, ["7g7f", "4a3b"]))

    def test_invalid_prefix_raises(self):
        with self.assertRaises(ValueError):
            bk.parse_root("7g7f 3c3d")


class BookKeyTest(unittest.TestCase):
    def test_ply_is_trimmed(self):
        board = cshogi.Board()
        self.assertEqual(
            bk.book_key(board),
            "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -",
        )


import YaneuraOuBookLib as BookLib  # noqa: E402  (bk の import で CommonLib が sys.path に入っている)


def key_after(*moves):
    board = cshogi.Board()
    for m in moves:
        board.push_usi(m)
    return bk.book_key(board)


def bm(move, value, depth=0):
    return BookLib.BookMove(move, "none", value, depth, 1)


def flatten(nodes):
    """テスト用: 木を (ki2, comment, [子...]) の入れ子タプルにする。"""
    return [(n.ki2, n.comment, flatten(n.children)) for n in nodes]


class BuildKifuTest(unittest.TestCase):
    def test_mainline_and_branches(self):
        book = {
            key_after(): [bm("7g7f", 50, 2), bm("2g2f", 40)],
            key_after("7g7f"): [bm("3c3d", -50, 1), bm("8c8d", -60)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 30)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "評価値 +50 depth 2", [
                ("△３四歩", "評価値 +50 depth 1", [
                    ("▲２六歩", "評価値 +30 depth 0", []),
                ]),
                ("△８四歩", "評価値 +60 depth 0", []),
            ]),
            ("▲２六歩", "評価値 +40 depth 0", []),
        ])
        self.assertEqual(tree.positions, 3)
        self.assertEqual(tree.warnings, [])

    def test_white_value_is_black_view(self):
        book = {key_after("7g7f"): [bm("3c3d", 120)]}
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(tree.roots[0].children[0].comment, "評価値 -120 depth 0")

    def test_prefix_move_not_in_book_candidates(self):
        # prefix上の局面がDBにあれば他候補を変化として出し、prefixの手が候補外なら注記する
        book = {
            key_after(): [bm("2g2f", 40)],
            key_after("7g7f"): [bm("3c3d", -50)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "定跡候補外", [("△３四歩", "評価値 +50 depth 0", [])]),
            ("▲２六歩", "評価値 +40 depth 0", []),
        ])
        self.assertEqual(tree.positions, 2)

    def test_prefix_move_in_book_candidates(self):
        book = {
            key_after(): [bm("2g2f", 40), bm("7g7f", 30, 1)],
            key_after("7g7f"): [bm("3c3d", -30)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "評価値 +30 depth 1", [("△３四歩", "評価値 +30 depth 0", [])]),
            ("▲２六歩", "評価値 +40 depth 0", []),
        ])

    def test_prefix_position_not_in_book_has_no_comment(self):
        book = {key_after("7g7f"): [bm("3c3d", -50)]}
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", None, [("△３四歩", "評価値 +50 depth 0", [])]),
        ])

    def test_prefix_is_extended_even_if_root_not_in_book(self):
        book = {key_after(): [bm("2g2f", 40)]}
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "定跡候補外", []),
            ("▲２六歩", "評価値 +40 depth 0", []),
        ])

    def test_alternative_reaching_prefix_position_is_merged(self):
        # 変化(2g2f 3c3d 7g7f)が、prefix上の局面(7g7f 3c3d 2g2f)に合流する
        book = {
            key_after(): [bm("7g7f", 50), bm("2g2f", 40)],
            key_after("2g2f"): [bm("3c3d", -40)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f", "3c3d", "2g2f"])
        merged = tree.roots[1].children[0].children[0]
        self.assertEqual(merged.comment, "評価値 +40 depth 0 既出局面に合流")
        self.assertEqual(merged.children, [])
        trunk_end = tree.roots[0].children[0].children[0]
        self.assertEqual([n.ki2 for n in trunk_end.children], ["△８四歩"])

    def test_max_depth(self):
        book = {
            key_after(): [bm("7g7f", 50)],
            key_after("7g7f"): [bm("3c3d", -50)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [], max_depth=1)
        self.assertEqual(flatten(tree.roots), [("▲７六歩", "評価値 +50 depth 0", [])])

    def test_cycle_is_cut(self):
        book = {
            key_after(): [bm("5i5h", 0)],
            key_after("5i5h"): [bm("5a5b", 0)],
            key_after("5i5h", "5a5b"): [bm("5h5i", 0)],
            key_after("5i5h", "5a5b", "5h5i"): [bm("5b5a", 0)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        node = tree.roots[0].children[0].children[0].children[0]
        self.assertEqual(node.ki2, "△５一玉")
        self.assertEqual(node.comment, "評価値 +0 depth 0 循環のため打ち切り")
        self.assertEqual(node.children, [])

    def test_transposition_is_not_repeated(self):
        book = {
            key_after(): [bm("7g7f", 50), bm("2g2f", 40)],
            key_after("7g7f"): [bm("3c3d", -50)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 50)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50)],
            key_after("2g2f"): [bm("3c3d", -40)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        second = tree.roots[1].children[0].children[0]
        self.assertEqual(second.ki2, "▲７六歩")
        self.assertEqual(second.comment, "評価値 +40 depth 0 既出局面に合流")
        self.assertEqual(second.children, [])
        self.assertEqual(tree.positions, 6)

    def test_none_and_illegal_moves_are_skipped(self):
        book = {key_after(): [bm("none", 0), bm("7g7e", 10), bm("7g7f", 5)]}
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual([n.ki2 for n in tree.roots], ["▲７六歩"])
        self.assertEqual(len(tree.warnings), 1)
        self.assertIn("7g7e", tree.warnings[0])

    def test_root_line_not_in_book(self):
        with self.assertRaises(bk.RootNotInBookError):
            bk.build_kifu({}, bk.SFEN_START_PLY1, ["7g7f"])

    def test_illegal_prefix_move(self):
        with self.assertRaises(ValueError):
            bk.build_kifu({}, bk.SFEN_START_PLY1, ["7g7e"])

    def test_invalid_sfen(self):
        with self.assertRaises(ValueError):
            bk.build_kifu({}, "garbage", [])


if __name__ == "__main__":
    unittest.main()
