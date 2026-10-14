"""RDOP mock server for testing the simulator's RDOP REST client without the real RDOP.

Follows "RDOP-MORAI 연계 인터페이스 정의서" (rev 1.1):
  GET  /mqnicrnd6/rdop-api/digital-twin/run/pop          01 real-time DT control
  GET  /mqnicrnd6/rdop-api/digital-twin/simrec/run/pop   02 history replay
  GET  /mqnicrnd6/rdop-api/micro-simulations/run/pop     03 micro simulation job
  POST /mqnicrnd6/rdop-api/micro-simulations/result      04 result report
Pop returns one FIFO item (200) and removes it, or 204 with no body when empty.

The queues are filled from the console below, or over HTTP the way WAS does it:
  POST /mqnicrnd6/rdop-api/digital-twin/run              {"locX":..,"locY":..}
  POST /mqnicrnd6/rdop-api/digital-twin/simrec/run       {"simulationId":..,"locX":..,"locY":..}
  POST /mock/micro-simulations/run                       {"simulationArea":..,"macroHour":..}  (not in spec)

Path style:
  nas   (default) paths look like the real ones (/nas/...). The simulator cannot open them, so
        readable/exists in its log will be 0 and the result file is not checked.
  local paths point under --nas-root on this PC. The output folder is created (RDOP does that
        before queueing), --macro-file is copied to the job's macro path, and the result CSV must
        really exist when reported.

  nas + --stage-root  jobs carry real /nas/... paths, but the mock prepares the files under
        --stage-root as if that folder were RDOP's /nas (output folder, --macro-file copy) and
        checks the reported result there. Point the simulator's Rdop.NasRoot at the same folder
        to test its path mapping end to end, e.g. with a NAS share:
          python rdop_mock_server.py --stage-root //10.100.100.5/log_storage/rdop_test --macro-file D:/x.anmroutes
          (simulator console) Rdop.NasRoot \\10.100.100.5\log_storage\rdop_test

Python 3.7+, standard library only.

  python rdop_mock_server.py
  python rdop_mock_server.py --path-style local --nas-root D:/rdop_nas --macro-file D:/data/x.anmroutes
"""

import argparse
import itertools
import json
import os
import shutil
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIX = "/mqnicrnd6/rdop-api"
PATH_CAM_POP = PREFIX + "/digital-twin/run/pop"
PATH_REC_POP = PREFIX + "/digital-twin/simrec/run/pop"
PATH_SIM_POP = PREFIX + "/micro-simulations/run/pop"
PATH_RESULT = PREFIX + "/micro-simulations/result"
PATH_CAM_PUSH = PREFIX + "/digital-twin/run"
PATH_REC_PUSH = PREFIX + "/digital-twin/simrec/run"
PATH_SIM_PUSH = "/mock/micro-simulations/run"

RESULT_OK_MESSAGE = "The result was received successfully."

# Keys accepted by the "fail" console command
FAIL_KEYS = {"cam": PATH_CAM_POP, "rec": PATH_REC_POP, "sim": PATH_SIM_POP, "result": PATH_RESULT}


def now():
    return time.strftime("%H:%M:%S")


def log(msg):
    print("[{}] {}".format(now(), msg), flush=True)


class MockState:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.cam_queue = deque()
        self.rec_queue = deque()
        self.sim_queue = deque()
        self.running = {}       # simulationId -> popped micro simulation job, waiting for a result
        self.history = {}       # simulationId -> accepted resultFilePath (source for replay jobs)
        self.forced = {}        # path -> status to return once
        self.seq = itertools.count(1)
        self.pop_counts = {PATH_CAM_POP: 0, PATH_REC_POP: 0, PATH_SIM_POP: 0}
        self.last_pop_status = {}

    # ---- paths --------------------------------------------------------------------------------

    def root(self):
        if self.args.path_style == "local":
            return self.args.nas_root.replace("\\", "/").rstrip("/")
        return "/nas"

    def staged(self, path):
        """Where a job path lives on this PC: --stage-root stands in for /nas."""
        if self.args.path_style == "nas" and self.args.stage_root and (path == "/nas" or path.startswith("/nas/")):
            return self.args.stage_root.replace("\\", "/").rstrip("/") + path[len("/nas"):]
        return path

    def stages_files(self):
        return self.args.path_style == "local" or bool(self.args.stage_root)

    def macro_path(self, area, hour):
        name = "hwasong_2024_{:02d}_{:02d}_section_section{}.xml".format(hour, (hour + 1) % 24, area)
        return "{}/macro/base/2024/av_rate_000/{}".format(self.root(), name)

    def output_dir(self, area, hour):
        return "{}/micro/result/2024/000/{:02d}/{:02d}".format(self.root(), hour, area)

    # ---- enqueue ------------------------------------------------------------------------------

    def push_cam(self, lon, lat):
        item = {"locX": lon, "locY": lat}
        with self.lock:
            self.cam_queue.append(item)
        return item

    def push_sim(self, area, hour, overrides=None):
        """overrides: field values used as given (e.g. a real job's id/paths); a given
        macroResultFilePath is not copied over, the file is expected to be there already."""
        overrides = overrides or {}
        sim_id = "MOCK{:05d}".format(next(self.seq))
        item = {
            "simulationId": sim_id,
            "simulationArea": area,
            "macroHour": hour,
            "macroResultFilePath": self.macro_path(area, hour),
            "microResultOutputDir": self.output_dir(area, hour),
        }
        item.update(overrides)
        if "macroResultFilePath" in overrides:
            pass
        elif self.stages_files():
            try:
                os.makedirs(self.staged(item["microResultOutputDir"]), exist_ok=True)
                if self.args.macro_file:
                    macro_dir = os.path.dirname(self.staged(item["macroResultFilePath"]))
                    os.makedirs(macro_dir, exist_ok=True)
                    shutil.copyfile(self.args.macro_file, self.staged(item["macroResultFilePath"]))
            except OSError as e:
                # e.g. WinError 1326: this process has no credentials for the share
                log("could not prepare the job's files, not queued: {}".format(e))
                return None
                # RDOP jobs read the road network from Content/NetworkInterface/Traffic/network.xml.
                # A copy next to the macro file only helps a manual Import of that path in the panel.
                network = os.path.join(os.path.dirname(os.path.abspath(self.args.macro_file)), "network.xml")
                if os.path.isfile(network):
                    shutil.copyfile(network, os.path.join(macro_dir, "network.xml"))
        with self.lock:
            self.sim_queue.append(item)
        return item

    def push_rec(self, sim_id, lon, lat, forced_path=None):
        # RDOP looks the result path up from its history and only queues known runs
        with self.lock:
            path = forced_path or self.history.get(sim_id)
            if path is None:
                return None
            item = {"simulationId": sim_id, "locX": lon, "locY": lat, "resultFilePath": path}
            self.rec_queue.append(item)
        return item

    # ---- pop / result -------------------------------------------------------------------------

    def take_forced(self, path):
        with self.lock:
            return self.forced.pop(path, None)

    def pop(self, path):
        queue = {PATH_CAM_POP: self.cam_queue, PATH_REC_POP: self.rec_queue, PATH_SIM_POP: self.sim_queue}[path]
        with self.lock:
            self.pop_counts[path] += 1
            if not queue:
                return None
            item = queue.popleft()
            if path == PATH_SIM_POP:
                self.running[item["simulationId"]] = item
            return item

    def report_result(self, body):
        """Returns (status, response dict) following section 04."""
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            return 422, {"error": "요청 본문이 JSON 이 아닙니다", "details": [str(e)]}

        details = []
        if not isinstance(data, dict):
            return 422, {"error": "요청 본문은 JSON 객체여야 합니다", "details": []}
        extra = sorted(set(data) - {"simulationId", "resultFilePath"})
        if extra:
            details.append("허용되지 않은 필드: {}".format(", ".join(extra)))
        for key in ("simulationId", "resultFilePath"):
            if key not in data:
                details.append("필수 필드 누락: {}".format(key))
            elif not isinstance(data[key], str) or not data[key]:
                details.append("{} 는 비어 있지 않은 문자열이어야 합니다 (받은 값: {!r})".format(key, data[key]))
        if details:
            return 422, {"error": "스키마 검증 실패", "details": details}

        sim_id = data["simulationId"]
        path = data["resultFilePath"]
        with self.lock:
            if sim_id in self.history:
                return 404, {"error": "이미 결과가 접수된 simulationId 입니다 (중복 통보)", "status_code": 404}
            job = self.running.get(sim_id)
            if job is None:
                return 404, {"error": "해당 simulationId의 실행 요청 정보를 찾을 수 없습니다", "status_code": 404}

            out_dir = job["microResultOutputDir"].rstrip("/")
            norm = path.replace("\\", "/")
            if not norm.lower().endswith(".csv"):
                return 422, {"error": "결과 파일 확장자가 .csv 가 아닙니다: " + path, "status_code": 422}
            if os.path.dirname(norm) != out_dir:
                return 422, {"error": "결과 파일이 지정 출력 폴더({}) 안에 있지 않습니다: {}".format(out_dir, path),
                             "status_code": 422}
            if self.check_files() and not os.path.isfile(self.staged(norm)):
                return 422, {"error": "결과 파일이 존재하지 않습니다: {} (확인 위치 {})".format(path, self.staged(norm)),
                             "status_code": 422}

            del self.running[sim_id]
            self.history[sim_id] = path
        return 200, {"message": RESULT_OK_MESSAGE}

    def check_files(self):
        return self.args.check_files or self.stages_files()


class Handler(BaseHTTPRequestHandler):
    state = None  # set in main

    def log_message(self, fmt, *args):
        pass  # replaced by our own compact log

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def forced_error(self, path):
        status = self.state.take_forced(path)
        if status is None:
            return False
        log("{} {} -> {} (forced)".format(self.command, path, status))
        self.send_json(status, {"error": "mock forced error", "status_code": status})
        return True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path not in (PATH_CAM_POP, PATH_REC_POP, PATH_SIM_POP):
            self.send_json(404, {"error": "unknown path", "status_code": 404})
            log("GET {} -> 404 (unknown path)".format(path))
            return
        if self.forced_error(path):
            return

        item = self.state.pop(path)
        if item is None:
            self.send_empty(204)
            # 204 arrives every second or two; log only the first one after a change
            if self.state.last_pop_status.get(path) != 204:
                log("GET {} -> 204 (queue empty; further 204s not logged)".format(path))
            self.state.last_pop_status[path] = 204
            return

        self.send_json(200, item)
        self.state.last_pop_status[path] = 200
        log("GET {} -> 200 {}".format(path, json.dumps(item, ensure_ascii=False)))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self.read_body()
        state = self.state

        if path == PATH_RESULT:
            if self.forced_error(path):
                return
            status, resp = state.report_result(body)
            self.send_json(status, resp)
            log("POST {} body={} -> {} {}".format(path, body.decode("utf-8", "replace"), status,
                                                   json.dumps(resp, ensure_ascii=False)))
            return

        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except ValueError:
            self.send_json(422, {"error": "JSON 파싱 실패", "status_code": 422})
            return

        if path == PATH_CAM_PUSH:
            item = state.push_cam(float(data["locX"]), float(data["locY"]))
            self.send_json(200, {"message": "success"})
            log("WAS enqueue camera {}".format(item))
        elif path == PATH_REC_PUSH:
            item = state.push_rec(data["simulationId"], float(data["locX"]), float(data["locY"]))
            if item is None:
                self.send_json(404, {"error": "실행 이력이 없습니다", "status_code": 404})
            else:
                self.send_json(200, {"message": "success"})
                log("WAS enqueue replay {}".format(item))
        elif path == PATH_SIM_PUSH:
            overrides = {k: v for k, v in data.items() if k in SIM_FIELDS}
            item = state.push_sim(int(data.get("simulationArea", 1)), int(data.get("macroHour", 12)), overrides)
            if item is None:
                self.send_json(500, {"error": "작업 파일 준비 실패 (mock 로그 확인)", "status_code": 500})
                return
            self.send_json(200, item)
            log("enqueue micro simulation {}".format(item))
        else:
            self.send_json(404, {"error": "unknown path", "status_code": 404})
            log("POST {} -> 404 (unknown path)".format(path))


# simset keys -> job fields
SIM_KEYS = {"id": "simulationId", "area": "simulationArea", "hour": "macroHour",
            "macro": "macroResultFilePath", "out": "microResultOutputDir"}
SIM_FIELDS = set(SIM_KEYS.values())


def parse_simset(argv):
    overrides = {}
    for token in argv:
        key, sep, value = token.partition("=")
        if not sep or key not in SIM_KEYS:
            raise ValueError("expected key=value with key in " + ", ".join(SIM_KEYS))
        field = SIM_KEYS[key]
        overrides[field] = int(value) if field in ("simulationArea", "macroHour") else value.replace("\\", "/")
    return overrides


HELP = """commands:
  cam [lon lat]            queue a camera location           (default 126.83 37.2)
  sim [area hour]          queue a micro simulation job       (default 1 12)
  simset key=value ...     queue a micro simulation job with the given fields (no spaces in values)
                           keys: id area hour macro out  e.g.
                           simset id=THWSEQ26091011 area=4 hour=9 macro=D:/x.anmroutes out=/nas/micro/result/2024/000/09/04
  rec <id> [lon lat]       queue a replay of an accepted result (id from 'status' history)
  recpath <path> [id]      queue a replay with any file path (skips the history check)
  fail <cam|rec|sim|result> <status>
                           make the next response of that API return <status> (e.g. 500, 409)
  status                   show queues, jobs waiting for a result, accepted results
  help | quit"""


def console(state):
    print(HELP, flush=True)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        parts = line.split()
        cmd, argv = parts[0].lower(), parts[1:]
        try:
            if cmd in ("quit", "exit"):
                return
            elif cmd == "help":
                print(HELP)
            elif cmd == "cam":
                lon, lat = (float(argv[0]), float(argv[1])) if len(argv) >= 2 else (126.83, 37.2)
                log("queued camera {}".format(state.push_cam(lon, lat)))
            elif cmd == "sim":
                area, hour = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 12)
                item = state.push_sim(area, hour)
                if item is not None:
                    log("queued micro simulation {}".format(json.dumps(item, ensure_ascii=False)))
            elif cmd == "simset":
                overrides = parse_simset(argv)
                item = state.push_sim(overrides.get("simulationArea", 1), overrides.get("macroHour", 12), overrides)
                if item is not None:
                    log("queued micro simulation {}".format(json.dumps(item, ensure_ascii=False)))
            elif cmd == "rec":
                lon, lat = (float(argv[1]), float(argv[2])) if len(argv) >= 3 else (126.83, 37.2)
                item = state.push_rec(argv[0], lon, lat)
                if item is None:
                    log("no accepted result for {} (RDOP would refuse this replay)".format(argv[0]))
                else:
                    log("queued replay {}".format(item))
            elif cmd == "recpath":
                sim_id = argv[1] if len(argv) >= 2 else "MOCKREC{:05d}".format(next(state.seq))
                log("queued replay {}".format(state.push_rec(sim_id, 126.83, 37.2, forced_path=argv[0])))
            elif cmd == "fail":
                key, status = argv[0].lower(), int(argv[1])
                with state.lock:
                    state.forced[FAIL_KEYS[key]] = status
                log("next {} response will be {}".format(key, status))
            elif cmd == "status":
                with state.lock:
                    print("  queues   cam={} rec={} sim={}".format(
                        len(state.cam_queue), len(state.rec_queue), len(state.sim_queue)))
                    print("  pops     " + "  ".join(
                        "{}={}".format(p.rsplit("/", 3)[-3], n) for p, n in state.pop_counts.items()))
                    print("  waiting for result: " + (", ".join(state.running) or "-"))
                    for sim_id, path in state.history.items():
                        print("  accepted {} -> {}".format(sim_id, path))
                    if state.forced:
                        print("  forced   {}".format(state.forced))
            else:
                print("unknown command, type 'help'")
        except (IndexError, ValueError, KeyError) as e:
            print("bad arguments ({}), type 'help'".format(e))


def main():
    parser = argparse.ArgumentParser(description="RDOP mock server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10033)
    parser.add_argument("--path-style", choices=["nas", "local"], default="nas")
    parser.add_argument("--nas-root", default="D:/rdop_nas", help="root folder for --path-style local")
    parser.add_argument("--macro-file", help="file copied to each job's macro path (local style or --stage-root)")
    parser.add_argument("--stage-root", help="nas style: folder standing in for /nas (files prepared and checked there)")
    parser.add_argument("--check-files", action="store_true",
                        help="require the reported result file to exist (always on for local style)")
    args = parser.parse_args()

    if args.macro_file and not os.path.isfile(args.macro_file):
        sys.exit("macro file not found: " + args.macro_file)
    if args.stage_root and not os.path.isdir(args.stage_root):
        sys.exit("stage root not reachable from this process: {}\n"
                 "  For a NAS share, log on to it from this account first (e.g. cmdkey or net use), and\n"
                 "  note that an elevated (administrator) terminal does not see the Explorer logon.".format(args.stage_root))

    state = MockState(args)
    Handler.state = state
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("RDOP mock listening on http://{}:{}{} (path style: {}{}{})".format(
        args.host, args.port, PREFIX, args.path_style,
        ", root " + state.root() if args.path_style == "local" else "",
        ", /nas staged at " + args.stage_root if args.path_style == "nas" and args.stage_root else ""))

    console(state)
    server.shutdown()


if __name__ == "__main__":
    main()
