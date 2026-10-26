#!/usr/bin/env python3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from cms.core import build_site  # noqa: E402

print(f"Built {build_site(root)} published book(s) into {root / 'dist'}")
