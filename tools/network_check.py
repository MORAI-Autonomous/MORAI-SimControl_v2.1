from __future__ import annotations

"""Networks (0x010A) check against a running, logged-in simulator in SCENARIO_MODE_EDIT.

Lists the templates, creates a UDP network and a ROS 2 network (when there are templates for them)
from the first fitting template, reads them back, changes and removes them. Refusals are checked too.
Everything made here is removed at the end; nothing is saved.

    python tools/network_check.py
    python tools/network_check.py --entity Ego --sensor Camera_1

--entity: a vehicle to link (its state for a send template, its control for a receive template).
--sensor: a sensor to link to a sensor template.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

PREFIX = "network_check_"
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
    print(f"  {'OK  ' if ok else 'FAIL'} {label}  ({time.time() - start:.1f}s)" + ("" if ok else f"  expected {expect_reason}"))
    return resp if resp is not None else {}


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")


def shown(n: dict) -> str:
    where = n.get("topic") or "{ip}:{port}".format(**{"ip": "", "port": 0, **n.get("address", {})})
    return (f"{n.get('name')} [{n.get('protocol', '').replace('NETWORK_PROTOCOL_', '')}/"
            f"{n.get('direction', '').replace('NETWORK_DIRECTION_', '')}] {n.get('template_name')} -> {where} "
            f"{n.get('hz', 0)} Hz active={n.get('active', False)} entities={n.get('entity_ids', [])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--entity", help="a vehicle to link")
    ap.add_argument("--sensor", help="a sensor to link")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        call = lambda name, **kw: (lambda: client.call(name, **kw))
        made = []

        print("[1] Templates")
        t = step("GetNetworkTemplates", call("GetNetworkTemplates")) or {}
        templates = t.get("templates", [])
        print(f"  SEEN {len(templates)} templates")
        for tpl in templates[:8]:
            print(f"    {tpl.get('name')}: {tpl.get('protocol')} {tpl.get('direction')} {tpl.get('ros_message_type', '')} {tpl.get('data_types', [])}")

        def first(protocol: str, direction: str) -> Optional[dict]:
            return next((x for x in templates if x.get("protocol") == protocol and x.get("direction") == direction), None)

        print("[2] Create")
        for protocol in ("NETWORK_PROTOCOL_UDP", "NETWORK_PROTOCOL_ROS2"):
            tpl = first(protocol, "NETWORK_DIRECTION_SEND")
            if tpl is None:
                print(f"  no {protocol} send template: skipped")
                continue
            name = PREFIX + protocol.split("_")[-1].lower()
            linked = []
            types = " ".join(tpl.get("data_types", []))
            if args.sensor and "Entity" in types and "Vehicle" not in types:
                linked = [args.sensor]
            r = step(f"CreateNetwork {name} from {tpl['name']}", call("CreateNetwork", network={
                "name": name, "template_name": tpl["name"], "entity_ids": linked}))
            if r is not None:
                made.append(name)
                n = r.get("network", {})
                print(f"  SEEN {shown(n)}  warnings={r.get('warnings', [])}")
                check("protocol as the template's", n.get("protocol") == protocol)
                if protocol.endswith("UDP"):
                    check("a port was chosen", n.get("address", {}).get("port", 0) >= 9000, str(n.get("address")))
                else:
                    check("a topic was chosen", n.get("topic", "").startswith("/morai/"), n.get("topic", ""))
                check("60 Hz by default", n.get("hz") == 60)

        if args.entity:
            tpl = first("NETWORK_PROTOCOL_UDP", "NETWORK_DIRECTION_RECEIVE")
            if tpl is not None:
                name = PREFIX + "control"
                r = step(f"CreateNetwork {name} (receive) for {args.entity}", call("CreateNetwork", network={
                    "name": name, "template_name": tpl["name"], "entity_ids": [args.entity]}))
                if r is not None:
                    made.append(name)
                    print(f"  SEEN {shown(r.get('network', {}))}  warnings={r.get('warnings', [])}")

        print("[3] List and update")
        lst = step("ListNetworks", call("ListNetworks")) or {}
        names = [n.get("name") for n in lst.get("networks", [])]
        check("the created ones are listed", all(m in names for m in made), str(names))
        if made:
            target = made[0]
            u = step(f"UpdateNetwork {target}: off, 30 Hz", call("UpdateNetwork", name=target, set_active=True, active=False, hz=30))
            if u is not None:
                n = u.get("network", {})
                check("now off at 30 Hz", not n.get("active", False) and n.get("hz") == 30, shown(n))

        print("[4] Refusals")
        step("no name", call("CreateNetwork", network={"template_name": "x"}), "MISSING_FIELD")
        step("bad name", call("CreateNetwork", network={"name": "a b", "template_name": "x"}), "OUT_OF_RANGE")
        step("unknown template", call("CreateNetwork", network={"name": PREFIX + "x", "template_name": "network_check_nothing"}),
             "TEMPLATE_NOT_FOUND")
        if made:
            tpl_name = next((n.get("template_name") for n in lst.get("networks", []) if n.get("name") == made[0]), "")
            step("same name again", call("CreateNetwork", network={"name": made[0], "template_name": tpl_name}), "NAME_IN_USE")
            step("hz 101", call("UpdateNetwork", name=made[0], hz=101), "OUT_OF_RANGE")
        step("update unknown", call("UpdateNetwork", name=PREFIX + "nobody", hz=10), "NETWORK_NOT_FOUND")
        step("remove unknown", call("RemoveNetwork", name=PREFIX + "nobody"), "NETWORK_NOT_FOUND")

        print("[5] Remove")
        for name in made:
            step(f"RemoveNetwork {name}", call("RemoveNetwork", name=name))
        lst = step("ListNetworks", call("ListNetworks")) or {}
        left = [n.get("name") for n in lst.get("networks", []) if n.get("name", "").startswith(PREFIX)]
        check("none left", not left, str(left))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
