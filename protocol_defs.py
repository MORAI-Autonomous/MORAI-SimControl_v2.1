# protocol_defs.py
import struct

# =========================
# TCP Server Config Fixed Step Mode Control
# =========================
TCP_SERVER_IP = "127.0.0.1"
TCP_SERVER_PORT = 9093

# =========================
# UDP Sender Config (Manual Command)
# =========================
UDP_IP = "127.0.0.1"
UDP_PORT = 9090

# ManualCommand payload: throttle, brake, steer (float64 x3) = 24 bytes
MANUAL_FMT = "<ddd"
MANUAL_SIZE = struct.calcsize(MANUAL_FMT)

# =========================
# Protocol (TCP header matches <BBIIIH)
# =========================
MAGIC = 0x4D  # 'M'

MSG_CLASS_REQ = 0x01
MSG_CLASS_RESP = 0x02

MSG_TYPE_SAVE_DATA = 0x1101
MSG_TYPE_FIXED_STEP = 0x1200
MSG_TYPE_GET_STATUS = 0x1201

FLAG = 0

HEADER_FMT = "<BBIIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 16

RESULT_FMT = "<II"  # uint32 result_code, uint32 detail_code
RESULT_SIZE = struct.calcsize(RESULT_FMT)  # 8

STATUS_FMT = "<fQqI"  # float fixed_delta, uint64 step_index, int64 seconds, uint32 nanos
STATUS_SIZE = struct.calcsize(STATUS_FMT)  # 24

GET_STATUS_PAYLOAD_SIZE = RESULT_SIZE + STATUS_SIZE  # 32

VALID_MSG_CLASSES = {MSG_CLASS_REQ, MSG_CLASS_RESP}
VALID_MSG_TYPES = {MSG_TYPE_FIXED_STEP, MSG_TYPE_GET_STATUS, MSG_TYPE_SAVE_DATA}

# =========================
# AutoCall defaults
# =========================
MAX_CALL_NUM = 1000
AUTO_TIMEOUT_SEC = 2.0
AUTO_DELAY_BETWEEN_CMDS_SEC = 0.0  # 0.01 등으로 조절 가능