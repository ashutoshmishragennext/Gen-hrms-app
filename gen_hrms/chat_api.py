import frappe
from frappe import _
from frappe.utils import now_datetime, cint


# ============================================================
# HELPERS
# ============================================================

def get_current_user():
    user = frappe.session.user

    if not user or user == "Guest":
        frappe.throw(
            _("Login required"),
            frappe.PermissionError
        )

    return user


def ensure_participant(conversation, user=None):
    """
    Ensure the current user is a participant of the conversation.
    """
    user = user or get_current_user()

    exists = frappe.db.exists(
        "Chat Participant",
        {
            "parent": conversation,
            "parenttype": "Chat Conversation",
            "user": user,
        },
    )

    if not exists:
        frappe.throw(
            _("You are not a participant of this conversation"),
            frappe.PermissionError,
        )

    return True


def get_participants(conversation):
    return frappe.get_all(
        "Chat Participant",
        filters={
            "parent": conversation,
            "parenttype": "Chat Conversation",
        },
        fields=[
            "user",
            "joined_at",
            "last_read_at",
            "is_admin",
        ],
    )


def publish_to_participants(conversation, event, message, exclude_user=None):
    """
    Publish a realtime event to every participant of a conversation.
    """
    participants = get_participants(conversation)

    for participant in participants:
        user = participant.user

        if exclude_user and user == exclude_user:
            continue

        frappe.publish_realtime(
            event,
            message=message,
            user=user,
        )


def get_message_payload(message):
    """
    Convert Chat Message document into a frontend-friendly object.
    """
    return {
        "name": message.name,
        "conversation": message.conversation,
        "sender": message.sender,
        "message_type": message.message_type,
        "content": message.content,
        "attachment": message.attachment,
        "reply_to": message.reply_to,
        "is_edited": message.is_edited,
        "edited_at": message.edited_at,
        "is_deleted": message.is_deleted,
        "deleted_at": message.deleted_at,
        "creation": message.creation,
        "modified": message.modified,
    }


# ============================================================
# CONVERSATIONS
# ============================================================

@frappe.whitelist()
def create_direct_conversation(user):
    """
    Create or return an existing 1-to-1 conversation.
    """

    current_user = get_current_user()

    if not user:
        frappe.throw(_("User is required"))

    if current_user == user:
        frappe.throw(_("You cannot create a conversation with yourself"))

    if not frappe.db.exists("User", user):
        frappe.throw(_("User does not exist"))

    # Check existing direct conversation
    existing = frappe.db.sql(
        """
        SELECT cc.name
        FROM `tabChat Conversation` cc

        INNER JOIN `tabChat Participant` cp1
            ON cp1.parent = cc.name
            AND cp1.parenttype = 'Chat Conversation'

        INNER JOIN `tabChat Participant` cp2
            ON cp2.parent = cc.name
            AND cp2.parenttype = 'Chat Conversation'

        WHERE cc.conversation_type = 'Direct'
          AND cp1.user = %s
          AND cp2.user = %s

        LIMIT 1
        """,
        (current_user, user),
        as_dict=True,
    )

    if existing:
        return {
            "conversation": existing[0].name,
            "created": False,
        }

    now = now_datetime()

    conversation = frappe.new_doc("Chat Conversation")

    conversation.conversation_type = "Direct"
    conversation.created_by = current_user
    conversation.title = ""

    conversation.append(
        "participants",
        {
            "user": current_user,
            "joined_at": now,
            "is_admin": 0,
        },
    )

    conversation.append(
        "participants",
        {
            "user": user,
            "joined_at": now,
            "is_admin": 0,
        },
    )

    conversation.insert()

    return {
        "conversation": conversation.name,
        "created": True,
    }

@frappe.whitelist()
def get_conversations():
    """
    Get conversations for the logged-in user.
    """

    current_user = get_current_user()

    conversations = frappe.db.sql(
        """
        SELECT
            cc.name,
            cc.conversation_type,
            cc.title,
            cc.avatar,
            cc.last_message,
            cc.last_message_at,
            cc.is_archived,
            cc.is_muted,
            cc.creation,
            cc.modified

        FROM `tabChat Conversation` cc

        INNER JOIN `tabChat Participant` cp
            ON cp.parent = cc.name
            AND cp.parenttype = 'Chat Conversation'

        WHERE cp.user = %s

        ORDER BY
            COALESCE(cc.last_message_at, cc.creation) DESC
        """,
        current_user,
        as_dict=True,
    )

    for conversation in conversations:

        # Get all participants
        participants = get_participants(
            conversation.name
        )

        conversation["participants"] = participants
        me = next(
            (p for p in participants if p["user"] == current_user),
            None,
        )

        count_filters = {
            "conversation": conversation.name,
            "sender": ["!=", current_user],
            "is_deleted": 0,
        }

        if me and me.get("last_read_at"):
            count_filters["creation"] = [">", me["last_read_at"]]

        conversation["unread_count"] = frappe.db.count(
            "Chat Message", count_filters
        )
        # --------------------------------------------------
        # Direct conversation
        # --------------------------------------------------

        if conversation["conversation_type"] == "Direct":

            # Find the other participant
            other_user = next(
                (
                    p["user"]
                    for p in participants
                    if p["user"] != current_user
                ),
                None,
            )

            if other_user:

                # Get user's details
                user_details = frappe.db.get_value(
                    "User",
                    other_user,
                    [
                        "name",
                        "full_name",
                        "user_image",
                    ],
                    as_dict=True,
                )

                # Return frontend-friendly structure
                conversation["other_user"] = {
                    "name": other_user,
                    "full_name": (
                        user_details.full_name
                        if user_details
                        else other_user
                    ),
                    "user_image": (
                        user_details.user_image
                        if user_details
                        else None
                    ),
                }

            else:
                conversation["other_user"] = None

        # --------------------------------------------------
        # Group conversation
        # --------------------------------------------------

        else:
            conversation["other_user"] = None

    return conversations
#=======================================
# MESSAGES
# ============================================================

@frappe.whitelist()
def get_messages(
    conversation,
    limit=50,
    before=None,
):
    """
    Get paginated messages.

    `before` should be a message creation timestamp.
    """

    current_user = get_current_user()

    ensure_participant(
        conversation,
        current_user,
    )

    limit = min(
        max(cint(limit), 1),
        100,
    )

    filters = {
        "conversation": conversation,
    }

    if before:
        filters["creation"] = ["<", before]

    messages = frappe.get_all(
        "Chat Message",
        filters=filters,
        fields=[
            "name",
            "conversation",
            "sender",
            "message_type",
            "content",
            "attachment",
            "reply_to",
            "is_edited",
            "edited_at",
            "is_deleted",
            "deleted_at",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        limit_page_length=limit,
    )

    # Return oldest → newest to frontend
    messages.reverse()

    return messages


@frappe.whitelist()
def send_message(
    conversation,
    message_type,
    content=None,
    attachment=None,
    reply_to=None,
):
    """
    Send a new chat message.
    """

    current_user = get_current_user()

    ensure_participant(
        conversation,
        current_user,
    )

    allowed_types = {
        "Text",
        "Image",
        "File",
        "Audio",
        "Video",
        "System",
    }

    if message_type not in allowed_types:
        frappe.throw(
            _("Invalid message type")
        )

    # Text message requires content
    if message_type == "Text" and not content:
        frappe.throw(
            _("Message content is required")
        )

    # Media message requires attachment
    if message_type in {
        "Image",
        "File",
        "Audio",
        "Video",
    } and not attachment:
        frappe.throw(
            _("Attachment is required for this message type")
        )

    # Validate reply target
    if reply_to:

        reply_exists = frappe.db.exists(
            "Chat Message",
            {
                "name": reply_to,
                "conversation": conversation,
            },
        )

        if not reply_exists:
            frappe.throw(
                _("Invalid reply message")
            )

    message = frappe.new_doc("Chat Message")

    message.conversation = conversation
    message.sender = current_user
    message.message_type = message_type
    message.content = content
    message.attachment = attachment
    message.reply_to = reply_to

    message.is_edited = 0
    message.is_deleted = 0

    message.insert()

    # Update conversation preview
    conversation_doc = frappe.get_doc(
        "Chat Conversation",
        conversation,
    )

    if message_type == "Text":
        conversation_doc.last_message = content
    elif message_type == "Image":
        conversation_doc.last_message = "📷 Image"
    elif message_type == "Video":
        conversation_doc.last_message = "🎥 Video"
    elif message_type == "Audio":
        conversation_doc.last_message = "🎵 Audio"
    elif message_type == "File":
        conversation_doc.last_message = "📎 File"
    else:
        conversation_doc.last_message = content or ""

    conversation_doc.last_message_at = message.creation

    conversation_doc.save(
        ignore_permissions=True
    )

    payload = get_message_payload(message)

    # Send realtime event to all participants
    publish_to_participants(
        conversation=conversation,
        event="chat_message_created",
        message=payload,
    )

    return payload


# ============================================================
# READ RECEIPTS
# ============================================================

@frappe.whitelist()
def mark_message_read(
    conversation,
    message,
):
    """
    Mark a message as read by the current user.
    """

    current_user = get_current_user()

    ensure_participant(
        conversation,
        current_user,
    )

    message_doc = frappe.db.get_value(
        "Chat Message",
        message,
        [
            "name",
            "conversation",
            "sender",
            "creation",
        ],
        as_dict=True,
    )

    if not message_doc:
        frappe.throw(
            _("Message does not exist")
        )

    if message_doc.conversation != conversation:
        frappe.throw(
            _("Message does not belong to this conversation")
        )

    # Don't create read receipt for your own message
    if message_doc.sender == current_user:
        return {
            "success": True,
            "created": False,
        }

    existing = frappe.db.exists(
        "Chat Message Read",
        {
            "message": message,
            "user": current_user,
        },
    )

    read_at = now_datetime()

    if existing:

        frappe.db.set_value(
            "Chat Message Read",
            existing,
            "read_at",
            read_at,
        )

    else:

        read_doc = frappe.new_doc(
            "Chat Message Read"
        )

        read_doc.message = message
        read_doc.user = current_user
        read_doc.read_at = read_at

        read_doc.insert()

    # Update participant last-read timestamp
    participant = frappe.db.exists(
        "Chat Participant",
        {
            "parent": conversation,
            "parenttype": "Chat Conversation",
            "user": current_user,
        },
    )

    if participant:

        frappe.db.set_value(
            "Chat Participant",
            participant,
            "last_read_at",
            read_at,
        )

    payload = {
        "conversation": conversation,
        "message": message,
        "user": current_user,
        "read_at": read_at,
    }

    # Tell all other participants
    publish_to_participants(
        conversation=conversation,
        event="chat_message_read",
        message=payload,
        exclude_user=current_user,
    )

    return {
        "success": True,
        "created": not bool(existing),
        "read_at": read_at,
    }


# ============================================================
# EDIT MESSAGE
# ============================================================

@frappe.whitelist()
def edit_message(
    message,
    content,
):
    """
    Edit a message sent by the current user.
    """

    current_user = get_current_user()

    if not content:
        frappe.throw(
            _("Message content is required")
        )

    message_doc = frappe.get_doc(
        "Chat Message",
        message,
    )

    ensure_participant(
        message_doc.conversation,
        current_user,
    )

    if message_doc.sender != current_user:
        frappe.throw(
            _("You can only edit your own messages"),
            frappe.PermissionError,
        )

    if message_doc.is_deleted:
        frappe.throw(
            _("Deleted messages cannot be edited")
        )

    if message_doc.message_type != "Text":
        frappe.throw(
            _("Only text messages can be edited")
        )

    message_doc.content = content
    message_doc.is_edited = 1
    message_doc.edited_at = now_datetime()

    message_doc.save(
        ignore_permissions=True
    )

    payload = get_message_payload(
        message_doc
    )

    publish_to_participants(
        conversation=message_doc.conversation,
        event="chat_message_edited",
        message=payload,
    )

    return payload


# ============================================================
# DELETE MESSAGE
# ============================================================

@frappe.whitelist()
def delete_message(message):
    """
    Soft-delete a message.
    """

    current_user = get_current_user()

    message_doc = frappe.get_doc(
        "Chat Message",
        message,
    )

    ensure_participant(
        message_doc.conversation,
        current_user,
    )

    if message_doc.sender != current_user:
        frappe.throw(
            _("You can only delete your own messages"),
            frappe.PermissionError,
        )

    if message_doc.is_deleted:
        return {
            "success": True,
            "already_deleted": True,
        }

    message_doc.is_deleted = 1
    message_doc.deleted_at = now_datetime()

    message_doc.content = None
    message_doc.attachment = None

    message_doc.save(
        ignore_permissions=True
    )

    payload = {
        "name": message_doc.name,
        "conversation": message_doc.conversation,
        "sender": message_doc.sender,
        "is_deleted": True,
        "deleted_at": message_doc.deleted_at,
    }

    publish_to_participants(
        conversation=message_doc.conversation,
        event="chat_message_deleted",
        message=payload,
    )

    return {
        "success": True,
        "message": message_doc.name,
    }



@frappe.whitelist()
def mark_conversation_read(conversation):
    current_user = get_current_user()
    ensure_participant(conversation, current_user)

    read_at = now_datetime()

    participant = frappe.db.get_value(
        "Chat Participant",
        {
            "parent": conversation,
            "parenttype": "Chat Conversation",
            "user": current_user,
        },
        "name",
    )

    frappe.db.set_value("Chat Participant", participant, "last_read_at", read_at)

    publish_to_participants(
        conversation=conversation,
        event="chat_conversation_read",
        message={
            "conversation": conversation,
            "user": current_user,
            "read_at": str(read_at),
        },
        exclude_user=current_user,
    )

    return {"success": True, "read_at": str(read_at)}
