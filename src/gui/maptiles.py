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
_fetcher = None


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
        self._inflight = {}                    # url -> Event, 진행 중인 요청
        self._inflight_lock = threading.Lock()

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

        # 같은 타일을 두 곳(프리페치 스레드 · 위젯 로딩 스레드)에서 동시에 노릴 수 있다.
        # 뒤에 온 쪽은 앞선 요청이 끝날 때까지 기다렸다가 캐시에서 읽는다 — 같은 바이트를
        # 두 번 받지 않는다.
        with self._inflight_lock:
            ev = self._inflight.get(url)
            leader = ev is None
            if leader:
                ev = threading.Event()
                self._inflight[url] = ev

        if not leader:
            ev.wait(timeout=15)
            cached = self._read(url)
            if cached is not None:
                return _Response(cached)

        try:
            resp = self.session.get(url, stream=True, timeout=10)
            data = resp.content
            # 오류 페이지·워터마크 타일을 캐시에 굳히지 않는다.
            if resp.status_code == 200 and data:
                self._write(url, data)
            return _Response(data)
        finally:
            if leader:
                with self._inflight_lock:
                    self._inflight.pop(url, None)
                ev.set()


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
        global _fetcher
        _fetcher = TileFetcher()
        mw.requests = _fetcher
        _installed = True
        return True
    except Exception:
        return False


def cache_size_mb() -> float:
    try:
        return CACHE_DB.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


# ------------------------------------------------------------------------------
# 선행 캐시(pre-cache) 억제
#
# 연결 재사용으로 네트워크는 사실상 0 이 됐는데도 첫 화면이 늦었다. 계측해 보니
# 원인이 바뀌어 있었다(1600x900 · 줌 7 · 캐시 워밤):
#
#     타일 요청 296 장 (전부 캐시 히트, 네트워크 0.00s)
#     request_image 합계 7.55s  = 전부 디코드 + ImageTk.PhotoImage (장당 25ms)
#
# 화면에 실제로 보이는 타일은 30여 장이다. 나머지는 `pre_cache()` 가 반경 8까지
# 넓혀 가며 미리 받는 것이고(≈289장), **PhotoImage 생성은 Tk 락을 잡으므로**
# 보이는 타일의 렌더와 정면으로 경쟁한다. 즉 선행 캐시가 첫 화면을 늦춘다.
#
# 그래서 반경을 좁히고, 첫 화면이 그려질 시간을 준 뒤에 시작하게 만든다.
# 패닝 체감을 위해 선행 캐시를 아예 끄지는 않는다 — 반경 2면 한 화면 바깥 한 겹이다.
#
# 콜드(빈 캐시) 실측, 첫 화면이 다 찰 때까지:
#     원본(반경 8, 즉시 시작)   4.14s   타일 294장
#     반경 2 + 1.5s 지연        3.35s   타일 105장
# 반경을 0·1·2 로 흔들어도 3.4s 대에서 차이가 없다(지연이 이미 경쟁을 없앴다) — 2를 택했다.
# 남은 시간은 앱 구동 약 1.0s + 라이브러리가 첫 화면에 요청하는 104장(13열×8행, 전부 고유)의
# 네트워크다. 이 장수를 줄이려면 tkintermapview 의 타일 범위 계산에 손대야 한다 — 하지 않았다.
# ------------------------------------------------------------------------------

PRECACHE_RADIUS = 2
PRECACHE_WARMUP_S = 1.5

_precache_patched = False


def patch_precache(radius: int = PRECACHE_RADIUS, warmup_s: float = PRECACHE_WARMUP_S) -> bool:
    """`TkinterMapView.pre_cache` 를 좁은 반경 · 늦은 시작 판으로 교체한다.

    위젯 생성 **전에** 불러야 한다 — pre_cache 스레드는 `__init__` 에서 시작된다.
    """
    global _precache_patched
    if _precache_patched:
        return True
    try:
        import time as _time
        import sqlite3 as _sqlite3
        import tkintermapview.map_widget as mw

        def pre_cache(self):
            # 원본과 같은 구조. 다른 점은 radius 상한과 시작 지연뿐이다.
            _time.sleep(warmup_s)
            last_position = None
            r = 1
            zoom = round(self.zoom)
            db_cursor = None
            if self.database_path is not None:
                db_cursor = _sqlite3.connect(self.database_path).cursor()

            while self.running:
                if last_position != self.pre_cache_position:
                    last_position = self.pre_cache_position
                    zoom = round(self.zoom)
                    r = 1

                if last_position is not None and r <= radius:
                    px, py = self.pre_cache_position
                    for x in range(px - r, px + r + 1):
                        for y in (py + r, py - r):
                            if f"{zoom}{x}{y}" not in self.tile_image_cache:
                                self.request_image(zoom, x, y, db_cursor=db_cursor)
                    for y in range(py - r, py + r + 1):
                        for x in (px + r, px - r):
                            if f"{zoom}{x}{y}" not in self.tile_image_cache:
                                self.request_image(zoom, x, y, db_cursor=db_cursor)
                    r += 1
                    # 한 겹 받을 때마다 숨을 돌린다 — Tk 락을 독점하지 않는다.
                    _time.sleep(0.05)
                else:
                    _time.sleep(0.1)

        mw.TkinterMapView.pre_cache = pre_cache
        _precache_patched = True
        return True
    except Exception:
        return False
