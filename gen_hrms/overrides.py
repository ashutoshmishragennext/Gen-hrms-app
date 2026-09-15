import frappe

_original_sendmail = frappe.sendmail

def _guarded_sendmail(*args, **kwargs):
    if getattr(frappe.local, "custom_mail_allowed", False):
        return _original_sendmail(*args, **kwargs)
    frappe.logger("email_control").info(
        f"BLOCKED email — subject: {kwargs.get('subject')}, "
        f"recipients: {kwargs.get('recipients')}"
    )
    return None

def apply_email_override():
    frappe.sendmail = _guarded_sendmail

