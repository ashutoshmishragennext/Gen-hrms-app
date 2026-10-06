import frappe


@frappe.whitelist()
def get_employees_reporting_to_manager(user_id):
    if not user_id:
        frappe.throw("user_id is required")

    employees = frappe.get_all(
        "Employee Additional Manager",
        filters={
            "manager_user": user_id,
            "parenttype": "Employee"
        },
        fields=["parent as employee_id"],
        distinct=True
    )

    result = []

    for row in employees:
        employee = frappe.db.get_value(
            "Employee",
            row.employee_id,
            ["name", "employee_name", "user_id", "image"],
            as_dict=True
        )

        if not employee:
            continue

        # Default counts
        open_count = 0
        closed_count = 0
        total_count = 0

        # Count ToDos created by this employee/user
        if employee.user_id:
            todo_counts = frappe.db.sql(
                """
                SELECT
                    status,
                    COUNT(*) as count
                FROM `tabToDo`
                WHERE owner = %s
                GROUP BY status
                """,
                (employee.user_id,),
                as_dict=True
            )

            for todo in todo_counts:
                status = todo.status
                count = int(todo.count)

                total_count += count

                if status == "Open":
                    open_count += count
                elif status == "Closed":
                    closed_count += count

        result.append({
            "employee_id": employee.name,
            "employee_name": employee.employee_name,
            "user_id": employee.user_id,
            "profile_photo": employee.image,

            "todos": {
                "total": total_count,
                "open": open_count,
                "closed": closed_count
            }
        })

    return result

@frappe.whitelist()
def create_employee_todo(
    employee,
    date=None,
    custom_task_name=None,
    description=None,
    priority=None,
    status=None,
    custom_duration=None,
    custom_remarkschallenges=None,
    custom_schdeuled_date=None,
    custom_schdeuled_time=None,
    custom_repeat=None,
    custom_show_before=None,
    custom_repeat_on=None,
    custom_day_of_month=None,
    custom_month=None,
    custom_day=None,
    custom_start_date=None,
    custom_due_time=None,
    custom_deadline=None,
    custom_interval=None,
    custom_end_type=None,
    custom_end_date=None,
    custom_occurrences=None,
    custom_week_of_month=None,
    custom_day_of_week=None,
    custom_repeat_days=None,
):
    if not employee:
        frappe.throw("employee is required")

    current_user = frappe.session.user

    # Check that current user is one of the managers
    # of the selected employee through Employee Additional Manager.
    manager_row = frappe.db.exists(
        "Employee Additional Manager",
        {
            "parent": employee,
            "parenttype": "Employee",
            "manager_user": current_user,
        }
    )

    if not manager_row:
        frappe.throw("You are not authorized to create a task for this employee.")

    employee_user = frappe.db.get_value("Employee", employee, "user_id")

    if not employee_user:
        frappe.throw("Selected employee does not have a user account.")

    # ---------------------------------------------------------
    # Build the ToDo document
    # ---------------------------------------------------------
    manager_emp_name = frappe.db.get_value(
        "Employee",
        {"user_id": current_user},
        "employee_name",
    )

    todo_dict = {
        "doctype": "ToDo",
        "date": date or "",
        "custom_task_name": custom_task_name or "",
        "description": description or "",
        "priority": priority or "Medium",
        "status": status or "Open",
        "custom_duration": float(custom_duration or 0),
        "custom_remarkschallenges": custom_remarkschallenges or "",
        "custom_schdeuled_date": custom_schdeuled_date or "",
        "custom_schdeuled_time": custom_schdeuled_time or "",
        "custom_repeat": custom_repeat or "Does Not Repeat",
        "custom_show_before": custom_show_before or "0",
        "custom_repeat_on": custom_repeat_on or "",
        "custom_day_of_month": int(custom_day_of_month or 0),
        "custom_month": custom_month or "",
        "custom_day": int(custom_day or 0),
        "custom_deadline": custom_deadline or None,
        "custom_interval": int(custom_interval or 1),
        "custom_end_type": custom_end_type or "never",
        "custom_end_date": custom_end_date or "",
        "custom_occurrences": int(custom_occurrences or 0),
        "custom_week_of_month": custom_week_of_month or "",
        "custom_day_of_week": custom_day_of_week or "",
	"custom_created_by": manager_emp_name or current_user,
    }

    if custom_repeat_days:
        import json as _json
        if isinstance(custom_repeat_days, str):
            try:
                custom_repeat_days = _json.loads(custom_repeat_days)
            except Exception:
                custom_repeat_days = []

        if isinstance(custom_repeat_days, list):
            todo_dict["custom_repeat_days"] = [
                {"day": row.get("day") if isinstance(row, dict) else row}
                for row in custom_repeat_days
                if row
            ]

    # Only set optional fields if they exist on the doctype
    if custom_start_date is not None:
        todo_dict["custom_start_date"] = custom_start_date

    if custom_due_time is not None:
        todo_dict["custom_due_time"] = custom_due_time

    todo = frappe.get_doc(todo_dict)

    todo.insert(ignore_permissions=True)

    # Frappe sets Owner to the logged-in user.
    # Make the selected employee the actual ToDo owner.
    frappe.db.set_value(
        "ToDo",
        todo.name,
        "owner",
        employee_user,
        update_modified=False,
    )

    frappe.db.commit()
    todo.reload()

    return {
        "success": True,
        "message": "Task created successfully.",
        "data": todo.as_dict(),
    }

@frappe.whitelist()
def update_employee_todo(
    name,
    employee,
    date=None,
    custom_task_name=None,
    description=None,
    priority=None,
    status=None,
    custom_duration=None,
    custom_remarkschallenges=None,
    custom_schdeuled_date=None,
    custom_schdeuled_time=None,
    custom_repeat=None,
    custom_show_before=None,
    custom_repeat_on=None,
    custom_day_of_month=None,
    custom_month=None,
    custom_day=None,
    custom_start_date=None,
    custom_due_time=None,
    custom_interval=None,
    custom_end_type=None,
    custom_end_date=None,
    custom_occurrences=None,
    custom_week_of_month=None,
    custom_day_of_week=None,
    custom_repeat_days=None,
	custom_deadline=None,
):
    if not name:
        frappe.throw("name is required")

    if not employee:
        frappe.throw("employee is required")

    current_user = frappe.session.user

    # ---------------------------------------------------------
    # Verify logged-in manager has access to this employee
    # through Employee Additional Manager
    # ---------------------------------------------------------

    manager_row = frappe.db.exists(
        "Employee Additional Manager",
        {
            "parent": employee,
            "parenttype": "Employee",
            "manager_user": current_user
        }
    )

    if not manager_row:
        frappe.throw(
            "You are not authorized to update a task for this employee."
        )

    # ---------------------------------------------------------
    # Load ToDo
    # ---------------------------------------------------------

    todo = frappe.get_doc("ToDo", name)

    # ---------------------------------------------------------
    # IMPORTANT:
    # Task must actually belong to the employee whose page
    # is currently open.
    # ---------------------------------------------------------

    employee_user = frappe.db.get_value(
        "Employee",
        employee,
        "user_id"
    )

    if not employee_user:
        frappe.throw(
            "Selected employee does not have a user account."
        )

    if todo.owner != employee_user:
        frappe.throw(
            "This task does not belong to the selected employee."
        )

    # ---------------------------------------------------------
    # Update normal fields
    # ---------------------------------------------------------

    if date is not None:
        todo.date = date

    if custom_task_name is not None:
        todo.custom_task_name = custom_task_name

    if description is not None:
        todo.description = description

    if priority is not None:
        todo.priority = priority

    if status is not None:
        todo.status = status

    if custom_duration is not None:
        todo.custom_duration = float(
            custom_duration or 0
        )

    if custom_remarkschallenges is not None:
        todo.custom_remarkschallenges = (
            custom_remarkschallenges
        )

    # ---------------------------------------------------------
    # Schedule fields
    # ---------------------------------------------------------

    if custom_schdeuled_date is not None:
        todo.custom_schdeuled_date = (
            custom_schdeuled_date
        )

    if custom_schdeuled_time is not None:
        todo.custom_schdeuled_time = (
            custom_schdeuled_time
        )

    if custom_repeat is not None:
        todo.custom_repeat = custom_repeat

    if custom_show_before is not None:
        todo.custom_show_before = (
            custom_show_before
        )

    if custom_repeat_on is not None:
        todo.custom_repeat_on = (
            custom_repeat_on
        )

    if custom_day_of_month is not None:
        todo.custom_day_of_month = (
            int(custom_day_of_month or 0)
        )

    if custom_month is not None:
        todo.custom_month = custom_month

    if custom_day is not None:
        todo.custom_day = int(
            custom_day or 0
        )


    if custom_interval is not None:
        todo.custom_interval = int(custom_interval or 1)

    if custom_end_type is not None:
        todo.custom_end_type = custom_end_type

    if custom_end_date is not None:
        todo.custom_end_date = custom_end_date

    if custom_occurrences is not None:
        todo.custom_occurrences = int(custom_occurrences or 0)

    if custom_week_of_month is not None:
        todo.custom_week_of_month = custom_week_of_month

    if custom_day_of_week is not None:
        todo.custom_day_of_week = custom_day_of_week

    # ✅ Child table custom_repeat_days ko replace karo
    if custom_repeat_days is not None:
        import json as _json
        if isinstance(custom_repeat_days, str):
            try:
                custom_repeat_days = _json.loads(custom_repeat_days)
            except Exception:
                custom_repeat_days = []

        if isinstance(custom_repeat_days, list):
            todo.set("custom_repeat_days", [])
            for row in custom_repeat_days:
                day_val = row.get("day") if isinstance(row, dict) else row
                if day_val:
                    todo.append("custom_repeat_days", {"day": day_val})

    # These fields are included because the schedule UI
    # can use them when configured in the ToDo DocType.

    if hasattr(todo, "custom_start_date"):
        if custom_start_date is not None:
            todo.custom_start_date = custom_start_date

    if hasattr(todo, "custom_due_time"):
        if custom_due_time is not None:
            todo.custom_due_time = custom_due_time

    if hasattr(todo, "custom_deadline"):
        if custom_deadline is not None:
            existing_deadline = str(todo.custom_deadline or "").strip()
            new_deadline = str(custom_deadline).strip()

            if existing_deadline and existing_deadline != new_deadline:
                current_user = frappe.session.user

                is_manager = frappe.db.exists(
                    "Employee Additional Manager",
                    {
                        "parent": employee,
                        "parenttype": "Employee",
                        "manager_user": current_user,
                    }
                )

                user_roles = frappe.get_roles(current_user)
                is_admin = (
                    "System Manager" in user_roles
                    or "Administrator" in user_roles
                    or current_user == "Administrator"
                )

                if not is_manager and not is_admin:
                    frappe.throw(
                        "Deadline has already been set and cannot be changed. "
                        "Please contact your manager."
                    )

            todo.custom_deadline = custom_deadline
    # ---------------------------------------------------------

    todo.save(ignore_permissions=True)

    frappe.db.commit()

    todo.reload()

    return {
        "success": True,
        "message": "Task updated successfully.",
        "data": todo.as_dict()
    }


@frappe.whitelist()
def add_employee_to_my_team(employee_id):
    if not employee_id:
        frappe.throw("employee_id is required")

    current_user = frappe.session.user

    # ---------------------------------------------------------
    # 1. Current user ka Employee record dhoondho
    # ---------------------------------------------------------

    manager_employee = frappe.db.get_value(
        "Employee",
        {"user_id": current_user, "status": "Active"},
        "name"
    )

    if not manager_employee:
        frappe.throw(
            "Your user is not linked to any active Employee record."
        )

    # ---------------------------------------------------------
    # 2. Admin ya Manager check
    # ---------------------------------------------------------

    user_roles = frappe.get_roles(current_user)
    is_admin = (
        "System Manager" in user_roles
        or "Administrator" in user_roles
        or current_user == "Administrator"
    )

    if not is_admin:
        employee_type = frappe.db.get_value(
            "Employee", manager_employee, "employee_type"
        )
        if employee_type != "Manager":
            frappe.throw(
                "Only Managers and Admins can add employees to their team."
            )

    # ---------------------------------------------------------
    # 3. Target employee exist check
    # ---------------------------------------------------------

    if not frappe.db.exists("Employee", employee_id):
        frappe.throw(f"Employee {employee_id} does not exist.")

    if employee_id == manager_employee:
        frappe.throw("You cannot add yourself under yourself.")

    # ---------------------------------------------------------
    # 4. Employee load karo
    # ---------------------------------------------------------

    employee = frappe.get_doc("Employee", employee_id)

    # ---------------------------------------------------------
    # 5. Duplicate check — already under me?
    # ---------------------------------------------------------

    for row in (employee.custom_additional_managers or []):
        if row.manager_user == current_user:
            frappe.throw(
                f"Employee {employee_id} is already under you."
            )

    # ---------------------------------------------------------
    # 6. Naya row append karo (purana nahi hatega)
    # ---------------------------------------------------------

    employee.append("custom_additional_managers", {
        "manager": manager_employee,
        "manager_user": current_user,
    })

    employee.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True,
        "message": f"Employee {employee_id} added under you.",
        "employee_id": employee_id,
        "manager": manager_employee,
        "manager_user": current_user,
    }



@frappe.whitelist()
def get_available_employees():
    """
    Current manager ke under NA hone wale active employees return kare.
    """
    current_user = frappe.session.user

    # 1. Current user ka Employee
    my_employee = frappe.db.get_value(
        "Employee",
        {"user_id": current_user, "status": "Active"},
        "name"
    )

    all_employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=[
            "name",
            "user_id",
            "employee_name",
            "designation",
            "department",
            "status",
        ],
    )


    available = []

    for emp in all_employees:
        # Self exclude
        if emp.name == my_employee:
            continue

        # No user_id — skip
        if not emp.user_id:
            continue


        employee_doc = frappe.get_doc("Employee", emp.name)

        already_under_me = any(
            (row.manager_user == current_user)
            for row in (employee_doc.custom_additional_managers or [])
        )

        if already_under_me:
            continue

        available.append({
            "employee_id": emp.name,
            "employee_name": emp.employee_name,
            "user_id": emp.user_id,
            "designation": emp.designation or "",
            "department": emp.department or "",
        })

    return available



@frappe.whitelist()
def get_employee_todos(
    employee_id,
    status=None,
    priority=None,
    status_exclude=None,
    from_date=None,
    to_date=None,
    page=1,
    page_size=50,
):
    if not employee_id:
        frappe.throw("employee_id is required")

    employee_user = frappe.db.get_value("Employee", employee_id, "user_id")

    if not employee_user:
        frappe.throw(f"Employee {employee_id} does not have a user account.")

    filters = {"owner": employee_user}

    if status:
        filters["status"] = status

    if status_exclude:
        filters["status"] = ["!=", status_exclude]

    if priority:
        priority_list = [
            p.strip() for p in str(priority).split(",") if p.strip()
        ]
        if len(priority_list) == 1:
            filters["priority"] = priority_list[0]
        elif len(priority_list) > 1:
            filters["priority"] = ["in", priority_list]

    if from_date and to_date:
        filters["creation"] = [
            "between",
            [f"{from_date} 00:00:00", f"{to_date} 23:59:59"],
        ]
    elif from_date:
        filters["creation"] = [">=", f"{from_date} 00:00:00"]
    elif to_date:
        filters["creation"] = ["<=", f"{to_date} 23:59:59"]

    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = max(1, min(500, int(page_size or 50)))
    except (TypeError, ValueError):
        page_size = 50

    limit_start = (page - 1) * page_size

    total_count = frappe.db.count("ToDo", filters=filters)

    todos = frappe.get_all(
        "ToDo",
        filters=filters,
        fields=[
            "name", "owner", "creation", "modified", "modified_by",
            "status", "priority",
            "custom_notes", "custom_schdeuled_time", "custom_repeat_daily",
            "custom_task_name", "custom_teamdepartment", "custom_duration",
            "custom_remarkschallenges", "custom_reporting_manager",
            "custom_schdeuled_date",
            "custom_repeat", "custom_start_date", "custom_show_before",
            "custom_due_time", "custom_repeat_on", "custom_day_of_month",
            "custom_month", "custom_day",
		"custom_deadline",
            "date", "allocated_to", "description",
            "reference_type", "reference_name",
		"custom_created_by",
            "assigned_by", "assigned_by_full_name",
            "custom_interval",
            "custom_end_type",
            "custom_end_date",
            "custom_occurrences",
            "custom_week_of_month",
            "custom_day_of_week",
        ],
        order_by="date desc, creation desc",
        limit_start=limit_start,
        limit_page_length=page_size,
        ignore_permissions=True,
    )

    if todos:
        todo_names = [t["name"] for t in todos]
        placeholders = ", ".join(["%s"] * len(todo_names))

        child_rows = frappe.db.sql(
            f"""
            SELECT parent, day
            FROM `tabToDo Repeat Day`
            WHERE parent IN ({placeholders})
            ORDER BY parent, idx
            """,
            todo_names,
            as_dict=True,
        )

        days_map = {}
        for row in child_rows:
            days_map.setdefault(row["parent"], []).append({"day": row["day"]})

        for t in todos:
            t["custom_repeat_days"] = days_map.get(t["name"], [])
    total_pages = max(1, -(-total_count // page_size))

    current_user = frappe.session.user

    is_manager = bool(
        frappe.db.exists(
            "Employee Additional Manager",
            {
                "parent": employee_id,
                "parenttype": "Employee",
                "manager_user": current_user,
            }
        )
    )

    return {
        "data": todos,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
        "is_manager": is_manager,
    }
