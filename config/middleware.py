"""Small project middleware."""
from django.middleware.gzip import GZipMiddleware

#: Content types worth compressing (pages, JSON from the Edit mode script, scripts, styles, SVG).
COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml")


class TextGZipMiddleware(GZipMiddleware):
    """gzip for pages and text only, so a phone downloads a fraction of the bytes over mobile data.

    Downloads (backup files, Word files, anything sent as an attachment) are left alone: they are already compressed,
    and compressing them again would only cost time and hide their size from the browser's progress bar.
    """

    def process_response(self, request, response):
        content_type = (response.get("Content-Type", "") or "").split(";")[0].strip().lower()
        if response.has_header("Content-Disposition") or not content_type.startswith(COMPRESSIBLE):
            return response
        return super().process_response(request, response)
