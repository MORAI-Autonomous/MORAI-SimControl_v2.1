# tcp_thread.py
import threading

import protocol_defs as proto
import tcp_transport as tcp


class Receiver(threading.Thread):
    """
    TCP 응답 수신 스레드.
    - tcp.recv_packet()으로 스트림 동기화 포함 수신
    - GetStatus 응답은 parse 후 출력
    - pending dict에 (request_id, msg_type) event를 set 해서 동기화 신호 제공
    """
    def __init__(self, sock, pending: dict, lock: threading.Lock):
        super().__init__(daemon=True)
        self.sock = sock
        self.pending = pending
        self.lock = lock
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        try:
            while self.running:
                msg_class, msg_type, payload_size, request_id, flag, payload = tcp.recv_packet(self.sock)

                # GetStatus 출력
                if msg_class == proto.MSG_CLASS_RESP and msg_type == proto.MSG_TYPE_GET_STATUS:
                    parsed = tcp.parse_get_status_payload(payload)
                    if parsed is not None:
                        print(
                            f"[RECV][TCP][GetStatus] rid={request_id} "
                            f"fixed_delta={parsed['fixed_delta']:.6f} step_index={parsed['step_index']} "
                            f"sim_time={parsed['seconds']}s {parsed['nanos']}ns"
                        )

                # pending sync signal
                if msg_class == proto.MSG_CLASS_RESP:
                    key = (request_id, msg_type)
                    with self.lock:
                        item = self.pending.get(key)
                        if item is not None:
                            item["ev"].set()

        except (ConnectionError, OSError) as e:
            print(f"[RECV-THREAD] stopped: {e}")
            self.running = False