from __future__ import annotations

import threading
import time

import numpy as np


MAX_STEER_RAD = 0.5


class Ros2AdRunner:
    """
    ROS2 Path Follow runner for the ID-less single-vehicle interface.

    Subscribes to morai_v2_1_ros2_msgs/msg/VehicleInfo and publishes
    morai_v2_1_ros2_msgs/msg/VehicleManualControl. The path-following
    calculation intentionally matches AdRunner's normal path-follow mode.
    """

    def __init__(
        self,
        vehicle_info_topic: str = "/VehicleInfo",
        manual_control_topic: str = "/ManualControl",
        path_file: str = "path_link.csv",
        map_name: str | None = None,
        max_speed_kph: float | None = None,
        entity_id: str = "ROS2",
        node_name: str = "morai_path_follow",
        log_fn=None,
        status_cb=None,
    ):
        self._vehicle_info_topic = vehicle_info_topic
        self._manual_control_topic = manual_control_topic
        self._node_name = node_name
        self._max_speed_kph = max_speed_kph
        self._entity_id = entity_id
        self._log = log_fn or (lambda msg, level="INFO": print(f"[ROS2 AD] {msg}"))
        self._status_cb = status_cb or (lambda *a: None)

        from autonomous_driving.autonomous_driving import AutonomousDriving
        from autonomous_driving.vehicle_state import VehicleState

        self._ad = AutonomousDriving(path_file, map_name=map_name, max_speed_kph=max_speed_kph)
        self._vehicle_state_cls = VehicleState
        self._running = False
        self._thread: threading.Thread | None = None
        self._node = None
        self._publisher = None
        self._manual_control_cls = None
        self._rclpy = None
        self._last_vehicle_info_t = 0.0
        self._last_graph_log_t = 0.0
        self._last_command_log_t = 0.0
        self._rx_count = 0
        self._tx_count = 0

    def start(self) -> None:
        if self._running:
            self._log("already running", "WARN")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._spin,
            daemon=True,
            name="ros2-ad-runner",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None
        if self._rclpy is not None:
            try:
                self._rclpy.shutdown()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._log("stopped")

    def update_max_speed_kph(self, max_speed_kph: float) -> None:
        self._max_speed_kph = float(max_speed_kph)
        self._ad.set_max_speed_kph(self._max_speed_kph)

    def _spin(self) -> None:
        try:
            import rclpy
            from rclpy.qos import QoSProfile, ReliabilityPolicy
            from morai_v2_1_ros2_msgs.msg import VehicleInfo, VehicleManualControl
        except Exception as e:
            self._running = False
            self._log(f"ROS2 import failed: {e}", "ERROR")
            return

        self._rclpy = rclpy
        try:
            if not rclpy.ok():
                rclpy.init(args=None)
            self._node = rclpy.create_node(self._node_name)
            self._manual_control_cls = VehicleManualControl
            self._publisher = self._node.create_publisher(
                VehicleManualControl,
                self._manual_control_topic,
                10,
            )
            vi_qos = QoSProfile(depth=10)
            vi_qos.reliability = ReliabilityPolicy.BEST_EFFORT
            self._node.create_subscription(
                VehicleInfo,
                self._vehicle_info_topic,
                self._on_vehicle_info,
                vi_qos,
            )
            self._log(f"VehicleInfo subscribe : {self._vehicle_info_topic}")
            self._log(f"ManualControl publish : {self._manual_control_topic}")
            self._log("path follow started")

            while self._running and rclpy.ok():
                rclpy.spin_once(self._node, timeout_sec=0.1)
                self._log_graph_status()
        except Exception as e:
            self._log(f"ROS2 runner error: {e}", "ERROR")
        finally:
            self._running = False

    def _log_graph_status(self) -> None:
        if self._node is None:
            return
        now = time.monotonic()
        if now - self._last_graph_log_t < 2.0:
            return
        self._last_graph_log_t = now
        vi_publishers = self._node.count_publishers(self._vehicle_info_topic)
        ctrl_subscribers = self._node.count_subscribers(self._manual_control_topic)
        if vi_publishers == 0 or ctrl_subscribers == 0:
            self._log(
                "ROS2 graph waiting: "
                f"{self._vehicle_info_topic} publishers={vi_publishers}, "
                f"{self._manual_control_topic} subscribers={ctrl_subscribers}",
                "WARN",
            )
            return
        if self._last_vehicle_info_t <= 0.0:
            self._log(
                "ROS2 graph matched, waiting for first VehicleInfo message "
                f"on {self._vehicle_info_topic}",
                "INFO",
            )
            return
        age = now - self._last_vehicle_info_t
        if age > 1.0:
            self._log(
                f"VehicleInfo timeout: last message {age:.1f}s ago "
                f"(rx={self._rx_count}, tx={self._tx_count})",
                "WARN",
            )

    def _on_vehicle_info(self, msg) -> None:
        if self._publisher is None or self._manual_control_cls is None:
            return
        try:
            now = time.monotonic()
            first_msg = self._rx_count == 0
            self._rx_count += 1
            self._last_vehicle_info_t = now
            vs = self._vehicle_state_cls(
                x=float(msg.position.x),
                y=float(msg.position.y),
                yaw=float(np.deg2rad(msg.rotation.z)),
                velocity=float(msg.local_velocity.x),
            )
            ctrl, _ = self._ad.execute(vs)
            steer_norm = float(np.clip(ctrl.steering / MAX_STEER_RAD, -1.0, 1.0))
            throttle = float(ctrl.accel)
            brake = float(ctrl.brake)

            out = self._manual_control_cls()
            out.throttle = throttle
            out.brake = brake
            out.steering_wheel_angle = steer_norm
            self._publisher.publish(out)
            self._tx_count += 1

            if first_msg:
                self._log(
                    "first VehicleInfo received: "
                    f"pos=({vs.position.x:.2f}, {vs.position.y:.2f}), "
                    f"yaw={msg.rotation.z:.2f}deg, "
                    f"vel={vs.velocity * 3.6:.1f}km/h",
                    "INFO",
                )
            if now - self._last_command_log_t >= 1.0:
                self._last_command_log_t = now
                self._log(
                    "publish ManualControl: "
                    f"throttle={throttle:.3f}, brake={brake:.3f}, "
                    f"steer={steer_norm:.3f}, rx={self._rx_count}, tx={self._tx_count}",
                    "INFO",
                )

            self._status_cb(
                self._entity_id,
                vs.position.x,
                vs.position.y,
                vs.velocity * 3.6,
                throttle,
                brake,
                steer_norm,
            )
        except Exception as e:
            self._log(f"control error: {e}", "ERROR")


def main() -> None:
    runner = Ros2AdRunner()
    try:
        runner.start()
        while runner._running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()


if __name__ == "__main__":
    main()
