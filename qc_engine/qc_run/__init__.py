import os
import json
import base64
import binascii
import logging
import pathlib
import traceback
import time
import uuid
from typing import Any, Dict, Optional, Tuple

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

# ---------- Logging Setup ----------
def _get_logger() -> logging.Logger:
    logger = logging.getLogger("qc_http_function")
    if not logger.handlers:
        # Let Azure Functions host wire up handlers, but set level from env
        level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)
        logger.setLevel(level)
    return logger

logger = _get_logger()

# ---------- Helpers ----------
def _json_response(
    status: int,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None
) -> HttpResponse:
    headers = {'Content-Type': 'application/json'}
    if correlation_id:
        headers['X-Correlation-Id'] = correlation_id
        payload.setdefault('correlationId', correlation_id)
    return HttpResponse(json.dumps(payload, ensure_ascii=False), status_code=status, headers=headers)

def _err(
    status: int,
    error_code: str,
    message: str,
    *,
    correlation_id: Optional[str] = None,
    exc: Optional[Exception] = None
) -> HttpResponse:
    debug = os.getenv("DEBUG_RESPONSES", "false").lower() in ("1", "true", "yes")
    body: Dict[str, Any] = {"errorCode": error_code, "message": message}
    if debug and exc is not None:
        body["details"] = {
            "type": type(exc).__name__,
            "args": getattr(exc, "args", None),
            "traceback": traceback.format_exc(limit=20)
        }
    return _json_response(status, body, correlation_id)

def _safe_len(s: Optional[str]) -> int:
    if s is None:
        return 0
    try:
        return len(s)
    except Exception:
        return -1

def _decode_base64_content(raw_b64: str, correlation_id: str) -> str:
    """Decode base64 content with robust handling & logging. Returns UTF-8 text (errors replaced)."""
    t0 = time.perf_counter()
    # Allow and strip data-URL prefix if present
    prefix_idx = raw_b64.find(";base64,")
    if prefix_idx != -1:
        logger.debug(
            "Stripping data URL prefix before base64 decoding",
            extra={"event": "data_url_prefix_stripped", "correlationId": correlation_id}
        )
        raw_b64 = raw_b64[prefix_idx + len(";base64,"):]

    try:
        decoded_bytes = base64.b64decode(raw_b64, validate=True)
        text = decoded_bytes.decode("utf-8", errors="replace")
        logger.info(
            "Base64 decoded successfully",
            extra={
                "event": "base64_decoded",
                "correlationId": correlation_id,
                "decodedBytes": len(decoded_bytes),
                "durationMs": int((time.perf_counter() - t0) * 1000),
            },
        )
        return text
    except binascii.Error as e:
        logger.error(
            "Invalid base64 content",
            exc_info=True,
            extra={
                "event": "base64_decode_error",
                "correlationId": correlation_id,
                "rawLength": len(raw_b64),
            },
        )
        raise e

def _load_profiles(path: str, correlation_id: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    path_obj = pathlib.Path(path)
    if not path_obj.exists():
        logger.error(
            "Profiles file not found",
            extra={"event": "profiles_missing", "correlationId": correlation_id, "path": str(path_obj)}
        )
        raise FileNotFoundError(f"Profiles file not found at {path_obj}")

    try:
        profiles = utils.load_profiles(str(path_obj))
        if "profiles" not in profiles or not isinstance(profiles["profiles"], dict):
            logger.error(
                "Profiles JSON malformed or missing 'profiles' key",
                extra={"event": "profiles_malformed", "correlationId": correlation_id}
            )
            raise ValueError("Profiles JSON does not contain a valid 'profiles' object")
        logger.info(
            "Profiles loaded",
            extra={
                "event": "profiles_loaded",
                "correlationId": correlation_id,
                "availableProfiles": list(profiles["profiles"].keys()),
                "durationMs": int((time.perf_counter() - t0) * 1000),
            },
        )
        return profiles
    except Exception as e:
        logger.error(
            "Failed to load profiles",
            exc_info=True,
            extra={"event": "profiles_load_failed", "correlationId": correlation_id}
        )
        raise e

def _validate_profile(profiles: Dict[str, Any], profile_name: str, correlation_id: str) -> Dict[str, Any]:
    if profile_name not in profiles["profiles"]:
        logger.warning(
            "Profile not found",
            extra={
                "event": "profile_unknown",
                "correlationId": correlation_id,
                "requestedProfile": profile_name,
                "availableProfiles": list(profiles["profiles"].keys()),
            },
        )
        raise KeyError(f"Unknown profile: {profile_name}")
    return profiles["profiles"][profile_name]

def _run_qc_and_report(
    subs, fmt, profile, profile_name: str, correlation_id: str
) -> Tuple[Any, Any, str]:
    # Run QC
    t_qc = time.perf_counter()
    issues, metrics = utils.run_qc(subs, profile)
    qc_ms = int((time.perf_counter() - t_qc) * 1000)

    # Generate HTML report
    t_html = time.perf_counter()
    sources = GUIDELINE_SOURCES.get(profile_name, [])
    report_html = utils.generate_html_report(issues, metrics, profile_name, sources)
    html_ms = int((time.perf_counter() - t_html) * 1000)

    # Persist sample report (local)
    report_path = os.path.join(os.path.dirname(__file__), '..', 'report_sample.html')
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_html)
    except OSError as e:
        logger.error(
            "Failed to write report file",
            exc_info=True,
            extra={
                "event": "report_write_failed",
                "correlationId": correlation_id,
                "reportPath": str(pathlib.Path(report_path).resolve()),
            },
        )
        raise e
    logger.info(
        "QC and report generated",
        extra={
            "event": "qc_complete",
            "correlationId": correlation_id,
            "issuesCount": len(issues) if isinstance(issues, list) else "n/a",
            "metricsKeys": list(metrics.keys()) if isinstance(metrics, dict) else "n/a",
            "qcDurationMs": qc_ms,
            "htmlDurationMs": html_ms,
            "reportPath": str(pathlib.Path(report_path).resolve()),
        },
    )
    return issues, metrics, report_path

# ---------- Main Function ----------
async def main(req: HttpRequest) -> HttpResponse:
    correlation_id = req.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    overall_t0 = time.perf_counter()

    try:
        # Log request metadata without PII/content
        logger.info(
            "Request received",
            extra={
                "event": "request_received",
                "correlationId": correlation_id,
                "method": getattr(req, "method", "UNKNOWN"),
                "contentLength": int(req.headers.get("Content-Length", "0") or 0),
                "contentType": req.headers.get("Content-Type", "unknown"),
            },
        )

        # Parse JSON body
        try:
            body = req.get_json()
        except Exception as e:
            logger.error(
                "Invalid JSON in request body",
                exc_info=True,
                extra={"event": "json_parse_error", "correlationId": correlation_id}
            )
            return _err(400, "InvalidJson", "Invalid JSON payload.", correlation_id=correlation_id, exc=e)

        # Extract fields
        file_url = body.get('fileUrl', '')
        profile_name = body.get('profile', 'Netflix-SV')
        content_b64 = body.get('contentBase64')
        filename = body.get('filename', 'input.srt')

        logger.debug(
            "Parsed request fields",
            extra={
                "event": "request_fields",
                "correlationId": correlation_id,
                "hasContentBase64": bool(content_b64),
                "fileUrlProvided": bool(file_url),
                "profile": profile_name,
                "filename": filename,
                "contentBase64Length": _safe_len(content_b64),
            },
        )

        if not content_b64 and not file_url:
            logger.warning(
                "No content provided",
                extra={"event": "missing_content", "correlationId": correlation_id}
            )
            return _err(400, "NoContent", "Provide fileUrl or contentBase64", correlation_id=correlation_id)

        # For the sample, prefer contentBase64
        if content_b64:
            try:
                data = _decode_base64_content(content_b64, correlation_id)
            except Exception as e:
                return _err(400, "InvalidBase64", "contentBase64 is not valid base64 data", correlation_id, e)
        else:
            logger.info(
                "URL fetch not allowed in sample",
                extra={"event": "url_fetch_blocked", "correlationId": correlation_id, "fileUrl": file_url}
            )
            return _err(
                400,
                "UrlFetchDisabled",
                "Fetching by URL is not enabled in sample. Use contentBase64.",
                correlation_id=correlation_id
            )

        # Load profiles
        try:
            profiles = _load_profiles(PROFILES_PATH, correlation_id)
        except Exception as e:
            return _err(500, "ProfilesLoadError", "Failed to load QC profiles", correlation_id=correlation_id, exc=e)

        # Select profile
        try:
            profile = _validate_profile(profiles, profile_name, correlation_id)
        except KeyError as e:
            return _err(400, "UnknownProfile", str(e), correlation_id=correlation_id)
        except Exception as e:
            logger.error(
                "Profile validation failed unexpectedly",
                exc_info=True,
                extra={"event": "profile_validation_failed", "correlationId": correlation_id}
            )
            return _err(500, "ProfileValidationError", "Failed to validate profile", correlation_id=correlation_id, exc=e)

        # Load subtitles
        try:
            t_load = time.perf_counter()
            subs, fmt = utils.load_subtitles(data, filename)
            load_ms = int((time.perf_counter() - t_load) * 1000)
            subs_count = len(subs) if hasattr(subs, "__len__") else "n/a"
            logger.info(
                "Subtitles parsed",
                extra={
                    "event": "subs_loaded",
                    "correlationId": correlation_id,
                    "format": fmt,
                    "subsCount": subs_count,
                    "durationMs": load_ms,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to parse subtitles",
                exc_info=True,
                extra={"event": "subs_parse_failed", "correlationId": correlation_id, "filename": filename}
            )
            return _err(400, "SubtitleParseError", f"Failed to parse subtitles from {filename}", correlation_id, e)

        # QC + Report
        try:
            issues, metrics, report_path = _run_qc_and_report(subs, fmt, profile, profile_name, correlation_id)
        except Exception as e:
            return _err(500, "QCRunError", "Failed to run QC or generate report", correlation_id, e)

        # Build response
        preview = ""
        try:
            if subs and hasattr(subs[0], "lines"):
                preview = "\n".join(subs[0].lines)  # Preview only first cue lines (safe)
        except Exception:
            preview = ""

        resp = {
            'issues': issues,
            'metrics': metrics,
            'preview': preview,
            'reportUrl': 'file://' + str(pathlib.Path(report_path).resolve()),
            'normalizedFileUrl': 'inline://not-persisted-in-sample'
        }

        logger.info(
            "Request completed successfully",
            extra={
                "event": "request_success",
                "correlationId": correlation_id,
                "totalDurationMs": int((time.perf_counter() - overall_t0) * 1000),
                "issuesCount": len(issues) if isinstance(issues, list) else "n/a",
            },
        )
        return _json_response(200, resp, correlation_id=correlation_id)

    except Exception as e:
        # Last-resort catch-all
        logger.critical(
            "Unhandled error in function",
            exc_info=True,
            extra={"event": "unhandled_exception", "correlationId": correlation_id}
        )
        return _err(500, "UnhandledError", "An unexpected error occurred", correlation_id=correlation_id, exc=e)
