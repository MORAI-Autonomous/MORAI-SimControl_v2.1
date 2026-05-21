from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, Dict, Optional

import numpy as np

_CHUNK_HEADER_FMT = "<IHH"
_CHUNK_HEADER_SIZE = struct.calcsize(_CHUNK_HEADER_FMT)
_RECV_BUF = 65535
_ASSEMBLY_TIMEOUT = 5.0
_DEPTH_HEADER_FMT = "<ii5s?Ii"
_DEPTH_HEADER_SIZE = struct.calcsize(_DEPTH_HEADER_FMT)
_DEPTH_SCALE_M = 200.0 / 255.0


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


class CameraDepthReceiver(threading.Thread):
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
        sock.settimeout(0.5)
        self.running = True
        print(f"[CameraDepthReceiver] Listening on {self.ip}:{self.port}")

        try:
            while self.running:
                try:
                    data, _addr = sock.recvfrom(_RECV_BUF)
                except socket.timeout:
                    continue
                except OSError as e:
                    if self.running:
                        print(f"[CameraDepthReceiver] recv error: {e}")
                    break
                self._handle(data)
        finally:
            sock.close()
            print(f"[CameraDepthReceiver] Stopped ({self.ip}:{self.port})")

    def _handle(self, data: bytes) -> None:
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
            f"encoding={packet['encoding']} image_size={packet['image_size']} "
            f"depth_m=[{packet['depth_min_m']:.2f},{packet['depth_max_m']:.2f}] "
            f"parse={parse_ms:.1f}ms",
            key="parsed",
            interval_sec=1.0,
        )

        if self.on_packet is not None:
            try:
                self.on_packet(packet)
            except Exception as e:
                print(f"[CameraDepthReceiver] on_packet error: {e}")

    def _parse_payload(self, payload: bytes) -> Optional[dict]:
        if len(payload) < _DEPTH_HEADER_SIZE:
            self._debug(
                f"payload too short: {len(payload)} < {_DEPTH_HEADER_SIZE}",
                key="short",
                interval_sec=1.0,
            )
            return None

        try:
            width_i, height_i, encoding_raw, is_bigendian, step, image_size = struct.unpack_from(
                _DEPTH_HEADER_FMT, payload, 0
            )
        except struct.error as e:
            self._debug(f"header unpack failed: {e}", key="unpack", interval_sec=1.0)
            return None

        width = int(width_i)
        height = int(height_i)
        encoding = encoding_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")

        if width <= 0 or height <= 0:
            self._debug(
                f"invalid size width={width} height={height}",
                key="size",
                interval_sec=1.0,
            )
            return None

        if encoding != "32FC1":
            self._debug(
                f"unsupported encoding={encoding!r}",
                key="encoding",
                interval_sec=1.0,
            )
            return None

        if is_bigendian:
            self._debug(
                "big-endian depth is not supported",
                key="bigendian",
                interval_sec=1.0,
            )
            return None

        expected_step = width * 4
        if step != expected_step:
            self._debug(
                f"unexpected step={step} expected={expected_step}",
                key="step",
                interval_sec=1.0,
            )
            return None

        expected_image_size = width * height * 4
        image_start = _DEPTH_HEADER_SIZE
        image_end = image_start + image_size
        if image_size != expected_image_size or len(payload) < image_end:
            self._debug(
                f"image size mismatch image_size={image_size} expected={expected_image_size} payload={len(payload)}",
                key="image_size",
                interval_sec=1.0,
            )
            return None

        image_bytes = payload[image_start:image_end]
        depth_raw = np.frombuffer(image_bytes, dtype="<f4").reshape((height, width))
        depth_m = depth_raw * _DEPTH_SCALE_M
        valid_mask = depth_raw > 0.0
        if np.any(valid_mask):
            depth_min_m = float(np.min(depth_m[valid_mask]))
            depth_max_m = float(np.max(depth_m[valid_mask]))
        else:
            depth_min_m = 0.0
            depth_max_m = 0.0

        return {
            "raw_size": len(payload),
            "width": width,
            "height": height,
            "encoding": encoding,
            "is_bigendian": bool(is_bigendian),
            "step": int(step),
            "image_size": int(image_size),
            "depth_raw": depth_raw,
            "depth_m": depth_m,
            "depth_min_m": depth_min_m,
            "depth_max_m": depth_max_m,
        }

    def _debug(self, message: str, key: str, interval_sec: float) -> None:
        now = time.monotonic()
        last = self._debug_last.get(key, 0.0)
        if interval_sec <= 0.0 or now - last >= interval_sec:
            self._debug_last[key] = now
            print(f"[CameraDepthReceiver][DBG] {message}")
