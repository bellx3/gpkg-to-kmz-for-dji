import threading
import queue
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 내부 로직 호출
from src.core.generator import batch_process_inputs
from src.core import enums

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
        self.geometry("980x750")
        
        # 스타일 설정
        style = ttk.Style()
        # 기본 테마가 있다면 활용 (windows는 보통 'vista' 또는 'xpnative')
        style.configure("Accent.TButton", font=("Malgun Gothic", 10, "bold"), foreground="#0078d4")
        
        self.queue = queue.Queue()
        self.worker = None
        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self):
        # 전체 컨테이너
        main_frm = ttk.Frame(self, padding=12)
        main_frm.pack(fill=tk.BOTH, expand=True)
        
        # 1열: 기본 설정 및 비행 제어 / 2열: 미션 파라미터 및 옵션
        top_pane = ttk.Frame(main_frm)
        top_pane.pack(fill=tk.X, side=tk.TOP)
        top_pane.columnconfigure(0, weight=1)
        top_pane.columnconfigure(1, weight=1)

        # ---------------------------------------------------------
        # [왼쪽 섹션]
        left_pane = ttk.Frame(top_pane)
        left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        
        # 1. 경로 및 데이터 설정
        group_path = ttk.LabelFrame(left_pane, text=" 기본 설정 (Paths & Data) ", padding=10)
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

        # 2. 기체 및 비행 제어
        group_flight = ttk.LabelFrame(left_pane, text=" 기체 및 비행 (Drone & Flight) ", padding=10)
        group_flight.pack(fill=tk.X)
        group_flight.columnconfigure(1, weight=1)

        l_row = 0
        self.var_drone_model = tk.StringVar(value="mavic3e")
        drone_list = enums.get_supported_drone_models()
        add_item(group_flight, "드론 모델", self.var_drone_model, values=drone_list)

        self.var_gimbal_pitch = tk.StringVar(value="-90.0")
        add_item(group_flight, "짐벌 피치 (°)", self.var_gimbal_pitch)

        self.var_auto_flight_speed = tk.StringVar(value="10")
        add_item(group_flight, "비행 속도 (m/s)", self.var_auto_flight_speed)

        self.var_global_transitional_speed = tk.StringVar()
        add_item(group_flight, "전환 속도 (m/s)", self.var_global_transitional_speed)

        self.var_takeoff_security_height = tk.StringVar(value="20")
        add_item(group_flight, "이륙 안전 고도 (m)", self.var_takeoff_security_height)


        # ---------------------------------------------------------
        # [오른쪽 섹션]
        right_pane = ttk.Frame(top_pane)
        right_pane.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # 3. 미션 파라미터
        group_param = ttk.LabelFrame(right_pane, text=" 상세 파라미터 (Mission Specs) ", padding=10)
        group_param.pack(fill=tk.X, pady=(0, 8))
        group_param.columnconfigure(1, weight=1)

        r_row = 0
        def add_r_item(label, var):
            nonlocal r_row
            ttk.Label(group_param, text=label).grid(row=r_row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(group_param, textvariable=var).grid(row=r_row, column=1, sticky=tk.EW, padx=4)
            r_row += 1

        self.var_altitude = tk.StringVar(value="150.0")
        add_r_item("임무 고도 (m)", self.var_altitude)
        self.var_margin = tk.StringVar(value="0")
        add_r_item("마진 (m)", self.var_margin)

        # 중첩도 표 형식 구성
        overlap_frm = ttk.Frame(group_param)
        overlap_frm.grid(row=r_row, column=0, columnspan=2, sticky=tk.EW, pady=4)
        r_row += 1
        overlap_frm.columnconfigure((1, 2), weight=1, uniform="overlap") # 크기 통일
        
        # 헤더
        ttk.Label(overlap_frm, text="", width=12).grid(row=0, column=0)
        ttk.Label(overlap_frm, text="진행방향(종) %", font=("Malgun Gothic", 8, "bold")).grid(row=0, column=1, pady=(0, 2))
        ttk.Label(overlap_frm, text="옆경로(횡) %", font=("Malgun Gothic", 8, "bold")).grid(row=0, column=2, pady=(0, 2))

        self.var_overlap_camera_h = tk.StringVar(value="80")
        self.var_overlap_camera_w = tk.StringVar(value="70")
        self.var_overlap_lidar_h = tk.StringVar(value="50")
        self.var_overlap_lidar_w = tk.StringVar(value="50")
        
        # 카메라 행
        ttk.Label(overlap_frm, text="카메라 중첩:").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(overlap_frm, textvariable=self.var_overlap_camera_h, width=8, justify="center").grid(row=1, column=1, padx=2, pady=2)
        ttk.Entry(overlap_frm, textvariable=self.var_overlap_camera_w, width=8, justify="center").grid(row=1, column=2, padx=2, pady=2)
        
        # 라이다 행
        ttk.Label(overlap_frm, text="라이다 중첩:").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(overlap_frm, textvariable=self.var_overlap_lidar_h, width=8, justify="center").grid(row=2, column=1, padx=2, pady=2)
        ttk.Entry(overlap_frm, textvariable=self.var_overlap_lidar_w, width=8, justify="center").grid(row=2, column=2, padx=2, pady=2)


        # 4. 기타 옵션 및 최적화
        group_opt = ttk.LabelFrame(right_pane, text=" 작업 옵션 (Options) ", padding=10)
        group_opt.pack(fill=tk.X)
        group_opt.columnconfigure(1, weight=1)

        o_row = 0
        self.var_simplify_tolerance = tk.StringVar(value="0.0")
        ttk.Label(group_opt, text="단순화 오차 (m)").grid(row=o_row, column=0, sticky=tk.W)
        ttk.Entry(group_opt, textvariable=self.var_simplify_tolerance).grid(row=o_row, column=1, sticky=tk.EW, padx=4)
        o_row += 1

        self.var_pack_kmz = tk.BooleanVar(value=True)
        self.var_set_times = tk.BooleanVar(value=True)
        self.var_set_takeoff_ref_point = tk.BooleanVar(value=True)
        
        ttk.Checkbutton(group_opt, text="KMZ 패키징 사용", variable=self.var_pack_kmz).grid(row=o_row, column=0, columnspan=2, sticky=tk.W)
        o_row += 1
        ttk.Checkbutton(group_opt, text="생성/업데이트 시간 갱신", variable=self.var_set_times).grid(row=o_row, column=0, columnspan=2, sticky=tk.W)
        o_row += 1
        ttk.Checkbutton(group_opt, text="이륙 기준점 자동 설정", variable=self.var_set_takeoff_ref_point).grid(row=o_row, column=0, columnspan=2, sticky=tk.W)
        
        # 템플릿 파일 선택 (경로가 깊으므로 별도 배치)
        group_tpl = ttk.LabelFrame(right_pane, text=" 템플릿 설정 ", padding=10)
        group_tpl.pack(fill=tk.X, pady=(8, 0))
        group_tpl.columnconfigure(1, weight=1)
        
        self.var_template = tk.StringVar(value=str(BASE.parent / "templates" / "template.kml"))
        self.var_waylines = tk.StringVar(value=str(BASE.parent / "templates" / "waylines.wpml"))
        
        ttk.Label(group_tpl, text="KML:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(group_tpl, textvariable=self.var_template).grid(row=0, column=1, sticky=tk.EW, padx=4)
        ttk.Button(group_tpl, text="..", width=3, command=lambda: self._choose_file(self.var_template, [("KML", "*.kml")])).grid(row=0, column=2)
        
        ttk.Label(group_tpl, text="WPML:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(group_tpl, textvariable=self.var_waylines).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(group_tpl, text="..", width=3, command=lambda: self._choose_file(self.var_waylines, [("WPML", "*.wpml")])).grid(row=1, column=2, pady=2)


        # ---------------------------------------------------------
        # [하단 섹션: 버튼 및 로그]
        ctrl_pane = ttk.Frame(main_frm, padding=(0, 10))
        ctrl_pane.pack(fill=tk.X, side=tk.TOP)
        
        self.btn_load_preset = ttk.Button(ctrl_pane, text="프리셋 불러오기", command=self._on_load_preset)
        self.btn_load_preset.pack(side=tk.LEFT, padx=2)
        self.btn_save_preset = ttk.Button(ctrl_pane, text="프리셋 저장하기", command=self._on_save_preset)
        self.btn_save_preset.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(ctrl_pane, text="  |  ").pack(side=tk.LEFT)
        
        self.btn_run = ttk.Button(ctrl_pane, text="  미션 생성 실행  ", command=self._on_run, style="Accent.TButton")
        self.btn_run.pack(side=tk.LEFT, padx=10)

        # 로그 영역
        self.txt_log = tk.Text(main_frm, height=12, wrap=tk.WORD, bg="#f8f9fa", font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True, pady=10)

        # 상태바
        self.var_status = tk.StringVar(value="준비됨")
        status_bar = ttk.Label(main_frm, textvariable=self.var_status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, ipady=2)

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
                if "simplify_tolerance" in data:
                    self.var_simplify_tolerance.set(str(data["simplify_tolerance"]))
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
                "simplify_tolerance": to_float(self.var_simplify_tolerance.get())
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