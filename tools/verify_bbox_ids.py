"""Check that bbox class_id/instance_id (packed 0x00RRGGBB) match the semantic/instance PNG colors.

Usage: python tools/verify_bbox_ids.py "<SimulationLogs>/<interface_...>/<Scenario>"
Expects 2d/, bb3d/ CSV logs and seman/, inst/ PNG logs under that directory.
"""
from __future__ import annotations

import csv
import glob
import os
import re
import sys

import numpy as np
from PIL import Image

_GROUP_2D = 6   # min.xy, max.xy, class_id, instance_id
_GROUP_3D = 26  # 8 corners * xyz, class_id, instance_id


def _load_rows(path: str, group: int):
    # One row per object (rows of a frame share Timestamp); older logs packed all objects in one row.
    frames: dict = {}
    with open(path, newline="") as fp:
        reader = csv.reader(fp)
        next(reader)
        for row in reader:
            vals = row[4:]
            frames.setdefault(int(row[0]), []).extend(
                vals[i:i + group] for i in range(0, len(vals) - group + 1, group))
    return list(frames.items())


def _load_pngs(log_dir: str, kind: str):
    items = []
    for path in glob.glob(os.path.join(log_dir, kind, f"{kind}_*.png")):
        match = re.match(rf"{kind}_\d+_(\d+)\.png", os.path.basename(path))
        if match:
            items.append((int(match.group(1)), path))
    return sorted(items)


def _packed_rgb(rgba: np.ndarray) -> np.ndarray:
    px = rgba[..., :3].astype(np.uint32)
    return (px[..., 0] << 16) | (px[..., 1] << 8) | px[..., 2]


def main(log_dir: str) -> int:
    seman, inst = _load_pngs(log_dir, "seman"), _load_pngs(log_dir, "inst")
    rows_2d = _load_rows(os.path.join(log_dir, "2d", "2d_fr_number_.csv"), _GROUP_2D)
    rows_3d = _load_rows(os.path.join(log_dir, "bb3d", "bb3d_fr_number_.csv"), _GROUP_3D)
    if not (seman and inst and rows_2d):
        print("missing seman/inst/2d logs")
        return 2

    checked = mismatched = id_3d_mismatch = 0
    min_frac = {"semantic": 1.0, "instance": 1.0}
    for frame, (ts, objs) in enumerate(rows_2d):
        pngs = {
            "semantic": _packed_rgb(np.asarray(Image.open(min(seman, key=lambda t: abs(t[0] - ts))[1]).convert("RGBA"))),
            "instance": _packed_rgb(np.asarray(Image.open(min(inst, key=lambda t: abs(t[0] - ts))[1]).convert("RGBA"))),
        }
        for idx, obj in enumerate(objs):
            x0, y0, x1, y1 = (max(int(round(float(v))), 0) for v in obj[:4])
            ids = {"semantic": int(obj[4]), "instance": int(obj[5])}
            for kind, want in ids.items():
                crop = pngs[kind][y0:y1 + 1, x0:x1 + 1]
                frac = float((crop == want).mean()) if crop.size else 0.0
                min_frac[kind] = min(min_frac[kind], frac)
                checked += 1
                if frac == 0.0:
                    mismatched += 1
                    print(f"MISMATCH frame={frame} obj={idx} {kind} id=0x{want:06X}")
            if frame < len(rows_3d) and idx < len(rows_3d[frame][1]):
                ids_3d = rows_3d[frame][1][idx][-2:]
                if (int(ids_3d[0]), int(ids_3d[1])) != (ids["semantic"], ids["instance"]):
                    id_3d_mismatch += 1

    print(f"frames={len(rows_2d)} checks={checked} mismatched={mismatched} 3d_id_mismatch={id_3d_mismatch}")
    print(f"min pixel fraction inside box: semantic={min_frac['semantic']:.3f} instance={min_frac['instance']:.3f}")
    return 1 if mismatched or id_3d_mismatch else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
