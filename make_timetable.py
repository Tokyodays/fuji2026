#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FUJI ROCK FESTIVAL '26  10分刻み A4横タイムテーブル生成スクリプト。

assets/<day>.csv (stage,start,end,artist) を読み、A4横1枚のPDFを生成する。
レイアウト/配色は元PDF(v5)を元PNGから採寸・採色して再構築したもの。
列の左→右の並びは STAGE_ORDER で指定する。

使い方:
    python make_timetable.py            # 3日分PDF + 3days.pdf + PNGサムネを再生成
"""
import csv
import os
import subprocess
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

# ---- 日付定義 ---------------------------------------------------------------
DAYS = [
    ("24fri", "24 FRI"),
    ("25sat", "25 SAT"),
    ("26sun", "26 SUN"),
]

# ---- 列の並び（左 → 右）と配色 ----------------------------------------------
# key はCSVの stage 列と正規化して突き合わせる。label はヘッダー表示名。
STAGES = [
    ("PYRAMID GARDEN",      "PYRAMID GARDEN",      "#c2299e"),
    ("CRYSTAL PALACE TENT", "CRYSTAL PALACE TENT", "#45b8b0"),
    ("ROOKIE A GO-GO",      "ROOKIE A GO-GO",      "#3aa67d"),
    ("GAN-BAN SQUARE",      "GAN-BAN SQUARE",      "#d11f32"),
    ("RED MARQUEE",         "RED MARQUEE",         "#f05a4a"),
    ("苗場食堂",             "苗場食堂",             "#9f9c18"),
    ("BLUE GALAXY",         "BLUE GALAXY",         "#45689b"),
    ("GREEN STAGE",         "GREEN STAGE",         "#68a93a"),
    ("WHITE STAGE",         "WHITE STAGE",         "#8a8a8a"),
    ("AVALON FIELD",        "AVALON FIELD",        "#c84d80"),
    ("FIELD OF HEAVEN",     "FIELD OF HEAVEN",     "#54c3d5"),
    ("ORANGE ECHO",         "ORANGE ECHO",         "#f6a33a"),
]

# ---- 幾何（元PNG 3508x2480 の画素座標。300dpi = A4横に一致）---------------
PXW, PXH = 3508.0, 2480.0
PAGE_W, PAGE_H = landscape(A4)          # 841.89 x 595.28 pt
SX = PAGE_W / PXW
SY = PAGE_H / PXH

BAR_BOTTOM   = 70      # 上部オレンジバー下端 (px)
HEAD_TOP     = 74      # ステージヘッダー帯 上端
HEAD_BOTTOM  = 188     # ステージヘッダー帯 下端
PLOT_X0      = 250     # プロット左端（時間軸との境界）
PLOT_X1      = 3419    # プロット右端
T0_MIN       = 540     # 09:00 を分で
T1_MIN       = 1740    # 29:00 を分で
Y_T0         = 193     # 09:00 の画素y
PX_PER_MIN   = 1.825   # 1分あたりの画素

N_COL   = len(STAGES)
COL_W   = (PLOT_X1 - PLOT_X0) / N_COL
GAP     = 4            # 色付きブロック/ヘッダーの左右内側マージン(px)

ORANGE = HexColor("#f36b21")
INK    = HexColor("#151515")
MUTED  = HexColor("#6b6b6b")
GRID_HOUR = Color(0.78, 0.76, 0.72)
GRID_HALF = Color(0.87, 0.85, 0.81)
GRID_TEN  = Color(0.93, 0.92, 0.89)

# ラテン+日本語を1ファイルに含むTrueTypeを埋め込み、組版幅と描画を一致させる。
# 見つからない場合はCIDフォントにフォールバック（描画時に幅がずれる可能性あり）。
FONT = "TT"
_TTF_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
for _p in _TTF_CANDIDATES:
    if os.path.exists(_p):
        pdfmetrics.registerFont(TTFont(FONT, _p))
        break
else:
    FONT = "HeiseiKakuGo-W5"
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))


# ---- 座標変換 ---------------------------------------------------------------
def X(px):
    return px * SX


def Y(px):
    return PAGE_H - px * SY


def y_of_min(m):
    return Y_T0 + (m - T0_MIN) * PX_PER_MIN


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def tint(hex_color, a=0.20):
    """白80% + 色20% のブロック塗り。"""
    c = HexColor(hex_color)
    return Color(1 - a * (1 - c.red), 1 - a * (1 - c.green), 1 - a * (1 - c.blue))


def norm(s):
    return "".join(s.upper().split()).replace("-", "").replace("・", "")


# ---- テキスト折返し ---------------------------------------------------------
def _sw(s, size):
    return pdfmetrics.stringWidth(s, FONT, size)


def _tokens(para):
    """空白とハイフン境界で分割可能なトークン列にする。
    'GAN-BAN SQUARE' -> ['GAN-', 'BAN', ' ', 'SQUARE']"""
    out = []
    for i, word in enumerate(para.split(" ")):
        if i:
            out.append(" ")
        buf = ""
        for ch in word:
            buf += ch
            if ch == "-":
                out.append(buf); buf = ""
        if buf:
            out.append(buf)
    return out


def wrap(text, size, max_w):
    """単語（空白・ハイフン）優先で折返し。長すぎる語は文字単位で分割。"""
    lines = []
    for para in text.split("\n"):
        cur = ""
        for tok in _tokens(para):
            if tok == " ":
                if cur:
                    cur += " "
                continue
            if _sw(cur + tok, size) <= max_w:
                cur += tok
            elif not cur:
                # 空行に単独で入らない語 → 文字単位
                for ch in tok:
                    if _sw(cur + ch, size) <= max_w or not cur:
                        cur += ch
                    else:
                        lines.append(cur); cur = ch
            else:
                lines.append(cur.rstrip()); cur = tok
        if cur.strip():
            lines.append(cur.strip())
    return [ln for ln in lines if ln]


def autofit(text, max_w, max_size, min_size=5.0, max_lines=3):
    """max_lines行以内で各行がmax_wに収まる最大フォントサイズと行を返す。"""
    size = max_size
    while size >= min_size:
        lines = wrap(text, size, max_w)
        if len(lines) <= max_lines and all(_sw(l, size) <= max_w for l in lines):
            return size, lines
        size -= 0.25
    return min_size, wrap(text, min_size, max_w)


def draw_header(c, day_label):
    # 上部オレンジバー
    c.setFillColor(ORANGE)
    c.rect(0, Y(BAR_BOTTOM), PAGE_W, PAGE_H - Y(BAR_BOTTOM), stroke=0, fill=1)
    c.setFillColor(Color(1, 1, 1))
    c.setFont(FONT, 12)
    title = f"{day_label} / FUJI ROCK FESTIVAL '26 - 10分刻み A4一覧 (09:00-29:00)"
    c.drawString(X(24), Y(BAR_BOTTOM) + (PAGE_H - Y(BAR_BOTTOM) - 12) / 2 + 1, title)

    # ステージヘッダー帯
    hb_top, hb_bot = Y(HEAD_TOP), Y(HEAD_BOTTOM)
    for i, (key, label, hexc) in enumerate(STAGES):
        left = PLOT_X0 + i * COL_W + GAP
        w = COL_W - 2 * GAP
        c.setFillColor(HexColor(hexc))
        c.roundRect(X(left), hb_bot, X(left + w) - X(left), hb_top - hb_bot,
                    3, stroke=0, fill=1)
        c.setFillColor(Color(1, 1, 1))
        box_w = X(left + w) - X(left)
        size, lines = autofit(label, box_w - 8, 8.5, min_size=5.5, max_lines=3)
        lead = size + 1.5
        total_h = len(lines) * lead
        ty = (hb_top + hb_bot) / 2 + total_h / 2 - size
        cx = (X(left) + X(left + w)) / 2
        c.setFont(FONT, size)
        for ln in lines:
            c.drawCentredString(cx, ty, ln)
            ty -= lead


def draw_grid(c):
    top_y = y_of_min(T0_MIN)
    bot_y = y_of_min(T1_MIN)
    # 縦の10分・30分・時線
    for m in range(T0_MIN, T1_MIN + 1, 10):
        yy = Y(y_of_min(m))
        if m % 60 == 0:
            c.setStrokeColor(GRID_HOUR); c.setLineWidth(0.8)
        elif m % 30 == 0:
            c.setStrokeColor(GRID_HALF); c.setLineWidth(0.5)
        else:
            c.setStrokeColor(GRID_TEN); c.setLineWidth(0.35)
        c.line(X(PLOT_X0), yy, X(PLOT_X1), yy)
        # 左の時刻ラベル
        if m % 60 == 0:
            c.setFillColor(INK); c.setFont(FONT, 8)
            c.drawRightString(X(PLOT_X0) - 6, yy - 3, f"{m // 60:02d}:00")
        elif m % 30 == 0:
            c.setFillColor(MUTED); c.setFont(FONT, 5.5)
            c.drawRightString(X(PLOT_X0) - 6, yy - 2, f"{m // 60:02d}:{m % 60:02d}")
    # 列の縦罫線
    c.setStrokeColor(GRID_HALF); c.setLineWidth(0.4)
    for i in range(N_COL + 1):
        xx = X(PLOT_X0 + i * COL_W)
        c.line(xx, Y(y_of_min(T0_MIN)), xx, Y(y_of_min(T1_MIN)))


def draw_blocks(c, rows):
    idx = {norm(k): i for i, (k, _, _) in enumerate(STAGES)}
    colhex = {i: h for i, (_, _, h) in enumerate(STAGES)}
    plot_top = y_of_min(T0_MIN)
    plot_bot = y_of_min(T1_MIN)
    for stage, start, end, artist in rows:
        i = idx.get(norm(stage))
        if i is None:
            continue
        s, e = to_min(start), to_min(end)
        y_top = max(y_of_min(s), plot_top)
        y_bot = min(y_of_min(e), plot_bot)
        if y_bot <= y_top:
            continue
        left = PLOT_X0 + i * COL_W + GAP
        w = COL_W - 2 * GAP
        x0, x1 = X(left), X(left + w)
        yt, yb = Y(y_top), Y(y_bot)
        hexc = colhex[i]
        c.setFillColor(tint(hexc))
        c.setStrokeColor(HexColor(hexc)); c.setLineWidth(0.7)
        c.roundRect(x0, yb, x1 - x0, yt - yb, 3, stroke=1, fill=1)
        # 時刻
        pad = 3
        cy = yt - 8
        c.setFillColor(MUTED); c.setFont(FONT, 5)
        c.drawString(x0 + pad, cy, f"{start}-{end}")
        # アーティスト名
        c.setFillColor(INK)
        size = 7
        max_w = x1 - x0 - 2 * pad
        lines = wrap(artist, size, max_w)
        ty = cy - size - 1
        avail_bottom = yb + 2
        for ln in lines:
            if ty < avail_bottom:
                break
            c.setFont(FONT, size)
            c.drawString(x0 + pad, ty, ln)
            ty -= size + 1


def draw_footer(c):
    c.setFillColor(MUTED); c.setFont(FONT, 6)
    c.drawRightString(X(PLOT_X1), Y(2470),
                      "※個人整理の非公式タイムテーブルです。出演時間などは必ず公式発表もご確認ください。")


def read_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            if len(row) >= 4 and row[0].strip():
                rows.append([row[0].strip(), row[1].strip(),
                             row[2].strip(), row[3].strip()])
    return rows


def build_day(day, label):
    csv_path = os.path.join(ASSETS, f"{day}.csv")
    pdf_path = os.path.join(ASSETS, f"{day}.pdf")
    rows = read_csv(csv_path)
    c = canvas.Canvas(pdf_path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"FUJI_ROCK_26_{day.upper()}_A4_10min_timetable")
    draw_grid(c)
    draw_blocks(c, rows)
    draw_header(c, label)
    draw_footer(c)
    c.showPage()
    c.save()
    print("wrote", pdf_path)
    return pdf_path


def make_thumbnail(pdf_path):
    out = pdf_path[:-4]  # without .pdf
    try:
        subprocess.run(["pdftoppm", "-png", "-r", "150", "-singlefile",
                        pdf_path, out], check=True)
        print("wrote", out + ".png")
    except Exception as e:
        print("thumbnail skip:", e)


def merge(pdfs, out):
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
    w = PdfWriter()
    for p in pdfs:
        w.append(PdfReader(p))
    with open(out, "wb") as f:
        w.write(f)
    print("wrote", out)


def main():
    pdfs = []
    for day, label in DAYS:
        p = build_day(day, label)
        make_thumbnail(p)
        pdfs.append(p)
    merge(pdfs, os.path.join(ASSETS, "3days.pdf"))


if __name__ == "__main__":
    main()
