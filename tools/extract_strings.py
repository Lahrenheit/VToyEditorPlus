"""List the user-visible texts of the editor (the keys of vtoy/language/*.py).

Every string handed to an imgui / ui call, to ``wrapped``, ``tr`` or ``.log`` becomes a key; an f-string becomes a template with
``{0}``, ``{1}`` ... for its dynamic parts.  Run:   python tools/extract_strings.py            (prints the keys)
                                                   python tools/extract_strings.py --check   (what es.py / pt.py lack)"""
from __future__ import annotations

import ast
import glob
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SHOW = {"imgui", "ui"}            # modules whose calls display text
FUNCS = {"wrapped", "tr", "log", "toast", "set_tooltip", "_header", "SystemExit", "exit", "add_argument", "askopenfilename", "askdirectory", "add_text"}
FILES = ["vtoy/app/*.py", "vtoy/gamemode.py", "vtoy/convert.py", "vtoy/importer.py", "vtoy/crop.py", "vtoy/dllpatch.py"]
SKIP = ("--", "%Y", "*.", "python", "VToyEditor log", "__", "[_", ".wav", "glfw.", "could not create an OpenGL", " | python ")


def template(node: ast.JoinedStr) -> str:
    out, n = [], 0
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        else:
            out.append("{%d}" % n); n += 1
    return "".join(out)


def strings_in(node, found):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        found.append(node.value)
    elif isinstance(node, ast.JoinedStr):
        found.append(template(node))
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            strings_in(e, found)
    elif isinstance(node, ast.IfExp):
        strings_in(node.body, found); strings_in(node.orelse, found)
    elif isinstance(node, ast.BinOp):
        strings_in(node.left, found); strings_in(node.right, found)
    elif isinstance(node, ast.Dict):
        for e in node.values:
            strings_in(e, found)


def keep(s: str) -> bool:
    core = s.split("##")[0]
    return len(core.strip()) >= 2 and any(c.isalpha() for c in core) and not core.startswith(("%", "mp_", "nfos"))


def extract() -> list:
    keys = {}
    for pat in FILES:
      for path in sorted(glob.glob(os.path.join(ROOT, pat))):
        tree = ast.parse(open(path, encoding="utf-8").read())
        docs = set()
        for n in ast.walk(tree):                      # the pieces of an f-string are not texts of their own
            if isinstance(n, ast.JoinedStr):
                docs.update(id(v) for v in n.values)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Module)) and n.body and isinstance(n.body[0], ast.Expr) \
                    and isinstance(getattr(n.body[0], "value", None), ast.Constant):
                docs.add(id(n.body[0].value))
        for node in ast.walk(tree):
            # every other readable sentence / label of the program (shown through variables, lists, return values)
            s_ = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                s_ = node.value
            elif isinstance(node, ast.JoinedStr):
                s_ = template(node)
            if s_ and " " in s_.strip() and len(s_) >= 6 and "\n" not in s_ and not s_.startswith(SKIP) \
                    and not any(k in s_ for k in SKIP) and any(c.isalpha() for c in s_) and keep(s_.split("##")[0]):
                keys.setdefault(s_.split("##")[0], os.path.basename(path))
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
            if owner in SHOW or name in FUNCS:
                found = []
                for a in node.args:
                    strings_in(a, found)
                for s in found:
                    s = s.split("##")[0]
                    if keep(s):
                        keys.setdefault(s, os.path.basename(path))
    return sorted(keys)


if __name__ == "__main__":
    ks = extract()
    if "--check" in sys.argv:
        sys.path.insert(0, ROOT)
        from vtoy import language
        for code in language.codes():
            miss = [k for k in ks if k not in language.table(code)]
            print(code, "missing", len(miss))
            for k in miss:
                print("   ", repr(k))
    else:
        print(len(ks), "texts")
        for k in ks:
            print(repr(k))
