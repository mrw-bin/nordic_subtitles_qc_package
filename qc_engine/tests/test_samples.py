
import base64, json
from qc_engine.qc_run import __init__ as run_mod
from qc_engine.qc_fix import __init__ as fix_mod

class DummyReq:
    def __init__(self, d):
        self._d = d
    def get_json(self):
        return self._d

async def test_run_qc_event_loop():
    srt = """1
00:00:01,000 --> 00:00:02,000
Det här är en mycket lång rad som sannolikt bryter mot CPL för Netflix.

"""
    b64 = base64.b64encode(srt.encode()).decode()
    req = DummyReq({"profile":"Netflix-SV","contentBase64": b64, "filename":"test.srt"})
    resp = await run_mod.main(req)
    assert resp.status_code == 200

async def test_fix_safe_only():
    srt = """1
00:00:01,000 --> 00:00:01,200
- Hej!
- Tjena!

"""
    b64 = base64.b64encode(srt.encode()).decode()
    req = DummyReq({"profile":"NRK-NO","autoFixMode":"safe-only","contentBase64": b64, "filename":"a.srt"})
    resp = await fix_mod.main(req)
    assert resp.status_code == 200
