from __future__ import annotations

from pathlib import Path
import sys

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from simulation_control_main import main


if __name__ == "__main__":
    raise SystemExit(main())
