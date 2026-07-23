from __future__ import annotations

import http.cookiejar
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from demo.headless_launcher import (
    ActiveSessionError,
    MoraiHeadlessLogin,
    SimulatorAlreadyRunningError,
    find_running_simulator_pid,
    launch_headless_simulator,
    load_or_create_hardware_hash,
)


class HeadlessLauncherTests(unittest.TestCase):
    def test_login_request_uses_account_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={"success": False, "message": "code sent", "errorCode": 2235}
        )

        tokens = login.login("secret")

        self.assertIsNone(tokens)
        endpoint, body = login._post_json.call_args[0]
        self.assertEqual(endpoint, "/auth/login")
        self.assertEqual(body["email"], "driver@example.com")
        self.assertEqual(body["password"], "secret")
        self.assertEqual(body["userType"], "CUSTOMER")
        self.assertEqual(body["hardwareHash"], login.hardware_hash)

    def test_email_verification_required_is_the_next_login_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={
                "success": False,
                "message": "이메일 인증이 필요합니다.",
                "errorCode": 2235,
            }
        )

        self.assertIsNone(login.login("secret"))

    def test_trusted_device_login_returns_tokens_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={
                "success": True,
                "data": {"accessToken": "access-value", "refreshToken": "refresh-value"},
            }
        )

        tokens = login.login("secret")

        self.assertEqual(tokens, {
            "access_token": "access-value",
            "refresh_token": "refresh-value",
        })

    def test_verify_returns_access_and_refresh_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={"success": True, "data": {"accessToken": "access-value"}}
        )
        login._cookies.set_cookie(_cookie("refresh_token", "refresh-value"))

        tokens = login.verify("123456")

        self.assertEqual(tokens["access_token"], "access-value")
        self.assertEqual(tokens["refresh_token"], "refresh-value")
        _, body = login._post_json.call_args[0]
        self.assertEqual(login._post_json.call_args[0][0], "/auth/mail/verify")
        self.assertEqual(body["verificationCode"], "123456")
        self.assertEqual(body["hardwareHash"], login.hardware_hash)
        self.assertEqual(body["authType"], "AUTH_LOGIN_VERIFICATION")

    def test_active_session_requires_explicit_force_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={"success": False, "message": "existing active session"}
        )

        with self.assertRaises(ActiveSessionError):
            login.verify("123456")

    def test_force_login_uses_force_verification_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._post_json = Mock(
            return_value={
                "success": True,
                "data": {"accessToken": "access-value", "refreshToken": "refresh-value"},
            }
        )

        login.force_verify("123456")

        endpoint, body = login._post_json.call_args[0]
        self.assertEqual(endpoint, "/auth/mail/verify/force-login")
        self.assertEqual(body["verificationCode"], "123456")

    def test_hardware_hash_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hardware_hash"
            first = load_or_create_hardware_hash(path)
            second = load_or_create_hardware_hash(path)

        self.assertEqual(first, second)

    def test_launch_credentials_use_account_name_and_assigned_product(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            login = _login(Path(temp_dir))
        login._get_json = Mock(side_effect=[
            {"success": True, "data": {"name": "launch-account"}},
            {
                "success": True,
                "data": {"products": [{"productUid": "S90000"}]},
            },
        ])

        credentials = login.resolve_launch_credentials({
            "access_token": "access-value",
            "refresh_token": "refresh-value",
        })

        self.assertEqual(credentials["user_id"], "launch-account")
        self.assertEqual(credentials["product_uid"], "S90000")
        self.assertEqual(login._get_json.call_args_list[0][0][0], "/auth/token")
        self.assertEqual(
            login._get_json.call_args_list[1][0][0],
            "/for-launcher/user/products",
        )

    def test_launcher_passes_headless_arguments_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "MoraiSimulator.exe"
            executable.touch()
            process = Mock(pid=4321)
            with patch("demo.headless_launcher.find_running_simulator_pid", return_value=None), patch(
                "demo.headless_launcher.subprocess.Popen", return_value=process
            ) as popen:
                result = launch_headless_simulator(
                    str(executable),
                    "launch-account",
                    "access-value",
                    "refresh-value",
                    product_uid="S90000",
                )

        self.assertIs(result, process)
        arguments = popen.call_args[0][0]
        self.assertEqual(arguments[1:], [
            "--userId=launch-account",
            "--accessToken=access-value",
            "--refreshToken=refresh-value",
            "--productUid=S90000",
            "--mode=headless",
            "-nullrhi",
        ])

    def test_running_shipping_process_is_detected(self) -> None:
        tasklist = Mock(
            stdout='"MoraiSimulator-Win64-Shipping.exe","29196","Console","1","1 K"\n'
        )
        with patch("demo.headless_launcher.os.name", "nt"), patch(
            "demo.headless_launcher.subprocess.run", return_value=tasklist
        ):
            pid = find_running_simulator_pid()

        self.assertEqual(pid, 29196)

    def test_launcher_rejects_duplicate_simulator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "MoraiSimulator.exe"
            executable.touch()
            with patch("demo.headless_launcher.find_running_simulator_pid", return_value=35504):
                with self.assertRaises(SimulatorAlreadyRunningError):
                    launch_headless_simulator(
                        str(executable),
                        "driver@example.com",
                        "access-value",
                        "refresh-value",
                    )


def _cookie(name: str, value: str) -> http.cookiejar.Cookie:
    return http.cookiejar.Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain="v2-dev-api.morai-sim.com",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def _login(temp_dir: Path) -> MoraiHeadlessLogin:
    return MoraiHeadlessLogin(
        "driver@example.com",
        hardware_hash_file=temp_dir / "hardware_hash",
    )


if __name__ == "__main__":
    unittest.main()
