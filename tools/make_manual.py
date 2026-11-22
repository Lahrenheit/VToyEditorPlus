"""Builds the user manual in Spanish, English and Portuguese: docs/Manual_VToyEditorPlus_<es|en|pt>.pdf (cover with
the program's icon, clickable index and PDF bookmarks, every function, three step-by-step guides).  Needs reportlab.

    python tools/make_manual.py                 all three into docs/
    python tools/make_manual.py en out.pdf      one language

The text is in this file (content(), every sentence as t(spanish, english, portuguese)); the version comes from APP_REV
in vtoy/__init__.py."""
from __future__ import annotations

import math
import os
import re
import sys

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String, Circle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = ("es", "en", "pt")
ICON = os.path.join(ROOT, "icon", "vtoy.png")
_lang = [0]


def t(es, en, pt):
    """The text in the language being built."""
    return (es, en, pt)[_lang[0]]


def manual_path(lang: str, root: str = ROOT) -> str:
    return os.path.join(root, "docs", f"Manual_VToyEditorPlus_{lang}.pdf")

# ------------------------------------------------------------------------------------------------ look
NAVY = colors.HexColor("#14213d")
NAVY2 = colors.HexColor("#1d2d50")
ACCENT = colors.HexColor("#e4572e")
ACCENT2 = colors.HexColor("#f3a712")
TEAL = colors.HexColor("#2a9d8f")
INK = colors.HexColor("#1f2430")
GREY = colors.HexColor("#6b7280")
LIGHT = colors.HexColor("#f3f4f6")
TIPBG = colors.HexColor("#fff4e6")
NOTEBG = colors.HexColor("#e8f4f2")
WARNBG = colors.HexColor("#fdecea")

FONT_DIRS = ["/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/truetype/crosextra",
             "/usr/share/fonts/truetype/dejavu", os.path.join(ROOT, "docs", "fonts"), r"C:\Windows\Fonts"]


def _font(name, files):
    for d in FONT_DIRS:
        for f in files:
            p = os.path.join(d, f)
            if os.path.isfile(p):
                pdfmetrics.registerFont(TTFont(name, p))
                return True
    return False


def setup_fonts():
    ok = {
        "Head": _font("Head", ["Poppins-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"]),
        "HeadM": _font("HeadM", ["Poppins-Medium.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"]),
        "HeadL": _font("HeadL", ["Poppins-Light.ttf", "DejaVuSans-ExtraLight.ttf", "arial.ttf"]),
        "Body": _font("Body", ["Carlito-Regular.ttf", "DejaVuSans.ttf", "calibri.ttf", "arial.ttf"]),
        "BodyB": _font("BodyB", ["Carlito-Bold.ttf", "DejaVuSans-Bold.ttf", "calibrib.ttf", "arialbd.ttf"]),
        "BodyI": _font("BodyI", ["Carlito-Italic.ttf", "DejaVuSans-Oblique.ttf", "calibrii.ttf", "ariali.ttf"]),
        "BodyBI": _font("BodyBI", ["Carlito-BoldItalic.ttf", "DejaVuSans-BoldOblique.ttf", "calibriz.ttf", "arialbi.ttf"]),
        "Mono": _font("Mono", ["DejaVuSansMono.ttf", "consola.ttf", "cour.ttf"]),
        "Sym": _font("Sym", ["DejaVuSans.ttf", "seguisym.ttf", "arial.ttf"]),
    }
    if not all(ok.values()):
        raise SystemExit("fonts missing: " + ", ".join(k for k, v in ok.items() if not v))
    from reportlab.lib.fonts import addMapping
    addMapping("Body", 0, 0, "Body")
    addMapping("Body", 1, 0, "BodyB")
    addMapping("Body", 0, 1, "BodyI")
    addMapping("Body", 1, 1, "BodyBI")


def styles():
    s = {}
    s["body"] = ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=14.6, textColor=INK, spaceAfter=5)
    s["lead"] = ParagraphStyle("lead", parent=s["body"], fontSize=12, leading=17, textColor=NAVY2, spaceAfter=8)
    s["h1"] = ParagraphStyle("h1", fontName="Head", fontSize=23, leading=28, textColor=NAVY, spaceAfter=4)
    s["h2"] = ParagraphStyle("h2", fontName="Head", fontSize=13.5, leading=18, textColor=ACCENT, spaceBefore=12,
                             spaceAfter=4)
    s["h3"] = ParagraphStyle("h3", fontName="HeadM", fontSize=11, leading=15, textColor=NAVY2, spaceBefore=7, spaceAfter=2)
    s["li"] = ParagraphStyle("li", parent=s["body"], spaceAfter=2.2, leftIndent=14, bulletIndent=3)
    s["cell"] = ParagraphStyle("cell", parent=s["body"], fontSize=9.6, leading=12.6, spaceAfter=0)
    s["cellh"] = ParagraphStyle("cellh", parent=s["cell"], fontName="BodyB", textColor=colors.white)
    s["box"] = ParagraphStyle("box", parent=s["body"], fontSize=10, leading=13.8, spaceAfter=0)
    s["cap"] = ParagraphStyle("cap", parent=s["body"], fontName="BodyI", fontSize=9, leading=12, textColor=GREY,
                              alignment=TA_CENTER, spaceBefore=3, spaceAfter=8)
    s["toc0"] = ParagraphStyle("toc0", fontName="HeadM", fontSize=11.5, leading=17, textColor=NAVY, leftIndent=0,
                               spaceBefore=5)
    s["toc1"] = ParagraphStyle("toc1", fontName="Body", fontSize=10, leading=13.5, textColor=INK, leftIndent=18)
    s["chapnum"] = ParagraphStyle("chapnum", fontName="HeadL", fontSize=12, leading=14, textColor=ACCENT)
    return s


# ------------------------------------------------------------------------------------------------ text helpers
def K(*keys):
    """Key caps: K("Ctrl", "Z") -> Ctrl + Z drawn as keys."""
    return " + ".join(f'<font name="Mono" size="8.6" backColor="#e5e7eb" color="#111827">&nbsp;{k}&nbsp;</font>'
                      for k in keys)


def M(path):
    """A menu path: M("Archivo", "Guardar") -> Archivo > Guardar in bold."""
    return ' <font name="Sym" size="8" color="#e4572e">\u25b8</font> '.join(f"<b>{p}</b>" for p in path.split(" > "))


def C(t):
    return f'<font name="Mono" size="9" color="#9a3412">{t}</font>'


def link(key, text):
    return f'<a href="#{key}" color="#e4572e"><u>{text}</u></a>'


# ------------------------------------------------------------------------------------------------ flowables
class Heading(Paragraph):
    """A heading that goes into the index and the PDF bookmarks."""

    def __init__(self, text, style, level, key, toc=True, number=""):
        self.level, self.key, self.toc, self.plain, self.number = level, key, toc, re.sub(r"<[^>]+>", "", text), number
        super().__init__(text, style)


class ChapterHead(Flowable):
    """The start of a chapter: number, title and a coloured bar."""

    def __init__(self, num, title, key, width):
        super().__init__()
        self.num, self.title, self.key, self.w = num, title, key, width
        self.level, self.toc, self.plain = 0, True, f"{num}. {title}" if num else title
        self.h = 86

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        c.setFillColor(NAVY)
        c.roundRect(0, 0, self.w, self.h - 6, 10, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.roundRect(0, 0, 9, self.h - 6, 4, stroke=0, fill=1)
        for k in range(7):                                    # a few blocks top right, like the cover
            x = self.w - 30 - k * 13
            c.setFillColor([ACCENT, ACCENT2, TEAL][k % 3])
            c.setFillAlpha(0.18 + 0.1 * (k % 3))
            c.rect(x, self.h - 34 + (k % 2) * 10, 9, 9, stroke=0, fill=1)
        c.setFillAlpha(1)
        if self.num:
            c.setFont("HeadL", 11)
            c.setFillColor(ACCENT2)
            c.drawString(26, self.h - 32, f"{t('CAPÍTULO', 'CHAPTER', 'CAPÍTULO')} {self.num}")
        c.setFont("Head", 22 if len(self.title) < 34 else 18)
        c.setFillColor(colors.white)
        c.drawString(26, 22, self.title)


def box(kind, text, st):
    bg, bar, label = {"tip": (TIPBG, ACCENT2, t("Consejo", "Tip", "Dica")), "note": (NOTEBG, TEAL, t("Nota", "Note", "Nota")),
                      "warn": (WARNBG, ACCENT, t("Importante", "Important", "Importante"))}[kind]
    p = Paragraph(f'<font name="BodyB" color="{bar.hexval().replace("0x", "#")}">{label}.</font> {text}', st["box"])
    tb = Table([[p]], colWidths=[None])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3.5, bar),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([Spacer(1, 3), tb, Spacer(1, 6)])


def table(head, rows, widths, st, zebra=True):
    data = [[Paragraph(h, st["cellh"]) for h in head]] + [[Paragraph(str(c), st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    sty = [("BACKGROUND", (0, 0), (-1, 0), NAVY2), ("VALIGN", (0, 0), (-1, -1), "TOP"),
           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
           ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db"))]
    if zebra:
        for r in range(2, len(data), 2):
            sty.append(("BACKGROUND", (0, r), (-1, r), LIGHT))
    t.setStyle(TableStyle(sty))
    return t


def steps(items, st):
    """Numbered steps with a round number."""
    rows = []
    for k, it in enumerate(items, 1):
        num = Paragraph(f'<font name="Head" size="10.5" color="white">{k}</font>',
                        ParagraphStyle("n", alignment=TA_CENTER, leading=13))
        rows.append([num, Paragraph(it, st["body"])])
    t = Table(rows, colWidths=[22, None])
    sty = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 0),
           ("LEFTPADDING", (1, 0), (1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for r in range(len(rows)):
        sty.append(("BACKGROUND", (0, r), (0, r), ACCENT))
    t.setStyle(TableStyle(sty))
    return t


def bullets(items, st):
    return [Paragraph(it, st["li"], bulletText="\u2022") for it in items]


# ------------------------------------------------------------------------------------------------ figures
def fig_screen(w):
    """The editor's screen, drawn as a sketch with numbered parts."""
    h = 0.6 * w
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, rx=6, ry=6, fillColor=colors.HexColor("#0f172a"), strokeColor=NAVY, strokeWidth=1))
    # 3D view: a floor grid in perspective and a few blocks
    hor = h * 0.52
    cx = w * 0.5
    for k in range(-9, 10):
        x0, x1, y1 = cx + k * 6, cx + k * 60, 0.0
        if x1 < 0 or x1 > w:                                  # (clipped at the side of the picture)
            xe = 0.0 if x1 < 0 else w
            y1 = hor * (xe - x1) / (x0 - x1)
            x1 = xe
        d.add(Line(x0, hor, x1, y1, strokeColor=colors.HexColor("#334155"), strokeWidth=0.6))
    for k in range(1, 9):
        y = hor * (1 - (k / 9) ** 1.6)
        d.add(Line(0, y, w, y, strokeColor=colors.HexColor("#334155"), strokeWidth=0.6))
    d.add(Rect(0, hor, w, h - hor - 18, fillColor=colors.HexColor("#1e3a5f"), strokeColor=None))

    def block(x, y, s, col):
        d.add(Polygon([x, y, x + s, y + s * 0.35, x + s, y + s * 1.35, x, y + s], fillColor=col, strokeColor=None))
        d.add(Polygon([x, y, x - s * 0.9, y + s * 0.3, x - s * 0.9, y + s * 1.3, x, y + s],
                      fillColor=colors.Color(col.red * 0.7, col.green * 0.7, col.blue * 0.7), strokeColor=None))
        d.add(Polygon([x, y + s, x + s, y + s * 1.35, x + s * 0.1, y + s * 1.65, x - s * 0.9, y + s * 1.3],
                      fillColor=colors.Color(min(col.red * 1.25, 1), min(col.green * 1.25, 1), min(col.blue * 1.25, 1)),
                      strokeColor=None))
    block(cx - 20, hor * 0.35, 34, ACCENT)
    block(cx + 50, hor * 0.5, 22, ACCENT2)
    block(cx - 85, hor * 0.55, 18, TEAL)
    # menu bar
    d.add(Rect(0, h - 18, w, 18, fillColor=colors.HexColor("#1f2937"), strokeColor=None))
    x = 10
    for m in t(("Archivo", "Editar", "Ver", "Idioma", "Configuración", "Ayuda"),
               ("File", "Edit", "View", "Language", "Settings", "Help"),
               ("Arquivo", "Editar", "Exibir", "Idioma", "Configurações", "Ajuda")):
        d.add(String(x, h - 12.5, m, fontName="Body", fontSize=8, fillColor=colors.white))
        x += pdfmetrics.stringWidth(m, "Body", 8) + 14
    # HUD
    d.add(Rect(8, h - 74, 120, 50, rx=3, ry=3, fillColor=colors.Color(0, 0, 0, 0.55), strokeColor=None))
    for k, tx in enumerate(("60 FPS", t("Posición  X Y Z", "Position  X Y Z", "Posição  X Y Z"),
                            t("Ángulos", "Angles", "Ângulos"), t("MODIFICANDO MAPA: ...", "EDITING MAP: ...", "MODIFICANDO MAPA: ..."))):
        d.add(String(14, h - 36 - k * 11, tx, fontName="Mono", fontSize=6.5,
                     fillColor=ACCENT2 if k == 3 else colors.HexColor("#e5e7eb")))
    # tools bar
    d.add(Rect(8, h * 0.08, 22, 9 * 17 + 6, rx=3, ry=3, fillColor=colors.HexColor("#1f2937"), strokeColor=None))
    for k in range(9):
        y = h * 0.08 + 6 + (8 - k) * 17
        d.add(Rect(12, y, 14, 13, rx=2, ry=2, fillColor=ACCENT if k == 0 else colors.HexColor("#374151"), strokeColor=None))
        d.add(String(19, y + 3.5, str(k + 1), fontName="HeadM", fontSize=7, fillColor=colors.white, textAnchor="middle"))
    # DEBUG panel (right)
    pw = w * 0.24
    d.add(Rect(w - pw - 6, 8, pw, h - 32, rx=3, ry=3, fillColor=colors.HexColor("#111827"), strokeColor=colors.HexColor("#374151")))
    d.add(Rect(w - pw - 6, h - 40, pw, 16, fillColor=colors.HexColor("#374151"), strokeColor=None))
    d.add(String(w - pw, h - 35, "DEBUG", fontName="HeadM", fontSize=7.5, fillColor=colors.white))
    for k, tx in enumerate(t(("Lista de escenas", "Lista de mapas", "Library", "Modo de juego / cielo", "Luces", "Decals",
                              "Escena (módulos)", "Selección", "Opciones de vista"),
                             ("Scene list", "Maps list", "Library", "Game mode / sky", "Lights", "Decals",
                              "Scene (modules)", "Selection", "View options"),
                             ("Lista de cenas", "Lista de mapas", "Library", "Modo de jogo / céu", "Luzes", "Decals",
                              "Cena (módulos)", "Seleção", "Opções de exibição"))):
        d.add(String(w - pw, h - 52 - k * 13, "\u25b8 " + tx, fontName="Sym", fontSize=6.3, fillColor=colors.HexColor("#d1d5db")))
    # Map tools window
    mw, mh = w * 0.27, h * 0.36
    mx, my = w * 0.46, h * 0.1
    d.add(Rect(mx, my, mw, mh, rx=3, ry=3, fillColor=colors.HexColor("#111827"), strokeColor=colors.HexColor("#374151")))
    d.add(Rect(mx, my + mh - 15, mw, 15, fillColor=colors.HexColor("#374151"), strokeColor=None))
    d.add(String(mx + 5, my + mh - 10.5, t("Herramientas del mapa", "Map tools", "Ferramentas do mapa"), fontName="HeadM",
                 fontSize=6.8, fillColor=colors.white))
    cats = t(("Todo", "Construir", "Colisión", "Aspecto"), ("All", "Build", "Collision", "Look"),
             ("Tudo", "Construir", "Colisão", "Aparência"))
    xx = mx + 5
    for k, tx in enumerate(cats[:4]):
        tw = pdfmetrics.stringWidth(tx, "Body", 5.6) + 6
        d.add(Rect(xx, my + mh - 29, tw, 10, rx=2, ry=2, fillColor=ACCENT if k == 1 else colors.HexColor("#374151"),
                   strokeColor=None))
        d.add(String(xx + 3, my + mh - 26, tx, fontName="Body", fontSize=5.6, fillColor=colors.white))
        xx += tw + 3
    for k, tx in enumerate(t(("Mapa nuevo desde cero", "Crear desde .bsp / .rmf", "Formas", "Crear sólido"),
                             ("New map from zero", "Create from .bsp / .rmf", "Shapes", "Create solid"),
                             ("Mapa novo do zero", "Criar a partir de .bsp / .rmf", "Formas", "Criar sólido"))):
        d.add(String(mx + 6, my + mh - 42 - k * 11, "\u25b8 " + tx, fontName="Sym", fontSize=6, fillColor=colors.HexColor("#d1d5db")))

    def tag(x, y, n):
        d.add(Circle(x, y, 7, fillColor=ACCENT2, strokeColor=colors.white, strokeWidth=1))
        d.add(String(x, y - 3, str(n), fontName="Head", fontSize=8, fillColor=NAVY, textAnchor="middle"))
    tag(x + 4, h - 9, 1)
    tag(134, h - 30, 2)
    tag(38, h * 0.08 + 9 * 17, 3)
    tag(w - pw - 12, h - 32, 4)
    tag(mx + mw + 2, my + mh - 6, 5)
    tag(cx - 40, hor * 0.25, 6)
    return d


def fig_flow(w, items, color=ACCENT):
    """A row of boxes joined by arrows."""
    n = len(items)
    gap = 14
    bw = (w - gap * (n - 1)) / n
    h = 62
    d = Drawing(w, h)
    for k, (title, sub) in enumerate(items):
        x = k * (bw + gap)
        d.add(Rect(x, 4, bw, h - 8, rx=7, ry=7, fillColor=colors.white, strokeColor=color, strokeWidth=1.3))
        d.add(Rect(x, h - 22, bw, 18, rx=7, ry=7, fillColor=color, strokeColor=None))
        d.add(Rect(x, h - 22, bw, 8, fillColor=color, strokeColor=None))
        d.add(String(x + bw / 2, h - 16.5, f"{k + 1}. {title}", fontName="HeadM", fontSize=7.4, fillColor=colors.white,
                     textAnchor="middle"))
        words, lines, cur = sub.split(), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if pdfmetrics.stringWidth(t, "Body", 7.2) > bw - 8:
                lines.append(cur)
                cur = wd
            else:
                cur = t
        lines.append(cur)
        for j, ln in enumerate(lines[:3]):
            d.add(String(x + bw / 2, h - 32 - j * 9, ln, fontName="Body", fontSize=7.2, fillColor=INK, textAnchor="middle"))
        if k < n - 1:
            ax = x + bw + 2
            d.add(Line(ax, h / 2 - 2, ax + gap - 5, h / 2 - 2, strokeColor=NAVY2, strokeWidth=1.4))
            d.add(Polygon([ax + gap - 4, h / 2 - 2, ax + gap - 9, h / 2 + 1.5, ax + gap - 9, h / 2 - 5.5], fillColor=NAVY2,
                          strokeColor=None))
    return d


def fig_categories(w):
    cats = [(t("Construir", "Build", "Construir"), t("mapas nuevos, formas, sólidos, recorridos, medir, grupo, OBJ, piezas",
             "new maps, shapes, solids, paths, measuring, groups, OBJ, pieces", "mapas novos, formas, sólidos, caminhos, medir, grupo, OBJ, peças"), ACCENT),
            (t("Colisión", "Collision", "Colisão"), t("cajas, piso / paredes (.hm), limpiar, huecos", "boxes, floor / walls (.hm), clean-up, gaps",
             "caixas, chão / paredes (.hm), limpar, buracos"), TEAL),
            (t("Aspecto", "Look", "Aparência"), t("pintar caras, texturas, luz de CS, sombreado, luces, clima, partículas",
             "paint faces, textures, CS light, shading, lights, weather, particles", "pintar faces, texturas, luz do CS, sombreamento, luzes, clima, partículas"), ACCENT2),
            (t("Jugabilidad", "Gameplay", "Jogabilidade"), t("modo de juego, bomba, clima, puntos de inicio, caídas, simulación, caminar, balance",
             "game mode, bomb, weather, start points, falls, simulation, walk test, balance", "modo de jogo, bomba, clima, pontos de início, quedas, simulação, caminhada, equilíbrio"), ACCENT),
            (t("Revisar", "Check", "Verificar"), t("revisar mapa, mapa de carga, sectores, cambios, plano", "map check, load map, sectors, changes, plan",
             "verificar mapa, mapa de carga, setores, mudanças, planta"), TEAL),
            (t("Juego y archivos", "Game & files", "Jogo e arquivos"), t("probar en el juego, instalar / compartir, historial, atajos",
             "play in the game, install / share, history, shortcuts", "testar no jogo, instalar / compartilhar, histórico, atalhos"), ACCENT2)]
    cols, gap = 3, 10
    bw = (w - gap * (cols - 1)) / cols
    bh = 58
    h = 2 * bh + gap
    d = Drawing(w, h)
    for k, (title, sub, col) in enumerate(cats):
        x = (k % cols) * (bw + gap)
        y = h - (k // cols + 1) * bh - (k // cols) * gap
        d.add(Rect(x, y, bw, bh, rx=6, ry=6, fillColor=LIGHT, strokeColor=None))
        d.add(Rect(x, y, 5, bh, rx=2, ry=2, fillColor=col, strokeColor=None))
        d.add(String(x + 12, y + bh - 16, title, fontName="Head", fontSize=10, fillColor=NAVY))
        words, lines, cur = sub.split(), [], ""
        for wd in words:
            tt = (cur + " " + wd).strip()
            if pdfmetrics.stringWidth(tt, "Body", 7.6) > bw - 18:
                lines.append(cur)
                cur = wd
            else:
                cur = tt
        lines.append(cur)
        for j, ln in enumerate(lines[:3]):
            d.add(String(x + 12, y + bh - 29 - j * 9.5, ln, fontName="Body", fontSize=7.6, fillColor=INK))
    return d


def fig_files(w):
    """Scene -> map -> floor -> textures / models, as stacked layers."""
    layers = [(t("Escena  .scn", "Scene  .scn", "Cena  .scn"), t("qué hay y cómo se juega: módulos, cielo, niebla, música, DLL del modo",
               "what is there and how it is played: modules, sky, fog, music, mode DLL", "o que há e como se joga: módulos, céu, neblina, música, DLL do modo"), ACCENT),
              (t("Mapa  .opt", "Map  .opt", "Mapa  .opt"), t("lo que se ve: mallas, props, decals, luces, cajas de colisión, sectores",
               "what you see: meshes, props, decals, lights, collision boxes, sectors", "o que se vê: malhas, props, decals, luzes, caixas de colisão, setores"), ACCENT2),
              (t("Piso  .hm", "Floor  .hm", "Chão  .hm"), t("por dónde se camina: caras de piso, rampas y paredes",
               "where you walk: floor faces, ramps and walls", "por onde se anda: faces de chão, rampas e paredes"), TEAL),
              (t("Texturas .tex  ·  Modelos .nfo  ·  Animaciones .key", "Textures .tex  ·  Models .nfo  ·  Animations .key",
                 "Texturas .tex  ·  Modelos .nfo  ·  Animações .key"), t("los archivos que usan los de arriba",
                 "the files the ones above use", "os arquivos que os de cima usam"), NAVY2)]
    h = len(layers) * 30 + 6
    d = Drawing(w, h)
    for k, (title, sub, col) in enumerate(layers):
        y = h - (k + 1) * 30
        inset = k * 10
        d.add(Rect(inset, y, w - 2 * inset, 26, rx=5, ry=5, fillColor=col, strokeColor=None))
        d.add(String(inset + 10, y + 9.5, title, fontName="Head", fontSize=9.5, fillColor=colors.white))
        d.add(String(w - inset - 10, y + 9.5, sub, fontName="Body", fontSize=7.8, fillColor=colors.white, textAnchor="end"))
    return d


class Fig(Flowable):
    def __init__(self, drawing):
        super().__init__()
        self.d = drawing

    def wrap(self, aw, ah):
        return self.d.width, self.d.height

    def draw(self):
        from reportlab.graphics import renderPDF
        renderPDF.draw(self.d, self.canv, 0, 0)


# ------------------------------------------------------------------------------------------------ document
class ManualDoc(BaseDocTemplate):
    def __init__(self, path, version, **kw):
        super().__init__(path, pagesize=A4, leftMargin=22 * mm, rightMargin=20 * mm, topMargin=24 * mm,
                         bottomMargin=22 * mm, title="VToyEditor Plus+ - " + t("Manual de usuario", "User manual", "Manual do usuário"),
                         author="Lahrenheit", subject=t("Manual de usuario de VToyEditor Plus+ ", "VToyEditor Plus+ user manual ",
                                                        "Manual do usuário do VToyEditor Plus+ ") + version,
                         creator="tools/make_manual.py", lang=t("es-AR", "en-US", "pt-BR"), **kw)
        self.version = version
        self.chapter = ""
        fr = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        cover = Frame(0, 0, A4[0], A4[1], leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="c")
        self.addPageTemplates([PageTemplate("cover", [cover], onPage=self.draw_cover),
                               PageTemplate("body", [fr], onPageEnd=self.decorate)])

    def afterFlowable(self, fl):
        if isinstance(fl, (Heading, ChapterHead)) and getattr(fl, "key", None):
            c = self.canv
            c.bookmarkPage(fl.key)
            if fl.level == 0:
                self.chapter = fl.plain
            if fl.toc:
                c.addOutlineEntry(fl.plain, fl.key, level=fl.level, closed=False)
                self.notify("TOCEntry", (fl.level, fl.plain, self.page, fl.key))

    def handle_documentBegin(self):
        self.chapter = ""
        super().handle_documentBegin()

    # -------------------------------------------------------------------------------- page decoration
    def decorate(self, c, doc):
        w, h = A4
        c.saveState()
        c.setStrokeColor(colors.HexColor("#e5e7eb"))
        c.setLineWidth(0.6)
        c.line(self.leftMargin, h - 15 * mm, w - self.rightMargin, h - 15 * mm)
        if os.path.isfile(ICON):
            c.drawImage(ICON, self.leftMargin, h - 13.9 * mm, 10, 10, mask="auto")
        c.setFont("HeadM", 7.8)
        c.setFillColor(ACCENT)
        c.drawString(self.leftMargin + 13, h - 13 * mm, "VToyEditor Plus+")
        c.setFillColor(GREY)
        c.setFont("Body", 8.2)
        c.drawRightString(w - self.rightMargin, h - 13 * mm, self.chapter)
        # footer: page number, and a link back to the index
        c.line(self.leftMargin, 14 * mm, w - self.rightMargin, 14 * mm)
        c.setFont("Body", 8.2)
        c.setFillColor(GREY)
        c.drawString(self.leftMargin, 9.5 * mm, t("Manual de usuario", "User manual", "Manual do usuário") + f" · {self.version}")
        label = "\u25b2 " + t("Índice", "Contents", "Índice")
        c.setFont("Sym", 8)
        c.setFillColor(ACCENT)
        lw = pdfmetrics.stringWidth(label, "Sym", 8)
        cx = w / 2
        c.drawCentredString(cx, 9.5 * mm, label)
        c.linkRect("", "toc", (cx - lw / 2 - 3, 8 * mm, cx + lw / 2 + 3, 12.5 * mm), relative=0, thickness=0)
        c.setFont("HeadM", 9)
        c.setFillColor(NAVY)
        c.drawRightString(w - self.rightMargin, 9.5 * mm, str(doc.page))
        c.restoreState()

    def draw_cover(self, c, doc):
        w, h = A4
        c.saveState()
        n = 60                                               # background: navy, lighter towards the top
        for k in range(n):
            f = k / (n - 1)
            c.setFillColor(colors.Color(0.078 + 0.06 * f, 0.129 + 0.07 * f, 0.239 + 0.1 * f))
            c.rect(0, h * k / n, w, h / n + 1, stroke=0, fill=1)
        # an isometric town of blocks (original art)
        def iso(x, y, sx, sy, hz, col, alpha=1.0):
            c.setFillAlpha(alpha)
            a, b = 0.866, 0.5
            top = [(x, y + hz), (x + sx * a, y + sx * b + hz), (x + sx * a - sy * a, y + sx * b + sy * b + hz),
                   (x - sy * a, y + sy * b + hz)]
            right = [(x, y), (x + sx * a, y + sx * b), (x + sx * a, y + sx * b + hz), (x, y + hz)]
            left = [(x, y), (x - sy * a, y + sy * b), (x - sy * a, y + sy * b + hz), (x, y + hz)]
            for pts, f in ((left, 0.62), (right, 0.82), (top, 1.0)):
                c.setFillColor(colors.Color(min(col.red * f + (0.08 if f == 1 else 0), 1),
                                            min(col.green * f + (0.08 if f == 1 else 0), 1),
                                            min(col.blue * f + (0.08 if f == 1 else 0), 1)))
                p = c.beginPath()
                p.moveTo(*pts[0])
                for q in pts[1:]:
                    p.lineTo(*q)
                p.close()
                c.drawPath(p, stroke=0, fill=1)
            c.setFillAlpha(1)
        # grid floor
        c.setStrokeColor(colors.Color(1, 1, 1, 0.07))
        c.setLineWidth(0.6)
        ox, oy = w * 0.5, h * 0.13
        for k in range(-12, 13):
            c.line(ox + k * 26 * 0.866, oy + k * 26 * 0.5 - 0, ox + k * 26 * 0.866 - 12 * 26 * 0.866, oy + k * 26 * 0.5 + 12 * 26 * 0.5)
            c.line(ox - k * 26 * 0.866, oy + k * 26 * 0.5, ox - k * 26 * 0.866 + 12 * 26 * 0.866, oy + k * 26 * 0.5 + 12 * 26 * 0.5)
        cell = 22                                            # a small town of blocks (none overlaps another)
        town = [(0, 0, 3, 3, 70, ACCENT), (4, 1, 2, 2, 130, TEAL), (-4, 2, 2, 3, 100, ACCENT2), (1, 5, 2, 2, 185, TEAL),
                (5, 5, 3, 2, 60, ACCENT), (-3, 7, 3, 2, 140, ACCENT), (-7, 3, 2, 2, 50, TEAL), (8, 2, 2, 2, 90, ACCENT2),
                (2, 9, 2, 2, 95, ACCENT2), (-8, 7, 2, 2, 75, ACCENT2)]
        for gx, gy, sx, sy, hz, col in sorted(town, key=lambda t: -(t[0] + t[1])):
            x = ox + (gx - gy) * cell * 0.866
            y = oy + (gx + gy) * cell * 0.5
            iso(x, y, sx * cell, sy * cell, hz, col, 0.96)
        # top band
        c.setFillColor(ACCENT)
        c.rect(0, h - 9 * mm, w, 9 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("HeadM", 9)
        c.drawString(22 * mm, h - 6 * mm, t("MANUAL DE USUARIO", "USER MANUAL", "MANUAL DO USUÁRIO"))
        c.drawRightString(w - 20 * mm, h - 6 * mm, self.version)
        # the program's icon and the title
        tx = 22 * mm
        if os.path.isfile(ICON):
            c.drawImage(ICON, 22 * mm, h - 57 * mm, 58, 58, mask="auto")
            tx = 22 * mm + 70
        c.setFont("Head", 40)
        c.setFillColor(colors.white)
        c.drawString(tx, h - 52 * mm, "VToyEditor")
        c.setFillColor(ACCENT2)
        c.drawString(tx + pdfmetrics.stringWidth("VToyEditor ", "Head", 40), h - 52 * mm, "Plus+")
        c.setFont("HeadL", 17)
        c.setFillColor(colors.HexColor("#cbd5e1"))
        c.drawString(22 * mm, h - 68 * mm, t("Editor de mapas y escenas para Torrente Online",
                                             "Map and scene editor for Torrente Online",
                                             "Editor de mapas e cenas para Torrente Online"))
        c.setStrokeColor(ACCENT)
        c.setLineWidth(3)
        c.line(22 * mm, h - 75 * mm, 62 * mm, h - 75 * mm)
        c.setFont("Body", 11.5)
        c.setFillColor(colors.HexColor("#e2e8f0"))
        y = h - 86 * mm
        for ln in t(("Cómo se usa cada función, y cómo crear un mapa",
                     "desde cero, desde Counter-Strike 1.6 o desde Torrente, el juego."),
                    ("How to use every function, and how to make a map",
                     "from zero, from Counter-Strike 1.6 or from Torrente, el juego."),
                    ("Como usar cada função, e como criar um mapa",
                     "do zero, a partir do Counter-Strike 1.6 ou de Torrente, el juego.")):
            c.drawString(22 * mm, y, ln)
            y -= 15
        # version chip
        chip = t("Versión", "Version", "Versão") + f" {self.version.lstrip('v')}"
        cw = pdfmetrics.stringWidth(chip, "HeadM", 10) + 20
        c.setFillColor(colors.Color(1, 1, 1, 0.12))
        c.roundRect(22 * mm, h - 112 * mm, cw, 20, 10, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("HeadM", 10)
        c.drawString(22 * mm + 10, h - 112 * mm + 6.2, chip)
        # footer
        c.setFillColor(colors.Color(0, 0, 0, 0.35))
        c.rect(0, 0, w, 22 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("HeadM", 10.5)
        c.drawString(22 * mm, 13 * mm, "Lahrenheit")
        c.setFont("Body", 9.5)
        c.setFillColor(colors.HexColor("#cbd5e1"))
        c.drawString(22 * mm, 8 * mm, "github.com/Lahrenheit/VToyEditorPlus")
        c.drawRightString(w - 20 * mm, 8 * mm, t("Basado en el VToyEditor de Patoke", "Based on Patoke's VToyEditor",
                                                 "Baseado no VToyEditor de Patoke"))
        c.linkURL("https://github.com/Lahrenheit/VToyEditorPlus", (22 * mm, 6 * mm, 90 * mm, 12 * mm), relative=0)
        c.restoreState()


# ------------------------------------------------------------------------------------------------ content
def content(st, W, version):
    S = []
    chap = [0]
    sec = [0]
    lang = LANGS[_lang[0]]
    KEY_DEL = t("Supr", "Del", "Del")
    KEY_SPACE = t("Espacio", "Space", "Espaço")
    ch_word = t("capítulo", "chapter", "capítulo")
    fig_word = t("Figura", "Figure", "Figura")

    def H1(title, key):
        chap[0] += 1
        sec[0] = 0
        S.append(PageBreak())
        S.append(ChapterHead(chap[0], title, key, W))
        S.append(Spacer(1, 12))

    def H2(title, key=None):
        sec[0] += 1
        k = key or f"s{chap[0]}_{sec[0]}"
        S.append(CondPageBreak(60))
        S.append(Heading(f"{chap[0]}.{sec[0]}&nbsp;&nbsp;{title}", st["h2"], 1, k))

    def P(x, s="body"):
        S.append(Paragraph(x, st[s]))

    def UL(items):
        S.extend(bullets(items, st))
        S.append(Spacer(1, 4))

    def OL(items):
        S.append(steps(items, st))
        S.append(Spacer(1, 5))

    def T(head, rows, widths):
        S.append(table(head, rows, [W * x for x in widths], st))
        S.append(Spacer(1, 7))

    def BOX(kind, x):
        S.append(box(kind, x, st))

    def FIG(d, n, cap):
        S.append(KeepTogether([Fig(d), Paragraph(f"{fig_word} {n}. {cap}", st["cap"])]))

    def chap_link(key, n):
        return link(key, f"{ch_word} {n}")

    HT = (t("Herramienta", "Tool", "Ferramenta"), t("Qué hace", "What it does", "O que faz"))

    # ---------------------------------------------------------------- index
    S.append(NextPageTemplate("body"))
    S.append(PageBreak())
    S.append(ChapterHead(0, t("Índice", "Contents", "Índice"), "toc", W))
    S[-1].toc = False
    S.append(Spacer(1, 10))
    toc = TableOfContents(dotsMinLevel=0)
    toc.levelStyles = [st["toc0"], st["toc1"]]
    S.append(toc)
    S.append(Spacer(1, 8))
    arrow = '<font name="Sym">\u25b2</font>'
    S.append(Paragraph('<font color="#6b7280">' + t(
        f"Tocá cualquier título del índice para ir a su página. Al pie de cada página, <b>{arrow} Índice</b> vuelve acá. "
        "En el lector de PDF también están los marcadores (panel lateral).",
        f"Click any title in the contents to go to its page. At the foot of every page, <b>{arrow} Contents</b> comes back "
        "here. The PDF reader also shows the bookmarks (side panel).",
        f"Clique em qualquer título do índice para ir à sua página. No pé de cada página, <b>{arrow} Índice</b> volta "
        "aqui. O leitor de PDF também mostra os marcadores (painel lateral).") + "</font>", st["body"]))

    # ================================================================ 1
    H1(t("Introducción", "Introduction", "Introdução"), "c_intro")
    P(t("VToyEditor Plus+ es un editor de mapas y escenas para <b>Torrente Online</b>, el juego de Virtual Toys. Con él "
        "podés abrir cualquier mapa del juego y cambiarlo. También podés crear mapas nuevos de tres maneras: desde cero, "
        "desde un mapa de <b>Counter-Strike 1.6</b>, o con lo que trae <b>Torrente, el juego</b>. Está basado en el "
        "VToyEditor de Patoke y lo hace Lahrenheit.",
        "VToyEditor Plus+ is a map and scene editor for <b>Torrente Online</b>, the game by Virtual Toys. With it you can "
        "open any map of the game and change it. You can also make new maps in three ways: from zero, from a "
        "<b>Counter-Strike 1.6</b> map, or with what <b>Torrente, el juego</b> has. It is based on Patoke's VToyEditor "
        "and made by Lahrenheit.",
        "O VToyEditor Plus+ é um editor de mapas e cenas para o <b>Torrente Online</b>, o jogo da Virtual Toys. Com ele "
        "você pode abrir qualquer mapa do jogo e alterá-lo. Também pode criar mapas novos de três formas: do zero, a "
        "partir de um mapa do <b>Counter-Strike 1.6</b>, ou com o que o <b>Torrente, el juego</b> tem. É baseado no "
        "VToyEditor de Patoke e feito por Lahrenheit."), "lead")
    H2(t("Qué se puede hacer", "What you can do", "O que dá para fazer"))
    UL([t("<b>Abrir y guardar todos los archivos del juego</b> sin perder nada: el paquete " + C("demo.vpk") + ", las "
          "escenas, los mapas, la colisión del piso, los modelos, las animaciones y las texturas.",
          "<b>Open and save every file of the game</b> without losing anything: the " + C("demo.vpk") + " package, "
          "scenes, maps, floor collision, models, animations and textures.",
          "<b>Abrir e salvar todos os arquivos do jogo</b> sem perder nada: o pacote " + C("demo.vpk") + ", as cenas, "
          "os mapas, a colisão do chão, os modelos, as animações e as texturas."),
        t("<b>Ver el mapa en 3D</b> y editar todo lo que tiene: puntos de inicio, botiquines, banderas, la bomba, autos, "
          "puertas, modelos, luces, decals, niebla, cielo y música.",
          "<b>See the map in 3D</b> and edit everything in it: start points, health packs, flags, the bomb, cars, doors, "
          "models, lights, decals, fog, sky and music.",
          "<b>Ver o mapa em 3D</b> e editar tudo o que ele tem: pontos de início, kits médicos, bandeiras, a bomba, "
          "carros, portas, modelos, luzes, decals, neblina, céu e música."),
        t("<b>Construir</b> con herramientas: formas y sólidos con colisión, barandas a lo largo de un recorrido, pincel "
          "de árboles y piedras, importar modelos OBJ, piezas reutilizables.",
          "<b>Build</b> with tools: shapes and solids with collision, railings along a path, a brush for trees and rocks, "
          "OBJ model import, reusable pieces.",
          "<b>Construir</b> com ferramentas: formas e sólidos com colisão, corrimãos ao longo de um caminho, pincel de "
          "árvores e pedras, importação de modelos OBJ, peças reutilizáveis."),
        t("<b>Armar los 4 modos de juego</b>: deathmatch, deathmatch por equipos, capturar la bandera y destruir el "
          "objetivo (con dos sitios de bomba, tiempo de la bomba, HUD y radar).",
          "<b>Set up the 4 game modes</b>: deathmatch, team deathmatch, capture the flag and destroy the target (with two "
          "bomb sites, bomb time, HUD and radar).",
          "<b>Montar os 4 modos de jogo</b>: deathmatch, deathmatch por equipes, capturar a bandeira e destruir o alvo "
          "(com dois locais de bomba, tempo da bomba, HUD e radar)."),
        t("<b>Revisar el mapa antes de jugar</b>: revisión automática, prueba de caminar con la colisión real, buscador de "
          "caídas, balance de equipos y simulación de partida.",
          "<b>Check the map before playing</b>: automatic map check, walk test with the real collision, fall finder, team "
          "balance and match simulation.",
          "<b>Verificar o mapa antes de jogar</b>: verificação automática, teste de caminhada com a colisão real, "
          "buscador de quedas, equilíbrio dos times e simulação de partida."),
        t("<b>Compartir</b>: exportar el mapa en un " + C(".zip") + " con todo lo que necesita, e instalar mapas de otros "
          "sin pisar archivos del juego.",
          "<b>Share</b>: export the map as a " + C(".zip") + " with everything it needs, and install other people's maps "
          "without overwriting game files.",
          "<b>Compartilhar</b>: exportar o mapa num " + C(".zip") + " com tudo o que ele precisa, e instalar mapas de "
          "outros sem sobrescrever arquivos do jogo.")])
    H2(t("Las piezas de un mapa", "The parts of a map", "As partes de um mapa"), "k_files")
    P(t("Conviene conocer estas palabras, porque aparecen en todo el editor:",
        "These words show up all over the editor, so it helps to know them:",
        "Vale a pena conhecer estas palavras, porque aparecem no editor inteiro:"))
    FIG(fig_files(W), 1, t("Qué guarda cada archivo de un mapa.", "What each file of a map holds.",
                           "O que cada arquivo de um mapa guarda."))
    T([t("Archivo", "File", "Arquivo"), t("Qué es", "What it is", "O que é")],
      [[C(".scn") + t(" escena", " scene", " cena"),
        t("El mapa “jugable”: qué módulos tiene (puntos de inicio, botiquines, banderas, zonas de bomba, autos, puertas, "
          "modelos, sonidos), el cielo, la niebla, la música y la <b>DLL del modo</b> (el programa del modo de juego). En "
          "el menú del juego cada escena es un mapa.",
          "The “playable” map: which modules it has (start points, health packs, flags, bomb zones, cars, doors, models, "
          "sounds), the sky, the fog, the music and the <b>mode DLL</b> (the program of the game mode). In the game's "
          "menu, each scene is a map.",
          "O mapa “jogável”: quais módulos tem (pontos de início, kits médicos, bandeiras, zonas de bomba, carros, "
          "portas, modelos, sons), o céu, a neblina, a música e a <b>DLL do modo</b> (o programa do modo de jogo). No "
          "menu do jogo, cada cena é um mapa.")],
       [C(".opt") + t(" mapa", " map", " mapa"),
        t("La geometría: <b>mallas</b> (lo que se dibuja), <b>props</b> (copias de una malla), <b>decals</b> "
          "(calcomanías), <b>luces</b>, <b>cajas de colisión</b> y los <b>sectores</b> (qué se dibuja desde dónde).",
          "The geometry: <b>meshes</b> (what is drawn), <b>props</b> (copies of a mesh), <b>decals</b> (stickers), "
          "<b>lights</b>, <b>collision boxes</b> and <b>sectors</b> (what is drawn from where).",
          "A geometria: <b>malhas</b> (o que é desenhado), <b>props</b> (cópias de uma malha), <b>decals</b> "
          "(adesivos), <b>luzes</b>, <b>caixas de colisão</b> e os <b>setores</b> (o que é desenhado de onde).")],
       [C(".hm") + t(" piso", " floor", " chão"),
        t("La colisión por la que se camina: caras de <b>piso</b>, <b>rampa</b> y <b>pared</b>.",
          "The collision you walk on: <b>floor</b>, <b>ramp</b> and <b>wall</b> faces.",
          "A colisão por onde se anda: faces de <b>chão</b>, <b>rampa</b> e <b>parede</b>.")],
       [C(".tex") + ", " + C(".nfo") + ", " + C(".key"),
        t("Texturas, modelos y animaciones.", "Textures, models and animations.", "Texturas, modelos e animações.")],
       [C("demo.vpk"), t("El paquete con todos los archivos del juego. El editor lo desempaqueta y lo vuelve a armar.",
                         "The package with all the game's files. The editor unpacks it and packs it again.",
                         "O pacote com todos os arquivos do jogo. O editor o descompacta e o monta de novo.")],
       [C("mp_*.dll"), t("Los programas de los modos y de algunos módulos. Algunos mapas usan una <b>copia</b> propia (por "
                         "ejemplo, la de destruir el objetivo con dos zonas). La original del juego nunca se toca.",
                         "The programs of the modes and of some modules. Some maps use a <b>copy</b> of their own (for "
                         "example, destroy the target with two zones). The game's original is never touched.",
                         "Os programas dos modos e de alguns módulos. Alguns mapas usam uma <b>cópia</b> própria (por "
                         "exemplo, destruir o alvo com duas zonas). A original do jogo nunca é alterada.")]],
      [0.22, 0.78])
    P(t("Las medidas del editor están en <b>unidades del motor</b>: una unidad es más o menos un centímetro. Un jugador "
        "mide unas 180 unidades, y los puntos de inicio van 20 unidades sobre el piso.",
        "The editor measures in <b>engine units</b>: one unit is about a centimetre. A player is about 180 units tall, and "
        "start points sit 20 units above the floor.",
        "As medidas do editor estão em <b>unidades do motor</b>: uma unidade é mais ou menos um centímetro. Um jogador "
        "mede umas 180 unidades, e os pontos de início ficam 20 unidades acima do chão."))
    H2(t("Reglas de seguridad del editor", "The editor's safety rules", "Regras de segurança do editor"))
    UL([t("<b>Nunca se pisan archivos del juego.</b> Si algo importado choca con un nombre que ya existe, entra con otro "
          "nombre. Instalar un mapa saltea los archivos que el juego ya tiene.",
          "<b>Game files are never overwritten.</b> If something imported clashes with a name that already exists, it "
          "comes in under another name. Installing a map skips the files the game already has.",
          "<b>Arquivos do jogo nunca são sobrescritos.</b> Se algo importado tem um nome que já existe, entra com outro "
          "nome. Instalar um mapa pula os arquivos que o jogo já tem."),
        t("<b>Todo se puede deshacer</b> con " + K("Ctrl", "Z") + " (hasta 30 pasos).",
          "<b>Everything can be undone</b> with " + K("Ctrl", "Z") + " (up to 30 steps).",
          "<b>Tudo pode ser desfeito</b> com " + K("Ctrl", "Z") + " (até 30 passos)."),
        t("<b>Cada guardado queda en el historial</b> (los últimos 10, en " + C("vtoy_history") + "), y "
          "<b>Reempaquetar VPK</b> deja una copia " + C(".bak") + " del " + C("demo.vpk") + " anterior.",
          "<b>Every save goes into the history</b> (the last 10, in " + C("vtoy_history") + "), and <b>Repackage VPK</b> "
          "keeps a " + C(".bak") + " copy of the previous " + C("demo.vpk") + ".",
          "<b>Cada salvamento fica no histórico</b> (os últimos 10, em " + C("vtoy_history") + "), e <b>Reempacotar "
          "VPK</b> deixa uma cópia " + C(".bak") + " do " + C("demo.vpk") + " anterior."),
        t("<b>Guardar como</b> crea un mapa nuevo con su propio " + C(".opt") + " y " + C(".hm") + ", así el original no cambia.",
          "<b>Save as</b> makes a new map with its own " + C(".opt") + " and " + C(".hm") + ", so the original does not change.",
          "<b>Salvar como</b> cria um mapa novo com seu próprio " + C(".opt") + " e " + C(".hm") + ", assim o original "
          "não muda.")])
    BOX("note", t("Las funciones nuevas se prueban con los archivos reales del juego, pero no siempre dentro del juego. "
                  "Antes de publicar un mapa, probalo en una partida (" + chap_link("c_share", 10) + ").",
                  "New functions are tested with the game's real files, but not always inside the game. Before you "
                  "publish a map, try it in a match (" + chap_link("c_share", 10) + ").",
                  "As funções novas são testadas com os arquivos reais do jogo, mas nem sempre dentro do jogo. Antes "
                  "de publicar um mapa, teste-o numa partida (" + chap_link("c_share", 10) + ")."))

    # ================================================================ 2
    H1(t("Instalación y primer inicio", "Installing and first start", "Instalação e primeiro início"), "c_install")
    H2(t("Requisitos", "Requirements", "Requisitos"))
    UL([t("Windows 10 u 11 y <b>Torrente Online</b> instalado.", "Windows 10 or 11 and <b>Torrente Online</b> installed.",
          "Windows 10 ou 11 e o <b>Torrente Online</b> instalado."),
        t("Una placa de video con OpenGL 3.3. Con dos placas, conviene que el editor use la dedicada (" +
          chap_link("c_trouble", 11) + ").",
          "A graphics card with OpenGL 3.3. With two cards, let the editor use the dedicated one (" +
          chap_link("c_trouble", 11) + ").",
          "Uma placa de vídeo com OpenGL 3.3. Com duas placas, convém que o editor use a dedicada (" +
          chap_link("c_trouble", 11) + ").")])
    H2(t("Instalar", "Installing", "Instalar"), "k_install")
    OL([t("Bajá el último release de ", "Download the latest release from ", "Baixe o último release de ") +
        C("github.com/Lahrenheit/VToyEditorPlus/releases") + ".",
        t("Descomprimí <b>la carpeta entera</b>, porque el " + C(".exe") + " solo no funciona. Por ejemplo, en ",
          "Unzip <b>the whole folder</b>, because the " + C(".exe") + " alone does not work. For example, into ",
          "Descompacte <b>a pasta inteira</b>, porque o " + C(".exe") + " sozinho não funciona. Por exemplo, em ") +
        C("E:\\Juegos\\Torrente On-Line\\tools\\VToyEditor") + ".",
        t("Abrí ", "Run ", "Abra ") + C("VToyEditor.exe") + ".",
        t("La primera vez, elegí el " + C("demo.vpk") + " del juego. El editor lo desempaqueta una sola vez en una carpeta "
          + C("demo_unpacked") + " al lado del paquete, y desde ahí trabaja.",
          "The first time, pick the game's " + C("demo.vpk") + ". The editor unpacks it once into a " + C("demo_unpacked") +
          " folder next to the package, and works from there.",
          "Na primeira vez, escolha o " + C("demo.vpk") + " do jogo. O editor o descompacta uma única vez numa pasta " +
          C("demo_unpacked") + " ao lado do pacote, e trabalha a partir dela."),
        t("Elegí el idioma en el menú " + M("Idioma") + ": inglés, español o portugués.",
          "Pick the language in the " + M("Language") + " menu: English, Spanish or Portuguese.",
          "Escolha o idioma no menu " + M("Idioma") + ": inglês, espanhol ou português."),
        t("Este manual se abre desde " + M("Ayuda > Manual de usuario (PDF)") + ", en el idioma del editor.",
          "This manual opens from " + M("Help > User manual (PDF)") + ", in the editor's language.",
          "Este manual abre em " + M("Ajuda > Manual do usuário (PDF)") + ", no idioma do editor.")])
    H2(t("Archivos que el editor deja a su lado", "Files the editor keeps next to it", "Arquivos que o editor deixa ao lado"))
    T([t("Archivo / carpeta", "File / folder", "Arquivo / pasta"), t("Para qué", "What for", "Para quê")],
      [[C("vtoy_editor.json"), t("Tus opciones: idioma, último mapa, carpetas, candados, atajos. No lo borres al actualizar.",
                                 "Your settings: language, last map, folders, locks, shortcuts. Do not delete it when updating.",
                                 "Suas opções: idioma, último mapa, pastas, cadeados, atalhos. Não apague ao atualizar.")],
       [C("imgui.ini"), t("Dónde quedó cada ventana.", "Where each window was left.", "Onde ficou cada janela.")],
       [C("vtoy_editor.log"), t("Todo lo que hace el editor, con los errores completos. Es lo primero que hay que mirar si algo falla.",
                                "Everything the editor does, with full errors. The first thing to look at when something fails.",
                                "Tudo o que o editor faz, com os erros completos. É a primeira coisa a ver se algo falhar.")],
       [C("prefabs\\"), t("Tus piezas guardadas (grupos reutilizables).", "Your saved pieces (reusable groups).",
                          "Suas peças salvas (grupos reutilizáveis).")],
       [C("vtoy_history\\"), t("Los últimos 10 guardados de cada mapa.", "The last 10 saves of each map.",
                               "Os últimos 10 salvamentos de cada mapa.")],
       [C("export\\"), t("Junto al " + C("demo.vpk") + ": los " + C(".zip") + " exportados, capturas y PNG. Se puede "
                         "cambiar en " + M("Configuración") + ".",
                         "Next to " + C("demo.vpk") + ": exported " + C(".zip") + " files, screenshots and PNGs. It can be "
                         "changed in " + M("Settings") + ".",
                         "Ao lado do " + C("demo.vpk") + ": os " + C(".zip") + " exportados, capturas e PNG. Pode ser "
                         "mudada em " + M("Configurações") + ".")]],
      [0.28, 0.72])
    H2(t("Configuración", "Settings", "Configurações"), "k_settings")
    P(t("En el menú " + M("Configuración") + ":", "In the " + M("Settings") + " menu:",
        "No menu " + M("Configurações") + ":"))
    UL([t("<b>Abrir el último mapa al iniciar</b> y <b>Restaurar la última posición de cámara</b>.",
          "<b>Open the last map on start</b> and <b>Restore the last camera position</b>.",
          "<b>Abrir o último mapa ao iniciar</b> e <b>Restaurar a última posição da câmera</b>."),
        t("<b>Buscar versiones nuevas al iniciar</b> (" + link("k_update", "ver abajo") + ").",
          "<b>Check for newer versions on start</b> (" + link("k_update", "see below") + ").",
          "<b>Procurar versões novas ao iniciar</b> (" + link("k_update", "veja abaixo") + ")."),
        t("<b>Carpeta de exportación</b>: vacía significa la carpeta " + C("export") + " al lado del " + C("demo.vpk") + ".",
          "<b>Export folder</b>: empty means the " + C("export") + " folder next to " + C("demo.vpk") + ".",
          "<b>Pasta de exportação</b>: vazia significa a pasta " + C("export") + " ao lado do " + C("demo.vpk") + "."),
        t("<b>Mostrar la ventana de consola</b> y <b>Escribir vtoy_editor.log</b>.",
          "<b>Show the console window</b> and <b>Write vtoy_editor.log</b>.",
          "<b>Mostrar a janela do console</b> e <b>Escrever vtoy_editor.log</b>.")])
    H2(t("Versiones nuevas y actualización", "New versions and updating", "Versões novas e atualização"), "k_update")
    P(t("Al iniciar, el editor busca en GitHub si hay una versión más nueva. La búsqueda no hace esperar, y si no hay "
        "internet no pasa nada. Si encuentra una, aparece un cartel que dice cuál es, cuál tenés y sus notas, con el link "
        "para bajarla.",
        "On start, the editor checks GitHub for a newer version. It never makes you wait, and without internet nothing "
        "happens. If it finds one, a notice shows which one it is, which one you have and its notes, with the link to "
        "download it.",
        "Ao iniciar, o editor procura no GitHub se há uma versão mais nova. A busca não faz esperar, e sem internet nada "
        "acontece. Se encontrar uma, aparece um aviso com qual é, qual você tem e as notas, com o link para baixá-la."))
    OL([t("Tocá <b>Descargar y actualizar</b>. El editor baja el " + C(".zip") + " o " + C(".7z") + " y lo descomprime en ",
          "Click <b>Download and update</b>. The editor downloads the " + C(".zip") + " or " + C(".7z") + " and unpacks it into ",
          "Clique em <b>Baixar e atualizar</b>. O editor baixa o " + C(".zip") + " ou " + C(".7z") + " e o descompacta em ") +
        C("_vtoy_update") + ".",
        t("Para instalarla <b>hay que cerrar el editor</b>. Si no hay cambios sin guardar, se cierra solo en 10 segundos. "
          "Si los hay, al cerrar te pregunta si querés guardarlos.",
          "To install it <b>the editor has to close</b>. With nothing unsaved it closes by itself in 10 seconds; otherwise "
          "it asks whether to save when closing.",
          "Para instalá-la <b>é preciso fechar o editor</b>. Sem alterações não salvas, ele fecha sozinho em 10 segundos. "
          "Se houver, ao fechar ele pergunta se quer salvá-las."),
        t("Al cerrarse, una ventanita copia los archivos nuevos sobre los del programa y vuelve a abrir el editor. Tus "
          "opciones (" + C("vtoy_editor.json") + ") no se tocan.",
          "Once closed, a small window copies the new files over the program's and opens the editor again. Your settings ("
          + C("vtoy_editor.json") + ") are not touched.",
          "Ao fechar, uma janelinha copia os arquivos novos sobre os do programa e abre o editor de novo. Suas opções (" +
          C("vtoy_editor.json") + ") não são alteradas."),
        t("<b>Más tarde</b> deja la actualización para cuando cierres el editor.",
          "<b>Later</b> leaves the update for when you close the editor.",
          "<b>Mais tarde</b> deixa a atualização para quando você fechar o editor.")])
    P(t("Para buscar en cualquier momento: " + M("Ayuda > Buscar versiones nuevas ahora") + ". La versión que tenés está en "
        + M("Ayuda > Acerca de") + " y en las propiedades del " + C(".exe") + ".",
        "To check at any time: " + M("Help > Check for newer versions now") + ". Your version is in " + M("Help > About") +
        " and in the " + C(".exe") + "'s properties.",
        "Para procurar a qualquer momento: " + M("Ajuda > Procurar versões novas agora") + ". A sua versão está em " +
        M("Ajuda > Sobre") + " e nas propriedades do " + C(".exe") + "."))

    # ================================================================ 3
    H1(t("La pantalla del editor", "The editor's screen", "A tela do editor"), "c_screen")
    FIG(fig_screen(W), 2, t("Las partes de la pantalla. Las ventanas se pueden mover y cambiar de tamaño.",
                            "The parts of the screen. Windows can be moved and resized.",
                            "As partes da tela. As janelas podem ser movidas e redimensionadas."))
    T(["", t("Parte", "Part", "Parte"), t("Qué tiene", "What it has", "O que tem")],
      [["1", t("Menú", "Menu", "Menu"), t(M("Archivo") + ", " + M("Editar") + ", " + M("Ver") + ", " + M("Idioma") + ", " +
                                          M("Configuración") + " y " + M("Ayuda") + ".",
                                          M("File") + ", " + M("Edit") + ", " + M("View") + ", " + M("Language") + ", " +
                                          M("Settings") + " and " + M("Help") + ".",
                                          M("Arquivo") + ", " + M("Editar") + ", " + M("Exibir") + ", " + M("Idioma") + ", " +
                                          M("Configurações") + " e " + M("Ajuda") + ".")],
       ["2", t("Cuadro de información", "Info panel", "Quadro de informações"),
        t("FPS, posición y ángulos de la cámara, el modo del mouse, las teclas del momento y si estás <b>creando</b> o "
          "<b>modificando</b> un mapa. " + K("F1") + " lo oculta.",
          "FPS, camera position and angles, the mouse mode, the keys you can use and whether you are <b>creating</b> or "
          "<b>editing</b> a map. " + K("F1") + " hides it.",
          "FPS, posição e ângulos da câmera, o modo do mouse, as teclas do momento e se você está <b>criando</b> ou "
          "<b>modificando</b> um mapa. " + K("F1") + " o oculta.")],
       ["3", t("Herramientas 1–9", "Tools 1–9", "Ferramentas 1–9"),
        t("Seleccionar, Mover, Rotar, Escalar, Pluma, Relleno, Medir, Colisión y Pintar caras.",
          "Select, Move, Rotate, Scale, Pen, Fill, Measure, Collision and Paint faces.",
          "Selecionar, Mover, Girar, Escalar, Caneta, Preencher, Medir, Colisão e Pintar faces.")],
       ["4", t("Panel DEBUG", "DEBUG panel", "Painel DEBUG"),
        t("Escenas y mapas, la librería de Torrente el juego, el modo de juego, luces, decals, la escena y sus módulos, lo "
          "seleccionado y las opciones de vista.",
          "Scenes and maps, the Torrente el juego library, the game mode, lights, decals, the scene and its modules, the "
          "selection and the view options.",
          "Cenas e mapas, a biblioteca de Torrente el juego, o modo de jogo, luzes, decals, a cena e seus módulos, a "
          "seleção e as opções de exibição.")],
       ["5", t("Herramientas del mapa", "Map tools", "Ferramentas do mapa"),
        t("Todas las herramientas, en 6 categorías (", "All the tools, in 6 categories (",
          "Todas as ferramentas, em 6 categorias (") + chap_link("c_tools", 6) + ")."],
       ["6", t("Vista 3D", "3D view", "Vista 3D"),
        t("El mapa como lo dibuja el juego, con lo seleccionado resaltado.",
          "The map as the game draws it, with the selection highlighted.",
          "O mapa como o jogo o desenha, com a seleção destacada.")]],
      [0.05, 0.22, 0.73])
    H2(t("El menú de arriba", "The menu bar", "O menu de cima"))
    T([t("Menú", "Menu", "Menu"), t("Opciones", "Items", "Opções")],
      t([[M("Archivo"), "Guardar escena (y mapa editado) · Guardar escena como… · Exportar este mapa como .zip… · Mapa nuevo "
          "desde CS 1.6 (.bsp / .rmf)… · Vista previa del mapa 256x256… · Carpeta de Torrente, el juego… · Instalar mapa desde "
          "zip… · Guardar, empaquetar y probar en el juego · Captura de pantalla " + K("F12") + " · Abrir carpeta de capturas"],
         [M("Editar"), "Deshacer " + K("Ctrl", "Z") + " · Rehacer " + K("Ctrl", "Y") + " · Copiar selección " + K("Q") +
          " · Eliminar selección " + K(KEY_DEL)],
         [M("Ver"), "Cielo, decals, niebla y colisión (cajas) · Ventana de partes del mapa · Ventana Herramientas del mapa · "
          "Colisión de piso (.hm) · Ocultar la selección " + K("H") + " · Mostrar todos los objetos ocultos " + K("Shift", "H")],
         [M("Idioma"), "English · Español · Português"],
         [M("Configuración"), "Ver " + link("k_settings", "Configuración") + "."],
         [M("Ayuda"), "Manual de usuario (PDF) · Buscar versiones nuevas ahora · Acerca de"]],
        [[M("File"), "Save scene (and edited map) · Save scene as… · Export this map as .zip… · New map from CS 1.6 "
          "(.bsp / .rmf)… · Map preview 256x256… · Torrente, el juego folder… · Install map from zip… · Save, pack and "
          "play in the game · Screenshot " + K("F12") + " · Open screenshots folder"],
         [M("Edit"), "Undo " + K("Ctrl", "Z") + " · Redo " + K("Ctrl", "Y") + " · Copy selection " + K("Q") +
          " · Delete selection " + K(KEY_DEL)],
         [M("View"), "Sky, decals, fog and collision (boxes) · Map parts window · Map tools window · Floor collision "
          "(.hm) · Hide the selection " + K("H") + " · Show all hidden objects " + K("Shift", "H")],
         [M("Language"), "English · Español · Português"],
         [M("Settings"), "See " + link("k_settings", "Settings") + "."],
         [M("Help"), "User manual (PDF) · Check for newer versions now · About"]],
        [[M("Arquivo"), "Salvar cena (e mapa editado) · Salvar cena como… · Exportar este mapa como .zip… · Mapa novo a "
          "partir de CS 1.6 (.bsp / .rmf)… · Pré-visualização do mapa 256x256… · Pasta de Torrente, el juego… · Instalar "
          "mapa de zip… · Salvar, empacotar e testar no jogo · Captura de tela " + K("F12") + " · Abrir pasta de capturas"],
         [M("Editar"), "Desfazer " + K("Ctrl", "Z") + " · Refazer " + K("Ctrl", "Y") + " · Copiar seleção " + K("Q") +
          " · Excluir seleção " + K(KEY_DEL)],
         [M("Exibir"), "Céu, decals, neblina e colisão (caixas) · Janela de partes do mapa · Janela Ferramentas do mapa · "
          "Colisão do piso (.hm) · Ocultar a seleção " + K("H") + " · Mostrar todos os objetos ocultos " + K("Shift", "H")],
         [M("Idioma"), "English · Español · Português"],
         [M("Configurações"), "Veja " + link("k_settings", "Configurações") + "."],
         [M("Ajuda"), "Manual do usuário (PDF) · Procurar versões novas agora · Sobre"]]),
      [0.18, 0.82])
    H2(t("El panel DEBUG", "The DEBUG panel", "O painel DEBUG"))
    T([t("Sección", "Section", "Seção"), t("Para qué sirve", "What it is for", "Para que serve")],
      [[t("<b>Lista de escenas</b>", "<b>Scene list</b>", "<b>Lista de cenas</b>"),
        t("Abrir otro mapa del juego (con buscador): elegilo y tocá <b>Cargar escena</b>.",
          "Open another map of the game (with search): pick it and click <b>Load Scene</b>.",
          "Abrir outro mapa do jogo (com busca): escolha-o e clique em <b>Carregar cena</b>.")],
       [t("<b>Lista de mapas</b>", "<b>Maps list</b>", "<b>Lista de mapas</b>"),
        t("Cambiarle a la escena el " + C(".opt") + " que usa (<b>Cargar mapa</b>).",
          "Change the " + C(".opt") + " the scene uses (<b>Load Map</b>).",
          "Trocar o " + C(".opt") + " que a cena usa (<b>Carregar mapa</b>).")],
       [t("<b>Copias de seguridad (.bak)</b>", "<b>Map file backups (.bak)</b>", "<b>Cópias de segurança (.bak)</b>"),
        t("Volver a una copia anterior de un mapa.", "Go back to an earlier copy of a map.",
          "Voltar a uma cópia anterior de um mapa.")],
       ["<b>Library: Torrente, el juego</b>",
        t("Importar modelos, mapas, escenas, texturas y música del juego viejo (",
          "Import models, maps, scenes, textures and music from the old game (",
          "Importar modelos, mapas, cenas, texturas e música do jogo antigo (") + chap_link("c_tj", 9) + ")."],
       [t("<b>Modo de juego / cielo / spawns / música</b>", "<b>Game mode / sky / spawns / music</b>",
          "<b>Modo de jogo / céu / spawns / música</b>"),
        t("El modo (DM, DMT, B, DO), los puntos de inicio, botiquines, banderas, el cielo, la música y las armas "
          "permitidas (", "The mode (DM, DMT, B, DO), start points, health packs, flags, sky, music and the weapons "
          "allowed (", "O modo (DM, DMT, B, DO), os pontos de início, kits médicos, bandeiras, o céu, a música e as "
          "armas permitidas (") + chap_link("c_modes", 7) + ")."],
       [t("<b>Luces</b> y <b>Decals</b>", "<b>Lights</b> and <b>Decals</b>", "<b>Luzes</b> e <b>Decals</b>"),
        t("Agregar, editar, ir a, duplicar y borrar, con candado y ojo.", "Add, edit, go to, duplicate and delete, with "
          "lock and eye.", "Adicionar, editar, ir para, duplicar e excluir, com cadeado e olho.")],
       [t("<b>Barcos gemelos</b>", "<b>Twin ships</b>", "<b>Navios gêmeos</b>"),
        t("Las herramientas del mapa de los barcos (capturar la bandera 16 contra 16).",
          "The tools of the ships map (capture the flag, 16 against 16).",
          "As ferramentas do mapa dos navios (capturar a bandeira, 16 contra 16).")],
       [t("<b>Clima: cielo / luna</b>", "<b>Weather: sky / moon</b>", "<b>Clima: céu / lua</b>"),
        t("El cielo (también desde un PNG), la luna y los presets de clima.",
          "The sky (also from a PNG), the moon and the weather presets.",
          "O céu (também a partir de um PNG), a lua e os presets de clima.")],
       [t("<b>Escena</b>", "<b>Scene</b>", "<b>Cena</b>"),
        t("Niebla, cámara y el árbol de <b>módulos</b>: agregar, editar, duplicar y borrar.",
          "Fog, camera and the <b>modules</b> tree: add, edit, duplicate and delete.",
          "Neblina, câmera e a árvore de <b>módulos</b>: adicionar, editar, duplicar e excluir.")],
       ["<b>Map Mesh</b>", t("Las mallas del mapa.", "The map's meshes.", "As malhas do mapa.")],
       [t("<b>Selección</b>", "<b>Selection</b>", "<b>Seleção</b>"),
        t("Lo que tocaste en la vista: posición, giro, escala, textura y botones propios.",
          "What you clicked in the view: position, rotation, scale, texture and its own buttons.",
          "O que você clicou na vista: posição, giro, escala, textura e botões próprios.")],
       [t("<b>Opciones de vista</b>", "<b>View options</b>", "<b>Opções de exibição</b>"),
        t("Culling, decals, niebla, transparencias, gamma, velocidad de la cámara, campo visual.",
          "Culling, decals, fog, transparency, gamma, camera speed, field of view.",
          "Culling, decals, neblina, transparências, gama, velocidade da câmera, campo de visão.")]],
      [0.3, 0.7])
    H2(t("Otras ventanas", "Other windows", "Outras janelas"))
    UL([t("<b>Texturas de la escena</b>: las miniaturas de las texturas de la escena. Desde acá podés <b>Exportar PNG</b> o "
          "<b>Reemplazar desde PNG</b>.",
          "<b>Scene Textures</b>: thumbnails of the scene's textures, with <b>Export PNG</b> and <b>Replace from PNG</b>.",
          "<b>Texturas da cena</b>: as miniaturas das texturas da cena. Daqui você pode <b>Exportar PNG</b> ou "
          "<b>Substituir a partir de PNG</b>."),
        t("<b>Modelos (.nfo)</b>: todos los modelos del juego, con filtro. Al tocar uno aparece delante de la cámara, y "
          "<b>Place as</b> lo agrega a la escena como módulo.",
          "<b>Models (.nfo)</b>: every model of the game, with a filter. Clicking one shows it in front of the camera, and "
          "<b>Place as</b> adds it to the scene as a module.",
          "<b>Modelos (.nfo)</b>: todos os modelos do jogo, com filtro. Ao clicar num, ele aparece na frente da câmera, e "
          "<b>Place as</b> o adiciona à cena como módulo."),
        t("<b>Partes del mapa</b> (" + M("Ver") + "): las mallas con sus triángulos y texturas, con <b>Ir a</b>, "
          "<b>Eliminar</b> y el reemplazo de textura de una malla o de todas.",
          "<b>Map parts</b> (" + M("View") + "): the meshes with their triangles and textures, with <b>Go to</b>, "
          "<b>Delete</b> and texture replacement for one mesh or all.",
          "<b>Partes do mapa</b> (" + M("Exibir") + "): as malhas com seus triângulos e texturas, com <b>Ir para</b>, "
          "<b>Excluir</b> e a troca de textura de uma malha ou de todas."),
        t("<b>Buscador de comandos</b> " + K("Ctrl", "P") + ": escribí parte del nombre de cualquier herramienta y apretá " +
          K("Enter") + " para abrirla o ejecutarla. Desde ahí también le asignás tus propios atajos.",
          "<b>Command search</b> " + K("Ctrl", "P") + ": type part of any tool's name and press " + K("Enter") +
          " to open or run it. There you can also give commands your own shortcuts.",
          "<b>Busca de comandos</b> " + K("Ctrl", "P") + ": digite parte do nome de qualquer ferramenta e aperte " +
          K("Enter") + " para abri-la ou executá-la. Ali você também define seus próprios atalhos.")])

    # ================================================================ 4
    H1(t("Moverse y seleccionar", "Moving around and selecting", "Mover-se e selecionar"), "c_move")
    H2(t("Los dos modos del mouse", "The two mouse modes", "Os dois modos do mouse"))
    T([t("Modo", "Mode", "Modo"), t("Cómo se usa", "How it works", "Como se usa")],
      [[t("<b>Edición</b> (normal)", "<b>Edit</b> (normal)", "<b>Edição</b> (normal)"),
        t("El puntero se ve. El clic izquierdo usa la herramienta activa y, <b>manteniendo el clic derecho</b>, mirás "
          "alrededor. " + K("W") + K("A") + K("S") + K("D") + " caminan en el plano y " + K("Shift") + " acelera. Al "
          "pasar el mouse sobre un objeto aparece su información.",
          "The pointer is visible. Left click uses the active tool, and <b>holding right click</b> looks around. " +
          K("W") + K("A") + K("S") + K("D") + " walk on the flat and " + K("Shift") + " goes faster. Hovering an object "
          "shows its information.",
          "O ponteiro aparece. O clique esquerdo usa a ferramenta ativa e, <b>segurando o clique direito</b>, você olha "
          "em volta. " + K("W") + K("A") + K("S") + K("D") + " andam no plano e " + K("Shift") + " acelera. Passando o "
          "mouse sobre um objeto aparece a informação dele.")],
       [t("<b>Vuelo libre</b>", "<b>Free flight</b>", "<b>Voo livre</b>"),
        t(K("Alt") + " captura el mouse: mirás con el mouse y volás hacia donde mirás. " + K(KEY_SPACE) + " o " + K("E") +
          " suben, y " + K("Ctrl") + " o " + K("C") + " bajan. " + K("Alt") + " o " + K("Esc") + " vuelven al modo edición.",
          K("Alt") + " captures the mouse: you look with the mouse and fly where you look. " + K(KEY_SPACE) + " or " +
          K("E") + " go up, " + K("Ctrl") + " or " + K("C") + " go down. " + K("Alt") + " or " + K("Esc") +
          " go back to edit mode.",
          K("Alt") + " captura o mouse: você olha com o mouse e voa para onde olha. " + K(KEY_SPACE) + " ou " + K("E") +
          " sobem, e " + K("Ctrl") + " ou " + K("C") + " descem. " + K("Alt") + " ou " + K("Esc") + " voltam ao modo edição.")]],
      [0.22, 0.78])
    H2(t("Las herramientas 1 a 9", "Tools 1 to 9", "As ferramentas 1 a 9"), "k_tools19")
    T([t("Tecla", "Key", "Tecla"), HT[0], HT[1]],
      [[K("1"), t("Seleccionar", "Select", "Selecionar"),
        t("Clic en un objeto: sus datos aparecen en " + M("DEBUG > Selección") + ". " + K("Ctrl") + " + clic arma un "
          "grupo, y " + K("Shift") + " + arrastrar selecciona con un rectángulo.",
          "Click an object: its data appears in " + M("DEBUG > Selection") + ". " + K("Ctrl") + " + click builds a group, "
          "and " + K("Shift") + " + drag selects with a rectangle.",
          "Clique num objeto: os dados dele aparecem em " + M("DEBUG > Seleção") + ". " + K("Ctrl") + " + clique monta um "
          "grupo, e " + K("Shift") + " + arrastar seleciona com um retângulo.")],
       [K("2"), t("Mover", "Move", "Mover"),
        t("Arrastrar sobre el piso, o con las manijas de colores X (rojo), Y (verde) y Z (azul).",
          "Drag over the floor, or with the coloured handles X (red), Y (green) and Z (blue).",
          "Arrastar sobre o chão, ou com as alças coloridas X (vermelho), Y (verde) e Z (azul).")],
       [K("3"), t("Rotar", "Rotate", "Girar"), t("Girar (eje Y) o inclinar (X / Z).", "Turn (Y axis) or tilt (X / Z).",
                                                 "Girar (eixo Y) ou inclinar (X / Z).")],
       [K("4"), t("Escalar", "Scale", "Escalar"), t("Cambiar el tamaño, también distinto en cada eje.",
                                                    "Resize, also differently on each axis.",
                                                    "Mudar o tamanho, também diferente em cada eixo.")],
       [K("5"), t("Pluma", "Pen", "Caneta"),
        t("Marcar un contorno en el piso para recortar el mapa o borrar lo que está dentro o fuera.",
          "Mark an outline on the floor to crop the map or delete what is inside or outside.",
          "Marcar um contorno no chão para recortar o mapa ou apagar o que está dentro ou fora.")],
       [K("6"), t("Relleno", "Fill", "Preencher"),
        t("Tapar un hueco con una malla plana, con la textura que elijas.",
          "Cover a hole with a flat mesh, with the texture you choose.",
          "Tapar um buraco com uma malha plana, com a textura que escolher.")],
       [K("7"), t("Medir", "Measure", "Medir"),
        t("Puntos A, B, C…: distancias, alturas y superficie. Las herramientas de “entre A y B” los usan.",
          "Points A, B, C…: distances, heights and area. The “between A and B” tools use them.",
          "Pontos A, B, C…: distâncias, alturas e área. As ferramentas “entre A e B” os usam.")],
       [K("8"), t("Colisión", "Collision", "Colisão"),
        t("Elegir y editar cajas de colisión y caras del piso.", "Pick and edit collision boxes and floor faces.",
          "Escolher e editar caixas de colisão e faces do chão.")],
       [K("9"), t("Pintar caras", "Paint faces", "Pintar faces"),
        t("Cambiar la textura de un triángulo, de una zona plana o de todo un material.",
          "Change the texture of a triangle, a flat area or a whole material.",
          "Trocar a textura de um triângulo, de uma área plana ou de um material inteiro.")]],
      [0.1, 0.18, 0.72])
    H2(t("Mover, girar, escalar y copiar", "Move, rotate, scale and copy", "Mover, girar, escalar e copiar"))
    UL([t("Con algo seleccionado: " + K("G") + " + mouse mueve (con la rueda sube y baja), " + K("R") + " + mouse gira "
          "(con la rueda hace el alabeo), " + K("T") + " + mouse escala, y " + K("Ctrl") + " + rueda gira de a 5° (con " +
          K("Shift") + ", de a 1°).",
          "With something selected: " + K("G") + " + mouse moves (the wheel raises and lowers), " + K("R") + " + mouse "
          "rotates (the wheel rolls), " + K("T") + " + mouse scales, and " + K("Ctrl") + " + wheel turns in 5° steps "
          "(with " + K("Shift") + ", 1°).",
          "Com algo selecionado: " + K("G") + " + mouse move (com a roda sobe e desce), " + K("R") + " + mouse gira (com "
          "a roda faz a rolagem), " + K("T") + " + mouse escala, e " + K("Ctrl") + " + roda gira de 5 em 5° (com " +
          K("Shift") + ", de 1 em 1°)."),
        t("El cambio se ve como una caja naranja y se aplica al soltar.",
          "The change shows as an orange box and applies when you let go.",
          "A mudança aparece como uma caixa laranja e é aplicada ao soltar."),
        t(K("Q") + " copia lo seleccionado (o el grupo entero). La copia sigue al mouse hasta que hagas clic, y " + K("Esc") +
          " cancela.",
          K("Q") + " copies the selection (or the whole group). The copy follows the mouse until you click, and " +
          K("Esc") + " cancels.",
          K("Q") + " copia a seleção (ou o grupo inteiro). A cópia segue o mouse até você clicar, e " + K("Esc") +
          " cancela."),
        t(K(KEY_DEL) + " borra. Al borrar una malla o un prop también se va su colisión.",
          K(KEY_DEL) + " deletes. Deleting a mesh or a prop also removes its collision.",
          K(KEY_DEL) + " apaga. Ao apagar uma malha ou um prop, a colisão dele também vai embora."),
        t("<b>La colisión acompaña</b> (activada por defecto): las cajas y caras de piso que están dentro de una malla o de "
          "un prop se mueven, giran, escalan, copian y borran con él.",
          "<b>Collision goes with the object</b> (on by default): boxes and floor faces inside a mesh or a prop move, "
          "rotate, scale, copy and delete with it.",
          "<b>A colisão acompanha</b> (ligada por padrão): as caixas e faces de chão dentro de uma malha ou de um prop se "
          "movem, giram, escalam, copiam e apagam com ele."),
        t("En los campos de posición, giro y escala podés escribir el valor exacto (" + K("Ctrl") + " + clic en el campo).",
          "In the position, rotation and scale fields you can type the exact value (" + K("Ctrl") + " + click the field).",
          "Nos campos de posição, giro e escala você pode digitar o valor exato (" + K("Ctrl") + " + clique no campo).")])
    H2(t("Ocultar, bloquear y deshacer", "Hide, lock and undo", "Ocultar, bloquear e desfazer"))
    UL([t(K("H") + " oculta lo seleccionado solo en el editor (en el juego sigue estando) y " + K("Shift", "H") +
          " muestra todo otra vez.",
          K("H") + " hides the selection in the editor only (it is still in the game), and " + K("Shift", "H") +
          " shows everything again.",
          K("H") + " oculta a seleção só no editor (no jogo continua lá) e " + K("Shift", "H") + " mostra tudo de novo."),
        t("<b>Candado</b>: un objeto bloqueado no se selecciona ni lo mueven las herramientas. Es útil para el piso o las "
          "paredes grandes.",
          "<b>Lock</b>: a locked object cannot be selected and tools do not move it. Handy for the floor or big walls.",
          "<b>Cadeado</b>: um objeto bloqueado não é selecionado nem movido pelas ferramentas. Útil para o chão ou "
          "paredes grandes."),
        t(K("Ctrl", "Z") + " deshace y " + K("Ctrl", "Y") + " rehace (hasta 30 pasos): escena, mapa, luces, decals y colisión.",
          K("Ctrl", "Z") + " undoes and " + K("Ctrl", "Y") + " redoes (up to 30 steps): scene, map, lights, decals and collision.",
          K("Ctrl", "Z") + " desfaz e " + K("Ctrl", "Y") + " refaz (até 30 passos): cena, mapa, luzes, decals e colisão."),
        t("<b>Ir a</b> lleva la cámara hasta un objeto, y <b>Mover aquí</b> trae el objeto donde está la cámara.",
          "<b>Go to</b> takes the camera to an object, and <b>Move here</b> brings the object to the camera.",
          "<b>Ir para</b> leva a câmera até um objeto, e <b>Mover para cá</b> traz o objeto até a câmera.")])

    # ================================================================ 5
    H1(t("Editar lo que hay en el mapa", "Editing what is in the map", "Editar o que há no mapa"), "c_edit")
    H2(t("Módulos", "Modules", "Módulos"))
    P(t("Los módulos son los objetos “vivos” de la escena. Cada uno tiene un tipo y sus propios campos, que se editan en " +
        M("DEBUG > Escena > Modules") + " o, después de tocarlo en la vista, en " + M("Selección") + ".",
        "Modules are the “live” objects of the scene. Each has a type and its own fields, edited in " +
        M("DEBUG > Scene > Modules") + " or, after clicking it in the view, in " + M("Selection") + ".",
        "Os módulos são os objetos “vivos” da cena. Cada um tem um tipo e seus próprios campos, editados em " +
        M("DEBUG > Cena > Modules") + " ou, depois de clicar nele na vista, em " + M("Seleção") + "."))
    T([t("Módulo", "Module", "Módulo"), t("Qué es", "What it is", "O que é")],
      [[C("mp_CStartPoint"), t("Punto de inicio de un jugador. <b>Equipo 0</b> (amarillo) o <b>1</b> (rojo), y su orden.",
                               "A player start point. <b>Team 0</b> (yellow) or <b>1</b> (red), and its order.",
                               "Ponto de início de um jogador. <b>Time 0</b> (amarelo) ou <b>1</b> (vermelho), e sua ordem.")],
       [C("mp_salud"), t("Botiquín: ", "Health pack: ", "Kit médico: ") + C("ITEM_Medikit") + " (50) " +
        t("o", "or", "ou") + " " + C("ITEM_MiniMedikit") + " (25)."],
       [C("mp_Flag"), t("Bandera (capturar la bandera): equipo 0 amarilla, equipo 1 roja.",
                        "Flag (capture the flag): team 0 yellow, team 1 red.",
                        "Bandeira (capturar a bandeira): time 0 amarela, time 1 vermelha.")],
       [C("mp_BombZone"), t("Zona de bomba (destruir el objetivo). ", "Bomb zone (destroy the target). ",
                            "Zona de bomba (destruir o alvo). ") + C("bombZone") + t(" es el sitio A y ", " is site A and ",
                            " é o local A e ") + C("bombZone_B") + t(" el sitio B.", " site B.", " o local B.")],
       [C("mp_Bomba"), t("La bomba que se levanta y se planta.", "The bomb you pick up and plant.",
                         "A bomba que se pega e se planta.")],
       [C("mp_CameraStartPosition"), t("La cámara de la intro del mapa. Tiene que haber una.",
                                       "The map's intro camera. There must be one.",
                                       "A câmera da introdução do mapa. Tem que haver uma.")],
       [C("mp_CCar") + ", " + C("mp_Door"), t("Autos y puertas. Un auto se puede hacer <b>indestructible</b> (queda como "
                                              "decorado, con su colisión).",
                                              "Cars and doors. A car can be made <b>indestructible</b> (it becomes scenery, "
                                              "with its collision).",
                                              "Carros e portas. Um carro pode ficar <b>indestrutível</b> (vira cenário, "
                                              "com sua colisão).")],
       [C("RenderNFO") + ", " + C("AnimatedRenderNFO"), t("Modelos de decorado, quietos o animados (con su ",
                                                          "Scenery models, still or animated (with their ",
                                                          "Modelos de cenário, parados ou animados (com seu ") + C(".key") + ")."],
       [C("mp_SoundSource") + ", " + C("CParticleSystem"),
        t("Sonidos con su alcance, y emisores de partículas (humo, fuego, fuentes).",
          "Sounds with their reach, and particle emitters (smoke, fire, fountains).",
          "Sons com seu alcance, e emissores de partículas (fumaça, fogo, fontes).")]],
      [0.3, 0.7])
    UL([t("<b>Add new module</b> agrega uno donde está la cámara. Los nombres se numeran solos, porque dos módulos con el "
          "mismo nombre cierran el juego.",
          "<b>Add new module</b> adds one where the camera is. Names are numbered automatically, because two modules with "
          "the same name crash the game.",
          "<b>Add new module</b> adiciona um onde está a câmera. Os nomes são numerados sozinhos, porque dois módulos com "
          "o mesmo nome fecham o jogo."),
        t("<b>Choose model…</b> abre la lista de modelos. Al pasar el mouse por un nombre, ese modelo aparece delante de la cámara.",
          "<b>Choose model…</b> opens the model list. Hovering a name shows that model in front of the camera.",
          "<b>Choose model…</b> abre a lista de modelos. Passando o mouse por um nome, o modelo aparece na frente da câmera."),
        t("<b>Duplicar</b>, <b>Eliminar</b>, <b>Ir a</b> y <b>Mover aquí</b> están en el panel de cada módulo.",
          "<b>Duplicate</b>, <b>Delete</b>, <b>Go to</b> and <b>Move here</b> are in each module's panel.",
          "<b>Duplicar</b>, <b>Excluir</b>, <b>Ir para</b> e <b>Mover para cá</b> estão no painel de cada módulo."),
        t("En un punto de inicio, <b>Al piso</b> lo apoya sobre la colisión que tiene debajo.",
          "On a start point, <b>To the floor</b> sets it on the collision below it.",
          "Num ponto de início, <b>Ao chão</b> o apoia sobre a colisão que tem embaixo.")])
    H2(t("Mallas, props y decals", "Meshes, props and decals", "Malhas, props e decals"))
    UL([t("<b>Mallas</b>: la geometría del mapa. Se mueven, giran y escalan (también distinto en cada eje).",
          "<b>Meshes</b>: the map's geometry. They move, rotate and scale (also differently on each axis).",
          "<b>Malhas</b>: a geometria do mapa. Movem, giram e escalam (também diferente em cada eixo)."),
        t("<b>Props</b>: copias de una malla puestas en varios lugares. Una malla que es molde de props se edita desde sus props.",
          "<b>Props</b>: copies of one mesh placed in several spots. A mesh that is the mould of props is edited through its props.",
          "<b>Props</b>: cópias de uma malha em vários lugares. Uma malha que é molde de props é editada pelos props."),
        t("<b>Decals</b>: calcomanías (manchas, carteles). Se agregan, mueven, duplican y borran en " + M("DEBUG > Decals") + ".",
          "<b>Decals</b>: stickers (stains, signs). Add, move, duplicate and delete them in " + M("DEBUG > Decals") + ".",
          "<b>Decals</b>: adesivos (manchas, placas). São adicionados, movidos, duplicados e apagados em " +
          M("DEBUG > Decals") + ".")])
    H2(t("Luces", "Lights", "Luzes"))
    P(t("El juego ilumina en tiempo real con las luces del mapa: una <b>ambiental</b> (el color de todo), hasta tres "
        "<b>soles</b> (luz direccional) y <b>luces puntuales</b> con distancia de inicio y fin.",
        "The game lights the map in real time with its lights: one <b>ambient</b> (the colour of everything), up to three "
        "<b>suns</b> (directional light) and <b>point lights</b> with a start and end distance.",
        "O jogo ilumina em tempo real com as luzes do mapa: uma <b>ambiente</b> (a cor de tudo), até três <b>sóis</b> "
        "(luz direcional) e <b>luzes pontuais</b> com distância de início e fim."))
    UL([t("Se editan en " + M("DEBUG > Luces") + ". Para ver cómo quedan: " +
          M("Herramientas del mapa > Aspecto > Luces (vista iluminada)") + ".",
          "Edit them in " + M("DEBUG > Lights") + ". To see how they look: " + M("Map tools > Look > Lights (lit view)") + ".",
          "São editadas em " + M("DEBUG > Luzes") + ". Para ver como ficam: " +
          M("Ferramentas do mapa > Aparência > Luzes (vista iluminada)") + "."),
        t("En un sol solo cuenta la dirección, y en la ambiental solo el color: su marca en la vista se puede poner donde sea.",
          "For a sun only the direction counts, and for the ambient only the colour: their marker in the view can go anywhere.",
          "Num sol só conta a direção, e na ambiente só a cor: a marca delas na vista pode ficar em qualquer lugar."),
        t("<b>La luz de CS</b>: los mapas hechos desde Counter-Strike pueden llevar la luz original de CS, con su sol y sus "
          "sombras (" + link("k_cslight", "sección 8.4") + ").",
          "<b>The CS light</b>: maps made from Counter-Strike can carry the original CS light, with its sun and shadows (" +
          link("k_cslight", "section 8.4") + ").",
          "<b>A luz do CS</b>: os mapas feitos a partir do Counter-Strike podem levar a luz original do CS, com seu sol e "
          "suas sombras (" + link("k_cslight", "seção 8.4") + ").")])
    H2(t("Texturas", "Textures", "Texturas"))
    UL([t("<b>Exportar / reemplazar</b> una textura con un PNG, en la ventana <b>Texturas de la escena</b>.",
          "<b>Export / replace</b> a texture with a PNG, in the <b>Scene Textures</b> window.",
          "<b>Exportar / substituir</b> uma textura com um PNG, na janela <b>Texturas da cena</b>."),
        t("<b>Cambiar la textura</b> de un material desde " + M("Selección") + ", o en " + M("Partes del mapa") +
          " para una malla o para todas.",
          "<b>Change the texture</b> of a material from " + M("Selection") + ", or in " + M("Map parts") +
          " for one mesh or all.",
          "<b>Trocar a textura</b> de um material em " + M("Seleção") + ", ou em " + M("Partes do mapa") +
          " para uma malha ou para todas."),
        t("<b>Pintar caras</b> (herramienta 9): cambia la textura de un triángulo, de una zona plana o de todo un material. "
          "Con " + K("Shift") + " + clic tomás la textura de una cara.",
          "<b>Paint faces</b> (tool 9): changes the texture of a triangle, a flat area or a whole material. " + K("Shift") +
          " + click picks the texture of a face.",
          "<b>Pintar faces</b> (ferramenta 9): troca a textura de um triângulo, de uma área plana ou de um material "
          "inteiro. Com " + K("Shift") + " + clique você pega a textura de uma face."),
        t("<b>Texturas: buscar / reemplazar</b> (" + M("Aspecto") + "): la lista de texturas del mapa y el reemplazo en todo el mapa.",
          "<b>Textures: search / replace</b> (" + M("Look") + "): the map's texture list and replacing across the whole map.",
          "<b>Texturas: procurar / substituir</b> (" + M("Aparência") + "): a lista de texturas do mapa e a troca no mapa inteiro."),
        t("Una textura nueva se guarda con el nombre del mapa delante, así no cambia en otros mapas.",
          "A new texture is saved with the map's name in front, so other maps do not change.",
          "Uma textura nova é salva com o nome do mapa na frente, assim não muda em outros mapas.")])
    H2(t("Cielo, niebla, música y clima", "Sky, fog, music and weather", "Céu, neblina, música e clima"))
    UL([t("<b>Cielo</b>: cualquier cielo del juego o uno propio desde un PNG. Debajo se ve la lista de escenas que lo usan.",
          "<b>Sky</b>: any sky of the game or your own from a PNG. Below it is the list of scenes that use it.",
          "<b>Céu</b>: qualquer céu do jogo ou um próprio a partir de um PNG. Embaixo aparece a lista de cenas que o usam."),
        t("<b>Niebla</b>: cercana, lejana y color, en " + M("DEBUG > Escena") + ".",
          "<b>Fog</b>: near, far and colour, in " + M("DEBUG > Scene") + ".",
          "<b>Neblina</b>: perto, longe e cor, em " + M("DEBUG > Cena") + "."),
        t("<b>Presets de clima</b>: Día, Atardecer, Noche, Tormenta y Niebla. Cambian el cielo, la niebla y las luces.",
          "<b>Weather presets</b>: Day, Sunset, Night, Storm and Fog. They change the sky, the fog and the lights.",
          "<b>Presets de clima</b>: Dia, Entardecer, Noite, Tempestade e Neblina. Mudam o céu, a neblina e as luzes."),
        t("<b>Lluvia y tormenta</b> (" + M("Jugabilidad > Clima: lluvia / tormenta") + "): lluvia como la de Marbella, con "
          "truenos o calma, y salpicaduras en el piso. Usa una copia de la DLL del modo para ese mapa.",
          "<b>Rain and storm</b> (" + M("Gameplay > Weather: rain / storm") + "): rain like Marbella's, with thunder or "
          "calm, and splashes on the floor. It uses a copy of the mode DLL for that map.",
          "<b>Chuva e tempestade</b> (" + M("Jogabilidade > Clima: chuva / tempestade") + "): chuva como a de Marbella, "
          "com trovões ou calma, e respingos no chão. Usa uma cópia da DLL do modo para esse mapa."),
        t("<b>Música</b>: el campo " + C("ambient_music") + ". El archivo va en la carpeta " + C("musica") + " del juego.",
          "<b>Music</b>: the " + C("ambient_music") + " field. The file goes in the game's " + C("musica") + " folder.",
          "<b>Música</b>: o campo " + C("ambient_music") + ". O arquivo vai na pasta " + C("musica") + " do jogo.")])

    # ================================================================ 6
    H1(t("Las herramientas del mapa", "The map tools", "As ferramentas do mapa"), "c_tools")
    P(t("La ventana " + M("Herramientas del mapa") + " (" + M("Ver > Ventana Herramientas del mapa") + ") reúne todo. "
        "Arriba hay una fila de botones por categoría, y cada herramienta se abre con un clic en su título. Si no sabés "
        "dónde está algo, " + K("Ctrl", "P") + " lo busca por nombre.",
        "The " + M("Map tools") + " window (" + M("View > Map tools window") + ") has everything. At the top there is a "
        "row of category buttons, and each tool opens with a click on its title. If you do not know where something is, " +
        K("Ctrl", "P") + " finds it by name.",
        "A janela " + M("Ferramentas do mapa") + " (" + M("Exibir > Janela Ferramentas do mapa") + ") reúne tudo. Em cima "
        "há uma fileira de botões por categoria, e cada ferramenta abre com um clique no título. Se não souber onde está "
        "algo, " + K("Ctrl", "P") + " procura pelo nome."))
    FIG(fig_categories(W), 3, t("Las seis categorías de herramientas.", "The six tool categories.",
                                "As seis categorias de ferramentas."))
    H2(t("Construir", "Build", "Construir"), "k_build")
    T(list(HT),
      [[t("<b>Crear desde .bsp / .rmf</b>", "<b>Create from .bsp / .rmf</b>", "<b>Criar a partir de .bsp / .rmf</b>"),
        t("Un mapa nuevo entero a partir de un mapa de CS 1.6 (", "A whole new map from a CS 1.6 map (",
          "Um mapa novo inteiro a partir de um mapa do CS 1.6 (") + chap_link("c_cs", 8) + ")."],
       [t("<b>Mapa nuevo desde cero</b>", "<b>New map from zero</b>", "<b>Mapa novo do zero</b>"),
        t("Suelo y paredes con colisión, puntos de inicio, botiquines y lo del modo (",
          "Floor and walls with collision, start points, health packs and what the mode needs (",
          "Chão e paredes com colisão, pontos de início, kits médicos e o que o modo precisa (") +
        link("c_zero", "7.5") + ")."],
       [t("<b>Formas</b>", "<b>Shapes</b>", "<b>Formas</b>"),
        t("Caja, cilindro, cono, rampa, escalera, pirámide, pared, disco, o una forma dibujada por puntos. Se ven en vista "
          "previa amarilla antes de crearlas y pueden llevar colisión.",
          "Box, cylinder, cone, ramp, stairs, pyramid, wall, disc, or a shape drawn by points. A yellow preview shows them "
          "before you create them, and they can have collision.",
          "Caixa, cilindro, cone, rampa, escada, pirâmide, parede, disco, ou uma forma desenhada por pontos. Aparecem em "
          "pré-visualização amarela antes de criar e podem ter colisão.")],
       [t("<b>Importar un mapa de CS 1.6</b>", "<b>Import a Counter-Strike 1.6 map</b>", "<b>Importar um mapa de CS 1.6</b>"),
        t("Pone un " + C(".bsp") + " o " + C(".rmf") + " dentro del mapa abierto, en el lugar, la escala y el giro que "
          "elijas. Con <b>vaciar el lugar antes</b>, saca lo que había ahí.",
          "Puts a " + C(".bsp") + " or " + C(".rmf") + " inside the open map, at the place, scale and rotation you choose. "
          "With <b>empty the place first</b>, it removes what was there.",
          "Coloca um " + C(".bsp") + " ou " + C(".rmf") + " dentro do mapa aberto, no lugar, escala e giro que escolher. "
          "Com <b>esvaziar o lugar antes</b>, tira o que havia ali.")],
       [t("<b>Crear sólido (con colisión)</b>", "<b>Create solid (with collision)</b>", "<b>Criar sólido (com colisão)</b>"),
        t("Tabla, bloque, pared, rampa, pasamanos o baranda de barco. Se crea en un punto o entre los puntos A y B de Medir.",
          "Plank, block, wall, ramp, handrail or ship railing, at a point or between Measure's points A and B.",
          "Tábua, bloco, parede, rampa, corrimão ou grade de navio. É criado num ponto ou entre os pontos A e B de Medir.")],
       [t("<b>Recorrido de varios puntos</b>", "<b>Path of several points</b>", "<b>Caminho de vários pontos</b>"),
        t("Puntos A, B, C… para poner barandas, paredes o filas de copias a lo largo. También sirve para hacer solo "
          "colisión invisible.",
          "Points A, B, C… to put railings, walls or rows of copies along them. It can also make invisible collision only.",
          "Pontos A, B, C… para pôr grades, paredes ou fileiras de cópias ao longo. Também serve para fazer só colisão invisível.")],
       [t("<b>Medir</b>", "<b>Measure</b>", "<b>Medir</b>"),
        t("Distancias, alturas, total y superficie entre los puntos que marques.",
          "Distances, heights, total and area between the points you mark.",
          "Distâncias, alturas, total e área entre os pontos que marcar.")],
       [t("<b>Grupo / ajuste / copias</b>", "<b>Group / snap / copies</b>", "<b>Grupo / ajuste / cópias</b>"),
        t("Mover, bloquear o borrar un grupo; grilla; apoyar en el piso; copia espejada (con cambio de equipo) y filas de copias.",
          "Move, lock or delete a group; grid; stand on the floor; mirror copy (switching team) and rows of copies.",
          "Mover, bloquear ou apagar um grupo; grade; apoiar no chão; cópia espelhada (trocando de time) e fileiras de cópias.")],
       [t("<b>Bajar al piso / alinear / repartir</b>", "<b>Drop to the floor / align / distribute</b>",
          "<b>Baixar ao chão / alinhar / distribuir</b>"),
        t("Apoya, alinea en X / Y / Z o reparte a la misma distancia.", "Drops, aligns on X / Y / Z or spaces evenly.",
          "Apoia, alinha em X / Y / Z ou distribui à mesma distância.")],
       [t("<b>Pincel de objetos</b>", "<b>Object brush</b>", "<b>Pincel de objetos</b>"),
        t("Desparrama copias al azar (árboles, arbustos, piedras) con cada clic.",
          "Scatters random copies (trees, bushes, rocks) with each click.",
          "Espalha cópias ao acaso (árvores, arbustos, pedras) a cada clique.")],
       [t("<b>Importar modelo (OBJ)</b>", "<b>Import model (OBJ)</b>", "<b>Importar modelo (OBJ)</b>"),
        t("Trae un " + C(".obj") + " con sus texturas, y exporta a OBJ para Blender.",
          "Brings in an " + C(".obj") + " with its textures, and exports to OBJ for Blender.",
          "Traz um " + C(".obj") + " com suas texturas, e exporta para OBJ para o Blender.")],
       [t("<b>Piezas de otros mapas</b> / <b>Piezas</b>", "<b>Pieces of other maps</b> / <b>Pieces</b>",
          "<b>Peças de outros mapas</b> / <b>Peças</b>"),
        t("Copiar mallas de otro mapa, y guardar grupos para usarlos en cualquier mapa.",
          "Copy meshes from another map, and save groups to use in any map.",
          "Copiar malhas de outro mapa, e salvar grupos para usar em qualquer mapa.")]],
      [0.31, 0.69])
    H2(t("Colisión", "Collision", "Colisão"), "k_coll")
    T(list(HT),
      [[t("<b>Editar colisión</b> (herramienta 8)", "<b>Collision editing</b> (tool 8)", "<b>Editar colisão</b> (ferramenta 8)"),
        t("Mover, cambiar de tamaño o borrar cajas; agregar una caja o una caja alrededor de lo seleccionado; piso nuevo; "
          "pared invisible y rampa entre A y B.",
          "Move, resize or delete boxes; add a box or a box around the selection; new floor; invisible wall and ramp "
          "between A and B.",
          "Mover, redimensionar ou apagar caixas; adicionar uma caixa ou uma caixa em volta da seleção; chão novo; parede "
          "invisível e rampa entre A e B.")],
       [t("<b>Colisión desde las mallas (.hm)</b>", "<b>Collision from meshes (.hm)</b>", "<b>Colisão a partir das malhas (.hm)</b>"),
        t("Hace el piso, las rampas y las paredes a partir de lo que se ve, para lo seleccionado o para todo el mapa.",
          "Makes the floor, ramps and walls from what you see, for the selection or the whole map.",
          "Faz o chão, as rampas e as paredes a partir do que se vê, para a seleção ou o mapa inteiro.")],
       [t("<b>Limpiar colisión</b>", "<b>Collision clean-up</b>", "<b>Limpar colisão</b>"),
        t("Busca cajas duplicadas, metidas dentro de otra o solas, y las borra.",
          "Finds duplicate boxes, boxes inside another and lonely ones, and deletes them.",
          "Procura caixas duplicadas, dentro de outra ou sozinhas, e as apaga.")],
       [t("<b>Huecos en el piso y objetos enterrados</b>", "<b>Floor gaps and buried objects</b>",
          "<b>Buracos no chão e objetos enterrados</b>"),
        t("Rendijas donde se traba un pie o se cae un jugador, y objetos que quedaron bajo el piso.",
          "Slits where a foot gets stuck or a player falls, and objects left under the floor.",
          "Frestas onde um pé fica preso ou um jogador cai, e objetos que ficaram embaixo do chão.")]],
      [0.31, 0.69])
    BOX("tip", t("Con " + M("Ver > Colisión de piso (.hm)") + " ves el piso del juego: <b>verde</b> = piso, <b>amarillo</b> "
                 "= rampa, <b>rojo</b> = pared. Así se encuentran rápido los agujeros y las paredes invisibles.",
                 "With " + M("View > Floor collision (.hm)") + " you see the game's floor: <b>green</b> = floor, "
                 "<b>yellow</b> = ramp, <b>red</b> = wall. It makes holes and invisible walls easy to find.",
                 "Com " + M("Exibir > Colisão do piso (.hm)") + " você vê o chão do jogo: <b>verde</b> = chão, "
                 "<b>amarelo</b> = rampa, <b>vermelho</b> = parede. Assim se acham rápido os buracos e as paredes invisíveis."))
    H2(t("Aspecto", "Look", "Aparência"), "k_look")
    T(list(HT),
      [[t("<b>Pintar caras</b>", "<b>Paint faces</b>", "<b>Pintar faces</b>"),
        t("Cambia la textura por cara (herramienta 9).", "Changes the texture per face (tool 9).",
          "Troca a textura por face (ferramenta 9).")],
       [t("<b>Texturas: buscar / reemplazar</b>", "<b>Textures: search / replace</b>", "<b>Texturas: procurar / substituir</b>"),
        t("Lista y reemplazo de texturas, y las herramientas de los mapas de CS: luz de CS, caras que faltan, parpadeos, "
          "rejas y barandas, materiales negros, mallas demasiado grandes.",
          "Texture list and replacement, and the tools for CS maps: CS light, missing faces, blinking, bars and railings, "
          "black materials, meshes too big.",
          "Lista e troca de texturas, e as ferramentas dos mapas de CS: luz do CS, faces que faltam, piscadas, grades e "
          "corrimãos, materiais pretos, malhas grandes demais.")],
       [t("<b>Capa de sombreado</b>", "<b>Shading layer</b>", "<b>Camada de sombreamento</b>"),
        t("Un sombreado como el de ", "Shading like ", "Um sombreamento como o de ") + C("mp_b_garaje") + "."],
       [t("<b>Luces (vista iluminada)</b>", "<b>Lights (lit view)</b>", "<b>Luzes (vista iluminada)</b>"),
        t("Ver el mapa con sus luces y el alcance de cada una, y agregar luces.",
          "See the map with its lights and each one's reach, and add lights.",
          "Ver o mapa com suas luzes e o alcance de cada uma, e adicionar luzes.")],
       [t("<b>Clima: cielo / luna</b>", "<b>Weather: sky / moon</b>", "<b>Clima: céu / lua</b>"),
        t("Cielo, luna y presets.", "Sky, moon and presets.", "Céu, lua e presets.")],
       [t("<b>Sonidos y partículas</b>", "<b>Sounds and particles</b>", "<b>Sons e partículas</b>"),
        t("Alcance de los sonidos, vista previa y presets de partículas.", "Sound reach, particle preview and presets.",
          "Alcance dos sons, pré-visualização e presets de partículas.")],
       [t("<b>Animaciones (.key)</b>", "<b>Animations (.key)</b>", "<b>Animações (.key)</b>"),
        t("Hacer una animación más rápida o más lenta, o cambiar su recorrido (siempre en un archivo nuevo).",
          "Make an animation faster or slower, or change its route (always in a new file).",
          "Deixar uma animação mais rápida ou mais lenta, ou mudar seu trajeto (sempre num arquivo novo).")]],
      [0.31, 0.69])
    H2(t("Jugabilidad", "Gameplay", "Jogabilidade"), "k_play")
    T(list(HT),
      [[t("<b>Armado del modo de juego</b>", "<b>Game mode layout</b>", "<b>Montagem do modo de jogo</b>"),
        t("Marcás Base A y Base B, y pone los puntos de inicio, las banderas, el objetivo y los botiquines de forma pareja.",
          "Mark Base A and Base B, and it places start points, flags, the target and health packs fairly.",
          "Marque Base A e Base B, e ele põe os pontos de início, as bandeiras, o alvo e os kits médicos de forma justa.")],
       [t("<b>Destruir el objetivo</b>", "<b>Destroy the target</b>", "<b>Destruir o alvo</b>"),
        t("Sitios de bomba A y B, la bomba, el tiempo y la DLL que cuenta las dos zonas (",
          "Bomb sites A and B, the bomb, its time and the DLL that counts both zones (",
          "Locais de bomba A e B, a bomba, o tempo e a DLL que conta as duas zonas (") + link("k_do", "7.3") + ")."],
       [t("<b>Clima: lluvia / tormenta</b>", "<b>Weather: rain / storm</b>", "<b>Clima: chuva / tempestade</b>"),
        t("Lluvia, tormenta y salpicaduras para este mapa.", "Rain, storm and splashes for this map.",
          "Chuva, tempestade e respingos para este mapa.")],
       [t("<b>Revisión de puntos de aparición</b>", "<b>Start point check</b>", "<b>Verificação dos pontos de início</b>"),
        t("Puntos dentro de una pared, en el aire o a la vista del otro equipo, y <b>Repartirlos por todo el piso</b>.",
          "Points inside a wall, in the air or in sight of the other team, and <b>Spread them over the whole floor</b>.",
          "Pontos dentro de uma parede, no ar ou à vista do outro time, e <b>Espalhá-los por todo o chão</b>.")],
       [t("<b>Buscador de caídas y trampas</b>", "<b>Fall / trap finder</b>", "<b>Buscador de quedas e armadilhas</b>"),
        t("Bordes por donde te caés del mapa (rojo), y lugares de los que no se sale (naranja). "
          "<b>Cerrar las trampas</b> pone una pared invisible en el borde por donde se cae a esos lugares.",
          "Edges where you fall off the map (red), and places you cannot walk out of (orange). "
          "<b>Close the traps</b> puts an invisible wall on the edge where one falls into them.",
          "Bordas por onde se cai do mapa (vermelho), e lugares de onde não se sai (laranja). "
          "<b>Fechar as armadilhas</b> põe uma parede invisível na borda por onde se cai neles.")],
       [t("<b>Simulación de partida</b>", "<b>Match simulation</b>", "<b>Simulação de partida</b>"),
        t("Cada jugador corre por el camino más corto; muestra dónde y cuándo se cruzan.",
          "Each player runs the shortest way; it shows where and when they meet.",
          "Cada jogador corre pelo caminho mais curto; mostra onde e quando se cruzam.")],
       [t("<b>Prueba de recorrido</b>", "<b>Walk test</b>", "<b>Teste de caminhada</b>"),
        t("Caminás vos con la colisión real: ", "You walk with the real collision: ", "Você anda com a colisão real: ") +
        K("W") + K("A") + K("S") + K("D") + ", " + K(KEY_SPACE) + t(" salta, ", " jumps, ", " pula, ") + K("Esc") +
        t(" termina.", " ends.", " termina.")],
       [t("<b>Balance de equipos</b>", "<b>Team balance</b>", "<b>Equilíbrio dos times</b>"),
        t("Distancias y tiempos de cada equipo a los objetivos, con su veredicto.",
          "Each team's distances and times to the objectives, with a verdict.",
          "Distâncias e tempos de cada time até os objetivos, com o veredito.")]],
      [0.31, 0.69])
    H2(t("Revisar", "Check", "Verificar"), "k_check")
    T(list(HT),
      [[t("<b>Revisar mapa</b>", "<b>Map check</b>", "<b>Verificar mapa</b>"),
        t("Errores (rojo) y avisos (amarillo) con <b>Ir a</b>: puntos sin piso, nombres repetidos, falta la cámara, "
          "archivos que faltan, materiales negros, luces… Se corre sola en cada guardado.",
          "Errors (red) and warnings (yellow) with <b>Go to</b>: points with no floor, repeated names, missing camera, "
          "missing files, black materials, lights… It runs by itself on every save.",
          "Erros (vermelho) e avisos (amarelo) com <b>Ir para</b>: pontos sem chão, nomes repetidos, falta a câmera, "
          "arquivos que faltam, materiais pretos, luzes… Roda sozinha a cada salvamento.")],
       [t("<b>Mapa de carga</b>", "<b>Load map</b>", "<b>Mapa de carga</b>"),
        t("Dónde el mapa tiene más triángulos, de verde a rojo.", "Where the map has the most triangles, green to red.",
          "Onde o mapa tem mais triângulos, de verde a vermelho.")],
       [t("<b>Sectores</b>", "<b>Sectors</b>", "<b>Setores</b>"),
        t("Rehacer los sectores si algo movido desaparece desde ciertos lugares.",
          "Rebuild the sectors if something moved disappears from some places.",
          "Refazer os setores se algo movido some de certos lugares.")],
       [t("<b>Cambios desde una versión guardada</b>", "<b>Changes since a saved version</b>",
          "<b>Mudanças desde uma versão salva</b>"),
        t("Lo nuevo (verde), lo sacado (rojo) y lo movido (amarillo).", "New (green), removed (red) and moved (yellow).",
          "O novo (verde), o retirado (vermelho) e o movido (amarelo).")],
       [t("<b>Plano del mapa</b>", "<b>Map plan</b>", "<b>Planta do mapa</b>"),
        t("Vista desde arriba, con los puntos de inicio, las banderas y los botiquines.",
          "Top view, with start points, flags and health packs.",
          "Vista de cima, com os pontos de início, as bandeiras e os kits médicos.")]],
      [0.31, 0.69])
    H2(t("Juego y archivos", "Game & files", "Jogo e arquivos"), "k_files2")
    T(list(HT),
      [[t("<b>Probar en el juego</b>", "<b>Play in the game</b>", "<b>Testar no jogo</b>"),
        t("Elegís el " + C(".exe") + " del juego una vez. Después, un botón guarda, rehace el " + C("demo.vpk") +
          " y abre el juego.",
          "Pick the game's " + C(".exe") + " once. Then one button saves, rebuilds " + C("demo.vpk") + " and starts the game.",
          "Escolha o " + C(".exe") + " do jogo uma vez. Depois, um botão salva, refaz o " + C("demo.vpk") + " e abre o jogo.")],
       [t("<b>Instalar / compartir mapas</b>", "<b>Install / share maps</b>", "<b>Instalar / compartilhar mapas</b>"),
        t("Exportar en " + C(".zip") + ", instalar un " + C(".zip") + " y desinstalar.",
          "Export as " + C(".zip") + ", install a " + C(".zip") + " and uninstall.",
          "Exportar em " + C(".zip") + ", instalar um " + C(".zip") + " e desinstalar.")],
       [t("<b>Historial</b>", "<b>History</b>", "<b>Histórico</b>"),
        t("Los últimos 10 guardados: <b>Restaurar</b> y <b>Comparar</b>.", "The last 10 saves: <b>Restore</b> and <b>Compare</b>.",
          "Os últimos 10 salvamentos: <b>Restaurar</b> e <b>Comparar</b>.")],
       [t("<b>Atajos y buscador de comandos</b>", "<b>Shortcuts and command search</b>", "<b>Atalhos e busca de comandos</b>"),
        t("Tus propias teclas para cualquier comando.", "Your own keys for any command.",
          "Suas próprias teclas para qualquer comando.")]],
      [0.31, 0.69])

    # ================================================================ 7
    H1(t("Modos de juego", "Game modes", "Modos de jogo"), "c_modes")
    H2(t("Los cuatro modos", "The four modes", "Os quatro modos"))
    T([t("Modo", "Mode", "Modo"), t("Prefijo", "Prefix", "Prefixo"), t("DLL del modo", "Mode DLL", "DLL do modo"),
       t("Necesita", "Needs", "Precisa")],
      [[t("Deathmatch", "Deathmatch", "Deathmatch"), C("mp_dm_"), C("mp_deathMatch.dll"),
        t("8 o más puntos de inicio, de cualquier equipo.", "8 or more start points, any team.",
          "8 ou mais pontos de início, de qualquer time.")],
       [t("Deathmatch por equipos", "Team deathmatch", "Deathmatch por equipes"), C("mp_dmt_"), C("mp_deathMatchTeam.dll"),
        t("Puntos de inicio de los dos equipos (0 y 1).", "Start points for both teams (0 and 1).",
          "Pontos de início dos dois times (0 e 1).")],
       [t("Capturar la bandera", "Capture the flag", "Capturar a bandeira"), C("mp_b_"), C("mp_CaptureTheFlag.dll"),
        t("Puntos de los dos equipos y 2 banderas.", "Points for both teams and 2 flags.",
          "Pontos dos dois times e 2 bandeiras.")],
       [t("Destruir el objetivo", "Destroy the target", "Destruir o alvo"), C("mp_do_"), C("mp_DestroyTheTarget.dll"),
        t("Muchos puntos de inicio, zona(s) de bomba y la bomba.", "Many start points, bomb zone(s) and the bomb.",
          "Muitos pontos de início, zona(s) de bomba e a bomba.")]],
      [0.22, 0.12, 0.28, 0.38])
    P(t("El modo se elige en " + M("DEBUG > Modo de juego / cielo / spawns / música") + ". El prefijo del nombre es una "
        "costumbre del juego: el editor lo propone al crear un mapa.",
        "The mode is chosen in " + M("DEBUG > Game mode / sky / spawns / music") + ". The name prefix is a habit of the "
        "game: the editor suggests it when you create a map.",
        "O modo é escolhido em " + M("DEBUG > Modo de jogo / céu / spawns / música") + ". O prefixo do nome é um costume "
        "do jogo: o editor o sugere ao criar um mapa."))
    H2(t("Puntos de inicio, botiquines y armas", "Start points, health packs and weapons",
         "Pontos de início, kits médicos e armas"))
    UL([t("<b>Puntos de inicio</b>: botones por equipo o un anillo de 14. Con " + M("Revisión de puntos de aparición") +
          " se encuentran los mal puestos, y <b>Repartirlos por todo el piso</b> los distribuye solos.",
          "<b>Start points</b>: buttons per team or a ring of 14. " + M("Start point check") + " finds badly placed ones, "
          "and <b>Spread them over the whole floor</b> places them by itself.",
          "<b>Pontos de início</b>: botões por time ou um anel de 14. " + M("Verificação dos pontos de início") +
          " encontra os mal colocados, e <b>Espalhá-los por todo o chão</b> os distribui sozinho."),
        t("<b>Botiquines</b>: grande (50) o chico (25). Se puede cambiar el tiempo en que vuelven a aparecer (de 1 a 600 "
          "s). Para eso se hace una copia de la DLL del botiquín para ese mapa.",
          "<b>Health packs</b>: big (50) or small (25). Their respawn time can be changed (1 to 600 s), with a copy of the "
          "health-pack DLL for that map.",
          "<b>Kits médicos</b>: grande (50) ou pequeno (25). Dá para mudar o tempo em que reaparecem (de 1 a 600 s), com "
          "uma cópia da DLL do kit para esse mapa."),
        t("<b>Armas permitidas</b> (" + M("Armas permitidas en este mapa") + "): en cada grupo elegís una sola arma, todas o "
          "ninguna. <b>Crear el DLL de armas de este mapa</b> hace la copia de la DLL del modo con esa elección.",
          "<b>Weapons allowed</b> (" + M("Weapons allowed on this map") + "): in each group pick one weapon, all or none. "
          "<b>Make weapons DLL for this map</b> makes the copy of the mode DLL with that choice.",
          "<b>Armas permitidas</b> (" + M("Armas permitidas neste mapa") + "): em cada grupo escolha uma arma só, todas ou "
          "nenhuma. <b>Criar a DLL de armas deste mapa</b> faz a cópia da DLL do modo com essa escolha.")])
    H2(t("Destruir el objetivo (DO)", "Destroy the target (DO)", "Destruir o alvo (DO)"), "k_do")
    P(t("El modo DO del juego termina la ronda solo cuando explota el objeto " + C("bombZone") + ". Para mapas con dos "
        "sitios (A y B), el editor hace una <b>copia de la DLL del modo</b> para ese mapa. En " +
        M("Jugabilidad > Destruir el objetivo: sitios de bomba y la bomba") + ":",
        "The game's DO mode only ends the round when the object " + C("bombZone") + " blows up. For maps with two sites "
        "(A and B), the editor makes a <b>copy of the mode DLL</b> for that map. In " +
        M("Gameplay > Destroy the target: bomb sites and the bomb") + ":",
        "O modo DO do jogo só termina a rodada quando o objeto " + C("bombZone") + " explode. Para mapas com dois locais "
        "(A e B), o editor faz uma <b>cópia da DLL do modo</b> para esse mapa. Em " +
        M("Jogabilidade > Destruir o alvo: locais da bomba e a bomba") + ":"))
    UL([t("<b>Otra zona de bomba acá</b>: agrega un sitio (copia de ", "<b>Another bomb zone here</b>: adds a site (copy of ",
          "<b>Outra zona de bomba aqui</b>: adiciona um local (cópia de ") + C("bombZone") + ").",
        t("<b>Hacer la DLL que cuenta todas las zonas</b>: la ronda se gana volando todas las zonas, las zonas se ven en el "
          "HUD y el radar señala la más cercana que sigue en pie.",
          "<b>Make the DLL that counts all the zones</b>: the round is won by blowing up every zone, the zones show on the "
          "HUD and the radar points at the nearest one still standing.",
          "<b>Fazer a DLL que conta todas as zonas</b>: a rodada é ganha explodindo todas as zonas, as zonas aparecem no "
          "HUD e o radar aponta a mais próxima ainda de pé."),
        t("<b>La bomba</b>: segundos desde que se planta hasta que explota (el juego usa 20), y si a las 0:00 la ronda "
          "espera a una bomba plantada. <b>Aplicar a este mapa</b>.",
          "<b>The bomb</b>: seconds from planting to the explosion (the game uses 20), and whether at 0:00 the round waits "
          "for a planted bomb. <b>Apply to this map</b>.",
          "<b>A bomba</b>: segundos desde que é plantada até explodir (o jogo usa 20), e se às 0:00 a rodada espera uma "
          "bomba plantada. <b>Aplicar a este mapa</b>."),
        t("Varios mapas pueden usar la misma copia: por ejemplo, " + C("mp_DestroyTheTargetCS.dll") + " para los mapas DO "
          "hechos desde Counter-Strike.",
          "Several maps can share one copy: for example, " + C("mp_DestroyTheTargetCS.dll") + " for the DO maps made "
          "from Counter-Strike.",
          "Vários mapas podem usar a mesma cópia: por exemplo, " + C("mp_DestroyTheTargetCS.dll") + " para os mapas DO "
          "feitos a partir do Counter-Strike.")])
    BOX("warn", t("Las copias de DLL (modo, armas, botiquines, clima) <b>van en la carpeta del juego del servidor y de cada "
                  "jugador</b>. El " + C(".zip") + " exportado las trae en " + C("dll/") + ", e <b>Instalar mapa desde "
                  "zip</b> las pone en su lugar.",
                  "DLL copies (mode, weapons, health packs, weather) <b>go in the game folder of the server and of every "
                  "player</b>. The exported " + C(".zip") + " carries them in " + C("dll/") + ", and <b>Install map from "
                  "zip</b> puts them in place.",
                  "As cópias de DLL (modo, armas, kits médicos, clima) <b>vão na pasta do jogo do servidor e de cada "
                  "jogador</b>. O " + C(".zip") + " exportado as traz em " + C("dll/") + ", e <b>Instalar mapa de zip</b> "
                  "as põe no lugar."))
    H2(t("Simular y equilibrar", "Simulate and balance", "Simular e equilibrar"))
    P(t("Antes de jugar, " + M("Simulación de partida") + " y " + M("Balance de equipos") + " muestran si un equipo llega "
        "antes al objetivo. Los mapas originales del juego dan entre 0 y 0,6 % de diferencia.",
        "Before playing, " + M("Match simulation") + " and " + M("Team balance") + " show whether one team reaches the "
        "objective first. The game's own maps give between 0 and 0.6 % difference.",
        "Antes de jogar, " + M("Simulação de partida") + " e " + M("Equilíbrio dos times") + " mostram se um time chega "
        "antes ao objetivo. Os mapas originais do jogo dão entre 0 e 0,6 % de diferença."))
    H2(t("Tutorial: un mapa desde cero", "Tutorial: a map from zero", "Tutorial: um mapa do zero"), "c_zero")
    FIG(fig_flow(W, t([("Datos", "nombre, modo, forma y medidas"), ("Crear", "suelo, paredes, inicios, botiquines"),
                       ("Construir", "formas, sólidos, OBJ, texturas"), ("Revisar", "revisar mapa, caminar, balance"),
                       ("Probar", "guardar, empaquetar y jugar")],
                      [("Settings", "name, mode, shape and size"), ("Create", "floor, walls, starts, health packs"),
                       ("Build", "shapes, solids, OBJ, textures"), ("Check", "map check, walk test, balance"),
                       ("Play", "save, pack and play")],
                      [("Dados", "nome, modo, forma e medidas"), ("Criar", "chão, paredes, inícios, kits médicos"),
                       ("Construir", "formas, sólidos, OBJ, texturas"), ("Verificar", "verificar mapa, caminhar, equilíbrio"),
                       ("Testar", "salvar, empacotar e jogar")])), 4,
        t("Un mapa desde cero, paso a paso.", "A map from zero, step by step.", "Um mapa do zero, passo a passo."))
    OL([t("Abrí cualquier mapa del juego y andá a " + M("Herramientas del mapa > Construir > Mapa nuevo desde cero (suelo y paredes)") + ".",
          "Open any map of the game and go to " + M("Map tools > Build > New map from zero (floor and walls)") + ".",
          "Abra qualquer mapa do jogo e vá em " + M("Ferramentas do mapa > Construir > Mapa novo do zero (chão e paredes)") + "."),
        t("Escribí el <b>nombre</b> y elegí el <b>modo</b>; el nombre toma el prefijo del modo. Después elegí la <b>forma</b> "
          "(rectángulo, cuadrado, círculo, octógono o L), las <b>medidas</b> en cm, el alto y el grosor de las paredes, las "
          "texturas del suelo y de las paredes, y los <b>jugadores por equipo</b>.",
          "Type the <b>name</b> and pick the <b>mode</b>; the name takes the mode's prefix. Then pick the <b>shape</b> "
          "(rectangle, square, circle, octagon or L), the <b>size</b> in cm, the height and thickness of the walls, the "
          "floor and wall textures, and the <b>players per team</b>.",
          "Digite o <b>nome</b> e escolha o <b>modo</b>; o nome recebe o prefixo do modo. Depois escolha a <b>forma</b> "
          "(retângulo, quadrado, círculo, octógono ou L), as <b>medidas</b> em cm, a altura e a espessura das paredes, as "
          "texturas do chão e das paredes, e os <b>jogadores por time</b>."),
        t("Tocá <b>Crear el mapa nuevo</b>. El editor arma la escena con su propio " + C(".opt") + " y " + C(".hm") +
          " (cielo, sol y configuración de Madrid para ese modo), el suelo y las paredes con colisión, los puntos de "
          "inicio, lo del modo (banderas o zona de bomba y bomba), 4 botiquines, la cámara y los sectores. Queda guardado y abierto.",
          "Click <b>Create the new map</b>. The editor builds the scene with its own " + C(".opt") + " and " + C(".hm") +
          " (Madrid's sky, sun and settings for that mode), the floor and walls with collision, the start points, what "
          "the mode needs (flags, or bomb zone and bomb), 4 health packs, the camera and the sectors. It is saved and opened.",
          "Clique em <b>Criar o mapa novo</b>. O editor monta a cena com seu próprio " + C(".opt") + " e " + C(".hm") +
          " (céu, sol e configuração de Madrid para esse modo), o chão e as paredes com colisão, os pontos de início, o "
          "que o modo precisa (bandeiras, ou zona de bomba e bomba), 4 kits médicos, a câmera e os setores. Fica salvo e aberto."),
        t("Construí con ", "Build with ", "Construa com ") +
        link("k_build", t("Formas, Crear sólido, Recorridos, Pincel e Importar modelo (OBJ)",
                          "Shapes, Create solid, Paths, Object brush and Import model (OBJ)",
                          "Formas, Criar sólido, Caminhos, Pincel e Importar modelo (OBJ)")) +
        t(". Lo que tenga <b>sólido</b> marcado lleva colisión.", ". Anything with <b>solid</b> ticked gets collision.",
          ". O que tiver <b>sólido</b> marcado ganha colisão."),
        t("Vestí el mapa: texturas, luces, cielo, niebla y música (", "Dress the map: textures, lights, sky, fog and music (",
          "Vista o mapa: texturas, luzes, céu, neblina e música (") + chap_link("c_edit", 5) + ").",
        t("Revisá: " + M("Revisar mapa") + ", " + M("Prueba de recorrido") + ", " + M("Buscador de caídas y trampas") + " y " +
          M("Balance de equipos") + ".",
          "Check: " + M("Map check") + ", " + M("Walk test") + ", " + M("Fall / trap finder") + " and " + M("Team balance") + ".",
          "Verifique: " + M("Verificar mapa") + ", " + M("Teste de caminhada") + ", " + M("Buscador de quedas e armadilhas") +
          " e " + M("Equilíbrio dos times") + "."),
        t("Hacé la <b>vista previa</b> del menú del juego (" + M("Archivo > Vista previa del mapa 256x256") + ") y después " +
          M("Archivo > Guardar, empaquetar y probar en el juego") + ".",
          "Make the game menu's <b>preview</b> (" + M("File > Map preview 256x256") + ") and then " +
          M("File > Save, pack and play in the game") + ".",
          "Faça a <b>pré-visualização</b> do menu do jogo (" + M("Arquivo > Pré-visualização do mapa 256x256") + ") e "
          "depois " + M("Arquivo > Salvar, empacotar e testar no jogo") + ".")])
    BOX("tip", t("Para un mapa nuevo a partir de uno del juego: abrilo, tocá " + M("Guardar escena como…") + " con un nombre "
                 "nuevo y después usá <b>1. Vaciar este mapa</b>, <b>2. Importar</b> y <b>3. Sectores nuevos</b>. Se quedan "
                 "su cielo, su sol y su configuración.",
                 "For a new map based on one of the game's: open it, use " + M("Save scene as…") + " with a new name, then "
                 "<b>1. Empty this map</b>, <b>2. Import</b> and <b>3. New sectors</b>. Its sky, sun and settings stay.",
                 "Para um mapa novo a partir de um do jogo: abra-o, use " + M("Salvar cena como…") + " com um nome novo e "
                 "depois <b>1. Esvaziar este mapa</b>, <b>2. Importar</b> e <b>3. Setores novos</b>. Ficam o céu, o sol e a "
                 "configuração dele."))

    # ================================================================ 8
    H1(t("Mapas desde Counter-Strike 1.6", "Maps from Counter-Strike 1.6", "Mapas a partir do Counter-Strike 1.6"), "c_cs")
    P(t("El editor convierte mapas de CS 1.6 (" + C(".bsp") + " compilados o " + C(".rmf") + " de Hammer) con sus texturas, "
        "su colisión real, sus puntos de inicio, sus sitios de bomba, sus modelos (" + C(".mdl") + ") y su luz.",
        "The editor converts CS 1.6 maps (compiled " + C(".bsp") + " or Hammer " + C(".rmf") + ") with their textures, real "
        "collision, start points, bomb sites, models (" + C(".mdl") + ") and light.",
        "O editor converte mapas do CS 1.6 (" + C(".bsp") + " compilados ou " + C(".rmf") + " do Hammer) com suas texturas, "
        "sua colisão real, seus pontos de início, seus locais de bomba, seus modelos (" + C(".mdl") + ") e sua luz."))
    FIG(fig_flow(W, t([("Archivos", ".bsp / .rmf, sus .wad y modelos"), ("Mapa nuevo", "modo, nombre, jugadores, agua"),
                       ("Luz de CS", "sol y sombras del .bsp"), ("Arreglos", "caras, parpadeos, rejas"),
                       ("Revisar y jugar", "DLL del modo en el zip")],
                      [("Files", ".bsp / .rmf, its .wad and models"), ("New map", "mode, name, players, water"),
                       ("CS light", "sun and shadows of the .bsp"), ("Fixes", "faces, blinking, bars"),
                       ("Check and play", "mode DLL in the zip")],
                      [("Arquivos", ".bsp / .rmf, seus .wad e modelos"), ("Mapa novo", "modo, nome, jogadores, água"),
                       ("Luz do CS", "sol e sombras do .bsp"), ("Correções", "faces, piscadas, grades"),
                       ("Verificar e jogar", "DLL do modo no zip")]), TEAL), 5,
        t("De Counter-Strike 1.6 a Torrente Online.", "From Counter-Strike 1.6 to Torrente Online.",
          "Do Counter-Strike 1.6 ao Torrente Online."))
    H2(t("Qué hace falta", "What you need", "O que é preciso"))
    UL([t("El " + C(".bsp") + " (o " + C(".rmf") + "). Si viene en un " + C(".rar") + " o " + C(".zip") + ", descomprimilo "
          "conservando las carpetas " + C("maps") + ", " + C("models") + ", " + C("sprites") + " y " + C("gfx") + ".",
          "The " + C(".bsp") + " (or " + C(".rmf") + "). If it comes in a " + C(".rar") + " or " + C(".zip") + ", unpack it "
          "keeping the " + C("maps") + ", " + C("models") + ", " + C("sprites") + " and " + C("gfx") + " folders.",
          "O " + C(".bsp") + " (ou " + C(".rmf") + "). Se vier num " + C(".rar") + " ou " + C(".zip") + ", descompacte "
          "mantendo as pastas " + C("maps") + ", " + C("models") + ", " + C("sprites") + " e " + C("gfx") + "."),
        t("Los <b>" + C(".wad") + "</b> que nombra el mapa, si no trae las texturas adentro. El editor dice cuáles pide: en "
          "<b>verde</b> los cargados, en <b>amarillo</b> los encontrados (<b>Cargar los N encontrados</b>) y en <b>rojo</b> "
          "los que faltan. Las texturas que no aparecen en ningún " + C(".wad") + " se dibujan con una de Torrente parecida.",
          "The <b>" + C(".wad") + "</b> files the map names, if its textures are not inside. The editor lists them: "
          "<b>green</b> loaded, <b>yellow</b> found (<b>Load the N found</b>) and <b>red</b> missing. Textures in no " +
          C(".wad") + " are drawn with a similar Torrente texture.",
          "Os <b>" + C(".wad") + "</b> que o mapa cita, se ele não traz as texturas dentro. O editor diz quais pede: em "
          "<b>verde</b> os carregados, em <b>amarelo</b> os encontrados (<b>Carregar os N encontrados</b>) e em "
          "<b>vermelho</b> os que faltam. As texturas que não estão em nenhum " + C(".wad") + " são desenhadas com uma "
          "parecida do Torrente."),
        t("Los modelos " + C(".mdl") + " (autos, palmeras, toldos) se buscan junto al mapa y se ponen como mallas.",
          "The " + C(".mdl") + " models (cars, palm trees, awnings) are looked for next to the map and placed as meshes.",
          "Os modelos " + C(".mdl") + " (carros, palmeiras, toldos) são procurados junto ao mapa e colocados como malhas.")])
    H2(t("Crear el mapa", "Creating the map", "Criar o mapa"), "k_csnew")
    OL([t(M("Archivo > Mapa nuevo desde CS 1.6 (.bsp / .rmf)…") + " y elegí el archivo.",
          M("File > New map from CS 1.6 (.bsp / .rmf)…") + " and pick the file.",
          M("Arquivo > Mapa novo a partir de CS 1.6 (.bsp / .rmf)…") + " e escolha o arquivo."),
        t("Cargá los " + C(".wad") + " que falten.", "Load any missing " + C(".wad") + ".",
          "Carregue os " + C(".wad") + " que faltarem."),
        t("Elegí el <b>modo</b> y el <b>nombre</b> (se propone " + C("mp_&lt;modo&gt;_&lt;mapa&gt;") + "). Después elegí "
          "los <b>jugadores por equipo</b> (por ejemplo, 16) y el <b>agua</b>: piso (se camina encima) o hueco (el que entra "
          "se cae).",
          "Pick the <b>mode</b> and the <b>name</b> (" + C("mp_&lt;mode&gt;_&lt;map&gt;") + " is suggested). Then the "
          "<b>players per team</b> (for example, 16) and the <b>water</b>: floor (you walk on it) or hole (whoever goes "
          "in falls).",
          "Escolha o <b>modo</b> e o <b>nome</b> (é sugerido " + C("mp_&lt;modo&gt;_&lt;mapa&gt;") + "). Depois os "
          "<b>jogadores por time</b> (por exemplo, 16) e a <b>água</b>: chão (anda-se em cima) ou buraco (quem entra cai)."),
        t("Tocá <b>Crear el mapa nuevo</b>. El editor pone:"
          "<br/>• el mapa a tamaño real (1 unidad de CS = 2,54 cm) con sus texturas;"
          "<br/>• la colisión que el jugador choca en CS; los escalones de hasta 46 cm se vuelven rampas cortas para que se puedan subir;"
          "<br/>• los puntos de inicio (CT = equipo 0, T = equipo 1). Si el mapa trae menos que los pedidos, completa los que faltan al lado de los de su equipo;"
          "<br/>• los botiquines junto a cada base;"
          "<br/>• lo del modo: banderas (B), o los sitios A y B con su DLL y la bomba junto a los T (DO);"
          "<br/>• la luz de CS, los sectores y la cámara.",
          "Click <b>Create the new map</b>. The editor puts in:"
          "<br/>• the map at real size (1 CS unit = 2.54 cm) with its textures;"
          "<br/>• the collision the player bumps into in CS; steps up to 46 cm become short ramps so they can be climbed;"
          "<br/>• the start points (CT = team 0, T = team 1). If the map has fewer than asked, the missing ones are added next to their team's;"
          "<br/>• health packs by each base;"
          "<br/>• what the mode needs: flags (B), or sites A and B with their DLL and the bomb by the T (DO);"
          "<br/>• the CS light, the sectors and the camera.",
          "Clique em <b>Criar o mapa novo</b>. O editor coloca:"
          "<br/>• o mapa em tamanho real (1 unidade do CS = 2,54 cm) com suas texturas;"
          "<br/>• a colisão em que o jogador bate no CS; os degraus de até 46 cm viram rampas curtas para poder subir;"
          "<br/>• os pontos de início (CT = time 0, T = time 1). Se o mapa traz menos que os pedidos, completa os que faltam ao lado dos do seu time;"
          "<br/>• os kits médicos junto a cada base;"
          "<br/>• o que o modo precisa: bandeiras (B), ou os locais A e B com sua DLL e a bomba junto aos T (DO);"
          "<br/>• a luz do CS, os setores e a câmera."),
        t("Revisá y probalo (", "Check it and try it (", "Verifique e teste (") + link("k_csfix", "8.5") + ")."])
    H2(t("Qué pasa con cada cosa de CS", "What happens to each CS thing", "O que acontece com cada coisa do CS"))
    T([t("En CS", "In CS", "No CS"), t("En Torrente", "In Torrente", "No Torrente")],
      [[t("Paredes, pisos, ", "Walls, floors, ", "Paredes, pisos, ") + C("func_wall"),
        t("Mallas con su textura y colisión.", "Meshes with their texture and collision.", "Malhas com sua textura e colisão.")],
       [C("func_water"), t("Agua semitransparente: piso caminable o hueco, según elijas.",
                           "See-through water: a floor you walk on, or a hole, as you choose.",
                           "Água semitransparente: chão caminhável ou buraco, como escolher.")],
       [C("func_door"), t("Puertas abiertas (en el juego no se abrirían).", "Doors left open (they would not open in the game).",
                          "Portas abertas (no jogo não abririam).")],
       [C("func_illusionary"), t("Se ve, pero se atraviesa.", "Seen, but you walk through it.", "Aparece, mas se atravessa.")],
       [t("Vidrios, rejas (texturas ", "Glass, bars (", "Vidros, grades (texturas ") + C("{") + t(")", " textures)", ")"),
        t("Transparentes. Las balas pasan por los huecos de las rejas y el jugador no.",
          "See-through. Bullets go through the gaps between bars, players do not.",
          "Transparentes. As balas passam pelos vãos das grades e o jogador não.")],
       [C("func_breakable") + t(" fino", " (thin)", " fino"),
        t("Si tiene aire de los dos lados queda abierto (tablones sobre ventanas).",
          "If there is air on both sides it is left open (planks over windows).",
          "Se tem ar dos dois lados fica aberto (tábuas sobre janelas).")],
       [t("Triggers, zonas de compra, CLIP, SKY", "Triggers, buy zones, CLIP, SKY", "Triggers, zonas de compra, CLIP, SKY"),
        t("No se dibujan. La colisión de los CLIP sí cuenta.", "Not drawn. CLIP collision does count.",
          "Não são desenhados. A colisão dos CLIP conta.")],
       [C("info_player_start") + " / " + C("info_player_deathmatch"),
        t("Puntos de inicio del equipo 0 / equipo 1.", "Start points of team 0 / team 1.", "Pontos de início do time 0 / time 1.")],
       [C("func_bomb_target"), t("Zonas de bomba ", "Bomb zones ", "Zonas de bomba ") + C("bombZone") + " (A) " +
        t("y", "and", "e") + " " + C("bombZone_B") + " (B)."]],
      [0.36, 0.64])
    H2(t("La luz de CS", "The CS light", "A luz do CS"), "k_cslight")
    P(t("En " + M("Aspecto > Texturas: buscar / reemplazar") + " está la sección de la luz de un mapa de CS:",
        "In " + M("Look > Textures: search / replace") + " there is the section for the light of a CS map:",
        "Em " + M("Aparência > Texturas: procurar / substituir") + " fica a seção da luz de um mapa de CS:"))
    UL([t("<b>Agregar la luz del .bsp (sol, sombras)</b>: le pone al mapa la luz original de CS, con las sombras de cada "
          "pared. Los modelos toman la luz del piso que tienen debajo.",
          "<b>Add the light of the .bsp (sun, shadows)</b>: gives the map CS's original light, with every wall's shadows. "
          "Models take the light of the floor under them.",
          "<b>Adicionar a luz do .bsp (sol, sombras)</b>: põe no mapa a luz original do CS, com as sombras de cada parede. "
          "Os modelos pegam a luz do chão que têm embaixo."),
        t("<b>Sacar la luz de CS</b>: vuelve a la luz normal del juego.", "<b>Take the CS light off</b>: back to the "
          "game's normal light.", "<b>Tirar a luz do CS</b>: volta à luz normal do jogo.")])
    H2(t("Revisar un mapa de CS", "Checking a CS map", "Verificar um mapa de CS"), "k_csfix")
    P(t("En la misma sección hay arreglos para mapas hechos antes o con problemas. Todos usan el " + C(".bsp") + " original:",
        "The same section has fixes for maps made earlier or with problems. They all use the original " + C(".bsp") + ":",
        "Na mesma seção há correções para mapas feitos antes ou com problemas. Todas usam o " + C(".bsp") + " original:"))
    T([t("Botón", "Button", "Botão"), t("Arregla", "Fixes", "Corrige")],
      [[t("<b>Paredes sin textura: volver a dibujar las caras del .bsp que faltan</b>",
          "<b>Walls with no texture: draw again the faces of the .bsp missing</b>",
          "<b>Paredes sem textura: desenhar de novo as faces do .bsp que faltam</b>"),
        t("Huecos por donde se veía el cielo.", "Holes the sky showed through.", "Buracos por onde se via o céu.")],
       [t("<b>Calcos que parpadean / láminas oscuras transparentes</b>", "<b>Blinking decals / dark see-through sheets</b>",
          "<b>Decalques que piscam / lâminas escuras transparentes</b>"),
        t("Carteles y manchas pegados a la pared, placas finas dibujadas dos veces, caras apretadas contra otra (el fondo "
          "de una caja sobre el piso), el agua y las hojas dobles de los modelos.",
          "Signs and stains stuck to the wall, thin slabs drawn twice, faces pressed against another (a crate's bottom on "
          "the floor), water and the double leaves of models.",
          "Placas e manchas grudadas na parede, chapas finas desenhadas duas vezes, faces apertadas contra outra (o fundo "
          "de uma caixa no chão), a água e as folhas duplas dos modelos.")],
       [t("<b>Rejas, barrotes, barandas: balas por los huecos</b>", "<b>Bars, grilles, railings: bullets through the gaps</b>",
          "<b>Grades, barras, corrimãos: balas pelos vãos</b>"),
        t("En CS las balas pasan entre los barrotes; con este botón en Torrente también, y los jugadores siguen sin poder pasar.",
          "In CS bullets go between bars; with this button they do in Torrente too, and players still cannot get through.",
          "No CS as balas passam entre as barras; com este botão no Torrente também, e os jogadores continuam sem passar.")],
       [t("<b>Escaleras: volver a hacer la colisión del piso desde el .bsp</b>",
          "<b>Stairs: make the floor collision again from the .bsp</b>",
          "<b>Escadas: refazer a colisão do chão a partir do .bsp</b>"),
        t("Rehace la colisión del piso con las reglas de ahora: escaleras como una sola pendiente pareja sin "
          "nada debajo (no te hundís en ellas), escalones chicos con rampa, sin piso dentro de escaleras o cajas "
          "sólidas, y sin las paredes invisibles que dejaba el hull de CS.",
          "Makes the floor collision again with today's rules: stairs as one even slope with nothing under it (you "
          "no longer sink into them), small steps with a ramp, no floor inside solid stairs or crates, and none of "
          "the invisible walls CS's hull left.",
          "Refaz a colisão do chão com as regras de agora: escadas como uma só rampa uniforme sem nada embaixo "
          "(você não afunda nelas), degraus pequenos com rampa, sem chão dentro de escadas ou caixas sólidas, e "
          "sem as paredes invisíveis que o hull do CS deixava.")],
       [t("<b>Arreglar materiales negros</b>", "<b>Fix black materials</b>", "<b>Consertar materiais pretos</b>"),
        t("Mallas que el juego dibujaba negras.", "Meshes the game drew black.", "Malhas que o jogo desenhava pretas.")],
       [t("<b>Cortar mallas demasiado grandes</b>", "<b>Cut meshes too big for the game</b>", "<b>Cortar malhas grandes demais</b>"),
        t("Mallas con tantos vértices que el juego se cerraba al cargar.", "Meshes with so many vertices that the game "
          "closed while loading.", "Malhas com tantos vértices que o jogo fechava ao carregar.")]],
      [0.5, 0.5])
    BOX("note", t("Después de crear un mapa de CS, revisá sobre todo: los sitios de bomba (en DO), que los puntos de inicio "
                  "estén en su base, la prueba de caminar entre las bases y el " + M("Buscador de caídas y trampas") + ".",
                  "After creating a CS map, check above all: the bomb sites (in DO), that start points are in their base, the "
                  "walk test between bases and the " + M("Fall / trap finder") + ".",
                  "Depois de criar um mapa de CS, verifique sobretudo: os locais de bomba (no DO), que os pontos de início "
                  "estejam na base, o teste de caminhada entre as bases e o " + M("Buscador de quedas e armadilhas") + "."))

    # ================================================================ 9
    H1(t("Mapas desde Torrente, el juego", "Maps from Torrente, el juego", "Mapas a partir de Torrente, el juego"), "c_tj")
    P(t("<i>Torrente, el juego</i> (el juego de un jugador) usa un motor más viejo. El editor puede traer sus modelos, mapas, "
        "escenas, texturas y música a Torrente Online, convertidos al formato nuevo y sin pisar nada.",
        "<i>Torrente, el juego</i> (the single-player game) uses an older engine. The editor can bring its models, maps, "
        "scenes, textures and music into Torrente Online, converted to the new format and without overwriting anything.",
        "<i>Torrente, el juego</i> (o jogo de um jogador) usa um motor mais antigo. O editor pode trazer seus modelos, "
        "mapas, cenas, texturas e música para o Torrente Online, convertidos ao formato novo e sem sobrescrever nada."))
    FIG(fig_flow(W, t([("Carpeta", "elegir dónde está el juego"), ("Library", "modelos, mapas, escenas, texturas, música"),
                       ("Importar", "convierte TeX1 y VTOP al formato Online"), ("Completar", "inicios, modo, botiquines"),
                       ("Revisar y jugar", "revisar mapa, caminar, empaquetar")],
                      [("Folder", "choose where the game is"), ("Library", "models, maps, scenes, textures, music"),
                       ("Import", "converts TeX1 and VTOP to the Online format"), ("Complete", "starts, mode, health packs"),
                       ("Check and play", "map check, walk test, pack")],
                      [("Pasta", "escolher onde está o jogo"), ("Library", "modelos, mapas, cenas, texturas, música"),
                       ("Importar", "converte TeX1 e VTOP ao formato Online"), ("Completar", "inícios, modo, kits médicos"),
                       ("Verificar e jogar", "verificar mapa, caminhar, empacotar")]), ACCENT2), 6,
        t("De Torrente, el juego a Torrente Online.", "From Torrente, el juego to Torrente Online.",
          "De Torrente, el juego ao Torrente Online."))
    H2(t("Elegir la carpeta del juego", "Choosing the game folder", "Escolher a pasta do jogo"))
    OL([t(M("Archivo > Carpeta de Torrente, el juego…") + " (o <b>Browse</b> en " + M("DEBUG > Library") + ").",
          M("File > Torrente, el juego folder…") + " (or <b>Browse</b> in " + M("DEBUG > Library") + ").",
          M("Arquivo > Pasta de Torrente, el juego…") + " (ou <b>Browse</b> em " + M("DEBUG > Library") + ")."),
        t("Elegí la carpeta donde está instalado. Si solo hay " + C(".vpk") + ", se desempaquetan una vez en " +
          C("tj_unpacked") + ". La carpeta se recuerda para la próxima vez.",
          "Pick the folder where it is installed. If there are only " + C(".vpk") + " files, they are unpacked once into " +
          C("tj_unpacked") + ". The folder is remembered.",
          "Escolha a pasta onde está instalado. Se só houver " + C(".vpk") + ", são descompactados uma vez em " +
          C("tj_unpacked") + ". A pasta fica lembrada para a próxima vez."),
        t("Con <b>only what my game does not have</b> activada, la lista muestra solo lo que tu Torrente Online no tiene con ese nombre.",
          "With <b>only what my game does not have</b> ticked, the list only shows what your Torrente Online does not have under that name.",
          "Com <b>only what my game does not have</b> marcado, a lista mostra só o que o seu Torrente Online não tem com esse nome.")])
    H2(t("Qué se puede importar", "What you can import", "O que dá para importar"))
    T([t("Tipo", "Type", "Tipo"), t("Qué hace el botón", "What the button does", "O que o botão faz")],
      [["<b>models (.nfo)</b>", t("<b>Import and place in scene</b>: copia el modelo y sus texturas y lo pone en la escena. "
                                  "Al pasar el mouse por un nombre, aparece delante de la cámara.",
                                  "<b>Import and place in scene</b>: copies the model and its textures and puts it in the "
                                  "scene. Hovering a name shows it in front of the camera.",
                                  "<b>Import and place in scene</b>: copia o modelo e suas texturas e o põe na cena. "
                                  "Passando o mouse por um nome, ele aparece na frente da câmera.")],
       ["<b>maps (.opt + .hm)</b>", t("<b>Import map and create scene</b>: convierte el mapa (VTOP → VTO1) y sus texturas, y "
                                      "crea una escena nueva con el mismo nombre.",
                                      "<b>Import map and create scene</b>: converts the map (VTOP → VTO1) and its textures, "
                                      "and makes a new scene with the same name.",
                                      "<b>Import map and create scene</b>: converte o mapa (VTOP → VTO1) e suas texturas, "
                                      "e cria uma cena nova com o mesmo nome.")],
       ["<b>old scenes</b>", t("<b>Convert to an Online scene</b>: el mapa más sus objetos (ver abajo).",
                               "<b>Convert to an Online scene</b>: the map plus its objects (see below).",
                               "<b>Convert to an Online scene</b>: o mapa mais seus objetos (veja abaixo).")],
       ["<b>textures</b> / <b>music</b>", t("Copia texturas (TeX1 → TeX2) y músicas que tu juego no tiene.",
                                            "Copies textures (TeX1 → TeX2) and music your game does not have.",
                                            "Copia texturas (TeX1 → TeX2) e músicas que o seu jogo não tem.")]],
      [0.25, 0.75])
    H2(t("Convertir una escena entera", "Converting a whole scene", "Converter uma cena inteira"))
    P(t("Por ejemplo, <i>Spinelli chalets</i> (", "For example, <i>Spinelli chalets</i> (", "Por exemplo, <i>Spinelli chalets</i> (") +
      C("fasex_f03.scn") + "):")
    OL([t("En " + M("Library") + " elegí <b>old scenes</b> y la escena, escribí el nombre nuevo y tocá <b>Convert to an Online scene</b>.",
          "In " + M("Library") + " pick <b>old scenes</b> and the scene, type the new name and click <b>Convert to an Online scene</b>.",
          "Em " + M("Library") + " escolha <b>old scenes</b> e a cena, digite o nome novo e clique em <b>Convert to an Online scene</b>."),
        t("Se importan el nivel y todas sus texturas, sin pisar nada.", "The level and all its textures are imported, "
          "overwriting nothing.", "O nível e todas as suas texturas são importados, sem sobrescrever nada."),
        t("Se crea la escena Online con la configuración de una escena DM. Los módulos se traducen: los modelos y "
          "animaciones pasan tal cual, ", "The Online scene is created with a DM scene's settings. Modules are translated: "
          "models and animations go as they are, ", "A cena Online é criada com a configuração de uma cena DM. Os módulos "
          "são traduzidos: modelos e animações passam como estão, ") + C("CCar") + " → " + C("mp_CCar") + ", " + C("salud") +
        " → " + C("mp_salud") + t(" y los sonidos a ", " and sounds become ", " e os sons viram ") + C("mp_SoundSource") +
        t(". Los objetos de decorado quedan como modelos quietos.", ". Scenery objects become still models.",
          ". Os objetos de cenário viram modelos parados."),
        t("Se ponen 14 puntos de inicio alrededor de donde empezaba el jugador, y la cámara.",
          "14 start points are placed around where the player started, plus the camera.",
          "São postos 14 pontos de início em volta de onde o jogador começava, e a câmera."),
        t("Se muestra un informe: lo copiado, lo reutilizado, lo renombrado y lo que no se pudo convertir.",
          "A report shows what was copied, reused, renamed and what could not be converted.",
          "Aparece um relatório: o copiado, o reutilizado, o renomeado e o que não pôde ser convertido.")])
    BOX("note", t("No existen en Online, así que no se convierten: enemigos, peatones, perros, armas del juego viejo, físicas "
                  "y scripts. Después de convertir, acomodá los puntos de inicio, elegí el modo y agregá botiquines, banderas "
                  "o la bomba.",
                  "They do not exist in Online, so they are not converted: enemies, pedestrians, dogs, the old game's "
                  "weapons, physics and scripts. After converting, adjust the start points, pick the mode and add health "
                  "packs, flags or the bomb.",
                  "Não existem no Online, então não são convertidos: inimigos, pedestres, cachorros, armas do jogo antigo, "
                  "físicas e scripts. Depois de converter, ajuste os pontos de início, escolha o modo e adicione kits "
                  "médicos, bandeiras ou a bomba."))
    BOX("tip", t("Los modelos del juego viejo también sirven para decorar cualquier mapa. Si alguno cambia a una versión "
                 "simple de lejos, su panel ofrece <b>Detalle completo a cualquier distancia</b>.",
                 "The old game's models are also good to decorate any map. If one switches to a simple version from afar, "
                 "its panel offers <b>Full detail at any distance</b>.",
                 "Os modelos do jogo antigo também servem para decorar qualquer mapa. Se algum muda para uma versão simples "
                 "de longe, o painel oferece <b>Detalhe total a qualquer distância</b>."))

    # ================================================================ 10
    H1(t("Guardar, probar y compartir", "Saving, testing and sharing", "Salvar, testar e compartilhar"), "c_share")
    H2(t("Guardar", "Saving", "Salvar"))
    UL([t(M("Archivo > Guardar escena (y mapa editado)") + " guarda la escena y, si cambió, su " + C(".opt") + " y su " + C(".hm") + ".",
          M("File > Save scene (and edited map)") + " saves the scene and, if they changed, its " + C(".opt") + " and " + C(".hm") + ".",
          M("Arquivo > Salvar cena (e mapa editado)") + " salva a cena e, se mudaram, seu " + C(".opt") + " e seu " + C(".hm") + "."),
        t(M("Guardar escena como…") + " crea un mapa nuevo con otro nombre y deja el original como estaba.",
          M("Save scene as…") + " makes a new map under another name and leaves the original as it was.",
          M("Salvar cena como…") + " cria um mapa novo com outro nome e deixa o original como estava."),
        t("En cada guardado se corre " + M("Revisar mapa") + " y queda una copia en el <b>historial</b>.",
          "Every save runs the " + M("Map check") + " and keeps a copy in the <b>history</b>.",
          "A cada salvamento roda o " + M("Verificar mapa") + " e fica uma cópia no <b>histórico</b>."),
        t("Al cerrar con cambios sin guardar, el editor pregunta: <b>Guardar y salir</b>, <b>Salir sin guardar</b> o <b>Cancelar</b>.",
          "Closing with unsaved changes asks: <b>Save and exit</b>, <b>Exit without saving</b> or <b>Cancel</b>.",
          "Ao fechar com alterações não salvas, o editor pergunta: <b>Salvar e sair</b>, <b>Sair sem salvar</b> ou <b>Cancelar</b>.")])
    H2(t("Probar en el juego", "Testing in the game", "Testar no jogo"))
    OL([t("En " + M("Juego y archivos > Probar en el juego") + ", elegí una vez el " + C(".exe") + " de Torrente Online.",
          "In " + M("Game & files > Play in the game") + ", pick Torrente Online's " + C(".exe") + " once.",
          "Em " + M("Jogo e arquivos > Testar no jogo") + ", escolha uma vez o " + C(".exe") + " do Torrente Online."),
        t(M("Archivo > Guardar, empaquetar y probar en el juego") + " guarda, rehace el " + C("demo.vpk") + " (con copia " +
          C(".bak") + ") y abre el juego.",
          M("File > Save, pack and play in the game") + " saves, rebuilds " + C("demo.vpk") + " (with a " + C(".bak") +
          " copy) and starts the game.",
          M("Arquivo > Salvar, empacotar e testar no jogo") + " salva, refaz o " + C("demo.vpk") + " (com cópia " +
          C(".bak") + ") e abre o jogo."),
        t("En el juego, elegí el mapa en el menú.", "In the game, pick the map in the menu.", "No jogo, escolha o mapa no menu.")])
    H2(t("Exportar e instalar", "Export and install", "Exportar e instalar"))
    UL([t("<b>Exportar este mapa como .zip</b>: la escena, el mapa, el piso, las texturas, los modelos, las animaciones, la "
          "vista previa, las DLL propias, la música y un " + C("vtoy_manifest.json") + ". Guardá antes, porque se exporta "
          "lo que está en disco.",
          "<b>Export this map as .zip</b>: the scene, map, floor, textures, models, animations, preview, its own DLLs, "
          "music and a " + C("vtoy_manifest.json") + ". Save first, because what is on disk is exported.",
          "<b>Exportar este mapa como .zip</b>: a cena, o mapa, o chão, as texturas, os modelos, as animações, a "
          "pré-visualização, as DLL próprias, a música e um " + C("vtoy_manifest.json") + ". Salve antes, porque é "
          "exportado o que está no disco."),
        t("<b>Instalar mapa desde zip</b>: copia cada cosa a su lugar y <b>nunca reemplaza</b> un archivo que el juego ya "
          "tiene. Anota lo que instaló, y <b>Uninstall</b> borra exactamente eso. Después, <b>Reempaquetar VPK</b>.",
          "<b>Install map from zip</b>: copies everything to its place and <b>never replaces</b> a file the game already "
          "has. It notes what it installed, and <b>Uninstall</b> removes exactly that. Then <b>Repackage VPK</b>.",
          "<b>Instalar mapa de zip</b>: copia cada coisa para o seu lugar e <b>nunca substitui</b> um arquivo que o jogo já "
          "tem. Anota o que instalou, e <b>Uninstall</b> apaga exatamente isso. Depois, <b>Reempacotar VPK</b>."),
        t("<b>Vista previa</b> (" + M("Archivo > Vista previa del mapa 256x256") + "): la imagen del mapa en el menú del juego.",
          "<b>Preview</b> (" + M("File > Map preview 256x256") + "): the map's picture in the game menu.",
          "<b>Pré-visualização</b> (" + M("Arquivo > Pré-visualização do mapa 256x256") + "): a imagem do mapa no menu do jogo.")])
    BOX("warn", t("Para jugar en red, todos necesitan el mismo mapa y las mismas DLL propias. Pasá el " + C(".zip") +
                  " exportado y que cada jugador lo instale.",
                  "To play online, everyone needs the same map and the same DLLs. Share the exported " + C(".zip") +
                  " and have every player install it.",
                  "Para jogar em rede, todos precisam do mesmo mapa e das mesmas DLL próprias. Passe o " + C(".zip") +
                  " exportado e cada jogador o instala."))
    H2(t("Historial y copias", "History and copies", "Histórico e cópias"))
    UL([t(M("Juego y archivos > Historial") + ": <b>Restaurar</b> vuelve a un guardado anterior (el actual se guarda antes), "
          "y <b>Comparar</b> lista qué cambió.",
          M("Game & files > History") + ": <b>Restore</b> goes back to an earlier save (the current one is saved first), and "
          "<b>Compare</b> lists what changed.",
          M("Jogo e arquivos > Histórico") + ": <b>Restaurar</b> volta a um salvamento anterior (o atual é salvo antes), e "
          "<b>Comparar</b> lista o que mudou."),
        t(M("Revisar > Cambios desde una versión guardada") + " marca en la vista lo nuevo, lo sacado y lo movido.",
          M("Check > Changes since a saved version") + " marks in the view what is new, removed and moved.",
          M("Verificar > Mudanças desde uma versão salva") + " marca na vista o novo, o retirado e o movido.")])

    # ================================================================ 11
    H1(t("Solución de problemas", "Troubleshooting", "Solução de problemas"), "c_trouble")
    T([t("Problema", "Problem", "Problema"), t("Qué hacer", "What to do", "O que fazer")],
      [[t("<b>El editor va lento (pocos FPS)</b>", "<b>The editor is slow (low FPS)</b>", "<b>O editor está lento (FPS baixo)</b>"),
        t("Puede estar usando la placa integrada. En Windows: Configuración > Pantalla > Gráficos > " + C("VToyEditor.exe") +
          " > Alto rendimiento. El log dice qué placa usa.",
          "It may be on the integrated card. In Windows: Settings > Display > Graphics > " + C("VToyEditor.exe") +
          " > High performance. The log says which card it uses.",
          "Pode estar usando a placa integrada. No Windows: Configurações > Tela > Gráficos > " + C("VToyEditor.exe") +
          " > Alto desempenho. O log diz qual placa usa.")],
       [t("<b>El juego no carga el mapa o se cierra</b>", "<b>The game does not load the map, or closes</b>",
          "<b>O jogo não carrega o mapa ou fecha</b>"),
        t("Corré " + M("Revisar mapa") + ": falta la cámara, hay nombres repetidos, puntos de inicio fuera del mapa o "
          "archivos que faltan. Fijate también que las DLL propias estén en la carpeta del juego.",
          "Run the " + M("Map check") + ": missing camera, repeated names, start points outside the map or missing files. "
          "Also make sure the map's own DLLs are in the game folder.",
          "Rode o " + M("Verificar mapa") + ": falta a câmera, há nomes repetidos, pontos de início fora do mapa ou "
          "arquivos que faltam. Veja também se as DLL próprias estão na pasta do jogo.")],
       [t("<b>El mapa se ve negro en el juego</b>", "<b>The map looks black in the game</b>", "<b>O mapa fica preto no jogo</b>"),
        t(M("Aspecto > Texturas > Arreglar materiales negros") + ". Fijate también que haya un sol o una luz ambiental.",
          M("Look > Textures > Fix black materials") + ". Also check there is a sun or an ambient light.",
          M("Aparência > Texturas > Consertar materiais pretos") + ". Veja também se há um sol ou uma luz ambiente.")],
       [t("<b>Algo parpadea</b>", "<b>Something blinks</b>", "<b>Algo pisca</b>"),
        t("En mapas de CS: <b>Calcos que parpadean / láminas oscuras</b> (", "In CS maps: <b>Blinking decals / dark sheets</b> (",
          "Em mapas de CS: <b>Decalques que piscam / lâminas escuras</b> (") + link("k_csfix", "8.5") +
        t("). En otros, buscá dos caras en el mismo lugar.", "). In others, look for two faces in the same place.",
          "). Em outros, procure duas faces no mesmo lugar.")],
       [t("<b>Me caigo del mapa / me trabo</b>", "<b>I fall off the map / get stuck</b>", "<b>Caio do mapa / fico preso</b>"),
        t(M("Buscador de caídas y trampas") + ", " + M("Huecos en el piso") + " y " + M("Ver > Colisión de piso (.hm)") + ".",
          M("Fall / trap finder") + ", " + M("Floor gaps") + " and " + M("View > Floor collision (.hm)") + ".",
          M("Buscador de quedas e armadilhas") + ", " + M("Buracos no chão") + " e " + M("Exibir > Colisão do piso (.hm)") + ".")],
       [t("<b>Un objeto desaparece desde ciertos lugares</b>", "<b>An object disappears from some places</b>",
          "<b>Um objeto some de certos lugares</b>"),
        t(M("Revisar > Sectores > Rehacer los sectores") + ".", M("Check > Sectors > Rebuild the sectors") + ".",
          M("Verificar > Setores > Refazer os setores") + ".")],
       [t("<b>No encuentro una herramienta</b>", "<b>I cannot find a tool</b>", "<b>Não acho uma ferramenta</b>"),
        K("Ctrl", "P") + t(" y escribí parte de su nombre.", " and type part of its name.", " e digite parte do nome.")],
       [t("<b>Algo falló</b>", "<b>Something failed</b>", "<b>Algo falhou</b>"),
        t("Mirá " + C("vtoy_editor.log") + " al lado del " + C(".exe") + ". Tiene el error completo.",
          "Look at " + C("vtoy_editor.log") + " next to the " + C(".exe") + ". It has the full error.",
          "Veja o " + C("vtoy_editor.log") + " ao lado do " + C(".exe") + ". Ele tem o erro completo.")]],
      [0.33, 0.67])

    # ================================================================ 12
    H1(t("Atajos de teclado", "Keyboard shortcuts", "Atalhos de teclado"), "c_keys")
    T([t("Tecla", "Key", "Tecla"), t("Acción", "Action", "Ação")],
      [[K("Alt"), t("Vuelo libre sí / no", "Free flight on / off", "Voo livre sim / não")],
       [K("Esc"), t("Volver al modo edición · cancelar una copia o la prueba de caminar",
                    "Back to edit mode · cancel a copy or the walk test",
                    "Voltar ao modo edição · cancelar uma cópia ou o teste de caminhada")],
       [K("W") + K("A") + K("S") + K("D") + ", " + K("Shift"), t("Moverse, más rápido", "Move, faster", "Mover-se, mais rápido")],
       [K(KEY_SPACE) + " / " + K("E"), t("Subir (vuelo libre)", "Up (free flight)", "Subir (voo livre)")],
       [K("Ctrl") + " / " + K("C"), t("Bajar (vuelo libre)", "Down (free flight)", "Descer (voo livre)")],
       [t("clic derecho (mantener)", "right click (hold)", "clique direito (segurar)"),
        t("Mirar alrededor en modo edición", "Look around in edit mode", "Olhar em volta no modo edição")],
       [K("1") + " … " + K("9"), t("Herramientas: Seleccionar, Mover, Rotar, Escalar, Pluma, Relleno, Medir, Colisión, Pintar caras",
                                   "Tools: Select, Move, Rotate, Scale, Pen, Fill, Measure, Collision, Paint faces",
                                   "Ferramentas: Selecionar, Mover, Girar, Escalar, Caneta, Preencher, Medir, Colisão, Pintar faces")],
       [K("G") + t(" + mouse / rueda", " + mouse / wheel", " + mouse / roda"),
        t("Mover lo seleccionado / subir y bajar", "Move the selection / raise and lower", "Mover a seleção / subir e descer")],
       [K("R") + t(" + mouse / rueda", " + mouse / wheel", " + mouse / roda"),
        t("Girar lo seleccionado / alabeo", "Rotate the selection / roll", "Girar a seleção / rolagem")],
       [K("T") + t(" + mouse / rueda", " + mouse / wheel", " + mouse / roda"),
        t("Escalar lo seleccionado", "Scale the selection", "Escalar a seleção")],
       [K("Ctrl") + t(" + rueda", " + wheel", " + roda"), t("Girar 5° (con ", "Turn 5° (with ", "Girar 5° (com ") + K("Shift") + ": 1°)"],
       [K("Q"), t("Copiar lo seleccionado o el grupo", "Copy the selection or the group", "Copiar a seleção ou o grupo")],
       [K(KEY_DEL), t("Borrar lo seleccionado", "Delete the selection", "Apagar a seleção")],
       [K("Ctrl") + t(" + clic · ", " + click · ", " + clique · ") + K("Shift") + t(" + arrastrar", " + drag", " + arrastar"),
        t("Agregar al grupo · seleccionar con un rectángulo", "Add to the group · select with a rectangle",
          "Adicionar ao grupo · selecionar com um retângulo")],
       [K("H") + " / " + K("Shift", "H"), t("Ocultar lo seleccionado / mostrar todo", "Hide the selection / show everything",
                                           "Ocultar a seleção / mostrar tudo")],
       [K("Ctrl", "Z") + " / " + K("Ctrl", "Y"), t("Deshacer / rehacer", "Undo / redo", "Desfazer / refazer")],
       [K("Ctrl", "P"), t("Buscador de comandos y atajos propios", "Command search and your own shortcuts",
                          "Busca de comandos e atalhos próprios")],
       [K("Backspace"), t("Pluma: sacar el último punto", "Pen: remove the last point", "Caneta: tirar o último ponto")],
       ["Alt + " + t("clic", "click", "clique"), t("Medir / Recorrido: sacar un punto", "Measure / Path: remove a point",
                                                   "Medir / Caminho: tirar um ponto")],
       [K("Shift") + t(" + clic", " + click", " + clique"),
        t("Relleno / Pintar caras: tomar la textura de una cara", "Fill / Paint faces: pick a face's texture",
          "Preencher / Pintar faces: pegar a textura de uma face")],
       [K("F1"), t("Mostrar / ocultar el cuadro de información", "Show / hide the info panel", "Mostrar / ocultar o quadro de informações")],
       [K("F11"), t("Pantalla completa", "Full screen", "Tela cheia")],
       [K("F12"), t("Captura de pantalla", "Screenshot", "Captura de tela")]],
      [0.34, 0.66])
    P(t("Cualquier comando puede tener tu propia tecla: " + M("Juego y archivos > Atajos y buscador de comandos (Ctrl+P)") + ".",
        "Any command can have your own key: " + M("Game & files > Shortcuts and command search (Ctrl+P)") + ".",
        "Qualquer comando pode ter sua própria tecla: " + M("Jogo e arquivos > Atalhos e busca de comandos (Ctrl+P)") + "."))

    # ================================================================ about
    S.append(PageBreak())
    S.append(ChapterHead(0, t("Acerca de este manual", "About this manual", "Sobre este manual"), "c_about", W))
    S.append(Spacer(1, 12))
    if os.path.isfile(ICON):
        from reportlab.platypus import Image as RLImage
        S.append(RLImage(ICON, 64, 64, hAlign="LEFT"))
        S.append(Spacer(1, 8))
    P(t(f"Manual de usuario de <b>VToyEditor Plus+ {version}</b>. El editor es de <b>Lahrenheit</b> y está basado en el "
        "VToyEditor de Patoke.",
        f"User manual of <b>VToyEditor Plus+ {version}</b>. The editor is made by <b>Lahrenheit</b>, based on Patoke's VToyEditor.",
        f"Manual do usuário do <b>VToyEditor Plus+ {version}</b>. O editor é de <b>Lahrenheit</b>, baseado no VToyEditor de Patoke."))
    P(t("Página del proyecto, descargas y versiones nuevas: ", "Project page, downloads and new versions: ",
        "Página do projeto, downloads e versões novas: ") +
      '<a href="https://github.com/Lahrenheit/VToyEditorPlus" color="#e4572e"><u>github.com/Lahrenheit/VToyEditorPlus</u></a>.')
    P(t("El manual está en español, inglés y portugués (" + C("docs/Manual_VToyEditorPlus_es.pdf") + ", " + C("_en") + ", " +
        C("_pt") + "). El detalle técnico de cada función y de cada cambio está en " + C("docs/CHANGELOG.md") + ".",
        "The manual comes in Spanish, English and Portuguese (" + C("docs/Manual_VToyEditorPlus_es.pdf") + ", " + C("_en") +
        ", " + C("_pt") + "). The technical detail of every function and change is in " + C("docs/CHANGELOG.md") + ".",
        "O manual está em espanhol, inglês e português (" + C("docs/Manual_VToyEditorPlus_es.pdf") + ", " + C("_en") + ", " +
        C("_pt") + "). O detalhe técnico de cada função e de cada mudança está em " + C("docs/CHANGELOG.md") + "."))
    P(t("El manual se genera con " + C("python tools/make_manual.py") + ": al cambiar el editor, se vuelve a armar con la "
        "versión nueva.",
        "The manual is generated with " + C("python tools/make_manual.py") + ": when the editor changes, it is rebuilt with "
        "the new version.",
        "O manual é gerado com " + C("python tools/make_manual.py") + ": quando o editor muda, ele é refeito com a versão nova."))
    P(t("Torrente Online y Torrente, el juego son de Virtual Toys; Counter-Strike y Half-Life, de Valve. Este programa no está "
        "relacionado con ellos.",
        "Torrente Online and Torrente, el juego belong to Virtual Toys; Counter-Strike and Half-Life to Valve. This program "
        "is not affiliated with them.",
        "Torrente Online e Torrente, el juego são da Virtual Toys; Counter-Strike e Half-Life, da Valve. Este programa não "
        "tem relação com eles."), "cap")
    return S


def build(out: str, lang: str = "es") -> str:
    setup_fonts()
    _lang[0] = LANGS.index(lang)
    src = open(os.path.join(ROOT, "vtoy", "__init__.py"), encoding="utf-8").read()
    version = re.search(r'^APP_REV\s*=\s*"([^"]*)"', src, re.M).group(1)
    st = styles()
    doc = ManualDoc(out, version)
    W = doc.width
    story = content(st, W, version)
    doc.multiBuild(story, maxPasses=6)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in LANGS:
        out = args[1] if len(args) > 1 else manual_path(args[0])
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        print(build(out, args[0]))
    else:
        for lg in LANGS:
            p = manual_path(lg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            print(build(p, lg))
