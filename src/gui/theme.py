"""E8IGHT 디자인시스템 토큰 — CustomTkinter 이식본.

CSS 커스텀 프로퍼티(`tokens/colors.css`·`radius.css`·`typography.css`)를 파이썬 상수로 옮긴다.
Tk 위젯은 알파를 모르므로, 시스템의 반투명 헤어라인 보더는 각 표면 색 위에 미리 합성해 hex 로 둔다.

규칙(디자인시스템 non-negotiables):
  다크 네이비 기본 · 시안 강조 하나 · 그림자 대신 헤어라인 보더 · 측정값은 모노스페이스 ·
  반경 3/5/8/12 · 컨트롤 높이 26/34/44 · 이모지 없음.
"""

import customtkinter as ctk

# ---- base ramps (tokens/colors.css) ----
NAVY_1000 = "#03060D"; NAVY_950 = "#060A14"; NAVY_900 = "#0A0F1C"; NAVY_850 = "#0E1424"
NAVY_800 = "#131B2E";  NAVY_750 = "#18213A"; NAVY_700 = "#1E2946"; NAVY_600 = "#28345C"
SLATE_100 = "#E9EEF8"; SLATE_200 = "#C6D0E3"; SLATE_300 = "#9AA6C1"
SLATE_400 = "#6E7C9A"; SLATE_500 = "#4C5872"

CYAN_200 = "#B4F4FF"; CYAN_300 = "#75E7FB"; CYAN_400 = "#33D6F2"; CYAN_500 = "#12B4D6"
CYAN_600 = "#0B8AA8"; CYAN_700 = "#07647B"
GREEN_400 = "#3ADFA0"; AMBER_400 = "#FFC24D"; RED_400 = "#FF7183"
VIZ = ["#33D6F2", "#5A8CFF", "#3ADFA0", "#FFC24D", "#FF7183", "#A98BFF", "#75E7FB", "#9AA6C1"]

# ---- semantic surfaces ----
BG_APP = NAVY_950
BG_CANVAS = NAVY_1000
SURFACE_1 = NAVY_900        # 사이드바·로그 패널
SURFACE_CARD = NAVY_850     # 카드
SURFACE_RAISED = NAVY_800   # 실행 존·지도 위 오버레이
SURFACE_HOVER = NAVY_750

# ---- 헤어라인 보더: rgba(154,166,193,α) 를 각 표면 위에 합성한 값 ----
BORDER_SUBTLE = "#22283A"   # α .14 over navy-850 — 구조
BORDER_DEFAULT = "#30374A"  # α .24 — 컨트롤
BORDER_STRONG = "#464E63"   # α .40 — hover
BORDER_ACCENT = CYAN_500

# ---- text ----
TX_PRIMARY = SLATE_100
TX_BODY = SLATE_200
TX_MUTED = SLATE_300
TX_FAINT = SLATE_400
TX_ACCENT = CYAN_300

# ---- accent — 강조는 시안 하나뿐이다 ----
ACCENT = CYAN_400
ACCENT_HOVER = CYAN_300
ACCENT_PRESS = CYAN_500
ON_ACCENT = "#03181F"
ACCENT_QUIET = "#0D2C3C"    # rgba(51,214,242,.12) over navy-900

# ---- status: green 정상 · amber 주의 · red 임계 초과 · slate 유휴 ----
STATUS = {
    "safe":    (GREEN_400, "#122A2C"),
    "warning": (AMBER_400, "#2A2519"),
    "danger":  (RED_400,   "#2A1620"),
    "idle":    (SLATE_400, "#161C2B"),
}

# ---- radius (tokens/radius.css) — 컨트롤 5 · 카드 8 · 모달 12 · 배지 3 ----
R_BADGE = 3; R_CONTROL = 5; R_CARD = 8; R_PANEL = 8; R_MODAL = 12

# ---- control heights — 세 가지뿐이다 ----
H_SM = 26; H_MD = 34; H_LG = 44

# ---- type ----
FONT_UI = "Pretendard"        # 없으면 Tk 가 시스템 기본으로 폴백한다
FONT_UI_FALLBACK = "Malgun Gothic"
FONT_MONO = "JetBrains Mono"
FONT_MONO_FALLBACK = "Consolas"


def _has(family: str) -> bool:
    try:
        import tkinter.font as tkfont
        return family in tkfont.families()
    except Exception:
        return False


_ui_family = None
_mono_family = None


def ui_family() -> str:
    global _ui_family
    if _ui_family is None:
        _ui_family = FONT_UI if _has(FONT_UI) else FONT_UI_FALLBACK
    return _ui_family


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        _mono_family = FONT_MONO if _has(FONT_MONO) else FONT_MONO_FALLBACK
    return _mono_family


def font(size=12, weight="normal"):
    """UI 폰트. 한국어는 400 미만에서 가독성을 잃고 700 위에서 뭉친다."""
    return ctk.CTkFont(family=ui_family(), size=size, weight=weight)


def mono(size=11, weight="normal"):
    """측정값·좌표·ID·타임스탬프 전용. 수치는 언제나 모노스페이스다."""
    return ctk.CTkFont(family=mono_family(), size=size, weight=weight)


def micro_text(s: str) -> str:
    """라틴 마이크로 라벨은 대문자 + 자간. 한국어는 대문자화하지 않는다."""
    return s.upper()


# ------------------------------------------------------------------------------
# 위젯 팩토리 — 스타일 결정을 한곳에 모은다
# ------------------------------------------------------------------------------

def card(parent, **kw):
    """헤어라인 보더 · 반경 8 · surface-card. 그림자는 쓰지 않는다."""
    opts = dict(corner_radius=R_CARD, fg_color=SURFACE_CARD,
                border_width=1, border_color=BORDER_SUBTLE)
    opts.update(kw)
    return ctk.CTkFrame(parent, **opts)


def entry(parent, **kw):
    """입력은 우물(inset)이다 — 카드보다 어두운 바닥 + 컨트롤 보더."""
    opts = dict(corner_radius=R_CONTROL, height=H_MD - 6, font=font(12),
                fg_color=NAVY_1000, border_width=1, border_color=BORDER_DEFAULT,
                text_color=TX_PRIMARY)
    opts.update(kw)
    return ctk.CTkEntry(parent, **opts)


def primary(parent, **kw):
    """주 동작. 화면 영역당 하나만 존재한다."""
    opts = dict(corner_radius=R_CONTROL, height=H_LG, font=font(14, "bold"),
                fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT)
    opts.update(kw)
    return ctk.CTkButton(parent, **opts)


def quiet(parent, **kw):
    """보조 동작 — 표면 + 보더. hover 는 밝아진다."""
    opts = dict(corner_radius=R_CONTROL, height=H_MD - 4, font=font(12),
                fg_color=SURFACE_RAISED, hover_color=SURFACE_HOVER,
                border_width=1, border_color=BORDER_DEFAULT, text_color=TX_BODY)
    opts.update(kw)
    return ctk.CTkButton(parent, **opts)


def ghost(parent, **kw):
    """배경 없는 동작. hover 에서만 12% 시안 틴트가 깔린다."""
    opts = dict(corner_radius=R_CONTROL, height=H_SM, font=font(12),
                fg_color="transparent", hover_color=ACCENT_QUIET,
                border_width=1, border_color=BORDER_DEFAULT, text_color=TX_MUTED)
    opts.update(kw)
    return ctk.CTkButton(parent, **opts)


def option(parent, **kw):
    opts = dict(corner_radius=R_CONTROL, height=H_MD - 6, font=font(12),
                fg_color=SURFACE_RAISED, button_color=NAVY_700,
                button_hover_color=NAVY_600, text_color=TX_PRIMARY,
                dropdown_fg_color=SURFACE_RAISED, dropdown_text_color=TX_BODY,
                dropdown_hover_color=NAVY_700, dropdown_font=font(12))
    opts.update(kw)
    return ctk.CTkOptionMenu(parent, **opts)


def check(parent, **kw):
    opts = dict(font=font(12), corner_radius=R_BADGE, checkbox_width=18, checkbox_height=18,
                border_width=1, border_color=BORDER_DEFAULT, hover_color=ACCENT_HOVER,
                fg_color=ACCENT, checkmark_color=ON_ACCENT, text_color=TX_BODY)
    opts.update(kw)
    return ctk.CTkCheckBox(parent, **opts)


def micro(parent, text, **kw):
    """라틴 마이크로 라벨 — 11px · 대문자 · 흐린 slate."""
    opts = dict(text=micro_text(text), font=font(11, "bold"), text_color=TX_FAINT)
    opts.update(kw)
    return ctk.CTkLabel(parent, **opts)


def hairline(parent, orient="h"):
    """구조는 여백이 아니라 헤어라인으로 나눈다."""
    if orient == "h":
        return ctk.CTkFrame(parent, height=1, width=1, corner_radius=0, fg_color=BORDER_SUBTLE)
    return ctk.CTkFrame(parent, width=1, height=1, corner_radius=0, fg_color=BORDER_SUBTLE)
