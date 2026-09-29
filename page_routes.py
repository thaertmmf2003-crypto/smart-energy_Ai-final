"""
page_routes.py — Protected dashboard and administrative page endpoints.
"""

from flask import Blueprint, render_template, redirect, url_for
from auth import login_required, admin_required, get_current_user
import database

pages = Blueprint("pages", __name__)


@pages.get("/overview")
@login_required
def overview():
    return render_template("overview.html", page="overview", title="Overview")


@pages.get("/energy")
@login_required
def energy():
    return render_template("energy.html", page="energy", title="Energy Monitor")


@pages.get("/operations")
@login_required
def operations():
    return render_template("operations.html", page="operations", title="AI Operations")


@pages.get("/digital-twin")
@login_required
def digital_twin():
    return render_template("digital_twin.html", page="digital_twin", title="Digital Twin")


@pages.get("/verification")
@login_required
def verification():
    return render_template("verification.html", page="verification", title="Verification")


@pages.get("/knowledge")
@login_required
def knowledge():
    return render_template("knowledge.html", page="knowledge", title="AI Knowledge")


@pages.get("/activity")
@login_required
def activity():
    return render_template("activity.html", page="activity", title="Activity Log")


@pages.get("/history")
@login_required
def history():
    return redirect(url_for("pages.energy") + "#historical-data-section")


@pages.get("/admin")
@login_required
@admin_required
def admin():
    """Admin Control Center: Users, Permissions, Audit Verification Codes."""
    users = database.get_all_users()
    verification_codes = database.get_all_verification_codes(limit=50)

    kpis = {
        "total_users": len(users),
        "admin_count": sum(1 for u in users if u.get("role") == "admin"),
        "manager_count": sum(1 for u in users if u.get("role") == "manager"),
        "analyst_count": sum(1 for u in users if u.get("role") == "analyst"),
        "verified_count": sum(1 for u in users if u.get("is_verified")),
        "active_count": sum(1 for u in users if u.get("is_active")),
        "codes_count": len(verification_codes),
    }

    return render_template(
        "admin.html",
        page="admin",
        title="Admin Control Center",
        users=users,
        verification_codes=verification_codes,
        kpis=kpis,
    )


@pages.get("/user")
@pages.get("/profile")
@login_required
def user_profile():
    """User Portal: Profile info and secure password update."""
    current_u = get_current_user()
    return render_template(
        "user.html",
        page="user",
        title="User Profile",
        user=current_u,
    )
