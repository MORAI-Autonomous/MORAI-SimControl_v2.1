from __future__ import annotations

from pathlib import Path
import contextlib
import io
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from transport.message_schema import pack_message_payload
import transport.protocol_defs as proto
import transport.tcp_transport as tcp


class TcpPayloadGoldenTests(unittest.TestCase):
    def test_fixed_step_payload_includes_monotonic_timestamps(self) -> None:
        sent = []

        class FakeSocket:
            def sendall(self, data: bytes) -> None:
                sent.append(data)

        sock = FakeSocket()
        before_ns = time.perf_counter_ns()
        tcp.send_fixed_step(sock, 23, step_count=2)
        after_ns = time.perf_counter_ns()

        packet = sent[0]
        _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
            proto.HEADER_FMT,
            packet[:proto.HEADER_SIZE],
        )
        step_count, save_mode, client_recv_ns, client_send_ns = struct.unpack(
            "<IBQQ",
            packet[proto.HEADER_SIZE:],
        )
        self.assertEqual(msg_class, proto.MSG_CLASS_REQ)
        self.assertEqual(msg_type, proto.MSG_TYPE_FIXED_STEP)
        self.assertEqual(payload_size, 21)
        self.assertEqual(request_id, 23)
        self.assertEqual(flag, proto.FLAG)
        self.assertEqual(step_count, 2)
        self.assertEqual(save_mode, proto.SAVE_MODE_SKIP)
        self.assertEqual(client_recv_ns, client_send_ns)
        self.assertLessEqual(before_ns, client_send_ns)
        self.assertLessEqual(client_send_ns, after_ns)

    def test_fixed_step_uses_previous_response_receive_timestamp(self) -> None:
        response_payload = struct.pack("<II", 0, 0)
        response = (
            tcp.build_header(
                proto.MSG_CLASS_RESP,
                proto.MSG_TYPE_FIXED_STEP,
                len(response_payload),
                request_id=41,
                flag=proto.FLAG,
            )
            + response_payload
        )

        class FakeSocket:
            def __init__(self) -> None:
                self.received = bytearray(response)
                self.sent = []

            def recv(self, size: int) -> bytes:
                chunk = bytes(self.received[:size])
                del self.received[:size]
                return chunk

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

        sock = FakeSocket()
        before_recv_ns = time.perf_counter_ns()
        tcp.recv_packet(sock)
        after_recv_ns = time.perf_counter_ns()
        tcp.send_fixed_step(sock, 42, step_count=1)

        step_count, save_mode, client_recv_ns, client_send_ns = struct.unpack(
            "<IBQQ",
            sock.sent[0][proto.HEADER_SIZE:],
        )
        self.assertEqual(step_count, 1)
        self.assertEqual(save_mode, proto.SAVE_MODE_SKIP)
        self.assertLessEqual(before_recv_ns, client_recv_ns)
        self.assertLessEqual(client_recv_ns, after_recv_ns)
        self.assertLessEqual(client_recv_ns, client_send_ns)

    def test_fixed_step_payload_accepts_save_mode(self) -> None:
        sent = []

        class FakeSocket:
            def sendall(self, data: bytes) -> None:
                sent.append(data)

        tcp.send_fixed_step(
            FakeSocket(),
            24,
            step_count=1,
            save_mode=proto.SAVE_MODE_FORCE,
        )

        step_count, save_mode, _, _ = struct.unpack(
            "<IBQQ",
            sent[0][proto.HEADER_SIZE:],
        )
        self.assertEqual(step_count, 1)
        self.assertEqual(save_mode, proto.SAVE_MODE_FORCE)

    def test_fixed_step_rejects_unknown_save_mode(self) -> None:
        class FakeSocket:
            def sendall(self, _data: bytes) -> None:
                pass

        with self.assertRaisesRegex(ValueError, "Unsupported save mode"):
            tcp.send_fixed_step(FakeSocket(), 25, step_count=1, save_mode=3)

    def test_shutdown_simulator_payload_is_one_byte(self) -> None:
        self.assertEqual(
            pack_message_payload(
                proto.MSG_TYPE_SHUTDOWN_SIMULATOR,
                {"b_force": 0},
            ),
            b"\x00",
        )
        self.assertEqual(
            pack_message_payload(
                proto.MSG_TYPE_SHUTDOWN_SIMULATOR,
                {"b_force": 1},
            ),
            b"\x01",
        )

    def test_parse_set_simulation_time_mode_result_only_response(self) -> None:
        payload = struct.pack("<II", 0, 0)

        parsed = tcp.parse_set_simulation_time_mode_payload(payload)

        self.assertEqual(parsed, {"result_code": 0, "detail_code": 0})

    def test_parse_set_simulation_time_mode_detailed_response(self) -> None:
        payload = struct.pack("<IIIff", 0, 0, 2, 0.01, 2.0)

        parsed = tcp.parse_set_simulation_time_mode_payload(payload)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["mode"], 2)

    def test_get_simulator_status_request_has_no_payload(self) -> None:
        actual = pack_message_payload(
            proto.MSG_TYPE_GET_SIMULATOR_STATUS,
            {},
        )
        self.assertEqual(actual, b"")

    def test_get_simulator_mode_request_has_no_payload(self) -> None:
        actual = pack_message_payload(
            proto.MSG_TYPE_GET_SIMULATOR_MODE,
            {},
        )
        self.assertEqual(actual, b"")

    def test_set_simulator_mode_payload(self) -> None:
        actual = pack_message_payload(
            proto.MSG_TYPE_SET_SIMULATOR_MODE,
            {"mode": proto.SIMULATOR_MODE_TRAFFIC},
        )
        self.assertEqual(actual, struct.pack("<I", proto.SIMULATOR_MODE_TRAFFIC))

    def test_load_map_payload(self) -> None:
        map_name = "sangam_racing_track"
        encoded = map_name.encode("utf-8")
        actual = pack_message_payload(
            proto.MSG_TYPE_LOAD_MAP,
            {"map_name": map_name},
        )
        self.assertEqual(actual, struct.pack("<I", len(encoded)) + encoded)

    def test_parse_get_simulator_mode_payload(self) -> None:
        payload = struct.pack("<III", 0, 0, proto.SIMULATOR_MODE_TRAFFIC)
        parsed = tcp.parse_get_simulator_mode_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["mode"], proto.SIMULATOR_MODE_TRAFFIC)

    def test_parse_get_simulator_mode_error_payload(self) -> None:
        payload = struct.pack("<III", 200, 10, proto.SIMULATOR_MODE_UNSPECIFIED)
        parsed = tcp.parse_get_simulator_mode_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 200)
        self.assertEqual(parsed["detail_code"], 10)
        self.assertEqual(parsed["mode"], proto.SIMULATOR_MODE_UNSPECIFIED)

    def test_set_simulation_time_mode_variable_payload(self) -> None:
        expected = struct.pack("<iiiii", 1, 60, 10, 0, 0)
        actual = pack_message_payload(
            proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
            {
                "mode": proto.TIME_MODE_VARIABLE,
                "target_fps": 60,
                "physics_delta_time": 10,
                "rtf": 0,
                "user_control": 0,
            },
        )
        self.assertEqual(actual, expected)

    def test_set_simulation_time_mode_fixed_payload(self) -> None:
        expected = struct.pack("<iiiii", 2, 60, 10, 1, 0)
        actual = pack_message_payload(
            proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
            {
                "mode": proto.TIME_MODE_FIXED,
                "target_fps": 60,
                "physics_delta_time": 10,
                "rtf": 1,
                "user_control": 0,
            },
        )
        self.assertEqual(actual, expected)

    def test_manual_control_by_id_payload(self) -> None:
        entity_id = "Car_1"
        expected = (
            struct.pack("<I", len(entity_id.encode("utf-8")))
            + entity_id.encode("utf-8")
            + struct.pack("<ddd", 0.4, 0.0, 12.5)
        )
        actual = tcp.build_manual_control_by_id_payload(entity_id, 0.4, 0.0, 12.5)
        self.assertEqual(actual, expected)

    def test_get_vehicle_info_request_uses_utf8_byte_length(self) -> None:
        entity_id = "차량_1"
        encoded = entity_id.encode("utf-8")
        self.assertEqual(
            tcp.build_get_vehicle_info_payload(entity_id),
            struct.pack("<I", len(encoded)) + encoded,
        )

    def test_get_vehicle_info_rejects_empty_id(self) -> None:
        with self.assertRaises(ValueError):
            tcp.build_get_vehicle_info_payload("")

    def test_get_vehicle_info_packet_header_matches_payload(self) -> None:
        sent = []

        class FakeSocket:
            def sendall(self, data: bytes) -> None:
                sent.append(data)

        with contextlib.redirect_stdout(io.StringIO()):
            tcp.send_get_vehicle_info(FakeSocket(), 17, "Car_1")
        packet = sent[0]
        _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
            proto.HEADER_FMT,
            packet[:proto.HEADER_SIZE],
        )
        self.assertEqual(msg_class, proto.MSG_CLASS_REQ)
        self.assertEqual(msg_type, proto.MSG_TYPE_GET_VEHICLE_INFO)
        self.assertEqual(payload_size, len(packet) - proto.HEADER_SIZE)
        self.assertEqual(request_id, 17)
        self.assertEqual(flag, proto.FLAG)

    def test_parse_get_vehicle_info_success_payload(self) -> None:
        entity_id = "Car_1"
        encoded = entity_id.encode("utf-8")
        values = tuple(float(value) for value in range(1, 19))
        payload = (
            struct.pack("<IIqiI", 0, 0, 123, 456, len(encoded))
            + encoded
            + struct.pack("<18f", *values)
        )

        parsed = tcp.parse_get_vehicle_info_payload(payload)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["seconds"], 123)
        self.assertEqual(parsed["nanos"], 456)
        self.assertEqual(parsed["entity_id"], entity_id)
        self.assertEqual(parsed["location"], {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertEqual(parsed["local_velocity"], {"x": 7.0, "y": 8.0, "z": 9.0})
        self.assertEqual(parsed["control"], {
            "throttle": 16.0,
            "brake": 17.0,
            "steer_angle": 18.0,
        })
        self.assertEqual(parsed["raw_size"], 96 + len(encoded))

    def test_parse_get_vehicle_info_failure_payload(self) -> None:
        parsed = tcp.parse_get_vehicle_info_payload(struct.pack("<II", 102, 7))
        self.assertEqual(parsed, {"result_code": 102, "detail_code": 7})

    def test_parse_get_vehicle_info_rejects_malformed_success_payload(self) -> None:
        payload = struct.pack("<IIqiI", 0, 0, 1, 2, 5) + b"Car" + struct.pack("<18f", *([0.0] * 18))
        self.assertIsNone(tcp.parse_get_vehicle_info_payload(payload))

    def test_transform_control_by_id_payload(self) -> None:
        entity_id = "Car_2"
        expected = (
            struct.pack("<I", len(entity_id.encode("utf-8")))
            + entity_id.encode("utf-8")
            + struct.pack("<fffffffd", -1.0, 2.5, 3.0, 10.0, 20.0, 30.0, 4.5, 6.75)
        )
        actual = tcp.build_transform_control_by_id_payload(
            entity_id,
            -1.0,
            2.5,
            3.0,
            10.0,
            20.0,
            30.0,
            4.5,
            6.75,
        )
        self.assertEqual(actual, expected)

    def test_set_trajectory_payload(self) -> None:
        entity_id = "Car_1"
        trajectory_name = "lane_change"
        points = [
            (1.0, 2.0, 3.0, 0.0),
            (4.0, 5.0, 6.0, 0.5),
        ]
        expected = (
            struct.pack("<I", len(entity_id.encode("utf-8")))
            + entity_id.encode("utf-8")
            + struct.pack("<i", 1)
            + struct.pack("<I", len(trajectory_name.encode("utf-8")))
            + trajectory_name.encode("utf-8")
            + struct.pack("<I", len(points))
            + b"".join(struct.pack("<dddd", *point) for point in points)
        )
        actual = tcp.build_set_trajectory_payload(
            entity_id=entity_id,
            follow_mode=1,
            trajectory_name=trajectory_name,
            points=points,
        )
        self.assertEqual(actual, expected)

    def test_set_trajectory_packet_header_matches_payload_size(self) -> None:
        sent = []
        points = [
            (1.0, 2.0, 3.0, 0.0),
            (4.0, 5.0, 6.0, 0.5),
        ]

        class FakeSocket:
            def sendall(self, data: bytes) -> None:
                sent.append(data)

        with contextlib.redirect_stdout(io.StringIO()):
            tcp.send_set_trajectory(
                FakeSocket(),
                9,
                entity_id="Car_1",
                follow_mode=2,
                trajectory_name="Route_1",
                points=points,
            )
        packet = sent[0]
        _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
            proto.HEADER_FMT,
            packet[:proto.HEADER_SIZE],
        )
        self.assertEqual(msg_class, proto.MSG_CLASS_REQ)
        self.assertEqual(msg_type, proto.MSG_TYPE_SET_TRAJECTORY_COMMAND)
        self.assertEqual(payload_size, len(packet) - proto.HEADER_SIZE)
        self.assertEqual(request_id, 9)
        self.assertEqual(flag, proto.FLAG)

    def test_load_suite_payload(self) -> None:
        suite_path = "C:/Suite/Test.suite"
        expected = struct.pack("<I", len(suite_path.encode("utf-8"))) + suite_path.encode("utf-8")
        actual = pack_message_payload(
            proto.MSG_TYPE_LOAD_SUITE,
            {"suite_path": suite_path},
        )
        self.assertEqual(actual, expected)

    def test_load_traffic_scenario_payload(self) -> None:
        file_path = "C:/Traffic/Test.anmroutes"
        expected = struct.pack("<I", len(file_path.encode("utf-8"))) + file_path.encode("utf-8")
        actual = pack_message_payload(
            proto.MSG_TYPE_LOAD_TRAFFIC_SCENARIO,
            {"file_path": file_path},
        )
        self.assertEqual(actual, expected)

    def test_traffic_generate_payload(self) -> None:
        actual = pack_message_payload(
            proto.MSG_TYPE_TRAFFIC_GENERATE,
            {
                "autonomous": 1,
                "lc_rate": 25,
            },
        )
        self.assertEqual(actual, struct.pack("<ii", 1, 25))

    def test_scenario_control_payload(self) -> None:
        expected = struct.pack("<I", 3) + struct.pack("<I", 0)
        actual = pack_message_payload(
            proto.MSG_TYPE_SCENARIO_CONTROL,
            {
                "command": 3,
                "scenario_name": "",
            },
        )
        self.assertEqual(actual, expected)

    def test_delete_object_payload_is_raw_entity_id(self) -> None:
        actual = tcp.pack_message_payload(
            proto.MSG_TYPE_DELETE_OBJECT,
            {"entity_id": "Car_1"},
        )
        self.assertEqual(actual, b"Car_1")

    def test_delete_object_packet_header_uses_raw_string_size(self) -> None:
        sent = []

        class FakeSocket:
            def sendall(self, data: bytes) -> None:
                sent.append(data)

        with contextlib.redirect_stdout(io.StringIO()):
            tcp.send_delete_object(FakeSocket(), 7, "Car_1")
        packet = sent[0]
        self.assertEqual(len(packet), proto.HEADER_SIZE + len(b"Car_1"))
        _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
            proto.HEADER_FMT,
            packet[:proto.HEADER_SIZE],
        )
        self.assertEqual(msg_class, proto.MSG_CLASS_REQ)
        self.assertEqual(msg_type, proto.MSG_TYPE_DELETE_OBJECT)
        self.assertEqual(payload_size, len(b"Car_1"))
        self.assertEqual(request_id, 7)
        self.assertEqual(flag, proto.FLAG)
        self.assertEqual(packet[proto.HEADER_SIZE:], b"Car_1")

    def test_parse_get_status_variable_payload(self) -> None:
        payload = struct.pack(
            proto.GET_STATUS_FMT,
            0,
            0,
            proto.TIME_MODE_VARIABLE,
            60,
            10,
            0,
            0,
            123,
            45,
            678,
        )
        parsed = tcp.parse_get_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["mode"], proto.TIME_MODE_VARIABLE)
        self.assertEqual(parsed["target_fps"], 60)
        self.assertEqual(parsed["physics_delta_time"], 10)
        self.assertEqual(parsed["rtf"], 0)
        self.assertEqual(parsed["user_control"], 0)
        self.assertEqual(parsed["step_index"], 123)
        self.assertEqual(parsed["seconds"], 45)
        self.assertEqual(parsed["nanos"], 678)

    def test_parse_get_simulator_status_payload(self) -> None:
        payload = struct.pack(proto.GET_SIMULATOR_STATUS_FMT, 0, 0, 4)
        parsed = tcp.parse_get_simulator_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["state"], 4)

    def test_parse_get_simulator_status_notification_payload(self) -> None:
        payload = bytes([0x08, 0x04])
        parsed = tcp.parse_get_simulator_status_notification_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["state"], 4)

    def test_parse_get_status_fixed_payload(self) -> None:
        payload = struct.pack(
            proto.GET_STATUS_FMT,
            0,
            0,
            proto.TIME_MODE_FIXED,
            60,
            10,
            2,
            1,
            456,
            78,
            901,
        )
        parsed = tcp.parse_get_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["mode"], proto.TIME_MODE_FIXED)
        self.assertEqual(parsed["target_fps"], 60)
        self.assertEqual(parsed["physics_delta_time"], 10)
        self.assertEqual(parsed["rtf"], 2)
        self.assertEqual(parsed["user_control"], 1)
        self.assertEqual(parsed["step_index"], 456)
        self.assertEqual(parsed["seconds"], 78)
        self.assertEqual(parsed["nanos"], 901)

    def test_parse_create_object_payload(self) -> None:
        object_id = "Car_9"
        payload = (
            struct.pack(proto.RESULT_FMT, 0, 0)
            + struct.pack("<I", len(object_id.encode("utf-8")))
            + object_id.encode("utf-8")
        )
        parsed = tcp.parse_create_object_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["object_id"], object_id)

    def test_parse_active_suite_status_payload(self) -> None:
        suite_name = "테스트 Suite"
        scenario_name = "시나리오 01"
        scenario_list = ["시나리오 01", "시나리오 02"]
        payload = (
            struct.pack(proto.RESULT_FMT, 0, 0)
            + struct.pack("<I", len(suite_name.encode("utf-8")))
            + suite_name.encode("utf-8")
            + struct.pack("<I", len(scenario_name.encode("utf-8")))
            + scenario_name.encode("utf-8")
            + struct.pack("<I", len(scenario_list))
            + b"".join(
                struct.pack("<I", len(name.encode("utf-8"))) + name.encode("utf-8")
                for name in scenario_list
            )
        )
        parsed = tcp.parse_active_suite_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["active_suite_name"], suite_name)
        self.assertEqual(parsed["active_scenario_name"], scenario_name)
        self.assertEqual(parsed["scenario_list"], scenario_list)

    def test_parse_scenario_status_payload(self) -> None:
        name = "Scenario_A"
        payload = (
            struct.pack("<III", 0, 0, 4)
            + struct.pack("<I", len(name.encode("utf-8")))
            + name.encode("utf-8")
        )
        parsed = tcp.parse_scenario_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["state"], 4)
        self.assertEqual(parsed["name"], name)

    def test_parse_scenario_status_payload_legacy_without_name(self) -> None:
        payload = struct.pack("<III", 0, 0, 3)
        parsed = tcp.parse_scenario_status_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result_code"], 0)
        self.assertEqual(parsed["detail_code"], 0)
        self.assertEqual(parsed["state"], 3)
        self.assertEqual(parsed["name"], "")

    def test_parse_scenario_status_notification_payload(self) -> None:
        name = "Scenario_A"
        payload = bytes([0x08, 0x04, 0x12, len(name)]) + name.encode("utf-8")
        parsed = tcp.parse_scenario_status_notification_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["state"], 4)
        self.assertEqual(parsed["name"], name)


if __name__ == "__main__":
    unittest.main()
