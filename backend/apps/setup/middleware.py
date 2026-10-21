"""Open the setup wizard instead of the admin home page while a business's setup is not finished (task 1.16)."""
from django.shortcuts import redirect

from . import services


class SetupWizardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and request.path == "/admin/":
            try:
                if services.should_open_wizard(request):
                    return redirect("setup")
            except Exception:  # noqa: BLE001 - never block the admin home page because of the wizard
                pass
        return self.get_response(request)
