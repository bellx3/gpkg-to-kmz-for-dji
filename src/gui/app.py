import threading
import queue
import sys
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 내부 로직 호출
from src.core.generator import batch_process_inputs, validate_mission_config, parse_polygon_coords_from_kml, parse_polygon_coords_from_gpkg, read_gpkg_to_gdf, parse_polygon_coords_from_gpkg_direct
from src.core import enums

try:
    import tkintermapview
except ImportError:
    tkintermapview = None

BASE = Path(__file__).parent

# 유틸 변환 함수

def to_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def to_float(v: str):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def to_int(v: str):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None


class LogRedirector:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SkyMission Builder - Desktop UI")
        self.geometry("1200x850") # 가로 폭 확장
        
        
        self.queue = queue.Queue()
        self.worker = None
        self._build_ui()
        
        # 기체 변경 관찰 및 초기 상태 설정
        self.var_drone_model.trace_add("write", self._on_drone_model_change)
        
        # 파라미터 실시간 안전 점검 트리거 설정
        param_vars = [self.var_drone_model, self.var_altitude, self.var_auto_flight_speed]
        for v in param_vars:
            v.trace_add("write", self._update_safety_status)

        self._on_drone_model_change()
        self._update_safety_status()
        
        # 입력 환경 변화 관찰 (지도 미리보기 갱신)
        self._map_debounce_timer = None
        self.var_input_dir.trace_add("write", lambda *a: self._debounce_map_preview())
        self.var_input_format.trace_add("write", lambda *a: self._debounce_map_preview())
        self.var_geometry_buffer.trace_add("write", lambda *a: self._debounce_map_preview())

        self.after(100, self._poll_queue)

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Malgun Gothic", 10, "bold"), foreground="#0078d4")
        self.var_status = tk.StringVar(value="준비됨")

        # 전체 컨테이너
        main_frm = ttk.Frame(self, padding=12)
        main_frm.pack(fill=tk.BOTH, expand=True)
        
        # 메인 좌우 분할 (설정 사이드바 / 메인 맵&로그)
        self.main_paned = tk.PanedWindow(main_frm, orient=tk.HORIZONTAL, sashwidth=4, bg="#ddd", borderwidth=0)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # ---------------------------------------------------------
        # [왼쪽 섹션: 사이드바]
        sidebar_frame = ttk.Frame(self.main_paned, width=360)
        self.main_paned.add(sidebar_frame, width=360)

        # 사이드바 내 스크롤 영역
        s_canvas = tk.Canvas(sidebar_frame, highlightthickness=0, bg="#f3f3f3")
        s_scrollbar = ttk.Scrollbar(sidebar_frame, orient="vertical", command=s_canvas.yview)
        sidebar = ttk.Frame(s_canvas, padding=5) # Padding reduced
        
        s_canvas.pack(side="left", fill="both", expand=True)
        s_scrollbar.pack(side="right", fill="y")
        s_canvas.configure(yscrollcommand=s_scrollbar.set)
        
        sidebar_id = s_canvas.create_window((0, 0), window=sidebar, anchor="nw")
        
        def _on_canvas_configure(event):
            s_canvas.itemconfig(sidebar_id, width=event.width)
            
        def _on_mousewheel(event):
            s_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        def _bind_mouse(event):
            s_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mouse(event):
            s_canvas.unbind_all("<MouseWheel>")

        s_canvas.bind("<Configure>", _on_canvas_configure)
        sidebar.bind("<Configure>", lambda e: s_canvas.configure(scrollregion=s_canvas.bbox("all")))
        
        # 마우스가 사이드바 위에 있을 때만 휠 작동
        sidebar_frame.bind("<Enter>", _bind_mouse)
        sidebar_frame.bind("<Leave>", _unbind_mouse)

        # 1. 경로 및 데이터 설정
        group_path = ttk.LabelFrame(sidebar, text=" 기본 설정 (Paths & Data) ", padding=10)
        group_path.pack(fill=tk.X, pady=(0, 8))
        group_path.columnconfigure(1, weight=1)

        l_row = 0
        def add_item(parent, label, var, is_dir=False, is_file=False, filetypes=None, values=None, row=None):
            nonlocal l_row
            curr_row = row if row is not None else l_row
            ttk.Label(parent, text=label).grid(row=curr_row, column=0, sticky=tk.W, pady=2)
            if values:
                cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly")
                cb.grid(row=curr_row, column=1, sticky=tk.EW, pady=2, padx=4)
                if row is None: l_row += 1
                return cb
            else:
                ent = ttk.Entry(parent, textvariable=var)
                ent.grid(row=curr_row, column=1, sticky=tk.EW, pady=2, padx=4)
                if is_dir:
                    ttk.Button(parent, text="..", width=3, command=lambda: self._choose_dir(var)).grid(row=curr_row, column=2, pady=2)
                if is_file:
                    ttk.Button(parent, text="..", width=3, command=lambda: self._choose_file(var, filetypes)).grid(row=curr_row, column=2, pady=2)
                if row is None: l_row += 1
                return ent

        self.var_input_format = tk.StringVar(value="gpkg")
        add_item(group_path, "입력 포맷", self.var_input_format, values=["gpkg", "kml", "auto"])
        
        self.var_input_dir = tk.StringVar(value=str(BASE.parent.parent / "input"))
        add_item(group_path, "입력 폴더", self.var_input_dir, is_dir=True)

        self.var_out_dir = tk.StringVar(value=str(BASE.parent.parent / "output"))
        add_item(group_path, "출력 폴더", self.var_out_dir, is_dir=True)

        self.var_naming_field = tk.StringVar()
        ttk.Label(group_path, text="파일명 필드").grid(row=l_row, column=0, sticky=tk.W, pady=2)
        self.cb_naming_field = ttk.Combobox(group_path, textvariable=self.var_naming_field, state="readonly")
        self.cb_naming_field.grid(row=l_row, column=1, sticky=tk.EW, pady=2, padx=4)
        ttk.Button(group_path, text="↻", width=3, command=self._refresh_naming_fields).grid(row=l_row, column=2, pady=2)
        l_row += 1

        # 2. 핵심 임무 설정 (사이드바 - 자주 쓰는 것만)
        group_mission = ttk.LabelFrame(sidebar, text=" 미션 설정 (Mission) ", padding=10)
        group_mission.pack(fill=tk.X, pady=(0, 8))
        group_mission.columnconfigure(1, weight=1)

        m_row = 0
        def add_m_item(label, var, values=None):
            nonlocal m_row
            ttk.Label(group_mission, text=label).grid(row=m_row, column=0, sticky=tk.W, pady=2)
            if values:
                cb = ttk.Combobox(group_mission, textvariable=var, values=values, state="readonly")
                cb.grid(row=m_row, column=1, sticky=tk.EW, pady=2, padx=4)
                m_row += 1
                return cb
            else:
                ent = ttk.Entry(group_mission, textvariable=var)
                ent.grid(row=m_row, column=1, sticky=tk.EW, pady=2, padx=4)
                m_row += 1
                return ent

        self.var_drone_model = tk.StringVar(value="mavic3e")
        drone_list = enums.get_supported_drone_models()
        self.cb_drone = add_m_item("드론 모델", self.var_drone_model, values=drone_list)

        self.var_altitude = tk.StringVar(value="150.0")
        add_m_item("임무 고도 (m)", self.var_altitude)

        self.var_auto_flight_speed = tk.StringVar(value="10")
        add_m_item("비행 속도 (m/s)", self.var_auto_flight_speed)

        self.var_geometry_buffer = tk.StringVar(value="0.0")
        add_m_item("물리적 버퍼 (m)", self.var_geometry_buffer)
        ttk.Label(group_mission, text="(양수:확장, 음수:축소)", font=("Malgun Gothic", 7), foreground="#888").grid(row=m_row-1, column=1, sticky=tk.E, padx=10)

        # 3. 실시간 안전 점검 (사이드바 간단 표시)
        self.group_safety = ttk.LabelFrame(sidebar, text=" 안전 상태 (Safety) ", padding=10)
        self.group_safety.pack(fill=tk.X, pady=(0, 8))
        self.group_safety.columnconfigure(1, weight=1)

        self.safety_canvas = tk.Canvas(self.group_safety, width=20, height=20, highlightthickness=0)
        self.safety_canvas.grid(row=0, column=0, padx=(0, 5))
        self.safety_circle = self.safety_canvas.create_oval(2, 2, 18, 18, fill="gray")

        self.lbl_safety_status = ttk.Label(self.group_safety, text="확인 중...", font=("Malgun Gothic", 9, "bold"))
        self.lbl_safety_status.grid(row=0, column=1, sticky=tk.W)

        self.lbl_metrics = ttk.Label(self.group_safety, text="-", font=("Consolas", 8), foreground="#666")
        self.lbl_metrics.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        # 액션 버튼
        group_action = ttk.Frame(sidebar, padding=5)
        group_action.pack(fill=tk.X, pady=5)
        
        self.btn_run = ttk.Button(group_action, text="  미션 생성 실행 (Batch Run)  ", command=self._on_run, style="Accent.TButton")
        self.btn_run.pack(fill=tk.X, pady=5)

        preset_frm = ttk.Frame(group_action)
        preset_frm.pack(fill=tk.X)
        self.btn_load_preset = ttk.Button(preset_frm, text="불러오기", command=self._on_load_preset)
        self.btn_load_preset.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self.btn_save_preset = ttk.Button(preset_frm, text="저장하기", command=self._on_save_preset)
        self.btn_save_preset.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # ---------------------------------------------------------
        # [오른쪽: 메인 콘텐츠 (맵 & 로그 상하 분할)]
        content_pane = ttk.Frame(self.main_paned)
        self.main_paned.add(content_pane)
        
        self.v_paned = tk.PanedWindow(content_pane, orient=tk.VERTICAL, sashwidth=4, bg="#ddd", borderwidth=0)
        self.v_paned.pack(fill=tk.BOTH, expand=True)

        # 맵 영역
        self.map_area = ttk.Frame(self.v_paned)
        self.v_paned.add(self.map_area, height=500)
        
        if tkintermapview:
            self.map_view = tkintermapview.TkinterMapView(self.map_area, corner_radius=0)
            self.map_view.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            # 기본: 구글 위성 하이브리드
            self.map_view.set_tile_server("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}", max_zoom=22)
            self.map_view.set_position(36.5, 127.5, marker=False)
            self.map_view.set_zoom(7)
            
            # 맵 위 오버레이 컨트롤 (우측 상단)
            btn_view = ttk.Button(self.map_view, text="Map View ↔ Satellite", width=20, command=self._toggle_map_view)
            btn_view.place(relx=1.0, rely=0.0, anchor=tk.NE, x=-10, y=10)

            # 테두리 느낌을 위해 프레임에 배경색 부여
            self.map_area.configure(style="Map.TFrame")
            style.configure("Map.TFrame", background="#ddd")
        else:
            lbl_no_map = ttk.Label(self.map_area, text="tkintermapview 미설치", justify=tk.CENTER)
            lbl_no_map.pack(expand=True)

        # 로그 영역
        self.log_area = ttk.Frame(self.v_paned)
        self.v_paned.add(self.log_area, height=250)
        
        self.log_notebook = ttk.Notebook(self.log_area)
        self.log_notebook.pack(fill=tk.BOTH, expand=True)

        self.txt_log = tk.Text(self.log_notebook, wrap=tk.WORD, bg="#f8f9fa", font=("Consolas", 9), borderwidth=0)
        self.log_notebook.add(self.txt_log, text=" 작업 로그 (Logs) ")

        # 신규: 상세 설정 탭
        self.settings_frm = ttk.Frame(self.log_notebook, padding=10)
        self.log_notebook.add(self.settings_frm, text=" 상세 설정 (Detailed Settings) ")
        
        s_row = 0
        def add_s_item(label, var, values=None):
            nonlocal s_row
            ttk.Label(self.settings_frm, text=label).grid(row=s_row, column=0, sticky=tk.W, pady=2)
            if values:
                cb = ttk.Combobox(self.settings_frm, textvariable=var, values=values, state="readonly")
                cb.grid(row=s_row, column=1, sticky=tk.EW, pady=2, padx=4)
            else:
                ttk.Entry(self.settings_frm, textvariable=var).grid(row=s_row, column=1, sticky=tk.EW, padx=4)
            s_row += 1

        self.var_margin = tk.StringVar(value="0")
        add_s_item("마진 (m)", self.var_margin)
        
        self.var_gimbal_pitch = tk.StringVar(value="-90.0")
        add_s_item("짐벌 피치 (°)", self.var_gimbal_pitch)

        self.var_global_transitional_speed = tk.StringVar()
        add_s_item("전환 속도 (m/s)", self.var_global_transitional_speed)

        self.var_takeoff_security_height = tk.StringVar(value="20")
        add_s_item("이륙 안전 고도 (m)", self.var_takeoff_security_height)

        self.var_set_times = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.settings_frm, text="생성/업데이트 시간 갱신", variable=self.var_set_times).grid(row=s_row, column=1, sticky=tk.W)
        s_row += 1

        self.var_set_takeoff_ref_point = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.settings_frm, text="이륙 기준점 자동 설정", variable=self.var_set_takeoff_ref_point).grid(row=s_row, column=1, sticky=tk.W)
        s_row += 1

        self.var_use_terrain_follow = tk.BooleanVar(value=False)
        self.chk_tf = ttk.Checkbutton(self.settings_frm, text="실시간 지형 팔로우 활성화", variable=self.var_use_terrain_follow)
        self.chk_tf.grid(row=s_row, column=1, sticky=tk.W, pady=2, padx=4)
        s_row += 1

        self.var_simplify_tolerance = tk.StringVar(value="0.0")
        add_s_item("단순화 오차 (m)", self.var_simplify_tolerance)

        self.var_pack_kmz = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.settings_frm, text="KMZ 패키징 사용", variable=self.var_pack_kmz).grid(row=s_row, column=1, sticky=tk.W)
        s_row += 1

        # 중첩도 상세
        overlap_labelfrm = ttk.LabelFrame(self.settings_frm, text=" 중첩도 설정 (%) ", padding=5)
        overlap_labelfrm.grid(row=s_row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        s_row += 1
        
        self.var_overlap_camera_h = tk.StringVar(value="80")
        self.var_overlap_camera_w = tk.StringVar(value="70")
        self.var_overlap_lidar_h = tk.StringVar(value="50")
        self.var_overlap_lidar_w = tk.StringVar(value="50")

        ttk.Label(overlap_labelfrm, text="카메라(종/횡):").grid(row=0, column=0)
        ttk.Entry(overlap_labelfrm, textvariable=self.var_overlap_camera_h, width=5).grid(row=0, column=1, padx=2)
        ttk.Entry(overlap_labelfrm, textvariable=self.var_overlap_camera_w, width=5).grid(row=0, column=2, padx=2)
        ttk.Label(overlap_labelfrm, text="라이다(종/횡):").grid(row=0, column=3, padx=(10,0))
        ttk.Entry(overlap_labelfrm, textvariable=self.var_overlap_lidar_h, width=5).grid(row=0, column=4, padx=2)
        ttk.Entry(overlap_labelfrm, textvariable=self.var_overlap_lidar_w, width=5).grid(row=0, column=5, padx=2)

        # 템플릿 영역
        tpl_labelfrm = ttk.LabelFrame(self.settings_frm, text=" 템플릿 경로 ", padding=5)
        tpl_labelfrm.grid(row=s_row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.var_template = tk.StringVar(value=str(BASE.parent / "templates" / "template.kml"))
        self.var_waylines = tk.StringVar(value=str(BASE.parent / "templates" / "waylines.wpml"))
        
        ttk.Label(tpl_labelfrm, text="KML").grid(row=0, column=0)
        ttk.Entry(tpl_labelfrm, textvariable=self.var_template).grid(row=0, column=1, sticky=tk.EW)
        ttk.Label(tpl_labelfrm, text="WPML").grid(row=1, column=0)
        ttk.Entry(tpl_labelfrm, textvariable=self.var_waylines).grid(row=1, column=1, sticky=tk.EW)

        # 신규: 분석 상세 탭
        self.analysis_frm = ttk.Frame(self.log_notebook, padding=10)
        self.log_notebook.add(self.analysis_frm, text=" 안전 분석 (Safety Analysis) ")
        
        self.txt_safety_msg = tk.Text(self.analysis_frm, wrap=tk.WORD, bg="#fdfdfe", font=("Malgun Gothic", 9), borderwidth=0)
        self.txt_safety_msg.pack(fill=tk.BOTH, expand=True)
        self.txt_safety_msg.config(state=tk.DISABLED)

        # 상태바
        status_bar = ttk.Label(main_frm, textvariable=self.var_status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, ipady=2)

    def _on_drone_model_change(self, *args):
        """드론 모델 선택에 따라 특정 기능 활성/비활성 제어"""
        model = self.var_drone_model.get().lower()
        
        # 실시간 지형 팔로우 지원 기체 (WPML 기반 최신 Enterprise 모델)
        tf_supported = [
            'mavic3e', 'mavic3t', 'mavic3m', 
            'm30', 'm30t', 'm300', 'm350', 
            'm3d', 'm3td', 'flycart30'
        ]
        
        if any(m in model for m in tf_supported):
            self.chk_tf.state(['!disabled'])
            self.var_status.set(f"{model} 모델: 지형 팔로우 지원됨")
        else:
            self.var_use_terrain_follow.set(False)
            self.chk_tf.state(['disabled'])
            self.var_status.set(f"{model} 모델: 지형 팔로우 미지원 (비활성)")

    def _update_safety_status(self, *args):
        """파라미터 변경 시 실시간으로 안전 상태 업데이트"""
        overrides = {
            "altitude": to_float(self.var_altitude.get()),
            "auto_flight_speed": to_float(self.var_auto_flight_speed.get()),
            "drone_model": self.var_drone_model.get().lower()
        }
        
        result = validate_mission_config(overrides)
        status = result.get('status', 'warning')
        messages = result.get('messages', [])
        metrics = result.get('metrics', {})

        # UI 업데이트
        colors = {
            'safe': '#28a745',    # Green
            'warning': '#ffc107', # Yellow
            'danger': '#dc3545'   # Red
        }
        status_texts = {
            'safe': '정상: 안전한 임무',
            'warning': '주의: 확인 필요',
            'danger': '위험: 설정 조정 권장'
        }

        color = colors.get(status, 'gray')
        self.safety_canvas.itemconfig(self.safety_circle, fill=color)
        self.lbl_safety_status.config(text=status_texts.get(status, status), foreground=color)
        
        # 지표 표시
        m_text = f"GSD: {metrics.get('gsd', '-')}cm | Blur: {metrics.get('blur', '-')}cm | Shutter: {metrics.get('shutter', '-')}"
        self.lbl_metrics.config(text=m_text)

        # 메시지 표시
        self.txt_safety_msg.config(state=tk.NORMAL)
        self.txt_safety_msg.delete("1.0", tk.END)
        self.txt_safety_msg.insert("1.0", "\n".join(messages))
        self.txt_safety_msg.config(state=tk.DISABLED)

    def _update_map_preview(self, *args):
        """입력 폴더 내 폴리곤들을 지도에 표시"""
        if not tkintermapview or not hasattr(self, 'map_view'):
            return

        input_dir = Path(self.var_input_dir.get())
        if not input_dir.exists() or not input_dir.is_dir():
            return

        # 모든 마커/패스/폴리곤 제거
        self.map_view.delete_all_marker()
        self.map_view.delete_all_path()
        self.map_view.delete_all_polygon()

        fmt = self.var_input_format.get()
        files = []
        if fmt == 'gpkg':
            files = sorted(input_dir.glob('*.gpkg'))
        elif fmt == 'kml':
            files = sorted(list(input_dir.glob('*.kml')) + list(input_dir.glob('*.kmz')))
        else:
            files = sorted(list(input_dir.glob('*.gpkg')) + list(input_dir.glob('*.kml')) + list(input_dir.glob('*.kmz')))

        if not files:
            return

        # 너무 많으면 상위 10개만 샘플링하여 표시
        sample_files = files[:10]
        points_for_zoom = []

        for f in sample_files:
            try:
                coords = []
                if f.suffix.lower() == '.gpkg':
                    gdf = read_gpkg_to_gdf(f)
                    lonlat, _ = parse_polygon_coords_from_gpkg_direct(
                        gdf, 
                        geometry_buffer_m=to_float(self.var_geometry_buffer.get()) or 0.0
                    )
                    coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                elif f.suffix.lower() == '.kmz':
                    try:
                        with zipfile.ZipFile(f, 'r') as z:
                            kml_name = [n for n in z.namelist() if n.endswith('.kml')][0]
                            with z.open(kml_name) as kf:
                                content = kf.read()
                                root = ET.fromstring(content)
                                ns = {'k': 'http://www.opengis.net/kml/2.2'}
                                c_elem = root.find('.//k:coordinates', ns)
                                if c_elem is not None and c_elem.text:
                                    raw = c_elem.text.strip()
                                    tokens = raw.split()
                                    for tok in tokens:
                                        p = tok.split(',')
                                        if len(p) >= 2: coords.append((float(p[1]), float(p[0])))
                    except Exception: pass
                else:
                    lonlat = parse_polygon_coords_from_kml(f)
                    coords = [(float(lat), float(lon)) for lon, lat in lonlat]
                
                if coords:
                    # 폴리곤(면)으로 표시 (시인성 위해 밝은 노란색 테두리 사용)
                    self.map_view.set_polygon(coords, outline_color="#ffff00", fill_color=None, border_width=3, name=f.stem)
                    points_for_zoom.extend(coords)
            except Exception:
                continue

        if points_for_zoom:
            # 중심점 계산 및 이동
            lats = [p[0] for p in points_for_zoom]
            lons = [p[1] for p in points_for_zoom]
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
            self.map_view.set_position(center_lat, center_lon)
            self.map_view.set_zoom(15)

    def _debounce_map_preview(self):
        """지도 업데이트 지연 실행 (성능 최적화)"""
        if self._map_debounce_timer:
            self.after_cancel(self._map_debounce_timer)
        self._map_debounce_timer = self.after(800, self._update_map_preview)

    def _toggle_map_view(self):
        """지도/위성 전환"""
        # 현재 타일 서버 확인 (간단하게 토글)
        curr = self.map_view.tile_server
        if "lyrs=y" in curr: # 위성 하이브리드인 경우 일반 지도로
            self.map_view.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}")
        else: # 일반 지도인 경우 다시 위성으로
            self.map_view.set_tile_server("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}")

    def _refresh_naming_fields(self):
        fmt = (self.var_input_format.get() or '').strip().lower()
        input_dir = Path((self.var_input_dir.get() or '').strip())
        if not input_dir.exists():
            messagebox.showerror("오류", "입력 폴더가 존재하지 않습니다.")
            return

        # auto 포맷 결정
        if fmt == 'auto' or fmt == '':
            if any(input_dir.glob('*.gpkg')):
                fmt = 'gpkg'
            elif any(input_dir.glob('*.kml')):
                fmt = 'kml'
            else:
                messagebox.showwarning("경고", "입력 폴더에 GPKG/KML 파일이 없습니다.")
                return

        if fmt == 'gpkg':
            candidates = self._get_gpkg_fields(input_dir, None)
        elif fmt == 'kml':
            candidates = self._get_kml_fields(input_dir)
        else:
            messagebox.showwarning("경고", f"지원하지 않는 포맷: {fmt}")
            return

        if not candidates:
            messagebox.showwarning("경고", "필드를 찾지 못했습니다. 레이어/포맷/파일을 확인하세요.")
            return

        self.cb_naming_field['values'] = candidates
        default = 'ADDRE_1_2' if 'ADDRE_1_2' in candidates else candidates[0]
        self.var_naming_field.set(default)
        messagebox.showinfo("완료", f"필드 {len(candidates)}개 로드됨")

    def _get_gpkg_fields(self, input_dir: Path, layer: str | None) -> list[str]:
        try:
            import geopandas as gpd
        except Exception:
            messagebox.showerror("오류", "GeoPandas/pyogrio가 설치되어야 GPKG 필드를 조회할 수 있습니다.\n설치: pip install geopandas pyogrio shapely")
            return []

        files = list(input_dir.glob('*.gpkg'))
        if not files:
            return []

        intersection: set[str] | None = None
        union: set[str] = set()
        count = 0
        for p in files:
            if count >= 10:  # 과도한 스캔 방지
                break
            count += 1
            try:
                gdf = gpd.read_file(p, layer=layer) if layer else gpd.read_file(p)
                cols = [c for c in gdf.columns if c.lower() != 'geometry']
                s = set(cols)
                union.update(s)
                intersection = s if intersection is None else intersection.intersection(s)
            except Exception:
                # 문제가 있는 파일은 건너뜀
                pass

        candidates = sorted(intersection) if intersection and len(intersection) > 0 else sorted(union)
        return candidates

    def _get_kml_fields(self, input_dir: Path) -> list[str]:
        import xml.etree.ElementTree as ET
        files = list(input_dir.glob('*.kml'))
        if not files:
            return []
        candidates: set[str] = set()
        for p in files[:5]:  # 최대 5개 샘플링
            try:
                tree = ET.parse(p)
                root = tree.getroot()
                ns = {'kml': 'http://www.opengis.net/kml/2.2'}
                for d in root.findall('.//kml:ExtendedData/kml:Data', ns):
                    n = d.get('name')
                    if n:
                        candidates.add(n)
                for sd in root.findall('.//kml:ExtendedData/kml:SchemaData/kml:SimpleData', ns):
                    n = sd.get('name')
                    if n:
                        candidates.add(n)
                # Placemark의 <name> 태그도 후보로 추가
                if root.findall('.//kml:Placemark/kml:name', ns):
                    candidates.add('name')
            except Exception:
                pass
        return sorted(candidates)

    def _choose_dir(self, var):
        d = filedialog.askdirectory(initialdir=str(BASE))
        if d:
            var.set(d)

    def _choose_file(self, var, filetypes):
        f = filedialog.askopenfilename(initialdir=str(BASE.parent.parent), filetypes=filetypes)
        if f:
            var.set(f)

    def _on_load_preset(self):
        f = filedialog.askopenfilename(initialdir=str(BASE.parent.parent / "presets"), filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")])
        if not f:
            return
        import json
        try:
            with open(f, 'r', encoding='utf-8') as j:
                data = json.load(j)
                self.var_altitude.set(str(data.get("altitude", "")))
                self.var_margin.set(str(data.get("margin", "")))
                self.var_overlap_camera_h.set(str(data.get("overlap_camera_h", "")))
                self.var_overlap_camera_w.set(str(data.get("overlap_camera_w", "")))
                self.var_overlap_lidar_h.set(str(data.get("overlap_lidar_h", "")))
                self.var_overlap_lidar_w.set(str(data.get("overlap_lidar_w", "")))
                self.var_auto_flight_speed.set(str(data.get("auto_flight_speed", "")))
                self.var_global_transitional_speed.set(str(data.get("global_transitional_speed", "")))
                self.var_takeoff_security_height.set(str(data.get("takeoff_security_height", "")))
                self.var_drone_model.set(str(data.get("drone_model", "mavic3e")))
                self.var_gimbal_pitch.set(str(data.get("gimbal_pitch", "-90.0")))
                self.var_use_terrain_follow.set(bool(data.get("use_terrain_follow", False)))
                if "simplify_tolerance" in data:
                    self.var_simplify_tolerance.set(str(data["simplify_tolerance"]))
                if "geometry_buffer_m" in data:
                    self.var_geometry_buffer.set(str(data["geometry_buffer_m"]))
            messagebox.showinfo("완료", "프리셋을 불러왔습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"프리셋 로드 실패: {e}")

    def _on_save_preset(self):
        f = filedialog.asksaveasfilename(initialdir=str(BASE.parent.parent / "presets"), defaultextension=".json", filetypes=[("JSON 파일", "*.json")])
        if not f:
            return
        import json
        try:
            data = {
                "altitude": to_float(self.var_altitude.get()),
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
                "simplify_tolerance": to_float(self.var_simplify_tolerance.get()),
                "geometry_buffer_m": to_float(self.var_geometry_buffer.get())
            }
            with open(f, 'w', encoding='utf-8') as j:
                json.dump(data, j, indent=4)
            messagebox.showinfo("완료", "프리셋을 저장했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"프리셋 저장 실패: {e}")

    def _append_log(self, text: str):
        self.txt_log.insert(tk.END, text)
        self.txt_log.see(tk.END)

    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                if msg == "<<DONE>>":
                    self._on_done()
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)

    def _on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("알림", "이미 실행 중입니다.")
            return
        self.txt_log.delete("1.0", tk.END)
        self.var_status.set("실행 중...")
        self.btn_run.config(state=tk.DISABLED)
        self.worker = threading.Thread(target=self._run_job, daemon=True)
        self.worker.start()

    def _on_done(self):
        self.btn_run.config(state=tk.NORMAL)
        self.var_status.set("완료")

    def _run_job(self):
        # stdout 리다이렉트
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
            print(f"오류: {e}")
        finally:
            sys.stdout = backup_stdout
            self.queue.put("<<DONE>>")


if __name__ == "__main__":
    app = App()
    app.mainloop()