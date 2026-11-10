"""Receives the "Camera H264" template over UDP and decodes the frames with PyAV (MSVM-3074).

Each message is the template fields in order: is_keyframe (bool), frame_index (uint64), width (uint32),
height (uint32), then one H.264 access unit (Annex-B) to the end. Messages larger than a datagram come
in chunks with the network plugin's chunk header (packet_id, chunk_index, chunk_count).

The template sends the field's latest value on every send tick, which can be faster than the camera, so
the same frame may arrive more than once; a repeated frame_index is dropped. A frame_index that skips
means frames were lost: decoding waits for the next keyframe, since the frames after a loss refer to
frames this receiver never got.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, Dict, Optional

import numpy as np

_CHUNK_HEADER_FMT = "<IHH"
_CHUNK_HEADER_SIZE = struct.calcsize(_CHUNK_HEADER_FMT)
_HEADER_FMT = "<?QII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_ASSEMBLY_TIMEOUT = 5.0


class CameraH264Receiver(threading.Thread):
    def __init__(
        self,
        ip: str = "0.0.0.0",
        port: int = 9200,
        on_frame: Optional[Callable[[np.ndarray, dict], None]] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.on_frame = on_frame
        self.running = False
        self.error: Optional[str] = None

        self.fps = 0.0
        self.received = 0
        self.decoded = 0
        self.keyframes = 0
        self.gaps = 0
        self.repeats = 0
        self.waiting = 0
        self.decode_errors = 0
        self.mbps = 0.0

        self._chunk_id: Optional[int] = None
        self._chunk_total = 0
        self._chunks: Dict[int, bytes] = {}
        self._chunk_started = 0.0
        self._last_index: Optional[int] = None
        self._synced = False
        self._fps_t = time.time()
        self._fps_count = 0
        self._fps_bytes = 0

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        try:
            import av  # PyAV: pip install av
        except ImportError:
            self.error = "PyAV is missing (pip install av)"
            print(f"[CameraH264Receiver] {self.error}")
            return
        codec = av.CodecContext.create("h264", "r")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        except OSError:
            pass
        sock.bind((self.ip, self.port))
        sock.settimeout(0.5)
        self.running = True
        print(f"[CameraH264Receiver] Listening on {self.ip}:{self.port}")
        try:
            while self.running:
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError as e:
                    if self.running:
                        print(f"[CameraH264Receiver] recv error: {e}")
                    break
                message = self._assemble(data) if self._is_chunk(data) else data
                if message is not None and len(message) >= _HEADER_SIZE:
                    self._handle(av, codec, message)
        finally:
            sock.close()
            print(f"[CameraH264Receiver] Stopped ({self.ip}:{self.port})")

    @staticmethod
    def _is_chunk(data: bytes) -> bool:
        if len(data) < _CHUNK_HEADER_SIZE:
            return False
        packet_id, index, total = struct.unpack_from(_CHUNK_HEADER_FMT, data)
        return packet_id != 0 and 0 < total <= 10000 and index < total

    def _assemble(self, data: bytes) -> Optional[bytes]:
        packet_id, index, total = struct.unpack_from(_CHUNK_HEADER_FMT, data)
        now = time.time()
        if packet_id != self._chunk_id or now - self._chunk_started > _ASSEMBLY_TIMEOUT:
            self._chunk_id, self._chunk_total, self._chunks, self._chunk_started = packet_id, total, {}, now
        self._chunks[index] = data[_CHUNK_HEADER_SIZE:]
        if len(self._chunks) < self._chunk_total:
            return None
        try:
            whole = b"".join(self._chunks[i] for i in range(self._chunk_total))
        except KeyError:
            whole = None
        self._chunk_id = None
        return whole

    def _handle(self, av, codec, message: bytes) -> None:
        is_key, index, width, height = struct.unpack_from(_HEADER_FMT, message)
        unit = message[_HEADER_SIZE:]
        if not unit:
            return  # the camera has no H.264 output (the field is empty)
        if self._last_index is not None and index == self._last_index:
            self.repeats += 1
            return
        self.received += 1
        self.keyframes += 1 if is_key else 0
        self._fps_bytes += len(unit)
        if self._last_index is not None and index != self._last_index + 1:
            self.gaps += 1
            self._synced = False
        self._last_index = index
        if not self._synced:
            if not is_key:
                self.waiting += 1
                return
            self._synced = True

        try:
            frames = codec.decode(av.Packet(unit))
        except Exception as e:  # PyAV raises av.error.FFmpegError subclasses
            self.decode_errors += 1
            self._synced = False
            print(f"[CameraH264Receiver] decode error at frame {index}: {e}")
            return

        for frame in frames:
            self.decoded += 1
            self._fps_count += 1
            now = time.time()
            elapsed = now - self._fps_t
            if elapsed >= 1.0:
                self.fps = self._fps_count / elapsed
                self.mbps = self._fps_bytes * 8 / elapsed / 1e6
                self._fps_t, self._fps_count, self._fps_bytes = now, 0, 0
            if self.on_frame is not None:
                info = {
                    "width": width, "height": height, "frame_index": index, "keyframe": bool(is_key),
                    "keyframes": self.keyframes, "gaps": self.gaps, "repeats": self.repeats,
                    "decode_errors": self.decode_errors, "mbps": self.mbps,
                }
                try:
                    self.on_frame(frame.to_ndarray(format="bgr24"), info)
                except Exception as e:
                    print(f"[CameraH264Receiver] on_frame error: {e}")
