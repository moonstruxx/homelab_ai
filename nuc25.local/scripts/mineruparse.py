#!/usr/bin/env python3
"""
mineruparse — parse PDFs with MinerU and write structured output per file.

Usage:
    mineruparse "/path/to/*.pdf"
    mineruparse "/path/to/docs/" -o /tmp/output

Each input PDF produces an output directory named after the file (without .pdf),
created next to the input file unless --out is given:
    input.pdf  →  input/
        README.md          full markdown text
        content_list.json  per-page blocks (text/table/image)
        middle_json.json   intermediate layout analysis
        model_output.json  raw model inference output
        images/            extracted images (base64-decoded)

 MinerU API must be running at MINERU_API_URL (default: http://macstudio.local:8086).
"""
import argparse
import base64
import json
import glob
import os
import subprocess
import sys
import time
from pathlib import Path


MINERU_API_URL = os.environ.get("MINERU_API_URL", "http://macstudio.local:8086")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "3600"))


def submit_task(pdf_path: Path) -> str | None:
    url = f"{MINERU_API_URL}/tasks"
    curl_cmd = [
        "curl", "-s", "--max-time", "60", "-X", "POST", url,
        "-F", f"files=@{pdf_path}",
    ]
    try:
        out = subprocess.run(curl_cmd, capture_output=True, text=True, check=True)
        body = json.loads(out.stdout)
        return body.get("task_id")
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Submit failed: {e.stderr[:300]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [ERROR] Submit failed: {e}", file=sys.stderr)
        return None


def poll_task(task_id: str) -> dict | None:
    url = f"{MINERU_API_URL}/tasks/{task_id}"
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "30", url],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)
    except Exception as e:
        print(f"  [ERROR] Status check failed: {e}", file=sys.stderr)
        return None


def fetch_result(task_id: str) -> dict | None:
    url = f"{MINERU_API_URL}/tasks/{task_id}/result"
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "60", url],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Result fetch failed: {e.stderr[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [ERROR] Result fetch failed: {e}", file=sys.stderr)
        return None


def wait_for_result(task_id: str, timeout: int) -> dict | None:
    elapsed = 0
    while elapsed < timeout:
        status = poll_task(task_id)
        if status is None:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue
        if status.get("status") == "completed":
            return fetch_result(task_id)
        if status.get("status") == "failed":
            print(f"  [ERROR] Task failed: {status.get('error')}", file=sys.stderr)
            return None
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    print(f"  [TIMEOUT] Task {task_id} did not complete within {POLL_TIMEOUT}s", file=sys.stderr)
    return None


def save_result(pdf_stem: str, out_dir: Path, result: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    results = result.get("results", {})
    file_data = next(iter(results.values()), None)
    if file_data is None:
        print(f"  [WARN] No result data for {pdf_stem}", file=sys.stderr)
        return

    if "md_content" in file_data:
        (out_dir / "README.md").write_text(file_data["md_content"], encoding="utf-8")

    for key in ["content_list", "middle_json", "model_output"]:
        if key in file_data:
            (out_dir / f"{key}.json").write_text(
                json.dumps(file_data[key], indent=2, ensure_ascii=False), encoding="utf-8"
            )

    if "images" in file_data:
        img_dir = out_dir / "images"
        img_dir.mkdir(exist_ok=True)
        for fname, data_uri in file_data["images"].items():
            if not isinstance(data_uri, str) or "," not in data_uri:
                continue
            header, b64 = data_uri.split(",", 1)
            ext = header.split(";")[0].split("/")[1] if "/" in header else "bin"
            img_path = img_dir / f"{fname}.{ext}"
            try:
                img_path.write_bytes(base64.b64decode(b64))
            except Exception as e:
                print(f"  [WARN] Failed to decode image {fname}: {e}", file=sys.stderr)


def process_pdf(pdf_path: Path, out_base: Path | None, no_wait: bool, timeout: int) -> bool:
    stem = pdf_path.stem
    parent = out_base if out_base is not None else pdf_path.parent
    out_dir = parent / stem
    if out_dir.exists():
        print(f"  [SKIP] {out_dir} already exists — remove to re-parse")
        return False

    print(f"  Submitting {pdf_path.name}…", end=" ", flush=True)
    task_id = submit_task(pdf_path)
    if task_id is None:
        return False
    print(f"task_id={task_id[:8]}…, waiting…", flush=True)

    if no_wait:
        print(f"  → task_id={task_id} (submit only)")
        return True

    result = wait_for_result(task_id, timeout)
    if result is None:
        return False

    save_result(stem, out_dir, result)
    print(f"  → {out_dir}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse PDFs with MinerU.")
    parser.add_argument("glob", help="Glob pattern for PDF files, e.g. /path/to/*.pdf")
    parser.add_argument(
        "--out", "-o", default=None,
        help="Output base directory (default: same directory as each input PDF)",
    )
    parser.add_argument(
        "--no-wait", action="store_true",
        help="Submit and print task_id without waiting for completion",
    )
    parser.add_argument(
        "--timeout", type=int, default=POLL_TIMEOUT,
        help=f"Max seconds to wait per task (default: {POLL_TIMEOUT}, env: POLL_TIMEOUT)",
    )
    args = parser.parse_args()

    pattern = os.path.expanduser(args.glob)
    pdfs = sorted(Path(p) for p in glob.glob(pattern))
    if not pdfs:
        print(f"No PDFs matched: {pattern}", file=sys.stderr)
        sys.exit(1)

    out_base = Path(args.out).resolve() if args.out else None
    if out_base is not None:
        out_base.mkdir(parents=True, exist_ok=True)

    print(f"Parsing {len(pdfs)} PDF(s) with MinerU at {MINERU_API_URL}")
    ok = fail = 0
    for pdf_path in pdfs:
        if process_pdf(pdf_path, out_base, args.no_wait, args.timeout):
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} succeeded, {fail} failed")


if __name__ == "__main__":
    main()
