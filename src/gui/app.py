import json
import os
import queue
import sys
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Add project root to path to allow running as script
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# 내부 로직 호출
from src.core.generator import (batch_process_inputs, validate_mission_config,
                                parse_polygon_coords_from_kml, read_gpkg_layer,
                                polygon_features, polygon_coords_from_geoms,
                                resolve_input_files, INPUT_SEP)
from src.core import enums, gpkg
from src.gui import theme as T

try:
    import tkintermapview
    from src.gui import maptiles
    maptiles.install()          # 타일마다 새 연결 → 세션 재사용 + 디스크 캐시 (실측 1.56s → 0.08s)
    maptiles.patch_precache()   # 선행 캐시 반경 8(≈289장) → 2 — PhotoImage 가 Tk 락을 잡아 첫 화면을 늦췄다
except ImportError:
    tkintermapview = None
    maptiles = None

BASE = Path(__file__).parent

# ------------------------------------------------------------------------------
# 디자인 토큰 · 지도 상수
#
# 화면은 "설정 나열"이 아니라 작업 흐름이다: ① 데이터 → ② 미션 → (③ 상세) → 실행.
# 안전 판정은 실행 버튼 바로 위 — 결정하는 자리에서 보인다.
# ------------------------------------------------------------------------------
# 색·반경·타이포는 전부 src/gui/theme.py(E8IGHT 디자인시스템 토큰)에서 온다.
# 여기서 hex 를 새로 만들지 말 것 — 강조는 시안 하나뿐이고, 상태색은 의미가 고정돼 있다.

# 미리보기 폴리곤 외곽선 색 순환 — 디자인시스템의 viz 시퀀스를 순서대로 쓴다(재배열 금지).
# 채움 없이 테두리만 — 불투명 채움은 판독을 막는다.
POLY_COLORS = T.VIZ[:6]

# CartoDB 는 뺐다 — 2026-08 부터 익명 접근에 "API KEY REQUIRED" 워터마크 타일을
# 반환한다(실측). 죽은 기본값은 없느니만 못하다. Esri 는 키 없이 안정적이다.
MAP_PROVIDERS = {
    "Esri Dark": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", 16),
    "Esri Satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                       "World_Imagery/MapServer/tile/{z}/{y}/{x}", 19),
    "Google Hybrid": ("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}", 22),
    "OpenStreetMap": ("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", 19),
    "VWorld Base": ("https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png", 19),
}

# 사이드바 폭 — 입력·출력 경로가 들어가는 자리라 좁으면 경로가 잘린다.
SIDEBAR_W = 400

# 데이터를 읽기 전의 기본 시야 — 한반도 전체.
MAP_HOME = (36.5, 127.5, 7)

PREVIEW_MAX_FILES = 20     # 메인 루프를 오래 막으면 타일 로딩까지 굶는다 (docs/gui-audit.md)
PREVIEW_MAX_FEATURES = 150

# 파일명 필드 미선택 sentinel. 언어 토글로 표시가 바뀌면 값 비교가 깨지므로 언어 중립으로 둔다.
AUTO_NAME = "(auto)"

# ------------------------------------------------------------------------------
# 순수 로직 — Tk 없이 테스트된다 (tests/test_gui_logic.py)
# ------------------------------------------------------------------------------

def to_float(v):
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    try: return float(s)
    except Exception: return None

def to_int(v):
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    try: return int(s)
    except Exception: return None

def to_number(v):
    """소수를 보존하되 정수값이면 int 로 강등한다.

    속도가 to_int 였을 때 12.5 가 조용히 버려졌다(B4). 반면 전부 float 로 바꾸면
    "10" 이 "10.0" 으로 주입돼 기존 산출물이 달라진다 — 정수는 정수로 남긴다.
    """
    f = to_float(v)
    if f is None: return None
    return int(f) if f == int(f) else f

def effective_naming_field(value) -> 'str | None':
    """파일명 필드 선택값을 엔진 인자로. sentinel/빈값은 None(=파일 이름 자동)."""
    s = (str(value) if value is not None else "").strip()
    if not s or s.startswith("("):
        return None
    return s

# 지형 팔로우 지원 기종 — 값이 드롭다운(enums) 출신이므로 정확 매칭으로 판정한다.
TF_MODELS = {"mavic3e", "mavic3t", "mavic3m", "m30", "m30t",
             "m300", "m350", "m3d", "m3td", "flycart30"}

def build_overrides(v: dict) -> dict:
    """GUI 입력(문자열/불리언 딕셔너리)에서 엔진 overrides 를 만든다."""
    altitude = to_float(v.get("altitude"))
    shoot = to_float(v.get("shoot_height"))
    return {
        "altitude": altitude,
        "shoot_height": shoot if shoot is not None else altitude,  # 빈칸 = 임무 고도를 따른다
        "margin": to_int(v.get("margin")),
        "overlap_camera_h": to_int(v.get("overlap_camera_h")),
        "overlap_camera_w": to_int(v.get("overlap_camera_w")),
        "overlap_lidar_h": to_int(v.get("overlap_lidar_h")),
        "overlap_lidar_w": to_int(v.get("overlap_lidar_w")),
        "auto_flight_speed": to_number(v.get("auto_flight_speed")),
        "global_transitional_speed": to_number(v.get("global_transitional_speed")),
        "takeoff_security_height": to_int(v.get("takeoff_security_height")),
        "drone_model": v.get("drone_model"),
        "gimbal_pitch": to_float(v.get("gimbal_pitch")),
        "use_terrain_follow": bool(v.get("use_terrain_follow")),
        # 빈칸이 None 으로 가면 엔진의 buffer(None) 이 터진다(B16) — 0.0 으로 굳힌다
        "geometry_buffer_m": to_float(v.get("geometry_buffer_m")) or 0.0,
    }

# 프리셋 스키마 — presets/default_inspection.json 과 호환된다.
PRESET_NUMBER_KEYS = [
    "altitude", "shoot_height", "margin",
    "overlap_camera_h", "overlap_camera_w", "overlap_lidar_h", "overlap_lidar_w",
    "auto_flight_speed", "global_transitional_speed", "takeoff_security_height",
    "gimbal_pitch", "simplify_tolerance", "geometry_buffer_m",
]
PRESET_BOOL_KEYS = ["use_terrain_follow", "set_times", "set_takeoff_ref_point", "pack_kmz"]

def preset_from_values(v: dict) -> dict:
    """GUI 입력을 프리셋 JSON 딕셔너리로. 빈칸은 저장하지 않는다."""
    data = {}
    for k in PRESET_NUMBER_KEYS:
        n = to_number(v.get(k))
        if n is not None:
            data[k] = n
    # 촬영 고도 빈칸 = 임무 고도를 따름 → 같은 값으로 저장 (기존 스키마의 형태)
    if "shoot_height" not in data and "altitude" in data:
        data["shoot_height"] = data["altitude"]
    data["drone_model"] = v.get("drone_model") or "mavic3e"
    for k in PRESET_BOOL_KEYS:
        data[k] = bool(v.get(k))
    return data

def values_from_preset(data: dict) -> dict:
    """프리셋 JSON 을 GUI 입력 딕셔너리로. 모르는 키는 무시하고 없는 키는 건드리지 않는다."""
    out = {}
    for k in PRESET_NUMBER_KEYS:
        if k in data and data[k] is not None:
            out[k] = str(data[k])
    if "drone_model" in data:
        out["drone_model"] = str(data["drone_model"])
    for k in PRESET_BOOL_KEYS:
        if k in data:
            out[k] = bool(data[k])
    # 촬영 고도가 임무 고도와 같으면 GUI 에서는 빈칸(=따름)으로 표현한다
    if out.get("shoot_height") and out.get("altitude") == out.get("shoot_height"):
        out["shoot_height"] = ""
    return out

# ------------------------------------------------------------------------------
# stdout/stderr 리다이렉터 — 배치 중 print 와 traceback 을 로그 큐로 보낸다
# ------------------------------------------------------------------------------
class LogRedirector:
    def __init__(self, q: queue.Queue):
        self.q = q
    def write(self, s):
        if s: self.q.put(s)
    def flush(self):
        # sys.stdout 대체물의 파일 프로토콜상 필요하다. 파이썬이 부른다 — 지우지 말 것.
        pass

# ------------------------------------------------------------------------------
# 다국어 번역 데이터 (Default: KO)
# ------------------------------------------------------------------------------
TRANSLATIONS = {
    "ko": {
        "app_title": "SkyMission Builder",
        "tagline": "GPKG → DJI KMZ · WPML 1.0.6",
        "checking": "확인 중...",
        "sec_data": "①  데이터",
        "sec_mission": "②  미션",
        "sec_advanced": "③  상세 설정",
        "fmt": "포맷",
        "in": "입력",
        "out": "출력",
        "name": "파일명",
        "browse": "찾기",
        "browse_dir": "폴더",
        "browse_files": "파일",
        "load_fields": "↻ 로드",
        "model": "드론 모델",
        "alt_m": "임무 고도 (m)",
        "speed_ms": "비행 속도 (m/s)",
        "buffer_m": "물리적 버퍼 (m)",
        "margin_m": "마진 (m)",
        "pitch_deg": "짐벌 피치 (°)",
        "shoot_h": "촬영 고도 (m)",
        "trans_speed": "전환 속도 (m/s)",
        "takeoff_h": "이륙 보안 고도 (m)",
        "simplify_m": "단순화 오차 (m)",
        "tf_follow": "지형 팔로우 (Terrain Follow)",
        "set_times": "생성 시각 기록",
        "takeoff_ref": "이륙 기준점 자동 설정",
        "pack_kmz": "KMZ로 포장 (해제 시 KML)",
        "overlap_cam": "중첩 Cam H/W (%)",
        "overlap_lidar": "중첩 Lidar H/W (%)",
        "run_batch": "미션 생성 실행",
        "load_preset": "프리셋 불러오기",
        "save_preset": "프리셋 저장",
        "system_logs": "작업 로그",
        "open_report": "리포트 열기",
        "refresh_preview": "↻ 미리보기",
        "safe": "정상: 안전",
        "warning": "주의: 확인 필요",
        "danger": "위험: 설정 조정",
        "tf_supported": "지형 팔로우 지원됨",
        "tf_not_supported": "지형 팔로우 미지원",
        "status_prefix": "상태: ",
        "ready": "준비됨",
        "running": "실행 중...",
        "done": "완료",
        "scan_line": "파일 {files} · 폴리곤 {polys}",
        "scan_skipped": " · 생략 {n}",
        "input_missing": "입력 경로가 없습니다.",
        "no_files": "입력 폴더에 처리할 파일이 없습니다: {pat}",
        "confirm_danger_t": "위험 설정",
        "confirm_danger_m": "안전 판정이 '위험'입니다.\n{msgs}\n\n그래도 실행할까요?",
        "confirm_quit_t": "배치 실행 중",
        "confirm_quit_m": "배치가 아직 실행 중입니다. 종료하면 쓰다 만 파일이 남을 수 있습니다.\n종료할까요?",
        "field_quality_ok": "{n}개 전부 고유 — 이름이 겹치지 않습니다",
        "field_quality_dup": "{d}개 중복 — 겹치면 _2 가 붙습니다",
        "field_quality_auto": "파일 이름으로 자동 명명합니다",
        "fields_dropped": "비어 있어 제외한 필드: {names}",
        "fields_loaded": "필드 {n}개를 불러왔습니다.",
        "fields_none": "이름으로 쓸 필드를 찾지 못했습니다.\n파일명 자동 명명으로 진행됩니다.",
        "preset_loaded": "프리셋을 불러왔습니다.",
        "preset_saved": "프리셋을 저장했습니다.",
        "already_running": "이미 실행 중입니다.",
        "preset_hint": "위 ①②③ 설정값 묶음입니다. 현장·기체별로 저장해 두고 다음 배치에서 그대로 불러옵니다.",
    },
    "en": {
        "app_title": "SkyMission Builder",
        "tagline": "GPKG → DJI KMZ · WPML 1.0.6",
        "checking": "Checking...",
        "sec_data": "①  Data",
        "sec_mission": "②  Mission",
        "sec_advanced": "③  Advanced",
        "fmt": "Format",
        "in": "Input",
        "out": "Output",
        "name": "Naming",
        "browse": "Browse",
        "browse_dir": "Folder",
        "browse_files": "Files",
        "load_fields": "↻ Load",
        "model": "Drone Model",
        "alt_m": "Altitude (m)",
        "speed_ms": "Speed (m/s)",
        "buffer_m": "Buffer (m)",
        "margin_m": "Margin (m)",
        "pitch_deg": "Gimbal Pitch (°)",
        "shoot_h": "Shoot Height (m)",
        "trans_speed": "Transitional (m/s)",
        "takeoff_h": "Takeoff Security (m)",
        "simplify_m": "Simplify Tol. (m)",
        "tf_follow": "Terrain Follow",
        "set_times": "Stamp Create Time",
        "takeoff_ref": "Auto Takeoff Ref Point",
        "pack_kmz": "Pack as KMZ (off = KML)",
        "overlap_cam": "Overlap Cam H/W (%)",
        "overlap_lidar": "Overlap Lidar H/W (%)",
        "run_batch": "RUN BATCH MISSION",
        "load_preset": "Load Preset",
        "save_preset": "Save Preset",
        "system_logs": "SYSTEM LOG",
        "open_report": "Open Report",
        "refresh_preview": "↻ Preview",
        "safe": "SAFE",
        "warning": "CHECK",
        "danger": "DANGER",
        "tf_supported": "Terrain Follow Supported",
        "tf_not_supported": "No Terrain Follow",
        "status_prefix": "STATUS: ",
        "ready": "Ready",
        "running": "Running...",
        "done": "Done",
        "scan_line": "Files {files} · Polygons {polys}",
        "scan_skipped": " · skipped {n}",
        "input_missing": "Input path not found.",
        "no_files": "No matching files in input directory: {pat}",
        "confirm_danger_t": "Dangerous Settings",
        "confirm_danger_m": "Safety check says DANGER.\n{msgs}\n\nRun anyway?",
        "confirm_quit_t": "Batch Running",
        "confirm_quit_m": "A batch is still running. Quitting may leave half-written files.\nQuit anyway?",
        "field_quality_ok": "{n} unique — no filename collisions",
        "field_quality_dup": "{d} duplicates — collisions get _2",
        "field_quality_auto": "Named automatically from the file name",
        "fields_dropped": "Dropped (all empty): {names}",
        "fields_loaded": "Loaded {n} fields.",
        "fields_none": "No naming fields found.\nFiles will be named automatically.",
        "preset_loaded": "Preset loaded.",
        "preset_saved": "Preset saved.",
        "already_running": "Already running.",
        "preset_hint": "The whole set of values in sections 1-3. Save one per site or aircraft, then load it for the next batch.",
    }
}

# ------------------------------------------------------------------------------
# Main Application Class (CustomTkinter)
# ------------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 다크가 기본이자 정체성이다. 내장 위젯(스크롤바·세그먼트)이 테마 딕셔너리를 참조하므로
        # 베이스 테마는 남기고, 눈에 보이는 위젯은 theme.py 팩토리가 전부 덮어쓴다.
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=T.BG_APP)

        self.curr_lang = "ko"
        self.title(self._tr("app_title"))
        self.geometry("1600x900")
        # Maximize window on start (Windows only)
        self.after(0, lambda: self.state('zoomed'))

        # 데이터 관리
        self.queue = queue.Queue()
        self.worker = None

        # 언어 토글이 UI 를 통째로 재생성하므로, 위젯 밖에 살아남아야 하는 상태는 여기 둔다
        self._naming_values = [AUTO_NAME]
        self._field_stats = {}          # 필드명 -> gpkg.FieldStat, 재생성에서 살아남는다
        self._map_style = "Esri Dark"
        self._advanced_open = False
        self._last_safety = "safe"
        self._last_safety_msgs = []
        self._last_report = None
        self._last_out_dir = None
        self._map_debounce_timer = None

        self._init_variables()
        self._build_ui()
        self._bind_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 초기화 실행
        self._on_drone_model_change()
        self._update_safety_status()
        self.after(100, self._poll_queue)
        self.after(600, self._update_map_preview)   # 기본 경로에 파일이 있으면 처음부터 보여준다(B11)

    def _init_variables(self):
        """설정 변수 초기화. self._vars 가 수집/프리셋 적용의 단일 지도다."""
        # Paths
        self.var_input_format = ctk.StringVar(value="gpkg")
        self.var_input_dir = ctk.StringVar(value=str(BASE.parent.parent / "input"))
        self.var_out_dir = ctk.StringVar(value=str(BASE.parent.parent / "output"))
        self.var_naming_field = ctk.StringVar(value=AUTO_NAME)

        # Mission
        self.var_drone_model = ctk.StringVar(value="mavic3e")
        self.var_altitude = ctk.StringVar(value="150.0")
        self.var_auto_flight_speed = ctk.StringVar(value="10")
        self.var_geometry_buffer = ctk.StringVar(value="0.0")

        # Advanced
        self.var_margin = ctk.StringVar(value="0")
        self.var_gimbal_pitch = ctk.StringVar(value="-90.0")
        self.var_shoot_height = ctk.StringVar(value="")            # 빈칸 = 임무 고도를 따름
        self.var_global_transitional_speed = ctk.StringVar(value="")
        self.var_takeoff_security_height = ctk.StringVar(value="20")
        self.var_simplify_tolerance = ctk.StringVar(value="0.0")

        self.var_set_times = ctk.BooleanVar(value=True)
        self.var_set_takeoff_ref_point = ctk.BooleanVar(value=True)
        self.var_use_terrain_follow = ctk.BooleanVar(value=False)
        self.var_pack_kmz = ctk.BooleanVar(value=True)

        # Overlap
        self.var_overlap_camera_h = ctk.StringVar(value="80")
        self.var_overlap_camera_w = ctk.StringVar(value="70")
        self.var_overlap_lidar_h = ctk.StringVar(value="50")
        self.var_overlap_lidar_w = ctk.StringVar(value="50")

        # Templates
        self.var_template = ctk.StringVar(value=str(BASE.parent / "templates" / "template.kml"))
        self.var_waylines = ctk.StringVar(value=str(BASE.parent / "templates" / "waylines.wpml"))

        # Status
        self.var_status = ctk.StringVar(value=self._tr("ready"))

        self._vars = {
            "input_format": self.var_input_format,
            "input_dir": self.var_input_dir,
            "out_dir": self.var_out_dir,
            "naming_field": self.var_naming_field,
            "drone_model": self.var_drone_model,
            "altitude": self.var_altitude,
            "auto_flight_speed": self.var_auto_flight_speed,
            "geometry_buffer_m": self.var_geometry_buffer,
            "margin": self.var_margin,
            "gimbal_pitch": self.var_gimbal_pitch,
            "shoot_height": self.var_shoot_height,
            "global_transitional_speed": self.var_global_transitional_speed,
            "takeoff_security_height": self.var_takeoff_security_height,
            "simplify_tolerance": self.var_simplify_tolerance,
            "set_times": self.var_set_times,
            "set_takeoff_ref_point": self.var_set_takeoff_ref_point,
            "use_terrain_follow": self.var_use_terrain_follow,
            "pack_kmz": self.var_pack_kmz,
            "overlap_camera_h": self.var_overlap_camera_h,
            "overlap_camera_w": self.var_overlap_camera_w,
            "overlap_lidar_h": self.var_overlap_lidar_h,
            "overlap_lidar_w": self.var_overlap_lidar_w,
        }

    def _tr(self, key):
        return TRANSLATIONS.get(self.curr_lang, TRANSLATIONS["en"]).get(key, key)

    def _collect_values(self) -> dict:
        """모든 설정을 평범한 딕셔너리로. 메인 스레드에서 모아 워커에 넘긴다."""
        return {k: v.get() for k, v in self._vars.items()}

    def _apply_values(self, values: dict):
        for k, val in values.items():
            var = self._vars.get(k)
            if var is not None:
                var.set(val)

    # --------------------------------------------------------------------------
    # 언어 토글 / UI 재생성
    # --------------------------------------------------------------------------
    def _toggle_language(self):
        self.curr_lang = "en" if self.curr_lang == "ko" else "ko"
        self._rebuild_full_ui()

    def _rebuild_full_ui(self):
        # 파괴될 지도를 겨눈 debounce 콜백부터 끊는다(B3)
        if self._map_debounce_timer:
            try: self.after_cancel(self._map_debounce_timer)
            except Exception: pass
            self._map_debounce_timer = None

        # 로그는 위젯과 함께 죽는다 — 내용을 들고 건너간다(B3)
        log_text = ""
        if hasattr(self, "txt_log"):
            try: log_text = self.txt_log.get("1.0", "end-1c")
            except Exception: pass

        for widget in self.winfo_children():
            widget.destroy()

        self._build_ui()
        self.title(self._tr("app_title"))
        if log_text:
            self.txt_log.insert("1.0", log_text)
            self.txt_log.see("end")

        self._on_drone_model_change()
        self._update_safety_status()

        # 배치가 도는 중이면 RUN 버튼이 되살아나면 안 된다(B3)
        if self.worker and self.worker.is_alive():
            self.btn_run.configure(state="disabled")
            self.var_status.set(self._tr("running"))

        self.after(200, self._update_map_preview)

    # --------------------------------------------------------------------------
    # UI 구성 — 전역 헤더 / 사이드바(워크플로) / 지도(주역) / 로그
    # --------------------------------------------------------------------------
    def _build_ui(self):
        self.font_section = T.font(14, "bold")
        self.font_body = T.font(13)
        self.font_brand = T.font(17, "bold")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)   # 본문(지도)
        self.grid_rowconfigure(2, weight=0)   # 로그

        # ---- [Header] 브랜드 · 작업 상태 · 언어 ----
        # 상단 바는 시스템 규격 52px. 아래 헤어라인이 구조를 만든다 — 그림자는 쓰지 않는다.
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=T.NAVY_1000, height=52)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)

        ctk.CTkLabel(header, text=self._tr("app_title"), font=self.font_brand,
                     text_color=T.TX_PRIMARY).pack(side="left", padx=(16, 10), pady=8)
        ctk.CTkLabel(header, text=self._tr("tagline"), font=T.mono(12),
                     text_color=T.TX_MUTED).pack(side="left", pady=8)
        T.ghost(header, text="EN / KR", width=64, height=T.H_SM,
                command=self._toggle_language).pack(side="right", padx=16)
        ctk.CTkLabel(header, textvariable=self.var_status, font=T.font(13),
                     text_color=T.TX_BODY).pack(side="right", padx=10)

        # ---- [Left Sidebar] 설정 스크롤 + 하단 고정 실행 존 ----
        side_wrap = ctk.CTkFrame(self, width=SIDEBAR_W, corner_radius=0, fg_color=T.SURFACE_1)
        side_wrap.grid(row=1, column=0, rowspan=2, sticky="nsew")
        side_wrap.grid_rowconfigure(0, weight=1)
        side_wrap.grid_columnconfigure(0, weight=1)

        self.sidebar = ctk.CTkScrollableFrame(side_wrap, width=SIDEBAR_W, corner_radius=0,
                                              fg_color=T.SURFACE_1,
                                              scrollbar_button_color=T.NAVY_700,
                                              scrollbar_button_hover_color=T.NAVY_600)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        # 실행 존은 카드보다 한 단 떠 있고, 위쪽 헤어라인으로 스크롤 영역과 갈린다.
        self.action_bar = ctk.CTkFrame(side_wrap, corner_radius=0, fg_color=T.SURFACE_RAISED)
        self.action_bar.grid(row=1, column=0, sticky="ew")
        T.hairline(self.action_bar).pack(fill="x", side="top")

        self._build_data_card(row_idx=0)
        self._build_mission_card(row_idx=1)
        self._build_advanced_section(row_idx=2)
        self._build_run_zone()

        # ---- [Main Area] 지도 — 이 도구의 주역 ----
        self.map_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=T.BG_CANVAS)
        self.map_frame.grid(row=1, column=1, sticky="nsew")

        if tkintermapview:
            self.map_view = tkintermapview.TkinterMapView(self.map_frame, corner_radius=0)
            self.map_view.pack(fill="both", expand=True)
            if self._map_style not in MAP_PROVIDERS:   # 옛 저장값(CartoDB 등) 방어
                self._map_style = "Esri Dark"
            url, mz = MAP_PROVIDERS[self._map_style]
            self.map_view.set_tile_server(url, max_zoom=mz)
            self.map_view.set_position(MAP_HOME[0], MAP_HOME[1])
            self.map_view.set_zoom(MAP_HOME[2])

            # 뷰포트 위에 뜨는 컨트롤만 떠 있는 표면을 쓴다(평면 위에서는 쓰지 않는다).
            self.cb_map_style = T.option(self.map_frame, values=list(MAP_PROVIDERS.keys()),
                                         command=self._change_map_provider, width=150)
            self.cb_map_style.set(self._map_style)
            self.cb_map_style.place(relx=0.985, rely=0.025, anchor="ne")

            T.quiet(self.map_frame, text=self._tr("refresh_preview"), width=150, height=T.H_SM,
                    command=self._update_map_preview).place(relx=0.985, rely=0.09, anchor="ne")

            # 스캔 요약 — 실행 전에 "무슨 일이 벌어질지"를 지도 위에서 말해 준다
            self.lbl_scan = ctk.CTkLabel(self.map_frame, text="  —  ", font=T.mono(12),
                                         fg_color=T.SURFACE_RAISED, corner_radius=T.R_CONTROL,
                                         text_color=T.TX_BODY, height=T.H_MD)
            self.lbl_scan.place(relx=0.015, rely=0.975, anchor="sw")
        else:
            ctk.CTkLabel(self.map_frame, font=T.font(12), text_color=T.TX_MUTED,
                         text="tkintermapview 미설치 — 지도 미리보기 없이 동작합니다.\n"
                              "pip install -r requirements-optional.txt").pack(expand=True)

        # ---- [Bottom Area] 로그 ----
        self.log_frame = ctk.CTkFrame(self, height=190, corner_radius=0, fg_color=T.SURFACE_1)
        self.log_frame.grid(row=2, column=1, sticky="ew")
        self.log_frame.grid_propagate(False)
        T.hairline(self.log_frame).pack(fill="x", side="top")

        # 38px 헤더 행 — 시스템의 카드 헤더 규격. 라틴 마이크로 라벨은 대문자.
        head = ctk.CTkFrame(self.log_frame, fg_color="transparent", height=38)
        head.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(head, text=self._tr("system_logs"), font=T.font(13, "bold"),
                     text_color=T.TX_BODY).pack(side="left")

        # 로그는 우물이다 — 캔버스 톤 바닥 + 헤어라인. 값은 모노스페이스.
        self.txt_log = ctk.CTkTextbox(self.log_frame, font=T.mono(12),
                                      corner_radius=T.R_CARD, fg_color=T.BG_CANVAS,
                                      border_width=1, border_color=T.BORDER_SUBTLE,
                                      text_color=T.TX_BODY,
                                      scrollbar_button_color=T.NAVY_700,
                                      scrollbar_button_hover_color=T.NAVY_600)
        self.txt_log.pack(fill="both", expand=True, padx=16, pady=(4, 12))

    def _watch_path_entry(self, widget, var):
        """긴 경로는 앞이 아니라 뒤가 정보다 — 값이 바뀌면 끝으로 스크롤하고 전체는 툴팁으로 보인다."""
        def show_tail(*_):
            try:
                widget.xview_moveto(1.0)
            except Exception:
                pass
        var.trace_add("write", lambda *a: self.after(1, show_tail))
        self.after(50, show_tail)
        T.tooltip(widget, var.get)

    # ---- 카드 헬퍼 ----
    def _card(self, row_idx, title_key):
        card = T.card(self.sidebar)
        card.grid(row=row_idx, column=0, padx=16, pady=(12, 0), sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        # 카드 헤더 행 + 아래 헤어라인 — 구조는 여백이 아니라 선으로 나뉜다.
        ctk.CTkLabel(card, text=self._tr(title_key), font=self.font_section,
                     text_color=T.TX_PRIMARY).grid(row=0, column=0, columnspan=3,
                                                   sticky="w", padx=14, pady=(11, 8))
        T.hairline(card).grid(row=0, column=0, columnspan=3, sticky="sew")
        return card

    def _entry_row(self, card, r, label_key, var):
        # 필드 라벨은 문장이 아니라 명사다.
        ctk.CTkLabel(card, text=self._tr(label_key), font=self.font_body,
                     text_color=T.TX_BODY).grid(row=r, column=0, sticky="w",
                                                 padx=(14, 8), pady=4)
        # 설정값은 측정값이다 — 모노스페이스로 읽는다.
        T.entry(card, textvariable=var, font=T.mono(12)).grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=4)

    def _pad_bottom(self, card, r):
        # width 를 명시하지 않으면 CTkFrame 기본 200 이 col0 최소폭이 되어 입력칸을 짜부라뜨린다
        ctk.CTkFrame(card, height=10, width=1, fg_color="transparent").grid(
            row=r, column=0, columnspan=3)

    # ---- ① 데이터 ----
    def _build_data_card(self, row_idx):
        card = self._card(row_idx, "sec_data")
        # 경로는 라벨 옆이 아니라 라벨 **아래** 전체 폭을 쓴다 — 옆에 두면 버튼에 밀려
        # 입력칸이 좁아지고, 이 카드에서 가장 긴 값이 바로 그 경로다.
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=self._tr("fmt"), font=self.font_body,
                     text_color=T.TX_BODY).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=4)
        ctk.CTkSegmentedButton(card, values=["gpkg", "kml", "auto"],
                               variable=self.var_input_format, font=T.font(12),
                               corner_radius=T.R_CONTROL, height=T.H_MD - 6,
                               fg_color=T.NAVY_1000, text_color=T.TX_MUTED,
                               selected_color=T.CYAN_700, selected_hover_color=T.CYAN_600,
                               unselected_color=T.NAVY_1000, unselected_hover_color=T.SURFACE_HOVER,
                               border_width=1).grid(row=1, column=1, columnspan=2,
                                                    sticky="ew", padx=(0, 14), pady=4)

        # ---- 입력: 폴더 전체를 훑거나, 파일을 직접 고른다 ----
        ctk.CTkLabel(card, text=self._tr("in"), font=self.font_body,
                     text_color=T.TX_BODY).grid(row=2, column=0, columnspan=3, sticky="w",
                                                padx=14, pady=(8, 0))
        in_row = ctk.CTkFrame(card, fg_color="transparent")
        in_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=(2, 4))
        self.ent_input_dir = T.entry(in_row, textvariable=self.var_input_dir)
        self.ent_input_dir.pack(side="left", fill="x", expand=True)
        self._watch_path_entry(self.ent_input_dir, self.var_input_dir)
        T.quiet(in_row, text=self._tr("browse_dir"), width=48,
                command=lambda: self._choose_dir(self.var_input_dir)).pack(side="left", padx=(6, 0))
        T.quiet(in_row, text=self._tr("browse_files"), width=48,
                command=self._choose_input_files).pack(side="left", padx=(4, 0))

        # ---- 출력 ----
        ctk.CTkLabel(card, text=self._tr("out"), font=self.font_body,
                     text_color=T.TX_BODY).grid(row=4, column=0, columnspan=3, sticky="w",
                                                padx=14, pady=(4, 0))
        out_row = ctk.CTkFrame(card, fg_color="transparent")
        out_row.grid(row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=(2, 4))
        self.ent_out_dir = T.entry(out_row, textvariable=self.var_out_dir)
        self.ent_out_dir.pack(side="left", fill="x", expand=True)
        self._watch_path_entry(self.ent_out_dir, self.var_out_dir)
        T.quiet(out_row, text=self._tr("browse"), width=48,
                command=lambda: self._choose_dir(self.var_out_dir)).pack(side="left", padx=(6, 0))

        # ---- 파일명 필드 ----
        name_row = ctk.CTkFrame(card, fg_color="transparent")
        name_row.grid(row=6, column=0, columnspan=3, sticky="ew", padx=14, pady=(6, 0))
        ctk.CTkLabel(name_row, text=self._tr("name"), font=self.font_body,
                     text_color=T.TX_BODY).pack(side="left", padx=(0, 8))
        T.quiet(name_row, text=self._tr("load_fields"), width=52,
                command=self._refresh_naming_fields).pack(side="right")
        self.cb_naming = T.option(name_row, variable=self.var_naming_field,
                                  values=self._naming_values)
        self.cb_naming.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # 고른 필드가 파일명으로 쓸 만한지 — 고르는 자리에서 바로 보인다. 개수는 모노스페이스.
        self.lbl_field_quality = ctk.CTkLabel(card, text="", font=T.mono(12),
                                              text_color=T.TX_MUTED, anchor="w")
        self.lbl_field_quality.grid(row=7, column=0, columnspan=3, sticky="w",
                                    padx=14, pady=(2, 0))
        self._update_field_quality()

        self._pad_bottom(card, 8)

    # ---- ② 미션 ----
    def _build_mission_card(self, row_idx):
        card = self._card(row_idx, "sec_mission")

        ctk.CTkLabel(card, text=self._tr("model"), font=self.font_body,
                     text_color=T.TX_BODY).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=4)
        self.cb_drone = T.option(card, variable=self.var_drone_model,
                                 values=enums.get_supported_drone_models())
        self.cb_drone.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=4)

        self._entry_row(card, 2, "alt_m", self.var_altitude)
        self._entry_row(card, 3, "speed_ms", self.var_auto_flight_speed)
        self._entry_row(card, 4, "buffer_m", self.var_geometry_buffer)
        self._pad_bottom(card, 5)

    # ---- ③ 상세 설정 (접이식 — 매일 만지는 값이 아니다) ----
    def _build_advanced_section(self, row_idx):
        self.btn_adv = ctk.CTkButton(self.sidebar, text="", command=self._toggle_advanced,
                                     fg_color="transparent", hover_color=T.ACCENT_QUIET,
                                     text_color=T.TX_BODY, anchor="w", height=T.H_MD,
                                     font=self.font_section, corner_radius=T.R_CARD,
                                     border_width=1, border_color=T.BORDER_SUBTLE)
        self.btn_adv.grid(row=row_idx, column=0, padx=16, pady=(12, 0), sticky="ew")

        card = T.card(self.sidebar)
        card.grid(row=row_idx + 1, column=0, padx=16, pady=(6, 0), sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        self.adv_card = card

        self._entry_row(card, 0, "margin_m", self.var_margin)
        self._entry_row(card, 1, "pitch_deg", self.var_gimbal_pitch)
        self._entry_row(card, 2, "shoot_h", self.var_shoot_height)
        self._entry_row(card, 3, "trans_speed", self.var_global_transitional_speed)
        self._entry_row(card, 4, "takeoff_h", self.var_takeoff_security_height)
        self._entry_row(card, 5, "simplify_m", self.var_simplify_tolerance)

        for r, (label_key, v1, v2) in enumerate([
            ("overlap_cam", self.var_overlap_camera_h, self.var_overlap_camera_w),
            ("overlap_lidar", self.var_overlap_lidar_h, self.var_overlap_lidar_w),
        ], start=6):
            ctk.CTkLabel(card, text=self._tr(label_key), font=self.font_body,
                         text_color=T.TX_BODY).grid(row=r, column=0, sticky="w",
                                                     padx=(14, 8), pady=4)
            sub = ctk.CTkFrame(card, fg_color="transparent")
            sub.grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
            T.entry(sub, textvariable=v1, width=56, font=T.mono(12)).pack(side="left")
            T.entry(sub, textvariable=v2, width=56, font=T.mono(12)).pack(side="left", padx=(6, 0))

        self.chk_tf = T.check(card, text=self._tr("tf_follow"),
                              variable=self.var_use_terrain_follow)
        self.chk_tf.grid(row=8, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 4))
        for r, (key, var) in enumerate([
            ("set_times", self.var_set_times),
            ("takeoff_ref", self.var_set_takeoff_ref_point),
            ("pack_kmz", self.var_pack_kmz),
        ], start=9):
            T.check(card, text=self._tr(key), variable=var).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=14, pady=4)

        self._pad_bottom(card, 12)
        self._apply_advanced_state()

    def _toggle_advanced(self):
        self._advanced_open = not self._advanced_open
        self._apply_advanced_state()

    def _apply_advanced_state(self):
        arrow = "▾" if self._advanced_open else "▸"
        self.btn_adv.configure(text=f"{arrow}  {self._tr('sec_advanced')}")
        if self._advanced_open:
            self.adv_card.grid()
        else:
            self.adv_card.grid_remove()

    # ---- 실행 존: 안전 판정은 결정하는 자리에서 보여야 한다 ----
    def _build_run_zone(self):
        frm = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        frm.pack(fill="x", padx=16, pady=(10, 12))

        # 안전 판정은 배지다 — 솔리드 채움이 아니라 상태색 틴트 + 좌측 상태 레일.
        # 상태색은 의미가 고정돼 있어 강조 용도로 전용되지 않는다.
        # height 를 명시하지 않으면 CTkFrame 기본 200 이 배지를 세로로 부풀린다(실측).
        self.safety_card = ctk.CTkFrame(frm, corner_radius=T.R_CONTROL, border_width=1,
                                        height=T.H_MD, fg_color=T.STATUS["idle"][1],
                                        border_color=T.BORDER_SUBTLE)
        self.safety_card.pack(fill="x")
        self.safety_card.pack_propagate(False)
        self.safety_rail = ctk.CTkFrame(self.safety_card, width=2, height=T.H_MD,
                                        corner_radius=0, fg_color=T.STATUS["idle"][0])
        self.safety_rail.pack(side="left", fill="y", padx=(0, 10))
        self.btn_safety_indicator = ctk.CTkLabel(self.safety_card, text=self._tr("checking"),
                                                 font=T.font(13, "bold"), anchor="w",
                                                 height=T.H_MD, text_color=T.STATUS["idle"][0])
        self.btn_safety_indicator.pack(side="left", pady=2)

        # 지표는 판정과 같은 줄에 둔다 — 한 줄을 아끼고, 판정의 근거는 판정 옆에 있어야 읽힌다.
        self.lbl_metrics = ctk.CTkLabel(self.safety_card, text="-", font=T.mono(12),
                                        anchor="e", height=T.H_MD, text_color=T.TX_MUTED)
        self.lbl_metrics.pack(side="right", padx=(8, 10), pady=2)

        self.btn_run = T.primary(frm, text=self._tr("run_batch"), command=self._on_run)
        self.btn_run.pack(fill="x", pady=(8, 6))

        # 리포트(실행의 결과)와 프리셋(설정 묶음)을 한 줄에 둔다. 프리셋이 무엇인지는
        # 라벨만으로 알 수 없으므로 설명을 툴팁으로 붙인다 — 상시 표시하면 두 줄을 먹는다.
        sub = ctk.CTkFrame(frm, fg_color="transparent")
        sub.pack(fill="x")
        self.btn_report = T.quiet(sub, text=self._tr("open_report"), width=100,
                                  height=T.H_SM, command=self._open_report)
        self.btn_report.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._refresh_report_button()

        for key, cmd in (("load_preset", self._on_load_preset),
                         ("save_preset", self._on_save_preset)):
            b = T.quiet(sub, text=self._tr(key), width=100, height=T.H_SM, command=cmd)
            b.pack(side="left", expand=True, fill="x", padx=(3, 0))
            T.tooltip(b, lambda: self._tr("preset_hint"))

    def _bind_events(self):
        """변수 trace 는 변수와 함께 살아남으므로 최초 1회만 건다 (재생성 시 재호출 금지 — 중복 트리거)."""
        self.var_drone_model.trace_add("write", lambda *a: self._on_drone_model_change())
        for v in (self.var_drone_model, self.var_altitude, self.var_auto_flight_speed):
            v.trace_add("write", lambda *a: self._update_safety_status())
        for v in (self.var_input_dir, self.var_input_format, self.var_geometry_buffer):
            v.trace_add("write", lambda *a: self._debounce_map_preview())
        self.var_naming_field.trace_add("write", lambda *a: self._update_field_quality())

    # --------------------------------------------------------------------------
    # 로직
    # --------------------------------------------------------------------------
    def _log(self, msg: str):
        try:
            self.txt_log.insert("end", msg.rstrip() + "\n")
            self.txt_log.see("end")
        except Exception:
            pass

    def _on_drone_model_change(self):
        model = self.var_drone_model.get().lower().strip()
        if model in TF_MODELS:
            self.chk_tf.configure(state="normal")
            self.var_status.set(f"{model}: {self._tr('tf_supported')}")
        else:
            self.var_use_terrain_follow.set(False)
            self.chk_tf.configure(state="disabled")
            self.var_status.set(f"{model}: {self._tr('tf_not_supported')}")

    def _update_safety_status(self):
        result = validate_mission_config({
            "altitude": to_float(self.var_altitude.get()),
            "auto_flight_speed": to_float(self.var_auto_flight_speed.get()),
            "drone_model": self.var_drone_model.get().lower(),
        })
        status = result.get('status', 'warning')
        metrics = result.get('metrics', {})
        self._last_safety = status
        self._last_safety_msgs = result.get('messages', [])

        fg, bg = T.STATUS.get(status, T.STATUS["idle"])
        self.btn_safety_indicator.configure(
            text=f"{self._tr('status_prefix')}{self._tr(status)}", text_color=fg)
        self.safety_card.configure(fg_color=bg)
        self.safety_rail.configure(fg_color=fg)
        approx = f" · ≈{metrics.get('spec_model')} 사양" if metrics.get('spec_approx') else ""
        self.lbl_metrics.configure(
            text=f"GSD {metrics.get('gsd', '-')} cm · BLUR {metrics.get('blur', '-')} cm{approx}")

    # ---- 지도 미리보기 ----
    def _debounce_map_preview(self):
        if self._map_debounce_timer:
            try: self.after_cancel(self._map_debounce_timer)
            except Exception: pass
        self._map_debounce_timer = self.after(800, self._update_map_preview)

    def _set_scan_label(self, files_text, polys, skipped=0):
        if not hasattr(self, "lbl_scan"):
            return
        text = self._tr("scan_line").format(files=files_text, polys=polys)
        if skipped:
            text += self._tr("scan_skipped").format(n=skipped)
        self.lbl_scan.configure(text=f"  {text}  ")

    def _update_map_preview(self):
        self._map_debounce_timer = None
        if not tkintermapview or not hasattr(self, 'map_view'):
            return
        try:
            if not self.map_view.winfo_exists():
                return
        except tk.TclError:
            return

        # 지우기를 먼저 — 폴더가 무효여도 김 빠진 그림을 남기지 않는다(B10)
        self.map_view.delete_all_marker()
        self.map_view.delete_all_path()
        self.map_view.delete_all_polygon()

        files = self._input_files()
        if not files:
            self._set_scan_label("0", 0)
            return

        buf = to_float(self.var_geometry_buffer.get()) or 0.0
        drawn = 0
        skipped = 0
        pts = []

        for f in files[:PREVIEW_MAX_FILES]:
            try:
                # 배치는 피처당 KMZ 하나를 만든다 — 미리보기도 피처 단위로 그린다(B8)
                if f.suffix.lower() == '.gpkg':
                    lyr = read_gpkg_layer(f)
                    for _, feat in polygon_features(lyr.features):
                        if drawn >= PREVIEW_MAX_FEATURES:
                            skipped += 1
                            continue
                        lonlat = polygon_coords_from_geoms([feat.geom], lyr.epsg,
                                                           geometry_buffer_m=buf)
                        coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                        self._draw_preview_polygon(coords, drawn)
                        pts.extend(coords)
                        drawn += 1
                elif f.suffix.lower() == '.kmz':
                    with zipfile.ZipFile(f, 'r') as z:
                        kml_names = [n for n in z.namelist() if n.endswith('.kml')]
                        if not kml_names:
                            continue
                        root = ET.fromstring(z.read(kml_names[0]))
                        ns = {'k': 'http://www.opengis.net/kml/2.2'}
                        c_elem = root.find('.//k:coordinates', ns)
                        # 요소 진리값 함정: 자식 없는 요소는 거짓 — is not None 로 판정(B1)
                        if c_elem is not None and c_elem.text:
                            coords = []
                            for tok in c_elem.text.strip().split():
                                p = tok.split(',')
                                if len(p) >= 2:
                                    coords.append((float(p[1]), float(p[0])))
                            if coords and drawn < PREVIEW_MAX_FEATURES:
                                self._draw_preview_polygon(coords, drawn)
                                pts.extend(coords)
                                drawn += 1
                else:
                    lonlat = parse_polygon_coords_from_kml(f)
                    coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                    if drawn < PREVIEW_MAX_FEATURES:
                        self._draw_preview_polygon(coords, drawn)
                        pts.extend(coords)
                        drawn += 1
            except Exception as e:
                self._log(f"[지도] {f.name}: {e}")

        shown = min(len(files), PREVIEW_MAX_FILES)
        files_text = f"{shown}/{len(files)}" if len(files) > shown else str(len(files))
        self._set_scan_label(files_text, drawn, skipped)
        if len(files) > PREVIEW_MAX_FILES or skipped:
            self._log(f"[지도] 미리보기 한도 — 파일 {shown}/{len(files)}개, "
                      f"생략된 폴리곤 {skipped}개")
        if pts:
            self._fit_map_to(pts)

    def _draw_preview_polygon(self, coords, idx):
        # 채움 없이 테두리만 — 불투명 채움은 지도 판독을 막는다
        self.map_view.set_polygon(coords,
                                  outline_color=POLY_COLORS[idx % len(POLY_COLORS)],
                                  border_width=3, fill_color=None)

    def _fit_map_to(self, pts):
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        top, bottom = max(lats), min(lats)
        left, right = min(lons), max(lons)
        # 극소 범위는 fit 이 ValueError 를 내므로 미리 벌린다
        if top - bottom < 2e-4:
            top += 1.5e-3; bottom -= 1.5e-3
        if right - left < 2e-4:
            left -= 1.5e-3; right += 1.5e-3
        try:
            self.map_view.fit_bounding_box((top, left), (bottom, right))
        except Exception:
            self.map_view.set_position((top + bottom) / 2, (left + right) / 2)
            self.map_view.set_zoom(14)

    def _change_map_provider(self, choice):
        info = MAP_PROVIDERS.get(choice)
        if info:
            self._map_style = choice          # 재생성에서 살아남도록 기억(B3)
            self.map_view.set_tile_server(info[0], max_zoom=info[1])

    def _choose_input_files(self):
        """파일을 직접 고른다. 여러 개면 세미콜론으로 이어 한 칸에 담는다."""
        fmt = (self.var_input_format.get() or 'auto').strip().lower()
        types = {
            'gpkg': [("GeoPackage", "*.gpkg")],
            'kml': [("KML", "*.kml")],
        }.get(fmt, [("GPKG · KML", "*.gpkg *.kml"), ("GeoPackage", "*.gpkg"), ("KML", "*.kml")])
        types = types + [("모든 파일", "*.*")]

        current = (self.var_input_dir.get() or "").strip().split(INPUT_SEP)[0]
        start = current if current and Path(current).exists() else str(BASE.parent.parent)
        if Path(start).is_file():
            start = str(Path(start).parent)

        picked = filedialog.askopenfilenames(initialdir=start, filetypes=types)
        if picked:
            self.var_input_dir.set(INPUT_SEP.join(picked))

    def _choose_dir(self, var):
        current = (var.get() or "").strip()
        start = current if current and Path(current).exists() else str(BASE.parent.parent)
        d = filedialog.askdirectory(initialdir=start)
        if d:
            var.set(d)

    # ---- 파일명 필드 ----
    def _input_files(self):
        """입력 지정(폴더·파일·세미콜론 목록)에서 처리 대상 파일 목록. 엔진과 같은 해석이다."""
        spec = (self.var_input_dir.get() or '').strip()
        if not spec:
            return []
        try:
            return resolve_input_files(spec, self.var_input_format.get() or 'auto')
        except Exception:
            return []

    def _refresh_naming_fields(self):
        files = self._input_files()
        if not files:
            messagebox.showerror("Error", self._tr("input_missing"))
            return

        gpkgs = [f for f in files if f.suffix.lower() == '.gpkg']
        kmls = [f for f in files if f.suffix.lower() == '.kml']
        fmt = (self.var_input_format.get() or '').strip().lower()
        if fmt not in ('gpkg', 'kml'):
            # auto 는 실제로 있는 것을 따른다 — 없는 포맷을 가정하지 않는다
            fmt = 'gpkg' if gpkgs else ('kml' if kmls else '')
        if not fmt:
            messagebox.showwarning("Warning", self._tr("no_files").format(pat="*.gpkg, *.kml"))
            return

        if fmt == 'gpkg':
            candidates, dropped = self._get_gpkg_fields(gpkgs, None)
        else:
            candidates, dropped = self._get_kml_fields(kmls), []

        if not candidates:
            # 가짜 후보를 만들어 넣지 않는다(B5) — 자동 명명으로 안내
            self._naming_values = [AUTO_NAME]
            self.cb_naming.configure(values=self._naming_values)
            self.var_naming_field.set(AUTO_NAME)
            messagebox.showwarning("Warning", self._tr("fields_none"))
            return

        self._naming_values = [AUTO_NAME] + candidates
        self.cb_naming.configure(values=self._naming_values)
        self.var_naming_field.set('ADDRE_1_2' if 'ADDRE_1_2' in candidates else candidates[0])
        self._update_field_quality()
        msg = self._tr("fields_loaded").format(n=len(candidates))
        if dropped:
            # 전부 비어 있는 필드는 후보에서 뺐다 — 고르면 산출물이 하나만 남는다
            msg += chr(10) * 2 + self._tr("fields_dropped").format(names=", ".join(dropped))
        messagebox.showinfo("Done", msg)

    def _get_gpkg_fields(self, files: list, layer: 'str | None'):
        """(후보 필드, 전부 비어서 제외한 필드) 를 돌려주고 품질을 기억한다.

        전부 비어 있는 필드는 **후보에서 뺀다** — 고르면 산출물이 하나만 남으므로
        (실측: 83필지 중 82개 유실) 목록에 두는 것 자체가 함정이다.
        """
        files = list(files)
        if not files:
            return [], []
        intersection = None
        union = set()
        stats = {}
        for p in files[:10]:
            try:
                st = gpkg.field_stats(p, layer=layer)
                cols = {x.name for x in st}
                union.update(cols)
                intersection = cols if intersection is None else intersection.intersection(cols)
                for x in st:   # 여러 파일이면 나쁜 쪽을 남긴다
                    prev = stats.get(x.name)
                    if prev is None or x.all_null or x.collisions > prev.collisions:
                        stats[x.name] = x
            except Exception:
                pass
        names = sorted(intersection) if intersection else sorted(union)
        self._field_stats = stats
        dropped = [n for n in names if n in stats and stats[n].all_null]
        return [n for n in names if n not in dropped], dropped

    def _update_field_quality(self):
        """고른 명명 필드가 파일명으로 쓸 만한지 한 줄로 보여 준다."""
        if not hasattr(self, "lbl_field_quality"):
            return
        name = effective_naming_field(self.var_naming_field.get())
        if name is None:
            self.lbl_field_quality.configure(text=self._tr("field_quality_auto"), text_color=T.TX_MUTED)
            return
        st = getattr(self, "_field_stats", {}).get(name)
        if st is None:
            self.lbl_field_quality.configure(text="", text_color=T.TX_MUTED)
        elif st.collisions:
            self.lbl_field_quality.configure(
                text=self._tr("field_quality_dup").format(d=st.collisions),
                text_color=T.STATUS["warning"][0])
        else:
            self.lbl_field_quality.configure(
                text=self._tr("field_quality_ok").format(n=st.unique), text_color=T.TX_MUTED)

    def _get_kml_fields(self, files: list) -> list:
        files = list(files)
        if not files:
            return []
        candidates = set()
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        for p in files[:5]:
            try:
                root = ET.parse(p).getroot()
                for d in root.findall('.//kml:ExtendedData/kml:Data', ns):
                    if d.get('name'):
                        candidates.add(d.get('name'))
                for sd in root.findall('.//kml:ExtendedData/kml:SchemaData/kml:SimpleData', ns):
                    if sd.get('name'):
                        candidates.add(sd.get('name'))
                if root.findall('.//kml:Placemark/kml:name', ns):
                    candidates.add('name')
            except Exception:
                pass
        return sorted(candidates)

    # ---- 프리셋 ----
    def _on_load_preset(self):
        f = filedialog.askopenfilename(initialdir=str(BASE.parent.parent / "presets"),
                                       filetypes=[("JSON", "*.json")])
        if not f:
            return
        try:
            with open(f, 'r', encoding='utf-8') as j:
                data = json.load(j)
            self._apply_values(values_from_preset(data))
            self.var_status.set(self._tr("preset_loaded"))
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

    def _on_save_preset(self):
        f = filedialog.asksaveasfilename(initialdir=str(BASE.parent.parent / "presets"),
                                         defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not f:
            return
        try:
            data = preset_from_values(self._collect_values())
            with open(f, 'w', encoding='utf-8') as j:
                json.dump(data, j, indent=4, ensure_ascii=False)
            self.var_status.set(self._tr("preset_saved"))
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

    # ---- 리포트 ----
    def _refresh_report_button(self):
        """가장 최근 배치 리포트를 찾아 버튼을 살리거나 죽인다."""
        out_dir = Path(self._last_out_dir or self.var_out_dir.get() or ".")
        newest = None
        try:
            reports = sorted(out_dir.glob("report_*.html"), key=lambda p: p.stat().st_mtime)
            newest = reports[-1] if reports else None
        except Exception:
            pass
        self._last_report = newest
        if hasattr(self, "btn_report"):
            self.btn_report.configure(state="normal" if newest else "disabled")

    def _open_report(self):
        if self._last_report and Path(self._last_report).exists():
            try:
                os.startfile(str(self._last_report))   # Windows 전용 — 이 앱의 대상 환경이다
            except Exception as e:
                messagebox.showerror("Error", f"Failed: {e}")

    # ---- 실행 ----
    def _on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Info", self._tr("already_running"))
            return

        # 사전 점검 — 스레드에 들어가기 전에 사람이 고칠 수 있는 것은 여기서 잡는다(B13)
        spec = (self.var_input_dir.get() or '').strip()
        if not spec or not any(Path(x.strip()).exists() for x in spec.split(INPUT_SEP) if x.strip()):
            messagebox.showerror("Error", self._tr("input_missing"))
            return
        if not self._input_files():
            fmt = self.var_input_format.get()
            pats = {'gpkg': ['*.gpkg'], 'kml': ['*.kml']}.get(fmt, ['*.gpkg', '*.kml'])
            messagebox.showerror("Error", self._tr("no_files").format(pat=", ".join(pats)))
            return

        # 안전 도구가 위험 판정을 두고 조용히 실행하지 않는다(B13)
        if self._last_safety == 'danger':
            msgs = "\n".join(f"- {m}" for m in self._last_safety_msgs[:4])
            if not messagebox.askyesno(self._tr("confirm_danger_t"),
                                       self._tr("confirm_danger_m").format(msgs=msgs)):
                return

        values = self._collect_values()   # tk 변수는 메인 스레드에서만 읽는다
        self._last_out_dir = values["out_dir"]
        self.txt_log.delete("1.0", "end")
        self.var_status.set(self._tr("running"))
        self.btn_run.configure(state="disabled")
        self.worker = threading.Thread(target=self._run_job, args=(values,), daemon=True)
        self.worker.start()

    def _run_job(self, values: dict):
        qredir = LogRedirector(self.queue)
        backup_stdout, backup_stderr = sys.stdout, sys.stderr
        sys.stdout = qredir
        sys.stderr = qredir   # traceback 도 로그창으로(B7)
        try:
            batch_process_inputs(
                missions_dir=values["input_dir"],   # 폴더·파일·세미콜론 목록 — 엔진이 해석한다
                template_path=Path(self.var_template.get()),
                waylines_path=Path(self.var_waylines.get()),
                out_dir=Path(values["out_dir"]),
                input_format=values["input_format"],
                naming_field=effective_naming_field(values["naming_field"]),
                layer=None,
                set_times=bool(values["set_times"]),
                set_takeoff_ref_point=bool(values["set_takeoff_ref_point"]),
                pack_kmz=bool(values["pack_kmz"]),
                overrides=build_overrides(values),
                simplify_tolerance=to_float(values["simplify_tolerance"]) or 0.0,
            )
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout = backup_stdout
            sys.stderr = backup_stderr
            self.queue.put("<<DONE>>")

    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                if msg == "<<DONE>>":
                    self.btn_run.configure(state="normal")
                    self.var_status.set(self._tr("done"))
                    self._refresh_report_button()
                else:
                    self.txt_log.insert("end", msg)
                    self.txt_log.see("end")
        except queue.Empty:
            pass
        except Exception:
            pass   # 재생성 직후 등 위젯 과도기 — 다음 tick 에 회복된다
        finally:
            self.after(100, self._poll_queue)

    def _on_close(self):
        # 배치 중 즉사하면 쓰다 만 KMZ 가 남는다 — 한 번 묻는다(B12)
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(self._tr("confirm_quit_t"), self._tr("confirm_quit_m")):
                return
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
