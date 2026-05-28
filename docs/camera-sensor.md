# Camera Sensor Panel

`Camera Sensor` is the integrated panel for receiving and visualizing camera streams from the simulator.

## Scope

The panel supports up to four sensor slots and the following camera templates:

- RGB
- Depth
- Semantic
- Instance
- RGB with 2D/3D bounding boxes

Depth testing was previously separate, but is now integrated into this panel.

## Main Files

- UI: [panels/camera_sensor_panel.py](../panels/camera_sensor_panel.py)
- RGB receiver: [receivers/camera_receiver.py](../receivers/camera_receiver.py)
- Depth receiver: [receivers/camera_depth_receiver.py](../receivers/camera_depth_receiver.py)
- Semantic/Instance receiver: [receivers/camera_semantic_receiver.py](../receivers/camera_semantic_receiver.py)
- BBox receiver: [receivers/camera_sensor_receiver.py](../receivers/camera_sensor_receiver.py)

## Templates

Camera templates are stored under `templates/camera/`.

- `Camera RGB.tmpl`
- `Camera Depth.tmpl`
- `Camera Semantic.tmpl`
- `Instance Cam.tmpl`
- `Camera With 2D_3D Bounding Box.tmpl`

The panel resolves templates by file name through `utils.template_paths`, so the UI does not depend on the physical subfolder.

Legacy names are normalized in the panel when loading saved state:

- `Camera Template.tmpl` -> `Camera RGB.tmpl`
- `Camera Depth Template.tmpl` -> `Camera Depth.tmpl`
- `CameraSensorMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`
- `CameraWithBboxMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`

## Panel UI

Each slot stores:

- `Template`
- `Depth View`: `Simulator`, `Grayscale`, `Turbo`
- `Scale`: `MORAI 0-255`, `Raw 32FC1`
- `IP`, `Port`
- Start/Stop state
- FPS, frame size, type, info, last RX timestamp

Panel state is saved to `config/camera_sensor_state.json`.

The panel uses one outer scroll container. Slot cards do not create their own nested scrollbars.

## Threading Rule

Receiver callbacks must not call DearPyGUI directly. They process the packet/frame and post UI updates through `utils.ui_queue.post()`.

## Depth Payload

`Camera Depth.tmpl` is parsed as a `32FC1` depth image.

Expected fields:

- width
- height
- encoding
- is bigendian
- image size
- step
- image data

Receiver validation:

- width and height must be greater than zero.
- encoding must be `32FC1`.
- little-endian data is expected.
- `step` must match `width * 4`.
- `image_size` must match `width * height * 4`.

Image data is read as little-endian float32:

```python
depth_raw = np.frombuffer(image_bytes, dtype="<f4").reshape((height, width))
```

## Depth Scale Modes

### MORAI 0-255

This mode treats the incoming value as a 0-255 encoded depth signal:

```text
depth_m = depth_raw * (200.0 / 255.0)
```

It exists for compatibility with older simulator output.

### Raw 32FC1

This mode treats incoming `32FC1` values as meters:

```text
depth_m = depth_raw
```

This is the mode closest to typical ROS depth image semantics.

## Depth Visualization

The client supports multiple visual modes. The most important comparison path is:

1. Receiver stats: raw min/max and converted depth min/max
2. Client `_visualize_depth()` debug PNG
3. Simulator `SaveDepthAsPng()` PNG
4. Simulator viewport preview

The client debug PNG and simulator saved PNG should match when both use the same raw frame, scale mode, and color map.

The simulator viewport can differ because it may use a separate visualization or post-process path.

## Depth Investigation Result

The latest confirmed issue was not packet parsing, byte order, `step`, or reshape.

Observed facts:

- UDP receive was stable.
- Frame size was received as `640 x 480`.
- FPS was stable around 26-27.
- Client debug PNG and simulator saved PNG differed even outside the GUI resize/display path.
- The strongest candidate was the simulator C++ `TurboLUT` high-index range, especially indices `240-255`.

OpenCV Turbo RGB examples from the Python client environment:

```text
240 = (169, 22, 1)
243 = (161, 18, 1)
247 = (149, 13, 1)
252 = (133, 7, 2)
255 = (122, 4, 3)
```

If the simulator LUT uses darker values in this range, near objects and lower image regions can look too dark and horizontal bands can become more visible.

## Recommended Simulator Check

When the saved PNG does not match the client debug PNG:

1. Extract the exact 256 RGB entries from Python OpenCV `cv2.COLORMAP_TURBO`.
2. Replace the simulator `SaveDepthAsPng()` `TurboLUT[256][3]` with those values.
3. Compare the client debug PNG and simulator saved PNG from the same scene and frame.
4. Separately inspect sky/far pixels to decide whether invalid/far values should be clamped to black.

## Semantic / Instance

Semantic and Instance cameras share the segmentation receiver.

Supported paths:

- encoded image payload through `cv2.imdecode()`
- raw `BGRA8`, `RGB8`, and `LABEL8` fallback payloads
- `LABEL8` visualization through OpenCV Turbo color map
- `step` and `image_size` validation from the template layout

Current status:

- `Camera Semantic.tmpl` receive/render verified
- `Instance Cam.tmpl` receive/render verified

## Current Completion Status

Completed:

- Depth test UI integrated into `Camera Sensor`
- RGB, Depth, Semantic, Instance, and BBox template selection
- RGB receive/render verified
- Depth receive/render verified
- Semantic receive/render verified
- Instance receive/render verified
- Depth view mode selection
- Depth scale mode selection
- raw range and converted depth range display
- nested scrollbar removed from Camera Sensor slot area
- client-side depth debug PNG helper added but disabled by default

Remaining simulator-side item:

- Align simulator `SaveDepthAsPng()` Turbo LUT with Python OpenCV Turbo, then re-compare saved PNG outputs.

## Validation

```bash
python -m py_compile panels/camera_sensor_panel.py receivers/camera_depth_receiver.py receivers/camera_receiver.py receivers/camera_semantic_receiver.py receivers/camera_sensor_receiver.py
```
