
import re, os, io, json, math, html
from datetime import timedelta
from xml.etree import ElementTree as ET

TIME_RE = re.compile(r"^(\d+):(\d+):(\d+),(\d+)$")

class Subtitle:
    def __init__(self, index, start_ms, end_ms, lines):
        self.index = index
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.lines = lines  # list[str]

    @property
    def text(self):
        return "
".join(self.lines)

    @property
    def duration_ms(self):
        return max(0, self.end_ms - self.start_ms)


def parse_timestamp_srt(ts: str) -> int:
    m = TIME_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: {ts}")
    h, m_, s, ms = map(int, m.groups())
    return ((h*60 + m_) * 60 + s) * 1000 + ms


def parse_srt(text: str):
    subs = []
    blocks = re.split(r"?
?
", text.strip(), flags=re.M)
    idx = 0
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip() != ""]
        if len(lines) >= 2:
            # First line may be index
            i0 = 0
            if re.match(r"^\d+$", lines[0].strip()):
                i0 = 1
            timing = lines[i0]
            if '-->' not in timing:
                continue
            t1, t2 = [t.strip() for t in timing.split('-->')]
            start = parse_timestamp_srt(t1)
            end = parse_timestamp_srt(t2.split()[0])
            content = lines[i0+1:]
            idx += 1
            subs.append(Subtitle(idx, start, end, content))
    return subs


def parse_vtt(text: str):
    subs = []
    lines = text.splitlines()
    lines = [l for l in lines if not l.strip().startswith('WEBVTT')]
    buf = []
    for line in lines:
        buf.append(line)
    blocks = re.split(r"?
?
", "
".join(buf).strip())
    idx = 0
    for b in blocks:
        lns = [l for l in b.splitlines() if l.strip()]
        if not lns:
            continue
        # VTT may have an optional cue id line
        i0 = 0
        timing_line = None
        for k in range(min(2, len(lns))):
            if '-->' in lns[k]:
                timing_line = lns[k]
                i0 = k
                break
        if not timing_line:
            continue
        t1, t2 = [t.strip() for t in timing_line.split('-->')]
        def parse_vtt_ts(ts):
            ts = ts.split()[0]
            hh, mm, ss_ms = ts.split(':')
            if '.' in ss_ms:
                ss, ms = ss_ms.split('.')
                ms = int((ms + '000')[:3])
            else:
                ss, ms = ss_ms, '000'
            return ((int(hh)*60 + int(mm))*60 + int(ss))*1000 + int(ms)
        start = parse_vtt_ts(t1)
        end = parse_vtt_ts(t2)
        content = lns[i0+1:]
        idx += 1
        subs.append(Subtitle(idx, start, end, content))
    return subs


def parse_ttml(text: str):
    subs = []
    ns = {
        'tt':'http://www.w3.org/ns/ttml',
        'p':'http://www.w3.org/ns/ttml#parameter',
        'tts':'http://www.w3.org/ns/ttml#styling'
    }
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Try without namespaces
        root = ET.fromstring(text)
    # Support both tt and imsc style ttml
    # search for all <p> regardless of prefix
    idx = 0
    for p in root.iter():
        tag = p.tag.split('}')[-1]
        if tag != 'p':
            continue
        begin = p.attrib.get('begin')
        end = p.attrib.get('end')
        if not begin or not end:
            continue
        def parse_clock(c):
            # supports HH:MM:SS.mmm or SS.mmm or time in seconds with 's'
            c = c.strip()
            if c.endswith('s'):
                return int(float(c[:-1])*1000)
            if ':' in c:
                parts = c.split(':')
                hh=int(parts[0]); mm=int(parts[1]);
                ss_ms = parts[2]
                if '.' in ss_ms:
                    ss, ms = ss_ms.split('.')
                    ms = int((ms + '000')[:3])
                else:
                    ss, ms = ss_ms, '000'
                return ((hh*60+mm)*60+int(ss))*1000+int(ms)
            if '.' in c:
                ss, ms = c.split('.')
                return int(float(ss+'.'+ms)*1000)
            return int(float(c)*1000)
        start = parse_clock(begin)
        endt = parse_clock(end)
        # collect text (join spans)
        text_lines = []
        # split by <br/> into lines
        raw = ''.join(p.itertext())
        # replace multiple spaces
        raw = re.sub(r"\s+", ' ', raw).strip()
        text_lines = raw.split('
') if '
' in raw else [raw]
        idx += 1
        subs.append(Subtitle(idx, start, endt, text_lines))
    return subs


def detect_format(text: str, filename: str):
    name = filename.lower()
    if name.endswith('.srt'):
        return 'srt'
    if name.endswith('.vtt') or 'WEBVTT' in text[:20]:
        return 'vtt'
    if name.endswith('.xml') or name.endswith('.ttml') or '<tt' in text[:200]:
        return 'ttml'
    if name.endswith('.pac'):
        return 'pac'
    # try to guess SRT
    if '-->' in text and ',' in text:
        return 'srt'
    return 'unknown'


def load_subtitles(text: str, filename: str):
    fmt = detect_format(text, filename)
    if fmt == 'srt':
        return parse_srt(text), fmt
    elif fmt == 'vtt':
        return parse_vtt(text), fmt
    elif fmt == 'ttml':
        return parse_ttml(text), fmt
    elif fmt == 'pac':
        raise ValueError('PAC provided: convert to SRT/VTT/TTML before QC (style fidelity not guaranteed).')
    else:
        raise ValueError('Unknown subtitle format')

# --- Profiles ---

def load_profiles(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- QC checks ---

def cps(text: str, duration_ms: int):
    if duration_ms <= 0:
        return float('inf')
    return len(text) / (duration_ms/1000.0)


def run_qc(subs, profile):
    issues = []
    total_chars = 0
    total_duration = 0
    over_cps = 0
    for s in subs:
        total_chars += len(s.text)
        total_duration += s.duration_ms
        # duration checks
        min_d = profile.get('minDurationSec')
        max_d = profile.get('maxDurationSec')
        if min_d and s.duration_ms < min_d*1000:
            issues.append({"type":"duration-too-short","severity":"warning","index":s.index,"time":s.start_ms,
                           "message":f"Duration {s.duration_ms}ms below {min_d}s"})
        if max_d and s.duration_ms > max_d*1000:
            issues.append({"type":"duration-too-long","severity":"warning","index":s.index,"time":s.start_ms,
                           "message":f"Duration {s.duration_ms}ms above {max_d}s"})
        # line count
        if len(s.lines) > profile.get('maxLines', 2):
            issues.append({"type":"too-many-lines","severity":"error","index":s.index,"time":s.start_ms,
                           "message":f"{len(s.lines)} lines (max {profile.get('maxLines',2)})"})
        # CPL
        max_cpl = profile.get('maxCpl')
        min_cpl = profile.get('minCpl')
        for li, line in enumerate(s.lines, start=1):
            L = len(line)
            if max_cpl and L > max_cpl:
                issues.append({"type":"cpl-exceeded","severity":"warning","index":s.index,"line":li,
                               "time":s.start_ms,"message":f"{L} > {max_cpl} chars"})
            if min_cpl and L < min_cpl and len(s.lines)==2:
                # informational: highly uneven lines
                issues.append({"type":"cpl-low" ,"severity":"info","index":s.index,"line":li,
                               "time":s.start_ms,"message":f"{L} < {min_cpl} chars (balance lines if possible)"})
        # CPS
        target_cps = profile.get('targetCps')
        if target_cps:
            c = cps(s.text.replace('
',' '), s.duration_ms)
            if c > target_cps:
                over_cps += 1
                issues.append({"type":"cps-high","severity":"warning","index":s.index,"time":s.start_ms,
                               "message":f"CPS {c:.1f} > target {target_cps}"})
        # Swedish ellipsis rule if specified
        ell = profile.get('ellipsis', {})
        if ell:
            if '...' in s.text:
                issues.append({"type":"ellipsis-three-dots","severity":"info","index":s.index,"time":s.start_ms,
                               "message":"Use single ellipsis character … (U+2026)"})
        # Dual speaker dash
        if profile.get('dualSpeakerDash') and len(s.lines)==2:
            # if both lines look like dialogue by two speakers but not prefixed with dash
            needs = []
            for line in s.lines:
                if line.strip().startswith('-'):
                    continue
                # naive heuristic: treat colon or quote as speaker lead, else require dash
                needs.append(True)
            if all(needs):
                issues.append({"type":"missing-dual-speaker-dash","severity":"info","index":s.index,"time":s.start_ms,
                               "message":"Add hyphen at start of each line for two speakers"})
    avg_cps = (total_chars/(total_duration/1000.0)) if total_duration>0 else 0
    metrics = {"avgCPS": round(avg_cps,2), "count": len(subs), "overCPS": over_cps}
    return issues, metrics


def safe_fixes(subs, profile):
    # Apply limited, deterministic fixes
    max_cpl = profile.get('maxCpl')
    min_d = profile.get('minDurationSec')
    max_d = profile.get('maxDurationSec')
    changed = []
    for s in subs:
        ch = []
        # duration clamp
        if min_d and s.duration_ms < min_d*1000:
            s.end_ms = s.start_ms + int(min_d*1000)
            ch.append('duration-min')
        if max_d and s.duration_ms > max_d*1000:
            s.end_ms = s.start_ms + int(max_d*1000)
            ch.append('duration-max')
        # CPL reflow (very naive: wrap long lines at last space before max_cpl)
        if max_cpl:
            new_lines = []
            for line in s.lines:
                ln = line
                while len(ln) > max_cpl:
                    cut = ln.rfind(' ', 0, max_cpl)
                    if cut == -1:
                        cut = max_cpl
                    new_lines.append(ln[:cut].rstrip())
                    ln = ln[cut:].lstrip()
                new_lines.append(ln)
            # ensure at most 2 lines; if more, join tail lines
            if len(new_lines) > 2:
                head = new_lines[:1]
                tail = ' '.join(new_lines[1:])
                s.lines = [head[0], tail]
            else:
                s.lines = new_lines
            ch.append('wrap-cpl')
        # ellipsis normalization
        ell = profile.get('ellipsis', {})
        if ell:
            desired = ell.get('char', '…')
            t = s.text
            t2 = t.replace('...', desired)
            if ell.get('noSpacesWithinSentence', False):
                t2 = re.sub(r"\s*…\s*", '…', t2)
            if t2 != t:
                s.lines = t2.split('
')
                ch.append('ellipsis')
        # dual speaker dash addition
        if profile.get('dualSpeakerDash') and len(s.lines)==2:
            if not s.lines[0].strip().startswith('-'):
                s.lines[0] = '- ' + s.lines[0].lstrip()
            if not s.lines[1].strip().startswith('-'):
                s.lines[1] = '- ' + s.lines[1].lstrip()
            ch.append('dual-dash')
        if ch:
            changed.append((s.index, ch))
    return changed


def serialize_srt(subs):
    out = []
    def fmt(ms):
        s = ms//1000
        ms2 = ms%1000
        h = s//3600
        m = (s%3600)//60
        ss = s%60
        return f"{h:02d}:{m:02d}:{ss:02d},{ms2:03d}"
    for s in subs:
        out.append(str(s.index))
        out.append(f"{fmt(s.start_ms)} --> {fmt(s.end_ms)}")
        out.extend(s.lines)
        out.append("")
    return "
".join(out)


def generate_html_report(issues, metrics, profile_name, sources):
    rows = []
    for it in issues[:200]:
        rows.append(f"<tr><td>{html.escape(it.get('severity',''))}</td><td>{html.escape(it.get('type',''))}</td><td>{it.get('index')}</td><td>{it.get('time')}</td><td>{html.escape(it.get('message',''))}</td></tr>")
    refs = ''.join([f"<li><a href='{html.escape(u)}' target='_blank'>{html.escape(u)}</a></li>" for u in sources])
    return f"""
<!doctype html>
<html><head><meta charset='utf-8'><title>QC Report</title>
<style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif}} table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:6px}} th{{background:#f5f5f5}}</style>
</head>
<body>
<h1>QC Report – {html.escape(profile_name)}</h1>
<p><b>Count:</b> {metrics.get('count')} &nbsp; <b>Avg CPS:</b> {metrics.get('avgCPS')} &nbsp; <b>Over CPS:</b> {metrics.get('overCPS')}</p>
<h2>Issues</h2>
<table><tr><th>Severity</th><th>Type</th><th>#</th><th>Time (ms)</th><th>Message</th></tr>
{''.join(rows)}
</table>
<h2>Guidelines referenced</h2>
<ul>{refs}</ul>
</body></html>
"""
