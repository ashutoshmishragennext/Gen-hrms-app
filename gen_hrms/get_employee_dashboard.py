import json

import frappe
from frappe.utils import get_first_day, get_last_day, nowdate, getdate


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


def _get_employee_schedule(employee_id):
    """Rows from the employee's most recently modified Employee Schedule."""
    docs = frappe.get_all(
        "Employee Schedule",
        filters={"employee": employee_id},
        fields=["snapshot"],
        order_by="modified desc",
        limit_page_length=1,
    )
    if not docs:
        return []
    return get_schedule_rows(docs[0].snapshot)


def _fmt_duration(seconds):
    """custom_duration is a Frappe Duration field -> stored in seconds."""
    seconds = float(seconds or 0)
    if seconds <= 0:
        return "—"
    hours = seconds / 3600
    text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return f"{text}h"


def _map_priority(p):
    p = (p or "").strip()
    if p == "High":
        return {"label": "High", "tone": "red"}
    if p == "Low":
        return {"label": "Low", "tone": "gray"}
    return {"label": "Normal", "tone": "blue"}


@frappe.whitelist()
def get_employee_dashboard(employee_id=None, from_date=None, to_date=None):
    current_user = frappe.session.user

    # ---------------------------------------------------------
    # 1. Find the employee (default: logged-in user)
    # ---------------------------------------------------------
    if not employee_id:
        employee_id = frappe.db.get_value(
            "Employee",
            {"user_id": current_user, "status": "Active"},
            "name",
        )

    if not employee_id:
        frappe.throw("No active Employee record linked to your user.")

    employee = frappe.db.get_value(
        "Employee",
        employee_id,
        ["name", "employee_name", "user_id", "image", "designation", "department"],
        as_dict=True,
    )

    if not employee:
        frappe.throw(f"Employee {employee_id} not found.")

    employee_user = employee.user_id
    if not employee_user:
        frappe.throw("Employee does not have a linked user account.")

    # ---------------------------------------------------------
    # 2. Permission: self / the employee's manager / admin
    # ---------------------------------------------------------
    is_self = employee_user == current_user
    is_manager = bool(
        frappe.db.exists(
            "Employee Additional Manager",
            {
                "parent": employee_id,
                "parenttype": "Employee",
                "manager_user": current_user,
            },
        )
    )
    roles = frappe.get_roles(current_user)
    is_admin = (
        current_user == "Administrator"
        or "System Manager" in roles
        or "Administrator" in roles
    )

    if not (is_self or is_manager or is_admin):
        frappe.throw(
            "You are not allowed to view this employee's dashboard.",
            frappe.PermissionError,
        )

    # ---------------------------------------------------------
    # 3. Date range (filters on ToDo.creation)
    # ---------------------------------------------------------
    today = getdate(nowdate())

    from_date = getdate(from_date) if from_date else get_first_day(today)
    to_date = getdate(to_date) if to_date else get_last_day(today)

    creation_range = [
        "between",
        [f"{from_date} 00:00:00", f"{to_date} 23:59:59"],
    ]

    todos = frappe.get_all(
        "ToDo",
        filters={"owner": employee_user, "creation": creation_range},
        fields=[
            "name", "status", "priority", "date",
            "custom_task_name", "custom_duration",
            "custom_teamdepartment", "custom_deadline",
            "custom_schdeuled_date", "description",
        ],
        order_by="date desc, creation desc",
        limit_page_length=0,  # fetch all tasks so counts stay accurate
        ignore_permissions=True,
    )

    def due_date(t):
        """Use the deadline if present, otherwise the task date."""
        if t.custom_deadline:
            return getdate(t.custom_deadline)
        if t.date:
            return getdate(t.date)
        return None

    tasks = []
    total_count = closed_count = open_count = 0
    in_progress_count = cancelled_count = overdue_count = 0
    high_count = medium_count = low_count = 0
    on_time_closed = 0
    total_hours_sec = 0.0

    for t in todos:
        total_count += 1
        status = t.status or "Open"

        if t.priority == "High":
            high_count += 1
        elif t.priority == "Medium":
            medium_count += 1
        elif t.priority == "Low":
            low_count += 1

        if status == "Closed":
            closed_count += 1
            if t.custom_deadline and t.date:
                if getdate(t.date) <= getdate(t.custom_deadline):
                    on_time_closed += 1
        elif status == "Cancelled":
            cancelled_count += 1
        elif status == "In Progress":
            in_progress_count += 1
        elif status == "Open":
            open_count += 1

        if status in ("Open", "In Progress"):
            d = due_date(t)
            if d and d < today:
                overdue_count += 1

        total_hours_sec += float(t.custom_duration or 0)
        pr = _map_priority(t.priority)

        tasks.append({
            "name": t.name,
            "title": t.custom_task_name or "Untitled Task",
            "priority": t.priority or "Medium",
            "status": status,
            "duration": _fmt_duration(t.custom_duration),
            "date": str(t.date) if t.date else "",
            "deadline": str(t.custom_deadline) if t.custom_deadline else "",
            "department": t.custom_teamdepartment or "",
            "description": t.description or "",
            "label": pr["label"],
            "tone": pr["tone"],
            "done": status == "Closed",
        })

    completion_rate = round((closed_count / total_count) * 100, 1) if total_count else 0
    on_time_rate = round((on_time_closed / closed_count) * 100, 1) if closed_count else 0

    # ---------------------------------------------------------
    # 4. Today's tasks (independent of the date filter)
    # ---------------------------------------------------------
    today_todos = frappe.get_all(
        "ToDo",
        filters={"owner": employee_user, "date": str(today)},
        fields=["status", "custom_deadline"],
        limit_page_length=0,
        ignore_permissions=True,
    )

    today_total = len(today_todos)
    today_closed = today_open = today_blocked = 0

    for t in today_todos:
        status = t.status or "Open"
        if status == "Closed":
            today_closed += 1
        elif status in ("Open", "In Progress"):
            if t.custom_deadline and getdate(t.custom_deadline) < today:
                today_blocked += 1
            else:
                today_open += 1

    # ---------------------------------------------------------
    # 5. Team average (for the score's volume factor)
    # ---------------------------------------------------------
    team_avg = 0
    team_ids = frappe.get_all(
        "Employee Additional Manager",
        filters={"manager_user": current_user, "parenttype": "Employee"},
        pluck="parent",
        distinct=True,
    )
    if team_ids:
        team_users = [
            u for u in frappe.get_all(
                "Employee", filters={"name": ["in", team_ids]}, pluck="user_id"
            ) if u
        ]
        if team_users:
            row = frappe.db.sql(
                """
                SELECT AVG(cnt) AS avg_cnt FROM (
                    SELECT owner, COUNT(*) AS cnt
                    FROM `tabToDo`
                    WHERE owner IN %(users)s
                      AND creation BETWEEN %(f)s AND %(t)s
                    GROUP BY owner
                ) x
                """,
                {
                    "users": tuple(team_users),
                    "f": f"{from_date} 00:00:00",
                    "t": f"{to_date} 23:59:59",
                },
                as_dict=True,
            )
            team_avg = float(row[0].avg_cnt) if row and row[0].avg_cnt else 0

    volume_factor = min(total_count / team_avg, 1.5) * 100 if team_avg > 0 else 100

    score = round(
        (completion_rate * 0.60) + (on_time_rate * 0.25) + (volume_factor * 0.15)
    )
    score = int(min(score, 100))

    if score >= 90:
        tier = "A+"
    elif score >= 80:
        tier = "A"
    elif score >= 70:
        tier = "B"
    elif score >= 60:
        tier = "C"
    elif score >= 50:
        tier = "D"
    else:
        tier = "E"

    schedule = _get_employee_schedule(employee_id)

    return {
        "user": {
            "name": employee.employee_name,
            "image": employee.image,
            "designation": employee.designation or "",
            "department": employee.department or "",
            "date": today.strftime("%a, %d %b %Y"),
        },
        "stats": {
            "planned": today_total,
            "completed": today_closed,
            "inProgress": today_open,
            "blocked": today_blocked,
            "score": score,
            "tier": tier,
            "total": total_count,
            "open": open_count,
            "in_progress": in_progress_count,
            "closed": closed_count,
            "overdue": overdue_count,
            "cancelled": cancelled_count,
            "completion_rate": completion_rate,
            "on_time_rate": on_time_rate,
            "total_hours": round(total_hours_sec / 3600, 2),
        },
        "priority_summary": {
            "High": high_count,
            "Medium": medium_count,
            "Low": low_count,
        },
        "tasks": tasks,
        "schedule": schedule,
    }
