from __future__ import annotations

import http.cookiejar
import csv
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
from typing import Any, Dict, Iterable, Mapping, Optional
import urllib.error
import urllib.request


DEFAULT_API_BASE_URL = "https://v2-prd-api.morai-sim.com:8080"
DEFAULT_PRODUCT_UID = "S00002"
EMAIL_VERIFICATION_REQUIRED = "2235"
DEFAULT_HARDWARE_HASH_FILE = Path.home() / ".morai_login" / "hardware_hash"


class HeadlessLoginError(ValueError):
    pass


class ActiveSessionError(HeadlessLoginError):
    pass


class SimulatorAlreadyRunningError(ValueError):
    def __init__(self, pid: int) -> None:
        super().__init__(f"Simulator is already running (PID {pid})")
        self.pid = pid


class MoraiHeadlessLogin:
    def __init__(
        self,
        email: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        user_type: str = "CUSTOMER",
        timeout: float = 30.0,
        hardware_hash_file: Path = DEFAULT_HARDWARE_HASH_FILE,
    ) -> None:
        self.email = email
        self.api_base_url = api_base_url.rstrip("/")
        self.user_type = user_type
        self.timeout = timeout
        self.hardware_hash = load_or_create_hardware_hash(hardware_hash_file)
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )

    def login(self, password: str) -> Optional[Dict[str, str]]:
        response = self._post_json(
            "/auth/login",
            {
                "email": self.email,
                "password": password,
                "userType": self.user_type,
                "hardwareHash": self.hardware_hash,
                "autoLogin": False,
            },
        )
        error_code = str(response.get("errorCode", "")).strip()
        if error_code == EMAIL_VERIFICATION_REQUIRED:
            return None
        _ensure_success(response, "Login failed")
        return _tokens_from_response(response, self._cookies, required=False)

    def verify(self, verification_code: str) -> Dict[str, str]:
        response = self._post_json(
            "/auth/mail/verify",
            {
                "email": self.email,
                "verificationCode": verification_code,
                "userType": self.user_type,
                "authType": "AUTH_LOGIN_VERIFICATION",
                "hardwareHash": self.hardware_hash,
                "autoLogin": False,
            },
        )
        try:
            _ensure_success(response, "Verification failed")
        except HeadlessLoginError as exc:
            if _requires_session_invalidation(exc):
                raise ActiveSessionError(str(exc)) from exc
            raise
        tokens = _tokens_from_response(response, self._cookies, required=True)
        assert tokens is not None
        return tokens

    def force_verify(self, verification_code: str) -> Dict[str, str]:
        response = self._post_json(
            "/auth/mail/verify/force-login",
            {
                "email": self.email,
                "verificationCode": verification_code,
                "userType": self.user_type,
            },
        )
        _ensure_success(response, "Force login failed")
        tokens = _tokens_from_response(response, self._cookies, required=True)
        assert tokens is not None
        return tokens

    def resolve_launch_credentials(self, tokens: Mapping[str, str]) -> Dict[str, str]:
        access_token = str(tokens.get("access_token", "")).strip()
        refresh_token = str(tokens.get("refresh_token", "")).strip()
        if not access_token or not refresh_token:
            raise HeadlessLoginError("Login tokens are incomplete")

        token_response = self._get_json("/auth/token", access_token)
        token_data = _response_data(token_response, "Could not read account information")
        account_name = str(
            token_data.get("name")
            or token_data.get("userName")
            or token_data.get("email")
            or self.email
        ).strip()

        products_response = self._get_json("/for-launcher/user/products", access_token)
        products_data = _response_data(products_response, "Could not read assigned products")
        products = products_data.get("products")
        if not isinstance(products, list):
            raise HeadlessLoginError("Product response does not contain a products list")
        product_uid = next(
            (
                str(product.get("productUid", "")).strip()
                for product in products
                if isinstance(product, Mapping) and product.get("productUid")
            ),
            "",
        )
        if not product_uid:
            raise HeadlessLoginError("No simulator product is assigned to this account")
        if not account_name:
            raise HeadlessLoginError("Account information does not contain a launch user ID")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_id": account_name,
            "product_uid": product_uid,
        }

    def _post_json(self, endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self.api_base_url}{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Accept": "application/json,*/*",
                "Content-Type": "application/json",
                "Referer": f"{self.api_base_url}/swagger-ui/index.html",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        return self._open_json(request)

    def _get_json(self, endpoint: str, access_token: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self.api_base_url}{endpoint}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        return self._open_json(request)

    def _open_json(self, request: urllib.request.Request) -> Dict[str, Any]:
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            try:
                error_result = json.loads(payload)
            except json.JSONDecodeError:
                raise HeadlessLoginError(f"Login API returned HTTP {exc.code}") from exc
            if isinstance(error_result, dict):
                return error_result
            raise HeadlessLoginError(f"Login API returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise HeadlessLoginError(f"Could not reach login API: {exc.reason}") from exc
        try:
            result = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HeadlessLoginError("Login API returned an invalid response") from exc
        if not isinstance(result, dict):
            raise HeadlessLoginError("Login API response must be a JSON object")
        return result


def launch_simulator(
    simulator_path: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
    product_uid: str = DEFAULT_PRODUCT_UID,
    headless: bool = True,
) -> subprocess.Popen:
    executable = Path(simulator_path).expanduser().resolve()
    if not executable.is_file():
        raise ValueError(f"Simulator executable not found: {executable}")
    if executable.suffix.lower() != ".exe":
        raise ValueError("Simulator path must point to an .exe file")
    running_pid = find_running_simulator_pid()
    if running_pid is not None:
        raise SimulatorAlreadyRunningError(running_pid)
    arguments = [
        str(executable),
        f"--userId={user_id}",
        f"--accessToken={access_token}",
        f"--refreshToken={refresh_token}",
        f"--productUid={product_uid}",
    ]
    if headless:
        arguments.extend(["--mode=headless", "-nullrhi"])
    return subprocess.Popen(arguments, cwd=str(executable.parent))


def launch_headless_simulator(
    simulator_path: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
    product_uid: str = DEFAULT_PRODUCT_UID,
) -> subprocess.Popen:
    return launch_simulator(
        simulator_path=simulator_path,
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        product_uid=product_uid,
        headless=True,
    )


def find_running_simulator_pid() -> Optional[int]:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    simulator_names = {
        "moraisimulator.exe",
        "moraisimulator-win64-shipping.exe",
    }
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) < 2 or row[0].strip().lower() not in simulator_names:
            continue
        try:
            return int(row[1].replace(",", "").strip())
        except ValueError:
            continue
    return None


def _response_error(response: Dict[str, Any], fallback: str) -> str:
    message = str(response.get("message", "")).strip()
    error_code = str(response.get("errorCode", "")).strip()
    if message and error_code:
        return f"{message} ({error_code})"
    return message or error_code or fallback


def load_or_create_hardware_hash(path: Path = DEFAULT_HARDWARE_HASH_FILE) -> str:
    target = path.expanduser()
    if target.is_file():
        value = target.read_text(encoding="utf-8").strip()
        if value:
            return value
        raise HeadlessLoginError(f"Trusted-device file is empty: {target}")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = secrets.token_urlsafe(32)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_or_create_hardware_hash(target)
    with os.fdopen(descriptor, "w", encoding="utf-8") as hardware_file:
        hardware_file.write(value + "\n")
    return value


def _ensure_success(response: Mapping[str, Any], fallback: str) -> None:
    if response.get("success") is False:
        raise HeadlessLoginError(_response_error(dict(response), fallback))


def _response_data(response: Mapping[str, Any], fallback: str) -> Mapping[str, Any]:
    _ensure_success(response, fallback)
    data = response.get("data", response)
    if not isinstance(data, Mapping):
        raise HeadlessLoginError(f"{fallback}: invalid data response")
    return data


def _tokens_from_response(
    response: Mapping[str, Any],
    cookies: Iterable[Any],
    required: bool,
) -> Optional[Dict[str, str]]:
    access_token = _find_value(response, {"accessToken", "access_token"})
    refresh_token = _find_value(response, {"refreshToken", "refresh_token"})
    if not refresh_token:
        refresh_token = next(
            (
                str(cookie.value)
                for cookie in cookies
                if cookie.name.lower() in {"refresh_token", "refreshtoken", "refresh", "rt"}
                and cookie.value
            ),
            "",
        )
    if not access_token:
        if required:
            raise HeadlessLoginError("Authentication did not return an access token")
        return None
    if not refresh_token:
        raise HeadlessLoginError("Authentication did not return a refresh token")
    return {"access_token": access_token, "refresh_token": refresh_token}


def _find_value(value: Any, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in wanted and isinstance(item, str) and item:
                return item
        for item in value.values():
            found = _find_value(item, wanted)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_value(item, wanted)
            if found:
                return found
    return ""


def _requires_session_invalidation(error: HeadlessLoginError) -> bool:
    text = str(error).lower()
    return "기존 활성 세션" in text or "active session" in text
