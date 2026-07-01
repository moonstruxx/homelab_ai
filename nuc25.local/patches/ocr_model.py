#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# Patches:
# 1. PADDLEOCR_REQUEST_TIMEOUT env var support (default 3600s) — upstream hardcodes 600s.
# 2. Thread-safe PDF page rendering: pypdfium2/libpdfium is not thread-safe under concurrent
#    parse jobs (task_executor dispatches via ThreadPoolExecutor). Concurrent failures cause a
#    segfault that kills the ragflow process. Fixed by serialising pdfplumber calls with a
#    module-level lock and handling per-page errors individually rather than in a list
#    comprehension that aborts on first failure.
#
import gc
import json
import logging
import os
import threading
from io import BytesIO
from os import PathLike
from typing import Any, Optional

import pdfplumber
from common.constants import MAXIMUM_PAGE_NUMBER
from deepdoc.parser.mineru_parser import MinerUParser
from deepdoc.parser.opendataloader_parser import OpenDataLoaderParser
from deepdoc.parser.paddleocr_parser import PaddleOCRParser

# Serialize all pdfplumber/pypdfium2 calls across threads.  libpdfium is not
# thread-safe under concurrent failures; concurrent segfaults kill the process.
_PDF_RENDER_LOCK = threading.Lock()


class Base:
    def __init__(self, key: str | dict, model_name: str, **kwargs):
        self.model_name = model_name

    def parse_pdf(self, filepath: str, binary=None, **kwargs) -> tuple[Any, Any]:
        raise NotImplementedError("Please implement parse_pdf!")


class MinerUOcrModel(Base, MinerUParser):
    _FACTORY_NAME = "MinerU"

    def __init__(self, key: str | dict, model_name: str, **kwargs):
        Base.__init__(self, key, model_name, **kwargs)
        raw_config = {}
        if key:
            try:
                raw_config = json.loads(key)
            except Exception:
                raw_config = {}

        # nested {"api_key": {...}} from UI
        # flat {"MINERU_*": "..."} payload auto-provisioned from env vars
        config = raw_config.get("api_key", raw_config)
        if not isinstance(config, dict):
            config = {}

        def _resolve_config(key: str, env_key: str, default=""):
            # lower-case keys (UI), upper-case MINERU_* (env auto-provision), env vars
            return config.get(key, config.get(env_key, os.environ.get(env_key, default)))

        self.mineru_api = _resolve_config("mineru_apiserver", "MINERU_APISERVER", "")
        self.mineru_output_dir = _resolve_config("mineru_output_dir", "MINERU_OUTPUT_DIR", "")
        self.mineru_backend = _resolve_config("mineru_backend", "MINERU_BACKEND", "pipeline")
        self.mineru_server_url = _resolve_config("mineru_server_url", "MINERU_SERVER_URL", "")
        self.mineru_delete_output = bool(int(_resolve_config("mineru_delete_output", "MINERU_DELETE_OUTPUT", 1)))

        # Redact sensitive config keys before logging
        redacted_config = {}
        for k, v in config.items():
            if any(sensitive_word in k.lower() for sensitive_word in ("key", "password", "token", "secret")):
                redacted_config[k] = "[REDACTED]"
            else:
                redacted_config[k] = v
        logging.info(f"Parsed MinerU config (sensitive fields redacted): {redacted_config}")

        MinerUParser.__init__(self, mineru_api=self.mineru_api, mineru_server_url=self.mineru_server_url)

    def check_available(self, backend: Optional[str] = None, server_url: Optional[str] = None) -> tuple[bool, str]:
        backend = backend or self.mineru_backend
        server_url = server_url or self.mineru_server_url
        return self.check_installation(backend=backend, server_url=server_url)

    def parse_pdf(self, filepath: str, binary=None, callback=None, parse_method: str = "raw", **kwargs):
        ok, reason = self.check_available()
        if not ok:
            raise RuntimeError(f"MinerU server not accessible: {reason}")

        sections, tables = MinerUParser.parse_pdf(
            self,
            filepath=filepath,
            binary=binary,
            callback=callback,
            output_dir=self.mineru_output_dir,
            backend=self.mineru_backend,
            server_url=self.mineru_server_url,
            delete_output=self.mineru_delete_output,
            parse_method=parse_method,
            **kwargs,
        )
        return sections, tables


class PaddleOCROcrModel(Base, PaddleOCRParser):
    _FACTORY_NAME = "PaddleOCR"

    def __init__(self, key: str | dict, model_name: str, **kwargs):
        Base.__init__(self, key, model_name, **kwargs)
        raw_config = {}
        if key:
            try:
                raw_config = json.loads(key)
            except Exception:
                raw_config = {}

        # nested {"api_key": {...}} from UI
        # flat {"PADDLEOCR_*": "..."} payload auto-provisioned from env vars
        config = raw_config.get("api_key", raw_config)
        if not isinstance(config, dict):
            config = {}

        def _resolve_config(key: str, env_key: str, default=""):
            # lower-case keys (UI), upper-case PADDLEOCR_* (env auto-provision), env vars
            return config.get(key, config.get(env_key, os.environ.get(env_key, default)))

        self.paddleocr_base_url = _resolve_config("paddleocr_base_url", "PADDLEOCR_BASE_URL", "") or _resolve_config("paddleocr_api_url", "PADDLEOCR_API_URL", "")
        self.paddleocr_algorithm = _resolve_config("paddleocr_algorithm", "PADDLEOCR_ALGORITHM", "PaddleOCR-VL")
        self.paddleocr_access_token = _resolve_config("paddleocr_access_token", "PADDLEOCR_ACCESS_TOKEN", None)
        timeout_val = _resolve_config("paddleocr_request_timeout", "PADDLEOCR_REQUEST_TIMEOUT", "3600") or "3600"
        try:
            self.paddleocr_request_timeout = int(timeout_val)
        except (TypeError, ValueError):
            self.paddleocr_request_timeout = 3600

        # Redact sensitive config keys before logging
        redacted_config = {}
        for k, v in config.items():
            if any(sensitive_word in k.lower() for sensitive_word in ("key", "password", "token", "secret")):
                redacted_config[k] = "[REDACTED]"
            else:
                redacted_config[k] = v
        logging.info(f"Parsed PaddleOCR config (sensitive fields redacted): {redacted_config}")

        PaddleOCRParser.__init__(
            self,
            base_url=self.paddleocr_base_url or None,
            access_token=self.paddleocr_access_token,
            algorithm=self.paddleocr_algorithm,
            request_timeout=self.paddleocr_request_timeout,
        )

    def __images__(self, fnm, page_from=0, page_to=MAXIMUM_PAGE_NUMBER, callback=None):
        # Serialise via _PDF_RENDER_LOCK: libpdfium is not thread-safe under concurrent failures.
        # Use pypdfium2 directly with a SINGLE document instead of pdfplumber's to_image()
        # which opens a new PdfDocument for every page (causes state corruption on large PDFs).
        self.page_from = page_from
        self.page_to = page_to
        with _PDF_RENDER_LOCK:
            try:
                import pypdfium2
                from PIL import Image

                # Open document once
                if isinstance(fnm, (str, PathLike)):
                    doc = pypdfium2.PdfDocument(str(fnm))
                else:
                    data = fnm if isinstance(fnm, bytes) else fnm.getbuffer().tobytes()
                    doc = pypdfium2.PdfDocument(BytesIO(data))

                total_pages = len(doc)
                end = min(page_to, total_pages)
                page_images = []
                for i in range(page_from, end):
                    try:
                        page = doc.get_page(i)
                        pil_img = page.render(
                            scale=1.0,
                            no_smoothtext=False,
                            no_smoothpath=False,
                            no_smoothimage=False,
                        ).to_pil().convert("RGB")
                        page_images.append(pil_img)
                    except Exception as page_err:
                        self.logger.debug(
                            f"[PaddleOCR] skipping page {i} (render failed): {page_err}"
                        )
                doc.close()
                self.page_images = page_images if page_images else None
            except Exception as e:
                self.page_images = None
                self.logger.warning(f"[PaddleOCR] failed to generate page images: {e}")
            finally:
                gc.collect()

    def check_available(self) -> tuple[bool, str]:
        return self.check_installation()

    def parse_pdf(self, filepath: str, binary=None, callback=None, parse_method: str = "raw", **kwargs):
        ok, reason = self.check_available()
        if not ok:
            raise RuntimeError(f"PaddleOCR server not accessible: {reason}")

        sections, tables = PaddleOCRParser.parse_pdf(self, filepath=filepath, binary=binary, callback=callback, parse_method=parse_method, **kwargs)
        return sections, tables

    def parse_image(self, filepath: str, binary=None, callback=None, **kwargs) -> str:
        ok, reason = self.check_available()
        if not ok:
            raise RuntimeError(f"PaddleOCR server not accessible: {reason}")

        logging.info(f"PaddleOCR parse_image start: {filepath}")
        result = PaddleOCRParser.parse_image(self, filepath=filepath, binary=binary, callback=callback, **kwargs)
        logging.info(f"PaddleOCR parse_image done: {filepath}, text length: {len(result)}")
        return result


class OpenDataLoaderOcrModel(Base, OpenDataLoaderParser):
    _FACTORY_NAME = "OpenDataLoader"

    def __init__(self, key: str | dict, model_name: str, **kwargs):
        Base.__init__(self, key, model_name, **kwargs)
        raw_config = {}
        if key:
            try:
                raw_config = json.loads(key)
            except Exception:
                raw_config = {}

        config = raw_config.get("api_key", raw_config)
        if not isinstance(config, dict):
            config = {}

        def _resolve_config(key: str, env_key: str, default=""):
            return config.get(key, config.get(env_key, os.environ.get(env_key, default)))

        redacted_config = {}
        for k, v in config.items():
            if any(s in k.lower() for s in ("key", "password", "token", "secret")):
                redacted_config[k] = "[REDACTED]"
            else:
                redacted_config[k] = v
        logging.info(f"Parsed OpenDataLoader config (sensitive fields redacted): {redacted_config}")

        OpenDataLoaderParser.__init__(self)
        self.api_url = _resolve_config("opendataloader_apiserver", "OPENDATALOADER_APISERVER", "").rstrip("/")
        self.api_key = _resolve_config("opendataloader_api_key", "OPENDATALOADER_API_KEY", "").strip()
        timeout_val = _resolve_config("opendataloader_timeout", "OPENDATALOADER_TIMEOUT", "600") or "600"
        try:
            self.timeout = int(timeout_val)
        except (TypeError, ValueError):
            self.timeout = 600

    def check_available(self) -> tuple[bool, str]:
        ok = self.check_installation()
        return ok, "" if ok else "OpenDataLoader service not reachable"

    def parse_pdf(self, filepath: str, binary=None, callback=None, parse_method: str = "raw", **kwargs):
        ok, reason = self.check_available()
        if not ok:
            raise RuntimeError(f"OpenDataLoader service not accessible: {reason}")

        sections, tables = OpenDataLoaderParser.parse_pdf(
            self,
            filepath=filepath,
            binary=binary,
            callback=callback,
            parse_method=parse_method,
            **kwargs,
        )
        return sections, tables
