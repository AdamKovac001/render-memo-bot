import os
import json
import logging
from datetime import datetime
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import openai
from dotenv import load_dotenv

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

# Initialize bot
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_CREDENTIALS = json.loads(os.getenv('GOOGLE_CREDENTIALS_JSON'))

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# Initialize Google Docs API
credentials = service_account.Credentials.from_service_account_info(
    GOOGLE_CREDENTIALS,
    scopes=['https://www.googleapis.com/auth/drive.file']
)
drive_service = build('drive', 'v3', credentials=credentials)
docs_service = build('docs', 'v1', credentials=credentials)

# Store user documents
user_docs = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and create personal Google Doc."""
    user_id = update.effective_user.id
    
    try:
        # Create a new Google Doc
        doc_metadata = {
            'name': f'MindShot Notes - {update.effective_user.first_name}',
            'mimeType': 'application/vnd.google-apps.document'
        }
        doc = drive_service.files().create(body=doc_metadata, fields='id').execute()
        doc_id = doc.get('id')
        
        # Store the doc ID
        user_docs[user_id] = doc_id
        
        # Set initial permissions
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': update.effective_user.email
        }
        drive_service.permissions().create(
            fileId=doc_id,
            body=permission,
            fields='id'
        ).execute()
        
        doc_url = f'https://docs.google.com/document/d/{doc_id}'
        await update.message.reply_text(
            f"Welcome to MindShot Bot! 🎉\n\n"
            f"I've created your personal Google Doc: {doc_url}\n\n"
            f"Available commands:\n"
            f"/add_editor <email> - Share your doc with someone\n"
            f"/list_editors - Show who has access\n"
            f"Send a voice message and reply with /cursor to transcribe and summarize it"
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("Sorry, there was an error setting up your document. Please try again later.")

async def add_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add an editor to the user's Google Doc."""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Please provide an email address: /add_editor <email>")
        return
    
    email = context.args[0]
    
    if user_id not in user_docs:
        await update.message.reply_text("Please use /start first to create your document.")
        return
    
    try:
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': email
        }
        drive_service.permissions().create(
            fileId=user_docs[user_id],
            body=permission,
            fields='id'
        ).execute()
        
        await update.message.reply_text(f"Successfully added {email} as an editor.")
    except Exception as e:
        logger.error(f"Error adding editor: {e}")
        await update.message.reply_text("Sorry, there was an error adding the editor. Please try again.")

async def list_editors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all editors of the user's Google Doc."""
    user_id = update.effective_user.id
    
    if user_id not in user_docs:
        await update.message.reply_text("Please use /start first to create your document.")
        return
    
    try:
        permissions = drive_service.permissions().list(
            fileId=user_docs[user_id],
            fields='permissions(emailAddress,role)'
        ).execute()
        
        editors = []
        for perm in permissions.get('permissions', []):
            editors.append(f"• {perm['emailAddress']} ({perm['role']})")
        
        if editors:
            await update.message.reply_text("Document editors:\n" + "\n".join(editors))
        else:
            await update.message.reply_text("No editors found for this document.")
    except Exception as e:
        logger.error(f"Error listing editors: {e}")
        await update.message.reply_text("Sorry, there was an error listing the editors. Please try again.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages and process them when /cursor is used."""
    if not update.message.reply_to_message or not update.message.reply_to_message.voice:
        return
    
    if update.message.text != "/cursor":
        return
    
    user_id = update.effective_user.id
    if user_id not in user_docs:
        await update.message.reply_text("Please use /start first to create your document.")
        return
    
    try:
        # Download voice message
        voice = update.message.reply_to_message.voice
        voice_file = await context.bot.get_file(voice.file_id)
        voice_bytes = await voice_file.download_as_bytearray()
        
        # Transcribe with Whisper
        transcription = openai.audio.transcriptions.create(
            model="whisper-1",
            file=("voice.ogg", voice_bytes)
        )
        
        # Summarize with GPT-4
        summary = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Summarize the following text into clear, concise bullet points:"},
                {"role": "user", "content": transcription.text}
            ]
        )
        
        # Append to Google Doc
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': f"\n\n--- {timestamp} ---\n\n"
                }
            },
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': summary.choices[0].message.content
                }
            }
        ]
        
        docs_service.documents().batchUpdate(
            documentId=user_docs[user_id],
            body={'requests': requests}
        ).execute()
        
        await update.message.reply_text("✅ Voice message processed and added to your document!")
        
    except Exception as e:
        logger.error(f"Error processing voice message: {e}")
        await update.message.reply_text("Sorry, there was an error processing your voice message. Please try again.")

def main():
    """Initialize bot and set up webhook."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_editor", add_editor))
    application.add_handler(CommandHandler("list_editors", list_editors))
    application.add_handler(MessageHandler(filters.VOICE | filters.TEXT, handle_voice))
    
    # Set up webhook
    @app.route('/webhook', methods=['POST'])
    def webhook():
        update = Update.de_json(request.get_json(), application.bot)
        application.process_update(update)
        return 'ok'
    
    # Start the bot
    application.run_webhook(
        listen='0.0.0.0',
        port=int(os.getenv('PORT', 10000)),
        webhook_url=f'https://{request.host}/webhook'
    )

if __name__ == '__main__':
    main() 