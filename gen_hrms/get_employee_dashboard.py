import json

import frappe
from frappe.utils import today


def get_schedule_rows(snapshot):
    """
    Employee Schedule.snapshot (Univer workbook JSON) se
    "Work Details" aur "Time duration" columns nikalta hai.
    Return: [{"work": "...", "duration": "..."}]
    """
    if not snapshot:
        return []

    try:
        wb = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    except Exception:
        return []

    sheets = (wb or {}).get("sheets") or {}
    if not sheets:
        return []

    order = wb.get("sheetOrder") or list(sheets.keys())

    # Prefer the sheet named "Time Management", else the first sheet
    sheet = None
    for sid in order:
        sh = sheets.get(sid) or {}
        if "time management" in (sh.get("name") or "").lower():
            sheet = sh
            break
    if sheet is None:
        sheet = sheets.get(order[0]) or {}

    cells = sheet.get("cellData") or {}
    if not cells:
        return []

    def val(r, c):
        cell = (cells.get(str(r)) or {}).get(str(c)) or {}
        v = cell.get("v")
        return "" if v is None else str(v).strip()

    # Find the header row (Work Details / Time duration)
    header_row = work_col = time_col = None
    for r in sorted(int(k) for k in cells.keys()):
        wc = tc = None
        for c_key, cell in (cells.get(str(r)) or {}).items():
            text = str((cell or {}).get("v") or "").strip().lower()
            if text == "work details":
                wc = int(c_key)
            elif text == "time duration":
                tc = int(c_key)
        if wc is not None:
            header_row, work_col, time_col = r, wc, tc
            break

    if header_row is None:
        return []

    rows = []
    last_row = max(int(k) for k in cells.keys())
    for r in range(header_row + 1, last_row + 1):
        work = val(r, work_col)
        if not work or work.lower() == "total":
            continue
        duration = val(r, time_col) if time_col is not None else ""
        rows.append({"work": work, "duration": duration})

    return rows


def get_team_schedules(employee_ids):
    """Latest Employee Schedule per employee -> {employee_id: [rows]}"""
    if not employee_ids:
        return {}

    docs = frappe.get_all(
        "Employee Schedule",
        filters={"employee": ["in", employee_ids]},
        fields=["employee", "snapshot", "modified"],
        order_by="modified desc",
        limit_page_length=0,
    )

    result = {}
    for d in docs:
        if d.employee in result:  # newest comes first, skip older ones
            continue
        result[d.employee] = get_schedule_rows(d.snapshot)
    return result


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
    # 1. Team = employees who have the current user as an additional manager
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
    schedule_map = get_team_schedules([e.name for e in employees])

    # ---------------------------------------------------------
    # 2. ToDo stats for all team members in a single query
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
    # 3. Per-employee result + team summary
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
                "schedule": schedule_map.get(emp.name, []),
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
