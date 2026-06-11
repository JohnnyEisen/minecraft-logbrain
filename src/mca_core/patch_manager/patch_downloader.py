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

    @staticmethod
    def _validate_url(url: str) -> tuple[bool, str]:
        """VULN-002 修复: URL 协议白名单 + IP 验证，防止 SSRF。

        仅允许 http/https 协议。对 IP 地址做精确的内网检查，
        避免 startswith 误杀合法域名（如 127.example.com）。
        """
        import ipaddress
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"不允许的协议: {parsed.scheme}（仅允许 http/https）"
        if not parsed.hostname:
            return False, "URL 缺少主机名"

        host = parsed.hostname
        host_lower = host.lower()

        # 精确匹配已知保留主机名
        if host_lower in ("localhost", "0.0.0.0", "[::1]"):
            return False, f"不允许访问内网地址: {host}"

        # BUG-001 修复: 用 ipaddress 精确判断 IP 是否为内网地址
        # 避免 startswith 误杀合法域名
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"不允许访问内网地址: {host}"
            if ip.is_multicast:
                return False, f"不允许访问组播地址: {host}"
        except ValueError:
            # 不是 IP 地址，是域名 — 允许通过
            pass

        return True, ""

    def _download_once(
        self,
        url: str,
        dest: str,
        expected_sha256: Optional[str],
        progress_callback: Optional[Callable[[int, int], None]],
    ) -> tuple[bool, str]:
        # ── VULN-002: URL 安全验证 ──
        ok, err = self._validate_url(url)
        if not ok:
            return False, f"URL 验证失败: {err}"

        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

        # ── 禁止 HTTP 重定向跟随，防 DNS 重绑定 / 302 到内网 ──
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise urllib.error.HTTPError(
                    req.get_full_url(), code, f"重定向被拒绝: {msg} → {newurl}",
                    headers, None
                )
            def http_error_301(self, req, fp, code, msg, headers):  # noqa: N802
                return self.redirect_request(req, fp, code, msg, headers, headers.get("Location", ""))
            http_error_302 = http_error_301  # noqa: N815
            http_error_303 = http_error_301
            http_error_307 = http_error_301
            http_error_308 = http_error_301

        opener = urllib.request.build_opener(NoRedirectHandler)

        req = urllib.request.Request(url, headers={"User-Agent": "minecraft-logbrain/2.1"})

        try:
            response = opener.open(req, timeout=self._timeout)
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