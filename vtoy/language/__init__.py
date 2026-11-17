"""Languages of the editor.

Every language is ONE file in this folder (``en.py``, ``es.py``, ``pt.py`` ...) with two variables:

    NAME = "Español"            # what the Language menu shows
    TEXT = {"File": "Archivo", ...}   # English text -> text in this language

The English text is the key, so a text that is missing from a language simply shows in English.  To add a language copy
``en.py`` to ``<code>.py`` (e.g. ``fr.py``), set ``NAME`` and translate the right-hand side of ``TEXT``; it appears in the
Language menu by itself (no code to change).  The same works for a ``language`` folder placed next to the .exe.

A text with ``{0}``, ``{1}`` ... is a template: the editor fills these with numbers / names (keep them in the translation, you may
reorder them).  Everything after ``##`` in a label is an internal id and is never translated.

``tools/extract_strings.py --check`` lists the texts a language still lacks.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from typing import Dict, List

_TABLES: Dict[str, Dict[str, str]] = {}
_NAMES: Dict[str, str] = {}
_current = "en"
_cur_table: Dict[str, str] = {}
_cur_templates: List = []          # (compiled regex, translated template) for texts with {0} {1} ...
_cur_fragments: List = []          # (text, translation) for pieces of messages built by concatenation
_cur_tails: List = []              # (compiled regex, translation) for the endings messages are built with
_cache: Dict[str, str] = {}
_loaded = False


def _folders() -> List[str]:
    out = [os.path.dirname(os.path.abspath(__file__))]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        out.append(os.path.join(base, "vtoy", "language"))
    exe = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    out.append(os.path.join(exe, "language"))          # a folder next to the program: add languages without rebuilding
    return out


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for folder in _folders():
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            code = fn[:-3]
            try:
                spec = importlib.util.spec_from_file_location("vtoy_lang_" + code, os.path.join(folder, fn))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _TABLES[code] = dict(getattr(mod, "TEXT", {}))
                _NAMES[code] = str(getattr(mod, "NAME", code))
            except Exception as e:                      # a broken translation file must never stop the editor
                print(f"language {fn}: {e!r}")
    if "en" not in _TABLES:
        _TABLES["en"], _NAMES["en"] = {}, "English"


def codes() -> List[str]:
    _load()
    return sorted(_TABLES, key=lambda c: (c != "en", c))


def name(code: str) -> str:
    _load()
    return _NAMES.get(code, code)


def table(code: str) -> Dict[str, str]:
    _load()
    return _TABLES.get(code, {})


def current() -> str:
    return _current


def _build(t: Dict[str, str]) -> None:
    global _cur_table, _cur_templates, _cur_fragments
    _cur_table = {k: v for k, v in t.items() if v and v != k}
    _cur_templates, _cur_fragments = [], []
    for k, v in _cur_table.items():
        if re.search(r"\{\d+\}", k):
            pat = "".join("(.*?)" if re.fullmatch(r"\{\d+\}", part) else re.escape(part)
                          for part in re.split(r"(\{\d+\})", k) if part)
            _cur_templates.append((re.compile("^" + pat + "$", re.S), k, v))
        if k != k.strip() or k.endswith(":") or len(k) >= 10 and not re.search(r"\{\d+\}", k):
            _cur_fragments.append((k, v))
    _cur_fragments.sort(key=lambda kv: -len(kv[0]))      # longest first
    # tails that messages are built with (" - save the map", ", 2 collision boxes"): translated on their own
    _cur_tails.clear()
    for k, v in sorted(_cur_table.items(), key=lambda kv: -len(kv[0])):
        if k[:1] in " ,;" and len(k) >= 5 and k.strip():
            pat = "".join("(.*?)" if re.fullmatch(r"\{\d+\}", part) else re.escape(part)
                          for part in re.split(r"(\{\d+\})", k) if part)
            _cur_tails.append((re.compile("^(.+)" + pat + "$", re.S), v))
    _cache.clear()


def set_language(code: str) -> str:
    global _current
    _load()
    if code not in _TABLES:
        code = "en"
    _current = code
    _build(_TABLES[code])
    return code


def _fill(template: str, groups) -> str:
    groups = [_cur_table.get(g, g) for g in groups]            # a piece that is itself a known text (e.g. an undo label)
    return re.sub(r"\{(\d+)\}", lambda m: groups[int(m.group(1))] if int(m.group(1)) < len(groups) else m.group(0), template)


def _translate(s: str) -> str:
    v = _cur_table.get(s)
    if v is not None:
        return v
    for rx, val in _cur_tails:
        m = rx.match(s)
        if m:
            return _translate(m.group(1)) + _fill(val, m.groups()[1:])
    for rx, key, val in _cur_templates:
        m = rx.match(s)
        if m:
            return _fill(val, m.groups())
    out = s                                   # messages built from pieces: translate the pieces that are known texts
    for k, val in _cur_fragments:
        if k in out and not re.search(r"\{\d+\}", k):
            out = out.replace(k, val)
    return out


def tr(text):
    """Text in the current language (English when it has no translation). Safe to call with anything."""
    if not _cur_table or not isinstance(text, str) or not text:
        return text
    head, sep, tail = text.partition("##")
    r = _cache.get(head)
    if r is None:
        r = _translate(head)
        if len(_cache) > 6000:
            _cache.clear()
        _cache[head] = r
    return r + sep + tail


# ----------------------------------------------------------------------------------------------- imgui hook
# imgui function -> positions of the arguments that are texts (a list argument = every item is a text)
_SPEC = {
    "button": (0,), "small_button": (0,), "text": (0,), "text_wrapped": (0,), "text_disabled": (0,), "text_unformatted": (0,),
    "text_colored": (1,), "bullet_text": (0,), "checkbox": (0,), "radio_button": (0,), "begin_menu": (0,), "menu_item": (0,),
    "collapsing_header": (0,), "tree_node": (0,), "tree_node_ex": (0,), "selectable": (0,), "input_text": (0,),
    "input_int": (0,), "input_float": (0,), "drag_float": (0,), "slider_float": (0,), "color_edit3": (0,), "color_edit4": (0,),
    "combo": (0, 2), "begin_combo": (0, 1), "begin": (0,), "begin_popup": (0,), "begin_popup_modal": (0,), "open_popup": (0,),
    "set_tooltip": (0,), "separator_text": (0,), "begin_child": (), "text_link": (0,),
}


def install(imgui) -> None:
    """Make every text that reaches Dear ImGui go through ``tr``. Called once; switching language needs no restart."""
    if getattr(imgui, "_vtoy_tr_installed", False):
        return
    for fname, pos in _SPEC.items():
        orig = getattr(imgui, fname, None)
        if orig is None or not pos:
            continue

        def make(orig, pos):
            def wrapper(*a, **k):
                if _cur_table:
                    a = list(a)
                    for i in pos:
                        if i < len(a):
                            x = a[i]
                            if isinstance(x, str):
                                a[i] = tr(x)
                            elif isinstance(x, (list, tuple)) and x and all(isinstance(y, str) for y in x):
                                a[i] = [tr(y) for y in x]
                return orig(*a, **k)
            return wrapper
        setattr(imgui, fname, make(orig, pos))
    imgui._vtoy_tr_installed = True
