"""SPA fallback: serve the Vite-built index.html for anything that isn't
matched by /api, /admin, /health, or /static. Vite hashes asset filenames
so caching is safe to leave to the browser/whitenoise defaults."""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse


def spa_index(_request):
    index = Path(settings.WEB_BUILD_DIR) / "index.html"
    if not index.exists():
        raise Http404(
            "SPA build not found at WEB_BUILD_DIR. In dev, run the Vite dev "
            "server (npm run dev). In the container, the Dockerfile copies "
            "web/dist/ into this path during the build."
        )
    # Don't cache index.html — it references the latest hashed assets.
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
