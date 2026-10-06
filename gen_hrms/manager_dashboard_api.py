import frappe
from frappe.utils import today


@frappe.whitelist()
def get_manager_dashboard(from_date=None, to_date=None):
    """
    Dashboard data ONLY for employees who are under the logged-in manager
    (via Employee Additional Manager child table).

    Every count is based on ToDo where owner = employee's user_id.
    from_date / to_date (YYYY-MM-DD) filter on ToDo.creation. Both optional.
    """
    current_user = frappe.session.user

    # ---------------------------------------------------------
    # 1. Team = employees jinke Additional Managers me current user hai
    # ---------------------------------------------------------
    team_ids = frappe.get_all(
        "Employee Additional Manager",
        filters={"manager_user": current_user, "parenttype": "Employee"},
        pluck="parent",
        distinct=True,
    )

    empty = {
        "summary": {
            "total_employees": 0,
            "total_tasks": 0,
            "open": 0,
            "closed": 0,
            "in_progress": 0,
            "cancelled": 0,
            "overdue": 0,
            "completion_rate": 0,
            "total_hours": 0,
            "idle_employees": 0,
        },
        "priority_summary": {"High": 0, "Medium": 0, "Low": 0},
        "employees": [],
    }

    if not team_ids:
        return empty

    employees = frappe.get_all(
        "Employee",
        filters={"name": ["in", team_ids], "status": "Active"},
        fields=[
            "name",
            "employee_name",
            "user_id",
            "image",
            "designation",
            "department",
            "company_email",
            "personal_email",
        ],
    )

    users = [e.user_id for e in employees if e.user_id]

    # ---------------------------------------------------------

    stats = {}

    if users:
        conditions = ["owner IN %(users)s"]
        params = {"users": tuple(users), "today": today()}

        if from_date:
            conditions.append("creation >= %(from_dt)s")
            params["from_dt"] = f"{from_date} 00:00:00"
        if to_date:
            conditions.append("creation <= %(to_dt)s")
            params["to_dt"] = f"{to_date} 23:59:59"

        rows = frappe.db.sql(
            f"""
            SELECT
                owner,
                COUNT(*) AS total,
                SUM(status = 'Open') AS open_count,
                SUM(status = 'Closed') AS closed_count,
                SUM(status = 'In Progress') AS in_progress_count,
                SUM(status = 'Cancelled') AS cancelled_count,
                SUM(
                    status = 'Open'
                    AND COALESCE(DATE(custom_deadline), `date`) IS NOT NULL
                    AND COALESCE(DATE(custom_deadline), `date`) < %(today)s
                ) AS overdue_count,
                SUM(priority = 'High') AS high_count,
                SUM(priority = 'Medium') AS medium_count,
                SUM(priority = 'Low') AS low_count,
                SUM(COALESCE(custom_duration, 0)) AS hours
            FROM `tabToDo`
            WHERE {" AND ".join(conditions)}
            GROUP BY owner
            """,
            params,
            as_dict=True,
        )
        stats = {r.owner: r for r in rows}

    # ---------------------------------------------------------

    result = []
    summary = dict(empty["summary"])
    priority_summary = {"High": 0, "Medium": 0, "Low": 0}

    for emp in employees:
        s = stats.get(emp.user_id)

        total = int(s.total) if s else 0
        open_c = int(s.open_count or 0) if s else 0
        closed_c = int(s.closed_count or 0) if s else 0
        in_progress_c = int(s.in_progress_count or 0) if s else 0
        cancelled_c = int(s.cancelled_count or 0) if s else 0
        overdue_c = int(s.overdue_count or 0) if s else 0
        high_c = int(s.high_count or 0) if s else 0
        medium_c = int(s.medium_count or 0) if s else 0
        low_c = int(s.low_count or 0) if s else 0
        hours = float(s.hours or 0) if s else 0.0

        rate = round((closed_c / total) * 100) if total else 0

        result.append(
            {
                "employee_id": emp.name,
                "employee_name": emp.employee_name,
                "user_id": emp.user_id,
                "profile_photo": emp.image,
                "designation": emp.designation or "",
                "department": emp.department or "",
                "email": emp.company_email or emp.personal_email or emp.user_id,
                "total": total,
                "open": open_c,
                "closed": closed_c,
                "in_progress": in_progress_c,
                "cancelled": cancelled_c,
                "overdue": overdue_c,
                "high": high_c,
                "medium": medium_c,
                "low": low_c,
                "hours": round(hours, 2),
                "completion_rate": rate,
            }
        )

        summary["total_tasks"] += total
        summary["open"] += open_c
        summary["closed"] += closed_c
        summary["in_progress"] += in_progress_c
        summary["cancelled"] += cancelled_c
        summary["overdue"] += overdue_c
        summary["total_hours"] += hours
        if total == 0:
            summary["idle_employees"] += 1

        priority_summary["High"] += high_c
        priority_summary["Medium"] += medium_c
        priority_summary["Low"] += low_c

    summary["total_employees"] = len(result)
    summary["total_hours"] = round(summary["total_hours"], 2)
    summary["completion_rate"] = (
        round((summary["closed"] / summary["total_tasks"]) * 100)
        if summary["total_tasks"]
        else 0
    )

    return {
        "summary": summary,
        "priority_summary": priority_summary,
        "employees": result,
    }
