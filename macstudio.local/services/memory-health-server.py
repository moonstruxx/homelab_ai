#!/usr/bin/env python3
"""
Minimal HTTP health server exposing macOS swap / memory-pressure state.
Returns 200 + {"status": "ok"} while swap is under threshold.
Returns 503 + {"status": "degraded"} when swap used exceeds SWAP_WARN_MB.
Used by Gatus (nuc25.local) to alert on macstudio memory pressure.
"""
import json
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9101
SWAP_WARN_MB = 2048  # alert when more than 2 GB of swap is in use


def get_swap_stats():
    # LC_ALL=C forces dot as decimal separator regardless of system locale
    env = {"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"}
    out = subprocess.run(["/usr/sbin/sysctl", "vm.swapusage"], capture_output=True, text=True, env=env).stdout
    # format: vm.swapusage: total = 2048.00M  used = 512.00M  free = 1536.00M (encrypted)
    m = re.search(r"total\s*=\s*([\d.,]+)M\s+used\s*=\s*([\d.,]+)M\s+free\s*=\s*([\d.,]+)M", out)
    if not m:
        return None, None, None
    def parse_mb(s):
        return float(s.replace(",", "."))
    return parse_mb(m.group(1)), parse_mb(m.group(2)), parse_mb(m.group(3))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        total_mb, used_mb, free_mb = get_swap_stats()

        if total_mb is None:
            status, http_code = "unknown", 503
            issues = ["could not read vm.swapusage"]
        elif used_mb > SWAP_WARN_MB:
            status, http_code = "degraded", 503
            issues = [f"swap_used={used_mb:.0f}MB exceeds threshold of {SWAP_WARN_MB}MB"]
        else:
            status, http_code = "ok", 200
            issues = []

        body = json.dumps({
            "status": status,
            "swap_total_mb": total_mb,
            "swap_used_mb": used_mb,
            "swap_free_mb": free_mb,
            "issues": issues,
        }).encode()

        self.send_response(http_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress per-request access logs


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"memory-health-server listening on 0.0.0.0:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
