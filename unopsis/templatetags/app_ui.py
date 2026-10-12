"""Two display helpers for the wireframe templates: {% load app_ui %}."""

from django import template

register = template.Library()


@register.filter
def initials(name):
    """The avatar circle: "Priya Shah" -> "PS", "Prof. Ramirez" -> "PR", "Mom" -> "M"."""
    parts = str(name or "").replace(".", " ").split()
    return "".join(part[0] for part in parts[:2]).upper() or "?"


@register.filter
def provider_letter(value):
    """The one-letter source tile: a Connection or a label -> "G", "S", "W"; nothing -> "·"."""
    if value is None:
        return "·"
    label = value.get_provider_display() if hasattr(value, "get_provider_display") else str(value)
    return label[:1].upper() or "·"
