"""The business dashboard page (until the React screens arrive)."""
from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from apps.rbac import policy

from . import dashboard

CHART_W, CHART_H, PAD_L, PAD_B, PAD_T = 640, 220, 56, 28, 16


def _nice_max(value: Decimal) -> Decimal:
    """A round number just above the largest bar (for the axis)."""
    if value <= 0:
        return Decimal("100")
    step = Decimal(10) ** (len(str(int(value))) - 1)
    for multiple in (1, 2, 2.5, 5, 10):
        top = step * Decimal(str(multiple))
        if top >= value:
            return top
    return step * 10


def _columns(week: list[dict]) -> dict:
    top = _nice_max(max((w["total"] for w in week), default=Decimal("0")))
    plot_w, plot_h = CHART_W - PAD_L - 8, CHART_H - PAD_T - PAD_B
    slot = plot_w / len(week)
    bar_w = min(24, slot * 0.5)
    bars = []
    for i, w in enumerate(week):
        h = float(w["total"]) / float(top) * plot_h if top else 0
        x = PAD_L + slot * i + (slot - bar_w) / 2
        y = PAD_T + plot_h - h
        r = min(4, h)  # rounded data end, square at the baseline
        path = (
            f"M{x:.1f},{PAD_T + plot_h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f} V{PAD_T + plot_h:.1f} Z"
        ) if h > 0 else ""
        bars.append({**w, "path": path, "x": x, "cx": x + bar_w / 2, "y": y, "hit_x": PAD_L + slot * i, "hit_w": slot})
    grid = [{"y": PAD_T + plot_h - plot_h * f, "label": f"${top * Decimal(str(f)):,.0f}"} for f in (0, 0.5, 1)]
    return {"bars": bars, "grid": grid, "w": CHART_W, "h": CHART_H, "base_y": PAD_T + plot_h, "plot_top": PAD_T, "pad_l": PAD_L,
            "plot_right": CHART_W - 8, "hit_y": PAD_T, "hit_h": plot_h, "label_y": CHART_H - 8}


def money_change(change: dict) -> dict:
    diff = change["difference"]
    sign = "+" if diff > 0 else ("−" if diff < 0 else "±")
    text = f"{sign}${abs(diff):,.2f}" + (f" ({change['percent']:+d}%)" if change["percent"] is not None else "")
    return {"direction": "up" if diff > 0 else ("down" if diff < 0 else ""), "text": text}


def count_change(change: dict) -> dict:
    diff = change["difference"]
    text = f"{diff:+d}" if diff else "Same as"
    return {"direction": "up" if diff > 0 else ("down" if diff < 0 else ""), "text": text}


def dashboard_page(request):
    if not policy.require(request.user, "reports.view", request=request):
        raise PermissionDenied
    value = request.GET.get("date")
    try:
        day = date.fromisoformat(value) if value else None
    except ValueError:
        day = None
    data = dashboard.summary(day, include_inbox=policy.has_perm(request.user, "crm.view"))
    best = max((p["sales"] for p in data["top_products"]), default=Decimal("0"))
    for p in data["top_products"]:
        p["width"] = round(float(p["sales"]) / float(best) * 100, 1) if best else 0
    context = {
        **admin.site.each_context(request),
        "title": "Dashboard",
        "data": data,
        "chart": _columns(data["week"]),
        "sales_change": money_change(data["sales"]["change"]),
        "orders_change": count_change(data["orders"]["change"]),
        "is_today": data["date"] == timezone.localdate().isoformat(),
        "can_see_orders": policy.has_perm(request.user, "orders.view"),
    }
    return render(request, "reports/dashboard.html", context)
