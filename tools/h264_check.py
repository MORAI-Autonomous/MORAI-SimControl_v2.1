"""Receives the "Camera H264" template over UDP, decodes the H.264 frames and reports what arrived.

The simulator sends one H.264 access unit per camera frame (CameraAttributes.h264, MSVM-3074). Each
message is the template fields in order: is_keyframe (bool), frame_index (uint64), width (uint32),
height (uint32), then the access unit (Annex-B bytes) to the end. Messages larger than one datagram
come in chunks with the network plugin's chunk header.

Decoding starts at the first keyframe; a gap in frame_index means frames were lost, and decoding waits
for the next keyframe. Needs PyAV (pip install av); with OpenCV the decoded frames are shown in a window.

    python tools/h264_check.py --port 9200 --seconds 10
    python tools/h264_check.py --port 9200 --show --save last_frame.png
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from typing import Dict, Optional

_CHUNK_HEADER_FMT = "<IHH"
_CHUNK_HEADER_SIZE = struct.calcsize(_CHUNK_HEADER_FMT)
_HEADER_FMT = "<?QII"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_ASSEMBLY_TIMEOUT = 5.0


class ChunkAssembler:
    """Joins chunked datagrams (packet_id, chunk_index, chunk_count + payload) into whole messages."""

    def __init__(self) -> None:
        self.packet_id: Optional[int] = None
        self.total = 0
        self.chunks: Dict[int, bytes] = {}
        self.started = 0.0

    @staticmethod
    def is_chunk(data: bytes) -> bool:
        if len(data) < _CHUNK_HEADER_SIZE:
            return False
        packet_id, index, total = struct.unpack_from(_CHUNK_HEADER_FMT, data)
        return packet_id != 0 and 0 < total <= 10000 and index < total

    def feed(self, data: bytes) -> Optional[bytes]:
        packet_id, index, total = struct.unpack_from(_CHUNK_HEADER_FMT, data)
        if packet_id != self.packet_id or time.time() - self.started > _ASSEMBLY_TIMEOUT:
            self.packet_id, self.total, self.chunks, self.started = packet_id, total, {}, time.time()
        self.chunks[index] = data[_CHUNK_HEADER_SIZE:]
        if len(self.chunks) < self.total:
            return None
        try:
            whole = b"".join(self.chunks[i] for i in range(self.total))
        except KeyError:
            whole = None
        self.packet_id = None
        return whole


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9200)
    ap.add_argument("--seconds", type=float, default=10.0, help="stop after this long (0: until Ctrl+C)")
    ap.add_argument("--show", action="store_true", help="show the decoded frames (needs OpenCV)")
    ap.add_argument("--save", help="write the last decoded frame to this image file (needs OpenCV)")
    args = ap.parse_args()

    try:
        import av  # noqa: F401
    except ImportError:
        print("PyAV is missing: pip install av")
        return 2
    cv2 = None
    if args.show or args.save:
        try:
            import cv2  # type: ignore
        except ImportError:
            print("OpenCV is missing (pip install opencv-python); frames are decoded but not shown")

    codec = av.CodecContext.create("h264", "r")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    except OSError:
        pass
    sock.bind((args.ip, args.port))
    sock.settimeout(0.5)
    print(f"listening on {args.ip}:{args.port}")

    assembler = ChunkAssembler()
    received = keyframes = decoded = gaps = waited = errors = repeats = 0
    bytes_total = 0
    last_index: Optional[int] = None
    synced = False
    last_image = None
    size = (0, 0)
    started = time.time()

    try:
        while args.seconds <= 0 or time.time() - started < args.seconds:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            message = assembler.feed(data) if ChunkAssembler.is_chunk(data) else data
            if message is None or len(message) < _HEADER_SIZE:
                continue

            is_key, index, width, height = struct.unpack_from(_HEADER_FMT, message)
            unit = message[_HEADER_SIZE:]
            # The template sends the field's latest value on every send tick, which can be faster than
            # the camera: the same frame then arrives again. It is not a loss; drop the repeat.
            if last_index is not None and index == last_index:
                repeats += 1
                continue
            received += 1
            bytes_total += len(unit)
            keyframes += 1 if is_key else 0
            size = (width, height)

            if last_index is not None and index != last_index + 1:
                gaps += 1
                synced = False  # frames were lost: the next ones refer to frames we do not have
            last_index = index
            if not synced:
                if not is_key:
                    waited += 1
                    continue
                synced = True

            try:
                for frame in codec.decode(av.Packet(unit)):
                    decoded += 1
                    if cv2 is not None:
                        last_image = frame.to_ndarray(format="bgr24")
                        if args.show:
                            cv2.imshow("h264_check", last_image)
                            cv2.waitKey(1)
            except Exception as e:  # PyAV raises av.error.FFmpegError subclasses
                errors += 1
                synced = False
                print(f"decode error at frame {index}: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    elapsed = max(time.time() - started, 1e-6)
    print(f"size {size[0]}x{size[1]}, {received} frames in {elapsed:.1f} s ({received / elapsed:.1f} fps), "
          f"{bytes_total * 8 / elapsed / 1e6:.2f} Mbit/s")
    print(f"keyframes {keyframes}, decoded {decoded}, frame index gaps {gaps}, "
          f"skipped waiting for a keyframe {waited}, decode errors {errors}, repeated sends dropped {repeats}")
    if args.save and cv2 is not None and last_image is not None:
        cv2.imwrite(args.save, last_image)
        print(f"last frame written to {args.save}")
    if args.show and cv2 is not None:
        cv2.destroyAllWindows()
    return 0 if decoded > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
