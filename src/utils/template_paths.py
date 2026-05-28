from __future__ import annotations

import os
from typing import Iterable, Optional

from utils.project_paths import ROOT_DIR

_ROOT_DIR = str(ROOT_DIR)
_TEMPLATE_DIR = os.path.join(_ROOT_DIR, "templates")


def iter_template_paths() -> Iterable[str]:
    if not os.path.isdir(_TEMPLATE_DIR):
        return
    for dirpath, _, filenames in os.walk(_TEMPLATE_DIR):
        for filename in sorted(filenames):
            if filename.lower().endswith(".tmpl"):
                yield os.path.join(dirpath, filename)


def resolve_template_path(template_name: str) -> Optional[str]:
    if os.path.isabs(template_name) and os.path.isfile(template_name):
        return template_name

    direct = os.path.join(_TEMPLATE_DIR, template_name)
    if os.path.isfile(direct):
        return direct

    for path in iter_template_paths() or ():
        if os.path.basename(path) == template_name:
            return path
    return None
