"""
plugins/admins.py
Commands: /addadmin /removeadmin /listadmins /forceassign /reassign
"""
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message

import database.anime as anime_db
import database.assignments as assign_db
import database.logs as logs_db
import database.users as users_db
from helper import assignment as asn, dashboard
from helper.aliases import owner_only


@Client.on_message(filters.command("addadmin"))
@owner_only
async def cmd_addadmin(app: Client, msg: Message):
    args = msg.command[1:]
    if not args:
        await msg.reply("Usage: `/addadmin @username`")
        return
    username = args[0].lstrip("@")
    db_user = await users_db.get_by_username(username)
    if db_user:
        if db_user.get("role") == "admin":
            await msg.reply(f"ℹ️ @{username} is already an admin.")
            return
        await users_db.set_role(username, "admin")
        await msg.reply(f"✅ @{username} granted admin access.")
    else:
        from database.mongo import get_db
        await get_db().users.insert_one({
            "telegram_id": 0,
            "username": username,
            "full_name": "",
            "role": "admin",
            "task_limit": 5,
            "is_away": False,
            "active_task_count": 0,
            "completed_count": 0,
            "encoded_count": 0,
            "leeched_count": 0,
            "invalid_count": 0,
            "joined_at": datetime.utcnow(),
            "pre_registered": True,
        })
        await msg.reply(
            f"✅ @{username} pre-registered as admin.\n"
            "They'll have access once they send /start to the bot."
        )
    await logs_db.log_audit(str(msg.from_user.id), "add_admin", target=username)


@Client.on_message(filters.command("removeadmin"))
@owner_only
async def cmd_removeadmin(app: Client, msg: Message):
    args = msg.command[1:]
    if not args:
        await msg.reply("Usage: `/removeadmin @username`")
        return
    username = args[0].lstrip("@")
    ok = await users_db.set_role(username, "removed")
    if ok:
        await msg.reply(f"✅ @{username} removed from admin list.")
        await logs_db.log_audit(str(msg.from_user.id), "remove_admin", target=username)
    else:
        await msg.reply(f"❌ User @{username} not found.")


@Client.on_message(filters.command("listadmins"))
@owner_only
async def cmd_listadmins(app: Client, msg: Message):
    admins = await users_db.list_admins()
    if not admins:
        await msg.reply("No admins registered.")
        return
    lines = []
    for u in admins:
        away  = " 😴 AWAY" if u.get("is_away") else ""
        uname = u.get("username") or u.get("full_name", "Unknown")
        lines.append(
            f"  @{uname}{away}\n"
            f"    ✅ {u.get('completed_count', 0)} done | "
            f"🎯 {u.get('active_task_count', 0)}/{u.get('task_limit', 5)} active"
        )
    await msg.reply(
        f"👥 **Registered Admins ({len(lines)})**\n\n" + "\n\n".join(lines)
    )


@Client.on_message(filters.command("forceassign"))
@owner_only
async def cmd_forceassign(app: Client, msg: Message):
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/forceassign <anime_id> @username`")
        return
    anime_id, target_username = args[0], args[1].lstrip("@")
    target = await users_db.get_by_username(target_username)
    if not target:
        await msg.reply(f"❌ User @{target_username} not found.")
        return
    ok, err = await asn.force_assign(anime_id, target["telegram_id"], msg.from_user.id)
    if ok:
        anime = await anime_db.get_by_id(anime_id)
        title = anime["titles"]["display_title"] if anime else anime_id
        if anime:
            await dashboard.upsert_anime_message(app, anime)
        await dashboard.update_all(app)
        await dashboard.log_event(app, f"🎯 **Force Assigned:** {title} → @{target_username}")
        await msg.reply(f"✅ **{title}** force-assigned to @{target_username}.")
    else:
        await msg.reply(f"❌ {err}")


@Client.on_message(filters.command("reassign"))
@owner_only
async def cmd_reassign(app: Client, msg: Message):
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/reassign <anime_id> @username`")
        return
    anime_id, target_username = args[0], args[1].lstrip("@")
    target = await users_db.get_by_username(target_username)
    if not target:
        await msg.reply(f"❌ User @{target_username} not found.")
        return

    current = await assign_db.get_active(anime_id)
    old_uid = current["user_id"] if current else None
    old_user = await users_db.get_by_id(old_uid) if old_uid else None
    old_name = old_user.get("username", str(old_uid)) if old_user else "unassigned"

    ok, err = await asn.force_assign(anime_id, target["telegram_id"], msg.from_user.id)
    if ok:
        anime = await anime_db.get_by_id(anime_id)
        title = anime["titles"]["display_title"] if anime else anime_id
        await logs_db.log_audit(
            str(msg.from_user.id), "reassigned",
            target=anime_id, old_value=old_name, new_value=target_username,
        )
        if anime:
            await dashboard.upsert_anime_message(app, anime)
        await dashboard.update_all(app)
        await dashboard.log_event(
            app, f"🔄 **Reassigned:** {title}\n@{old_name} → @{target_username}"
        )
        await msg.reply(f"🔄 **{title}** reassigned\n@{old_name} → @{target_username}")
    else:
        await msg.reply(f"❌ {err}")
