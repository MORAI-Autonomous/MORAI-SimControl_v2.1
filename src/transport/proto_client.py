from __future__ import annotations

"""Client for the simulator's Proto opcodes (domain 0x01 and up) that needs no generated code.

Message definitions come from the simulator itself: GetApiSchema answers with a
google.protobuf.FileDescriptorSet, which every protobuf runtime can read, and GetApiInfo lists the
opcodes with their request/response type names. After `load_schema()` any Proto opcode can be called
by name with plain dict fields:

    with ProtoClient("127.0.0.1", 20000) as client:
        client.load_schema()
        info = client.call("GetApiInfo")

It uses its own TCP connection. The legacy receiver (tcp_thread.Receiver) drops headers whose
msg_type is not in VALID_MSG_TYPES, so Proto responses must not share its socket. Legacy opcodes are
not callable here: their payloads are hand-packed bytes with no schema.
"""

import socket
import struct
from typing import Any, Dict, List, Optional

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

import transport.protocol_defs as proto

OPCODE_GET_API_INFO   = 0x01010001
OPCODE_GET_API_SCHEMA = 0x01010002

API_OPCODE_STYLE_NAMES = {0: "UNSPECIFIED", 1: "LEGACY", 2: "PROTO"}

_MAX_PAYLOAD = 16 * 1024 * 1024


class ProtoCallError(Exception):
    """The simulator answered with a non-zero result code."""

    def __init__(self, name: str, result_code: int, detail_code: int):
        super().__init__(f"{name} failed: result={result_code} detail={detail_code}")
        self.result_code = result_code
        self.detail_code = detail_code


class ProtoClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.pool: Optional[descriptor_pool.DescriptorPool] = None
        self.protocol_version = 0
        self.simulator_version = ""
        # name -> {"opcode", "name", "style", "request_type", "response_type"}
        self.opcodes: Dict[str, Dict[str, Any]] = {}
        self._next_request_id = 1

    # ---- connection ---------------------------------------------------------

    def connect(self) -> "ProtoClient":
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = sock
        return self

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self) -> "ProtoClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- schema -------------------------------------------------------------

    def load_schema(self) -> None:
        """GetApiSchema -> descriptor pool, then GetApiInfo -> opcode list."""
        schema = descriptor_pb2.FileDescriptorSet.FromString(
            self.request(OPCODE_GET_API_SCHEMA, b"", "GetApiSchema"))
        pool = descriptor_pool.DescriptorPool()
        # The simulator orders the files so that imports come first.
        for file_proto in schema.file:
            pool.AddSerializedFile(file_proto.SerializeToString())
        self.pool = pool

        info_class = self.message_class("datamodel.GetApiInfoResponse")
        info = info_class.FromString(self.request(OPCODE_GET_API_INFO, b"", "GetApiInfo"))
        self.protocol_version = info.protocol_version
        self.simulator_version = info.simulator_version
        self.opcodes = {}
        for op in info.opcodes:
            self.opcodes[op.name] = {
                "opcode": op.opcode,
                "name": op.name,
                "style": API_OPCODE_STYLE_NAMES.get(op.style, str(op.style)),
                "request_type": op.request_type,
                "response_type": op.response_type,
            }

    def message_class(self, full_name: str):
        if self.pool is None:
            raise RuntimeError("load_schema() first")
        descriptor = self.pool.FindMessageTypeByName(full_name)
        # protobuf 4.22+ has GetMessageClass; older releases only have MessageFactory.GetPrototype.
        if hasattr(message_factory, "GetMessageClass"):
            return message_factory.GetMessageClass(descriptor)
        return message_factory.MessageFactory(self.pool).GetPrototype(descriptor)

    # ---- calls --------------------------------------------------------------

    def call(self, name: str, **fields: Any) -> Dict[str, Any]:
        """Calls a Proto opcode by name. Fields use the .proto field names; the response comes back
        as a dict with the same names. A void response returns {}."""
        op = self.opcodes.get(name)
        if op is None:
            raise KeyError(f"unknown opcode name: {name}")
        if op["style"] != "PROTO":
            raise ValueError(f"{name} is a {op['style']} opcode; only PROTO opcodes are callable")

        request = json_format.ParseDict(fields, self.message_class(op["request_type"])())
        payload = self.request(op["opcode"], request.SerializeToString(), name)
        if not op["response_type"]:
            return {}
        response = self.message_class(op["response_type"]).FromString(payload)
        return json_format.MessageToDict(response, preserving_proto_field_name=True)

    def request(self, opcode: int, payload: bytes, name: str = "") -> bytes:
        """Sends one request and returns the payload after the ResultCode."""
        if self.sock is None:
            raise RuntimeError("not connected")
        request_id = self._next_request_id
        self._next_request_id += 1

        header = struct.pack(proto.HEADER_FMT, proto.MAGIC, proto.MSG_CLASS_REQ, opcode,
                             len(payload), request_id, proto.FLAG)
        self.sock.sendall(header + payload)

        label = name or f"0x{opcode:08X}"
        while True:
            msg_class, msg_type, resp_id, body = self._recv_packet()
            # Notifications and stray responses can arrive on any connection; skip them.
            if msg_class != proto.MSG_CLASS_RESP or msg_type != opcode or resp_id != request_id:
                continue
            if len(body) < proto.RESULT_SIZE:
                raise ProtoCallError(label, -1, -1)
            result_code, detail_code = struct.unpack_from(proto.RESULT_FMT, body)
            if result_code != 0:
                raise ProtoCallError(label, result_code, detail_code)
            return body[proto.RESULT_SIZE:]

    def _recv_packet(self):
        header = self._recv_exact(proto.HEADER_SIZE)
        magic, msg_class, msg_type, payload_size, request_id, _flag = struct.unpack(
            proto.HEADER_FMT, header)
        if magic != proto.MAGIC or payload_size > _MAX_PAYLOAD:
            raise ConnectionError(f"invalid header: magic=0x{magic:02X} payload_size={payload_size}")
        body = self._recv_exact(payload_size) if payload_size else b""
        return msg_class, msg_type, request_id, body

    def _recv_exact(self, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            chunk = self.sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("socket closed by peer")
            buf.extend(chunk)
        return bytes(buf)


def format_api_info(client: ProtoClient) -> List[str]:
    """GetApiInfo as printable lines: one header, then one row per opcode."""
    lines = [f"protocol v{client.protocol_version}  simulator {client.simulator_version or '-'}  "
             f"opcodes {len(client.opcodes)}"]
    for op in sorted(client.opcodes.values(), key=lambda o: o["opcode"]):
        response = op["response_type"] or "void"
        lines.append(f"  0x{op['opcode']:08X}  {op['style']:<6}  {op['name']:<24}  "
                     f"{op['request_type']} -> {response}")
    return lines
