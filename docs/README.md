# Nordic Subtitles QC – Deployment Package

**Generated:** 2025-10-21T11:11:12.298552Z

This package contains a Copilot Studio bot blueprint, a Custom Connector (OpenAPI), and an **Azure Functions (Python)** QC engine that performs subtitle quality control for **SRT, WebVTT, TTML/IMSC**, with **PAC supported via conversion**. It implements rule profiles for **Netflix Swedish**, **Sweden (SVT/industry)**, **Norway (Språkrådet model)**, **Denmark (FBO)**, and **Finland (Yle quality recommendations)**.

## Contents
```
nordic_subtitles_qc_package/
  copilot/
    system_message.txt
    topics.md
  connector/
    openapi.json
  qc_engine/
    host.json
    local.settings.json.sample
    requirements.txt
    utils.py
    qc_run/
      __init__.py
      function.json
    qc_fix/
      __init__.py
      function.json
    rules/
      profiles.json
    tests/
      test_samples.py
  sharepoint/
    adaptive_card.json
  docs/
    (you)
  samples/
    sample.srt
```

## Quick start (local)
1. **Python 3.10+** and **Azure Functions Core Tools v4**.
2. `cd qc_engine && python -m venv .venv && . .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `func start`
5. POST to `http://localhost:7071/api/qc/run` with JSON:
```json
{
  "profile": "Netflix-SV",
  "filename": "sample.srt",
  "contentBase64": "<base64 of samples/sample.srt>"
}
```

## Deploy
- **Azure Functions** → create a Python Function App, deploy this folder.
- **Custom Connector** (Power Platform) → import `connector/openapi.json` and set host URL to your Function App.
- **Copilot Studio** → create copilot, paste `copilot/system_message.txt` into the instructions, add actions bound to the connector methods, and wire the topics from `copilot/topics.md`.
- **Storage/SharePoint** → replace placeholders in `local.settings.json.sample` and in code with your URLs; in production, fetch files by SAS/Graph and persist reports to SharePoint, returning links.

## Rule sources (implementations reference)
- **Netflix Swedish Timed Text Style Guide** – CPL=42, ellipsis rules, abbreviations/titles: https://partnerhelp.netflixstudios.com/hc/en-us/articles/216014517-Swedish-Timed-Text-Style-Guide
- **Netflix General Requirements** – timing (min 5/6 s, max 7 s), line breaking & positioning: https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements
- **Sweden** – *Riktlinjer för undertextning i Sverige* (Medietextarna, with SVT et al.): https://www.medietextarna.se/wp-content/uploads/2024/12/Riktlinjer-for-undertextning-i-Sverige-v2.pdf
- **Norway** – *Retningslinjer for god teksting i Norge* (Språkrådet + broadcasters): https://sprakradet.no/godt-og-korrekt-sprak/praktisk-sprakbruk/retningslinjer-for-god-teksting-i-norge/
- **Denmark** – *Retningslinjer for undertekstning i Danmark* (FBO): https://undertekstning.dk/
- **Finland** – *Quality Recommendations for Finnish Subtitling*: https://kieliasiantuntijat.fi/wp/wp-content/uploads/2023/06/Quality-Recommendations-for-Finnish-Subtitling.pdf
- **PAC caveats** – PAC is a playout format; importers note limited font/position fidelity: https://broadstream.com/WebHelp/Reference/PAC_File_Format.htm

> NOTE: Some platform‑specific TTML/IMSC profiles (e.g., Netflix DFXP, Disney IMSC 1.1) exist; the engine parses generic TTML/IMSC. For Disney+ workflows tool vendors reference **IMSC 1.1** import/export: https://www.eztitles.com/Webhelp/EZConvert/import_subtitles_disney.htm

## Auto‑fix modes
- `none` – analysis only.
- `safe-only` – clamps durations, wraps long lines to CPL, normalizes ellipsis `…`, adds dual‑speaker dashes where applicable. All changes are logged.
- `llm-rewrite-with-approval` – placeholder in this sample; in production, call your LLM endpoint to propose textual rewrites; **require explicit user approval** before applying (Nordic broadcasters have publicly scrutinized quality of fully automated text). See: 
  - GRN/SVT AI‑textning critiques: https://www.voister.se/artikel/2025/06/granskningsnamnden-kritiserar-svts-ai-textning/

## Limitations (sample)
- **PAC** requires conversion to text (SRT) before QC; styling fidelity may be lost.
- This sample stores report locally and returns a `file://` URL; in production, upload to SharePoint/Blob and return HTTPS links.
- Shot‑change and advanced segmentation are not implemented here.

## Security & privacy
- Never overwrite originals; version outputs.
- Log fix operations with rule IDs and timestamps for audit.

## Adaptive Card
Use `sharepoint/adaptive_card.json` as a Teams card template. Replace `$Ellipsis` tokens at runtime.

## Tests
`qc_engine/tests/test_samples.py` includes two async tests showing how to invoke the functions with inline base64 content.

--
Generated for Jan West – Solution Architect, Stockholm.
