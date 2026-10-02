"""
定跡DB(.db / .ybb)から、指定した手数の局面をすべて一覧できる閲覧用HTML(1ファイル)を書き出すツール。

一覧にするのは root の手順を進めた局面(掘削の起点)から定跡DBの手で辿れる局面だけで、
root の手順の途中から分かれる局面は含めない。
各局面の手数は、開始局面から root の手順を進め、その先を定跡DBの手で辿った最短手数
(book_to_ki2.py と同じく、root の手順と、その先の先頭候補を辿った本線の上の局面は、その位置の手数)とする。
HTMLにはデータを埋め込むので、外部ファイルやネットワークなしでブラウザで開ける。
--side を指定すると、その手番の局面では最善手だけを辿る(book_to_ki2.py と同じ)。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cshogi
from cshogi import KI2

import book_to_ki2 as bk
from book_to_ki2 import BookLib, book_key, make_board, usi_to_move

DEFAULT_OUTPUT_PATH = Path("book/kif/exported.html")


@dataclass
class Placement:
    """局面の手数と、最短手順での1手前の局面のキー・そこから指した手。開始局面は parent が None。"""
    ply: int
    parent: str | None
    move: int | None


@dataclass
class PositionEntry:
    sfen: str
    path: list[str]
    last_usi: str | None
    # (KI2表記, 先手視点の評価値, depth)。先頭が最善手
    candidates: list[tuple[str, int, int]]


def shortest_placements(
    book: dict[str, list[BookLib.BookMove]], start_sfen: str, line: list[int], max_ply: int,
    expand_from: int = 0,
) -> dict[str, Placement]:
    """
    bk.placement_plies と同じ規則で max_ply 手目までの局面の手数を決め、最短手順を辿れるよう親も記録する。
    line 上の局面は max_ply より先のものも登録し、近道があってもその手数に固定する。
    expand_from 手目より前の局面からは定跡DBの手を辿らない(line 上の局面だけを登録する)。
    """
    board = make_board(start_sfen)
    placements: dict[str, Placement] = {}
    levels: list[list[str]] = []
    parent: str | None = None
    for ply in range(len(line) + 1):
        key = book_key(board)
        levels.append([])
        if key not in placements:
            placements[key] = Placement(ply, parent, line[ply - 1] if ply else None)
            levels[ply].append(board.sfen())
        parent = key
        if ply < len(line):
            board.push(line[ply])

    # max_ply 手目の局面を見つけるところまで展開する(max_ply 手目の局面からは先に進まない)
    ply = expand_from
    while ply < min(len(levels), max_ply):
        for sfen in levels[ply]:
            board = make_board(sfen)
            key = book_key(board)
            for book_move in book.get(key, []):
                move = None if book_move.move == "none" else usi_to_move(board, book_move.move)
                if move is None:
                    continue
                board.push(move)
                child_key = book_key(board)
                if child_key in book and child_key not in placements:
                    placements[child_key] = Placement(ply + 1, key, move)
                    if ply + 1 == len(levels):
                        levels.append([])
                    levels[ply + 1].append(board.sfen())
                board.pop()
        ply += 1
    return placements


def moves_to(placements: dict[str, Placement], key: str) -> list[int]:
    moves: list[int] = []
    placement = placements[key]
    while placement.parent is not None:
        moves.append(placement.move)
        placement = placements[placement.parent]
    return moves[::-1]


def candidate_list(book_moves: list[BookLib.BookMove], board: cshogi.Board) -> list[tuple[str, int, int]]:
    candidates = []
    for book_move in book_moves:
        move = None if book_move.move == "none" else usi_to_move(board, book_move.move)
        if move is None:
            continue
        # DBの value は手番側視点。book_to_ki2 と同じく先手視点にそろえる。
        value = book_move.value if board.turn == cshogi.BLACK else -book_move.value
        candidates.append((KI2.move_to_ki2(move, board), value, book_move.depth))
    return candidates


def collect_positions(
    book: dict[str, list[BookLib.BookMove]], start_sfen: str, prefix_moves: list[str], target_ply: int
) -> list[PositionEntry]:
    """
    root の手順を進めた局面から辿れる局面のうち、開始局面から target_ply 手目に置かれる、定跡DBにある局面の一覧。
    target_ply は平手初期局面からの手数ではなく開始局面からの手数。
    """
    board = make_board(start_sfen)
    moves: list[int] = []
    line_keys = {book_key(board)}
    for usi in prefix_moves:
        move = usi_to_move(board, usi)
        if move is None:
            raise ValueError(f"illegal root move: {usi} / {board.sfen()}")
        moves.append(move)
        board.push(move)
        line_keys.add(book_key(board))
    if not any(key in book for key in line_keys):
        raise bk.RootNotInBookError(
            f"no position on the root line is in the book: {board.sfen()} "
            "(--root で定跡DBに含まれる局面を指定してください)"
        )

    mainline = bk.mainline_moves(book, board, line_keys)
    placements = shortest_placements(book, start_sfen, moves + mainline, target_ply, expand_from=len(moves))

    entries = []
    for key, placement in placements.items():
        if placement.ply != target_ply or key not in book:
            continue
        board = make_board(start_sfen)
        path = []
        last_usi = None
        for move in moves_to(placements, key):
            path.append(KI2.move_to_ki2(move, board))
            last_usi = cshogi.move_to_usi(move)
            board.push(move)
        entries.append(PositionEntry(board.sfen(), path, last_usi, candidate_list(book[key], board)))
    return entries


def common_prefix_length(paths: list[list[str]]) -> int:
    if not paths:
        return 0
    n = min(len(p) for p in paths)
    for i in range(n):
        if any(p[i] != paths[0][i] for p in paths):
            return i
    return n


def render_html(entries: list[PositionEntry], meta: dict) -> str:
    data = {
        "meta": {**meta, "common": common_prefix_length([e.path for e in entries])},
        "positions": [[e.sfen, " ".join(e.path), e.last_usi, e.candidates] for e in entries],
    }
    # </script> でスクリプト要素が閉じないよう、"</" をエスケープして埋め込む
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", payload)


def non_negative_int(s: str) -> int:
    value = int(s)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="定跡DBの指定手数の局面一覧を、閲覧用HTML(1ファイル)に書き出す")
    parser.add_argument("--ply", type=non_negative_int, required=True,
                        help="一覧にする局面の手数 (開始局面からの手数。--root が startpos 系なら平手初期局面からの手数)")
    parser.add_argument("--book", default=None,
                        help=f"定跡DB (.db / .ybb)。省略時は {bk.DEFAULT_BACKUP_DIR} 内の最新の "
                             "peta_book-*.db (無ければ book_miner-*.db) を自動選択")
    parser.add_argument("--output", default=None,
                        help=f"出力HTMLファイル (UTF-8)。省略時は {DEFAULT_OUTPUT_PATH} に上書き"
                             "(--side 指定時はファイル名に -black / -white を付ける)")
    parser.add_argument("--root", default=None,
                        help="開始局面と、手数を固定する手順。'startpos moves ...' / 'sfen ... moves ...' "
                             f"(think_sfens.txtの行も可)。省略時は {bk.DEFAULT_PETA_START_SFENS_PATH} の1行目、無ければ startpos")
    parser.add_argument("--side", choices=bk.SIDES, default=None,
                        help="black(先手)/white(後手) の手番では最善手だけを辿る (省略時は両者とも全候補)")
    args = parser.parse_args(argv)
    output = args.output if args.output is not None else str(bk.default_output_path(DEFAULT_OUTPUT_PATH, args.side))

    try:
        book_path = args.book if args.book is not None else str(bk.find_latest_book())
        root = args.root if args.root is not None else bk.default_root()
        start_sfen, prefix_moves = bk.parse_root(root)
        book = BookLib.read_yaneuraou_book(book_path, ignore_book_ply=True)
        if args.side is not None:
            book = bk.restrict_to_best(book, bk.SIDES[args.side], bk.root_line_moves(start_sfen, prefix_moves))
        entries = collect_positions(book, start_sfen, prefix_moves, args.ply)
        if not entries:
            raise ValueError(f"no book positions at ply {args.ply}")
        meta = {
            "ply": args.ply,
            "root": root.split(",", 1)[0].strip(),
            "book": Path(book_path).name,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_html(entries, meta), encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {output}: {len(entries)} positions at ply {args.ply}")
    return 0


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>定跡局面一覧</title>
<style>
:root {
  --bg: #f6f5f1; --panel: #ffffff; --text: #1d1d1b; --muted: #6b6a65; --line: #dddbd3;
  --accent: #2f6db5; --sel: #e4ecf7; --plus: #1f5fa8; --minus: #b3372f;
  --board: #e9c98b; --board-line: #6f5326; --last: #f3a64a; --from: #f6d39e;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a19; --panel: #242422; --text: #e8e6df; --muted: #9a988f; --line: #3a3936;
    --accent: #7fb0eb; --sel: #2c3a4d; --plus: #84b6f0; --minus: #f08a80;
    --board: #b48d4e; --board-line: #3b2a10; --last: #d7812a; --from: #c79e5e;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font-family: "Hiragino Sans", "Yu Gothic UI", "Meiryo", system-ui, sans-serif; font-size: 14px; }
header { padding: 12px 16px; border-bottom: 1px solid var(--line); background: var(--panel); }
header h1 { font-size: 17px; margin: 0 0 4px; }
header .meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
main { display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 16px; padding: 16px; }
@media (max-width: 960px) { main { grid-template-columns: minmax(0, 1fr); } #detail { order: -1; } }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; min-width: 0; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 12px;
  border-bottom: 1px solid var(--line); }
.controls input, .controls select, .controls button { font: inherit; padding: 4px 8px; color: var(--text);
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px; }
.controls input { flex: 1 1 180px; min-width: 0; }
.controls button:disabled { opacity: .4; }
.count { color: var(--muted); font-size: 12px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; color: var(--muted); font-weight: normal; }
#list tbody tr { cursor: pointer; }
#list tbody tr:hover { background: var(--bg); }
#list tbody tr.selected { background: var(--sel); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.path { color: var(--muted); overflow-wrap: anywhere; }
td.path b { color: var(--text); font-weight: normal; }
.plus { color: var(--plus); } .minus { color: var(--minus); }
#detail { padding: 12px; align-self: start; position: sticky; top: 16px; }
@media (max-width: 960px) { #detail { position: static; } }
.hand { min-height: 22px; font-size: 13px; overflow-wrap: anywhere; }
.board-wrap { display: grid; grid-template-columns: 1fr 18px; grid-template-rows: 16px auto;
  max-width: 400px; margin: 4px auto; }
.files { display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); font-size: 11px; color: var(--muted); text-align: center; }
.ranks { display: grid; grid-template-rows: repeat(9, minmax(0, 1fr)); font-size: 11px; color: var(--muted);
  align-items: center; justify-items: center; }
.board { display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); grid-template-rows: repeat(9, minmax(0, 1fr));
  background: var(--board);
  border: 2px solid var(--board-line); aspect-ratio: 1 / 1; }
.sq { border: .5px solid var(--board-line); display: flex; align-items: center; justify-content: center;
  font-size: clamp(14px, 4.6vw, 24px); line-height: 1; color: #1b1308; user-select: none; }
.sq.gote span { transform: rotate(180deg); }
.sq.promoted { color: #a3150f; }
.sq.last { background: var(--last); }
.sq.from { background: var(--from); }
.info { margin: 10px 0 6px; display: flex; gap: 12px; flex-wrap: wrap; align-items: baseline; }
.info .eval { font-size: 18px; font-variant-numeric: tabular-nums; }
h2 { font-size: 13px; color: var(--muted); font-weight: normal; margin: 12px 0 4px; }
.tag { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; }
.fullpath { font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.fullpath .n { color: var(--muted); font-size: 11px; margin-left: 4px; }
.sfen { display: flex; gap: 6px; }
.sfen code { flex: 1; font-size: 11px; overflow-wrap: anywhere; background: var(--bg); padding: 4px 6px; border-radius: 4px; }
.sfen button { font: inherit; font-size: 12px; color: var(--text); background: var(--bg);
  border: 1px solid var(--line); border-radius: 6px; padding: 2px 8px; }
.empty { padding: 24px; color: var(--muted); text-align: center; }
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <div class="meta" id="meta"></div>
</header>
<main>
  <section>
    <div class="controls">
      <input id="search" type="search" placeholder="手順で絞り込み（例: ▲２五歩、空白区切りでAND）">
      <select id="sort">
        <option value="desc">評価値が高い順（先手有利）</option>
        <option value="asc">評価値が低い順（後手有利）</option>
        <option value="abs">評価値が0に近い順（互角）</option>
        <option value="path">手順順</option>
      </select>
      <button id="prev">前へ</button>
      <span class="count" id="page"></span>
      <button id="next">次へ</button>
    </div>
    <table id="list">
      <thead><tr><th class="num">#</th><th class="num">評価値</th><th>最善手</th><th id="pathhead">手順</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>
  <section id="detail"><div class="empty">局面を選んでください</div></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const META = DATA.meta;
const PAGE_SIZE = 100;
const KANJI_NUM = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
const PIECE = { P: "歩", L: "香", N: "桂", S: "銀", G: "金", B: "角", R: "飛", K: "玉",
  "+P": "と", "+L": "杏", "+N": "圭", "+S": "全", "+B": "馬", "+R": "龍" };
const HAND_ORDER = ["R", "B", "G", "S", "N", "L", "P"];

const positions = DATA.positions.map((p, i) => {
  const moves = p[1] ? p[1].split(" ") : [];
  const cands = p[3];
  return { id: i, sfen: p[0], moves, lastUsi: p[2], cands,
    value: cands.length ? cands[0][1] : null, tail: moves.slice(META.common).join(" ") };
});

let view = [];
let page = 0;
let selected = null;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const fmtValue = (v) => (v === null ? "-" : (v > 0 ? "+" : "") + v);
const valueClass = (v) => (v > 0 ? "plus" : v < 0 ? "minus" : "");

function header() {
  $("title").textContent = `${META.ply}手目の局面一覧（${positions.length.toLocaleString()}局面）`;
  $("meta").textContent = `定跡DB: ${META.book} ／ 開始: ${META.root} ／ 作成: ${META.generated}`;
  if (META.common > 0) {
    $("pathhead").textContent = `手順（${META.common}手目までは全局面共通のため省略）`;
  }
}

function applyFilter() {
  const words = $("search").value.trim().split(/\s+/).filter(Boolean);
  view = positions.filter((p) => {
    if (!words.length) return true;
    const s = p.moves.join(" ");
    return words.every((w) => s.includes(w));
  });
  const nullLast = (f) => (a, b) => (a.value === null) - (b.value === null) || f(a, b);
  const sorters = {
    desc: nullLast((a, b) => b.value - a.value),
    asc: nullLast((a, b) => a.value - b.value),
    abs: nullLast((a, b) => Math.abs(a.value) - Math.abs(b.value)),
    path: (a, b) => a.id - b.id,
  };
  view.sort(sorters[$("sort").value]);
  page = 0;
  renderList();
}

function renderList() {
  const tbody = $("list").querySelector("tbody");
  tbody.replaceChildren();
  const pages = Math.max(1, Math.ceil(view.length / PAGE_SIZE));
  page = Math.min(page, pages - 1);
  const start = page * PAGE_SIZE;
  view.slice(start, start + PAGE_SIZE).forEach((p, i) => {
    const tr = el("tr");
    if (selected === p) tr.className = "selected";
    tr.append(el("td", "num", String(start + i + 1)));
    tr.append(el("td", "num " + valueClass(p.value), fmtValue(p.value)));
    const best = el("td", "", p.cands.length ? p.cands[0][0] + " " : "-");
    if (p.cands.length && p.cands[0][2] === 0) best.append(el("span", "tag", "未探索"));
    tr.append(best);
    const td = el("td", "path");
    const head = p.tail.lastIndexOf(" ");
    td.append(head < 0 ? "" : p.tail.slice(0, head + 1));
    td.append(el("b", "", head < 0 ? p.tail : p.tail.slice(head + 1)));
    tr.append(td);
    tr.addEventListener("click", () => select(p));
    tbody.append(tr);
  });
  if (!view.length) {
    const tr = el("tr");
    const td = el("td", "empty", "該当する局面がありません");
    td.colSpan = 4;
    tr.append(td);
    tbody.append(tr);
  }
  $("page").textContent = `${view.length.toLocaleString()}件 ${page + 1}/${pages}`;
  $("prev").disabled = page === 0;
  $("next").disabled = page >= pages - 1;
}

function parseSfen(sfen) {
  const [boardPart, turn, handPart] = sfen.split(" ");
  const board = [];
  for (const row of boardPart.split("/")) {
    const cells = [];
    let promoted = false;
    for (const c of row) {
      if (c === "+") { promoted = true; continue; }
      if (/\d/.test(c)) { for (let k = 0; k < +c; k++) cells.push(null); continue; }
      const up = c.toUpperCase();
      cells.push({ kind: (promoted ? "+" : "") + up, gote: c !== up, promoted });
      promoted = false;
    }
    board.push(cells);
  }
  const hands = { b: {}, w: {} };
  if (handPart && handPart !== "-") {
    let n = "";
    for (const c of handPart) {
      if (/\d/.test(c)) { n += c; continue; }
      const up = c.toUpperCase();
      hands[c === up ? "b" : "w"][up] = n ? +n : 1;
      n = "";
    }
  }
  return { board, turn, hands };
}

function handText(label, hand) {
  const items = HAND_ORDER.filter((k) => hand[k]).map((k) => PIECE[k] + (hand[k] > 1 ? hand[k] : ""));
  return `${label}持駒：${items.length ? items.join(" ") : "なし"}`;
}

// USIの "7g" を盤の [行, 列] に変換する
const usiSquare = (s) => [s.charCodeAt(1) - 97, 9 - +s[0]];

function renderBoard(p) {
  const { board, turn, hands } = parseSfen(p.sfen);
  const wrap = el("div");
  wrap.append(el("div", "hand", "☖" + handText("後手", hands.w)));
  const grid = el("div", "board-wrap");
  const files = el("div", "files");
  for (let f = 9; f >= 1; f--) files.append(el("div", "", String(f)));
  grid.append(files, el("div"));
  const b = el("div", "board");
  let last = null, from = null;
  if (p.lastUsi) {
    last = usiSquare(p.lastUsi.slice(2, 4));
    if (p.lastUsi[1] !== "*") from = usiSquare(p.lastUsi.slice(0, 2));
  }
  board.forEach((row, r) => row.forEach((cell, c) => {
    const sq = el("div", "sq");
    if (last && last[0] === r && last[1] === c) sq.classList.add("last");
    if (from && from[0] === r && from[1] === c) sq.classList.add("from");
    if (cell) {
      if (cell.gote) sq.classList.add("gote");
      if (cell.promoted) sq.classList.add("promoted");
      sq.append(el("span", "", cell.kind === "K" && cell.gote ? "王" : PIECE[cell.kind]));
    }
    b.append(sq);
  }));
  const ranks = el("div", "ranks");
  for (let r = 1; r <= 9; r++) ranks.append(el("div", "", KANJI_NUM[r]));
  grid.append(b, ranks);
  wrap.append(grid);
  wrap.append(el("div", "hand", "☗" + handText("先手", hands.b)));
  return { node: wrap, turn };
}

function select(p) {
  selected = p;
  renderList();
  const d = $("detail");
  d.replaceChildren();
  const { node, turn } = renderBoard(p);
  d.append(node);

  const info = el("div", "info");
  info.append(el("span", "", turn === "b" ? "☗先手番" : "☖後手番"));
  info.append(el("span", "eval " + valueClass(p.value), "評価値 " + fmtValue(p.value)));
  info.append(el("span", "tag", "先手視点"));
  d.append(info);

  d.append(el("h2", "", "候補手"));
  const t = el("table");
  const head = el("tr");
  ["手", "評価値", "depth", ""].forEach((h, i) => head.append(el("th", i === 1 || i === 2 ? "num" : "", h)));
  t.append(head);
  p.cands.forEach(([ki2, v, depth]) => {
    const tr = el("tr");
    tr.append(el("td", "", ki2));
    tr.append(el("td", "num " + valueClass(v), fmtValue(v)));
    tr.append(el("td", "num", String(depth)));
    const td = el("td");
    if (depth === 0) td.append(el("span", "tag", "未探索"));
    tr.append(td);
    t.append(tr);
  });
  d.append(t);

  d.append(el("h2", "", "初手からの手順"));
  const fp = el("div", "fullpath");
  p.moves.forEach((m, i) => {
    if (i % 10 === 0) fp.append(el("span", "n", String(i + 1)));
    fp.append(m + " ");
  });
  d.append(fp);

  d.append(el("h2", "", "SFEN"));
  const sf = el("div", "sfen");
  const code = el("code", "", p.sfen);
  const btn = el("button", "", "コピー");
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(p.sfen);
      btn.textContent = "コピー済み";
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      btn.textContent = "選択しました";
    }
    setTimeout(() => (btn.textContent = "コピー"), 1500);
  });
  sf.append(code, btn);
  d.append(sf);
}

function moveSelection(delta) {
  if (!view.length) return;
  const i = selected ? view.indexOf(selected) : -1;
  const next = Math.min(view.length - 1, Math.max(0, i + delta));
  page = Math.floor(next / PAGE_SIZE);
  select(view[next]);
  const row = $("list").querySelector("tr.selected");
  if (row) row.scrollIntoView({ block: "nearest" });
}

let timer = null;
$("search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(applyFilter, 200); });
$("sort").addEventListener("change", applyFilter);
$("prev").addEventListener("click", () => { page--; renderList(); });
$("next").addEventListener("click", () => { page++; renderList(); });
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowDown" || e.key === "j") { moveSelection(1); e.preventDefault(); }
  if (e.key === "ArrowUp" || e.key === "k") { moveSelection(-1); e.preventDefault(); }
});

header();
applyFilter();
if (view.length) select(view[0]);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
