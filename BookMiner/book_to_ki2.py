"""
定跡DB(.db / .ybb)を、変化付きのKI2棋譜に書き出す閲覧用ツール。

各局面の先頭候補(best)を本線、2番目以降の候補を変化として出力する。
仕様: docs/superpowers/specs/2026-09-23-book-to-ki2-design.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import cshogi

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
