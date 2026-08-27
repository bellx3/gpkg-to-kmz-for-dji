"""
SkyMission Builder - Reporting Module
배치 작업 결과를 시각적인 HTML 리포트로 변환합니다.

스타일은 E8IGHT 디자인시스템을 따른다 — 다크 네이비 기본 · 시안 강조 하나 ·
그림자 대신 헤어라인 보더 · 모든 측정값은 모노스페이스 tabular · 반경 3/5/8/12 ·
이모지 없음. 색은 :root 커스텀 프로퍼티로만 참조하고 본문에 hex 를 쓰지 않는다.

리포트는 단일 HTML 파일이어야 한다(브라우저로 열고 메일로 보낸다). 그래서 CSS 는
인라인이고, 폰트는 CDN 이 죽어도 읽히도록 시스템 폰트 폴백을 반드시 동반한다.

템플릿은 str.format 을 쓰므로 CSS 중괄호는 전부 `{{ }}` 로 이스케이프되어 있다.
"""

import datetime
import html
from pathlib import Path
from typing import List, Dict

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SkyMission Builder — 작업 결과 리포트</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
:root {{
  /* base ramps */
  --navy-1000:#03060D; --navy-950:#060A14; --navy-900:#0A0F1C; --navy-850:#0E1424;
  --navy-800:#131B2E;  --navy-750:#18213A; --navy-700:#1E2946;
  --slate-100:#E9EEF8; --slate-200:#C6D0E3; --slate-300:#9AA6C1; --slate-400:#6E7C9A;
  --cyan-300:#75E7FB;  --cyan-400:#33D6F2; --cyan-500:#12B4D6;
  --green-400:#3ADFA0; --amber-400:#FFC24D; --red-400:#FF7183;

  /* semantic */
  --bg-app:var(--navy-950); --surface-card:var(--navy-850); --surface-raised:var(--navy-800);
  --border-subtle:rgba(154,166,193,.14); --border-default:rgba(154,166,193,.24);
  --text-primary:var(--slate-100); --text-body:var(--slate-200);
  --text-muted:var(--slate-300);   --text-faint:var(--slate-400);
  --accent:var(--cyan-400); --accent-quiet:rgba(51,214,242,.12);

  /* status — 의미가 고정돼 있다. 강조 용도로 전용하지 않는다. */
  --status-ok:var(--green-400);   --status-ok-bg:rgba(58,223,160,.13);
  --status-warn:var(--amber-400); --status-warn-bg:rgba(255,194,77,.13);
  --status-crit:var(--red-400);   --status-crit-bg:rgba(240,62,86,.14);
  --status-idle:var(--slate-400); --status-idle-bg:rgba(110,124,154,.15);

  --font-ui:"Pretendard","Noto Sans KR","Malgun Gothic",-apple-system,sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,Consolas,"D2Coding",monospace;
  --r-badge:3px; --r-control:5px; --r-card:8px;
}}

* {{ box-sizing:border-box; }}
body {{
  margin:0; padding:40px 24px 64px;
  background:var(--bg-app); color:var(--text-body);
  font-family:var(--font-ui); font-size:15px; line-height:1.6; letter-spacing:-.006em;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1200px; margin:0 auto; }}

/* 라틴 마이크로 라벨은 대문자 + 자간. 한국어는 대문자화하지 않는다. */
.micro {{ font-size:11px; font-weight:600; letter-spacing:.09em; text-transform:uppercase;
          color:var(--text-faint); }}
.mono {{ font-family:var(--font-mono); font-variant-numeric:tabular-nums; }}

/* ---- 헤더: 구조는 그림자가 아니라 헤어라인이 만든다 ---- */
header {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
          padding-bottom:16px; border-bottom:1px solid var(--border-subtle); margin-bottom:28px; }}
header h1 {{ margin:0; font-size:22px; font-weight:700; letter-spacing:-.016em;
             color:var(--text-primary); }}
header .sub {{ font-size:13px; color:var(--text-faint); }}
header .stamp {{ margin-left:auto; font-size:13px; color:var(--text-muted); }}

/* ---- KPI 타일: 좌측 2px 상태 레일은 상태를 인코딩할 때만 허용된다 ---- */
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
          gap:12px; margin-bottom:24px; }}
.tile {{ position:relative; background:var(--surface-card); border:1px solid var(--border-subtle);
         border-radius:var(--r-card); padding:14px 16px 16px 18px; overflow:hidden; }}
.tile::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:2px;
                 background:var(--rail,var(--slate-400)); }}
.tile .label {{ display:block; margin-bottom:6px; }}
.tile .value {{ font-family:var(--font-mono); font-variant-numeric:tabular-nums;
                font-size:32px; line-height:1.1; font-weight:500; color:var(--text-primary); }}
.tile .value.sm {{ font-size:17px; line-height:1.6; padding-top:9px; color:var(--text-body); }}
.tile.ok    {{ --rail:var(--status-ok); }}
.tile.crit  {{ --rail:var(--status-crit); }}
.tile.info  {{ --rail:var(--accent); }}
.tile.idle  {{ --rail:var(--status-idle); }}
.tile.ok .value {{ color:var(--status-ok); }}
.tile.crit .value {{ color:var(--status-crit); }}

/* ---- 고지: 주의는 앰버, 좌측 레일 + 틴트 배경 ---- */
.alert {{ background:var(--status-warn-bg); border:1px solid var(--border-subtle);
          border-left:2px solid var(--status-warn); border-radius:var(--r-control);
          padding:14px 18px; margin-bottom:28px; font-size:14px; color:var(--text-body); }}
.alert .head {{ display:block; margin-bottom:6px; font-weight:600; color:var(--status-warn); }}
.alert code, td code {{ font-family:var(--font-mono); font-size:.92em;
                        background:var(--navy-1000); border:1px solid var(--border-subtle);
                        border-radius:var(--r-badge); padding:1px 5px; color:var(--cyan-300); }}

/* ---- 테이블: 36px 행 · 스티키 대문자 헤더 · 수치 열은 우측 정렬 모노 ---- */
.panel {{ background:var(--surface-card); border:1px solid var(--border-subtle);
          border-radius:var(--r-card); overflow:hidden; }}
.panel-head {{ display:flex; align-items:center; height:38px; padding:0 16px;
               border-bottom:1px solid var(--border-subtle); }}
.scroll {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ position:sticky; top:0; background:var(--surface-raised); text-align:left;
      padding:0 16px; height:34px; white-space:nowrap;
      font-size:11px; font-weight:600; letter-spacing:.09em; text-transform:uppercase;
      color:var(--text-faint); border-bottom:1px solid var(--border-subtle); }}
td {{ padding:0 16px; height:36px; font-size:14px; color:var(--text-body);
      border-bottom:1px solid var(--border-subtle); }}
tr:last-child td {{ border-bottom:none; }}
tbody tr:hover td {{ background:var(--accent-quiet); }}
td.num {{ text-align:right; font-family:var(--font-mono); font-variant-numeric:tabular-nums;
          color:var(--text-primary); white-space:nowrap; }}
td.name {{ font-family:var(--font-mono); color:var(--text-primary); white-space:nowrap; }}
td.msg {{ font-size:13px; color:var(--text-muted); line-height:1.5;
          padding-top:8px; padding-bottom:8px; height:auto; min-width:260px; }}

/* 상태 배지 — 반경 3, 틴트 배경, 상태색 텍스트 */
.badge {{ display:inline-block; padding:2px 8px; border-radius:var(--r-badge);
          font-size:11px; font-weight:600; letter-spacing:.09em; }}
.badge.safe    {{ color:var(--status-ok);   background:var(--status-ok-bg); }}
.badge.warning {{ color:var(--status-warn); background:var(--status-warn-bg); }}
.badge.danger  {{ color:var(--status-crit); background:var(--status-crit-bg); }}
.badge.na      {{ color:var(--status-idle); background:var(--status-idle-bg); }}

footer {{ margin-top:28px; padding-top:16px; border-top:1px solid var(--border-subtle);
          font-size:12px; color:var(--text-faint); display:flex; gap:10px; flex-wrap:wrap; }}

@media (prefers-reduced-motion:no-preference) {{
  tbody tr td {{ transition:background 120ms cubic-bezier(.2,0,.25,1); }}
}}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>작업 결과 리포트</h1>
    <span class="sub">SkyMission Builder · GPKG → DJI KMZ · WPML 1.0.6</span>
    <span class="stamp mono">{timestamp}</span>
  </header>

  <div class="tiles">
    <div class="tile info">
      <span class="label micro">total missions</span>
      <span class="value">{total}</span>
    </div>
    <div class="tile ok">
      <span class="label micro">succeeded</span>
      <span class="value">{success}</span>
    </div>
    <div class="tile {failure_tone}">
      <span class="label micro">failed</span>
      <span class="value">{failure}</span>
    </div>
    <div class="tile idle">
      <span class="label micro">generated at</span>
      <span class="value sm mono">{timestamp}</span>
    </div>
  </div>

  <div class="alert">
    <span class="head">비행 전 확인</span>
    이 KMZ 의 <code>waylines.wpml</code> 은 원 템플릿 현장의 실행 웨이포인트를 그대로 담고
    있습니다. 임무 폴리곤은 <code>template.kml</code> 에만 반영됩니다.
    <b>DJI Pilot 2 에서 불러와 경로를 재생성한 뒤 비행하십시오</b> — 웨이라인을 그대로
    실행하면 원 현장을 비행합니다.
    검증: <code>python src/core/inspector.py [KMZ경로]</code>
  </div>

  <div class="panel">
    <div class="panel-head"><span class="micro">missions</span></div>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>파일명</th>
            <th>상태</th>
            <th style="text-align:right">GSD (cm)</th>
            <th style="text-align:right">Blur (cm)</th>
            <th style="text-align:right">속도 (m/s)</th>
            <th style="text-align:right">고도 (m)</th>
            <th>메시지</th>
          </tr>
        </thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </div>
  </div>

  <footer>
    <span>SkyMission Builder v0.1.0</span>
    <span>·</span>
    <span>DJI WPML 1.0.6</span>
  </footer>

</div>
</body>
</html>
"""

# 상태값 → 배지 클래스. 알 수 없는 값은 유휴로 떨어뜨린다(없는 상태를 지어내지 않는다).
_BADGE = {"safe": "safe", "warning": "warning", "danger": "danger"}


def _esc(value) -> str:
    """파일명·메시지는 외부 데이터다 — 그대로 넣으면 리포트가 깨지거나 주입된다."""
    return html.escape("-" if value is None else str(value), quote=True)


def generate_report(results: List[Dict], output_dir: Path) -> Path:
    """
    배치 결과를 바탕으로 HTML 리포트를 생성합니다.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    total = len(results)
    success = sum(1 for r in results if r['success'])
    failure = total - success

    rows = []
    for r in results:
        status = str(r.get('status', '') or '').lower()
        badge = _BADGE.get(status, "na")
        metrics = r.get('metrics', {})
        messages = [_esc(m) for m in r.get('messages', []) if m]

        rows.append(
            "          <tr>\n"
            f"            <td class=\"name\">{_esc(r['name'])}</td>\n"
            f"            <td><span class=\"badge {badge}\">{_esc(r.get('status', 'N/A')).upper()}</span></td>\n"
            f"            <td class=\"num\">{_esc(metrics.get('gsd'))}</td>\n"
            f"            <td class=\"num\">{_esc(metrics.get('blur'))}</td>\n"
            f"            <td class=\"num\">{_esc(r.get('speed'))}</td>\n"
            f"            <td class=\"num\">{_esc(r.get('altitude'))}</td>\n"
            f"            <td class=\"msg\">{'<br>'.join(messages) or '—'}</td>\n"
            "          </tr>"
        )

    html_content = HTML_TEMPLATE.format(
        total=total,
        success=success,
        failure=failure,
        failure_tone="crit" if failure else "idle",   # 0 건이면 적색을 켜지 않는다
        timestamp=timestamp,
        table_rows="\n".join(rows)
    )

    report_path = output_dir / f"report_{file_timestamp}.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return report_path
