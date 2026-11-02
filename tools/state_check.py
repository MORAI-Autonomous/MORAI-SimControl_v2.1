from __future__ import annotations

"""States and modes check (MSVM-3073, Automation API spec chapter 3) against a running, logged-in
simulator. It answers two questions the code alone does not settle:

  [A] After a scenario ends on its own (SCENARIO_STATE_COMPLETED): is it still "running" (PAUSE,
      STOP), are its objects back (ready, ListEntities), and does START work again?
  [B] While the objects are rebuilt (a mode switch): what do queries sent meanwhile answer, and do
      answers come back out of order on one connection?

The suite's first scenario must end by itself within --end-timeout seconds (a Storyboard StopTrigger,
e.g. SimulationTimeCondition > 5) and should hold a few vehicles:

    python tools/state_check.py --suite "C:/Users/user/Desktop/Scenario Stop Trigger/Scenario Stop Trigger.msuite"

Lines marked OK / FAIL check what the spec states; lines marked SEEN only report what the simulator
did, for the spec to be written from.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

failures = 0


def step(label: str, call: Callable[[], dict], expect_reason: Optional[str] = None) -> Optional[dict]:
    """Runs one call. expect_reason: the failure reason name the call must answer with."""
    global failures
    start = time.time()
    try:
        resp = call()
    except ProtoCallError as e:
        ok = expect_reason is not None and e.reason_name == expect_reason
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label}: {e.reason_name} {e.message}  ({time.time() - start:.1f}s)")
        return None
    ok = expect_reason is None
    failures += 0 if ok else 1
    shown = f" {resp}" if resp else ""
    print(f"  {'OK  ' if ok else 'FAIL'} {label}:{shown}  ({time.time() - start:.1f}s)"
          + ("" if ok else f"  expected {expect_reason}"))
    return resp


def status_line(client: ProtoClient) -> str:
    status = client.call("GetScenarioStatus")
    entities = client.call("ListEntities").get("entities", [])
    return (f"mode={status.get('mode', 'SCENARIO_MODE_UNSPECIFIED')} "
            f"state={status.get('state', 'SCENARIO_STATE_UNSPECIFIED')} "
            f"ready={status.get('ready', False)} entities={len(entities)}")


def expect_state(client: ProtoClient, label: str, expected: str) -> None:
    """The run state read right after a call: the call answers only once its work is done."""
    global failures
    state = client.call("GetScenarioStatus").get("state", "SCENARIO_STATE_UNSPECIFIED")
    ok = state == expected
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} state right after {label}: {state}" + ("" if ok else f"  expected {expected}"))


def check_completion(client: ProtoClient, end_timeout: float) -> None:
    global failures
    control = lambda action: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{action}"))

    print("[A] A scenario that ends on its own")
    step("START", control("START"))
    expect_state(client, "START", "SCENARIO_STATE_PLAYING")
    print(f"  ...   {status_line(client)}")

    start = time.time()
    last = ""
    while time.time() - start < end_timeout:
        state = client.call("GetScenarioStatus").get("state", "SCENARIO_STATE_UNSPECIFIED")
        if state != last:
            print(f"  ...   {time.time() - start:5.1f}s state={state}")
            last = state
        if state == "SCENARIO_STATE_COMPLETED":
            break
        time.sleep(0.2)
    else:
        failures += 1
        print(f"  FAIL  did not complete within {end_timeout:.0f}s; does the scenario have a StopTrigger?")
        step("STOP", control("STOP"))
        return

    print(f"  SEEN  right after COMPLETED: {status_line(client)}")
    summary = client.call("GetSimulatorSummary")
    print(f"  SEEN  GetSimulatorSummary.scenario_state={summary.get('scenario_state', 'SCENARIO_STATE_UNSPECIFIED')}")
    step("PAUSE after COMPLETED", control("PAUSE"), "NOT_RUNNING")
    step("STOP after COMPLETED", control("STOP"), "NOT_RUNNING")

    # Does the scene come back by itself (as after STOP), and how long does it take?
    start = time.time()
    while time.time() - start < 10.0:
        if client.call("GetScenarioStatus").get("ready", False):
            break
        time.sleep(0.2)
    print(f"  SEEN  after {time.time() - start:.1f}s: {status_line(client)}")

    step("START again after COMPLETED", control("START"))
    expect_state(client, "START", "SCENARIO_STATE_PLAYING")
    # A stop right after a completed run used to read COMPLETED.
    step("STOP", control("STOP"))
    expect_state(client, "STOP", "SCENARIO_STATE_STOPPED")
    print(f"  ...   {status_line(client)}")


def check_rebuild(client: ProtoClient, poll_interval: float) -> None:
    print("[B] Queries while the objects are rebuilt (one connection, answers by request_id)")
    status = client.call("GetScenarioStatus")
    names: List[str] = [e["entity_id"] for e in client.call("ListEntities").get("entities", [])]
    print(f"  ...   before: {status_line(client)} {names}")
    target = "SCENARIO_MODE_EDIT" if status.get("mode") == "SCENARIO_MODE_PLAY" else "SCENARIO_MODE_PLAY"
    probe = names[0] if names else "__no_entity__"

    start = time.time()
    switch_id = client.send("SetScenarioMode", mode=target, discard_edits=True)
    client.send("GetScenarioStatus")
    client.send("ListEntities")
    client.send("GetEntityState", entity_id=probe)

    order: List[int] = []
    switch_done = False
    next_poll = time.time() + poll_interval
    while client.pending:
        if not switch_done and time.time() >= next_poll:
            client.send("GetScenarioStatus")
            client.send("ListEntities")
            client.send("GetEntityState", entity_id=probe)
            next_poll = time.time() + poll_interval
        reply = client.receive(timeout=0.05)
        if reply is None:
            continue
        order.append(reply.request_id)
        t = time.time() - start
        if reply.request_id == switch_id:
            switch_done = True
            print(f"  ...   {t:6.2f}s #{reply.request_id:<4} SetScenarioMode: "
                  f"{'OK' if reply.ok else reply.reason_name + ' ' + reply.message}")
            continue
        if not reply.ok:
            detail = f"{reply.reason_name} {reply.message}"
        elif reply.name == "GetScenarioStatus":
            detail = f"ready={reply.response.get('ready', False)} mode={reply.response.get('mode', '-')}"
        elif reply.name == "ListEntities":
            detail = f"{len(reply.response.get('entities', []))} entities"
        else:
            detail = "found"
        print(f"  ...   {t:6.2f}s #{reply.request_id:<4} {reply.name}: {detail}")

    print(f"  SEEN  sent #{switch_id} SetScenarioMode first; answered as #{order.index(switch_id) + 1} of {len(order)}")
    out_of_order = any(b < a for a, b in zip(order, order[1:]))
    print(f"  SEEN  answers {'came out of order' if out_of_order else 'came in request order'}")
    print(f"  ...   after: {status_line(client)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--suite", help=".msuite whose first scenario ends by itself (omit to use the open suite)")
    ap.add_argument("--end-timeout", type=float, default=60.0, help="seconds to wait for COMPLETED")
    ap.add_argument("--poll", type=float, default=0.1, help="seconds between queries during the rebuild")
    ap.add_argument("--timeout", type=float, default=310.0, help="response timeout (s); server gives up at 300")
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        if args.suite:
            print(f"[0] OpenSuite {args.suite}")
            step("OpenSuite", lambda: client.call("OpenSuite", path=args.suite))
        step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
        print(f"  ...   {status_line(client)}")

        check_completion(client, args.end_timeout)
        check_rebuild(client, args.poll)
        # Back the other way, so both directions are seen.
        check_rebuild(client, args.poll)

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'} (SEEN lines are not judged)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
