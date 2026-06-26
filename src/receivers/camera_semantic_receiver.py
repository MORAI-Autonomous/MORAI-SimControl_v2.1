from __future__ import annotations

import select
import socket
import struct
import threading
import time
from typing import Callable, Dict, Optional, Tuple

import cv2
import numpy as np

_CHUNK_HEADER_FMT = "<IHH"
_CHUNK_HEADER_SIZE = struct.calcsize(_CHUNK_HEADER_FMT)
_SEMANTIC_HEADER_FMT = "<iI"
_SEMANTIC_HEADER_SIZE = struct.calcsize(_SEMANTIC_HEADER_FMT)
_RECV_BUF = 65535
_ASSEMBLY_TIMEOUT = 5.0


class _AssemblyState:
    def __init__(self) -> None:
        self.packet_id: Optional[int] = None
        self.total_chunks: int = 0
        self.chunks: Dict[int, bytes] = {}
        self.started_at: float = 0.0

    def reset(self) -> None:
        self.packet_id = None
        self.total_chunks = 0
        self.chunks.clear()
        self.started_at = 0.0


class CameraSemanticReceiver(threading.Thread):
    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 9100,
        on_packet: Optional[Callable[[dict], None]] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.on_packet = on_packet
        self.running = False

        self._asm = _AssemblyState()
        self._lock = threading.Lock()
        self._fps_ts = time.time()
        self._frame_count = 0
        self._packet_seq = 0
        self.fps = 0.0
        self.last_packet: Optional[dict] = None
        self._debug_last: Dict[str, float] = {}

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
        print(f"[CameraSemanticReceiver] Listening on {self.ip}:{self.port}")

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
                    except OSError as e:
                        if self.running:
                            print(f"[CameraSemanticReceiver] recv error: {e}")
                        break
                    self._handle_datagram(data)
        finally:
            sock.close()
            print(f"[CameraSemanticReceiver] Stopped ({self.ip}:{self.port})")

    def _handle_datagram(self, data: bytes) -> None:
        if self._is_chunked(data):
            self._handle_chunked(data)
        else:
            self._deliver(data)

    @staticmethod
    def _is_chunked(data: bytes) -> bool:
        if len(data) < _CHUNK_HEADER_SIZE:
            return False
        try:
            packet_id, chunk_idx, total = struct.unpack(_CHUNK_HEADER_FMT, data[:_CHUNK_HEADER_SIZE])
        except struct.error:
            return False
        return packet_id != 0 and 0 < total <= 10000 and chunk_idx < total

    def _handle_chunked(self, data: bytes) -> None:
        packet_id, chunk_idx, total = struct.unpack(_CHUNK_HEADER_FMT, data[:_CHUNK_HEADER_SIZE])
        payload = data[_CHUNK_HEADER_SIZE:]
        asm = self._asm

        if asm.packet_id != packet_id:
            asm.reset()
            asm.packet_id = packet_id
            asm.total_chunks = total
            asm.started_at = time.time()

        if time.time() - asm.started_at > _ASSEMBLY_TIMEOUT:
            asm.reset()
            self._debug("chunk assembly timeout", key="asm_timeout", interval_sec=1.0)
            return

        asm.chunks[chunk_idx] = payload
        if len(asm.chunks) < asm.total_chunks:
            return

        try:
            full = b"".join(asm.chunks[i] for i in range(asm.total_chunks))
        except KeyError:
            asm.reset()
            self._debug("chunk assembly missing chunk", key="asm_missing", interval_sec=1.0)
            return

        asm.reset()
        self._deliver(full)

    def _deliver(self, payload: bytes) -> None:
        t0 = time.perf_counter()
        packet = self._parse_payload(payload)
        if packet is None:
            return
        parse_ms = (time.perf_counter() - t0) * 1000.0

        self._packet_seq += 1
        packet["packet_seq"] = self._packet_seq
        packet["parse_ms"] = parse_ms

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
            f"packet#{self._packet_seq} parsed {packet['width']}x{packet['height']} "
            f"format={packet['pixel_format']} image_size={packet['image_size']} "
            f"step={packet['step']} parse={parse_ms:.1f}ms",
            key="parsed",
            interval_sec=1.0,
        )

        if self.on_packet is not None:
            try:
                self.on_packet(packet)
            except Exception as e:
                print(f"[CameraSemanticReceiver] on_packet error: {e}")

    def _parse_payload(self, payload: bytes) -> Optional[dict]:
        if len(payload) < 4:
            self._debug(
                f"payload too short: {len(payload)} < 4",
                key="short",
                interval_sec=1.0,
            )
            return None

        parsed = self._extract_image_bytes(payload)
        if parsed is None:
            return None
        image_size, step, image_bytes, parse_mode = parsed

        frame_bgr, pixel_format, width, height, value_range, unique_count = _decode_semantic_image(
            image_bytes,
            step,
        )
        if frame_bgr is None:
            first16 = payload[:16].hex(" ")
            self._debug(
                f"could not decode semantic image parse_mode={parse_mode} "
                f"image_size={image_size} step={step} payload={len(payload)} first16=[{first16}]",
                key="format",
                interval_sec=1.0,
            )
            return None

        return {
            "raw_size": len(payload),
            "image_size": int(image_size),
            "step": int(step),
            "height": int(height),
            "width": int(width),
            "pixel_format": pixel_format,
            "frame": frame_bgr,
            "value_range": value_range,
            "unique_count": unique_count,
            "parse_mode": parse_mode,
        }

    def _extract_image_bytes(self, payload: bytes) -> Optional[Tuple[int, int, bytes, str]]:
        candidates = []

        if len(payload) >= _SEMANTIC_HEADER_SIZE:
            try:
                image_size, step = struct.unpack_from(_SEMANTIC_HEADER_FMT, payload, 0)
            except struct.error:
                image_size, step = -1, 0
            image_start = _SEMANTIC_HEADER_SIZE
            image_end = image_start + max(image_size, 0)
            if image_size > 0 and step > 0 and len(payload) >= image_end:
                candidates.append((image_size, step, payload[image_start:image_end], "image_size_step"))

        try:
            (image_size_only,) = struct.unpack_from("<i", payload, 0)
        except struct.error:
            image_size_only = -1
        image_start = 4
        image_end = image_start + max(image_size_only, 0)
        if image_size_only > 0 and len(payload) >= image_end:
            candidates.append((image_size_only, 0, payload[image_start:image_end], "image_size_only"))

        for image_size, step, image_bytes, parse_mode in candidates:
            if _is_encoded_image(image_bytes):
                return image_size, step, image_bytes, parse_mode
            if step > 0 and image_size % step == 0:
                return image_size, step, image_bytes, parse_mode

        first16 = payload[:16].hex(" ")
        self._debug(
            f"invalid semantic header payload={len(payload)} first16=[{first16}]",
            key="header",
            interval_sec=1.0,
        )
        return None

    def _debug(self, message: str, key: str, interval_sec: float) -> None:
        now = time.monotonic()
        last = self._debug_last.get(key, 0.0)
        if interval_sec <= 0.0 or now - last >= interval_sec:
            self._debug_last[key] = now
            print(f"[CameraSemanticReceiver][DBG] {message}")


def _decode_semantic_image(
    image_bytes: bytes,
    step: int,
) -> Tuple[Optional[np.ndarray], str, int, int, str, int]:
    if not image_bytes:
        return None, "", 0, 0, "-", 0

    data = np.frombuffer(image_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if decoded is not None:
        height, width = decoded.shape[:2]
        return decoded, "ENCODED", width, height, "-", 0

    if step <= 0 or len(image_bytes) % step != 0:
        return None, "", 0, 0, "-", 0

    height = len(image_bytes) // step
    bpp = _infer_bytes_per_pixel(step, height)

    if bpp == 4:
        width = step // bpp
        bgra = data.reshape((height, width, 4))
        frame_bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return frame_bgr, "BGRA8", width, height, "-", 0

    if bpp == 3:
        width = step // bpp
        rgb = data.reshape((height, width, 3))
        frame_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return frame_bgr, "RGB8", width, height, "-", 0

    width = step
    labels = data.reshape((height, width))
    label_min = int(labels.min()) if labels.size else 0
    label_max = int(labels.max()) if labels.size else 0
    unique_count = int(np.unique(labels).size) if labels.size else 0
    colored = cv2.applyColorMap(labels, cv2.COLORMAP_TURBO)
    return colored, "LABEL8", width, height, f"{label_min}~{label_max}", unique_count


def _infer_bytes_per_pixel(step: int, height: int) -> int:
    candidates = []
    for bpp in (1, 3, 4):
        if step % bpp != 0:
            continue
        width = step // bpp
        if width <= 0:
            continue
        aspect = width / max(1, height)
        score = min(abs(aspect - (4.0 / 3.0)), abs(aspect - (16.0 / 9.0)))
        candidates.append((score, -bpp, bpp))
    if not candidates:
        return 1
    return sorted(candidates)[0][2]


def _is_encoded_image(image_bytes: bytes) -> bool:
    return (
        image_bytes.startswith(b"\xFF\xD8\xFF")
        or image_bytes.startswith(b"\x89PNG\r\n\x1A\n")
        or image_bytes.startswith(b"BM")
    )
