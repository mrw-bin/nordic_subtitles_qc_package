
import json, os, base64, pathlib
from azure.functions import HttpRequest, HttpResponse
from . import utils

# In a real deployment you would fetch the file from SharePoint/Blob via SAS URL.
# For this sample we accept a base64 payload or inline text for demonstration.

GUIDELINE_SOURCES = {
    'Netflix-SV': [
        'https://partnerhelp.netflixstudios.com/hc/en-us/articles/216014517-Swedish-Timed-Text-Style-Guide',
        'https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements'
    ],
    'SVT-SE': [
        'https://www.medietextarna.se/wp-content/uploads/2024/12/Riktlinjer-for-undertextning-i-Sverige-v2.pdf'
    ],
    'NRK-NO': [
        'https://sprakradet.no/godt-og-korrekt-sprak/praktisk-sprakbruk/retningslinjer-for-god-teksting-i-norge/'
    ],
    'DR-DK': [
        'https://undertekstning.dk/'
    ],
    'Yle-FI (fi)': [
        'https://kieliasiantuntijat.fi/wp/wp-content/uploads/2023/06/Quality-Recommendations-for-Finnish-Subtitling.pdf'
    ],
    'Yle-FI (sv)': [
        'https://kieliasiantuntijat.fi/wp/wp-content/uploads/2023/06/Quality-Recommendations-for-Finnish-Subtitling.pdf'
    ]
}

PROFILES_PATH = os.path.join(os.path.dirname(__file__), '..', 'rules', 'profiles.json')

async def main(req: HttpRequest) -> HttpResponse:
    try:
        body = req.get_json()
    except Exception:
        return HttpResponse('Invalid JSON', status_code=400)
    file_url = body.get('fileUrl','')
    profile_name = body.get('profile','Netflix-SV')
    content_b64 = body.get('contentBase64')
    filename = body.get('filename','input.srt')

    if not content_b64 and not file_url:
        return HttpResponse('Provide fileUrl or contentBase64', status_code=400)

    # For the sample, prefer contentBase64
    if content_b64:
        data = base64.b64decode(content_b64).decode('utf-8', errors='replace')
    else:
        # Demo: cannot fetch external URLs in this environment
        return HttpResponse('Fetching by URL is not enabled in sample. Use contentBase64.', status_code=400)

    profiles = utils.load_profiles(PROFILES_PATH)
    if profile_name not in profiles['profiles']:
        return HttpResponse('Unknown profile', status_code=400)
    profile = profiles['profiles'][profile_name]

    try:
        subs, fmt = utils.load_subtitles(data, filename)
    except Exception as e:
        return HttpResponse(json.dumps({"error": str(e)}), status_code=400, mimetype='application/json')

    issues, metrics = utils.run_qc(subs, profile)
    report_html = utils.generate_html_report(issues, metrics, profile_name, GUIDELINE_SOURCES.get(profile_name, []))
    # Save a sample report locally (for demo) and return as data URL
    report_path = os.path.join(os.path.dirname(__file__), '..', 'report_sample.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_html)

    return HttpResponse(
        json.dumps({
            'issues': issues,
            'metrics': metrics,
            'preview': '
'.join(subs[0].lines) if subs else '',
            'reportUrl': 'file://' + str(pathlib.Path(report_path).resolve()),
            'normalizedFileUrl': 'inline://not-persisted-in-sample'
        }),
        mimetype='application/json'
    )
