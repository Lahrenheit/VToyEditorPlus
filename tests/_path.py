import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DATA = os.environ.get("VTOY_DATA", "/tmp/claude-0/-home-claude/a1f1d153-25ad-5ddf-bbf3-8bd13f83ac99/scratchpad/data")
