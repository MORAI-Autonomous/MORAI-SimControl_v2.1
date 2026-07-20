from __future__ import annotations

import socket
import struct
import threading
import unittest
from pathlib import Path
import sys

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from demo.demo_session import DemoSession, DemoSessionProtocolError, ScenarioStatus
import transport.protocol_defs as proto
import transport.tcp_transport as tcp


class _TestServer:
    def __init__(self, handler) -> None:
        self._handler = handler
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.host, self.port = self._listener.getsockname()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            conn, _ = self._listener.accept()
            with conn:
                self._handler(conn)
        except BaseException as exc:
            self.error = exc
        finally:
            self._listener.close()

    def join(self) -> None:
        self.thread.join(timeout=2.0)
        if self.error is not None:
            raise self.error


def _send_packet(conn: socket.socket, msg_class: int, msg_type: int, request_id: int, payload: bytes) -> None:
    conn.sendall(tcp.build_header(msg_class, msg_type, len(payload), request_id) + payload)


class DemoSessionTests(unittest.TestCase):
    def test_load_suite_waits_for_matching_success_response(self) -> None:
        def handler(conn: socket.socket) -> None:
            msg_class, msg_type, _, request_id, _, _ = tcp.recv_packet(conn)
            self.assertEqual(msg_class, proto.MSG_CLASS_REQ)
            self.assertEqual(msg_type, proto.MSG_TYPE_LOAD_SUITE)
            _send_packet(
                conn,
                proto.MSG_CLASS_RESP,
                msg_type,
                request_id,
                struct.pack(proto.RESULT_FMT, 0, 0),
            )

        server = _TestServer(handler)
        with DemoSession(server.host, server.port, request_timeout=1.0) as session:
            response = session.load_suite("C:/Demo/Customer.msuite")
        server.join()
        self.assertEqual(response, {"result_code": 0, "detail_code": 0})

    def test_failed_scenario_control_raises_protocol_error(self) -> None:
        def handler(conn: socket.socket) -> None:
            _, msg_type, _, request_id, _, _ = tcp.recv_packet(conn)
            _send_packet(
                conn,
                proto.MSG_CLASS_RESP,
                msg_type,
                request_id,
                struct.pack(proto.RESULT_FMT, 102, 7),
            )

        server = _TestServer(handler)
        with DemoSession(server.host, server.port, request_timeout=1.0) as session:
            with self.assertRaises(DemoSessionProtocolError) as caught:
                session.play("HighwayDemo")
        server.join()
        self.assertEqual(caught.exception.result_code, 102)
        self.assertEqual(caught.exception.detail_code, 7)

    def test_scenario_notification_updates_state_and_listener(self) -> None:
        received = threading.Event()
        send_allowed = threading.Event()
        statuses = []

        def handler(conn: socket.socket) -> None:
            send_allowed.wait(1.0)
            name = "HighwayDemo".encode("utf-8")
            payload = bytes([0x08, 0x01, 0x12, len(name)]) + name
            _send_packet(
                conn,
                proto.MSG_CLASS_NOTI,
                proto.MSG_TYPE_SCENARIO_STATUS,
                0,
                payload,
            )
            received.wait(1.0)

        server = _TestServer(handler)
        with DemoSession(server.host, server.port, request_timeout=1.0) as session:
            session.add_scenario_status_listener(
                lambda status: (statuses.append(status), received.set())
            )
            send_allowed.set()
            self.assertTrue(received.wait(1.0))
            self.assertEqual(session.scenario_status, ScenarioStatus(1, "HighwayDemo"))
        server.join()
        self.assertEqual(statuses, [ScenarioStatus(1, "HighwayDemo")])


if __name__ == "__main__":
    unittest.main()
