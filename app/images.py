"""正文图片异步加载：后台线程下载 + 主线程回调插入，绝不阻塞 UI。"""
from __future__ import annotations

import hashlib
import io
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageTk

from . import config
from .fetcher import http_get


class ImageLoader:
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, root, *, proxy_getter=None, ua_getter=None):
        self.root = root
        self.proxy_getter = proxy_getter or (lambda: "")
        self.ua_getter = ua_getter or (lambda: "")
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="img")
        self.results: queue.Queue = queue.Queue()
        self._cache: dict[tuple[str, int], object] = {}
        self._inflight: set[tuple[str, int]] = set()
        self._lock = threading.Lock()
        self._stopped = False
        self._pump_job = self.root.after(120, self.pump)

    # ------------------------------------------------------------------ 对外
    def load(self, url: str, width: int, callback) -> None:
        """请求一张图；主线程稍后以 ImageTk.PhotoImage 或 None 回调。"""
        if not url:
            callback(None)
            return
        key = (url, int(width))
        with self._lock:
            if key in self._cache:
                callback(self._cache[key])
                return
            if key in self._inflight:
                return
            self._inflight.add(key)

        def work() -> None:
            image = None
            try:
                image = self._fetch(url, width)
            except Exception:
                image = None
            self.results.put((key, image, callback))

        self.pool.submit(work)

    def stop(self) -> None:
        self._stopped = True
        try:
            self.root.after_cancel(self._pump_job)
        except Exception:
            pass
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ 内部
    def _fetch(self, url: str, width: int):
        raw = self._disk_cache(url)
        if raw is None:
            resp = http_get(url, proxy=self.proxy_getter(), ua=self.ua_getter(), timeout=15,
                            max_bytes=self.MAX_BYTES)
            if resp.status != 200 or len(resp.body) < 64:
                return None
            raw = resp.body
            try:
                self._disk_store(url, raw)
            except OSError:
                pass
        img = Image.open(io.BytesIO(raw))
        img.load()
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        if img.width > width:
            ratio = width / float(img.width)
            img = img.resize((int(img.width * ratio), max(1, int(img.height * ratio))), Image.LANCZOS)
        return ImageTk.PhotoImage(img, master=self.root)

    def _cache_file(self, url: str):
        name = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:24] + ".img"
        return config.CACHE_DIR / name

    def _disk_cache(self, url: str):
        path = self._cache_file(url)
        try:
            if path.stat().st_size >= 64:
                return path.read_bytes()
        except OSError:
            pass
        return None

    def _disk_store(self, url: str, raw: bytes) -> None:
        path = self._cache_file(url)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)

    def pump(self) -> None:
        """主线程定时收割结果。"""
        if self._stopped:
            return
        try:
            while True:
                key, image, callback = self.results.get_nowait()
                with self._lock:
                    self._inflight.discard(key)
                    if image is not None:
                        self._cache[key] = image
                try:
                    callback(image)
                except Exception:
                    pass
        except queue.Empty:
            pass
        if not self._stopped:
            try:
                self._pump_job = self.root.after(120, self.pump)
            except Exception:
                pass
