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


if __name__ == "__main__":
    unittest.main()
