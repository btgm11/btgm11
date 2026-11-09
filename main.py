import asyncio
import os
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Message, BusinessMessagesDeleted

BOT_TOKEN = "9209876712:AAFnvmG2g3fZCg2eyaejHUbMc_Xp4_logeo"
MY_USER_ID = 8026731485

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_FILE = "deleted_tracker.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER,
                chat_id INTEGER,
                sender_name TEXT,
                username TEXT,
                content_type TEXT,
                text_or_caption TEXT,
                file_id TEXT,
                PRIMARY KEY (message_id, chat_id)
            )
        """)
        await db.commit()

@dp.business_message()
async def cache_message(message: Message):
    if message.from_user.id == MY_USER_ID:
        return

    chat_id = message.chat.id
    msg_id = message.message_id
    sender = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "без юзернейма"

    content_type = "text"
    file_id = None
    caption = message.caption or ""

    if message.text:
        content_type = "text"
        text_or_caption = message.text
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
        text_or_caption = caption
    elif message.video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id
        text_or_caption = caption
    elif message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        text_or_caption = caption
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        text_or_caption = caption
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
        text_or_caption = caption
    else:
        content_type = "other"
        text_or_caption = "[Неподдерживаемый тип медиа]"

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """INSERT OR REPLACE INTO messages 
               (message_id, chat_id, sender_name, username, content_type, text_or_caption, file_id) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, chat_id, sender, username, content_type, text_or_caption, file_id)
        )
        await db.commit()

@dp.deleted_business_messages()
async def process_deleted(event: BusinessMessagesDeleted):
    chat_id = event.chat.id

    async with aiosqlite.connect(DB_FILE) as db:
        for msg_id in event.message_ids:
            async with db.execute(
                """SELECT sender_name, username, content_type, text_or_caption, file_id 
                   FROM messages WHERE message_id = ? AND chat_id = ?""",
                (msg_id, chat_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    sender, username, c_type, text, file_id = row
                    header = (
                        f"🗑 <b>УДАЛЕНО СООБЩЕНИЕ</b>\n"
                        f"👤 <b>От:</b> {sender} ({username})"
                    )

                    if c_type == "text":
                        await bot.send_message(
                            chat_id=MY_USER_ID, 
                            text=f"{header}\n💬 <b>Текст:</b>\n{text}", 
                            parse_mode="HTML"
                        )
                    elif c_type == "voice":
                        await bot.send_message(chat_id=MY_USER_ID, text=f"{header}\n🎤 <b>Голосовое сообщение:</b>", parse_mode="HTML")
                        await bot.send_voice(chat_id=MY_USER_ID, voice=file_id, caption=text)
                    elif c_type == "video_note":
                        await bot.send_message(chat_id=MY_USER_ID, text=f"{header}\n📹 <b>Кружочек:</b>", parse_mode="HTML")
                        await bot.send_video_note(chat_id=MY_USER_ID, video_note=file_id)
                    elif c_type == "photo":
                        await bot.send_message(chat_id=MY_USER_ID, text=f"{header}\n🖼 <b>Фотография:</b>", parse_mode="HTML")
                        await bot.send_photo(chat_id=MY_USER_ID, photo=file_id, caption=text)
                    elif c_type == "video":
                        await bot.send_message(chat_id=MY_USER_ID, text=f"{header}\n🎥 <b>Видео:</b>", parse_mode="HTML")
                        await bot.send_video(chat_id=MY_USER_ID, video=file_id, caption=text)
                    elif c_type == "document":
                        await bot.send_message(chat_id=MY_USER_ID, text=f"{header}\n📁 <b>Документ:</b>", parse_mode="HTML")
                        await bot.send_document(chat_id=MY_USER_ID, document=file_id, caption=text)

                    await db.execute("DELETE FROM messages WHERE message_id = ? AND chat_id = ?", (msg_id, chat_id))
        await db.commit()

async def dummy_web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await init_db()
    await dummy_web_server()
    print("Бот запущен и веб-сервер слушает порт!")
    await dp.start_polling(
        bot, 
        allowed_updates=["business_message", "deleted_business_messages", "business_connection"]
    )

if __name__ == "__main__":
    asyncio.run(main())
