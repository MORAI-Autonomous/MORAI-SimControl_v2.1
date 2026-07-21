from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import transport.protocol_defs as proto
import transport.tcp_transport as tcp


class DemoSessionError(RuntimeError):
    """Base error raised by DemoSession."""


class DemoSessionConnectionError(DemoSessionError):
    """The simulator connection failed or was lost."""


class DemoSessionTimeoutError(DemoSessionError):
    """The simulator did not answer a request before its deadline."""


class DemoSessionProtocolError(DemoSessionError):
    """The simulator returned an invalid or unsuccessful response."""

    def __init__(self, message: str, result_code: Optional[int] = None, detail_code: Optional[int] = None):
        super().__init__(message)
        self.result_code = result_code
        self.detail_code = detail_code


@dataclass(frozen=True)
class ScenarioStatus:
    state: int
    name: str = ""


@dataclass
class _PendingRequest:
    event: threading.Event
    response: Optional[Dict[str, Any]] = None
    error: Optional[BaseException] = None


class DemoSession:
    """GUI-independent, synchronous client for a MORAI customer demo.

    A single receiver thread owns all reads. Public command methods register a
    request, send it, and wait for the matching response. Scenario status
    notifications update ``scenario_status`` and are delivered to listeners.
    """

    _SCENARIO_PLAY = 1
    _SCENARIO_PAUSE = 2
    _SCENARIO_STOP = 3
    _SCENARIO_PREVIOUS = 4
    _SCENARIO_NEXT = 5

    def __init__(
        self,
        host: str = proto.TCP_SERVER_IP,
        port: int = proto.TCP_SERVER_PORT,
        request_timeout: float = 10.0,
        connect_timeout: float = 5.0,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be greater than zero")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be greater than zero")

        self.host = host
        self.port = int(port)
        self.request_timeout = float(request_timeout)
        self.connect_timeout = float(connect_timeout)

        self._socket: Optional[socket.socket] = None
        self._receiver: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._request_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_request_id = 1
        self._pending: Dict[Tuple[int, int], _PendingRequest] = {}
        self._scenario_status: Optional[ScenarioStatus] = None
        self._scenario_listeners: List[Callable[[ScenarioStatus], None]] = []

    @property
    def is_connected(self) -> bool:
        return self._running.is_set() and self._socket is not None

    @property
    def scenario_status(self) -> Optional[ScenarioStatus]:
        with self._state_lock:
            return self._scenario_status

    def connect(self) -> None:
        if self.is_connected:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect((self.host, self.port))
            sock.settimeout(None)
        except OSError as exc:
            sock.close()
            raise DemoSessionConnectionError(
                f"Failed to connect to MORAI at {self.host}:{self.port}: {exc}"
            ) from exc

        self._socket = sock
        self._running.set()
        self._receiver = threading.Thread(
            target=self._receive_loop,
            name="DemoSessionReceiver",
            daemon=True,
        )
        self._receiver.start()

    def close(self) -> None:
        self._running.clear()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        receiver = self._receiver
        self._receiver = None
        if receiver is not None and receiver is not threading.current_thread():
            receiver.join(timeout=1.0)

        self._fail_all_pending(DemoSessionConnectionError("Demo session is closed"))

    def __enter__(self) -> "DemoSession":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def add_scenario_status_listener(self, listener: Callable[[ScenarioStatus], None]) -> None:
        with self._state_lock:
            if listener not in self._scenario_listeners:
                self._scenario_listeners.append(listener)

    def remove_scenario_status_listener(self, listener: Callable[[ScenarioStatus], None]) -> None:
        with self._state_lock:
            if listener in self._scenario_listeners:
                self._scenario_listeners.remove(listener)

    def load_suite(self, suite_path: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        if not suite_path.strip():
            raise ValueError("suite_path is required")
        return self._request_result(
            proto.MSG_TYPE_LOAD_SUITE,
            lambda sock, rid: tcp.send_load_suite(sock, rid, suite_path),
            timeout,
        )

    def set_time_mode(
        self,
        mode: int,
        target_fps: int = 60,
        physics_delta_time: int = 10,
        rtf: int = 1,
        user_control: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self._request_result(
            proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
            lambda sock, rid: tcp.send_simulation_time_mode_command(
                sock,
                rid,
                mode=mode,
                target_fps=target_fps,
                physics_delta_time=physics_delta_time,
                rtf=rtf,
                user_control=1 if user_control else 0,
            ),
            timeout,
        )

    def get_time_status(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        return self._request_result(
            proto.MSG_TYPE_GET_SIMULATION_TIME_STATUS,
            lambda sock, rid: tcp.send_get_status(sock, rid),
            timeout,
        )

    def get_scenario_status(self, timeout: Optional[float] = None) -> ScenarioStatus:
        response = self._request_result(
            proto.MSG_TYPE_SCENARIO_STATUS,
            lambda sock, rid: tcp.send_scenario_status(sock, rid),
            timeout,
        )
        status = ScenarioStatus(state=response["state"], name=response.get("name", ""))
        self._publish_scenario_status(status)
        return status

    def control_scenario(
        self,
        command: int,
        scenario_name: str = "",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if command not in (
            self._SCENARIO_PLAY,
            self._SCENARIO_PAUSE,
            self._SCENARIO_STOP,
            self._SCENARIO_PREVIOUS,
            self._SCENARIO_NEXT,
        ):
            raise ValueError(f"Unsupported scenario command: {command}")
        return self._request_result(
            proto.MSG_TYPE_SCENARIO_CONTROL,
            lambda sock, rid: tcp.send_scenario_control(sock, rid, command, scenario_name),
            timeout,
        )

    def play(self, scenario_name: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        return self.control_scenario(self._SCENARIO_PLAY, scenario_name, timeout)

    def pause(self, scenario_name: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        return self.control_scenario(self._SCENARIO_PAUSE, scenario_name, timeout)

    def stop(self, scenario_name: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        return self.control_scenario(self._SCENARIO_STOP, scenario_name, timeout)

    def previous(self, scenario_name: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        return self.control_scenario(self._SCENARIO_PREVIOUS, scenario_name, timeout)

    def next(self, scenario_name: str = "", timeout: Optional[float] = None) -> Dict[str, Any]:
        return self.control_scenario(self._SCENARIO_NEXT, scenario_name, timeout)

    def _request_result(
        self,
        msg_type: int,
        send: Callable[[socket.socket, int], None],
        timeout: Optional[float],
    ) -> Dict[str, Any]:
        response = self._request(msg_type, send, timeout)
        result_code = response.get("result_code")
        detail_code = response.get("detail_code")
        if result_code != 0:
            raise DemoSessionProtocolError(
                f"MORAI request 0x{msg_type:04X} failed "
                f"(result={result_code}, detail={detail_code})",
                result_code=result_code,
                detail_code=detail_code,
            )
        return response

    def _request(
        self,
        msg_type: int,
        send: Callable[[socket.socket, int], None],
        timeout: Optional[float],
    ) -> Dict[str, Any]:
        wait_timeout = self.request_timeout if timeout is None else float(timeout)
        if wait_timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        sock = self._socket
        if not self.is_connected or sock is None:
            raise DemoSessionConnectionError("Demo session is not connected")

        with self._request_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            pending = _PendingRequest(event=threading.Event())
            self._pending[(request_id, msg_type)] = pending

        try:
            with self._send_lock:
                send(sock, request_id)
        except (OSError, ValueError) as exc:
            with self._request_lock:
                self._pending.pop((request_id, msg_type), None)
            if isinstance(exc, ValueError):
                raise
            raise DemoSessionConnectionError(f"Failed to send MORAI request: {exc}") from exc

        if not pending.event.wait(wait_timeout):
            with self._request_lock:
                self._pending.pop((request_id, msg_type), None)
            raise DemoSessionTimeoutError(
                f"Timed out waiting for MORAI response 0x{msg_type:04X} "
                f"after {wait_timeout:.1f}s"
            )
        if pending.error is not None:
            raise pending.error
        if pending.response is None:
            raise DemoSessionProtocolError(f"Empty MORAI response for 0x{msg_type:04X}")
        return pending.response

    def _receive_loop(self) -> None:
        sock = self._socket
        if sock is None:
            return
        try:
            while self._running.is_set():
                msg_class, msg_type, _, request_id, _, payload = tcp.recv_packet(sock)
                if msg_class == proto.MSG_CLASS_RESP:
                    self._handle_response(request_id, msg_type, payload)
                elif msg_class == proto.MSG_CLASS_NOTI:
                    self._handle_notification(msg_type, payload)
        except (ConnectionError, OSError, ValueError) as exc:
            if self._running.is_set():
                self._running.clear()
                if self._socket is sock:
                    self._socket = None
                try:
                    sock.close()
                except OSError:
                    pass
                self._fail_all_pending(
                    DemoSessionConnectionError(f"MORAI connection lost: {exc}")
                )

    def _handle_response(self, request_id: int, msg_type: int, payload: bytes) -> None:
        try:
            response = self._parse_response(msg_type, payload)
            error = None
        except DemoSessionProtocolError as exc:
            response = None
            error = exc

        with self._request_lock:
            pending = self._pending.pop((request_id, msg_type), None)
        if pending is None:
            return
        pending.response = response
        pending.error = error
        pending.event.set()

    def _handle_notification(self, msg_type: int, payload: bytes) -> None:
        if msg_type != proto.MSG_TYPE_SCENARIO_STATUS:
            return
        parsed = tcp.parse_scenario_status_notification_payload(payload)
        if parsed is not None:
            self._publish_scenario_status(
                ScenarioStatus(state=parsed["state"], name=parsed.get("name", ""))
            )

    def _parse_response(self, msg_type: int, payload: bytes) -> Dict[str, Any]:
        if msg_type in (proto.MSG_TYPE_LOAD_SUITE, proto.MSG_TYPE_SCENARIO_CONTROL):
            result = tcp.parse_result_code(payload)
            parsed = None if result is None else {
                "result_code": result[0],
                "detail_code": result[1],
            }
        elif msg_type == proto.MSG_TYPE_GET_SIMULATION_TIME_STATUS:
            parsed = tcp.parse_get_status_payload(payload)
        elif msg_type == proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND:
            parsed = tcp.parse_set_simulation_time_mode_payload(payload)
        elif msg_type == proto.MSG_TYPE_SCENARIO_STATUS:
            parsed = tcp.parse_scenario_status_payload(payload)
        else:
            raise DemoSessionProtocolError(f"Unsupported MORAI response type: 0x{msg_type:04X}")

        if parsed is None:
            raise DemoSessionProtocolError(f"Invalid MORAI response payload for 0x{msg_type:04X}")
        return parsed

    def _publish_scenario_status(self, status: ScenarioStatus) -> None:
        with self._state_lock:
            self._scenario_status = status
            listeners = list(self._scenario_listeners)
        for listener in listeners:
            try:
                listener(status)
            except Exception:
                # A presentation-layer listener must not stop network reception.
                continue

    def _fail_all_pending(self, error: BaseException) -> None:
        with self._request_lock:
            pending_requests = list(self._pending.values())
            self._pending.clear()
        for pending in pending_requests:
            pending.error = error
            pending.event.set()
