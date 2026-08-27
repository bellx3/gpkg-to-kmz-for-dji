"""GUI 재생성(언어 토글) 스모크 — 디스플레이가 있으면 실제 위젯으로 왕복한다.

CLAUDE.md 의 경고가 이 테스트의 존재 이유다: 언어 토글은 UI 를 통째로 다시
만들므로, 위젯 밖 상태(파일명 후보·로그·실행 버튼 상태)가 재생성에서 살아남는지를
사람 손 없이 확인한다. 지도 위젯은 타일 다운로드 스레드가 테스트를 불안하게 만들어
None 으로 바꿔 끼운다 — 지도 없는 환경(선택 설치 미적용)의 경로 검증을 겸한다.
"""
import tkinter as tk

import pytest

import src.gui.app as app_mod


@pytest.fixture
def gui(monkeypatch):
    monkeypatch.setattr(app_mod, "tkintermapview", None)
    try:
        gui = app_mod.App()
    except tk.TclError as e:
        pytest.skip(f"디스플레이 없음: {e}")
    gui.withdraw()
    yield gui
    try:
        gui.destroy()
    except Exception:
        pass


def test_language_toggle_survives_round_trip(gui):
    gui.txt_log.insert("end", "보존되어야 하는 로그 한 줄\n")
    gui._naming_values = ["(auto)", "ADDRE_1_2"]
    gui.var_naming_field.set("ADDRE_1_2")

    gui._toggle_language()   # ko -> en
    assert gui.curr_lang == "en"
    # 로그가 재생성을 건너 살아남는다(B3)
    assert "보존되어야 하는" in gui.txt_log.get("1.0", "end")
    # 파일명 선택과 후보가 유지된다
    assert gui.var_naming_field.get() == "ADDRE_1_2"
    assert "ADDRE_1_2" in gui.cb_naming.cget("values")

    gui._toggle_language()   # en -> ko
    assert gui.curr_lang == "ko"
    assert "보존되어야 하는" in gui.txt_log.get("1.0", "end")


def test_status_variable_is_actually_displayed(gui):
    """var_status 가 어떤 위젯에도 묶여 있지 않던 결함(B2)의 회귀망."""
    gui.var_status.set("__status_probe__")

    def any_label_shows(widget):
        for w in widget.winfo_children():
            try:
                if w.cget("textvariable") and str(w.cget("textvariable")) == str(gui.var_status):
                    return True
            except Exception:
                pass
            if any_label_shows(w):
                return True
        return False

    assert any_label_shows(gui)


def test_drone_model_gates_terrain_follow(gui):
    gui.var_drone_model.set("mavic3e")
    assert gui.chk_tf.cget("state") == "normal"
    gui.var_use_terrain_follow.set(True)
    gui.var_drone_model.set("mini3")   # 미지원 기종으로 바꾸면
    assert gui.chk_tf.cget("state") == "disabled"
    assert gui.var_use_terrain_follow.get() is False   # 체크도 풀려야 한다


def test_collect_values_covers_run_arguments(gui):
    v = gui._collect_values()
    for key in ("input_dir", "out_dir", "input_format", "naming_field",
                "set_times", "set_takeoff_ref_point", "pack_kmz", "simplify_tolerance"):
        assert key in v
    ov = app_mod.build_overrides(v)
    assert ov["altitude"] == 150.0


def test_metrics_label_discloses_spec_fallback(gui):
    gui.var_drone_model.set("m300")   # 사양 미등록 기종
    assert "≈" in gui.lbl_metrics.cget("text")
    gui.var_drone_model.set("mavic3e")
    assert "≈" not in gui.lbl_metrics.cget("text")
