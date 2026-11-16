"""SPA fallback: serve the Vite-built index.html for anything that isn't
matched by /api, /admin, /health, or /static. Vite hashes asset filenames
so caching is safe to leave to the browser/whitenoise defaults.

Two SPAs share this view: the staff dashboard (web/) and, on the portal
hostname, the customer portal (portal/). The choice is made by Host."""

from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse

from .middleware import is_portal_host


def spa_index(request):
    build_dir = settings.PORTAL_BUILD_DIR if is_portal_host(request) else settings.WEB_BUILD_DIR
    index = Path(build_dir) / "index.html"
    if not index.exists():
        raise Http404(
            f"SPA build not found at {build_dir}. In dev, run the Vite dev "
            "server (npm run dev). In the container, the Dockerfile copies "
            "the built SPAs into place during the build."
        )
    # Don't cache index.html — it references the latest hashed assets.
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
