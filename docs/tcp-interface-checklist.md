# TCP Interface Checklist

Use this checklist when adding or changing a TCP interface.

## Source Of Truth

[src/transport/message_schema.py](../src/transport/message_schema.py) is the source of truth for TCP command definitions.

Generated documentation and most payload tests are derived from that schema. Avoid editing [docs/tcp-api.md](tcp-api.md) by hand.

## Add A New Interface

1. Add the request `MessageSpec` in [src/transport/message_schema.py](../src/transport/message_schema.py).
2. Add a matching response entry to `RESPONSE_MESSAGES` when the simulator sends one.
3. Add passive simulator updates to `NOTIFICATION_MESSAGES` when needed.
4. Add or verify the related `MSG_TYPE_*`, format, and size constants in [src/transport/protocol_defs.py](../src/transport/protocol_defs.py).
5. Add the send helper and payload builder in [src/transport/tcp_transport.py](../src/transport/tcp_transport.py).
6. Add response or notification parsing when the payload needs custom handling.
7. Update [src/transport/tcp_thread.py](../src/transport/tcp_thread.py) if app logic must consume the response or notification.
8. Wire the command into the caller: panel, runner, CLI, or tool.
9. Add or update payload tests in [tests/test_tcp_payloads.py](../tests/test_tcp_payloads.py).
10. Regenerate docs and run validation.

## Change An Existing Interface

1. Update [src/transport/message_schema.py](../src/transport/message_schema.py).
2. Verify [src/transport/protocol_defs.py](../src/transport/protocol_defs.py).
3. Update send helpers, builders, and parsers in [src/transport/tcp_transport.py](../src/transport/tcp_transport.py).
4. If passive updates are involved, update `NOTIFICATION_MESSAGES` and notification parsing together.
5. Update response handling and logs in [src/transport/tcp_thread.py](../src/transport/tcp_thread.py).
6. Check every caller passes the full updated field set.
7. Update tests and generated docs.

## Validation

```bash
python tools/gen_tcp_docs.py
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads
```

For a quick syntax pass:

```bash
python -m compileall -q morai_interface_console.py simulation_control.py cli sitecustomize.py src tools tests
```

## Rules Of Thumb

- Start schema changes from `message_schema.py`.
- If a request payload changes, update the builder and golden payload test together.
- If a response payload changes, update the parser and `tcp_thread.py` handling together.
- If a notification payload exists, check the `msg_class = 0x03` path and the generated `Notifications` section.
- Treat `docs/tcp-api.md` as generated output.
