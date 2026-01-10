import os
import secrets
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))
    DB_FILE = os.getenv("DB_FILE", "neubot.db")
    
    # API Keys
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "") 
    BRAVE_SEARCH_TOKEN = os.getenv("BRAVE_SEARCH_TOKEN", "")
    
    # OAuth
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
    
    # Encryption
    TOKEN_ENCRYPTION_SALT = os.getenv("TOKEN_ENCRYPTION_SALT", "").encode()

    # Defaults
    DEFAULT_TIMEZONE = "America/New_York"
    
    # Rate Limits
    GUEST_WEATHER_RATE_LIMIT = 5
    GUEST_SEARCH_RATE_LIMIT = 10

    USER_WEATHER_RATE_LIMIT = 50
    USER_SEARCH_RATE_LIMIT = 100
