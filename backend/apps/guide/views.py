"""
User guide pages (every signed-in person of the site, staff app users included).

/guide/                    contents and search box
/guide/search/?q=...       search results
/guide/<chapter>/          one chapter, with its sections and previous/next
/guide/images/<name>       a screenshot used by the chapters
"""
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import services


def _ctx(request, **extra):
    from django.db import connection

    return {"contents": services.contents(), "on_platform": connection.schema_name == "public",
            "is_staff": request.user.is_staff, **extra}


@login_required
@require_GET
def home(request):
    return render(request, "guide/home.html", _ctx(request, title="User guide"))


@login_required
@require_GET
def search(request):
    query = request.GET.get("q", "").strip()[:100]
    results = services.search(query) if query else []
    return render(request, "guide/search.html", _ctx(request, title="Search the guide", query=query, results=results))


@login_required
@require_GET
def chapter(request, slug):
    item = services.chapter(slug)
    if item is None:
        raise Http404("No such chapter.")
    previous, following = services.neighbours(slug)
    return render(request, "guide/chapter.html", _ctx(request, title=item.title, chapter=item, previous=previous, following=following))


@login_required
@require_GET
def image(request, name):
    path = services.image_path(name)
    if path is None:
        raise Http404("No such image.")
    response = FileResponse(open(path, "rb"), content_type="image/png" if name.endswith(".png") else None)
    response["Cache-Control"] = "private, max-age=3600"
    return response
