# your_app/api/auth.py
import frappe
from frappe.utils import random_string, get_url

@frappe.whitelist(allow_guest=True)
def request_password_reset(email):
    user = frappe.db.get_value("User", {"email": email, "enabled": 1}, "name")
    if not user:
        # same response de, taaki email enumeration na ho
        return {"message": "If the email exists, a reset link was sent."}

    doc = frappe.get_doc("User", user)
    key = random_string(32)
    doc.db_set("reset_password_key", frappe.utils.password.get_hashed_password(key) if False else key)
    doc.db_set("last_reset_password_key_generated_on", frappe.utils.now_datetime())

    link = f"https://merapath-hrms-frontend-qxqb.vercel.app/auth/reset-password?key={key}"
    frappe.sendmail(
        recipients=[doc.email],
        subject="Reset your password",
        message=f'<p>Click <a href="{link}">here</a> to reset your password.</p>',
        now=True,
    )
    return {"message": "If the email exists, a reset link was sent."}


@frappe.whitelist(allow_guest=True)
def reset_password_with_key(key, new_password):
    from frappe.utils.password import update_password

    user = frappe.db.get_value("User", {"reset_password_key": key}, "name")
    if not user:
        frappe.throw("Invalid or expired link", frappe.AuthenticationError)

    update_password(user, new_password)
    frappe.db.set_value("User", user, "reset_password_key", "")
    return {"message": "Password updated"}
