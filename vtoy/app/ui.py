"""Adapter over imgui-bundle so the editor does not care about return-type differences between versions."""
from __future__ import annotations

from typing import List, Sequence, Tuple

from imgui_bundle import imgui


def _tup(r, default):
    """Normalise ``(changed, value)`` / bare-bool / bare-value returns."""
    if isinstance(r, tuple) and len(r) == 2:
        return bool(r[0]), r[1]
    return False, default


def begin(title: str, opened: bool = True, flags: int = 0) -> Tuple[bool, bool]:
    r = imgui.begin(title, True if opened else None, flags) if opened is not None else imgui.begin(title, None, flags)
    if isinstance(r, tuple):
        return bool(r[0]), bool(r[1])
    return bool(r), True


end = imgui.end


def button(label: str) -> bool:
    return bool(imgui.button(label))


def text(s: str) -> None:
    imgui.text(s)


def checkbox(label: str, v: bool) -> Tuple[bool, bool]:
    return _tup(imgui.checkbox(label, v), v)


def input_text(label: str, v: str) -> Tuple[bool, str]:
    return _tup(imgui.input_text(label, v), v)


def drag_float(label: str, v: float, speed: float = 1.0, lo: float = 0.0, hi: float = 0.0) -> Tuple[bool, float]:
    return _tup(imgui.drag_float(label, float(v), speed, lo, hi), v)


def drag_float3(label: str, v: Sequence[float], speed: float = 1.0, axes: str = "XYZ") -> Tuple[bool, List[float]]:
    """Three drag fields in a row, each one labelled with its axis (X / Y / Z) inside the field."""
    vv = [float(x) for x in v]
    try:
        total = float(imgui.calc_item_width())
        gap = float(imgui.get_style().item_inner_spacing.x)
        w = max(40.0, (total - 2 * gap) / 3.0)
        changed = False
        for i in range(3):
            if i:
                imgui.same_line(0.0, gap)
            imgui.push_item_width(w)
            ch, nv = _tup(imgui.drag_float(f"##{label}{i}", vv[i], speed, 0.0, 0.0, f"{axes[i]}  %.2f"), vv[i])
            imgui.pop_item_width()
            if ch:
                vv[i], changed = float(nv), True
        imgui.same_line(0.0, gap)
        imgui.text(label.split("##")[0])
        return changed, vv
    except (AttributeError, TypeError):
        try:
            ch, nv = _tup(imgui.drag_float3(label, vv, speed), vv)
        except TypeError:                 # older bindings: drag_float3(label, x, y, z)
            r = imgui.drag_float3(label, *vv, speed)
            ch, nv = bool(r[0]), list(r[1:])
        return ch, [float(x) for x in nv]


def slider_float(label: str, v: float, lo: float, hi: float) -> Tuple[bool, float]:
    return _tup(imgui.slider_float(label, float(v), lo, hi), v)


def input_int(label: str, v: int) -> Tuple[bool, int]:
    return _tup(imgui.input_int(label, int(v)), v)


def color_edit3(label: str, rgb: Sequence[float]) -> Tuple[bool, List[float]]:
    vv = [float(x) for x in rgb]
    ch, nv = _tup(imgui.color_edit3(label, vv), vv)
    return ch, [float(x) for x in nv]


def combo(label: str, idx: int, items: Sequence[str]) -> Tuple[bool, int]:
    return _tup(imgui.combo(label, int(idx), list(items)), idx)


def selectable(label: str, selected: bool) -> bool:
    r = imgui.selectable(label, selected)
    return bool(r[0] if isinstance(r, tuple) else r)


def want_capture_mouse() -> bool:
    return bool(imgui.get_io().want_capture_mouse)


def want_capture_keyboard() -> bool:
    return bool(imgui.get_io().want_capture_keyboard)
