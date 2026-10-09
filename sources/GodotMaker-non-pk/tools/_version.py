#!/usr/bin/env python3
"""Shared semantic versioning utilities for GodotMaker tools."""
import re
from typing import NamedTuple


class SemVer(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: str) -> "SemVer | None":
    """Parse a 'major.minor.patch' string into SemVer. Returns None on failure."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    if not m:
        return None
    return SemVer(int(m.group(1)), int(m.group(2)), int(m.group(3)))
