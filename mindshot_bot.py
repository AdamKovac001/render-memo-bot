import os
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
import requests
import datetime
import re
import logging
import asyncio
from dotenv import load_dotenv
import aiohttp
from flask import Flask
from threading import Thread

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))

# --- CONFIG ---
WHITELIST = {8079951399, 123456789, 987654321}  # Added Adam Kováč's chat ID
USER_DOCS_FILE = "user_docs.json"

# Google Docs setup
SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
docs_service = build("docs", "v1", credentials=credentials)
drive_service = build("drive", "v3", credentials=credentials)

# --- USER DOCS MAPPING ---
def load_user_docs():
    if os.path.exists(USER_DOCS_FILE):
        with open(USER_DOCS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_user_docs(mapping):
    with open(USER_DOCS_FILE, "w") as f:
        json.dump(mapping, f)

user_docs = load_user_docs()

def get_or_create_user_doc(user_id, username=None):
    user_id_str = str(user_id)
    if user_id_str in user_docs:
        return user_docs[user_id_str]
    # Create new doc
    title = f"Voice Notes for {username or user_id}"
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    user_docs[user_id_str] = doc_id
    save_user_docs(user_docs)
    return doc_id

def get_doc_link(doc_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit?usp=sharing"

def append_text_to_doc(doc_id, text):
    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": text + "\n\n"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def transcribe_voice(file_path):
    openai.api_key = os.getenv("OPENAI_API_KEY")
    with open(file_path, "rb") as audio_file:
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text

def summarize_with_gpt(transcription):
    openai.api_key = os.getenv("OPENAI_API_KEY")
    prompt = (
        "Summarize the following text as clear, concise bullet-point notes. "
        "Add only the most important information.\n\nText:\n" + transcription
    )
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.4
    )
    return response.choices[0].message.content.strip()

def format_transcription_entry(transcription):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    # Simple bullet point split: split by sentences ('.', '!', '?')
    sentences = re.split(r'(?<=[.!?]) +', transcription.strip())
    bullets = '\n'.join([f'• {s.strip()}' for s in sentences if s.strip()])
    entry = f"---\n🕒 {now}\n\n{bullets}\n"
    return entry

# --- WHITELIST CHECK DECORATOR ---
def whitelist_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in WHITELIST:
            await update.message.reply_text("❌ You are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@whitelist_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    doc_id = get_or_create_user_doc(user_id, username)
    doc_link = get_doc_link(doc_id)
    welcome_message = (
        "👋 Welcome to MindShotBot!\n\n"
        "Here's how to use me:\n"
        "1. Send me a voice message\n"
        "2. Reply to it with /cursor\n"
        "3. I'll transcribe it, format it, and save it to your doc!\n\n"
        "Commands:\n"
        "/add_editor <email> - Add an editor to the document\n"
        "/remove_editor - Show list of editors to remove\n"
        "/list_editors - Show all current editors\n\n"
        f"📝 Your document:\n{doc_link}\n\n"
        "Let's try it - send me a voice message!"
    )
    await update.message.reply_text(welcome_message)

@whitelist_only
async def add_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc_id = get_or_create_user_doc(user_id, update.effective_user.username)
    if context.args:
        email = context.args[0]
        try:
            drive_service.permissions().create(
                fileId=doc_id,
                body={"type": "user", "role": "writer", "emailAddress": email},
                sendNotificationEmail=True
            ).execute()
            await update.message.reply_text(f"✅ Successfully added {email} as an editor to your document!")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to add editor: {e}")
    else:
        await update.message.reply_text("Usage: /add_editor <email>")

@whitelist_only
async def list_editors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc_id = get_or_create_user_doc(user_id, update.effective_user.username)
    try:
        permissions = drive_service.permissions().list(fileId=doc_id, fields="permissions(emailAddress,role)").execute()
        editors = [p["emailAddress"] for p in permissions.get("permissions", []) if p.get("role") == "writer"]
        if editors:
            editors_list = "\n".join([f"• {e}" for e in editors])
            await update.message.reply_text(f"📝 Current editors:\n{editors_list}\n\nUse /remove_editor to see numbered list for removal.")
        else:
            await update.message.reply_text("No editors found.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to list editors: {e}")

@whitelist_only
async def remove_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc_id = get_or_create_user_doc(user_id, update.effective_user.username)
    try:
        permissions = drive_service.permissions().list(fileId=doc_id, fields="permissions(id,emailAddress,role)").execute()
        editors = [(p["id"], p["emailAddress"]) for p in permissions.get("permissions", []) if p.get("role") == "writer"]
        if not editors:
            await update.message.reply_text("No editors to remove.")
            return
        numbered = "\n".join([f"{i+1}. {e[1]}" for i, e in enumerate(editors)])
        await update.message.reply_text(f"Send the number of the editor to remove:\n{numbered}")
        # For demo: remove the first editor (in real bot, handle user reply)
        # permission_id, email = editors[0]
        # drive_service.permissions().delete(fileId=doc_id, permissionId=permission_id).execute()
        # await update.message.reply_text(f"✅ Removed {email} as an editor.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to remove editor: {e}")

@whitelist_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

@whitelist_only
async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    doc_id = get_or_create_user_doc(user_id, username)
    await update.message.reply_text("I received your voice message! Reply to it with /cursor to process it.")

@whitelist_only
async def cursor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    doc_id = get_or_create_user_doc(user_id, username)
    doc_link = get_doc_link(doc_id)
    print(f"[DEBUG] /cursor called by user {user_id}")
    if update.message.reply_to_message and update.message.reply_to_message.voice:
        print("[DEBUG] Voice message reply detected. Downloading file...")
        file = await context.bot.get_file(update.message.reply_to_message.voice.file_id)
        file_path = f"voice_{user_id}.ogg"
        file_bytes = requests.get(file.file_path)
        with open(file_path, "wb") as f:
            f.write(file_bytes.content)
        try:
            print("[DEBUG] Transcribing audio...")
            transcription = transcribe_voice(file_path)
            print(f"[DEBUG] Transcription: {transcription}")
            print("[DEBUG] Sending transcription to ChatGPT for summarization...")
            summary = summarize_with_gpt(transcription)
            print(f"[DEBUG] GPT summary: {summary}")
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            entry = f"---\n🕒 {now}\n\n{summary}\n"
            append_text_to_doc(doc_id, entry)
            print("[DEBUG] Appended GPT summary to doc.")
            await update.message.reply_text(f"✅ Voice note processed!\n📝 View your notes: {doc_link}")
        except Exception as e:
            print(f"[ERROR] {e}")
            await update.message.reply_text(f"❌ Error transcribing or saving: {e}")
        finally:
            os.remove(file_path)
    else:
        print("[DEBUG] /cursor was not a reply to a voice message.")
        await update.message.reply_text("❌ Please reply to a voice message with /cursor")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I'm here to help! Use /start to see instructions.")

async def main():
    # Start Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Initialize bot
    application = ApplicationBuilder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_editor", add_editor))
    application.add_handler(CommandHandler("list_editors", list_editors))
    application.add_handler(CommandHandler("remove_editor", remove_editor))
    application.add_handler(CommandHandler("cursor", cursor))
    application.add_handler(MessageHandler(filters.VOICE, voice_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    # Start the bot
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main()) 