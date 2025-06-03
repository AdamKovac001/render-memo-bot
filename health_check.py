import os
import requests
from dotenv import load_dotenv

load_dotenv()

def check_env_vars():
    required = [
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "RENDER_EXTERNAL_URL"
    ]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return False
    print("✅ All required environment variables are set.")
    return True

def check_webhook():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    resp = requests.get(url)
    data = resp.json()
    if data.get("ok"):
        webhook_url = data["result"].get("url")
        if webhook_url:
            print(f"✅ Webhook is set: {webhook_url}")
            return True
        else:
            print("❌ Webhook is not set.")
            return False
    else:
        print(f"❌ Failed to get webhook info: {data}")
        return False

def check_google_api():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        credentials = service_account.Credentials.from_service_account_file('credentials.json')
        docs_service = build('docs', 'v1', credentials=credentials)
        docs_service.documents().list(pageSize=1).execute()
        print("✅ Google Docs API is reachable.")
        return True
    except Exception as e:
        print(f"❌ Google Docs API check failed: {e}")
        return False

def check_openai():
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    try:
        openai.models.list()
        print("✅ OpenAI API is reachable.")
        return True
    except Exception as e:
        print(f"❌ OpenAI API check failed: {e}")
        return False

if __name__ == "__main__":
    all_ok = True
    if not check_env_vars():
        all_ok = False
    if not check_webhook():
        all_ok = False
    if not check_google_api():
        all_ok = False
    if not check_openai():
        all_ok = False

    if all_ok:
        print("🎉 All systems are running as they should!")
    else:
        print("⚠️  Some checks failed. Please review the output above.") 