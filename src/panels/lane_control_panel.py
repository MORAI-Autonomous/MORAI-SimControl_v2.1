# panels/lane_control_panel.py
#
# Lane Control 전용 탭 패널
# - 제어 / 파라미터 설정
# - Debug Frame (원본+BEV+binary+조향게이지 합성 1280×480 → 640×240 표시)
# - Vehicle Info 실시간 수치
# - 튜닝 슬라이더 (Kp, Kd, EMA, Steer Rate, Offset Clip, Target Speed)
from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Optional

import numpy as np
import cv2
import dearpygui.dearpygui as dpg

import utils.ui_queue as ui_queue
import panels.log as log
from lane_control.run_analyzer import analyze_latest_run
from utils.project_paths import ROOT_DIR


_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "lane_control_panel_state.json")

# ── 튜닝 기본값 (Reset 버튼용) ───────────────────────────────────
_TUNING_DEFAULTS = {
    "lc_kp":           0.50,
    "lc_kd":           0.10,
    "lc_ema":          0.30,
    "lc_steer_rate":   0.15,
    "lc_offset_clip":  1.50,
    "lc_tune_speed":   15.0,
    "lc_bev_top_crop": 80,
    "lc_min_blob":     50,
    "lc_shadow_filter": 0,
    "lc_preprocess_mode": "legacy",
    "lc_search_ratio": 0.50,
    "lc_min_pixels":   30,
}

_NEXT_TEST_PARAMS = {
    "lc_target_kmh":    15.0,
    "lc_tune_speed":    15.0,
    "lc_kp":            0.65,
    "lc_steer_rate":    0.20,
    "lc_shadow_filter": 20,
    "lc_search_ratio":  0.70,
    "lc_min_pixels":    15,
}

# ── 카메라/디버그 텍스처 해상도 ─────────────────────────────────
# 디버그 합성 1280×480 → 0.5× → 640×240 (AR 완전 보존)
_CAM_W = 640
_CAM_H = 240
_CAM_BLANK: list = [0.0] * (_CAM_W * _CAM_H * 4)

# ── 프레임 표시 제어 ─────────────────────────────────────────────
_FRAME_INTERVAL   = 1.0 / 30.0   # 최대 30fps
_last_frame_t     = 0.0
_suppress_raw_until = 0.0         # debug frame 수신 후 raw 억제 기간

# ── 모듈 상태 ────────────────────────────────────────────────────
_start_fn:  Optional[Callable] = None
_stop_fn:   Optional[Callable] = None
_scenario_control_fn: Optional[Callable] = None
_auto_thread: Optional[threading.Thread] = None
_auto_stop_event = threading.Event()
_auto_iteration = 0
_runner = None   # LaneRunner 참조 (start 후 set_runner() 로 주입)


def init(
    start_lc_fn: Callable,
    stop_lc_fn: Callable,
    scenario_control_fn: Optional[Callable] = None,
) -> None:
    global _start_fn, _stop_fn, _scenario_control_fn
    _start_fn = start_lc_fn
    _stop_fn  = stop_lc_fn
    _scenario_control_fn = scenario_control_fn


def set_runner(runner) -> None:
    """app.py가 LaneRunner 생성/소멸 시 호출."""
    global _runner
    _runner = runner


# ── UI 빌드 ──────────────────────────────────────────────────────
def build(parent: int | str) -> None:
    with dpg.texture_registry():
        dpg.add_dynamic_texture(
            width=_CAM_W, height=_CAM_H,
            default_value=_CAM_BLANK,
            tag="lc_cam_texture",
        )

    with dpg.child_window(parent=parent, width=-1, height=-1, border=False):

        # ── CONTROL ────────────────────────────────────────────
        _section("CONTROL")
        with dpg.group(horizontal=True):
            dpg.add_button(label="▶ Start", tag="lc_btn_start",
                           width=90, callback=_on_start)
            dpg.add_button(label="■ Stop",  tag="lc_btn_stop",
                           width=90, callback=_on_stop)
            dpg.add_spacer(width=8)
            dpg.add_checkbox(tag="lc_record_run", label="Record Run", default_value=False)
            dpg.add_spacer(width=8)
            dpg.add_text("○ Stopped", tag="lc_status", color=(180, 80, 80, 255))

        with dpg.group(horizontal=True):
            dpg.add_button(label="Auto Cycle Start", tag="lc_auto_start",
                           width=130, callback=_on_auto_cycle_start)
            dpg.add_button(label="Auto Cycle Stop", tag="lc_auto_stop",
                           width=130, callback=_on_auto_cycle_stop)
            dpg.add_spacer(width=8)
            dpg.add_text("Auto Idle", tag="lc_auto_status", color=(150, 150, 150, 255))

        with dpg.group(horizontal=True):
            dpg.add_text("Iter :", color=(180, 180, 180, 255))
            dpg.add_input_int(tag="lc_auto_iters", default_value=5,
                              min_value=1, max_value=100, step=0, width=50,
                              callback=_save_state_cb)
            dpg.add_text("Max Sec :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_max_sec", default_value=90.0,
                                min_value=5.0, max_value=300.0,
                                format="%.1f", step=0, width=60,
                                callback=_save_state_cb)
            dpg.add_text("No Launch :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_no_launch_sec", default_value=4.0,
                                min_value=1.0, max_value=30.0,
                                format="%.1f", step=0, width=55,
                                callback=_save_state_cb)
            dpg.add_text("Stuck :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_stuck_sec", default_value=3.0,
                                min_value=1.0, max_value=30.0,
                                format="%.1f", step=0, width=55,
                                callback=_save_state_cb)
            dpg.add_text("Lost :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_lost_sec", default_value=3.0,
                                min_value=1.0, max_value=30.0,
                                format="%.1f", step=0, width=55,
                                callback=_save_state_cb)

        with dpg.group(horizontal=True):
            dpg.add_text("Scenario :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="lc_auto_scenario_name", default_value="",
                               width=160, hint="blank = Commands name",
                               callback=_save_state_cb)
            dpg.add_text("Reset Wait :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_scenario_reset_wait", default_value=1.0,
                                min_value=0.0, max_value=30.0,
                                format="%.1f", step=0, width=55,
                                callback=_save_state_cb)
            dpg.add_text("Play Wait :", color=(180, 180, 180, 255))
            dpg.add_input_float(tag="lc_auto_scenario_play_wait", default_value=1.0,
                                min_value=0.0, max_value=30.0,
                                format="%.1f", step=0, width=55,
                                callback=_save_state_cb)

        _load_state()

        # ── TARGET VEHICLE (1줄) ───────────────────────────────
        _section("TARGET VEHICLE")
        with dpg.group(horizontal=True):
            dpg.add_text("ID :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="lc_entity_id", default_value="Car_1", width=90)
            dpg.add_spacer(width=8)
            dpg.add_checkbox(tag="lc_speed_ctrl", label="Speed Ctrl",
                             default_value=True, callback=_on_speed_ctrl_toggle)
            dpg.add_spacer(width=6)
            dpg.add_text("Target :", color=(180, 180, 180, 255), tag="lc_target_label")
            dpg.add_input_float(tag="lc_target_kmh", default_value=15.0,
                                min_value=1.0, max_value=200.0,
                                format="%.1f", step=0, width=60)
            dpg.add_text("km/h", color=(160, 160, 160, 255), tag="lc_kmh_label")
            dpg.add_text("Throttle :", color=(180, 180, 180, 255),
                         tag="lc_throttle_label", show=False)
            dpg.add_input_float(tag="lc_throttle", default_value=0.3,
                                min_value=0.0, max_value=1.0,
                                format="%.2f", step=0, width=55, show=False)
            dpg.add_spacer(width=8)
            dpg.add_checkbox(tag="lc_invert_steer", label="Invert Steer",
                             default_value=True, callback=_on_invert_steer_toggle)

        # ── INTERFACE ──────────────────────────────────────────
        _section("INTERFACE")
        with dpg.group(horizontal=True):
            dpg.add_text("VI Port :", color=(180, 180, 180, 255))
            dpg.add_input_int(tag="lc_vi_port", default_value=9091,
                              min_value=1, max_value=65535, step=0, width=70)
            dpg.add_spacer(width=16)
            dpg.add_text("Cam Port :", color=(180, 180, 180, 255))
            dpg.add_input_int(tag="lc_cam_port", default_value=9090,
                              min_value=1, max_value=65535, step=0, width=70)

        # ── TUNING ─────────────────────────────────────────────
        _section("TUNING")
        dpg.add_text("* Start 이후 실시간 반영됩니다.",
                     color=(140, 140, 100, 255))
        dpg.add_spacer(height=4)

        # Control(좌) / Noise Filter(우) 2열 배치
        with dpg.table(header_row=True, borders_innerV=True,
                       policy=dpg.mvTable_SizingStretchSame):
            dpg.add_table_column(label="Control")
            dpg.add_table_column(label="Noise Filter")

            with dpg.table_row():
                # ── 왼쪽: 제어 슬라이더 ──────────────────────
                with dpg.group():
                    _slider("Kp",          "lc_kp",          0.50,  0.0,  3.0,  "%.3f", _on_kp)
                    _slider("Kd",          "lc_kd",          0.10,  0.0,  1.0,  "%.3f", _on_kd)
                    _slider("EMA",         "lc_ema",         0.30,  0.01, 1.0,  "%.2f", _on_ema)
                    _slider("Steer Rate",  "lc_steer_rate",  0.15,  0.01, 0.5,  "%.3f", _on_steer_rate)
                    _slider("Offset Clip", "lc_offset_clip", 1.50,  0.1,  3.0,  "%.2f", _on_offset_clip)
                    _slider("Target Spd",  "lc_tune_speed",  15.0,  1.0,  100.0,"%.1f", _on_tune_speed,
                            suffix=" km/h", tag_suffix="lc_tune_speed_label",
                            show=dpg.get_value("lc_speed_ctrl") if dpg.does_item_exist("lc_speed_ctrl") else True)

                # ── 오른쪽: 노이즈 필터 슬라이더 ─────────────
                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_text("Preprocess  :", color=(180, 180, 180, 255))
                        dpg.add_combo(
                            ("legacy", "structure"),
                            tag="lc_preprocess_mode",
                            default_value="legacy",
                            width=160,
                            callback=_on_preprocess_mode,
                        )
                    _slider_int("BEV Crop",  "lc_bev_top_crop", 80,  0, 240, _on_bev_top_crop,
                                tooltip="BEV 바이너리 상단 N행 마스킹 (터널 천장/원경 노이즈 제거)")
                    _slider_int("Min Blob",  "lc_min_blob",      50,  0, 500, _on_min_blob,
                                tooltip="N픽셀 미만 blob 제거 (산점 노이즈 제거)")
                    _slider_int("Shadow Flt", "lc_shadow_filter", 0,   0, 100, _on_shadow_filter,
                                tooltip="Wide sun/shadow boundary removal strength")
                    _slider("Srch Ratio",    "lc_search_ratio",  0.50, 0.1, 1.0, "%.2f", _on_search_ratio,
                            tooltip="히스토그램 피크 탐색 범위 (이미지 하단 비율)")
                    _slider_int("Min Pix",   "lc_min_pixels",    30,  1,  200, _on_min_pixels,
                                tooltip="슬라이딩 윈도우 최소 픽셀 수")

        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Analyze Last Run", tag="lc_btn_analyze_last",
                           width=140, callback=_on_analyze_last_run)
            dpg.add_button(label="Apply Next Test", tag="lc_btn_apply_next",
                           width=130, callback=_on_apply_next_test)
            dpg.add_button(label="Reset Defaults", tag="lc_btn_reset",
                           width=130, callback=_on_reset_tuning)

        # ── LIVE VIEW ──────────────────────────────────────────
        _section("LIVE VIEW")
        with dpg.table(header_row=False, borders_innerV=True,
                       policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=_CAM_W)
            dpg.add_table_column(width_stretch=True)
            with dpg.table_row():
                dpg.add_image("lc_cam_texture", width=_CAM_W, height=_CAM_H)
                with dpg.child_window(height=_CAM_H, border=False):
                    dpg.add_text("Vehicle Info", color=(200, 200, 100, 255))
                    dpg.add_separator()
                    dpg.add_spacer(height=4)
                    _vi_row("Speed",   "lc_vi_speed")
                    dpg.add_spacer(height=4)
                    _vi_row("Pos X",   "lc_vi_posx")
                    _vi_row("Pos Y",   "lc_vi_posy")
                    _vi_row("Pos Z",   "lc_vi_posz")
                    dpg.add_spacer(height=4)
                    _vi_row("Yaw",     "lc_vi_yaw")
                    dpg.add_spacer(height=4)
                    _vi_row("Vel X",   "lc_vi_velx")
                    _vi_row("Vel Y",   "lc_vi_vely")


# ── 헬퍼 위젯 ────────────────────────────────────────────────────

def _section(label: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(label, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)


_STATE_TAGS = {
    "lc_auto_iters": int,
    "lc_auto_max_sec": float,
    "lc_auto_no_launch_sec": float,
    "lc_auto_stuck_sec": float,
    "lc_auto_lost_sec": float,
    "lc_auto_scenario_name": str,
    "lc_auto_scenario_reset_wait": float,
    "lc_auto_scenario_play_wait": float,
}


def _save_state_cb(sender=None, app_data=None, user_data=None) -> None:
    _save_state()


def _save_state() -> None:
    data = {}
    for tag in _STATE_TAGS:
        if dpg.does_item_exist(tag):
            data[tag] = dpg.get_value(tag)
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.append(f"[LC] failed to save panel state: {exc}", level="WARN")


def _load_state() -> None:
    if not os.path.exists(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.append(f"[LC] failed to load panel state: {exc}", level="WARN")
        return
    if not isinstance(data, dict):
        return
    for tag, caster in _STATE_TAGS.items():
        if tag not in data or not dpg.does_item_exist(tag):
            continue
        try:
            dpg.set_value(tag, caster(data[tag]))
        except (TypeError, ValueError):
            continue


def _slider(label: str, tag: str, default: float,
            vmin: float, vmax: float, fmt: str,
            callback: Callable,
            suffix: str = "", tag_suffix: str = "", show: bool = True,
            tooltip: str = "") -> None:
    """라벨 + 슬라이더 + 현재값 한 줄."""
    with dpg.group(horizontal=True, show=show,
                   tag=tag + "_row" if not tag_suffix else ""):
        t = dpg.add_text(f"{label:<12}:", color=(180, 180, 180, 255))
        dpg.add_slider_float(tag=tag, default_value=default,
                             min_value=vmin, max_value=vmax,
                             format=fmt, width=160,
                             callback=callback)
        if suffix:
            dpg.add_text(suffix, color=(160, 160, 160, 255))
        if tooltip:
            with dpg.tooltip(t):
                dpg.add_text(tooltip)


def _slider_int(label: str, tag: str, default: int,
                vmin: int, vmax: int,
                callback: Callable,
                tooltip: str = "") -> None:
    """정수 슬라이더 한 줄 (label + slider)."""
    with dpg.group(horizontal=True, tag=tag + "_row"):
        t = dpg.add_text(f"{label:<12}:", color=(180, 180, 180, 255))
        s = dpg.add_slider_int(tag=tag, default_value=default,
                               min_value=vmin, max_value=vmax,
                               width=160, callback=callback)
        if tooltip:
            with dpg.tooltip(t):
                dpg.add_text(tooltip)


def _vi_row(label: str, tag: str) -> None:
    with dpg.group(horizontal=True):
        dpg.add_text(f"{label:<7}:", color=(160, 160, 160, 255))
        dpg.add_text("---", tag=tag, color=(210, 210, 215, 255))


# ── 내부 콜백 ────────────────────────────────────────────────────

def _on_speed_ctrl_toggle(sender, app_data) -> None:
    on = bool(app_data)
    dpg.configure_item("lc_target_label",   show=on)
    dpg.configure_item("lc_target_kmh",     show=on)
    dpg.configure_item("lc_kmh_label",      show=on)
    dpg.configure_item("lc_throttle_label", show=not on)
    dpg.configure_item("lc_throttle",       show=not on)
    # Target Spd 슬라이더 표시 동기화
    if dpg.does_item_exist("lc_tune_speed"):
        dpg.configure_item("lc_tune_speed", show=on)


def _on_invert_steer_toggle(sender, app_data) -> None:
    if _runner:
        _runner.update_params(invert_steer=bool(app_data))


def _on_kp(sender, app_data)          -> None:
    if _runner: _runner.update_params(kp=app_data)

def _on_kd(sender, app_data)          -> None:
    if _runner: _runner.update_params(kd=app_data)

def _on_ema(sender, app_data)         -> None:
    if _runner: _runner.update_params(ema_alpha=app_data)

def _on_steer_rate(sender, app_data)  -> None:
    if _runner: _runner.update_params(steer_rate=app_data)

def _on_offset_clip(sender, app_data) -> None:
    if _runner: _runner.update_params(offset_clip=app_data)

def _on_tune_speed(sender, app_data)  -> None:
    if _runner: _runner.update_params(target_kmh=app_data)

def _on_bev_top_crop(sender, app_data) -> None:
    if _runner: _runner.update_params(bev_top_crop=app_data)

def _on_min_blob(sender, app_data) -> None:
    if _runner: _runner.update_params(min_blob_area=app_data)

def _on_shadow_filter(sender, app_data) -> None:
    if _runner: _runner.update_params(shadow_filter_strength=app_data)

def _on_preprocess_mode(sender, app_data) -> None:
    if _runner: _runner.update_params(preprocess_mode=app_data)

def _on_search_ratio(sender, app_data) -> None:
    if _runner: _runner.update_params(search_ratio=app_data)

def _on_min_pixels(sender, app_data) -> None:
    if _runner: _runner.update_params(min_pixels=app_data)


def _on_reset_tuning() -> None:
    """모든 튜닝 슬라이더를 기본값으로 리셋."""
    for tag, val in _TUNING_DEFAULTS.items():
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, val)
    if _runner:
        _runner.update_params(
            kp           = _TUNING_DEFAULTS["lc_kp"],
            kd           = _TUNING_DEFAULTS["lc_kd"],
            ema_alpha    = _TUNING_DEFAULTS["lc_ema"],
            steer_rate   = _TUNING_DEFAULTS["lc_steer_rate"],
            offset_clip  = _TUNING_DEFAULTS["lc_offset_clip"],
            target_kmh   = _TUNING_DEFAULTS["lc_tune_speed"],
            bev_top_crop = _TUNING_DEFAULTS["lc_bev_top_crop"],
            min_blob_area= _TUNING_DEFAULTS["lc_min_blob"],
            shadow_filter_strength= _TUNING_DEFAULTS["lc_shadow_filter"],
            preprocess_mode= _TUNING_DEFAULTS["lc_preprocess_mode"],
            search_ratio = _TUNING_DEFAULTS["lc_search_ratio"],
            min_pixels   = _TUNING_DEFAULTS["lc_min_pixels"],
        )


def _apply_param_tags(params: dict) -> None:
    for tag, val in params.items():
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, val)
    if dpg.does_item_exist("lc_speed_ctrl"):
        dpg.set_value("lc_speed_ctrl", True)
        _on_speed_ctrl_toggle("lc_speed_ctrl", True)


def _apply_runner_params(params: dict) -> None:
    if not _runner:
        return
    update = {}
    mapping = {
        "lc_kp": "kp",
        "lc_kd": "kd",
        "lc_ema": "ema_alpha",
        "lc_steer_rate": "steer_rate",
        "lc_offset_clip": "offset_clip",
        "lc_tune_speed": "target_kmh",
        "lc_bev_top_crop": "bev_top_crop",
        "lc_min_blob": "min_blob_area",
        "lc_shadow_filter": "shadow_filter_strength",
        "lc_preprocess_mode": "preprocess_mode",
        "lc_search_ratio": "search_ratio",
        "lc_min_pixels": "min_pixels",
    }
    for tag, key in mapping.items():
        if tag in params:
            update[key] = params[tag]
    if update:
        _runner.update_params(**update)


def _get_tune_params() -> dict:
    return {
        "kp":            dpg.get_value("lc_kp"),
        "kd":            dpg.get_value("lc_kd"),
        "ema_alpha":     dpg.get_value("lc_ema"),
        "steer_rate":    dpg.get_value("lc_steer_rate"),
        "offset_clip":   dpg.get_value("lc_offset_clip"),
        "target_kmh":    dpg.get_value("lc_tune_speed"),
        "bev_top_crop":  dpg.get_value("lc_bev_top_crop"),
        "min_blob_area": dpg.get_value("lc_min_blob"),
        "shadow_filter_strength": dpg.get_value("lc_shadow_filter"),
        "preprocess_mode": dpg.get_value("lc_preprocess_mode"),
        "search_ratio":  dpg.get_value("lc_search_ratio"),
        "min_pixels":    dpg.get_value("lc_min_pixels"),
    }


def _start_current_run(force_record: bool = False) -> bool:
    if _start_fn is None:
        log.append("[LC] start_fn is not initialized.", level="ERROR")
        return False
    if _runner is not None:
        log.append("[LC] already running.", level="WARN")
        return False

    cam_port     = dpg.get_value("lc_cam_port")
    vi_port      = dpg.get_value("lc_vi_port")
    entity_id    = dpg.get_value("lc_entity_id").strip() or "Car_1"
    speed_ctrl   = dpg.get_value("lc_speed_ctrl")
    target_kmh   = dpg.get_value("lc_target_kmh")
    throttle     = dpg.get_value("lc_throttle")
    invert_steer = dpg.get_value("lc_invert_steer")
    record_run   = bool(dpg.get_value("lc_record_run") or force_record)

    dpg.configure_item("lc_btn_start", enabled=False)
    dpg.set_value("lc_status", "● Running")
    dpg.configure_item("lc_status", color=(100, 220, 100, 255))

    _start_fn(
        cam_port,
        vi_port,
        entity_id,
        speed_ctrl,
        target_kmh,
        throttle,
        invert_steer,
        record_run,
        _get_tune_params(),
    )
    return True


def _run_on_ui_thread(fn: Callable, timeout_sec: float = 5.0):
    done = threading.Event()
    box = {"value": None, "error": None}

    def _wrapped():
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        finally:
            done.set()

    ui_queue.post(_wrapped)
    if not done.wait(timeout_sec):
        raise TimeoutError("UI operation timed out")
    if box["error"] is not None:
        raise box["error"]
    return box["value"]


def _get_auto_config() -> dict:
    _save_state()
    scenario_name = ""
    if dpg.does_item_exist("lc_auto_scenario_name"):
        scenario_name = (dpg.get_value("lc_auto_scenario_name") or "").strip()
    if not scenario_name and dpg.does_item_exist("sc_name"):
        scenario_name = (dpg.get_value("sc_name") or "").strip()
    no_launch_sec = max(1.0, float(dpg.get_value("lc_auto_no_launch_sec")))
    return {
        "max_iters": max(1, int(dpg.get_value("lc_auto_iters"))),
        "max_sec": max(5.0, float(dpg.get_value("lc_auto_max_sec"))),
        "no_launch_sec": no_launch_sec,
        "no_telemetry_sec": max(3.0, no_launch_sec * 1.5),
        "stuck_sec": max(1.0, float(dpg.get_value("lc_auto_stuck_sec"))),
        "lost_sec": max(1.0, float(dpg.get_value("lc_auto_lost_sec"))),
        "offset_limit": 1.20,
        "offset_sec": 1.0,
        "scenario_name": scenario_name,
        "scenario_reset_wait": (
            max(0.0, float(dpg.get_value("lc_auto_scenario_reset_wait")))
            if dpg.does_item_exist("lc_auto_scenario_reset_wait")
            else 1.0
        ),
        "scenario_play_wait": (
            max(0.0, float(dpg.get_value("lc_auto_scenario_play_wait")))
            if dpg.does_item_exist("lc_auto_scenario_play_wait")
            else 1.0
        ),
    }


def _set_auto_status(text: str, color=(150, 150, 150, 255)) -> None:
    def _apply():
        if dpg.does_item_exist("lc_auto_status"):
            dpg.set_value("lc_auto_status", text)
            dpg.configure_item("lc_auto_status", color=color)
    ui_queue.post(_apply)


def _status_family(status: str) -> str:
    if status.startswith("NO_DET"):
        return "NO_DET"
    if status.startswith("BAD_W"):
        return "BAD_W"
    if status.startswith("WAIT"):
        return "WAIT"
    return status.split("(", 1)[0]


def _send_auto_scenario_control(command: int, cfg: dict) -> None:
    if _scenario_control_fn is None:
        raise RuntimeError("scenario control callback is not initialized")
    scenario_name = str(cfg.get("scenario_name") or "")
    command_name = {
        1: "Play",
        2: "Pause",
        3: "Stop",
        4: "Prev",
        5: "Next",
    }.get(command, f"Command({command})")
    _scenario_control_fn(command, scenario_name)
    log.append(
        f"[LC][Auto] scenario {command_name} sent name={scenario_name!r}",
        level="INFO",
    )


def _auto_stop_reason(start_t: float, cfg: dict, state: dict) -> Optional[str]:
    runner = _runner
    row = runner.get_last_telemetry() if runner and hasattr(runner, "get_last_telemetry") else None
    now = time.monotonic()
    if row is None:
        if state.get("no_telemetry_t") is None:
            state["no_telemetry_t"] = now
        elif now - state["no_telemetry_t"] >= cfg["no_telemetry_sec"]:
            return "no_telemetry"
        return "max_duration_no_telemetry" if now - start_t >= cfg["max_sec"] else None
    state["no_telemetry_t"] = None

    speed = float(row.get("speed_kmh") or 0.0)
    throttle = float(row.get("throttle") or 0.0)
    offset = abs(float(row.get("smooth_offset_m") or 0.0))
    ready = bool(row.get("ready"))
    status = _status_family(str(row.get("status") or ""))

    if speed > 0.5:
        state["moved"] = True
        state["last_moving_t"] = now
    if speed > 3.0:
        state["last_progress_t"] = now

    if not ready and not state["moved"] and status == "WAIT":
        if state.get("wait_ready_t") is None:
            state["wait_ready_t"] = now
        elif now - state["wait_ready_t"] >= cfg["no_launch_sec"]:
            return "no_ready"
    else:
        state["wait_ready_t"] = None

    if ready and not state["moved"] and throttle >= 0.25:
        if state.get("launch_wait_t") is None:
            state["launch_wait_t"] = now
        elif now - state["launch_wait_t"] >= cfg["no_launch_sec"]:
            return "no_launch"
    else:
        state["launch_wait_t"] = None

    if state["moved"] and speed < 0.5:
        if state.get("stuck_t") is None:
            state["stuck_t"] = now
        elif now - state["stuck_t"] >= cfg["stuck_sec"]:
            return "stuck"
    else:
        state["stuck_t"] = None

    progress_grace = (
        state.get("last_progress_t") is not None
        and now - state["last_progress_t"] < max(4.0, cfg["lost_sec"])
    )

    if status == "NO_DET" and not progress_grace:
        if state.get("lost_t") is None:
            state["lost_t"] = now
        elif now - state["lost_t"] >= cfg["lost_sec"]:
            return "lane_lost"
    else:
        state["lost_t"] = None

    if offset >= cfg["offset_limit"] and not progress_grace:
        if state.get("offset_t") is None:
            state["offset_t"] = now
        elif now - state["offset_t"] >= cfg["offset_sec"]:
            return "out_of_lane"
    else:
        state["offset_t"] = None

    return "max_duration" if now - start_t >= cfg["max_sec"] else None


def _auto_cycle_loop(cfg: dict) -> None:
    global _auto_iteration
    for i in range(1, cfg["max_iters"] + 1):
        if _auto_stop_event.is_set():
            break
        _auto_iteration = i
        _set_auto_status(f"Auto {i}/{cfg['max_iters']} starting", (100, 200, 255, 255))
        try:
            _set_auto_status(f"Auto {i} scenario reset", (100, 200, 255, 255))
            _run_on_ui_thread(lambda: _send_auto_scenario_control(3, cfg), 5.0)
            if _auto_stop_event.wait(cfg["scenario_reset_wait"]):
                break
            _set_auto_status(f"Auto {i} scenario play", (100, 200, 255, 255))
            _run_on_ui_thread(lambda: _send_auto_scenario_control(1, cfg), 5.0)
            if _auto_stop_event.wait(cfg["scenario_play_wait"]):
                break
        except Exception as exc:
            log.append(f"[LC] auto scenario control failed: {exc}", level="ERROR")
            _set_auto_status("Auto scenario failed", (220, 80, 80, 255))
            break
        try:
            started = _run_on_ui_thread(lambda: _start_current_run(force_record=True), 10.0)
        except Exception as exc:
            log.append(f"[LC] auto cycle start failed: {exc}", level="ERROR")
            _set_auto_status("Auto start failed", (220, 80, 80, 255))
            break
        if not started:
            _set_auto_status("Auto start skipped", (220, 160, 80, 255))
            break

        start_t = time.monotonic()
        state = {
            "moved": False,
            "last_moving_t": None,
            "last_progress_t": None,
            "no_telemetry_t": None,
            "wait_ready_t": None,
            "launch_wait_t": None,
            "stuck_t": None,
            "lost_t": None,
            "offset_t": None,
        }
        stop_reason = "manual_stop"
        while not _auto_stop_event.wait(0.2):
            reason = _auto_stop_reason(start_t, cfg, state)
            elapsed = time.monotonic() - start_t
            _set_auto_status(f"Auto {i}/{cfg['max_iters']} {elapsed:.0f}s", (100, 220, 100, 255))
            if reason:
                stop_reason = reason
                break

        _set_auto_status(f"Auto {i} stopping: {stop_reason}", (220, 190, 80, 255))
        try:
            runner = _runner
            if runner is not None and hasattr(runner, "set_stop_reason"):
                runner.set_stop_reason(stop_reason)
            _run_on_ui_thread(_on_stop, 10.0)
            _run_on_ui_thread(lambda: _send_auto_scenario_control(3, cfg), 5.0)
            time.sleep(0.5)
            _run_on_ui_thread(_on_analyze_last_run, 10.0)
        except Exception as exc:
            log.append(f"[LC] auto cycle analyze failed: {exc}", level="ERROR")
            _set_auto_status("Auto analyze failed", (220, 80, 80, 255))
            break

        if _auto_stop_event.is_set():
            break
        time.sleep(1.0)

    _set_auto_status("Auto Idle", (150, 150, 150, 255))


def _on_auto_cycle_start() -> None:
    global _auto_thread
    if _auto_thread is not None and _auto_thread.is_alive():
        log.append("[LC] auto cycle already running", level="WARN")
        return
    cfg = _get_auto_config()
    _auto_stop_event.clear()
    if dpg.does_item_exist("lc_record_run"):
        dpg.set_value("lc_record_run", True)
    _auto_thread = threading.Thread(target=_auto_cycle_loop, args=(cfg,), daemon=True)
    _auto_thread.start()
    log.append(f"[LC] auto cycle started ({cfg['max_iters']} iterations)", level="INFO")


def _on_auto_cycle_stop() -> None:
    _auto_stop_event.set()
    _set_auto_status("Auto stopping...", (220, 190, 80, 255))
    log.append("[LC] auto cycle stop requested", level="INFO")


def _on_apply_next_test() -> None:
    """Apply the next recommended Lane Control experiment values."""
    _apply_param_tags(_NEXT_TEST_PARAMS)
    _apply_runner_params(_NEXT_TEST_PARAMS)
    log.append("[LC] Next test params applied", level="INFO")


def _on_analyze_last_run() -> None:
    run_dir, result = analyze_latest_run()
    if run_dir is None:
        log.append(f"[LC] analysis failed: {result.get('error')}", level="WARN")
        return
    params = result.get("suggestion", {})
    _apply_param_tags(params)
    _apply_runner_params(params)
    score = result.get("score")
    stats = result.get("telemetry_stats", {})
    note = "; ".join(result.get("notes", [])[:2])
    log.append(
        f"[LC] analyzed last run -> applied suggestion "
        f"(score={score:.3f}, max_speed={stats.get('max_speed_kmh', 0.0):.1f}km/h)",
        level="INFO",
    )
    if note:
        log.append(f"[LC] suggestion: {note}", level="INFO")


def _on_start() -> None:
    if _start_fn is None:
        log.append("[LC] start_fn이 초기화되지 않았습니다.", level="ERROR")
        return
    cam_port    = dpg.get_value("lc_cam_port")
    vi_port     = dpg.get_value("lc_vi_port")
    entity_id   = dpg.get_value("lc_entity_id").strip() or "Car_1"
    speed_ctrl  = dpg.get_value("lc_speed_ctrl")
    target_kmh  = dpg.get_value("lc_target_kmh")
    throttle    = dpg.get_value("lc_throttle")
    invert_steer= dpg.get_value("lc_invert_steer")
    record_run  = dpg.get_value("lc_record_run")
    tune_params = {
        "kp":            dpg.get_value("lc_kp"),
        "kd":            dpg.get_value("lc_kd"),
        "ema_alpha":     dpg.get_value("lc_ema"),
        "steer_rate":    dpg.get_value("lc_steer_rate"),
        "offset_clip":   dpg.get_value("lc_offset_clip"),
        "target_kmh":    dpg.get_value("lc_tune_speed"),
        "bev_top_crop":  dpg.get_value("lc_bev_top_crop"),
        "min_blob_area": dpg.get_value("lc_min_blob"),
        "shadow_filter_strength": dpg.get_value("lc_shadow_filter"),
        "preprocess_mode": dpg.get_value("lc_preprocess_mode"),
        "search_ratio":  dpg.get_value("lc_search_ratio"),
        "min_pixels":    dpg.get_value("lc_min_pixels"),
    }

    dpg.configure_item("lc_btn_start", enabled=False)
    dpg.set_value("lc_status", "● Running")
    dpg.configure_item("lc_status", color=(100, 220, 100, 255))

    _start_fn(
        cam_port,
        vi_port,
        entity_id,
        speed_ctrl,
        target_kmh,
        throttle,
        invert_steer,
        record_run,
        tune_params,
    )


def _on_stop() -> None:
    if _stop_fn:
        _stop_fn()


# ── 공개 업데이트 함수 ────────────────────────────────────────────

def reset_ui() -> None:
    """app.py에서 LC 종료 후 호출."""
    def _apply():
        if not dpg.does_item_exist("lc_btn_start"):
            return
        dpg.configure_item("lc_btn_start", enabled=True)
        dpg.set_value("lc_status", "○ Stopped")
        dpg.configure_item("lc_status", color=(180, 80, 80, 255))
        if dpg.does_item_exist("lc_cam_texture"):
            dpg.set_value("lc_cam_texture", _CAM_BLANK)
    ui_queue.post(_apply)


def update_frame(frame: np.ndarray) -> None:
    """원본 카메라 프레임 — debug frame 수신 중에는 억제됨."""
    global _last_frame_t
    if time.monotonic() < _suppress_raw_until:
        return
    now = time.monotonic()
    if now - _last_frame_t < _FRAME_INTERVAL:
        return
    _last_frame_t = now
    _post_frame(frame)


def update_debug_frame(frame: np.ndarray) -> None:
    """디버그 합성 이미지 (1280×480) — raw frame 을 500ms 억제."""
    global _last_frame_t, _suppress_raw_until
    now = time.monotonic()
    if now - _last_frame_t < _FRAME_INTERVAL:
        return
    _last_frame_t       = now
    _suppress_raw_until = now + 0.5
    _post_frame(frame)


def update_vehicle_info(parsed: dict) -> None:
    """Vehicle Info 파싱 결과 → UI 수치 업데이트."""
    try:
        loc = parsed.get("location",       {})
        rot = parsed.get("rotation",       {})
        vel = parsed.get("local_velocity", {})
        spd_kmh = (vel.get("x", 0.0) ** 2 +
                   vel.get("y", 0.0) ** 2 +
                   vel.get("z", 0.0) ** 2) ** 0.5 * 3.6
    except Exception:
        return

    def _apply(s=spd_kmh,
               x=loc.get("x", 0.0), y=loc.get("y", 0.0), z=loc.get("z", 0.0),
               yaw=rot.get("z", 0.0),
               vx=vel.get("x", 0.0), vy=vel.get("y", 0.0)):
        if not dpg.does_item_exist("lc_vi_speed"):
            return
        dpg.set_value("lc_vi_speed", f"{s:.1f} km/h")
        dpg.set_value("lc_vi_posx",  f"{x:.2f} m")
        dpg.set_value("lc_vi_posy",  f"{y:.2f} m")
        dpg.set_value("lc_vi_posz",  f"{z:.2f} m")
        dpg.set_value("lc_vi_yaw",   f"{yaw:.1f} °")
        dpg.set_value("lc_vi_velx",  f"{vx:.2f} m/s")
        dpg.set_value("lc_vi_vely",  f"{vy:.2f} m/s")
    ui_queue.post(_apply)


# ── 내부 헬퍼 ────────────────────────────────────────────────────

def _post_frame(frame: np.ndarray) -> None:
    """배경 스레드에서 BGR 프레임을 640×240 RGBA float 로 변환 후 큐에 올린다."""
    resized = cv2.resize(frame, (_CAM_W, _CAM_H))
    rgba    = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA)
    flat    = (rgba.astype(np.float32) / 255.0).flatten()

    def _apply(data=flat):
        if dpg.does_item_exist("lc_cam_texture"):
            dpg.set_value("lc_cam_texture", data)
    ui_queue.post(_apply)
