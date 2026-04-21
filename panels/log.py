# panels/log.py
import time
import dearpygui.dearpygui as dpg
import utils.ui_queue as ui_queue

_MAX_LINES   = 500
_TAG_TEXT    = "log_text"
_TAG_SEARCH  = "log_search"
_TAG_FOUND   = "log_found"
_auto_scroll = True
_lines: list[str] = []   # 표시용 plain text
_search_kw   = ""


def build(parent) -> None:
    with dpg.group(parent=parent):
        with dpg.group(horizontal=True):
            dpg.add_checkbox(
                label="Auto Scroll",
                default_value=True,
                callback=lambda s, v: _set_auto_scroll(v),
            )
            dpg.add_button(label="Go to End", callback=_go_to_end)
            dpg.add_button(label="Clear",     callback=_clear)
            dpg.add_spacer(width=8)
            dpg.add_text("Search:")
            dpg.add_input_text(
                tag=_TAG_SEARCH,
                width=160,
                hint="keyword  (Enter)",
                on_enter=True,
                callback=lambda s, v: _on_search(v),
            )
            dpg.add_button(label="Find",
                           callback=lambda: _on_search(dpg.get_value(_TAG_SEARCH)))
            dpg.add_text("", tag=_TAG_FOUND, color=(180, 180, 100, 255))

        dpg.add_input_text(
            tag=_TAG_TEXT,
            multiline=True,
            readonly=True,
            width=-1,
            height=-1,
        )


def append(msg: str, level: str = "INFO") -> None:
    ts   = time.strftime("%H:%M:%S")
    text = f"[{ts}][{level}] {msg}"
    ui_queue.post(lambda t=text: _add_line(t))


def _add_line(text: str) -> None:
    if not dpg.does_item_exist(_TAG_TEXT):
        return

    _lines.append(text)
    if len(_lines) > _MAX_LINES:
        _lines.pop(0)
        _rebuild_view()
        return

    if _search_kw and _search_kw.lower() not in text.lower():
        return

    current = dpg.get_value(_TAG_TEXT)
    dpg.set_value(_TAG_TEXT, (current + "\n" + text) if current else text)

    # mvInputText은 set_y_scroll을 지원하지 않음 — 자동 스크롤 미지원


def _go_to_end() -> None:
    pass  # mvInputText은 set_y_scroll 미지원


def _on_search(keyword: str) -> None:
    global _search_kw
    _search_kw = keyword.strip()
    _rebuild_view()


def _rebuild_view() -> None:
    if not dpg.does_item_exist(_TAG_TEXT):
        return

    if _search_kw:
        matched = [t for t in _lines if _search_kw.lower() in t.lower()]
        dpg.set_value(_TAG_TEXT, "\n".join(matched))
        dpg.set_value(_TAG_FOUND, f"{len(matched)} match(es)")
    else:
        dpg.set_value(_TAG_TEXT, "\n".join(_lines))
        dpg.set_value(_TAG_FOUND, "")

    _go_to_end()


def _clear() -> None:
    _lines.clear()
    if dpg.does_item_exist(_TAG_TEXT):
        dpg.set_value(_TAG_TEXT, "")
    if dpg.does_item_exist(_TAG_FOUND):
        dpg.set_value(_TAG_FOUND, "")


def _set_auto_scroll(val: bool) -> None:
    global _auto_scroll
    _auto_scroll = val


def _level_color(level: str) -> tuple:
    return {
        "SEND":  (100, 200, 255, 255),
        "RECV":  (100, 255, 150, 255),
        "WARN":  (255, 220,  50, 255),
        "ERROR": (255,  80,  80, 255),
        "AUTO":  (200, 150, 255, 255),
    }.get(level, (220, 220, 220, 255))
