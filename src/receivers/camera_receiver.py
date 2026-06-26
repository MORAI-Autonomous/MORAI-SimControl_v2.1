from __future__ import annotations

"""UDP camera image receiver.

Supported MORAI Dynamic Camera packet formats:
  - Chunked: [PacketID:4B][ChunkIdx:2B][TotalChunks:2B] + payload
  - Headerless: [size:4B][JPEG bytes]

The assembled payload is expected to be [size:4B][JPEG bytes]. Decoded
frames are delivered as BGR uint8 NumPy arrays.
"""

import select
import socket
import struct
import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np

_HEADER_FMT = "<IHH"   # PacketID(4), ChunkIdx(2), TotalChunks(2)
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_RECV_BUF = 65535
_ASSEMBLY_TIMEOUT = 5.0


class _AssemblyState:
    def __init__(self):
        self.packet_id: Optional[int] = None
        self.total_chunks: int = 0
        self.chunks: dict[int, bytes] = {}
        self.started_at: float = 0.0

    def reset(self) -> None:
        self.packet_id = None
        self.total_chunks = 0
        self.chunks.clear()
        self.started_at = 0.0


class CameraReceiver(threading.Thread):
    """
    Receive JPEG camera frames over UDP.

    Parameters
    ----------
    ip:
        UDP bind address.
    port:
        UDP receive port.
    on_frame:
        Optional callback receiving frame as BGR uint8 ndarray.
    show:
        Show decoded frames in an OpenCV window.
    window_name:
        OpenCV window title.
    """

    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 9090,
        on_frame: Optional[Callable[[np.ndarray], None]] = None,
        show: bool = True,
        window_name: Optional[str] = None,
    ):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.on_frame = on_frame
        self.show = show
        self.window_name = window_name or f"Camera [{ip}:{port}]"
        self.running = False

        self._frame_count = 0
        self._fps_ts = time.time()
        self.fps = 0.0
        self.last_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()

        self._asm = _AssemblyState()

    def stop(self) -> None:
        self.running = False

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return the latest decoded frame as a copy, or None."""
        with self._lock:
            return self.last_frame.copy() if self.last_frame is not None else None

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
        print(f"[CameraReceiver] Listening on {self.ip}:{self.port}")

        try:
            while self.running:
                readable, _, _ = select.select([sock], [], [], 0.5)
                if not readable:
                    if self.show:
                        cv2.waitKey(1)
                    continue

                try:
                    while True:
                        try:
                            data, _ = sock.recvfrom(_RECV_BUF)
                        except BlockingIOError:
                            break
                        self._handle_datagram(data)
                except Exception as e:
                    if self.running:
                        print(f"[CameraReceiver] recv error: {e}")

                if self.show:
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        self.running = False
                        break
        finally:
            sock.close()
            if self.show:
                cv2.destroyWindow(self.window_name)
            print(f"[CameraReceiver] Stopped ({self.ip}:{self.port})")

    def _handle_datagram(self, data: bytes) -> None:
        if self._is_chunked(data):
            self._handle_chunked(data)
        else:
            self._handle_headerless(data)

    @staticmethod
    def _is_chunked(data: bytes) -> bool:
        if len(data) < _HEADER_SIZE:
            return False
        try:
            pid, cidx, total = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
        except struct.error:
            return False
        return pid != 0 and 0 < total <= 10000 and cidx < total

    def _handle_headerless(self, data: bytes) -> None:
        """Handle [uint32 size][JPEG bytes]."""
        if len(data) < 4:
            return
        (img_size,) = struct.unpack("<I", data[:4])
        if img_size == 0 or len(data) < 4 + img_size:
            return
        self._deliver(data[4: 4 + img_size])

    def _handle_chunked(self, data: bytes) -> None:
        """Assemble chunks and deliver [uint32 size][JPEG bytes]."""
        pid, cidx, total = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
        payload = data[_HEADER_SIZE:]
        asm = self._asm

        if asm.packet_id != pid:
            asm.reset()
            asm.packet_id = pid
            asm.total_chunks = total
            asm.started_at = time.time()

        if time.time() - asm.started_at > _ASSEMBLY_TIMEOUT:
            asm.reset()
            return

        asm.chunks[cidx] = payload

        if len(asm.chunks) < asm.total_chunks:
            return

        try:
            full = b"".join(asm.chunks[i] for i in range(asm.total_chunks))
        except KeyError:
            asm.reset()
            return

        asm.reset()

        if len(full) < 4:
            return
        (img_size,) = struct.unpack("<I", full[:4])
        if img_size == 0 or len(full) < 4 + img_size:
            return
        self._deliver(full[4: 4 + img_size])

    def _deliver(self, img_bytes: bytes) -> None:
        """Decode a JPEG frame, update stats, optionally display, and callback."""
        np_buf = np.frombuffer(img_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
        if frame is None:
            return

        with self._lock:
            self.last_frame = frame

        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_ts
        if elapsed >= 1.0:
            self.fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_ts = now

        if self.show:
            title = f"{self.window_name}  FPS: {self.fps:.1f}"
            cv2.imshow(self.window_name, frame)
            cv2.setWindowTitle(self.window_name, title)

        if self.on_frame is not None:
            try:
                self.on_frame(frame)
            except Exception as e:
                print(f"[CameraReceiver] on_frame error: {e}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Camera UDP receiver test")
    parser.add_argument("--ip", default="127.0.0.1", help="Bind IP address")
    parser.add_argument("--port", type=int, default=9090, help="UDP receive port")
    args = parser.parse_args()

    receiver = CameraReceiver(ip=args.ip, port=args.port, show=True)
    receiver.start()

    print("Receiving. Press q or ESC in the OpenCV window to exit.")
    try:
        while receiver.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        receiver.join(timeout=2.0)
        print("Stopped")


if __name__ == "__main__":
    main()
