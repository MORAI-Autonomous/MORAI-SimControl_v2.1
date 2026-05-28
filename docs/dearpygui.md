# DearPyGUI 개발 규칙

## 탭바 대신 버튼 + show/hide

이 프로젝트에서는 `dpg.add_tab_bar` 대신 버튼과 `show/hide`를 사용합니다.  
기존에 폭 계산과 스크롤 영역에서 레이아웃 문제가 있었기 때문입니다.

```python
def _select_tab(name: str) -> None:
    dpg.configure_item("panel_a", show=(name == "a"))
    dpg.configure_item("panel_b", show=(name == "b"))
```

```python
with dpg.group(horizontal=True):
    dpg.add_button(label=" Tab A ", callback=lambda: _select_tab("a"))
    dpg.add_button(label=" Tab B ", callback=lambda: _select_tab("b"))
```

---

## 유니코드 아이콘 금지

DearPyGUI 기본 폰트와 일부 환경에서는 특수 유니코드가 깨질 수 있습니다.  
버튼 라벨은 ASCII 텍스트 기준으로 작성합니다.

예:

- `Reset Defaults`
- `Start`
- `Stop`

---

## Dynamic Texture

카메라나 디버그 프레임 표시에는 `dynamic_texture`를 사용합니다.

```python
blank = [0.0] * (W * H * 4)
with dpg.texture_registry():
    dpg.add_dynamic_texture(W, H, blank, tag="my_texture")
```

업데이트 시에는 `RGBA float32 1D array`로 변환해서 넣습니다.

```python
ui_queue.post(lambda d=rgba_f32: dpg.set_value("my_texture", d))
```

---

## does_item_exist 방어

콜백이나 비동기 업데이트 함수에서는 동적 UI가 이미 지워졌을 수 있습니다.  
항상 `dpg.does_item_exist()`로 방어합니다.

```python
if dpg.does_item_exist("my_tag"):
    dpg.set_value("my_tag", value)
```

---

## Scroll API 사용 위치

`set_y_scroll`, `get_y_scroll_max`는 `ChildWindow`나 `Window`에서만 사용합니다.  
`InputText`에 직접 호출하면 DPG 에러가 날 수 있습니다.

---

## collapsing_header 사용

같은 섹션 안에 기능을 구분할 때는 `collapsing_header`를 사용해 UI를 정리합니다.

```python
with dpg.collapsing_header(label="Manual Control", default_open=True):
    ...
```

---

## 동적 UI 재생성

차량 수처럼 개수가 바뀌는 UI는 컨테이너 그룹을 비우고 다시 만듭니다.

```python
dpg.add_group(tag="my_container")
```

```python
def _rebuild(count: int) -> None:
    dpg.delete_item("my_container", children_only=True)
    for i in range(count):
        with dpg.group(parent="my_container"):
            dpg.add_input_text(tag=f"my_input_{i}")
```

주의:

- `children_only=True` 후에는 `parent=`를 다시 명시해야 합니다.
- 동적 태그를 참조하는 update 함수는 `does_item_exist()` 체크가 필요합니다.

---

## Slider Helper Pattern

`src/panels/lane_control_panel.py`의 `_slider()`, `_slider_int()`처럼 공통 helper를 두면 일관된 UI를 유지하기 쉽습니다.

보통 포함할 요소:

- label
- slider/input widget
- tooltip
- 조건부 `show`

---

## Viewport Resize Rule

viewport resize callback 안에서 직접 레이아웃을 바꾸지 않습니다.  
callback은 dirty flag만 세우고, 실제 layout 반영은 메인 루프에서 합니다.

```python
def _mark_layout_dirty():
    global _layout_dirty
    _layout_dirty = True

dpg.set_viewport_resize_callback(_mark_layout_dirty)
```

이 규칙은 창 이동/리사이즈 시 hit-test, scroll, layout 꼬임을 줄이기 위한 것입니다.
