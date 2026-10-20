"""Small helpers shared by the business APIs."""
from rest_framework.pagination import PageNumberPagination


class Pages(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def as_bool(value) -> bool | None:
    """'true'/'1'/'yes' -> True, other text -> False, missing -> None."""
    if value is None or value == "":
        return None
    return str(value).strip().lower() in ("1", "true", "yes")
