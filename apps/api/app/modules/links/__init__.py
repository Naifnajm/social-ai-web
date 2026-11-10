"""Link tracking & sales attribution. Registers the publishing ``TEXT_FILTERS`` hook when the package is imported
(the registry imports ``links.models`` / ``links.router`` at start-up, which imports this package first)."""
from app.modules.social import hooks as _hooks


def tracked_links_filter(db, post, account, text):
    """(db, post, account, text) -> text with tracked short links (see ``links.service.track_text``)."""
    from .service import track_text
    return track_text(db, post, account, text)


if not any(getattr(f, "__name__", "") == "tracked_links_filter" for f in _hooks.TEXT_FILTERS):
    _hooks.TEXT_FILTERS.append(tracked_links_filter)
