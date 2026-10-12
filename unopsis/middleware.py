"""
Cross-origin access for the public, read-only endpoints.

A browser will not let a page on one site read a response from another site unless the response
says it may. That is exactly the situation of the Vega-Lite editor: it lives at
vega.github.io, and a spec opened there with "data": {"url": "https://<us>/api/..."} has the
editor's page fetch our JSON. Without an Access-Control-Allow-Origin header the browser blocks
that read and the chart in the editor stays empty, even though the same URL opens fine in a tab.

The header is added to the two prefixes that other sites may need to read:

    /api/...         the JSON feeds (and the holiday analysis)
    /vega-lite/...   the chart specs and the rendered PNGs

Assignment 5 changed what that sentence means, so it is worth restating carefully rather than
leaving the old one standing. Most of those endpoints now require a login; only
/api/insights/items-by-lane/ is still readable without an account. The wildcard header is
nevertheless still correct, and still safe, for a reason worth knowing:

    Access-Control-Allow-Origin: * and credentials are mutually exclusive. A browser refuses
    to hand a cross-origin response to a page when the response says "*" AND the request
    carried cookies, so a foreign page fetching /api/items/ sends no session cookie, gets the
    302 to /accounts/login/ that any anonymous request gets, and reads nothing. The header
    cannot widen access past the decorator; it only decides whether a reply the server was
    already willing to send may be read by script on another origin.

So the practical effect after Assignment 5 is: the public feed can be charted from anywhere
(which is the point -- the Vega-Lite editor at vega.github.io is "anywhere"), and the
protected endpoints answer a cross-origin reader with a login redirect instead of a CORS
error. The prefixes are kept broad rather than narrowed to the one public path on purpose: a
protected endpoint that says "*" leaks nothing, while a public one that forgets to is a chart
that silently renders empty in the editor, which is much harder to diagnose.

Pages, forms, /accounts/ and /admin/ are untouched and stay same-origin only -- which matters
most for /accounts/login/, where a cross-origin reader has no business at all.
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
