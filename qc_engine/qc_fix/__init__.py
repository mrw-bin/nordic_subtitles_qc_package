
import json, base64
from azure.functions import HttpRequest, HttpResponse
from . import utils

PROFILES_PATH = __import__('os').path.join(__import__('os').path.dirname(__file__), '..', 'rules', 'profiles.json')

async def main(req: HttpRequest) -> HttpResponse:
    try:
        body = req.get_json()
    except Exception:
        return HttpResponse('Invalid JSON', status_code=400)
    profile_name = body.get('profile','Netflix-SV')
    mode = body.get('autoFixMode','none')
    content_b64 = body.get('contentBase64')
    filename = body.get('filename','input.srt')

    if not content_b64:
        return HttpResponse('Provide contentBase64 for sample', status_code=400)

    data = base64.b64decode(content_b64).decode('utf-8', errors='replace')
    profiles = utils.load_profiles(PROFILES_PATH)
    profile = profiles['profiles'].get(profile_name)
    if not profile:
        return HttpResponse('Unknown profile', status_code=400)

    subs, fmt = utils.load_subtitles(data, filename)

    issues_before, metrics_before = utils.run_qc(subs, profile)
    changes = []
    if mode == 'safe-only':
        changes = utils.safe_fixes(subs, profile)
    elif mode == 'llm-rewrite-with-approval':
        # Placeholder: produce suggestions but do not modify content
        pass

    fixed_srt = utils.serialize_srt(subs)

    return HttpResponse(
        json.dumps({
            'fixedFileUrl': 'inline://fixed.srt',
            'fixedFileBase64': base64.b64encode(fixed_srt.encode('utf-8')).decode('ascii'),
            'changes': changes
        }),
        mimetype='application/json'
    )
