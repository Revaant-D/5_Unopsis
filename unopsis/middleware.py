"""
Cross-origin access for the public, read-only endpoints.

A browser will not let a page on one site read a response from another site unless the response
says it may. That is exactly the situation of the Vega-Lite editor: it lives at
vega.github.io, and a spec opened there with "data": {"url": "https://<us>/api/..."} has the
editor's page fetch our JSON. Without an Access-Control-Allow-Origin header the browser blocks
that read and the chart in the editor stays empty, even though the same URL opens fine in a tab.

The header is added only to the paths meant to be read by other sites:

    /api/...         the JSON feeds (and the holiday analysis)
    /vega-lite/...   the chart specs and the rendered PNGs

and only as "*", which is safe here because those endpoints are public, GET-only, and use no
cookies or login -- there is nothing a foreign page could read through them that it could not
read by opening the URL. Pages, forms and /admin/ are untouched and stay same-origin only.
"""

PUBLIC_PREFIXES = ("/api/", "/vega-lite/")


class PublicApiCorsMiddleware:
    """Add Access-Control-Allow-Origin: * to responses under PUBLIC_PREFIXES."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(PUBLIC_PREFIXES):
            response["Access-Control-Allow-Origin"] = "*"
        return response
