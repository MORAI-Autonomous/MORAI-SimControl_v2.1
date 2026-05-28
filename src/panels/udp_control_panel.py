from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional

import dearpygui.dearpygui as dpg

import panels.log as log
import transport.protocol_defs as proto
from receivers.template_parser import TemplateParser, FieldDef
from panels.monitor_utils import get_control_templates
from utils.project_paths import ROOT_DIR
from utils.template_paths import resolve_template_path

_BASE_DIR = str(ROOT_DIR)
_STATE_FILE = os.path.join(_BASE_DIR, "config", "udp_control_state.json")

_send_fn: Optional[Callable] = None
_current_template: str = ""
_current_parser: Optional[TemplateParser] = None
_field_tags: Dict[str, int] = {}
_state_cache: Dict[str, object] = {
    "selected_template": "",
    "templates": {},
}


def _save_state_cb(sender=None, app_data=None, user_data=None) -> None:
    _save_state()


def init(send_udp_control_fn: Callable) -> None:
    global _send_fn
    _send_fn = send_udp_control_fn


def build(parent) -> None:
    with dpg.group(parent=parent):
        _section("UDP CONTROL")

        with dpg.group(horizontal=True):
            dpg.add_text("Template  :", color=(180, 180, 180, 255))
            dpg.add_combo(
                tag="udp_ctrl_template",
                items=get_control_templates(),
                width=260,
                callback=_on_template_change,
            )
            dpg.add_button(label="Refresh", callback=_on_refresh)

        with dpg.group(horizontal=True):
            dpg.add_text("IP        :", color=(180, 180, 180, 255))
            dpg.add_input_text(
                tag="udp_ctrl_ip",
                default_value=proto.UDP_IP,
                width=140,
                callback=_save_state_cb,
            )
            dpg.add_text("Port      :", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag="udp_ctrl_port",
                default_value=proto.UDP_PORT,
                width=100,
                min_value=1,
                max_value=65535,
                step=0,
                callback=_save_state_cb,
            )
            dpg.add_button(label="Send", callback=_on_send)

        dpg.add_separator()
        dpg.add_group(tag="udp_ctrl_fields")
        dpg.add_spacer(height=6)
        dpg.add_text("Status", color=(180, 180, 180, 255))
        dpg.add_text("Select a control template.", tag="udp_ctrl_status",
                     color=(140, 140, 140, 255))

        _load_state()

        templates = get_control_templates()
        if templates:
            selected = str(_state_cache.get("selected_template", ""))
            chosen = selected if selected in templates else templates[0]
            dpg.set_value("udp_ctrl_template", chosen)
            _load_template(chosen)


def _on_refresh(sender=None, app_data=None, user_data=None) -> None:
    templates = get_control_templates()
    current = dpg.get_value("udp_ctrl_template") if dpg.does_item_exist("udp_ctrl_template") else ""
    dpg.configure_item("udp_ctrl_template", items=templates)
    if current in templates:
        dpg.set_value("udp_ctrl_template", current)
        _load_template(current)
    elif templates:
        dpg.set_value("udp_ctrl_template", templates[0])
        _load_template(templates[0])
    else:
        _clear_template()


def _on_template_change(sender, app_data, user_data=None) -> None:
    if isinstance(app_data, str) and app_data:
        _load_template(app_data)


def _load_template(filename: str) -> None:
    global _current_template, _current_parser, _field_tags
    path = resolve_template_path(filename)
    if path is None:
        _clear_template()
        return

    try:
        parser = TemplateParser(path)
    except Exception as e:
        log.append(f"[UDP CTRL] template load error: {e}", "ERROR")
        _clear_template()
        return

    _current_template = filename
    _current_parser = parser
    _field_tags = {}
    _state_cache["selected_template"] = filename

    dpg.delete_item("udp_ctrl_fields", children_only=True)

    template_state = _template_state(filename)
    dpg.set_value("udp_ctrl_ip", str(template_state.get("ip", _default_ip(filename))))
    dpg.set_value("udp_ctrl_port", int(template_state.get("port", _default_port(filename))))

    seg = parser.fields_segment
    if seg is None:
        dpg.set_value("udp_ctrl_status", f"{filename}: no fields")
        return

    for field in seg.fields:
        row_tag = _add_field_input(field)
        _field_tags[field.variable_name] = row_tag
        saved_value = template_state.get("values", {}).get(field.variable_name)
        if saved_value is not None and dpg.does_item_exist(row_tag):
            dpg.set_value(row_tag, saved_value)

    dpg.set_value("udp_ctrl_status", f"Loaded {filename} ({len(seg.fields)} fields)")
    _save_state()


def _clear_template() -> None:
    global _current_template, _current_parser, _field_tags
    _current_template = ""
    _current_parser = None
    _field_tags = {}
    dpg.delete_item("udp_ctrl_fields", children_only=True)
    if dpg.does_item_exist("udp_ctrl_status"):
        dpg.set_value("udp_ctrl_status", "No control template available.")


def _add_field_input(field: FieldDef) -> int:
    label = field.variable_name
    if field.var_type in ("FLOAT", "DOUBLE"):
        with dpg.group(horizontal=True, parent="udp_ctrl_fields"):
            dpg.add_text(f"{label} :", color=(180, 180, 180, 255))
            return dpg.add_input_float(
                width=180,
                step=0.0,
                default_value=0.0,
                callback=_save_state_cb,
            )
    if field.var_type in ("INT32", "INT64", "UINT32", "ENUM"):
        with dpg.group(horizontal=True, parent="udp_ctrl_fields"):
            dpg.add_text(f"{label} :", color=(180, 180, 180, 255))
            return dpg.add_input_int(
                width=180,
                step=0,
                default_value=0,
                callback=_save_state_cb,
            )
    if field.var_type == "STRING":
        with dpg.group(horizontal=True, parent="udp_ctrl_fields"):
            dpg.add_text(f"{label} :", color=(180, 180, 180, 255))
            return dpg.add_input_text(
                width=260,
                default_value="",
                callback=_save_state_cb,
            )

    with dpg.group(horizontal=True, parent="udp_ctrl_fields"):
        dpg.add_text(f"{label} :", color=(180, 180, 180, 255))
        return dpg.add_input_text(
            width=260,
            default_value="",
            callback=_save_state_cb,
        )


def _collect_values() -> Dict[str, object]:
    values: Dict[str, object] = {}
    if _current_parser is None or _current_parser.fields_segment is None:
        return values
    for field in _current_parser.fields_segment.fields:
        tag = _field_tags.get(field.variable_name)
        if tag and dpg.does_item_exist(tag):
            values[field.variable_name] = dpg.get_value(tag)
    return values


def _on_send(sender=None, app_data=None, user_data=None) -> None:
    if _send_fn is None:
        log.append("[UDP CTRL] panel not initialized", "ERROR")
        return
    if _current_parser is None or _current_parser.fields_segment is None:
        log.append("[UDP CTRL] no control template selected", "WARN")
        return

    ip = dpg.get_value("udp_ctrl_ip").strip() or "127.0.0.1"
    port = int(dpg.get_value("udp_ctrl_port"))
    values = _collect_values()

    try:
        _send_fn(
            template_name=_current_template,
            parser=_current_parser,
            ip=ip,
            port=port,
            values=values,
        )
        payload_size = _estimate_payload_size(values)
        dpg.set_value(
            "udp_ctrl_status",
            f"Sent {_current_template} -> {ip}:{port} ({payload_size}B)",
        )
        _save_state()
    except Exception as e:
        log.append(f"[UDP CTRL] send error: {e}", "ERROR")
        dpg.set_value("udp_ctrl_status", f"Send failed: {e}")


def _default_ip(filename: str) -> str:
    if filename == "TransformControl.tmpl":
        return proto.UDP_IP_TR
    return proto.UDP_IP


def _default_port(filename: str) -> int:
    if filename == "TransformControl.tmpl":
        return proto.UDP_PORT_TR
    return proto.UDP_PORT


def _estimate_payload_size(values: Dict[str, object]) -> int:
    if _current_parser is None or _current_parser.fields_segment is None:
        return 0
    size = 0
    for field in _current_parser.fields_segment.fields:
        if field.is_string:
            size += field.length
        else:
            size += field.byte_size
    return size


def _template_state(filename: str) -> Dict[str, object]:
    templates = _state_cache.setdefault("templates", {})
    if not isinstance(templates, dict):
        templates = {}
        _state_cache["templates"] = templates
    state = templates.get(filename)
    if not isinstance(state, dict):
        state = {}
        templates[filename] = state
    return state


def _save_state() -> None:
    if _current_template:
        template_state = _template_state(_current_template)
        if dpg.does_item_exist("udp_ctrl_ip"):
            template_state["ip"] = dpg.get_value("udp_ctrl_ip")
        if dpg.does_item_exist("udp_ctrl_port"):
            template_state["port"] = int(dpg.get_value("udp_ctrl_port"))
        template_state["values"] = _collect_values()
        _state_cache["selected_template"] = _current_template

    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(_state_cache, fp, indent=2, ensure_ascii=False)
    except Exception as e:
        log.append(f"[UDP CTRL] save state error: {e}", "ERROR")


def _load_state() -> None:
    global _state_cache
    if not os.path.isfile(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fp:
            loaded = json.load(fp)
    except Exception as e:
        log.append(f"[UDP CTRL] load state error: {e}", "ERROR")
        return
    if isinstance(loaded, dict):
        _state_cache = loaded


def _section(title: str) -> None:
    dpg.add_text(title, color=(220, 220, 80, 255))
    dpg.add_separator()
