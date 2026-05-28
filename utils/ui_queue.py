from __future__ import annotations

"""Thread-safe queue for DearPyGUI UI updates.

Background threads call post(lambda: dpg.set_value("tag", val)).
The main render loop calls drain() once per frame.
"""

import queue
import time
from typing import Callable

_q: queue.Queue[Callable] = queue.Queue()


def post(fn: Callable) -> None:
    """Queue a UI update callable from a background thread."""
    _q.put(fn)


_DRAIN_CAP = 200       # Maximum items processed per frame.
_WARN_BACKLOG = 50     # Warn when queue backlog grows beyond this.
_WARN_ITEM_MS = 50.0   # Warn when one queued item is slow.


def drain() -> int:
    """Drain queued UI updates from the DPG render loop.

    Returns the number of processed items.
    """
    backlog = _q.qsize()
    if backlog > _WARN_BACKLOG:
        print(f"[ui_queue] backlog={backlog}")

    count = 0
    for _ in range(_DRAIN_CAP):
        if _q.empty():
            break
        try:
            fn = _q.get_nowait()
            count += 1
            t0 = time.perf_counter()
            fn()
            ms = (time.perf_counter() - t0) * 1000.0
            if ms > _WARN_ITEM_MS:
                print(f"[ui_queue] slow item {ms:.1f}ms: {fn}")
        except Exception as e:
            print(f"[ui_queue] drain error: {e}")
    return count
