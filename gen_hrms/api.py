import frappe


@frappe.whitelist(allow_guest=True)
def create_public_ticket(
    subject,
    email,
    summary,
    ticket_type=None,
    priority=None
):
    if not subject:
        frappe.throw("Subject is required")

    if not email:
        frappe.throw("Email is required")

    if not summary:
        frappe.throw("Summary is required")

    ticket_data = {
        "doctype": "HD Ticket",
        "subject": subject,
        "raised_by": email,
        "summary": summary,
	"custom_project": custom_project,
    }

    if ticket_type:
        ticket_data["ticket_type"] = ticket_type

    if priority:
        ticket_data["priority"] = priority

    ticket = frappe.get_doc(ticket_data)

    ticket.insert(ignore_permissions=True)

    return {
        "success": True,
        "ticket": ticket.name
    }
