"""Which model (.nfo) is used by which kind of module, learned from the scenes that already exist.

The scene format does not say which models a module type accepts; the only way to know is to look at how the game's
own scenes use them. ``build()`` reads every scene given and counts, per module kind, the models it points to."""
from __future__ import annotations

import os
import struct
from collections import defaultdict
from typing import Dict, Iterable, Optional

from .scn import Scene

# the old game calls some modules without the "mp_" prefix
ALIASES = {"ccar": "mp_ccar", "salud": "mp_salud", "cosa": "mp_cosa", "door": "mp_door", "flag": "mp_flag"}


def norm_model(name: str) -> str:
    n = str(name).replace("\\", "/").strip("\0 ")
    return n if n.lower().startswith("nfos/") else "nfos/" + n.split("/")[-1]


def model_of(rec) -> Optional[str]:
    """Model name stored at the start of a module (typed or raw), or None if the module has no model."""
    p = getattr(rec, "parsed", None)
    if p is not None and getattr(p, "model_name", ""):
        n = str(p.model_name)
    else:
        d = rec.data
        if len(d) < 8:
            return None
        L = struct.unpack_from("<I", d, 0)[0]
        if not 5 < L < 200 or 4 + L > len(d):
            return None
        n = d[4:4 + L].split(b"\0", 1)[0].decode("cp1252", "replace")
    return n if n.lower().endswith(".nfo") else None


def kind_of(rec) -> str:
    k = rec.clean_name.lower()
    return ALIASES.get(k, k)


def build(scenes: Iterable[Scene]) -> Dict[str, Dict[str, int]]:
    """{module kind (lower case) -> {'nfos/Model.NFO' -> number of uses}}"""
    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    seen_case: Dict[str, str] = {}
    for sc in scenes:
        for rec in sc.modules:
            m = model_of(rec)
            if not m:
                continue
            m = norm_model(m)
            m = seen_case.setdefault(m.lower(), m)
            d = out[kind_of(rec)]
            d[m] = d.get(m, 0) + 1
    return dict(out)


def load_scenes(folder: Optional[str]) -> Iterable[Scene]:
    if folder and os.path.isdir(folder):
        for dp, _, fn in os.walk(folder):
            for f in sorted(fn):
                if f.lower().endswith(".scn"):
                    try:
                        yield Scene.load(os.path.join(dp, f))
                    except Exception:
                        pass
