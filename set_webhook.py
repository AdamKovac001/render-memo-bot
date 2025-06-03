import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def set_webhook():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    service_url = os.getenv("RENDER_EXTERNAL_URL")
    
    if not token or not service_url:
        print("Error: TELEGRAM_BOT_TOKEN and RENDER_EXTERNAL_URL must be set in .env file")
        return
    
    url = f"https://api.telegram.org/bot{token}/setWebhook"
    data = {"url": f"{service_url}/webhook"}
    
    try:
        resp = requests.post(url, data=data)
        result = resp.json()
        
        if result.get("ok"):
            print("✅ Webhook set successfully!")
            print(f"Webhook URL: {service_url}/webhook")
        else:
            print("❌ Failed to set webhook:")
            print(result.get("description", "Unknown error"))
            
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")

if __name__ == "__main__":
    set_webhook() 