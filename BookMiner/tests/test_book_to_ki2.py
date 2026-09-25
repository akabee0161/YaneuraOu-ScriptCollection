import contextlib
import io
import os
import sys
import tempfile
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
            ("▲７六歩", "評価値 +50 depth 2\n他候補(未探索): ▲２六歩 +40", [
                ("△３四歩", "評価値 +50 depth 1\n他候補(未探索): △８四歩 +60", [
                    ("▲２六歩", "評価値 +30 depth 0", []),
                ]),
            ]),
        ])
        self.assertEqual(tree.positions, 3)

    def test_explored_alternative_is_variation(self):
        book = {
            key_after(): [bm("7g7f", 50, 1), bm("2g2f", 40, 1)],
            key_after("2g2f"): [bm("8c8d", -40)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "評価値 +50 depth 1", []),
            ("▲２六歩", "評価値 +40 depth 1", [("△８四歩", "評価値 +40 depth 0", [])]),
        ])

    def test_first_candidate_with_depth_0_is_kept_as_move(self):
        book = {key_after(): [bm("7g7f", 50), bm("2g2f", 40)]}
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "評価値 +50 depth 0\n他候補(未探索): ▲２六歩 +40", []),
        ])
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
            ("▲７六歩", "定跡候補外\n他候補(未探索): ▲２六歩 +40", [("△３四歩", "評価値 +50 depth 0", [])]),
        ])
        self.assertEqual(tree.positions, 2)

    def test_prefix_move_in_book_candidates(self):
        book = {
            key_after(): [bm("2g2f", 40), bm("7g7f", 30, 1)],
            key_after("7g7f"): [bm("3c3d", -30)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(flatten(tree.roots), [
            ("▲７六歩", "評価値 +30 depth 1\n他候補(未探索): ▲２六歩 +40", [("△３四歩", "評価値 +30 depth 0", [])]),
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
            ("▲７六歩", "定跡候補外\n他候補(未探索): ▲２六歩 +40", []),
        ])

    def test_alternative_reaching_prefix_position_is_dropped(self):
        # 変化(2g2f 3c3d 7g7f)は prefix上の局面(7g7f 3c3d 2g2f)に合流するので、枝ごと出力しない
        book = {
            key_after(): [bm("7g7f", 50, 3), bm("2g2f", 40, 3)],
            key_after("2g2f"): [bm("3c3d", -40, 2)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f", "3c3d", "2g2f"])
        self.assertEqual(len(tree.roots), 1)
        trunk_end = tree.roots[0].children[0].children[0]
        self.assertEqual([n.ki2 for n in trunk_end.children], ["△８四歩"])

    def test_mainline_is_expanded_before_prefix_alternatives(self):
        # prefix 7g7f の変化 2g2f 3c3d 7g7f が、本線 7g7f 3c3d 2g2f と同じ局面に行き着く。
        # 本線を先に展開するので、本線は打ち切られず、変化のほうが出力されない。
        book = {
            key_after(): [bm("7g7f", 50, 4), bm("2g2f", 40, 4)],
            key_after("7g7f"): [bm("3c3d", -50, 3)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 50, 2)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50, 1)],
            key_after("7g7f", "3c3d", "2g2f", "8c8d"): [bm("2f2e", 50)],
            key_after("2g2f"): [bm("3c3d", -40, 3)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40, 2)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, ["7g7f"])
        self.assertEqual(len(tree.roots), 1)
        line = []
        nodes = tree.roots
        while nodes:
            line.append(nodes[0].ki2)
            self.assertNotIn("合流", nodes[0].comment)
            nodes = nodes[0].children
        self.assertEqual(line, ["▲７六歩", "△３四歩", "▲２六歩", "△８四歩", "▲２五歩"])

    def test_branch_with_new_position_survives_merge_pruning(self):
        # 変化 2g2f 3c3d の先: 7g7f は合流(出さない)、1g1f は新しい局面(出す)
        book = {
            key_after(): [bm("7g7f", 50, 3), bm("2g2f", 40, 3)],
            key_after("7g7f"): [bm("3c3d", -50, 2)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 50, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50)],
            key_after("2g2f"): [bm("3c3d", -40, 2)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40, 1), bm("1g1f", 30, 1)],
            key_after("2g2f", "3c3d", "1g1f"): [bm("8c8d", -30)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual(flatten(tree.roots[1:]), [
            ("▲２六歩", "評価値 +40 depth 3", [
                ("△３四歩", "評価値 +40 depth 2", [
                    ("▲１六歩", "評価値 +30 depth 1", [("△８四歩", "評価値 +30 depth 0", [])]),
                ]),
            ]),
        ])

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
            key_after(): [bm("7g7f", 50, 3), bm("2g2f", 40, 3)],
            key_after("7g7f"): [bm("3c3d", -50, 2)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 50, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -50)],
            key_after("2g2f"): [bm("3c3d", -40, 2)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 40, 1)],
        }
        tree = bk.build_kifu(book, bk.SFEN_START_PLY1, [])
        self.assertEqual([n.ki2 for n in tree.roots], ["▲７六歩"])
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


def node(ki2, *children, comment=None):
    return bk.KifuNode(ki2, comment, list(children))


def tree_of(*roots, sfen=None):
    board = bk.make_board(sfen or bk.SFEN_START_PLY1)
    return bk.KifuTree(board, list(roots), 0, [])


class RenderKi2Test(unittest.TestCase):
    def test_header_and_comments(self):
        text = bk.render_ki2(tree_of(node("▲７六歩", comment="評価値 +50 depth 0")))
        self.assertEqual(text, "手合割：平手\n先手：\n後手：\n\n▲７六歩\n*評価値 +50 depth 0\n")

    def test_multiline_comment(self):
        text = bk.render_ki2(tree_of(node("▲７六歩", comment="評価値 +50 depth 1\n他候補(未探索): ▲２六歩 +40")))
        self.assertTrue(text.endswith("▲７六歩\n*評価値 +50 depth 1\n*他候補(未探索): ▲２六歩 +40\n"))

    def test_variations_are_written_deepest_first(self):
        # 本線 A-B-C、2手目に B2/B3、1手目に A2(その先 X とその変化 X2)
        roots = [
            node("A", node("B", node("C")), node("B2"), node("B3")),
            node("A2", node("X"), node("X2")),
        ]
        text = bk.render_ki2(tree_of(*roots))
        body = text.split("\n\n", 1)[1]
        self.assertEqual(body, "\n".join([
            "A", "B", "C",
            "", "変化：2手", "B2",
            "", "変化：2手", "B3",
            "", "変化：1手", "A2", "X",
            "", "変化：2手", "X2",
        ]) + "\n")

    def test_nested_variation_inside_variation(self):
        # 1手目の変化 A2 の先の 3手目に分岐があるケース
        roots = [
            node("A", node("B", node("C"))),
            node("A2", node("Y", node("Z"), node("Z2"))),
        ]
        body = bk.render_ki2(tree_of(*roots)).split("\n\n", 1)[1]
        self.assertEqual(body, "\n".join([
            "A", "B", "C",
            "", "変化：1手", "A2", "Y", "Z",
            "", "変化：3手", "Z2",
        ]) + "\n")

    def test_non_startpos_uses_bod(self):
        sfen = "lnsgkgsnl/1r5b1/ppppppppp/9/9/2P6/PP1PPPPPP/1B5R1/LNSGKGSNL w - 2"
        text = bk.render_ki2(tree_of(node("△３四歩"), sfen=sfen))
        self.assertTrue(text.startswith("後手の持駒："))
        self.assertIn("後手番\n先手：\n後手：\n\n△３四歩\n", text)
        self.assertNotIn("手合割", text)


DB_TEXT = """#YANEURAOU-DB2016 1.00
sfen lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1
7g7f none 50 1 1
2g2f none 40 0 1
sfen lnsgkgsnl/1r5b1/ppppppppp/9/9/2P6/PP1PPPPPP/1B5R1/LNSGKGSNL w - 2
3c3d none -50 0 1
"""


class FindLatestBookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prefers_peta_book_over_book_miner(self):
        (self.dir / "book_miner-20260923093633_77.db").touch()
        (self.dir / "peta_book-20260923093152_35.db").touch()
        (self.dir / "peta_book-20260923124745_9812.db").touch()
        self.assertEqual(
            bk.find_latest_book(self.dir),
            self.dir / "peta_book-20260923124745_9812.db",
        )

    def test_falls_back_to_book_miner_when_no_peta_book(self):
        (self.dir / "book_miner-20260923093152_35.db").touch()
        (self.dir / "book_miner-20260923093633_77.db").touch()
        self.assertEqual(
            bk.find_latest_book(self.dir),
            self.dir / "book_miner-20260923093633_77.db",
        )

    def test_raises_when_directory_has_no_book(self):
        with self.assertRaises(ValueError):
            bk.find_latest_book(self.dir)

    def test_raises_when_directory_missing(self):
        with self.assertRaises(ValueError):
            bk.find_latest_book(self.dir / "no-such-dir")


class DefaultRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "peta_start_sfens.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_startpos(self):
        self.assertEqual(bk.default_root(self.path), "startpos")

    def test_first_nonblank_line_is_used(self):
        self.path.write_text("\nstartpos moves 7g7f 3c3d\nstartpos moves 2g2f\n", encoding="utf-8")
        self.assertEqual(bk.default_root(self.path), "startpos moves 7g7f 3c3d")

    def test_blank_file_is_startpos(self):
        self.path.write_text("\n\n", encoding="utf-8")
        self.assertEqual(bk.default_root(self.path), "startpos")


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.book = self.dir / "book.db"
        self.book.write_text(DB_TEXT, encoding="utf-8")
        self.out = self.dir / "out.ki2"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = bk.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_writes_cp932_ki2(self):
        code, out, _ = self.run_main("--book", str(self.book), "--output", str(self.out))
        self.assertEqual(code, 0)
        text = self.out.read_text(encoding="cp932")
        self.assertIn("▲７六歩\n*評価値 +50 depth 1\n*他候補(未探索): ▲２六歩 +40\n△３四歩\n", text)
        self.assertNotIn("変化：", text)
        self.assertIn("2 moves, 2/2 positions", out)

    def test_unreachable_positions_are_reported(self):
        orphan = "sfen lnsgkgsnl/1r5b1/ppppppppp/9/9/6P2/PPPPPP1PP/1B5R1/LNSGKGSNL w - 2\n8c8d none 0 0 1\n"
        self.book.write_text(DB_TEXT + orphan, encoding="utf-8")
        code, out, err = self.run_main("--book", str(self.book), "--output", str(self.out))
        self.assertEqual(code, 0)
        self.assertIn("2 moves, 2/3 positions", out)
        self.assertIn("note: 1 positions in the book are not reachable from root", err)

    def test_root_not_in_book_is_error(self):
        code, _, err = self.run_main(
            "--book", str(self.book), "--output", str(self.out),
            "--root", "sfen lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL w - 1",
        )
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error: no position on the root line is in the book"))
        self.assertFalse(self.out.exists())

    def test_missing_book_is_error(self):
        code, _, err = self.run_main("--book", str(self.dir / "nope.db"), "--output", str(self.out))
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error: "))

    def test_max_depth_must_be_positive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            bk.main(["--book", str(self.book), "--output", str(self.out), "--max-depth", "0"])
        self.assertEqual(cm.exception.code, 2)

    def test_all_args_omitted_uses_defaults(self):
        cwd = Path.cwd()
        os.chdir(self.dir)
        try:
            (self.dir / "book/backup").mkdir(parents=True)
            (self.dir / "book/backup/book_miner-20260923093152_35.db").write_text(DB_TEXT, encoding="utf-8")
            (self.dir / "book/peta_start_sfens.txt").write_text("startpos moves 7g7f\n", encoding="utf-8")
            code, out, _ = self.run_main()
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        written = (self.dir / "book/kif/exported.ki2").read_text(encoding="cp932")
        self.assertIn("▲７六歩\n*評価値 +50 depth 1\n*他候補(未探索): ▲２六歩 +40\n△３四歩\n", written)
        self.assertIn("2 moves, 2/2 positions", out)


if __name__ == "__main__":
    unittest.main()
