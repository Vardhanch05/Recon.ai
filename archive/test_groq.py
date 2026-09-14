import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("GROQ_API_KEY")

payload = {
    "model": "openai/gpt-oss-120b",
    "messages": [
        {"role": "system", "content": "You are a financial helper. Output JSON."},
        {"role": "user", "content": "Return a JSON object with key message set to Hello World."}
    ],
    "response_format": {"type": "json_object"}
}

req = urllib.request.Request(
    "https://api.groq.com/openai/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "ReconAI/1.0"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=15) as res:
        print("Success:")
        print(res.read().decode("utf-8"))
except Exception as e:
    print("Error:", e)
