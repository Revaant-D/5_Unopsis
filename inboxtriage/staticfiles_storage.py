"""
The static-file storage used in production, and why it is not Django's one straight out of the box.

Production wants cache busting: `collectstatic` hashes each file's contents and writes a copy
whose name carries the hash (css/unopsis.6fd1a0e9.css), so a new release is a new URL that no
browser has cached. Django ships ManifestStaticFilesStorage for exactly that, and
inboxtriage/settings/production.py explains the idea at length.

The catch is what it does when the hashes are missing. The lookup table lives in
staticfiles/staticfiles.json, which only exists AFTER `collectstatic` has run, and the stock class
treats a name it cannot find as a fatal error:

    ValueError: Missing staticfiles manifest entry for 'css/unopsis.css'

That is raised by the {% static %} tag while a template renders, so a fresh clone started with
--settings=inboxtriage.settings.production answers HTTP 500 on every HTML page -- not an unstyled
page, a dead one -- until someone remembers the collectstatic step. The assignment asks that the
project RUN under both development and production settings, and "it runs once you know the
undocumented step" is not that.

So this subclass makes the missing-hash case fall back to the plain name instead of raising. Two
things are needed, because Django fails twice on the way down:

  1. manifest_strict = False stops the first error, the missing manifest entry. Django then tries
     to hash the file on the spot instead.
  2. That attempt reads the file out of STATIC_ROOT, which is also empty before collectstatic, so
     it raises its own ValueError ("The file 'css/unopsis.css' could not be found with ..."). The
     stored_name() override below catches that and returns the un-hashed name.

The trade is small and honest:

  * manifest present (the real deployment, after collectstatic) -- behaviour is unchanged, the
    hashed name is served, cache busting works exactly as before. Neither fallback is reached.
  * manifest absent -- the page renders against /static/css/unopsis.css. The stylesheet may be
    served stale out of a browser cache, which is cosmetic; a 500 on the home page is not.

Running collectstatic before serving production is still the right thing to do, and README.md
flags it as a required step. This class only makes forgetting it a blemish instead of an outage.
"""

from urllib.parse import unquote, urlsplit

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class ResilientManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """ManifestStaticFilesStorage that falls back to the un-hashed name instead of raising."""

    # Read by Django inside stored_name(). False means "if the name is not in staticfiles.json,
    # try hashing it live" rather than "raise ValueError".
    manifest_strict = False

    def stored_name(self, name):
        """
        Return the hashed name for `name`, or `name` itself if it cannot be hashed yet.

        Only the un-collected case reaches the fallback. Once collectstatic has run, the manifest
        answers every lookup and super() returns before the except clause is ever considered.
        """
        try:
            return super().stored_name(name)
        except ValueError:
            # Either the manifest is missing/incomplete or the file is not in STATIC_ROOT yet.
            # Neither is worth a 500: hand back the plain path and let the page render.
            return urlsplit(unquote(name)).path.strip()
