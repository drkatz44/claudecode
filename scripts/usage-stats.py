#!/usr/bin/env python3
"""
Compute Claude Code usage stats: today, this week, all-time.
Outputs key=value lines for shell consumption.
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

SESSIONS_DIR = Path.home() / ".claude/projects/-Users-drk-Code-claudecode"
STATS_CACHE  = Path.home() / ".claude/stats-cache.json"

now       = datetime.now(timezone.utc)
today_str = now.strftime("%Y-%m-%d")
week_ago  = now - timedelta(days=7)
day_ago   = now - timedelta(days=1)

# ── Count from JSONL files ───────────────────────────────────────────────────
day_msgs = day_tools = day_sessions = 0
week_msgs = week_tools = week_sessions = 0

for path in SESSIONS_DIR.glob("*.jsonl"):
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        continue

    in_week = mtime >= week_ago
    in_day  = mtime >= day_ago
    if not in_week:
        continue

    # Count this file's contributions
    file_msgs = file_tools = 0
    session_dates: set[str] = set()

    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                msg_type = obj.get("type", "")

                if msg_type == "user":
                    file_msgs += 1
                    if ts:
                        session_dates.add(ts[:10])
                elif msg_type == "assistant":
                    content = obj.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                file_tools += 1
    except OSError:
        continue

    week_msgs  += file_msgs
    week_tools += file_tools
    week_sessions += 1

    if in_day:
        day_msgs  += file_msgs
        day_tools += file_tools
        day_sessions += 1

# ── All-time from stats cache ────────────────────────────────────────────────
all_msgs = all_sessions = all_tools = 0
try:
    cache = json.loads(STATS_CACHE.read_text())
    all_msgs     = cache.get("totalMessages", 0)
    all_sessions = cache.get("totalSessions", 0)
    # tool calls not stored directly; sum from dailyActivity
    for day in cache.get("dailyActivity", []):
        all_tools += day.get("toolCallCount", 0)
except Exception:
    pass

# Add week's counts to all-time if cache is stale
# (simple heuristic: just report what we have)

def fmt(n: int) -> str:
    return f"{n:,}"

print(f"day_msgs={fmt(day_msgs)}")
print(f"day_tools={fmt(day_tools)}")
print(f"day_sessions={fmt(day_sessions)}")
print(f"week_msgs={fmt(week_msgs)}")
print(f"week_tools={fmt(week_tools)}")
print(f"week_sessions={fmt(week_sessions)}")
print(f"all_msgs={fmt(all_msgs)}")
print(f"all_tools={fmt(all_tools)}")
print(f"all_sessions={fmt(all_sessions)}")
