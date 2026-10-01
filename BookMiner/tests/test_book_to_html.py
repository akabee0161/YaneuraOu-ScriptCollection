import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cshogi  # noqa: E402

import book_to_html as bh  # noqa: E402
import book_to_ki2 as bk  # noqa: E402
from book_to_ki2 import BookLib  # noqa: E402


def key_after(*moves):
    board = cshogi.Board()
    for m in moves:
        board.push_usi(m)
    return bk.book_key(board)


def bm(move, value, depth=0):
    return BookLib.BookMove(move, "none", value, depth, 1)


def embedded_data(html):
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


class CollectPositionsTest(unittest.TestCase):
    def test_lists_positions_at_target_ply_with_path_and_black_view_values(self):
        book = {
            key_after(): [bm("7g7f", 50, 2), bm("2g2f", 40, 1)],
            key_after("7g7f"): [bm("3c3d", -50, 1)],
            key_after("2g2f"): [bm("8c8d", -40)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 30)],
            key_after("2g2f", "8c8d"): [bm("7g7f", 20)],
        }
        entries = bh.collect_positions(book, bk.SFEN_START_PLY1, [], 1)
        by_path = {tuple(e.path): e for e in entries}
        self.assertEqual(set(by_path), {("▲７六歩",), ("▲２六歩",)})
        e = by_path[("▲７六歩",)]
        self.assertEqual(e.last_usi, "7g7f")
        # 後手番の局面の value -50 は先手視点で +50
        self.assertEqual(e.candidates, [("△３四歩", 50, 1)])
        self.assertTrue(e.sfen.endswith(" w - 2"))

    def test_position_reached_by_transposition_is_listed_once_at_shortest_ply(self):
        book = {
            key_after(): [bm("7g7f", 50, 1), bm("2g2f", 40, 1)],
            key_after("7g7f"): [bm("3c3d", -50, 1)],
            key_after("2g2f"): [bm("3c3d", -40, 1)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 30, 1)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 30, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -30)],
        }
        entries = bh.collect_positions(book, bk.SFEN_START_PLY1, [], 3)
        self.assertEqual([e.path for e in entries], [["▲７六歩", "△３四歩", "▲２六歩"]])

    def test_plies_match_book_to_ki2_placement_without_prefix(self):
        # root の手順が無ければ、手数は book_to_ki2 の配置と一致する(本線上の局面は本線の手数に固定)
        book = {
            key_after(): [bm("7g7f", 30, 1), bm("2g2f", 40, 1)],
            key_after("2g2f"): [bm("3c3d", -40, 1)],
            key_after("7g7f"): [bm("3c3d", -30, 1)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 30, 1)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 30, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -30, 1)],
            key_after("7g7f", "3c3d", "2g2f", "8c8d"): [bm("2f2e", 30)],
        }
        line = bk.mainline_moves(book, bk.make_board(bk.SFEN_START_PLY1), set())
        expected = bk.placement_plies(book, bk.SFEN_START_PLY1, line)
        for ply in range(6):
            got = {bk.book_key(bk.make_board(e.sfen)) for e in bh.collect_positions(book, bk.SFEN_START_PLY1, [], ply)}
            want = {k for k, p in expected.items() if p == ply and k in book}
            self.assertEqual(got, want, f"ply {ply}")

    def test_positions_branching_off_the_root_line_are_excluded(self):
        # root の手順の途中(初期局面)から分かれる ▲２六歩 系の局面は出さない。
        # 分かれた先から root の局面の子孫に合流する局面は、root を通る手順で出す。
        book = {
            key_after(): [bm("2g2f", 40, 1), bm("7g7f", 30, 1)],
            key_after("2g2f"): [bm("3c3d", -40, 1)],
            key_after("2g2f", "3c3d"): [bm("7g7f", 30, 1)],
            key_after("7g7f", "3c3d"): [bm("2g2f", 30, 1)],
            key_after("7g7f", "3c3d", "2g2f"): [bm("8c8d", -30)],
        }
        prefix = ["7g7f", "3c3d"]
        paths = lambda ply: [e.path for e in bh.collect_positions(book, bk.SFEN_START_PLY1, prefix, ply)]
        self.assertEqual(paths(1), [])
        self.assertEqual(paths(2), [["▲７六歩", "△３四歩"]])
        self.assertEqual(paths(3), [["▲７六歩", "△３四歩", "▲２六歩"]])

    def test_none_and_illegal_moves_are_not_candidates(self):
        book = {key_after(): [bm("none", 0), bm("7g7e", 10), bm("7g7f", 50)]}
        entries = bh.collect_positions(book, bk.SFEN_START_PLY1, [], 0)
        self.assertEqual(entries[0].candidates, [("▲７六歩", 50, 0)])

    def test_root_not_in_book_raises(self):
        with self.assertRaises(bk.RootNotInBookError):
            bh.collect_positions({}, bk.SFEN_START_PLY1, [], 1)


class RenderHtmlTest(unittest.TestCase):
    def test_common_prefix_length(self):
        self.assertEqual(bh.common_prefix_length([["a", "b", "c"], ["a", "b", "d"]]), 2)
        self.assertEqual(bh.common_prefix_length([["a"], ["a", "b"]]), 1)
        self.assertEqual(bh.common_prefix_length([]), 0)

    def test_data_is_embedded_and_script_close_is_escaped(self):
        entry = bh.PositionEntry("sfen x", ["▲７六歩"], "7g7f", [("</script>", 1, 0)])
        html = bh.render_html([entry], {"ply": 1, "root": "startpos", "book": "b.db", "generated": "now"})
        self.assertNotIn("</script>\"", html)
        data = embedded_data(html)
        self.assertEqual(data["meta"]["common"], 1)
        self.assertEqual(data["positions"], [["sfen x", "▲７六歩", "7g7f", [["</script>", 1, 0]]]])


class MainTest(unittest.TestCase):
    def test_writes_html_file(self):
        with tempfile.TemporaryDirectory() as d:
            book_path = Path(d) / "book.db"
            book_path.write_text(
                "#YANEURAOU-DB2016 1.00\n"
                f"sfen {key_after()} 1\n7g7f none 50 2 1\n"
                f"sfen {key_after('7g7f')} 2\n3c3d none -50 1 1\n",
                encoding="utf-8",
            )
            out = Path(d) / "out" / "ply.html"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = bh.main(["--ply", "1", "--book", str(book_path), "--root", "startpos", "--output", str(out)])
            self.assertEqual(rc, 0)
            self.assertIn("1 positions at ply 1", stdout.getvalue())
            data = embedded_data(out.read_text(encoding="utf-8"))
            self.assertEqual(data["meta"]["ply"], 1)
            self.assertEqual(len(data["positions"]), 1)

    def test_no_positions_at_ply_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            book_path = Path(d) / "book.db"
            book_path.write_text(f"#YANEURAOU-DB2016 1.00\nsfen {key_after()} 1\n7g7f none 50 2 1\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = bh.main(["--ply", "5", "--book", str(book_path), "--root", "startpos",
                              "--output", str(Path(d) / "x.html")])
            self.assertEqual(rc, 1)
            self.assertIn("no book positions at ply 5", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
