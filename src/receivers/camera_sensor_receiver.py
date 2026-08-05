from __future__ import annotations

import math
import os
import select
import socket
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from receivers.template_parser import MAX_REPEAT_COUNT, TemplateParser
from utils.template_paths import resolve_template_path

_HEADER_FMT = "<IHH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_RECV_BUF = 65535
_ASSEMBLY_TIMEOUT = 5.0
# ponytail: BBox-only packets have no dimensions; make this configurable if the protocol adds them.
_CANVAS_W = 1920
_CANVAS_H = 1080


def _make_debug_canvas() -> np.ndarray:
    canvas = np.full((_CANVAS_H, _CANVAS_W, 3), 24, dtype=np.uint8)
    for x in range(0, _CANVAS_W + 1, _CANVAS_W // 4):
        cv2.line(canvas, (x, 0), (x, _CANVAS_H), (48, 48, 48), 1)
    for y in range(0, _CANVAS_H + 1, _CANVAS_H // 4):
        cv2.line(canvas, (0, y), (_CANVAS_W, y), (48, 48, 48), 1)
    cv2.putText(
        canvas,
        f"BBox debug canvas {_CANVAS_W} x {_CANVAS_H}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (160, 160, 160),
        2,
        cv2.LINE_AA,
    )
    return canvas


_DEBUG_CANVAS = _make_debug_canvas()


class _AssemblyState:
    def __init__(self):
        self.packet_id: Optional[int] = None
        self.total_chunks: int = 0
        self.chunks: Dict[int, bytes] = {}
        self.started_at: float = 0.0

    def reset(self) -> None:
        self.packet_id = None
        self.total_chunks = 0
        self.chunks.clear()
        self.started_at = 0.0


class CameraSensorReceiver(threading.Thread):
    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 9090,
        on_packet: Optional[Callable[[dict], None]] = None,
        tmpl_path: Optional[str] = None,
    ):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.on_packet = on_packet
        self.running = False

        self._asm = _AssemblyState()
        self._lock = threading.Lock()
        self._fps_ts = time.time()
        self._frame_count = 0
        self.fps = 0.0
        self.last_packet: Optional[dict] = None
        self._debug_last: Dict[str, float] = {}
        self._packet_seq = 0

        self._tmpl_path = tmpl_path or resolve_template_path("Camera 2D Bounding Box.tmpl")
        if self._tmpl_path is None:
            raise FileNotFoundError("Camera 2D Bounding Box.tmpl")
        self._parser = TemplateParser(self._tmpl_path)
        repeat_segment = self._parser.repeat_segment
        if repeat_segment is None:
            raise ValueError(f"{os.path.basename(self._tmpl_path)} has no REPEAT segment")
        self._row_size = repeat_segment.byte_size()
        self._debug(
            f"template={os.path.basename(self._tmpl_path)} row_size={self._row_size}",
            key="init",
            interval_sec=0.0,
        )

    def stop(self) -> None:
        self.running = False

    def get_latest_packet(self) -> Optional[dict]:
        with self._lock:
            return self.last_packet

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        sock.bind((self.ip, self.port))
        sock.setblocking(False)

        self.running = True
        print(f"[CameraSensorReceiver] Listening on {self.ip}:{self.port}")

        try:
            while self.running:
                readable, _, _ = select.select([sock], [], [], 0.5)
                if not readable:
                    continue

                while True:
                    try:
                        data, _addr = sock.recvfrom(_RECV_BUF)
                    except BlockingIOError:
                        break
                    except OSError as exc:
                        if self.running:
                            print(f"[CameraSensorReceiver] recv error: {exc}")
                        break
                    self._handle_datagram(data)
        finally:
            sock.close()
            print(f"[CameraSensorReceiver] Stopped ({self.ip}:{self.port})")

    def _handle_datagram(self, data: bytes) -> None:
        if self._is_chunked(data):
            self._handle_chunked(data)
        else:
            self._deliver(data)

    @staticmethod
    def _is_chunked(data: bytes) -> bool:
        if len(data) < _HEADER_SIZE:
            return False
        try:
            packet_id, chunk_idx, total = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
        except struct.error:
            return False
        return packet_id != 0 and 0 < total <= 10000 and chunk_idx < total

    def _handle_chunked(self, data: bytes) -> None:
        packet_id, chunk_idx, total = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
        payload = data[_HEADER_SIZE:]
        asm = self._asm

        if asm.packet_id != packet_id:
            asm.reset()
            asm.packet_id = packet_id
            asm.total_chunks = total
            asm.started_at = time.time()

        if time.time() - asm.started_at > _ASSEMBLY_TIMEOUT:
            asm.reset()
            return

        asm.chunks[chunk_idx] = payload
        if len(asm.chunks) < asm.total_chunks:
            return

        try:
            full = b"".join(asm.chunks[i] for i in range(asm.total_chunks))
        except KeyError:
            asm.reset()
            return

        asm.reset()
        self._deliver(full)

    def _deliver(self, payload: bytes) -> None:
        packet = self._parse_payload(payload)
        if packet is None:
            return
        self._packet_seq += 1
        packet["packet_seq"] = self._packet_seq

        with self._lock:
            self.last_packet = packet

        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_ts
        if elapsed >= 1.0:
            self.fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_ts = now
        packet["fps"] = self.fps
        self._debug(
            f"packet#{self._packet_seq} parsed raw={packet['raw_size']} image={packet['image_size']} objects={packet['object_count']} frame={packet['frame'].shape[1]}x{packet['frame'].shape[0]}",
            key="parsed",
            interval_sec=1.0,
        )

        if self.on_packet is not None:
            try:
                self.on_packet(packet)
            except Exception as e:
                print(f"[CameraSensorReceiver] on_packet error: {e}")

    def _parse_payload(self, payload: bytes) -> Optional[dict]:
        if self._parser.fields_segment is None:
            if self._row_size <= 0:
                return None
            remainder = len(payload) % self._row_size
            if remainder:
                self._debug(
                    f"repeat tail mismatch bytes={len(payload)} row_size={self._row_size} remainder={remainder}",
                    key="repeat_remainder",
                    interval_sec=1.0,
                )

            parsed = self._parser.parse(payload)
            if parsed is None:
                return None
            objects = [row["fields"] for row in parsed["repeat_rows"]]
            return {
                "frame": _DEBUG_CANVAS,
                "image_size": 0,
                "object_count": len(objects),
                "objects": objects,
                "raw_size": len(payload),
                "parse_mode": "bbox_only",
                "template_name": parsed["template_name"],
            }

        if len(payload) < 4:
            self._debug(f"payload too short: {len(payload)} bytes", key="short", interval_sec=1.0)
            return None

        (image_size,) = struct.unpack_from("<i", payload, 0)
        if image_size > 0 and len(payload) >= 4 + image_size:
            image_start = 4
            image_end = 4 + image_size
            image_bytes = payload[image_start:image_end]
            remain = payload[image_end:]
            parse_mode = "size_prefix"
        else:
            jpg_at = payload.find(b"\xFF\xD8\xFF")
            first16 = payload[:16].hex(" ")
            le_i32 = struct.unpack_from("<i", payload, 0)[0] if len(payload) >= 4 else None
            be_i32 = struct.unpack_from(">i", payload, 0)[0] if len(payload) >= 4 else None
            self._debug(
                f"invalid image_size={image_size} payload_len={len(payload)} expected_at_least={4 + max(image_size, 0)} "
                f"first16=[{first16}] jpg_at={jpg_at} le_i32={le_i32} be_i32={be_i32}",
                key="image_size",
                interval_sec=1.0,
            )
            if jpg_at < 0:
                return None
            image_start = jpg_at
            image_end = self._find_jpeg_end(payload, image_start)
            if image_end <= image_start:
                self._debug(
                    f"jpeg end not found payload_len={len(payload)} image_start={image_start}",
                    key="jpeg_end",
                    interval_sec=1.0,
                )
                return None
            image_bytes = payload[image_start:image_end]
            remain = payload[image_end:]
            parse_mode = f"jpeg_scan(start={image_start})"

        np_buf = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
        if frame is None:
            self._debug(
                f"cv2.imdecode failed parse_mode={parse_mode} image_len={len(image_bytes)} payload_len={len(payload)}",
                key="decode_fail",
                interval_sec=1.0,
            )
            return None

        rows = self._parse_repeat_rows(remain)
        self._debug(
            f"payload parse_mode={parse_mode} image_bytes={len(image_bytes)} remain={len(remain)} rows={len(rows)}",
            key="parse_mode",
            interval_sec=1.0,
        )
        return {
            "frame": frame,
            "image_size": len(image_bytes),
            "object_count": len(rows),
            "objects": rows,
            "raw_size": len(payload),
            "image_start": image_start,
            "image_end": image_end,
            "parse_mode": parse_mode,
            "template_name": self._parser.template_name,
        }

    def _parse_repeat_rows(self, data: bytes) -> List[dict]:
        segment = self._parser.repeat_segment
        if segment is None or self._row_size <= 0:
            return []

        rows: List[dict] = []
        count = min(len(data) // self._row_size, MAX_REPEAT_COUNT)
        for row_index in range(count):
            values = struct.unpack_from(segment.build_fmt(), data, row_index * self._row_size)
            row: dict = {}
            for field, raw_value in zip(segment.fields, values):
                value = (
                    raw_value.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
                    if field.is_string
                    else raw_value
                )
                row[field.variable_name] = value
                row[field.name] = value
            rows.append(row)
        return rows

    def _find_jpeg_end(self, payload: bytes, image_start: int) -> int:
        candidates: List[int] = []
        search_pos = image_start + 2
        while True:
            eoi_at = payload.find(b"\xFF\xD9", search_pos)
            if eoi_at < 0:
                break
            image_end = eoi_at + 2
            remain_len = len(payload) - image_end
            if remain_len == 0 or remain_len % self._row_size == 0:
                candidates.append(image_end)
            search_pos = eoi_at + 1

        if candidates:
            return candidates[0]

        fallback = payload.rfind(b"\xFF\xD9")
        if fallback >= image_start:
            return fallback + 2
        return -1

    def _debug(self, msg: str, key: str, interval_sec: float) -> None:
        now = time.monotonic()
        last = self._debug_last.get(key, 0.0)
        if interval_sec > 0.0 and now - last < interval_sec:
            return
        self._debug_last[key] = now
        print(f"[CameraSensorReceiver][DBG] {msg}")


def draw_bbox_overlays(frame: np.ndarray, objects: List[dict]) -> Tuple[np.ndarray, Dict[str, int]]:
    out = frame.copy()
    drawn_2d = 0
    drawn_3d = 0
    for idx, obj in enumerate(objects):
        if _draw_bbox_2d(out, obj, idx):
            drawn_2d += 1
        if _draw_bbox_3d_projected(out, obj, idx):
            drawn_3d += 1
    return out, {
        "total_objects": len(objects),
        "drawn_2d": drawn_2d,
        "drawn_3d": drawn_3d,
    }


def _object_label(obj: dict, idx: int) -> str:
    return str(obj.get("annotation", "")).strip() or f"obj {idx}"


def _draw_bbox_2d(frame: np.ndarray, obj: dict, idx: int) -> bool:
    try:
        x0 = int(round(obj["bounding_box_2d.min.x"]))
        y0 = int(round(obj["bounding_box_2d.min.y"]))
        x1 = int(round(obj["bounding_box_2d.max.x"]))
        y1 = int(round(obj["bounding_box_2d.max.y"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

    if x1 <= x0 or y1 <= y0:
        return False

    cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 0, 255), 2)
    cv2.putText(
        frame,
        _object_label(obj, idx),
        (x0, max(14, y0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 255),
        1,
        cv2.LINE_AA,
    )
    return True


def _draw_bbox_3d_projected(frame: np.ndarray, obj: dict, idx: int) -> bool:
    points: List[Tuple[int, int]] = []
    for point_index in range(1, 9):
        x_key = f"bounding_box_3D8_points.projected_corner_points_{point_index}.x"
        y_key = f"bounding_box_3D8_points.projected_corner_points_{point_index}.y"
        x = obj.get(x_key)
        y = obj.get(y_key)
        if x is None or y is None:
            return False
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            return False
        points.append((int(round(float(x))), int(round(float(y)))))

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    for start, end in edges:
        cv2.line(frame, points[start], points[end], (255, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        _object_label(obj, idx),
        (points[0][0], max(14, points[0][1] - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return True
