from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0
CHUNK_SIZE = 8192
DOWNLOAD_TIMEOUT = 30.0


class PatchDownloader:
    """补丁下载器 — 支持重试、进度回调、校验和验证。

    特性:
        - 指数退避重试 (最多 3 次)
        - 进度回调 (bytes_done / total_bytes)
        - SHA-256 校验和验证
        - 可取消 (cancel_event)
        - 线程安全

    用法:
        downloader = PatchDownloader()
        ok, msg = downloader.download(
            url="https://example.com/patch.py",
            dest="patches/patch_001.py",
            progress_callback=lambda done, total: print(f"{done}/{total}"),
        )
    """

    def __init__(self, max_retries: int = MAX_RETRIES, timeout: float = DOWNLOAD_TIMEOUT):
        self._max_retries = max_retries
        self._timeout = timeout
        self._cancel_event = threading.Event()
        self._active: bool = False

    def cancel(self) -> None:
        self._cancel_event.set()

    def download(
        self,
        url: str,
        dest: str,
        expected_sha256: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[bool, str]:
        self._cancel_event.clear()
        self._active = True

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            if self._cancel_event.is_set():
                self._active = False
                return False, "下载已取消"

            try:
                ok, msg = self._download_once(
                    url, dest, expected_sha256, progress_callback
                )
                if ok:
                    self._active = False
                    return True, msg
                last_error = msg
            except Exception as e:
                last_error = str(e)
                logger.warning(f"下载尝试 {attempt}/{self._max_retries} 失败: {e}")

            if attempt < self._max_retries:
                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                logger.info(f"等待 {delay:.1f}s 后重试...")
                time.sleep(delay)

        self._active = False
        return False, f"下载失败 (已重试 {self._max_retries} 次): {last_error}"

    def _download_once(
        self,
        url: str,
        dest: str,
        expected_sha256: Optional[str],
        progress_callback: Optional[Callable[[int, int], None]],
    ) -> tuple[bool, str]:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

        req = urllib.request.Request(url, headers={"User-Agent": "MCA-Brain-PatchManager/2.0"})

        try:
            response = urllib.request.urlopen(req, timeout=self._timeout)
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"网络错误: {e.reason}"
        except Exception as e:
            return False, str(e)

        total_bytes = response.headers.get("Content-Length")
        total = int(total_bytes) if total_bytes else -1

        tmp_path = dest + ".tmp"
        hasher = hashlib.sha256()
        downloaded = 0

        try:
            with open(tmp_path, "wb") as f:
                while True:
                    if self._cancel_event.is_set():
                        response.close()
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        return False, "下载已取消"

                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)

                    if progress_callback and total > 0:
                        try:
                            progress_callback(downloaded, total)
                        except Exception:
                            pass
        finally:
            response.close()

        if expected_sha256:
            actual = hasher.hexdigest()
            if actual != expected_sha256:
                os.remove(tmp_path)
                return False, f"校验和不匹配: 期望 {expected_sha256[:16]}..., 实际 {actual[:16]}..."

        if os.path.exists(dest):
            os.remove(dest)
        os.rename(tmp_path, dest)
        return True, f"下载完成: {downloaded} bytes"

    @property
    def is_active(self) -> bool:
        return self._active