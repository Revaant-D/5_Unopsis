from django.apps import AppConfig


class UnopsisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'unopsis'

    def ready(self):
        """
        Import the modules whose only job is to connect signal receivers.

        Django calls ready() once per process, after the app registry is populated, which is
        the earliest moment an import may safely reach for another app's models or signals.
        A top-of-file import in this module would run before that and raise AppRegistryNotReady.

        unopsis/onboarding.py connects to allauth's user_signed_up, which is what gives an
        account created through "Continue with Google" its own demo rows. Without this line
        the receiver is simply never registered: no error, no warning, and a Google sign-up
        lands on an empty site. The noqa is because the import IS the side effect -- the name
        is never used here.
        """
        from . import onboarding  # noqa: F401  (imported for its signal registration)
