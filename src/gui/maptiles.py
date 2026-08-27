"""지도 타일 취득 가속 — 연결 재사용 + 디스크 캐시.

`tkintermapview` 는 타일마다 `requests.get(...)` 을 새로 연다. 25개 스레드가 각자
TLS 핸드셰이크를 반복하므로, 네트워크가 멀쩡해도 화면이 늦게 찬다.

실측(24 타일 · 스레드 8 · Esri Dark · 각 3회 중앙값):
    매번 새 연결   1.56 s
    세션 재사용    0.08 s      (콜드 첫 회 0.55 s)

여기서 하는 일은 두 가지다.
  1. `requests.Session` + 커넥션 풀로 keep-alive 를 살린다.
  2. 받은 타일을 sqlite 에 넣어 둔다 — 다음 실행에서 같은 화면은 네트워크를 타지 않는다.

라이브러리를 포크하지 않고 `map_widget` 모듈이 참조하는 `requests` 심볼만 갈아 끼운다.
`request_image()` 는 `requests.get(url, stream=True, headers=...).raw` 만 쓰므로
같은 모양의 껍데기를 돌려주면 된다.
"""

import io
import sqlite3
import threading
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".skymission"
CACHE_DB = CACHE_DIR / "tilecache.sqlite"

# 타일 하나가 대략 10~40KB. 4만 장이면 넉넉잡아 1GB 미만이고, 전국을 여러 줌으로 돌아도 남는다.
MAX_TILES = 40_000

_installed = False


class _Response:
    """`requests.Response` 중 tkintermapview 가 실제로 쓰는 부분만 흉내 낸다."""

    def __init__(self, data: bytes):
        self.raw = io.BytesIO(data)
        self.status_code = 200
        self.content = data


class TileFetcher:
    """세션 하나를 공유하고, 결과를 sqlite 에 캐시한다.

    sqlite 커넥션은 스레드마다 따로 연다 — 기본 sqlite3 커넥션은 스레드 간 공유가 금지돼 있고,
    타일 로딩은 25개 스레드에서 동시에 들어온다.
    """

    def __init__(self, cache_db: Path = CACHE_DB):
        import requests

        self.cache_db = cache_db
        self._local = threading.local()
        self._write_lock = threading.Lock()

        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=8, pool_maxsize=32, max_retries=1)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({"User-Agent": "TkinterMapView"})

        # map_widget 은 `requests.exceptions.ConnectionError` 도 참조한다(map_widget.py:540).
        # 모듈 심볼을 통째로 대체하므로 예외 계층을 그대로 물려줘야 한다.
        self.exceptions = requests.exceptions

        self._cache_ok = self._init_db()

    # ---- 캐시 ----
    def _init_db(self) -> bool:
        try:
            self.cache_db.parent.mkdir(parents=True, exist_ok=True)
            con = self._conn()
            con.execute("CREATE TABLE IF NOT EXISTS tiles ("
                        "url TEXT PRIMARY KEY, ts INTEGER NOT NULL, blob BLOB NOT NULL)")
            con.commit()
            self._prune(con)
            return True
        except Exception:
            # 캐시는 최적화일 뿐이다. 못 쓰면 네트워크로만 돌면 된다 — 지도를 죽이지 않는다.
            return False

    def _conn(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.cache_db, timeout=5)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            self._local.con = con
        return con

    def _prune(self, con):
        (n,) = con.execute("SELECT COUNT(*) FROM tiles").fetchone()
        if n > MAX_TILES:
            con.execute("DELETE FROM tiles WHERE url IN ("
                        "SELECT url FROM tiles ORDER BY ts ASC LIMIT ?)", (n - MAX_TILES,))
            con.commit()

    def _read(self, url: str):
        if not self._cache_ok:
            return None
        try:
            row = self._conn().execute(
                "SELECT blob FROM tiles WHERE url=?", (url,)).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _write(self, url: str, data: bytes):
        if not self._cache_ok:
            return
        try:
            con = self._conn()
            con.execute("INSERT OR REPLACE INTO tiles(url, ts, blob) VALUES (?,?,?)",
                        (url, int(time.time()), data))
            con.commit()
        except Exception:
            pass

    # ---- requests 흉내 ----
    def get(self, url, stream=False, headers=None, **kw):
        cached = self._read(url)
        if cached is not None:
            return _Response(cached)

        resp = self.session.get(url, stream=True, timeout=10)
        data = resp.content
        # 오류 페이지·워터마크 타일을 캐시에 굳히지 않는다.
        if resp.status_code == 200 and data:
            self._write(url, data)
        return _Response(data)


def install() -> bool:
    """`tkintermapview` 의 타일 취득 경로를 갈아 끼운다. 성공하면 True.

    tkintermapview 가 없거나 내부 구조가 바뀌었으면 조용히 False — 지도는 원래대로 돈다.
    """
    global _installed
    if _installed:
        return True
    try:
        import tkintermapview.map_widget as mw
        if not hasattr(mw, "requests"):
            return False
        mw.requests = TileFetcher()
        _installed = True
        return True
    except Exception:
        return False


def cache_size_mb() -> float:
    try:
        return CACHE_DB.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0
