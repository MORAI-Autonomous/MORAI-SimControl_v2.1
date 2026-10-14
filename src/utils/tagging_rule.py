"""Semantic segmentation color code (packed 0x00RRGGBB) -> Tagging Rule lookup.

The rules live in `assets/tagging_rule.csv` (Group/Class/SubClass/Tag/Red/Green/Blue/Code/...),
read with pandas at runtime; nothing is hardcoded here.

Source of truth (Google Sheets, tab "Tagging Rule"); re-export the tab as CSV to update:
https://docs.google.com/spreadsheets/d/1qpPzO1BCaqvenl4-MmxjS_zLGOU4-L_jY9IJsw8tDls/edit
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from utils.project_paths import ROOT_DIR

TAGGING_RULE_CSV = ROOT_DIR / "assets" / "tagging_rule.csv"

CodeLike = Union[int, str]


@lru_cache(maxsize=None)
def load_tagging_rules(path: Path = TAGGING_RULE_CSV) -> pd.DataFrame:
    """Read the rule table once, indexed by the integer 24-bit code."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"Code": str})
    df.index = df["Code"].str.lstrip("#").map(lambda text: int(text, 16))
    df.index.name = "code"
    return df


def _to_code(code: CodeLike) -> int:
    """Accept 0xA00000, 10485760 or '#A00000' / 'A00000'."""
    if isinstance(code, str):
        return int(code.strip().lstrip("#"), 16)
    return int(code)


def code_to_subclass(code: CodeLike, default: Optional[str] = None) -> Optional[str]:
    """SubClass name for a 24-bit semantic code, or `default` when the code is not in the table."""
    return load_tagging_rules()["SubClass"].get(_to_code(code), default)


def code_to_tag(code: CodeLike, default: Optional[str] = None) -> Optional[str]:
    """Full tag (`group_class_subclass`) for a 24-bit semantic code, or `default` when unknown."""
    return load_tagging_rules()["Tag"].get(_to_code(code), default)
