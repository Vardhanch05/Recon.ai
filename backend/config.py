import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Default to local sqlite for dev/testing if not specified in environment
    DATABASE_URL = "sqlite:///./recon_ai.db"

API_KEY = os.getenv("API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# In production, require API key by default unless explicitly disabled
REQUIRE_API_KEY_ENV = os.getenv("REQUIRE_API_KEY")
if REQUIRE_API_KEY_ENV is not None:
    REQUIRE_API_KEY = REQUIRE_API_KEY_ENV.lower() in ("true", "1", "yes")
else:
    REQUIRE_API_KEY = (ENVIRONMENT.lower() == "production")
