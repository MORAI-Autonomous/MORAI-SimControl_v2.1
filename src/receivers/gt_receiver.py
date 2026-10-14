from __future__ import annotations

# receivers/gt_receiver.py
"""
GT(Ground Truth) 센서 리시버 - "Detected Object.tmpl" 기반.

패킷 구조 (little-endian, 헤더 없음):
  [FIELDS]  seconds(INT64) nanos(INT32) object_count(INT32)          = 16 B
  [REPEAT]  object_count 개 x 100 B
            entity_id(STRING 24) object_type(ENUM) + FLOAT 18개

Object 수에 관계없이(0개 ~ UDP 한 패킷 한도) 파싱하며, 템플릿 파싱은
receivers/template_parser.TemplateParser 에 맡긴다.

사용 예:
    from receivers.gt_receiver import GTReceiver

    rx = GTReceiver(ip="127.0.0.1", port=9001, on_packet=my_callback)
    rx.start()
    frame = rx.get_latest()   # 콜백 없이 최신 프레임만 가져와도 됨
    rx.stop(); rx.join()
"""

import argparse
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from receivers.template_parser import TemplateParser
from utils.template_paths import resolve_template_path

GT_TEMPLATE = "Detected Object.tmpl"

_RECV_BUF = 65535          # UDP 최대 크기 → object 최대 약 650개/패킷
_SOCKET_TIMEOUT = 0.5      # stop() 이후 recv 블로킹을 빠져나오기 위한 타임아웃


def _xyz(row: Dict[str, Any], prefix: str) -> Dict[str, float]:
    return {
        "x": row.get(f"{prefix}.x", 0.0),
        "y": row.get(f"{prefix}.y", 0.0),
        "z": row.get(f"{prefix}.z", 0.0),
    }


def _row_to_object(row: Dict[str, Any]) -> Dict[str, Any]:
    """TemplateParser 의 repeat row(평평한 dict) → 보기 쉬운 중첩 dict."""
    return {
        "entity_id":   row.get("entity_id", ""),
        "object_type": row.get("object_type", 0),
        "location":    _xyz(row, "object_transform.location"),
        "rotation":    _xyz(row, "object_transform.rotation"),
        "dimensions": {
            "length": row.get("dimensions.length", 0.0),
            "width":  row.get("dimensions.width", 0.0),
            "height": row.get("dimensions.height", 0.0),
        },
        "overhang": {
            "front": row.get("vehicle.vehicle_spec.overhang.front", 0.0),
            "rear":  row.get("vehicle.vehicle_spec.overhang.rear", 0.0),
        },
        "wheel_base":   row.get("vehicle.vehicle_spec.wheel_base", 0.0),
        "velocity":     _xyz(row, "vehicle.vehicle_state.velocity"),
        "acceleration": _xyz(row, "vehicle.vehicle_state.acceleration"),
    }


class GTReceiver(threading.Thread):
    """
    UDP로 Detected Object 패킷을 받아 파싱하는 백그라운드 스레드.

    on_packet(frame) 콜백 또는 get_latest() 로 아래 형태의 frame dict 를 받는다.
      {
        "seconds": int, "nanos": int,
        "object_count": int,       # 헤더에 적힌 개수
        "objects": [ {...}, ... ], # 실제 파싱된 object 리스트
        "truncated": bool,         # 헤더 개수 > 실제 수신 개수인 경우 True
        "raw_size": int, "addr": (ip, port), "recv_time": float,
      }
    """

    def __init__(
        self,
        ip: str,
        port: int,
        on_packet: Optional[Callable[[Dict[str, Any]], None]] = None,
        tmpl_path: Optional[str] = None,
    ):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.on_packet = on_packet
        self.running = False

        path = tmpl_path or resolve_template_path(GT_TEMPLATE)
        if path is None:
            raise FileNotFoundError(f"템플릿을 찾을 수 없습니다: {GT_TEMPLATE}")
        self.parser = TemplateParser(path)

        hdr = self.parser.fields_segment.byte_size() if self.parser.fields_segment else 0
        row = self.parser.repeat_segment.byte_size() if self.parser.repeat_segment else 0
        self.header_size = hdr   # 16
        self.row_size = row      # 100

        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._latest: Optional[Dict[str, Any]] = None
        self.packet_count = 0
        self.invalid_count = 0

    # ── 파싱 ─────────────────────────────────────────────────────────
    def parse(self, data: bytes) -> Optional[Dict[str, Any]]:
        parsed = self.parser.parse(data)
        if parsed is None:          # 16B 보다 짧음
            return None

        f = parsed["fields"]
        header_count = int(f.get("object_count", 0))
        objects: List[Dict[str, Any]] = [
            _row_to_object(r["fields"]) for r in parsed["repeat_rows"]
        ]
        return {
            "seconds":      f.get("time_stamp.seconds", 0),
            "nanos":        f.get("time_stamp.nanos", 0),
            "object_count": header_count,
            "objects":      objects,
            "truncated":    len(objects) < max(0, header_count),
            "raw_size":     parsed["raw_size"],
        }

    # ── 스레드 ───────────────────────────────────────────────────────
    def run(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self._sock.bind((self.ip, self.port))
        self._sock.settimeout(_SOCKET_TIMEOUT)
        self.running = True

        while self.running:
            try:
                data, addr = self._sock.recvfrom(_RECV_BUF)
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    print(f"[GTReceiver] socket error: {e}")
                break

            frame = self.parse(data)
            if frame is None:
                self.invalid_count += 1
                continue

            frame["addr"] = addr
            frame["recv_time"] = time.time()
            self.packet_count += 1
            with self._lock:
                self._latest = frame

            if self.on_packet:
                try:
                    self.on_packet(frame)
                except Exception as e:  # 콜백 오류로 수신이 멈추지 않도록
                    print(f"[GTReceiver] on_packet error: {e}")

        if self._sock:
            self._sock.close()

    def stop(self) -> None:
        self.running = False

    def get_latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest


# ── 단독 실행: python -m receivers.gt_receiver --ip 127.0.0.1 --port 9001 ────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="GT(Detected Object) 수신 확인")
    ap.add_argument("--ip", required=True, help="수신 바인드 IP (예: 127.0.0.1)")
    ap.add_argument("--port", type=int, required=True, help="수신 포트 (예: 9001)")
    args = ap.parse_args()
    last = [0.0]

    def _print(frame: Dict[str, Any]) -> None:
        now = time.time()
        if now - last[0] < 0.5:     # 출력 rate-limit
            return
        last[0] = now
        print(f"[GT] t={frame['seconds']}.{frame['nanos']:09d} "
              f"count={frame['object_count']} parsed={len(frame['objects'])} "
              f"size={frame['raw_size']}B truncated={frame['truncated']}")
        for o in frame["objects"]:
            loc = o["location"]
            print(f"    id='{o['entity_id']}' type={o['object_type']} "
                  f"loc=({loc['x']:.2f}, {loc['y']:.2f}, {loc['z']:.2f})")

    rx = GTReceiver(ip=args.ip, port=args.port, on_packet=_print)
    rx.start()
    print(f"[GT] listening on {rx.ip}:{rx.port}  (Ctrl+C 종료)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        rx.stop()
        rx.join()


if __name__ == "__main__":
    main()
