"""
plugins/text_router.py — Single private-text dispatcher.

Runs in handler group 1 (all commands are group 0) so it can never
interfere with command routing regardless of filter logic.
"""
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


@Client.on_message(filters.text & filters.private, group=1)
async def _text_router(app: Client, msg: Message):
    try:
        if not msg.from_user:
            return

        # Ignore commands — they're handled in group 0
        text = (msg.text or "").strip()
        if text.startswith("/"):
            return

        uid = msg.from_user.id

        # Priority 1: Note reply
        from plugins.assignments import _pending_notes, handle_note_reply
        if uid in _pending_notes:
            await handle_note_reply(app, msg)
            return

        # Priority 2: Panel config edit
        from plugins.panel import _state, handle_panel_input
        from helper.aliases import is_owner
        if uid in _state and is_owner(uid):
            await handle_panel_input(app, msg)
            return

    except Exception as e:
        logger.exception("text_router error: %s", e)
