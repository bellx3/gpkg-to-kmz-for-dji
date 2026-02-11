import threading
import queue
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 내부 로직 호출
from kml_setting_v2 import batch_process_inputs
import dji_enums

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
        self.title("미션 저작도구 - 데스크톱 UI")
        self.geometry("900x700")
        self.queue = queue.Queue()
        self.worker = None
        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        # 그리드 설정
        frm.columnconfigure(1, weight=1)

        row = 0
        def add_label(text):
            nonlocal row
            lbl = ttk.Label(frm, text=text)
            lbl.grid(row=row, column=0, sticky=tk.W, pady=4)

        def add_entry(var, default="", width=60):
            nonlocal row
            var.set(default)
            ent = ttk.Entry(frm, textvariable=var, width=width)
            ent.grid(row=row, column=1, sticky=tk.EW, pady=4)
            return ent

        def add_button(text, cmd):
            nonlocal row
            btn = ttk.Button(frm, text=text, command=cmd)
            btn.grid(row=row, column=2, padx=6)
            return btn

        def add_combo(var, values, default):
            nonlocal row
            cb = ttk.Combobox(frm, textvariable=var, values=values, state="readonly")
            var.set(default)
            cb.grid(row=row, column=1, sticky=tk.W, pady=4)
            return cb

        def add_check(var, text, default=False):
            nonlocal row
            var.set(default)
            chk = ttk.Checkbutton(frm, text=text, variable=var)
            chk.grid(row=row, column=1, sticky=tk.W, pady=4)
            return chk

        # 입력 포맷
        self.var_input_format = tk.StringVar()
        add_label("입력 포맷")
        add_combo(self.var_input_format, ["gpkg", "kml", "auto"], "gpkg")
        row += 1

        # 입력 폴더
        self.var_input_dir = tk.StringVar()
        add_label("입력 폴더 경로")
        ent_in = add_entry(self.var_input_dir, str(BASE / "input"))
        add_button("찾기", lambda: self._choose_dir(self.var_input_dir))
        row += 1

        # 템플릿 KML
        self.var_template = tk.StringVar()
        add_label("템플릿 KML 경로")
        ent_tpl = add_entry(self.var_template, str(BASE / "template.kml"))
        add_button("찾기", lambda: self._choose_file(self.var_template, filetypes=[("KML 파일", "*.kml"), ("모든 파일", "*.*")]))
        row += 1

        # waylines
        self.var_waylines = tk.StringVar()
        add_label("waylines.wpml 경로")
        ent_wp = add_entry(self.var_waylines, str(BASE / "waylines.wpml"))
        add_button("찾기", lambda: self._choose_file(self.var_waylines, filetypes=[("WPML 파일", "*.wpml"), ("모든 파일", "*.*")]))
        row += 1

        # 출력 폴더
        self.var_out_dir = tk.StringVar()
        add_label("출력 폴더 경로")
        ent_out = add_entry(self.var_out_dir, str(BASE / "output"))
        add_button("찾기", lambda: self._choose_dir(self.var_out_dir))
        row += 1

        # 레이어(GPKG)
        self.var_layer = tk.StringVar()
        add_label("레이어 이름(GPKG)")
        add_entry(self.var_layer, "")
        row += 1

        # 파일명 필드
        self.var_naming_field = tk.StringVar()
        add_label("파일명 필드")
        self.cb_naming_field = ttk.Combobox(frm, textvariable=self.var_naming_field, values=[], width=60, state="readonly")
        self.cb_naming_field.grid(row=row, column=1, sticky=tk.EW, pady=4)
        add_button("필드 새로고침", self._refresh_naming_fields)
        row += 1

        # KMZ 패키징
        self.var_pack_kmz = tk.BooleanVar()
        add_label("KMZ로 패키징")
        add_check(self.var_pack_kmz, "사용", True)
        row += 1

        # set_times
        self.var_set_times = tk.BooleanVar()
        add_label("생성/업데이트 시간 갱신")
        add_check(self.var_set_times, "사용", True)
        row += 1

        # set_takeoff_ref_point
        self.var_set_takeoff_ref_point = tk.BooleanVar()
        add_label("이륙 기준점 자동 설정")
        add_check(self.var_set_takeoff_ref_point, "사용", False)
        row += 1

        # 프리셋 버튼
        self.btn_load_preset = ttk.Button(frm, text="프리셋 불러오기", command=self._on_load_preset)
        self.btn_load_preset.grid(row=row, column=1, sticky=tk.W, pady=4)
        self.btn_save_preset = ttk.Button(frm, text="프리셋 저장하기", command=self._on_save_preset)
        self.btn_save_preset.grid(row=row, column=2, sticky=tk.W, padx=6)
        row += 1

        # 구분선
        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=8)
        row += 1

        # Overrides
        self.var_altitude = tk.StringVar()
        add_label("고도(altitude)")
        add_entry(self.var_altitude, "")
        row += 1

        self.var_shoot_height = tk.StringVar()
        add_label("촬영고도(shoot_height)")
        add_entry(self.var_shoot_height, "")
        row += 1

        self.var_margin = tk.StringVar()
        add_label("마진(margin)")
        add_entry(self.var_margin, "")
        row += 1

        self.var_overlap_camera_h = tk.StringVar()
        add_label("카메라 중첩 H(%)")
        add_entry(self.var_overlap_camera_h, "")
        row += 1

        self.var_overlap_camera_w = tk.StringVar()
        add_label("카메라 중첩 W(%)")
        add_entry(self.var_overlap_camera_w, "")
        row += 1

        self.var_overlap_lidar_h = tk.StringVar()
        add_label("라이다 중첩 H(%)")
        add_entry(self.var_overlap_lidar_h, "")
        row += 1

        self.var_overlap_lidar_w = tk.StringVar()
        add_label("라이다 중첩 W(%)")
        add_entry(self.var_overlap_lidar_w, "")
        row += 1

        self.var_auto_flight_speed = tk.StringVar()
        add_label("자동 비행 속도")
        add_entry(self.var_auto_flight_speed, "")
        row += 1

        self.var_global_transitional_speed = tk.StringVar()
        add_label("전환 속도")
        add_entry(self.var_global_transitional_speed, "")
        row += 1

        self.var_takeoff_security_height = tk.StringVar()
        add_label("안전한 이륙 고도")
        add_entry(self.var_takeoff_security_height, "")
        row += 1

        self.var_drone_model = tk.StringVar()
        add_label("드론 모델")
        # dji_enums에서 모델 목록 가져오기 (임의로 딕셔너리 키 활용) - 실제 dji_enums 구조 확인 필요
        # 현재 dji_enums.py는 딕셔너리가 내부 변수이므로 직접 노출 안 될 수 있음. 
        # 일단 주요 모델만 하드코딩하거나 dji_enums를 수정해서 목록을 가져오도록 함.
        drone_list = ["mavic3e", "mavic3t", "m30", "m30t", "m300", "m350", "p4r"]
        add_combo(self.var_drone_model, drone_list, "mavic3e")
        row += 1

        self.var_gimbal_pitch = tk.StringVar()
        add_label("짐벌 피치 (각도)")
        add_entry(self.var_gimbal_pitch, "-90.0")
        row += 1

        self.var_simplify_tolerance = tk.StringVar()
        add_label("지오메트리 단순화(m)")
        add_entry(self.var_simplify_tolerance, "0.0")
        row += 1

        # 실행 버튼
        self.btn_run = ttk.Button(frm, text="실행", command=self._on_run)
        self.btn_run.grid(row=row, column=0, sticky=tk.W, pady=10)

        self.btn_exit = ttk.Button(frm, text="종료", command=self.destroy)
        self.btn_exit.grid(row=row, column=1, sticky=tk.W, pady=10)
        row += 1

        # 로그 창
        self.txt_log = tk.Text(frm, height=18, wrap=tk.WORD)
        self.txt_log.grid(row=row, column=0, columnspan=3, sticky=tk.NSEW, pady=8)
        frm.rowconfigure(row, weight=1)

        # 상태바
        row += 1
        self.var_status = tk.StringVar(value="대기 중")
        ttk.Label(frm, textvariable=self.var_status).grid(row=row, column=0, columnspan=3, sticky=tk.W)

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
            candidates = self._get_gpkg_fields(input_dir, (self.var_layer.get() or '').strip() or None)
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
        f = filedialog.askopenfilename(initialdir=str(BASE), filetypes=filetypes)
        if f:
            var.set(f)

    def _on_load_preset(self):
        f = filedialog.askopenfilename(initialdir=str(BASE / "presets"), filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")])
        if not f:
            return
        import json
        try:
            with open(f, 'r', encoding='utf-8') as j:
                data = json.load(j)
                self.var_altitude.set(str(data.get("altitude", "")))
                self.var_shoot_height.set(str(data.get("shoot_height", "")))
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
        f = filedialog.asksaveasfilename(initialdir=str(BASE / "presets"), defaultextension=".json", filetypes=[("JSON 파일", "*.json")])
        if not f:
            return
        import json
        try:
            data = {
                "altitude": to_float(self.var_altitude.get()),
                "shoot_height": to_float(self.var_shoot_height.get()),
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
            overrides = {
                "altitude": to_float(self.var_altitude.get()),
                "shoot_height": to_float(self.var_shoot_height.get()),
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
                layer=(self.var_layer.get() or None),
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