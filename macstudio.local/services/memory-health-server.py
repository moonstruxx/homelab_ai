#!/usr/bin/env python3
"""
macOS memory-pressure health endpoint for Gatus (port 9101).

Three signals (any one fires 503/degraded):
  1. kern.memorystatus_level  < PRESSURE_WARN   (0-100, 100=no pressure; Activity Monitor gauge)
  2. swap used                > SWAP_PCT_WARN % of total swap capacity
  3. swapout rate             > SWAPOUT_RATE_WARN pages/s (rolling delta between requests)

GET /health → 200/ok or 503/degraded + JSON with all metrics.
"""
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9101

PRESSURE_WARN     = 20    # memorystatus_level below this = kernel reports pressure
SWAP_PCT_WARN     = 90    # swap file > 90 % full = close to exhaustion
SWAPOUT_RATE_WARN = 500   # > 500 pages/s swapped out = active swapping (~8 MB/s at 16K pages)

STATE_FILE = "/tmp/macaistack-memory-health.state"
_ENV_C     = {"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"}


def sysctl(*keys):
    out = subprocess.run(
        ["/usr/sbin/sysctl"] + list(keys),
        capture_output=True, text=True, env=_ENV_C,
    ).stdout
    result = {}
    for line in out.splitlines():
        m = re.match(r"(\S+):\s+(.+)", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def get_memorystatus_level():
    try:
        return int(sysctl("kern.memorystatus_level")["kern.memorystatus_level"])
    except (KeyError, ValueError):
        return None


def get_swap_stats():
    """Returns (total_mb, used_mb, pct_used) or (None, None, None)."""
    raw = sysctl("vm.swapusage").get("vm.swapusage", "")
    # vm.swapusage: total = 6144.00M  used = 5417.31M  free = 726.69M (encrypted)
    m = re.search(r"total\s*=\s*([\d.,]+)M\s+used\s*=\s*([\d.,]+)M", raw)
    if not m:
        return None, None, None
    def f(s):
        return float(s.replace(",", "."))
    total, used = f(m.group(1)), f(m.group(2))
    pct = used / total * 100 if total > 0 else None
    return total, used, pct


def get_swapout_rate():
    """
    Returns (pages_per_second, cumulative_swapouts).
    Rate is None on the first call (no prior snapshot) or if measurement fails.
    Persists the last snapshot in STATE_FILE between requests.
    """
    out = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, env=_ENV_C).stdout
    current = None
    for line in out.splitlines():
        m = re.match(r"Swapouts:\s+(\d+)", line)
        if m:
            current = int(m.group(1))
            break
    if current is None:
        return None, None

    now = time.monotonic()
    rate = None
    try:
        prev_time, prev_count = map(float, open(STATE_FILE).read().split())
        elapsed = now - prev_time
        if elapsed > 0:
            rate = max(0.0, (current - prev_count) / elapsed)
    except (FileNotFoundError, ValueError, OSError):
        pass

    try:
        with open(STATE_FILE, "w") as f:
            f.write(f"{now} {current}")
    except OSError:
        pass

    return rate, current


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        level               = get_memorystatus_level()
        swap_total, swap_used, swap_pct = get_swap_stats()
        swapout_rate, swapout_total     = get_swapout_rate()

        issues = []
        if level is not None and level < PRESSURE_WARN:
            issues.append(f"memorystatus_level={level} below threshold {PRESSURE_WARN}")
        if swap_pct is not None and swap_pct > SWAP_PCT_WARN:
            issues.append(f"swap={swap_pct:.1f}% of capacity (threshold {SWAP_PCT_WARN}%)")
        if swapout_rate is not None and swapout_rate > SWAPOUT_RATE_WARN:
            issues.append(f"swapout_rate={swapout_rate:.0f} pages/s (threshold {SWAPOUT_RATE_WARN})")

        status = "ok" if not issues else "degraded"
        body = json.dumps({
            "status": status,
            "memorystatus_level": level,
            "swap_total_mb": swap_total,
            "swap_used_mb": swap_used,
            "swap_pct": round(swap_pct, 1) if swap_pct is not None else None,
            "swapout_rate_pages_per_s": round(swapout_rate, 1) if swapout_rate is not None else None,
            "swapout_total": swapout_total,
            "issues": issues,
        }).encode()

        self.send_response(200 if not issues else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"memory-health-server listening on 0.0.0.0:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
