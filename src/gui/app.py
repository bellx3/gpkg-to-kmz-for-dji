import json
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
                                polygon_features, polygon_coords_from_geoms)
from src.core import enums, gpkg

try:
    import tkintermapview
except ImportError:
    tkintermapview = None

BASE = Path(__file__).parent

# ------------------------------------------------------------------------------
# 팔레트 · 지도 상수
# ------------------------------------------------------------------------------
ACCENT = "#1F6AA5"
ACCENT_HOVER = "#17578C"
COL_SAFE = "#2E7D32"
COL_WARN = "#B45309"     # 흰 글자가 읽히는 어두운 앰버 (기존 #F9A825 는 대비 부족)
COL_DANGER = "#C62828"
TX_SECTION = "#7FB3D5"   # 카드 제목
TX_DIM = "gray62"

# 미리보기 폴리곤 외곽선 색 순환 — 채움 없이 테두리만 그린다.
# 불투명 채움은 위성/지도 판독을 막았다(점검 캡처로 실증).
POLY_COLORS = ["#FFD600", "#4FC3F7", "#81C784", "#FF8A65", "#BA68C8", "#F06292"]

MAP_PROVIDERS = {
    "CartoDB Dark": ("https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", 19),
    "OpenStreetMap": ("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", 19),
    "Google Hybrid": ("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}", 22),
    "VWorld Base": ("https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png", 19),
}

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
        "safety_status": "안전 상태 (Safety)",
        "checking": "확인 중...",
        "paths_data": "경로 및 데이터 (Paths & Data)",
        "fmt": "포맷",
        "in": "입력",
        "out": "출력",
        "name": "파일명",
        "browse": "찾기",
        "load_fields": "↻ 로드",
        "mission_config": "미션 설정 (Mission Config)",
        "model": "드론 모델",
        "alt_m": "임무 고도 (m)",
        "speed_ms": "비행 속도 (m/s)",
        "buffer_m": "물리적 버퍼 (m)",
        "adv_settings": "상세 설정 (Advanced)",
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
        "run_batch": "미션 생성 실행 (Batch Run)",
        "load_preset": "불러오기",
        "save_preset": "저장하기",
        "system_logs": "작업 로그 (System Logs)",
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
        "input_missing": "입력 폴더가 없습니다.",
        "no_files": "입력 폴더에 처리할 파일이 없습니다: {pat}",
        "confirm_danger_t": "위험 설정",
        "confirm_danger_m": "안전 판정이 '위험'입니다.\n{msgs}\n\n그래도 실행할까요?",
        "confirm_quit_t": "배치 실행 중",
        "confirm_quit_m": "배치가 아직 실행 중입니다. 종료하면 쓰다 만 파일이 남을 수 있습니다.\n종료할까요?",
        "fields_loaded": "필드 {n}개를 불러왔습니다.",
        "fields_none": "이름으로 쓸 필드를 찾지 못했습니다.\n파일명 자동 명명으로 진행됩니다.",
        "preset_loaded": "프리셋을 불러왔습니다.",
        "preset_saved": "프리셋을 저장했습니다.",
        "already_running": "이미 실행 중입니다.",
    },
    "en": {
        "app_title": "SkyMission Builder",
        "safety_status": "Safety Status",
        "checking": "Checking...",
        "paths_data": "Paths & Data",
        "fmt": "Format",
        "in": "Input",
        "out": "Output",
        "name": "Naming",
        "browse": "Browse",
        "load_fields": "↻ Load",
        "mission_config": "Mission Config",
        "model": "Drone Model",
        "alt_m": "Altitude (m)",
        "speed_ms": "Speed (m/s)",
        "buffer_m": "Buffer (m)",
        "adv_settings": "Advanced Settings",
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
        "system_logs": "System Logs",
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
        "input_missing": "Input directory not found.",
        "no_files": "No matching files in input directory: {pat}",
        "confirm_danger_t": "Dangerous Settings",
        "confirm_danger_m": "Safety check says DANGER.\n{msgs}\n\nRun anyway?",
        "confirm_quit_t": "Batch Running",
        "confirm_quit_m": "A batch is still running. Quitting may leave half-written files.\nQuit anyway?",
        "fields_loaded": "Loaded {n} fields.",
        "fields_none": "No naming fields found.\nFiles will be named automatically.",
        "preset_loaded": "Preset loaded.",
        "preset_saved": "Preset saved.",
        "already_running": "Already running.",
    }
}

# ------------------------------------------------------------------------------
# Main Application Class (CustomTkinter)
# ------------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")

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
        self._map_style = "CartoDB Dark"
        self._last_safety = "safe"
        self._last_safety_msgs = []
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
    # UI 구성
    # --------------------------------------------------------------------------
    def _build_ui(self):
        """전체 그리드 레이아웃 (Sidebar / Map / Log)"""
        self.font_section = ctk.CTkFont(size=13, weight="bold")
        self.font_body = ctk.CTkFont(size=12)
        self.font_logo = ctk.CTkFont(size=19, weight="bold")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # ---- [Left Sidebar] ----
        # 설정은 스크롤 영역에, 실행 버튼은 그 밖(하단 고정)에 — 첫 화면에서 RUN 이 안 보이면 안 된다
        side_wrap = ctk.CTkFrame(self, width=330, corner_radius=0)
        side_wrap.grid(row=0, column=0, rowspan=2, sticky="nsew")
        side_wrap.grid_rowconfigure(0, weight=1)
        side_wrap.grid_columnconfigure(0, weight=1)

        self.sidebar = ctk.CTkScrollableFrame(side_wrap, width=330, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.action_bar = ctk.CTkFrame(side_wrap, corner_radius=0)
        self.action_bar.grid(row=1, column=0, sticky="ew")

        head = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 12))
        ctk.CTkLabel(head, text="SkyMission Builder", font=self.font_logo).pack(side="left")
        ctk.CTkButton(head, text="EN/KR", width=52, height=22, command=self._toggle_language,
                      fg_color="transparent", border_width=1, text_color=TX_DIM).pack(side="right")

        self._build_sidebar_safety_card(row_idx=1)
        self._build_sidebar_path_card(row_idx=2)
        self._build_sidebar_mission_card(row_idx=3)
        self._build_sidebar_detail_card(row_idx=4)
        self._build_sidebar_actions()

        # ---- [Main Area] Map ----
        self.map_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.map_frame.grid(row=0, column=1, sticky="nsew")

        if tkintermapview:
            self.map_view = tkintermapview.TkinterMapView(self.map_frame, corner_radius=0)
            self.map_view.pack(fill="both", expand=True)
            url, mz = MAP_PROVIDERS[self._map_style]
            self.map_view.set_tile_server(url, max_zoom=mz)
            self.map_view.set_position(36.5, 127.5)
            self.map_view.set_zoom(7)

            self.cb_map_style = ctk.CTkOptionMenu(self.map_frame, values=list(MAP_PROVIDERS.keys()),
                                                  command=self._change_map_provider,
                                                  width=140, fg_color="#2B2B2B", button_color="#3A3A3A")
            self.cb_map_style.set(self._map_style)
            self.cb_map_style.place(relx=0.985, rely=0.02, anchor="ne")

            ctk.CTkButton(self.map_frame, text=self._tr("refresh_preview"), width=110, height=26,
                          fg_color="#2B2B2B", hover_color="#3A3A3A",
                          command=self._update_map_preview).place(relx=0.985, rely=0.075, anchor="ne")
        else:
            ctk.CTkLabel(self.map_frame,
                         text="tkintermapview 미설치 — 지도 미리보기 없이 동작합니다.\n"
                              "pip install -r requirements-optional.txt").pack(expand=True)

        # ---- [Bottom Area] Logs + Status ----
        self.log_frame = ctk.CTkFrame(self, height=200, corner_radius=0)
        self.log_frame.grid(row=1, column=1, sticky="ew")
        self.log_frame.grid_propagate(False)

        head = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(head, text=self._tr("system_logs"), font=("Consolas", 12, "bold")).pack(side="left")
        # 상태 표시줄 — var_status 가 처음으로 화면에 묶인다(B2)
        ctk.CTkLabel(head, textvariable=self.var_status, font=("Consolas", 12),
                     text_color=TX_DIM).pack(side="right")

        self.txt_log = ctk.CTkTextbox(self.log_frame, font=("Consolas", 11))
        self.txt_log.pack(fill="both", expand=True, padx=12, pady=6)

    def _card(self, row_idx, title_key):
        card = ctk.CTkFrame(self.sidebar, corner_radius=10)
        card.grid(row=row_idx, column=0, padx=12, pady=(0, 12), sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=self._tr(title_key), font=self.font_section,
                     text_color=TX_SECTION).grid(row=0, column=0, columnspan=3,
                                                 sticky="w", padx=12, pady=(10, 6))
        return card

    def _entry_row(self, card, r, label_key, var):
        ctk.CTkLabel(card, text=self._tr(label_key), font=self.font_body).grid(
            row=r, column=0, sticky="w", padx=(12, 8), pady=3)
        ctk.CTkEntry(card, textvariable=var, font=self.font_body).grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=3)

    def _pad_bottom(self, card, r):
        # width 를 명시하지 않으면 CTkFrame 기본 200 이 col0 최소폭이 되어 입력칸을 짜부라뜨린다
        ctk.CTkFrame(card, height=6, width=1, fg_color="transparent").grid(
            row=r, column=0, columnspan=3)

    def _build_sidebar_safety_card(self, row_idx):
        card = self._card(row_idx, "safety_status")
        self.btn_safety_indicator = ctk.CTkButton(card, text=self._tr("checking"), fg_color="gray",
                                                  state="disabled", text_color_disabled="white",
                                                  font=ctk.CTkFont(size=13, weight="bold"))
        self.btn_safety_indicator.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=2)
        self.lbl_metrics = ctk.CTkLabel(card, text="-", font=("Consolas", 11), text_color=TX_DIM)
        self.lbl_metrics.grid(row=2, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 10))

    def _build_sidebar_path_card(self, row_idx):
        card = self._card(row_idx, "paths_data")

        ctk.CTkLabel(card, text=self._tr("fmt"), font=self.font_body).grid(row=1, column=0, sticky="w", padx=(12, 8), pady=3)
        ctk.CTkOptionMenu(card, variable=self.var_input_format, values=["gpkg", "kml", "auto"],
                          font=self.font_body).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=3)

        ctk.CTkLabel(card, text=self._tr("in"), font=self.font_body).grid(row=2, column=0, sticky="w", padx=(12, 8), pady=3)
        ctk.CTkEntry(card, textvariable=self.var_input_dir, font=self.font_body).grid(row=2, column=1, sticky="ew", pady=3)
        ctk.CTkButton(card, text=self._tr("browse"), width=48, font=self.font_body,
                      command=lambda: self._choose_dir(self.var_input_dir)).grid(row=2, column=2, padx=(5, 12), pady=3)

        ctk.CTkLabel(card, text=self._tr("out"), font=self.font_body).grid(row=3, column=0, sticky="w", padx=(12, 8), pady=3)
        ctk.CTkEntry(card, textvariable=self.var_out_dir, font=self.font_body).grid(row=3, column=1, sticky="ew", pady=3)
        ctk.CTkButton(card, text=self._tr("browse"), width=48, font=self.font_body,
                      command=lambda: self._choose_dir(self.var_out_dir)).grid(row=3, column=2, padx=(5, 12), pady=3)

        ctk.CTkLabel(card, text=self._tr("name"), font=self.font_body).grid(row=4, column=0, sticky="w", padx=(12, 8), pady=3)
        self.cb_naming = ctk.CTkOptionMenu(card, variable=self.var_naming_field,
                                           values=self._naming_values, font=self.font_body)
        self.cb_naming.grid(row=4, column=1, sticky="ew", pady=3)
        ctk.CTkButton(card, text=self._tr("load_fields"), width=48, font=self.font_body,
                      command=self._refresh_naming_fields).grid(row=4, column=2, padx=(5, 12), pady=3)

        self._pad_bottom(card, 5)

    def _build_sidebar_mission_card(self, row_idx):
        card = self._card(row_idx, "mission_config")

        ctk.CTkLabel(card, text=self._tr("model"), font=self.font_body).grid(row=1, column=0, sticky="w", padx=(12, 8), pady=3)
        self.cb_drone = ctk.CTkOptionMenu(card, variable=self.var_drone_model,
                                          values=enums.get_supported_drone_models(), font=self.font_body)
        self.cb_drone.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=3)

        self._entry_row(card, 2, "alt_m", self.var_altitude)
        self._entry_row(card, 3, "speed_ms", self.var_auto_flight_speed)
        self._entry_row(card, 4, "buffer_m", self.var_geometry_buffer)
        self._pad_bottom(card, 5)

    def _build_sidebar_detail_card(self, row_idx):
        card = self._card(row_idx, "adv_settings")

        self._entry_row(card, 1, "margin_m", self.var_margin)
        self._entry_row(card, 2, "pitch_deg", self.var_gimbal_pitch)
        self._entry_row(card, 3, "shoot_h", self.var_shoot_height)
        self._entry_row(card, 4, "trans_speed", self.var_global_transitional_speed)
        self._entry_row(card, 5, "takeoff_h", self.var_takeoff_security_height)
        self._entry_row(card, 6, "simplify_m", self.var_simplify_tolerance)

        # Overlap 2×2 — 정체불명 4칸(B 디자인)을 라벨 있는 두 줄로
        for r, (label_key, v1, v2) in enumerate([
            ("overlap_cam", self.var_overlap_camera_h, self.var_overlap_camera_w),
            ("overlap_lidar", self.var_overlap_lidar_h, self.var_overlap_lidar_w),
        ], start=7):
            ctk.CTkLabel(card, text=self._tr(label_key), font=self.font_body).grid(
                row=r, column=0, sticky="w", padx=(12, 8), pady=3)
            sub = ctk.CTkFrame(card, fg_color="transparent")
            sub.grid(row=r, column=1, columnspan=2, sticky="w", pady=3)
            ctk.CTkEntry(sub, textvariable=v1, width=52, font=self.font_body).pack(side="left")
            ctk.CTkEntry(sub, textvariable=v2, width=52, font=self.font_body).pack(side="left", padx=(6, 0))

        self.chk_tf = ctk.CTkCheckBox(card, text=self._tr("tf_follow"), font=self.font_body,
                                      variable=self.var_use_terrain_follow)
        self.chk_tf.grid(row=9, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 3))
        for r, (key, var) in enumerate([
            ("set_times", self.var_set_times),
            ("takeoff_ref", self.var_set_takeoff_ref_point),
            ("pack_kmz", self.var_pack_kmz),
        ], start=10):
            ctk.CTkCheckBox(card, text=self._tr(key), font=self.font_body,
                            variable=var).grid(row=r, column=0, columnspan=3, sticky="w", padx=12, pady=3)

        self._pad_bottom(card, 13)

    def _build_sidebar_actions(self):
        frm = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        frm.pack(fill="x", padx=12, pady=(10, 12))

        self.btn_run = ctk.CTkButton(frm, text=self._tr("run_batch"), height=44,
                                     font=ctk.CTkFont(size=14, weight="bold"),
                                     command=self._on_run, fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.btn_run.pack(fill="x", pady=(0, 6))

        sub = ctk.CTkFrame(frm, fg_color="transparent")
        sub.pack(fill="x")
        ctk.CTkButton(sub, text=self._tr("load_preset"), width=100, font=self.font_body,
                      command=self._on_load_preset).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(sub, text=self._tr("save_preset"), width=100, font=self.font_body,
                      command=self._on_save_preset).pack(side="left", expand=True, fill="x", padx=(3, 0))

        ctk.CTkLabel(frm, text="DJI WPML 1.0.6", font=("Consolas", 10),
                     text_color=TX_DIM).pack(pady=(10, 0))

    def _bind_events(self):
        """변수 trace 는 변수와 함께 살아남으므로 최초 1회만 건다 (재생성 시 재호출 금지 — 중복 트리거)."""
        self.var_drone_model.trace_add("write", lambda *a: self._on_drone_model_change())
        for v in (self.var_drone_model, self.var_altitude, self.var_auto_flight_speed):
            v.trace_add("write", lambda *a: self._update_safety_status())
        for v in (self.var_input_dir, self.var_input_format, self.var_geometry_buffer):
            v.trace_add("write", lambda *a: self._debounce_map_preview())

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

        color = {'safe': COL_SAFE, 'warning': COL_WARN, 'danger': COL_DANGER}.get(status, 'gray')
        self.btn_safety_indicator.configure(
            text=f"{self._tr('status_prefix')}{self._tr(status)}", fg_color=color)
        approx = f" (≈{metrics.get('spec_model')} 사양)" if metrics.get('spec_approx') else ""
        self.lbl_metrics.configure(
            text=f"GSD {metrics.get('gsd', '-')}cm · Blur {metrics.get('blur', '-')}cm{approx}")

    # ---- 지도 미리보기 ----
    def _debounce_map_preview(self):
        if self._map_debounce_timer:
            try: self.after_cancel(self._map_debounce_timer)
            except Exception: pass
        self._map_debounce_timer = self.after(800, self._update_map_preview)

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

        input_dir = Path(self.var_input_dir.get())
        if not input_dir.exists() or not input_dir.is_dir():
            return

        fmt = self.var_input_format.get()
        if fmt == 'gpkg':
            files = sorted(input_dir.glob('*.gpkg'))
        elif fmt == 'kml':
            files = sorted(list(input_dir.glob('*.kml')) + list(input_dir.glob('*.kmz')))
        else:
            files = sorted(list(input_dir.glob('*.gpkg')) + list(input_dir.glob('*.kml'))
                           + list(input_dir.glob('*.kmz')))
        if not files:
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

        if len(files) > PREVIEW_MAX_FILES or skipped:
            self._log(f"[지도] 미리보기 한도 — 파일 {min(len(files), PREVIEW_MAX_FILES)}/{len(files)}개, "
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

    def _choose_dir(self, var):
        current = (var.get() or "").strip()
        start = current if current and Path(current).exists() else str(BASE.parent.parent)
        d = filedialog.askdirectory(initialdir=start)
        if d:
            var.set(d)

    # ---- 파일명 필드 ----
    def _refresh_naming_fields(self):
        fmt = (self.var_input_format.get() or '').strip().lower()
        input_dir = Path((self.var_input_dir.get() or '').strip())
        if not input_dir.exists():
            messagebox.showerror("Error", self._tr("input_missing"))
            return

        if fmt in ('auto', ''):
            if any(input_dir.glob('*.gpkg')):
                fmt = 'gpkg'
            elif any(input_dir.glob('*.kml')):
                fmt = 'kml'
            else:
                messagebox.showwarning("Warning", self._tr("no_files").format(pat="*.gpkg, *.kml"))
                return

        candidates = self._get_gpkg_fields(input_dir, None) if fmt == 'gpkg' \
            else self._get_kml_fields(input_dir)

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
        messagebox.showinfo("Done", self._tr("fields_loaded").format(n=len(candidates)))

    def _get_gpkg_fields(self, input_dir: Path, layer: 'str | None') -> list:
        files = list(input_dir.glob('*.gpkg'))
        if not files:
            return []
        intersection = None
        union = set()
        for p in files[:10]:
            try:
                cols = set(gpkg.field_names(p, layer=layer))
                union.update(cols)
                intersection = cols if intersection is None else intersection.intersection(cols)
            except Exception:
                pass
        return sorted(intersection) if intersection else sorted(union)

    def _get_kml_fields(self, input_dir: Path) -> list:
        files = list(input_dir.glob('*.kml'))
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

    # ---- 실행 ----
    def _on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Info", self._tr("already_running"))
            return

        # 사전 점검 — 스레드에 들어가기 전에 사람이 고칠 수 있는 것은 여기서 잡는다(B13)
        input_dir = Path((self.var_input_dir.get() or '').strip())
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Error", self._tr("input_missing"))
            return
        fmt = self.var_input_format.get()
        pats = {'gpkg': ['*.gpkg'], 'kml': ['*.kml']}.get(fmt, ['*.gpkg', '*.kml'])
        if not any(any(input_dir.glob(p)) for p in pats):
            messagebox.showerror("Error", self._tr("no_files").format(pat=", ".join(pats)))
            return

        # 안전 도구가 위험 판정을 두고 조용히 실행하지 않는다(B13)
        if self._last_safety == 'danger':
            msgs = "\n".join(f"- {m}" for m in self._last_safety_msgs[:4])
            if not messagebox.askyesno(self._tr("confirm_danger_t"),
                                       self._tr("confirm_danger_m").format(msgs=msgs)):
                return

        values = self._collect_values()   # tk 변수는 메인 스레드에서만 읽는다
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
                missions_dir=Path(values["input_dir"]),
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
