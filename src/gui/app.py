import threading
import queue
import sys
import re
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

import customtkinter as ctk  # NEW: CustomTkinter
# 내부 로직 호출
from src.core.generator import batch_process_inputs, validate_mission_config, parse_polygon_coords_from_kml, parse_polygon_coords_from_gpkg, read_gpkg_to_gdf, parse_polygon_coords_from_gpkg_direct
from src.core import enums

try:
    import tkintermapview
except ImportError:
    tkintermapview = None

BASE = Path(__file__).parent

# ------------------------------------------------------------------------------
# 유틸 변환 함수
# ------------------------------------------------------------------------------

def to_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def to_float(v: str):
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    try: return float(s)
    except Exception: return None

def to_int(v: str):
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    try: return int(s)
    except Exception: return None

# ------------------------------------------------------------------------------
# stdout 리다이렉터
# ------------------------------------------------------------------------------
class LogRedirector:
    def __init__(self, q: queue.Queue):
        self.q = q
    def write(self, s):
        if s: self.q.put(s)
    def flush(self):
        pass

# ------------------------------------------------------------------------------
# 다국어 번역 데이터 (Default: KO)
# ------------------------------------------------------------------------------
TRANSLATIONS = {
    "ko": {
        "app_title": "SkyMission Builder - 프로 에디션",
        "safety_status": "안전 상태 (Safety)",
        "checking": "확인 중...",
        "paths_data": "경로 및 데이터 (Paths & Data)",
        "fmt": "포맷",
        "in": "입력",
        "out": "출력",
        "name": "파일명",
        "load_first": "(로드 필요)",
        "mission_config": "미션 설정 (Mission Config)",
        "model": "드론 모델",
        "alt_m": "임무 고도 (m)",
        "speed_ms": "비행 속도 (m/s)",
        "buffer_m": "물리적 버퍼 (m)",
        "adv_settings": "상세 설정 (Advanced)",
        "margin_m": "마진 (m)",
        "pitch_deg": "짐벌 피치 (°)",
        "tf_follow": "지형 팔로우 (Terrain Follow)",
        "overlap": "중첩도 Cam/Lidar",
        "run_batch": "미션 생성 실행 (Batch Run)",
        "load_preset": "불러오기",
        "save_preset": "저장하기",
        "system_logs": "작업 로그 (System Logs)",
        "view_mode": "지도/위성 전환",
        "safe": "정상: 안전",
        "warning": "주의: 확인 필요",
        "danger": "위험: 설정 조정",
        "tf_supported": "지형 팔로우 지원됨",
        "tf_not_supported": "지형 팔로우 미지원",
        "lang_toggle": "언어 변경 (EN/KR)",
        "status_prefix": "상태: ",
        "ready": "준비됨",
        "running": "실행 중...",
        "done": "완료",
    },
    "en": {
        "app_title": "SkyMission Builder - Pro Edition",
        "safety_status": "Safety Status",
        "checking": "Checking...",
        "paths_data": "Paths & Data",
        "fmt": "Fmt",
        "in": "In",
        "out": "Out",
        "name": "Name",
        "load_first": "(Load First)",
        "mission_config": "Mission Config",
        "model": "Model",
        "alt_m": "Alt (m)",
        "speed_ms": "Speed (m/s)",
        "buffer_m": "Buffer (m)",
        "adv_settings": "Advanced Settings",
        "margin_m": "Margin (m)",
        "pitch_deg": "Pitch (°)",
        "tf_follow": "Terrain Follow",
        "overlap": "Overlap Cam/Lidar",
        "run_batch": "RUN BATCH MISSION",
        "load_preset": "Load Preset",
        "save_preset": "Save Preset",
        "system_logs": "System Logs",
        "view_mode": "View Mode",
        "safe": "SAFE",
        "warning": "CHECK",
        "danger": "DANGER",
        "tf_supported": "Terrain Follow Supported",
        "tf_not_supported": "No Terrain Follow",
        "lang_toggle": "Switch Lang (KR/EN)",
        "status_prefix": "STATUS: ",
        "ready": "Ready",
        "running": "Running...",
        "done": "Done",
    }
}

# ------------------------------------------------------------------------------
# Main Application Class (CustomTkinter)
# ------------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # 1. 기본 설정
        ctk.set_appearance_mode("Dark")       # Modes: "System" (standard), "Dark", "Light"
        ctk.set_default_color_theme("dark-blue")  # Themes: "blue" (standard), "green", "dark-blue"
        
        self.curr_lang = "ko"  # Default Language
        self.title(self._tr("app_title"))
        self.geometry("1600x900")
        # Maximize window on start (Windows only)
        self.after(0, lambda: self.state('zoomed'))
        # 데이터 관리
        self.queue = queue.Queue()
        self.worker = None
        
        # 변수 초기화 (StringVar 등은 tk/ctk 혼용 가능하지만 ctk 위젯엔 ctk.StringVar 권장)
        self._init_variables()

        # UI 구성
        self._build_ui()
        
        # 이벤트 바인딩
        self._bind_events()
        
        # 초기화 실행
        self._on_drone_model_change()
        self._update_safety_status()
        self.after(100, self._poll_queue)

    def _init_variables(self):
        """설정 변수 초기화"""
        # Paths
        self.var_input_format = ctk.StringVar(value="gpkg")
        self.var_input_dir = ctk.StringVar(value=str(BASE.parent.parent / "input"))
        self.var_out_dir = ctk.StringVar(value=str(BASE.parent.parent / "output"))
        self.var_naming_field = ctk.StringVar()
        
        # Mission
        self.var_drone_model = ctk.StringVar(value="mavic3e")
        self.var_altitude = ctk.StringVar(value="150.0")
        self.var_auto_flight_speed = ctk.StringVar(value="10")
        self.var_geometry_buffer = ctk.StringVar(value="0.0")
        
        # Detailed Settings
        self.var_margin = ctk.StringVar(value="0")
        self.var_gimbal_pitch = ctk.StringVar(value="-90.0")
        self.var_global_transitional_speed = ctk.StringVar(value="")
        self.var_takeoff_security_height = ctk.StringVar(value="20")
        
        self.var_set_times = ctk.BooleanVar(value=True)
        self.var_set_takeoff_ref_point = ctk.BooleanVar(value=True)
        self.var_use_terrain_follow = ctk.BooleanVar(value=False)
        self.var_simplify_tolerance = ctk.StringVar(value="0.0")
        self.var_pack_kmz = ctk.BooleanVar(value=True)
        
        # Overlap
        self.var_overlap_camera_h = ctk.StringVar(value="80")
        self.var_overlap_camera_w = ctk.StringVar(value="70")
        self.var_overlap_lidar_h = ctk.StringVar(value="50")
        self.var_overlap_lidar_w = ctk.StringVar(value="50")
        
        # Templates
        self.var_template = ctk.StringVar(value=str(BASE.parent / "templates" / "template.kml"))
        self.var_waylines = ctk.StringVar(value=str(BASE.parent / "templates" / "waylines.wpml"))
        
        # Status & Map
        self.var_status = ctk.StringVar(value=self._tr("ready"))
        self._map_debounce_timer = None

    def _tr(self, key):
        return TRANSLATIONS.get(self.curr_lang, TRANSLATIONS["en"]).get(key, key)

    def _toggle_language(self):
        self.curr_lang = "en" if self.curr_lang == "ko" else "ko"
        self._rebuild_full_ui()

    def _rebuild_full_ui(self):
        # Remove all widgets
        for widget in self.winfo_children():
            widget.destroy()
        # Re-init UI
        self._build_ui()
        self.title(self._tr("app_title"))
        self._on_drone_model_change()
        self._update_safety_status()

    def _build_ui(self):
        """전체 그리드 레이아웃 구성 (Sidebar / Main / Log)"""
        # Grid 설정: col 0=Sidebar, col 1=Main
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)  # Main area
        self.grid_rowconfigure(1, weight=0)  # Log/Status area (bottom)

        # ----------------------------------------------------
        # [Left Sidebar] - Scrollable
        # ----------------------------------------------------
        self.sidebar = ctk.CTkScrollableFrame(self, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)
        
        # Sidebar Header
        lbl_logo = ctk.CTkLabel(self.sidebar, text="SkyMission Builder", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_logo.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        # 1. 안전 모니터 카드 (최상단 배치)
        self._build_sidebar_safety_card(row_idx=1)
        
        # 2. 경로 설정 카드
        self._build_sidebar_path_card(row_idx=2)
        
        # 3. 미션 설정 카드
        self._build_sidebar_mission_card(row_idx=3)
        
        # 4. 상세 설정 (Collapsible 아님, 그냥 카드)
        self._build_sidebar_detail_card(row_idx=4)
        
        # 5. 실행 버튼 그룹
        self._build_sidebar_actions(row_idx=5)

        # ----------------------------------------------------
        # [Main Area] - Map View
        # ----------------------------------------------------
        self.map_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.map_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        
        if tkintermapview:
            self.map_view = tkintermapview.TkinterMapView(self.map_frame, corner_radius=0)
            self.map_view.pack(fill="both", expand=True)
            # Default to CartoDB Dark Matter for modern Dark UI
            self.map_view.set_tile_server("https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", max_zoom=19)
            self.map_view.set_position(36.5, 127.5)
            self.map_view.set_zoom(7)
            
            # Map Style Selector
            self.map_providers = {
                "CartoDB Dark": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "OpenStreetMap": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "Google Hybrid": "https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}",
                "VWorld Base": "https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png"
            }
            self.cb_map_style = ctk.CTkOptionMenu(self.map_frame, values=list(self.map_providers.keys()),
                                                  command=self._change_map_provider,
                                                  width=120, fg_color="#333333", button_color="#444444")
            self.cb_map_style.set("CartoDB Dark")
            self.cb_map_style.place(relx=0.98, rely=0.02, anchor="ne")
        else:
            ctk.CTkLabel(self.map_frame, text="tkintermapview not found").pack(expand=True)

        # ----------------------------------------------------
        # [Bottom Area] - Logs & Status
        # ----------------------------------------------------
        # 높이를 좀 줄여서 로그는 하단에 배치 (Log Panel)
        self.log_frame = ctk.CTkFrame(self, height=200, corner_radius=0)
        self.log_frame.grid(row=1, column=1, sticky="ew")
        self.log_frame.grid_propagate(False) # 높이 고정
        
        # Log Header
        ctk.CTkLabel(self.log_frame, text=self._tr("system_logs"), font=("Consolas", 12, "bold")).pack(anchor="w", padx=10, pady=(5,0))
        
        # Log Textbox
        self.txt_log = ctk.CTkTextbox(self.log_frame, font=("Consolas", 11))
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Status Bar overlay or integrated
        # (이미 로그 프레임이 있으니 별도 상태바보다는 여기에 통합 표시)

    def _build_sidebar_safety_card(self, row_idx):
        card = ctk.CTkFrame(self.sidebar)
        card.grid(row=row_idx, column=0, padx=10, pady=10, sticky="ew")
        
        ctk.CTkLabel(card, text=self._tr("safety_status"), font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        
        self.btn_safety_indicator = ctk.CTkButton(card, text=self._tr("checking"), fg_color="gray", state="disabled", text_color_disabled="white")
        self.btn_safety_indicator.pack(fill="x", padx=10, pady=5)
        
        self.lbl_metrics = ctk.CTkLabel(card, text="-", font=("Consolas", 11), text_color="gray")
        self.lbl_metrics.pack(anchor="w", padx=10, pady=(0, 10))

    def _build_sidebar_path_card(self, row_idx):
        card = ctk.CTkFrame(self.sidebar)
        card.grid(row=row_idx, column=0, padx=10, pady=10, sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        
        # Header with Language Toggle
        h_frm = ctk.CTkFrame(card, fg_color="transparent")
        h_frm.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 5))
        ctk.CTkLabel(h_frm, text=self._tr("paths_data"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(h_frm, text="EN/KR", width=40, height=20, command=self._toggle_language, fg_color="transparent", border_width=1, text_color="gray").pack(side="right")
        
        # Format
        ctk.CTkLabel(card, text=self._tr("fmt")).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        ctk.CTkOptionMenu(card, variable=self.var_input_format, values=["gpkg", "kml", "auto"]).grid(row=1, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        
        # Input Dir
        ctk.CTkLabel(card, text=self._tr("in")).grid(row=2, column=0, sticky="w", padx=10)
        ctk.CTkEntry(card, textvariable=self.var_input_dir).grid(row=2, column=1, sticky="ew", padx=(0,5))
        ctk.CTkButton(card, text="..", width=30, command=lambda: self._choose_dir(self.var_input_dir)).grid(row=2, column=2, padx=10)
        
        # Output Dir
        ctk.CTkLabel(card, text=self._tr("out")).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ctk.CTkEntry(card, textvariable=self.var_out_dir).grid(row=3, column=1, sticky="ew", padx=(0,5))
        ctk.CTkButton(card, text="..", width=30, command=lambda: self._choose_dir(self.var_out_dir)).grid(row=3, column=2, padx=10)
        
        # Naming Field
        ctk.CTkLabel(card, text=self._tr("name")).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.cb_naming = ctk.CTkOptionMenu(card, variable=self.var_naming_field, values=[self._tr("load_first")])
        self.cb_naming.grid(row=4, column=1, sticky="ew", padx=(0,5))
        ctk.CTkButton(card, text="R", width=30, command=self._refresh_naming_fields).grid(row=4, column=2, padx=10)
        
        ctk.CTkLabel(card, text="").grid(row=5, column=0) # Spacer

    def _build_sidebar_mission_card(self, row_idx):
        card = ctk.CTkFrame(self.sidebar)
        card.grid(row=row_idx, column=0, padx=10, pady=10, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text=self._tr("mission_config"), font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))
        
        # Drone
        ctk.CTkLabel(card, text=self._tr("model")).grid(row=1, column=0, sticky="w", padx=10, pady=2)
        drone_list = enums.get_supported_drone_models()
        self.cb_drone = ctk.CTkOptionMenu(card, variable=self.var_drone_model, values=drone_list)
        self.cb_drone.grid(row=1, column=1, sticky="ew", padx=10, pady=2)
        
        # Altitude
        ctk.CTkLabel(card, text=self._tr("alt_m")).grid(row=2, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkEntry(card, textvariable=self.var_altitude).grid(row=2, column=1, sticky="ew", padx=10, pady=2)
        
        # Speed
        ctk.CTkLabel(card, text=self._tr("speed_ms")).grid(row=3, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkEntry(card, textvariable=self.var_auto_flight_speed).grid(row=3, column=1, sticky="ew", padx=10, pady=2)

        # Buffer
        ctk.CTkLabel(card, text=self._tr("buffer_m")).grid(row=4, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkEntry(card, textvariable=self.var_geometry_buffer).grid(row=4, column=1, sticky="ew", padx=10, pady=2)
        
        ctk.CTkLabel(card, text="").grid(row=5, column=0) # Spacer

    def _build_sidebar_detail_card(self, row_idx):
        card = ctk.CTkFrame(self.sidebar)
        card.grid(row=row_idx, column=0, padx=10, pady=10, sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(card, text=self._tr("adv_settings"), font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))
        
        # Margin
        ctk.CTkLabel(card, text=self._tr("margin_m")).grid(row=1, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkEntry(card, textvariable=self.var_margin).grid(row=1, column=1, sticky="ew", padx=10, pady=2)
        
        # Gimbal
        ctk.CTkLabel(card, text=self._tr("pitch_deg")).grid(row=2, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkEntry(card, textvariable=self.var_gimbal_pitch).grid(row=2, column=1, sticky="ew", padx=10, pady=2)
        
        # TF
        self.chk_tf = ctk.CTkCheckBox(card, text=self._tr("tf_follow"), variable=self.var_use_terrain_follow)
        self.chk_tf.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=5)
        
        # Overlap (Compact)
        sub = ctk.CTkFrame(card, fg_color="transparent")
        sub.grid(row=4, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        
        ctk.CTkLabel(sub, text=self._tr("overlap")).pack(side="top", anchor="w")
        
        sub2 = ctk.CTkFrame(sub, fg_color="transparent")
        sub2.pack(fill="x")
        ctk.CTkEntry(sub2, textvariable=self.var_overlap_camera_h, width=35).pack(side="left", padx=2)
        ctk.CTkEntry(sub2, textvariable=self.var_overlap_camera_w, width=35).pack(side="left", padx=2)
        ctk.CTkLabel(sub2, text="|").pack(side="left", padx=5)
        ctk.CTkEntry(sub2, textvariable=self.var_overlap_lidar_h, width=35).pack(side="left", padx=2)
        ctk.CTkEntry(sub2, textvariable=self.var_overlap_lidar_w, width=35).pack(side="left", padx=2)
        
        ctk.CTkLabel(card, text="").grid(row=99, column=0) # Spacer

    def _build_sidebar_actions(self, row_idx):
        frm = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        frm.grid(row=row_idx, column=0, padx=10, pady=20, sticky="ew")
        
        self.btn_run = ctk.CTkButton(frm, text=self._tr("run_batch"), height=40, font=ctk.CTkFont(size=14, weight="bold"), 
                                     command=self._on_run, fg_color="#106BA3", hover_color="#0D4F75")
        self.btn_run.pack(fill="x", pady=5)
        
        # Preset buttons
        sub = ctk.CTkFrame(frm, fg_color="transparent")
        sub.pack(fill="x")
        ctk.CTkButton(sub, text=self._tr("load_preset"), width=100, command=self._on_load_preset).pack(side="left", expand=True, padx=2)
        ctk.CTkButton(sub, text=self._tr("save_preset"), width=100, command=self._on_save_preset).pack(side="left", expand=True, padx=2)

    def _bind_events(self):
        # 기체 변경 관찰
        self.var_drone_model.trace_add("write", lambda *a: self._on_drone_model_change())
        
        # 안전 점검 트리거
        param_vars = [self.var_drone_model, self.var_altitude, self.var_auto_flight_speed]
        for v in param_vars:
            v.trace_add("write", lambda *a: self._update_safety_status())

        # 지도 미리보기 갱신 트리거
        self.var_input_dir.trace_add("write", lambda *a: self._debounce_map_preview())
        self.var_input_format.trace_add("write", lambda *a: self._debounce_map_preview())
        self.var_geometry_buffer.trace_add("write", lambda *a: self._debounce_map_preview())

    # --------------------------------------------------------------------------
    # Logic Methods (Adapted from original)
    # --------------------------------------------------------------------------
    
    def _on_drone_model_change(self):
        model = self.var_drone_model.get().lower()
        tf_supported = ['mavic3e', 'mavic3t', 'mavic3m', 'm30', 'm30t', 'm300', 'm350', 'm3d', 'm3td', 'flycart30']
        
        if any(m in model for m in tf_supported):
            self.chk_tf.configure(state="normal")
            self.var_status.set(f"{model}: {self._tr('tf_supported')}")
        else:
            self.var_use_terrain_follow.set(False)
            self.chk_tf.configure(state="disabled")
            self.var_status.set(f"{model}: {self._tr('tf_not_supported')}")

    def _update_safety_status(self):
        overrides = {
            "altitude": to_float(self.var_altitude.get()),
            "auto_flight_speed": to_float(self.var_auto_flight_speed.get()),
            "drone_model": self.var_drone_model.get().lower()
        }
        result = validate_mission_config(overrides)
        status = result.get('status', 'warning')
        metrics = result.get('metrics', {})

        # Colors
        color_map = {'safe': '#2E7D32', 'warning': '#F9A825', 'danger': '#C62828'}
        
        st_color = color_map.get(status, 'gray')
        st_text = self._tr(status) # "safe", "warning", etc.
        st_prefix = self._tr('status_prefix')
        
        self.btn_safety_indicator.configure(text=f"{st_prefix}{st_text}", fg_color=st_color)
        
        m_text = f"GSD: {metrics.get('gsd', '-')}cm | Blur: {metrics.get('blur', '-')}cm"
        self.lbl_metrics.configure(text=m_text)

    def _debounce_map_preview(self):
        if self._map_debounce_timer:
            self.after_cancel(self._map_debounce_timer)
        self._map_debounce_timer = self.after(800, self._update_map_preview)

    def _update_map_preview(self):
        if not tkintermapview or not hasattr(self, 'map_view'): return
        input_dir = Path(self.var_input_dir.get())
        if not input_dir.exists() or not input_dir.is_dir(): return

        self.map_view.delete_all_marker()
        self.map_view.delete_all_path()
        self.map_view.delete_all_polygon()

        fmt = self.var_input_format.get()
        files = []
        if fmt == 'gpkg': files = sorted(input_dir.glob('*.gpkg'))
        elif fmt == 'kml': files = sorted(list(input_dir.glob('*.kml')) + list(input_dir.glob('*.kmz')))
        else: files = sorted(list(input_dir.glob('*.gpkg')) + list(input_dir.glob('*.kml')) + list(input_dir.glob('*.kmz')))

        if not files: return
        sample_files = files[:10]
        points_for_zoom = []

        for f in sample_files:
            try:
                coords = []
                if f.suffix.lower() == '.gpkg':
                    gdf = read_gpkg_to_gdf(f)
                    lonlat, _ = parse_polygon_coords_from_gpkg_direct(gdf, geometry_buffer_m=to_float(self.var_geometry_buffer.get()) or 0.0)
                    coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                elif f.suffix.lower() == '.kmz':
                    # Simplified logic for KMZ preview
                    with zipfile.ZipFile(f, 'r') as z:
                        kml_name = [n for n in z.namelist() if n.endswith('.kml')][0]
                        with z.open(kml_name) as kf:
                            root = ET.fromstring(kf.read())
                            ns = {'k': 'http://www.opengis.net/kml/2.2'}
                            c_elem = root.find('.//k:coordinates', ns)
                            if c_elem and c_elem.text:
                                for tok in c_elem.text.strip().split():
                                    p = tok.split(',')
                                    if len(p) >= 2: coords.append((float(p[1]), float(p[0])))
                else:
                    lonlat = parse_polygon_coords_from_kml(f)
                    coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                
                if coords:
                    # Fix: Ensure outline_color is hex
                    print(f"[Map] Drawing polygon for {f.name} with {len(coords)} points.")
                    # Use a fill color with transparency-like hex if supported, or just distinct color
                    # tkintermapview polygons: outline_color, fill_color (hex)
                    # Note: fill_color=None might be invisible if outline is thin. Let's use a fill.
                    poly = self.map_view.set_polygon(coords, 
                                              outline_color="#FFD600", 
                                              border_width=2, 
                                              fill_color="#FFD600") # Filled for visibility
                    # Try to add transparency via canvas if possible (advanced)
                    try:
                        # 50% opacity (approx)
                        poly.add_position(coords[0][0], coords[0][1]) # force redraw? no.
                    except: pass
                    
                    points_for_zoom.extend(coords)
            except Exception as e:
                print(f"[Map] Error loading {f.name}: {e}")
                import traceback
                traceback.print_exc()

        if points_for_zoom:
            lats = [p[0] for p in points_for_zoom]
            lons = [p[1] for p in points_for_zoom]
            
            if not lats or not lons: return
            
            min_lat, max_lat = min(lats), max(lats)
            min_lon, max_lon = min(lons), max(lons)
            
            # center
            c_lat = (min_lat + max_lat) / 2
            c_lon = (min_lon + max_lon) / 2
            
            self.map_view.set_position(c_lat, c_lon)
            self.map_view.set_zoom(14) # Start with a reasonable zoom

    def _change_map_provider(self, choice):
        url = self.map_providers.get(choice)
        if url:
            mz = 19
            if "google" in choice.lower(): mz = 22
            self.map_view.set_tile_server(url, max_zoom=mz)

    def _choose_dir(self, var):
        d = filedialog.askdirectory(initialdir=str(BASE))
        if d: var.set(d)

    def _refresh_naming_fields(self):
        fmt = (self.var_input_format.get() or '').strip().lower()
        input_dir = Path((self.var_input_dir.get() or '').strip())
        if not input_dir.exists():
            messagebox.showerror("Error", "Input directory not found")
            return

        # Auto-detect format
        if fmt == 'auto' or fmt == '':
            if any(input_dir.glob('*.gpkg')):
                fmt = 'gpkg'
            elif any(input_dir.glob('*.kml')):
                fmt = 'kml'
            else:
                messagebox.showwarning("Warning", "No GPKG/KML files found in input directory.")
                return

        candidates = []
        if fmt == 'gpkg':
            candidates = self._get_gpkg_fields(input_dir, None)
        elif fmt == 'kml':
            candidates = self._get_kml_fields(input_dir)
        else:
            messagebox.showwarning("Warning", f"Unsupported format: {fmt}")
            return

        # Fallback if no fields found or error occurred
        if not candidates:
            candidates = ["ADDRE_1_2", "name"]
            
        self.cb_naming.configure(values=candidates)
        # Select first available candidate that matches preference or default
        default = 'ADDRE_1_2' if 'ADDRE_1_2' in candidates else candidates[0]
        self.var_naming_field.set(default)
        
        # Show success message only if genuine candidates found
        if len(candidates) > 2 or (candidates[0] != "ADDRE_1_2" and candidates[0] != "name"):
             messagebox.showinfo("Done", f"Loaded {len(candidates)} fields.")

    def _get_gpkg_fields(self, input_dir: Path, layer: str | None) -> list[str]:
        try:
            import geopandas as gpd
        except ImportError:
            messagebox.showerror("Error", "GeoPandas required for GPKG scanning.\npip install geopandas pyogrio shapely")
            return []

        files = list(input_dir.glob('*.gpkg'))
        if not files: return []

        intersection = None
        union = set()
        count = 0
        for p in files:
            if count >= 10: break
            count += 1
            try:
                gdf = gpd.read_file(p, layer=layer) if layer else gpd.read_file(p)
                cols = [c for c in gdf.columns if c.lower() != 'geometry']
                s = set(cols)
                union.update(s)
                intersection = s if intersection is None else intersection.intersection(s)
            except Exception: pass
        
        return sorted(intersection) if intersection and len(intersection) > 0 else sorted(union)

    def _get_kml_fields(self, input_dir: Path) -> list[str]:
        files = list(input_dir.glob('*.kml'))
        if not files: return []
        candidates = set()
        for p in files[:5]:
            try:
                tree = ET.parse(p)
                root = tree.getroot()
                ns = {'kml': 'http://www.opengis.net/kml/2.2'}
                for d in root.findall('.//kml:ExtendedData/kml:Data', ns):
                    n = d.get('name')
                    if n: candidates.add(n)
                for sd in root.findall('.//kml:ExtendedData/kml:SchemaData/kml:SimpleData', ns):
                    n = sd.get('name')
                    if n: candidates.add(n)
                if root.findall('.//kml:Placemark/kml:name', ns):
                    candidates.add('name')
            except Exception: pass
        return sorted(candidates)

    def _on_load_preset(self):
        f = filedialog.askopenfilename(initialdir=str(BASE.parent.parent / "presets"), filetypes=[("JSON", "*.json")])
        if not f: return
        import json
        try:
            with open(f, 'r', encoding='utf-8') as j:
                data = json.load(j)
                # Assign values
                self.var_altitude.set(str(data.get("altitude", "")))
                self.var_drone_model.set(str(data.get("drone_model", "mavic3e")))
                # ... (Map other fields similarly)
            messagebox.showinfo("Done", "Preset loaded.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

    def _on_save_preset(self):
        f = filedialog.asksaveasfilename(initialdir=str(BASE.parent.parent / "presets"), defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not f: return
        import json
        try:
            data = {
                "altitude": to_float(self.var_altitude.get()),
                "drone_model": self.var_drone_model.get(),
                # ... (other fields)
            }
            with open(f, 'w', encoding='utf-8') as j:
                json.dump(data, j, indent=4)
            messagebox.showinfo("Done", "Preset saved.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

    def _on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Info", "Already running.")
            return
        self.txt_log.delete("1.0", "end")
        self.var_status.set(self._tr("running"))
        self.btn_run.configure(state="disabled")
        self.worker = threading.Thread(target=self._run_job, daemon=True)
        self.worker.start()

    def _run_job(self):
        qredir = LogRedirector(self.queue)
        backup_stdout = sys.stdout
        sys.stdout = qredir
        try:
            alt_val = to_float(self.var_altitude.get())
            overrides = {
                "altitude": alt_val,
                "shoot_height": alt_val,
                "margin": to_int(self.var_margin.get()),
                "overlap_camera_h": to_int(self.var_overlap_camera_h.get()),
                "overlap_camera_w": to_int(self.var_overlap_camera_w.get()),
                "overlap_lidar_h": to_int(self.var_overlap_lidar_h.get()),
                "overlap_lidar_w": to_int(self.var_overlap_lidar_w.get()),
                "auto_flight_speed": to_int(self.var_auto_flight_speed.get()),
                "global_transitional_speed": to_int(self.var_global_transitional_speed.get()),
                "takeoff_security_height": to_int(self.var_takeoff_security_height.get()),
                "drone_model": self.var_drone_model.get(),
                "gimbal_pitch": to_float(self.var_gimbal_pitch.get()),
                "use_terrain_follow": bool(self.var_use_terrain_follow.get()),
                "geometry_buffer_m": to_float(self.var_geometry_buffer.get()),
            }
            
            batch_process_inputs(
                missions_dir=Path(self.var_input_dir.get()),
                template_path=Path(self.var_template.get()),
                waylines_path=Path(self.var_waylines.get()),
                out_dir=Path(self.var_out_dir.get()),
                input_format=self.var_input_format.get(),
                naming_field=(self.var_naming_field.get() or None),
                layer=None,
                set_times=bool(self.var_set_times.get()),
                set_takeoff_ref_point=bool(self.var_set_takeoff_ref_point.get()),
                overrides=overrides,
                simplify_tolerance=to_float(self.var_simplify_tolerance.get()) or 0.0,
            )
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout = backup_stdout
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
        finally:
            self.after(100, self._poll_queue)


if __name__ == "__main__":
    app = App()
    app.mainloop()