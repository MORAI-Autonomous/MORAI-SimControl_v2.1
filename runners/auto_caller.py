from __future__ import annotations

import threading
import time

import transport.protocol_defs as proto
import transport.tcp_transport as tcp


class AutoCaller(threading.Thread):
    """Repeat FixedStep and SaveData calls with request/response synchronization."""

    def __init__(
        self,
        tcp_sock,
        pending: dict,
        lock: threading.Lock,
        request_id_ref,
        max_calls: int,
        pending_add_fn,
        pending_pop_fn,
        step_count: int = 1,
        timeout_sec: float = 3.0,
        delay_sec: float = 0.0,
        progress_every: int = 50,
    ):
        super().__init__(daemon=True)
        self.tcp_sock = tcp_sock
        self.pending = pending
        self.lock = lock
        self.request_id_ref = request_id_ref
        self.max_calls = max_calls
        self.pending_add = pending_add_fn
        self.pending_pop = pending_pop_fn
        self.step_count = step_count
        self.timeout_sec = timeout_sec
        self.delay_sec = delay_sec
        self.progress_every = progress_every
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _next_rid(self) -> int:
        return self.request_id_ref.next()

    def _wait_or_stop(self, ev: threading.Event) -> bool:
        if self._stop_event.is_set():
            return False
        return ev.wait(self.timeout_sec)

    def run(self) -> None:
        print(f"[AUTO] started. target_steps={self.max_calls}")

        for index in range(self.max_calls):
            if self._stop_event.is_set():
                break

            rid_step = self._next_rid()
            ev_step = self.pending_add(self.pending, self.lock, rid_step, proto.MSG_TYPE_FIXED_STEP)
            tcp.send_fixed_step(self.tcp_sock, rid_step, step_count=self.step_count)

            if not self._wait_or_stop(ev_step):
                self.pending_pop(self.pending, self.lock, rid_step, proto.MSG_TYPE_FIXED_STEP)
                print(f"[AUTO][TIMEOUT/STOP] FixedStep. i={index} rid={rid_step}")
                break
            self.pending_pop(self.pending, self.lock, rid_step, proto.MSG_TYPE_FIXED_STEP)

            if self.delay_sec > 0.0:
                time.sleep(self.delay_sec)

            if self._stop_event.is_set():
                break

            rid_save = self._next_rid()
            ev_save = self.pending_add(self.pending, self.lock, rid_save, proto.MSG_TYPE_SAVE_DATA)
            tcp.send_save_data(self.tcp_sock, rid_save)

            if not self._wait_or_stop(ev_save):
                self.pending_pop(self.pending, self.lock, rid_save, proto.MSG_TYPE_SAVE_DATA)
                print(f"[AUTO][TIMEOUT/STOP] SaveData. i={index} rid={rid_save}")
                break
            self.pending_pop(self.pending, self.lock, rid_save, proto.MSG_TYPE_SAVE_DATA)

            if self.delay_sec > 0.0:
                time.sleep(self.delay_sec)

            if self.progress_every > 0 and (index + 1) % self.progress_every == 0:
                print(f"[AUTO] progress: {index + 1}/{self.max_calls}")

        print("[AUTO] stopped.")
