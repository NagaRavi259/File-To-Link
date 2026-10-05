#Aadhi000
from Adarsh.bot import StreamBot
from Adarsh.vars import Var
import html
import re
import logging
logger = logging.getLogger("Adarsh.bot.plugins.start_help")
from Adarsh.bot.plugins.stream import MY_PASS, is_logged_in, login_waiting
from Adarsh.utils.human_readable import humanbytes
from Adarsh.utils.database import Database
from Adarsh.utils.access import has_access, access_db, is_exempt
from Adarsh.utils.link_expiry import link_expiry
from pyrogram import Client, filters, StopPropagation, enums
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant, PeerIdInvalid
from Adarsh.utils.file_properties import get_name, get_hash, get_media_file_size, get_media_from_message, hash_ok
from pyrogram.types import ReplyKeyboardMarkup
import asyncio

db = Database.shared(Var.name)


# ----------------- MIDDLEWARE HANDLER (Corrected) ----------------- #

@StreamBot.on_message(filters.private, group=-1)
async def check_user(b: Client, m: Message):
    """
    Middleware. Allowed: owners/trusted users, approved users, members of an access
    group, and people who asked to join one (see Adarsh/utils/access.py has_access).
    Everyone else gets a 'Request Access' button; banned users are told they are banned.
    """
    if not Var.USER_GROUP_ID or m.from_user is None:
        return
    # Invite deep link: /start inv_<token> must work for people who don't have access yet.
    if m.text and m.text.startswith("/start inv_"):
        from Adarsh.bot.plugins.access_admin import redeem
        ok = await redeem(b, m.from_user, m.text.split("inv_", 1)[1].strip())
        await m.reply_text(
            "✅ **Invite accepted.** Send me any file to get a link." if ok
            else "❌ This invite is invalid, expired or not for you."
        )
        raise StopPropagation()
    # Let an unapproved user reach the password login flow itself: the /login
    # command, and the password they send right after it.
    if MY_PASS and (m.chat.id in login_waiting or (m.text and (m.text.startswith("/login") or "login🔑" in m.text))):
        return
    try:
        allowed, reason = await has_access(b, m.from_user.id)
    except Exception:
        logger.exception("Access check failed")
        await m.reply_text("⚠️ Something went wrong on my side. Please try again in a moment.")
        raise StopPropagation()
    if allowed:
        if not is_exempt(m.from_user.id):
            try:
                await access_db.touch(m.from_user)
            except Exception:
                logger.exception("Could not record activity")  # bookkeeping only: never block the user
        return
    # Password login is a standalone access path, independent of admin approval
    # (but a ban still wins). Off by default; only matters once MY_PASS is set.
    if reason != "banned" and await is_logged_in(m.from_user.id):
        return
    if reason == "banned":
        await m.reply_text("🚫 **You are banned from this bot.**")
    elif reason == "pending":
        await m.reply_text("⏳ **Your access request is waiting for approval.** You will be notified.")
    else:
        text = (
            "🔒 **Access Denied**\n\nYou are not authorized to use this bot.\n"
            "Tap the button below to ask the admin for access."
        )
        if MY_PASS:
            text += "\n\nOr, if you have the password, send /login."
        await m.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Request Access", callback_data="req:access")]]),
        )
    raise StopPropagation()

# ----------------- END OF MIDDLEWARE ----------------- #

@StreamBot.on_message(filters.command('start') & filters.private)
async def start(b, m):
    if not await db.is_user_exist(m.from_user.id):
        await db.add_user(m.from_user.id)
        await b.send_message(
            Var.BIN_CHANNEL,
            f"#NEW_USER: \n\nNew User [{m.from_user.first_name}](tg://user?id={m.from_user.id}) Started !!"
        )
    payload = (m.text.split(maxsplit=1) + [""])[1].strip()
    if not payload:
        if Var.UPDATES_CHANNEL:
            try:
                user = await b.get_chat_member(Var.UPDATES_CHANNEL, m.chat.id)
                if user.status == "banned":
                    await b.send_message(
                        chat_id=m.chat.id,
                        text="**ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ../**",
                        disable_web_page_preview=True
                    )
                    return
            except UserNotParticipant:
                await b.send_message(
                    chat_id=m.chat.id,
                    text="**ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ  ᴍᴇ..**\n\n**ᴅᴜᴇ ᴛᴏ ᴏᴠᴇʀʟᴏᴀᴅ ᴏɴʟʏ ᴄʜᴀɴɴᴇʟ sᴜʙsᴄʀɪʙᴇʀs ᴄᴀɴ ᴜsᴇ ᴍᴇ..!**",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("𝙹𝙾𝙸𝙽 𝚄𝙿𝙳𝙰𝚃𝙴𝚉 𝙲𝙷𝙰𝙽𝙽𝙴𝙻", url=f"https://t.me/{Var.UPDATES_CHANNEL}")
                            ]
                        ]
                    )

                )
                return
            except Exception:
                await b.send_message(
                    chat_id=m.chat.id,
                    text='\n🎉 Welcome to the Ultimate Test Bot! 🎉**\n\n🔹 **Enjoy All Features for FREE!**\n🔹 **No Ads, No Subscription!**\n\n**📁 How to Use:**\n\n1. **Forward a File** to this bot.\n2. **Receive a Link** to **Stream** or **Download** your file instantly!\n\n**💡 Key Features:**\n\n- **Completely Ad-Free Experience** 🚫\n- **No Subscription Required** 🎟️\n- **Fast & Easy File Sharing** 📤',

                    disable_web_page_preview=True)
                return
        await m.reply_photo(
            photo="https://telegra.ph/file/3cd15a67ad7234c2945e7.jpg",
            caption="**ʜᴇʟʟᴏ...⚡\n\nɪᴀᴍ ᴀ sɪᴍᴘʟᴇ ᴛᴇʟᴇɢʀᴀᴍ ғɪʟᴇ/ᴠɪᴅᴇᴏ ᴛᴏ ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ ᴀɴᴅ sᴛʀᴇᴀᴍ ʟɪɴᴋ ɢᴇɴᴇʀᴀᴛᴏʀ ʙᴏᴛ.**\n\n**ᴜsᴇ /help ғᴏʀ ᴍᴏʀᴇ ᴅᴇᴛsɪʟs\n\nsᴇɴᴅ ᴍᴇ ᴀɴʏ ᴠɪᴅᴇᴏ / ғɪʟᴇ ᴛᴏ sᴇᴇ ᴍʏ ᴘᴏᴡᴇʀᴢ...**",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⚡ ᴜᴘᴅᴀᴛᴇᴢ ⚡", url="https://t.me/MWUpdatez"), InlineKeyboardButton("⚡ sᴜᴘᴘᴏʀᴛ ⚡", url="https://t.me/OpusTechz")],
                    [InlineKeyboardButton("💸 ᴅᴏɴᴀᴛᴇ 💸", url="https://paypal.me/114912Aadil"), InlineKeyboardButton("💠 ɢɪᴛʜᴜʙ 💠", url="https://github.com/Aadhi000")],
                    [InlineKeyboardButton("💌 sᴜʙsᴄʀɪʙᴇ 💌", url="https://youtube.com/opustechz")]
                ]
            ),

        )
    else:
        if Var.UPDATES_CHANNEL:
            try:
                user = await b.get_chat_member(Var.UPDATES_CHANNEL, m.chat.id)
                if user.status == "banned":
                    await b.send_message(
                        chat_id=m.chat.id,
                        text="**ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ../**",

                        disable_web_page_preview=True
                    )
                    return
            except UserNotParticipant:
                await b.send_message(
                    chat_id=m.chat.id,
                    text="**ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ  ᴍᴇ..**\n\n**ᴅᴜᴇ ᴛᴏ ᴏᴠᴇʀʟᴏᴀᴅ ᴏɴʟʏ ᴄʜᴀɴɴᴇʟ sᴜʙsᴄʀɪʙᴇʀs ᴄᴀɴ ᴜsᴇ ᴍᴇ..!**",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url=f"https://t.me/{Var.UPDATES_CHANNEL}")
                            ]
                        ]
                    )

                )
                return
            except Exception:
                await b.send_message(
                    chat_id=m.chat.id,
                    text='\n🎉 Welcome to the Ultimate Test Bot! 🎉**\n\n🔹 **Enjoy All Features for FREE!**\n🔹 **No Ads, No Subscription!**\n\n**📁 How to Use:**\n\n1. **Forward a File** to this bot.\n2. **Receive a Link** to **Stream** or **Download** your file instantly!\n\n**💡 Key Features:**\n\n- **Completely Ad-Free Experience** 🚫\n- **No Subscription Required** 🎟️\n- **Fast & Easy File Sharing** 📤',
                    disable_web_page_preview=True)
                return

        # Deep link: /start <message id>_<hash>. The hash is required, so ids cannot be enumerated.
        invalid = "❌ This link is not valid."
        match = re.fullmatch(r"(?:file_)?(\d+)_([A-Za-z0-9_-]{6,12})", payload)
        if not match:
            await m.reply_text(invalid)
            return
        msg_id, secure_hash = int(match.group(1)), match.group(2)
        media = None
        try:
            get_msg = await b.get_messages(Var.BIN_CHANNEL, msg_id)
            media = None if get_msg.empty else get_media_from_message(get_msg)
        except Exception:
            pass
        if not media or not hash_ok(media.file_unique_id, secure_hash) or await access_db.is_revoked(msg_id) \
                or await link_expiry.is_expired(msg_id):
            await m.reply_text(invalid)
            return
        file_name = html.escape(getattr(media, "file_name", None) or "file")
        file_size = humanbytes(getattr(media, "file_size", 0))
        online_link = f"{Var.URL}{msg_id}/?hash={secure_hash}"
        stream_link = f"{Var.URL}watch/{msg_id}/?hash={secure_hash}"
        await m.reply_text(
            text=f"<b>Your link is ready ⚡</b>\n\n📧 <b>File name:</b> {file_name}\n📦 <b>Size:</b> {file_size}\n\n💌 <b>Download:</b> {online_link}",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Watch ⚡", url=stream_link),
                                                InlineKeyboardButton("⚡ Download ⚡", url=online_link)]])
        )


@StreamBot.on_message(filters.command('help') & filters.private)
async def help_handler(bot, message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id)
        await bot.send_message(
            Var.BIN_CHANNEL,
            f"#NEW_USER: \n\nNew User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) Started !!"
        )
    if Var.UPDATES_CHANNEL:
        try:
            user = await bot.get_chat_member(Var.UPDATES_CHANNEL, message.chat.id)
            if user.status == "banned":
                await bot.send_message(
                    chat_id=message.chat.id,
                    text="**ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ../**",

                    disable_web_page_preview=True
                )
                return
        except UserNotParticipant:
            await bot.send_message(
                chat_id=message.chat.id,
                text="**ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ  ᴍᴇ..**\n\n**ᴅᴜᴇ ᴛᴏ ᴏᴠᴇʀʟᴏᴀᴅ ᴏɴʟʏ ᴄʜᴀɴɴᴇʟ sᴜʙsᴄʀɪʙᴇʀs ᴄᴀɴ ᴜsᴇ ᴍᴇ..!**",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url=f"https://t.me/{Var.UPDATES_CHANNEL}")
                        ]
                    ]
                )
            )
            return
        except Exception:
            await bot.send_message(
                chat_id=message.chat.id,
                text='\n🎉 Welcome to the Ultimate Test Bot! 🎉**\n\n🔹 **Enjoy All Features for FREE!**\n🔹 **No Ads, No Subscription!**\n\n**📁 How to Use:**\n\n1. **Forward a File** to this bot.\n2. **Receive a Link** to **Stream** or **Download** your file instantly!\n\n**💡 Key Features:**\n\n- **Completely Ad-Free Experience** 🚫\n- **No Subscription Required** 🎟️\n- **Fast & Easy File Sharing** 📤',

                disable_web_page_preview=True)
            return
    await message.reply_photo(
            photo="https://telegra.ph/file/3cd15a67ad7234c2945e7.jpg",
            caption="**┣⪼ sᴇɴᴅ ᴍᴇ ᴀɴʏ ғɪʟᴇ/ᴠɪᴅᴇᴏ ᴛʜᴇɴ ɪ ᴡɪʟʟ ʏᴏᴜ ᴘᴇʀᴍᴀɴᴇɴᴛ sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ ᴏғ ɪᴛ...\n\n┣⪼ ᴛʜɪs ʟɪɴᴋ ᴄᴀɴ ʙᴇ ᴜsᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴏʀ ᴛᴏ sᴛʀᴇᴀᴍ ᴜsɪɴɢ ᴇxᴛᴇʀɴᴀʟ ᴠɪᴅᴇᴏ ᴘʟᴀʏᴇʀs ᴛʜʀᴏᴜɢʜ ᴍʏ sᴇʀᴠᴇʀs.\n\n┣⪼ ғᴏʀ sᴛʀᴇᴀᴍɪɴɢ ᴊᴜsᴛ ᴄᴏᴘʏ ᴛʜᴇ ʟɪɴᴋ ᴀɴᴅ ᴘᴀsᴛᴇ ɪᴛ ɪɴ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴘʟᴀʏᴇʀ ᴛᴏ sᴛᴀʀᴛ sᴛʀᴇᴀᴍɪɴɢ.\n\n┣⪼ ᴛʜɪs ʙᴏᴛ ɪs ᴀʟsᴏ sᴜᴘᴘᴏʀᴛ ɪɴ ᴄʜᴀɴɴᴇʟ. ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ ᴀs ᴀᴅᴍɪɴ ᴛᴏ ɢᴇᴛ ʀᴇᴀʟᴛɪᴍᴇ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ ғᴏʀ ᴇᴠᴇʀʏ ғɪʟᴇs/ᴠɪᴅᴇᴏs ᴘᴏsʏ../\n\n┣⪼ ғᴏʀ ᴍᴏʀᴇ ɪɴғᴏʀᴍᴀᴛɪᴏɴ :- /about\n\n\nᴘʟᴇᴀsᴇ sʜᴀʀᴇ ᴀɴᴅ sᴜʙsᴄʀɪʙᴇ**",


        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚡ ᴜᴘᴅᴀʏᴇᴢ ⚡", url="https://t.me/MWUpdatez"), InlineKeyboardButton("⚡ sᴜᴘᴘᴏʀᴛ ⚡", url="https://t.me/OpusTechz")],
                [InlineKeyboardButton("💸 ᴅᴏɴᴀᴛᴇ 💸", url="https://paypal.me/114912Aadil"), InlineKeyboardButton("💠 ɢɪᴛʜᴜʙ 💠", url="https://github.com/Aadhi000")],
                [InlineKeyboardButton("💌 sᴜʙsᴄʀɪʙᴇ 💌", url="https://youtube.com/opustechz")]
            ]
        )
    )

@StreamBot.on_message(filters.command('about') & filters.private)
async def about_handler(bot, message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id)
        await bot.send_message(
            Var.BIN_CHANNEL,
            f"#NEW_USER: \n\nNew User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) Started !!"
        )
    if Var.UPDATES_CHANNEL:
        try:
            user = await bot.get_chat_member(Var.UPDATES_CHANNEL, message.chat.id)
            if user.status == "banned":
                await bot.send_message(
                    chat_id=message.chat.id,
                    text="**ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ../**",

                    disable_web_page_preview=True
                )
                return
        except UserNotParticipant:
            await bot.send_message(
                chat_id=message.chat.id,
                text="**ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ  ᴍᴇ..**\n\n**ᴅᴜᴇ ᴛᴏ ᴏᴠᴇʀʟᴏᴀᴅ ᴏɴʟʏ ᴄʜᴀɴɴᴇʟ sᴜʙsᴄʀɪʙᴇʀs ᴄᴀɴ ᴜsᴇ ᴍᴇ..!**",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("ᴊᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url=f"https://t.me/{Var.UPDATES_CHANNEL}")
                        ]
                    ]
                )
            )
            return
        except Exception:
            await bot.send_message(
                chat_id=message.chat.id,
                text='\n🎉 Welcome to the Ultimate Test Bot! 🎉**\n\n🔹 **Enjoy All Features for FREE!**\n🔹 **No Ads, No Subscription!**\n\n**📁 How to Use:**\n\n1. **Forward a File** to this bot.\n2. **Receive a Link** to **Stream** or **Download** your file instantly!\n\n**💡 Key Features:**\n\n- **Completely Ad-Free Experience** 🚫\n- **No Subscription Required** 🎟️\n- **Fast & Easy File Sharing** 📤',

                disable_web_page_preview=True)
            return
    await message.reply_photo(
            photo="https://telegra.ph/file/3cd15a67ad7234c2945e7.jpg",
            caption="""<b>sᴏᴍᴇ ʜɪᴅᴅᴇɴ ᴅᴇᴛᴀɪʟs😜</b>

<b>╭━━━━━━━〔ғɪʟᴇ ᴛᴏ ʟɪɴᴋ ʙᴏᴛ〕</b>
┃
┣⪼<b>ʙᴏᴛ ɴᴀᴍᴇ : <a href='https://github.com/Aadhi000/File-To-Link'>ғɪʟᴇ ᴛᴏ ʟɪɴᴋ</a></b>
┣⪼<b>ᴜᴘᴅᴀᴛᴇᴢ : <a href='https://t.me/MWUpdatez'>ᴍᴡ ᴜᴘᴅᴀᴛᴇᴢ</a></b>
┣⪼<b>sᴜᴘᴘᴏʀᴛ : <a href='https://t.me/OpusTechz'>ᴏᴘᴜs ᴛᴇᴄʜᴢ</a></b>
┣⪼<b>sᴇʀᴠᴇʀ : ʜᴇʀᴜᴋᴏ</b>
┣⪼<b>ʟɪʙʀᴀʀʏ : ᴘʏʀᴏɢʀᴀᴍ</b>
┣⪼<b>ʟᴀɴɢᴜᴀɢᴇ: ᴘʏᴛʜᴏɴ 3</b>
┣⪼<b>sᴏᴜʀᴄᴇ-ᴄᴏᴅᴇ : <a href='https://github.com/Aadhi000/File-To-Link'>ғɪʟᴇ ᴛᴏ ʟɪɴᴋ</a></b>
┣⪼<b>ʏᴏᴜᴛᴜʙᴇ : <a href='https://youtube.com/opustechz'>ᴏᴘᴜs ᴛᴇᴄʜᴢ</a></b>
┃
<b>╰━━━━━━━〔ᴘʟᴇᴀsʀ sᴜᴘᴘᴏʀᴛ〕</b>""",


        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚡ ᴜᴘᴅᴀᴛᴇᴢ ⚡", url="https://t.me/MWUpdatez"), InlineKeyboardButton("💸 ᴅᴏɴᴀᴛᴇ 💸", url="https://paypal.me/114912Aadil")],
                [InlineKeyboardButton("💌 sᴜʙsᴄʀɪʙᴇ 💌", url="https://youtube.com/opustechz")]
            ]
        )
    )
