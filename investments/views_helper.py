"""The local helper's two endpoints (plan 28.3). With PRICE_HELPER_ENABLED off both are a 404 and nothing else mentions the helper."""
import csv
import io
import json

from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .errors import InvestmentsError
from .services import helper


def _auth(request):
    if not helper.enabled():
        raise Http404
    if not request.is_secure() and not getattr(request, "_helper_allow_http", False):
        from django.conf import settings

        if not settings.DEBUG:
            return None, JsonResponse({"ok": False, "error": "HTTPS_ONLY"}, status=400)
    try:
        token = helper.authenticate(request.headers.get("Authorization", ""))
    except InvestmentsError as err:
        return None, JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=err.status)
    if token is None:
        return None, JsonResponse({"ok": False, "error": "UNAUTHORISED"}, status=401)
    return token, None


@csrf_exempt
def wanted(request):
    token, refused = _auth(request)
    if refused:
        return refused
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "METHOD"}, status=405)
    return JsonResponse({"ok": True, "wanted": helper.wanted()})


@csrf_exempt
def ingest(request):
    token, refused = _auth(request)
    if refused:
        return refused
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "METHOD"}, status=405)
    if len(request.body) > helper.MAX_BYTES:
        return JsonResponse({"ok": False, "error": "TOO_BIG"}, status=413)
    try:
        if request.content_type == "text/csv":
            rows = list(csv.DictReader(io.StringIO(request.body.decode("utf-8"))))
        else:
            rows = json.loads(request.body.decode("utf-8")).get("rows", [])
        result = helper.ingest(rows, token)
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "BAD_BODY"}, status=400)
    except InvestmentsError as err:
        return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=err.status)
    except Exception as exc:
        from .services.locks import Busy

        if isinstance(exc, Busy):
            return JsonResponse({"ok": False, "error": "BUSY"}, status=503)
        raise
    return JsonResponse({"ok": True, **result})
