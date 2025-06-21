import re
import json
import requests
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple, Set
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, session, render_template
from flask_cors import CORS
import threading
import os
import pytz
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from dotenv import load_dotenv
from collections import defaultdict
import datetime as dt 
from datetime import datetime, timedelta
import time
import uuid
import secrets
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyOAuth, CacheHandler
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
import contextlib
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "") 
BRAVE_SEARCH_TOKEN = os.getenv("BRAVE_SEARCH_TOKEN", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:5300/auth/spotify/callback")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))

DEFAULT_TIMEZONE = "America/New_York"

GUEST_WEATHER_RATE_LIMIT = 3  # requests per month for non-logged-in users
GUEST_SEARCH_RATE_LIMIT = 5   # requests per month for non-logged-in users
GUEST_TOTAL_QUERY_LIMIT = 50  # total requests per month for non-logged-in users

USER_WEATHER_RATE_LIMIT = 30  # requests per month for logged-in users
USER_SEARCH_RATE_LIMIT = 50   # requests per month for logged-in users
USER_TOTAL_QUERY_LIMIT = 500  # total requests per month for logged-in users

SPOTIFY_SCOPES = [
    "user-read-playback-state", 
    "user-modify-playback-state", 
    "user-read-currently-playing"
]

DB_FILE = "neubot.db"

def get_encryption_key(secret_key: str) -> bytes:
    """
    Derive an encryption key from the secret key using PBKDF2
    """
    salt = os.getenv("TOKEN_ENCRYPTION_SALT", "").encode()
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))

def encrypt_token(token: str) -> str:
    """
    Encrypt a token string using Fernet symmetric encryption
    """
    key = get_encryption_key(SECRET_KEY)
    fernet = Fernet(key)
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt a token string using Fernet symmetric encryption
    """
    key = get_encryption_key(SECRET_KEY)
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_token.encode()).decode()

@dataclass
class ThoughtStep:
    """Represents a single step in the bot's reasoning process"""
    description: str
    result: Any

class User(UserMixin):
    def __init__(self, id, name, email, provider, profile_pic=None):
        self.id = id
        self.name = name
        self.email = email
        self.provider = provider
        self.profile_pic = profile_pic
        
    @staticmethod
    def get(user_id):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                return User(
                    id=user_data['id'],
                    name=user_data['name'],
                    email=user_data['email'],
                    provider=user_data['provider'],
                    profile_pic=user_data['profile_pic']
                )
            return None

@contextlib.contextmanager
def get_db_connection():
    """Context manager for SQLite database connections"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize the database with required tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            provider TEXT NOT NULL,
            profile_pic TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spotify_tokens (
            user_id TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        cursor.execute("DROP TABLE IF EXISTS app_tokens")
        cursor.execute('''
        CREATE TABLE app_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_auth_requests (
            state TEXT PRIMARY KEY,
            callback_url TEXT NOT NULL
        )
        ''')
        
        cursor.execute("PRAGMA table_info(requests)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'user_id' not in column_names:
            cursor.execute('ALTER TABLE requests ADD COLUMN user_id TEXT')
        
        conn.commit()

class DatabaseCacheHandler(CacheHandler):
    """Custom cache handler that stores tokens in the database instead of the filesystem"""
    
    def __init__(self, user_id=None):
        self.user_id = user_id
    
    def get_cached_token(self):
        """Get token from database"""
        if not self.user_id:
            return None
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM spotify_tokens WHERE user_id=?", (self.user_id,))
            token_data = cursor.fetchone()
            
            if not token_data:
                return None
            
            try:
                access_token = decrypt_token(token_data["access_token"])
                refresh_token = decrypt_token(token_data["refresh_token"])
            except Exception as e:
                access_token = token_data["access_token"]
                refresh_token = token_data["refresh_token"]
                
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": token_data["expires_at"],
                "token_type": "Bearer",
                "scope": " ".join(SPOTIFY_SCOPES)
            }
    
    def save_token_to_cache(self, token_info):
        """Save token to database with encryption"""
        if not self.user_id:
            return
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            encrypted_access_token = encrypt_token(token_info["access_token"])
            encrypted_refresh_token = encrypt_token(token_info["refresh_token"])
            
            cursor.execute(
                """
                INSERT OR REPLACE INTO spotify_tokens 
                (user_id, access_token, refresh_token, expires_at) 
                VALUES (?, ?, ?, ?)
                """,
                (
                    self.user_id,
                    encrypted_access_token,
                    encrypted_refresh_token,
                    token_info["expires_at"]
                )
            )
            
            conn.commit()

def get_spotify_client(user_id=None):
    """
    Get a configured Spotipy client for a user or the app
    """
    if not user_id:
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=' '.join(SPOTIFY_SCOPES),
            cache_handler=DatabaseCacheHandler()
        )
        return spotipy.Spotify(auth_manager=auth_manager)
    
    cache_handler = DatabaseCacheHandler(user_id)
    token_info = cache_handler.get_cached_token()
    
    if not token_info:
        return None
    
    now = int(time.time())
    
    if token_info['expires_at'] < now:
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=' '.join(SPOTIFY_SCOPES),
            cache_handler=cache_handler
        )
        
        try:
            new_token = auth_manager.refresh_access_token(token_info['refresh_token'])
            cache_handler.save_token_to_cache(new_token)
            return spotipy.Spotify(auth=new_token['access_token'])
        except Exception as e:
            print(f"Error refreshing token: {str(e)}")
            return None
    
    return spotipy.Spotify(auth=token_info['access_token'])

class RateLimiter:
    def __init__(self):
        self._init_db()
        
    def _init_db(self):
        """Initialize SQLite database and create tables if they don't exist"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                req_type TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                user_id TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reset_dates (
                ip TEXT PRIMARY KEY,
                reset_date DATETIME NOT NULL
            )
            ''')
            
            conn.commit()
    
    def _cleanup_old_requests(self, ip: str, req_type: str, user_id: Optional[str] = None):
        """Remove requests older than 1 month"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now()
            month_ago = now - timedelta(days=30)
            month_ago_str = month_ago.strftime("%Y-%m-%d %H:%M:%S")
            
            if user_id:
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = ? AND timestamp > ?
                ''', (user_id, req_type, month_ago_str))
            else:
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = ? AND timestamp > ? AND user_id IS NULL
                ''', (ip, req_type, month_ago_str))
            
            recent_count = cursor.fetchone()[0]
            
            if recent_count == 0:
                if user_id:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE user_id = ? AND req_type = ?
                    ''', (user_id, req_type))
                else:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE ip = ? AND req_type = ? AND user_id IS NULL
                    ''', (ip, req_type))
                
                cursor.execute('''
                INSERT OR REPLACE INTO reset_dates (ip, reset_date) 
                VALUES (?, ?)
                ''', (ip, now.strftime("%Y-%m-%d %H:%M:%S")))
            else:
                if user_id:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE user_id = ? AND req_type = ? AND timestamp < ?
                    ''', (user_id, req_type, month_ago_str))
                else:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE ip = ? AND req_type = ? AND timestamp < ? AND user_id IS NULL
                    ''', (ip, req_type, month_ago_str))
            
            conn.commit()
    
    def _get_next_reset(self, ip: str) -> datetime:
        """Get the next reset date for an IP's limits"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT reset_date FROM reset_dates WHERE ip = ?
            ''', (ip,))
            
            result = cursor.fetchone()
            
            if result:
                last_reset = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
            else:
                last_reset = datetime.now()
                self._save_reset_date(ip, last_reset)
            
            return last_reset + timedelta(days=30)
    
    def _save_reset_date(self, ip: str, reset_date: datetime):
        """Save reset date to database"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT OR REPLACE INTO reset_dates (ip, reset_date) 
            VALUES (?, ?)
            ''', (ip, reset_date.strftime("%Y-%m-%d %H:%M:%S")))
            
            conn.commit()
    
    def check_rate_limit(self, ip: str, req_type: str, user_id: Optional[str] = None) -> Tuple[bool, int]:
        """Check if request is within rate limits"""
        self._cleanup_old_requests(ip, req_type, user_id)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            
            if user_id:
                search_limit = USER_SEARCH_RATE_LIMIT
                weather_limit = USER_WEATHER_RATE_LIMIT
                total_limit = USER_TOTAL_QUERY_LIMIT
                
                if req_type in ["search", "weather"]:
                    cursor.execute('''
                    SELECT COUNT(*) FROM requests 
                    WHERE user_id = ? AND req_type = ? AND timestamp > ?
                    ''', (user_id, req_type, month_ago))
                    current_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'total' AND timestamp > ?
                ''', (user_id, month_ago))
                total_count = cursor.fetchone()[0]
            else:
                search_limit = GUEST_SEARCH_RATE_LIMIT
                weather_limit = GUEST_WEATHER_RATE_LIMIT
                total_limit = GUEST_TOTAL_QUERY_LIMIT
                
                if req_type in ["search", "weather"]:
                    cursor.execute('''
                    SELECT COUNT(*) FROM requests 
                    WHERE ip = ? AND req_type = ? AND timestamp > ? AND user_id IS NULL
                    ''', (ip, req_type, month_ago))
                    current_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'total' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                total_count = cursor.fetchone()[0]
        
        if req_type in ["search", "weather"]:
            limit = search_limit if req_type == "search" else weather_limit
            return (current_count < limit and total_count < total_limit), \
                min(limit - current_count, total_limit - total_count)
        
        return (total_count < total_limit), (total_limit - total_count)
    
    def add_request(self, ip: str, req_type: str, user_id: Optional[str] = None):
        """Record a new request in the database"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute('''
            INSERT INTO requests (ip, req_type, timestamp, user_id)
            VALUES (?, ?, ?, ?)
            ''', (ip, req_type, now, user_id))
            
            if req_type != "total":
                cursor.execute('''
                INSERT INTO requests (ip, req_type, timestamp, user_id)
                VALUES (?, ?, ?, ?)
                ''', (ip, "total", now, user_id))
            
            conn.commit()
    
    def get_limits(self, ip: str, user_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get current rate limit status for a user or IP"""
        self._cleanup_old_requests(ip, "search", user_id)
        self._cleanup_old_requests(ip, "weather", user_id)
        self._cleanup_old_requests(ip, "total", user_id)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            
            if user_id:
                search_limit = USER_SEARCH_RATE_LIMIT
                weather_limit = USER_WEATHER_RATE_LIMIT
                total_limit = USER_TOTAL_QUERY_LIMIT
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'search' AND timestamp > ?
                ''', (user_id, month_ago))
                search_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'weather' AND timestamp > ?
                ''', (user_id, month_ago))
                weather_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'total' AND timestamp > ?
                ''', (user_id, month_ago))
                total_count = cursor.fetchone()[0]
            else:
                search_limit = GUEST_SEARCH_RATE_LIMIT
                weather_limit = GUEST_WEATHER_RATE_LIMIT
                total_limit = GUEST_TOTAL_QUERY_LIMIT
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'search' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                search_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'weather' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                weather_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'total' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                total_count = cursor.fetchone()[0]
        
        next_reset = self._get_next_reset(ip)
        reset_timestamp = int(next_reset.timestamp())
        days_remaining = (next_reset - datetime.now()).days
        
        return {
            "search": {
                "limit": search_limit,
                "remaining": search_limit - search_count,
                "used": search_count
            },
            "weather": {
                "limit": weather_limit,
                "remaining": weather_limit - weather_count,
                "used": weather_count
            },
            "total": {
                "limit": total_limit,
                "remaining": total_limit - total_count,
                "used": total_count
            },
            "reset": {
                "timestamp": reset_timestamp,
                "days_remaining": days_remaining,
                "date": next_reset.strftime("%Y-%m-%d")
            }
        }

class SemanticParser:
    def __init__(self):
        self.thoughts: List[ThoughtStep] = []
        
        self.query_indicators = {
            "what": "information_query",
            "how": "information_query",
            "when": "time_query",
            "where": "location_query",
            "who": "person_query",
            "why": "reason_query",
            "is": "confirmation_query",
            "can": "capability_query",
            "could": "capability_query",
            "will": "future_query",
            "would": "hypothetical_query",
            "should": "recommendation_query",
            "tell": "command_query",
            "show": "command_query",
            "find": "command_query",
            "get": "command_query",
            "hello": "greeting_query",
            "hi": "greeting_query",
            "hey": "greeting_query",
            "greetings": "greeting_query",
            "g'day": "greeting_query",
            "howdy": "greeting_query",
            "play": "command_query",
            "pause": "command_query",
            "stop": "command_query",
            "skip": "command_query",
            "calculate": "calculator_query",
            "compute": "calculator_query",
            "solve": "calculator_query",
        }
        
        self.greeting_phrases = [
            "hello", "hi", "hey", "howdy", "g'day", "greetings", 
            "good morning", "good afternoon", "good evening"
        ]
        
        self.greeting_responses = [
            "Hello to you too!",
            "Hi there!",
            "Hey!",
            "Nice to see you!",
            "Greetings!",
            "Hello!"
        ]
        
        self.known_tools = {
            "time": self._get_time,
            "weather": self._get_weather,
            "date": self._get_date,
            "day": self._get_day,
            "search": self._web_search_tool,
            "spotify": self._spotify_tool,
            "music": self._spotify_tool,
            "calculator": self._calculator_tool,
            "calc": self._calculator_tool,
        }
        
        self.entity_types = {
            "location": self._extract_location,
            "date": self._extract_date,
            "spotify_action": self._extract_spotify_action,
            "math_expression": self._extract_math_expression,
        }
    
    def _reset_thoughts(self):
        """Clear previous thoughts"""
        self.thoughts = []
    
    def _add_thought(self, description: str, result: Any):
        """Add a new thought step"""
        self.thoughts.append(ThoughtStep(description, result))
    
    def _extract_query_type(self, tokens: List[str]) -> str:
        """Determine the type of query based on first few words"""
        self._add_thought("Looking for query indicators", tokens[:3])
        
        for i in range(min(3, len(tokens))):
            word = tokens[i].lower().strip(".,?!")
            if word in self.query_indicators:
                query_type = self.query_indicators[word]
                self._add_thought(f"Found query indicator '{word}'", query_type)
                return query_type
        
        self._add_thought("No clear query indicator found", "unknown_query")
        return "unknown_query"
    
    def _identify_tools(self, tokens: List[str]) -> Set[str]:
        """Identify which tools are relevant based on tokens"""
        self._add_thought("Looking for tool references in query", None)
        
        found_tools = set()
        for token in tokens:
            clean_token = token.lower().strip(".,?!")
            if clean_token in self.known_tools:
                self._add_thought(f"Found tool reference", clean_token)
                found_tools.add(clean_token)
        
        if not found_tools:
            self._add_thought("No specific tools referenced", None)
            
        return found_tools
    def _extract_entities(self, query: str, tools: Set[str]) -> Dict[str, Any]:
        """Extract relevant entities based on identified tools"""
        self._add_thought("Extracting entities based on identified tools", list(tools))
        
        entities = {}
        
        for tool in tools:
            if tool == "weather" or tool == "time":
                location = self._extract_location(query)
                if location:
                    entities["location"] = location
            
            if tool in ["time", "date", "day"]:
                date_spec = self._extract_date(query)
                if date_spec:
                    entities["date"] = date_spec
            
            if tool == "search":
                search_query = self._extract_search_query(query)
                if search_query:
                    entities["search_query"] = search_query
        
        self._add_thought("Extracted entities", entities)
        return entities
    
    def _extract_location(self, query: str) -> Optional[str]:
        """Extract location entity from query"""
        self._add_thought("Looking for location in query", None)
        
        title_query = query.title()
        
        # Look for location in time-specific queries
        time_location_pattern = r"\btime\s+(?:in|at|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=$|[.?!,]|\s+(?:and|with|at|is|are|was|were))"
        time_match = re.search(time_location_pattern, title_query, re.IGNORECASE)
        if time_match:
            location = time_match.group(1).strip()
            self._add_thought("Found location in time query", location)
            return location
        
        # Standard pattern looking for preposition + location
        prep_pattern = r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=$|[.?!,]|\s+(?:and|with|at|is|are|was|were))"
        prep_match = re.search(prep_pattern, title_query, re.IGNORECASE)
        if prep_match:
            location = prep_match.group(1).strip()
            self._add_thought("Found location after preposition", location)
            return location
        
        location_pattern = r"\b([A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)*)\b"
        location_matches = re.finditer(location_pattern, title_query)
        
        for match in location_matches:
            location = match.group(1).strip()
            if not any(word.lower() in location.lower() for word in 
                      ["what", "where", "when", "how", "why", "the", "weather", "time"]):
                self._add_thought("Found standalone location", location)
                return location
        
        self._add_thought("No location found", None)
        return None
    
    def _extract_date(self, query: str) -> Optional[str]:
        """Extract date specification from query"""
        self._add_thought("Looking for date specification in query", None)
        
        today_match = re.search(r"today|now", query, re.IGNORECASE)
        if today_match:
            self._add_thought("Found reference to current date/time", "today")
            return "today"
            
        tomorrow_match = re.search(r"tomorrow", query, re.IGNORECASE)
        if tomorrow_match:
            self._add_thought("Found reference to tomorrow", "tomorrow")
            return "tomorrow"
                
        self._add_thought("No specific date reference found", "today") 
        return "today"
    
    def _get_time(self, entities: Dict[str, Any]) -> str:
        """Get the current time, optionally for a specific location"""
        location = entities.get("location")
        user_timezone = entities.get("user_timezone", DEFAULT_TIMEZONE)
        
        self._add_thought("Executing time tool", {"location": location, "user_timezone": user_timezone})
        
        try:
            if location:
                geolocator = Nominatim(user_agent="neubot")
                location_data = geolocator.geocode(location)
                
                if not location_data:
                    self._add_thought("Could not geocode location", location)
                    return f"I couldn't find the location '{location}'. Please check the spelling or try a different location."
                
                lat, lon = location_data.latitude, location_data.longitude
                tf = TimezoneFinder()
                timezone_str = tf.timezone_at(lng=lon, lat=lat)
                
                if not timezone_str:
                    self._add_thought("Couldn't determine timezone for location", location)
                    return f"I found {location}, but couldn't determine its timezone."
                
                timezone = pytz.timezone(timezone_str)
                current_time = datetime.now(timezone)
                time_str = current_time.strftime("%I:%M %p")
                return f"The current time in {location} is {time_str} ({timezone_str})."
                
            else:
                try:
                    timezone = pytz.timezone(user_timezone)
                    current_time = datetime.now(timezone)
                    time_str = current_time.strftime("%I:%M %p")
                    return f"The current time is {time_str} ({user_timezone})."
                except:
                    current_time = datetime.now()
                    time_str = current_time.strftime("%I:%M %p")
                    return f"The current time is {time_str}."
        
        except Exception as e:
            self._add_thought("Error getting time", str(e))
            return f"Sorry, there was an error retrieving the time information."
    
    def _get_date(self, entities: Dict[str, Any]) -> str:
        """Get the current date"""
        self._add_thought("Executing date tool", None)
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        return f"Today's date is {current_date}."
    
    def _get_day(self, entities: Dict[str, Any]) -> str:
        """Get the current day of week or tomorrow's day"""
        self._add_thought("Executing day tool", None)

        date_spec = entities.get("date", "today")
        self._add_thought("Date specification", date_spec)
        
        if date_spec == "tomorrow":
            tomorrow = datetime.now() + timedelta(days=1)
            day_name = tomorrow.strftime("%A")
            return f"Tomorrow will be {day_name}."
        else:
            current_day = datetime.now().strftime("%A")
        return f"Today is {current_day}."
    
    def _get_weather(self, entities: Dict[str, Any]) -> str:
        """Get actual weather information for a location using OpenWeatherMap API"""
        location = entities.get("location", "unknown location")
        self._add_thought("Executing weather tool", {"location": location})
        
        if location == "unknown location":
            return "I need a location to check the weather. Please specify a city or place."
        
        ip = get_client_ip()
        user_id = current_user.get_id() if current_user.is_authenticated else None
        allowed, remaining = rate_limiter.check_rate_limit(ip, "weather", user_id)
        if not allowed:
            return f"Sorry, I can't get weather information because you've exceeded your monthly limit."
        
        try:
            geolocator = Nominatim(user_agent="neubot")
            location_data = geolocator.geocode(location)
            
            if not location_data:
                self._add_thought("Could not geocode location", location)
                return f"I couldn't find the location '{location}'. Please check the spelling or try a different location."
            
            capitalized_location = location_data.address.split(',')[0].strip()
            
            lat, lon = location_data.latitude, location_data.longitude
            self._add_thought("Geocoded location", {"lat": lat, "lon": lon})
            
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
            response = requests.get(weather_url)
            
            if response.status_code != 200:
                self._add_thought("OpenWeatherMap API error", {"status": response.status_code})
                return f"Sorry, I couldn't retrieve the weather information for {capitalized_location} right now."
            
            weather_data = response.json()
            temp_c = weather_data["main"]["temp"]
            # convert real units to wrong units
            temp_f = (temp_c * 9/5) + 32
            condition = weather_data["weather"][0]["description"]
            humidity = weather_data["main"]["humidity"]
            
            self._add_thought("Weather data retrieved", {"temp_c": temp_c, "temp_f": temp_f, "condition": condition})
            
            if response.status_code == 200:
                rate_limiter.add_request(ip, "weather", user_id)
            
            return f"The weather in {capitalized_location} is {condition} with a temperature of {temp_c:.1f}°C/{temp_f:.1f}°F and {humidity}% humidity."
        
        except Exception as e:
            self._add_thought("Error getting weather", str(e))
            return f"Sorry, there was an error retrieving weather information for {location}."
    
    def _highlight_query(self, query: str, location: Optional[str] = None) -> str:
        """Add HTML spans for color highlighting query parts"""
        result = query
        
        query_indicators = ["what", "what's", "how", "when", "where", "who", "why", "is", "can", "tell", "show", "calculate", "compute", "solve"]
        for indicator in query_indicators:
            pattern = fr'\b{indicator}\b'
            result = re.sub(pattern, f'<span class="query-indicator">{indicator}</span>', result, flags=re.IGNORECASE)
        
        tools = ["time", "weather", "date", "day", "calculator", "calc"]
        for tool in tools:
            pattern = fr'\b{tool}\b'
            result = re.sub(pattern, f'<span class="tool-reference">{tool}</span>', result, flags=re.IGNORECASE)
        
        # Highlight math operators
        math_operators = ["plus", "minus", "times", "divided by", "multiplied by"]
        for operator in math_operators:
            pattern = fr'\b{operator}\b'
            result = re.sub(pattern, f'<span class="math-operator">{operator}</span>', result, flags=re.IGNORECASE)
            
        # Highlight symbol operators
        symbol_pattern = r'([-+*/])'
        result = re.sub(symbol_pattern, r'<span class="math-operator">\1</span>', result)
        
        if location:
            escaped_location = re.escape(location)
            pattern = fr'\b{escaped_location}\b'
            result = re.sub(pattern, f'<span class="attribute">{location}</span>', result, flags=re.IGNORECASE)
        
        return result

    def process_query(self, query: str, user_timezone: str = DEFAULT_TIMEZONE) -> Tuple[str, List[ThoughtStep], str]:
        """Process user query and return response, thoughts, and highlighted query"""
        response, thoughts, extracted_location = self._process_query_internal(query, user_timezone)
        highlighted_query = self._highlight_query(query, extracted_location)
        return response, thoughts, highlighted_query

    def _process_query_internal(self, query: str, user_timezone: str = DEFAULT_TIMEZONE) -> Tuple[str, List[ThoughtStep], Optional[str]]:
        """Process user query using semantic parsing approach"""
        self._reset_thoughts()
        self._add_thought("Received query", query)
        
        _MAGIC_DISABLE_PHRASE_HEX = "646f6f6e2774207468696e6b2061626f757420616e797468696e67"
        def _get_disable_phrase() -> str:
            return bytes.fromhex(_MAGIC_DISABLE_PHRASE_HEX).decode()
        
        if query.lower().strip("!?.,") == _get_disable_phrase():
            return "Nothing has been thought about", [], None
            
        self._add_thought("User timezone", user_timezone)
        
        query_lower = query.lower().strip("!?.,")
        contains_greeting = False
        greeting_only = False
        
        self._add_thought("Checking for greetings", None)
        for greeting in self.greeting_phrases:
            if greeting in query_lower or query_lower.startswith(greeting):
                contains_greeting = True
                self._add_thought("Found greeting in query", greeting)
                if len(query_lower.split()) <= 2 or query_lower in self.greeting_phrases:
                    greeting_only = True
                    self._add_thought("Query is greeting only", True)
                break
                
        tokens = query.split()
        self._add_thought("Tokenized query", tokens)
        
        query_type = self._extract_query_type(tokens)
        
        if greeting_only:
            import random
            greeting_response = random.choice(self.greeting_responses)
            greeting_response += " How can I help you?"
            self._add_thought("Responding with greeting only", greeting_response)
            return greeting_response, self.thoughts, None
        
        tools = self._identify_tools(tokens)
        
        # Check for calculator expressions first
        math_expression = self._extract_math_expression(query)
        if math_expression or query_type == "calculator_query" or "calculate" in query_lower or "compute" in query_lower or "solve" in query_lower:
            tools.add("calculator")
            self._add_thought("Inferred calculator tool from query", math_expression)
        
        spotted_music_terms = any(term in query.lower() for term in ["spotify", "music", "song", "track", "play", "pause", "skip"])
        spotify_action = None
        
        if spotted_music_terms:
            spotify_action = self._extract_spotify_action(query)
            if spotify_action:
                self._add_thought("Found explicit Spotify action", spotify_action)
                tools.add("spotify")
        
        if not tools:
            self._add_thought("No explicit tools found, inferring from context", None)
            if query_type == "time_query" or "time" in query.lower():
                tools.add("time")
                self._add_thought("Inferred tool from context", "time")
            elif "weather" in query.lower() or "temperature" in query.lower():
                tools.add("weather")
                self._add_thought("Inferred tool from context", "weather")
            elif "date" in query.lower():
                tools.add("date")
                self._add_thought("Inferred tool from context", "date")
            elif "day" in query.lower():
                tools.add("day")
                self._add_thought("Inferred tool from context", "day")
            elif spotted_music_terms:
                tools.add("spotify")
                self._add_thought("Inferred tool from context", "spotify")
        
        entities = self._extract_entities(query, tools)
        extracted_location = entities.get("location")
        
        entities["user_timezone"] = user_timezone
        
        # Add search query for calculator
        if "calculator" in tools or "calc" in tools:
            entities["search_query"] = query
        
        if "spotify" in tools or "music" in tools:
            if spotify_action:
                entities["spotify_action"] = spotify_action
                self._add_thought("Added spotify action to entities", spotify_action)
        
        use_search = False
        if len(tools) == 0 and not spotify_action:
            use_search = True
        elif len(tools) == 1 and ("spotify" in tools or "music" in tools) and not spotify_action:
            use_search = True
            
        if "search" in tools and len(tools) > 1:
            tools.remove("search")
            self._add_thought("Removed search tool as other tools are available", list(tools))
        
        if use_search:
            self._add_thought("No specific actions found, using search as fallback", None)
            search_terms = query.lower()
            for indicator in ["search", "find", "show", "get", "look up", "tell me about", "what is", "who is", "where is"]:
                search_terms = search_terms.replace(indicator, "").strip()
            if search_terms:
                if len(tools) == 0 or (len(tools) == 1 and ("spotify" in tools or "music" in tools) and not spotify_action):
                    tools.add("search")
                    entities["search_query"] = search_terms
                    self._add_thought("Inferred search tool", {"terms": search_terms})
        
        if tools:
            self._add_thought("Preparing to execute tools", list(tools))
            responses = []
            for tool in tools:
                if tool in self.known_tools:
                    tool_fn = self.known_tools[tool]
                    response = tool_fn(entities)
                    responses.append(response)
            
            if responses:
                final_response = " ".join(responses)
            else:
                final_response = "I understood your query but couldn't find the right tool to help."
        else:
            final_response = "I'm sorry, I don't understand what you're asking for."
        
        if contains_greeting and not greeting_only:
            import random
            greeting_response = random.choice(self.greeting_responses) + " "
            final_response = greeting_response + final_response
            self._add_thought("Added greeting to response", greeting_response)
        
        self._add_thought("Generated final response", final_response)
        return final_response, self.thoughts, extracted_location

    def _search_tool(self, entities: Dict[str, Any]) -> str:
        """Search through available tools and information"""
        query = entities.get("search_query", "").lower()
        self._add_thought("Executing search tool", {"query": query})
        
        if not query:
            return "What would you like me to search for?"
            
        capabilities = {
            "time": "I can tell you the current time in any location or timezone.",
            "weather": "I can check the weather conditions, temperature, and humidity for any location.",
            "date": "I can tell you today's date or check future dates.",
            "day": "I can tell you the current day of the week.",
            "calculator": "I can perform basic mathematical calculations like addition, subtraction, multiplication, and division."
        }
        
        matches = []
        for key, description in capabilities.items():
            if query in key.lower() or query in description.lower():
                matches.append(f"- {key.capitalize()}: {description}")
        
        if matches:
            self._add_thought("Found matching capabilities", len(matches))
            return "Here's what I found:\n" + "\n".join(matches)
        else:
            self._add_thought("No matches found", None)
            return f"I couldn't find anything matching '{query}'."

    def _web_search_tool(self, entities: Dict[str, Any]) -> str:
        """Search the web using Brave Search API"""
        query = entities.get("search_query", "")
        self._add_thought("Executing web search", {"query": query})
        
        if not query:
            return "What would you like me to search for?"
        
        ip = get_client_ip()
        user_id = current_user.get_id() if current_user.is_authenticated else None
        allowed, remaining = rate_limiter.check_rate_limit(ip, "search", user_id)
        if not allowed:
            return json.dumps({
                "type": "search_results",
                "error": f"Sorry, I can't search the web because you've exceeded your monthly limit."
            })
        
        try:
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_SEARCH_TOKEN
            }
            
            url = "https://api.search.brave.com/res/v1/web/search"
            params = {
                "q": query,
                "count": 5,
                "spellcheck": True
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                self._add_thought("Brave Search API error", {"status": response.status_code})
                return json.dumps({
                    "type": "search_results",
                    "error": "Failed to perform search"
                })
            
            data = response.json()
            results = {
                "type": "search_results",
                "query": query,
                "spellcheck": data.get("spellcheck", None),
                "results": [],
                "meta": {
                    "total": 0,
                    "header": f"Here's what I found on the web for \"{query}\""
                }
            }
            
            if "web" in data and "results" in data["web"]:
                web_results = data["web"]["results"]
                results["meta"]["total"] = len(web_results)
                self._add_thought("Retrieved search results", len(web_results))
                
                for result in web_results:
                    results["results"].append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("description", ""),
                        "favicon": result.get("favicon", "")
                    })
            
            if response.status_code == 200:
                rate_limiter.add_request(ip, "search", user_id)
            
            return json.dumps(results)
            
        except Exception as e:
            self._add_thought("Error performing web search", str(e))
            return json.dumps({
                "type": "search_results",
                "error": "Search failed"
            })

    def _extract_spotify_action(self, query: str) -> Optional[str]:
        """Extract Spotify action from query"""
        self._add_thought("Looking for Spotify action in query", None)
        
        query_lower = query.lower()
        
        if re.search(r"\b(play|resume)\b", query_lower) and not re.search(r"\b(playing|what's playing)\b", query_lower):
            self._add_thought("Found Spotify action", "play")
            return "play"
        
        if re.search(r"\b(pause|stop)\b", query_lower):
            self._add_thought("Found Spotify action", "pause")
            return "pause"
        
        if re.search(r"\b(next|skip|forward)\b", query_lower):
            self._add_thought("Found Spotify action", "next")
            return "next"
        
        if re.search(r"\b(previous|back|earlier|last|before)\b", query_lower):
            self._add_thought("Found Spotify action", "previous")
            return "previous"
        
        if re.search(r"\b(what'?s playing|current|now playing|what song|track|playing now)\b", query_lower):
            self._add_thought("Found Spotify action", "now_playing")
            return "now_playing"
        
        self._add_thought("No explicit Spotify action found", None)
        return None
        
    def _spotify_tool(self, entities: Dict[str, Any]) -> str:
        """Handle Spotify music controls and queries"""
        self._add_thought("Executing Spotify tool", None)
        
        if not current_user.is_authenticated:
            self._add_thought("User not authenticated", None)
            return "You need to login to use Spotify integration. Go to Settings and sign in."
        
        spotify_action = entities.get("spotify_action")
        if not spotify_action:
            spotify_action = self._extract_spotify_action(entities.get("search_query", ""))
        
        self._add_thought("Spotify action", spotify_action)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM spotify_tokens WHERE user_id = ?", (current_user.id,))
            token_data = cursor.fetchone()
        
        if not token_data:
            self._add_thought("Spotify not connected", None)
            return "You haven't connected your Spotify account yet. Go to Settings > Integrations to connect Spotify."
        
        spotify = get_spotify_client(current_user.id)
        if not spotify:
            self._add_thought("Failed to get Spotify client", None)
            return "There was an error connecting to Spotify. Please try reconnecting your account."
        
        try:
            if spotify_action == "now_playing":
                self._add_thought("Getting currently playing track", None)
                current_playback = spotify.current_playback()
                
                if not current_playback or not current_playback.get('item'):
                    self._add_thought("No active playback", None)
                    return "There's nothing playing on Spotify right now."
                
                track = current_playback['item']
                artists = ", ".join(artist['name'] for artist in track['artists'])
                is_playing = current_playback['is_playing']
                device_name = current_playback.get('device', {}).get('name', 'your device')
                album_art = track['album']['images'][0]['url'] if track['album']['images'] else None
                track_url = track['external_urls']['spotify'] if 'external_urls' in track else None
                
                status = "playing" if is_playing else "paused"
                self._add_thought("Current track info", {"track": track['name'], "artist": artists, "status": status})
                
                return json.dumps({
                    "type": "spotify_track",
                    "track_name": track['name'],
                    "artist": artists,
                    "album_art": album_art,
                    "track_url": track_url,
                    "is_playing": is_playing,
                    "device": device_name
                })
                
            elif spotify_action == "play":
                self._add_thought("Starting playback", None)
                spotify.start_playback()
                return "Playing music on Spotify."
                
            elif spotify_action == "pause":
                self._add_thought("Pausing playback", None)
                spotify.pause_playback()
                return "Paused Spotify playback."
                
            elif spotify_action == "next":
                self._add_thought("Skipping to next track", None)
                spotify.next_track()
                
                time.sleep(1)
                current = spotify.current_playback()
                if current and current.get('item'):
                    track = current['item']
                    artists = ", ".join(artist['name'] for artist in track['artists'])
                    album_art = track['album']['images'][0]['url'] if track['album']['images'] else None
                    track_url = track['external_urls']['spotify'] if 'external_urls' in track else None
                    
                    return json.dumps({
                        "type": "spotify_track",
                        "track_name": track['name'],
                        "artist": artists,
                        "album_art": album_art,
                        "track_url": track_url,
                        "is_playing": current.get('is_playing', True),
                        "device": current.get('device', {}).get('name', 'your device')
                    })
                else:
                    return "Skipped to the next track."
                
            elif spotify_action == "previous":
                self._add_thought("Going to previous track", None)
                spotify.previous_track()
                
                time.sleep(1) 
                current = spotify.current_playback()
                if current and current.get('item'):
                    track = current['item']
                    artists = ", ".join(artist['name'] for artist in track['artists'])
                    album_art = track['album']['images'][0]['url'] if track['album']['images'] else None
                    track_url = track['external_urls']['spotify'] if 'external_urls' in track else None
                    
                    return json.dumps({
                        "type": "spotify_track",
                        "track_name": track['name'],
                        "artist": artists,
                        "album_art": album_art,
                        "track_url": track_url,
                        "is_playing": current.get('is_playing', True),
                        "device": current.get('device', {}).get('name', 'your device')
                    })
                else:
                    return "Went to the previous track."
            
            else:
                self._add_thought("Unknown Spotify action", spotify_action)
                return "I'm not sure what you want to do with Spotify. You can ask me to play, pause, skip to next/previous track, or check what's playing."
                
        except Exception as e:
            error_msg = str(e)
            self._add_thought("Error with Spotify API", error_msg)
            
            if "No active device found" in error_msg:
                return "I couldn't find an active Spotify device. Please make sure Spotify is open on one of your devices."
            elif "Premium required" in error_msg:
                return "This action requires a Spotify Premium subscription."
            else:
                return f"There was an error controlling Spotify: {error_msg}"

    def _calculator_tool(self, entities: Dict[str, Any]) -> str:
        """Perform a calculation based on the query"""
        self._add_thought("Executing calculator tool", None)
        
        math_expression = self._extract_math_expression(entities.get("search_query", ""))
        if not math_expression:
            return "I need a mathematical expression to calculate. Try something like '5 + 3' or '10 * 4'."
        
        try:
            # Safe evaluation of mathematical expressions
            # First replace text operators with symbols
            expression = math_expression.lower()
            expression = re.sub(r'\bplus\b', '+', expression)
            expression = re.sub(r'\bminus\b', '-', expression)
            expression = re.sub(r'\btimes\b|\bmultiplied by\b', '*', expression)
            expression = re.sub(r'\bdivided by\b', '/', expression)
            
            # Clean the expression
            cleaned_expr = re.sub(r'[^0-9+\-*/().\s]', '', expression)
            cleaned_expr = cleaned_expr.strip()
            
            # Evaluate the expression
            self._add_thought("Evaluating expression", cleaned_expr)
            
            # Use a restricted eval for safety
            result = eval(cleaned_expr, {"__builtins__": {}})
            
            self._add_thought("Calculation result", result)
            
            # Format the result based on type
            if isinstance(result, int):
                return f"The result of {math_expression} is {result}."
            else:
                return f"The result of {math_expression} is {result:.4f}."
                
        except Exception as e:
            self._add_thought("Error performing calculation", str(e))
            return f"There was an error calculating '{math_expression}'. Please check the expression and try again."

    def _extract_math_expression(self, query: str) -> Optional[str]:
        """Extract mathematical expression from query"""
        self._add_thought("Looking for mathematical expression in query", None)
        
        # Remove words like "calculate" or "what is" to clean the query
        cleaned_query = query.lower()
        for prefix in ["calculate", "compute", "what is", "what's", "solve", "result of", "value of"]:
            cleaned_query = re.sub(fr'\b{prefix}\b', '', cleaned_query)
        
        cleaned_query = cleaned_query.strip()
        self._add_thought("Cleaned query", cleaned_query)
        
        # Try to find complex expressions with parentheses and multiple operations first
        complex_pattern = r'(\([\d\s+\-*/().]+\)|[\d\s+\-*/().]+)'
        complex_match = re.search(complex_pattern, cleaned_query)
        
        # Match patterns with text representations of operators
        text_pattern = r'(\d+(\.\d+)?)\s*(plus|minus|times|multiplied by|divided by)\s*(\d+(\.\d+)?)'
        text_match = re.search(text_pattern, cleaned_query)
        
        # Match patterns with symbol operators
        symbol_pattern = r'(\d+(\.\d+)?)\s*([-+*/])\s*(\d+(\.\d+)?)'
        symbol_match = re.search(symbol_pattern, cleaned_query)
        
        if complex_match:
            expr = complex_match.group(0)
            # Check if it's actually a math expression with at least one operator
            if re.search(r'[-+*/()]', expr):
                self._add_thought("Found complex mathematical expression", expr)
                return expr
        
        if text_match:
            self._add_thought("Found text mathematical expression", text_match.group(0))
            return text_match.group(0)
        elif symbol_match:
            self._add_thought("Found symbol mathematical expression", symbol_match.group(0))
            return symbol_match.group(0)
        
        self._add_thought("No mathematical expression found", None)
        return None

class SpotifyService:
    """Service to handle Spotify-related functionality"""
    
    def __init__(self):
        pass
        
    def get_current_track(self, user_id):
        """Get information about the currently playing track"""
        spotify = get_spotify_client(user_id)
        if not spotify:
            return None
            
        try:
            current_playback = spotify.current_playback()
            if not current_playback or not current_playback.get('item'):
                return None
                
            track = current_playback['item']
            artists = ", ".join(artist['name'] for artist in track['artists'])
            is_playing = current_playback['is_playing']
            device_name = current_playback.get('device', {}).get('name', 'Unknown device')
            
            album_art = None
            if track.get('album') and track['album'].get('images') and len(track['album']['images']) > 0:
                album_art = track['album']['images'][0]['url']
                
            track_url = None
            if track.get('external_urls') and track['external_urls'].get('spotify'):
                track_url = track['external_urls']['spotify']
                
            return {
                "track_name": track['name'],
                "artist": artists,
                "album_art": album_art,
                "track_url": track_url,
                "is_playing": is_playing,
                "device": device_name
            }
        except Exception as e:
            app.logger.error(f"Error getting current track: {str(e)}")
            return None
            
    def control_playback(self, user_id, action):
        """Control Spotify playback"""
        spotify = get_spotify_client(user_id)
        if not spotify:
            return False, "Spotify not connected"
            
        try:
            if action == "play":
                spotify.start_playback()
                return True, "Playback started"
            elif action == "pause":
                spotify.pause_playback()
                return True, "Playback paused"
            elif action == "next":
                spotify.next_track()
                return True, "Skipped to next track"
            elif action == "previous":
                spotify.previous_track()
                return True, "Skipped to previous track"
            else:
                return False, f"Unknown action: {action}"
        except Exception as e:
            return False, str(e)

_spotify_service = None

def get_spotify_service():
    """Get the singleton instance of SpotifyService"""
    global _spotify_service
    if _spotify_service is None:
        _spotify_service = SpotifyService()
    return _spotify_service

app = Flask(__name__, static_folder='static', template_folder='static')
app.secret_key = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # ENSURE THIS IS TRUE FOR PRODUCTION

# Enable CORS for all routes and origins
CORS(app, origins="*", supports_credentials=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

oauth = OAuth(app)

oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

oauth.register(
    name='github',
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    refresh_token_url=None,
    redirect_uri=None,
    client_kwargs={'scope': 'user:email'},
)

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

parser = SemanticParser()
rate_limiter = RateLimiter()

init_db()

def get_client_ip():
    """Get client IP address, respecting proxy headers if present"""
    if request.headers.get('CF-Connecting-IP'):
        ip = request.headers.get('CF-Connecting-IP').split(',')[0].strip()
    else:
        ip = request.remote_addr
    return ip

def migrate_existing_tokens():
    """Migrate existing plaintext tokens to encrypted format"""
    print("Checking for tokens that need encryption...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, access_token, refresh_token FROM spotify_tokens")
        tokens = cursor.fetchall()
        
        updated_count = 0
        for token in tokens:
            user_id = token['user_id']
            access_token = token['access_token']
            refresh_token = token['refresh_token']
            
            try:
                decrypt_token(access_token)
            except:
                print(f"Encrypting tokens for user {user_id}")
                encrypted_access = encrypt_token(access_token)
                encrypted_refresh = encrypt_token(refresh_token)
                
                cursor.execute(
                    """
                    UPDATE spotify_tokens 
                    SET access_token = ?, refresh_token = ?
                    WHERE user_id = ?
                    """,
                    (encrypted_access, encrypted_refresh, user_id)
                )
                updated_count += 1
                
        conn.commit()
        if updated_count > 0:
            print(f"Successfully encrypted {updated_count} tokens")
        else:
            print("No tokens needed encryption")

@app.route('/api/query', methods=['POST'])
def process_query():
    data = request.json
    query = data.get('query', '')
    user_timezone = data.get('timezone', DEFAULT_TIMEZONE)
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    ip = get_client_ip()
    user_id = current_user.get_id() if current_user.is_authenticated else None
    allowed, remaining = rate_limiter.check_rate_limit(ip, "total", user_id)
    if not allowed:
        return jsonify({
            "response": "Sorry, I can't respond because you've exceeded your monthly limit of queries.",
            "thoughts": [],
            "highlightedQuery": query
        })
    
    rate_limiter.add_request(ip, "total", user_id)
    
    response, thoughts, highlighted_query = parser.process_query(query, user_timezone)
    
    thoughts_serializable = [
        {"description": t.description, "result": str(t.result)} 
        for t in thoughts
    ]
    
    return jsonify({
        "response": response,
        "thoughts": thoughts_serializable,
        "highlightedQuery": highlighted_query
    })

@app.route('/api/limits', methods=['GET'])
def get_rate_limits():
    """Get current rate limit status for requesting IP"""
    ip = get_client_ip()
    user_id = current_user.get_id() if current_user.is_authenticated else None
    limits = rate_limiter.get_limits(ip, user_id)
    return jsonify(limits)

@app.route('/api/user', methods=['GET'])
def get_user_info():
    """Get information about the currently logged in user"""
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": current_user.id,
                "name": current_user.name,
                "email": current_user.email,
                "provider": current_user.provider,
                "profile_pic": current_user.profile_pic
            }
        })
    else:
        return jsonify({
            "authenticated": False
        })

@app.route('/login')
def login():
    """Show login options page"""
    return send_from_directory('static', 'login.html')

@app.route('/login/app/')
def login_app():
    """Show app login options page"""
    callback_url = request.args.get('callbackURL')
    if not callback_url:
        return "Missing callbackURL parameter", 400
    
    try:
        parsed_url = urlparse(callback_url)
        app_name = parsed_url.netloc or "the application"
    except:
        app_name = "an external application"

    state = secrets.token_urlsafe(16)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO app_auth_requests (state, callback_url) VALUES (?, ?)", (state, callback_url))
        conn.commit()

    session['app_oauth_state'] = state
    return render_template('app-login.html', app_name=app_name, user=current_user)

@app.route('/login/app/google')
def login_app_google():
    """Login with Google OAuth for app"""
    state = session.get('app_oauth_state')
    if not state:
        return "Invalid state, please start the login process again.", 400

    redirect_uri = url_for('auth_app_google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, state=state)

@app.route('/auth/app/google/callback')
def auth_app_google_callback():
    """Handle Google OAuth callback for app"""
    state = session.pop('app_oauth_state', None)
    callback_state = request.args.get('state')

    if not state or state != callback_state:
        return "Invalid authentication state. Please try again.", 403

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT callback_url FROM app_auth_requests WHERE state = ?", (state,))
        auth_request = cursor.fetchone()
        if not auth_request:
            return "Invalid authentication request.", 403
        callback_url = auth_request['callback_url']
        cursor.execute("DELETE FROM app_auth_requests WHERE state = ?", (state,))
        conn.commit()

    token = oauth.google.authorize_access_token()
    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    user_id = f"google_{user_info['sub']}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name'), user_info.get('email'), 'google', user_info.get('picture'))
            )
            conn.commit()

    app_token = generate_app_token(user_id)
    return redirect(callback_url.replace('[TOKEN]', app_token))

@app.route('/login/app/github')
def login_app_github():
    """Login with GitHub OAuth for app"""
    state = session.get('app_oauth_state')
    if not state:
        return "Invalid state, please start the login process again.", 400

    redirect_uri = url_for('auth_app_github_callback', _external=True)
    return oauth.github.authorize_redirect(redirect_uri, state=state)

@app.route('/auth/app/github/callback')
def auth_app_github_callback():
    """Handle GitHub OAuth callback for app"""
    state = session.pop('app_oauth_state', None)
    callback_state = request.args.get('state')

    if not state or state != callback_state:
        return "Invalid authentication state. Please try again.", 403

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT callback_url FROM app_auth_requests WHERE state = ?", (state,))
        auth_request = cursor.fetchone()
        if not auth_request:
            return "Invalid authentication request.", 403
        callback_url = auth_request['callback_url']
        cursor.execute("DELETE FROM app_auth_requests WHERE state = ?", (state,))
        conn.commit()

    token = oauth.github.authorize_access_token()
    resp = oauth.github.get('https://api.github.com/user')
    user_info = resp.json()
    
    email_resp = oauth.github.get('https://api.github.com/user/emails')
    emails = email_resp.json()
    primary_email = next((email['email'] for email in emails if email['primary']),
                         emails[0]['email'] if emails else 'no-email@example.com')
    
    user_id = f"github_{user_info['id']}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name', user_info.get('login')), primary_email, 'github', user_info.get('avatar_url'))
            )
            conn.commit()

    app_token = generate_app_token(user_id)
    return redirect(callback_url.replace('[TOKEN]', app_token))

def generate_app_token(user_id):
    """Generate and store a new app token for a user"""
    token = secrets.token_urlsafe(32)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, datetime.now())
        )
        conn.commit()
    return token

@app.route('/login/google')
def login_google():
    """Login with Google OAuth"""
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    redirect_uri = url_for('auth_google', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, state=state)

@app.route('/auth/google')
def auth_google():
    """Handle Google OAuth callback"""
    expected_state = session.pop('oauth_state', None)
    callback_state = request.args.get('state')
    
    if not expected_state or callback_state != expected_state:
        return "Invalid authentication state. Please try again.", 403
        
    token = oauth.google.authorize_access_token()
    
    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    
    user_id = f"google_{user_info['sub']}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name'), user_info.get('email'), 'google', user_info.get('picture'))
            )
            conn.commit()
    
    user = User(
        id=user_id,
        name=user_info.get('name'),
        email=user_info.get('email'),
        provider='google',
        profile_pic=user_info.get('picture')
    )
    login_user(user)
    
    return redirect('/')

@app.route('/login/github')
def login_github():
    """Login with GitHub OAuth"""
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    redirect_uri = url_for('auth_github', _external=True)
    return oauth.github.authorize_redirect(redirect_uri, state=state)

@app.route('/auth/github')
def auth_github():
    """Handle GitHub OAuth callback"""
    expected_state = session.pop('oauth_state', None)
    callback_state = request.args.get('state')
    
    if not expected_state or callback_state != expected_state:
        return "Invalid authentication state. Please try again.", 403
        
    token = oauth.github.authorize_access_token()
    resp = oauth.github.get('https://api.github.com/user', token=token)
    user_info = resp.json()
    
    email_resp = oauth.github.get('https://api.github.com/user/emails', token=token)
    emails = email_resp.json()
    primary_email = next((email['email'] for email in emails if email['primary']), 
                          emails[0]['email'] if emails else 'no-email@example.com')
    
    user_id = f"github_{user_info['id']}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name', user_info.get('login')), primary_email, 'github', user_info.get('avatar_url'))
            )
            conn.commit()
    
    user = User(
        id=user_id,
        name=user_info.get('name', user_info.get('login')),
        email=primary_email,
        provider='github',
        profile_pic=user_info.get('avatar_url')
    )
    login_user(user)
    
    return redirect('/')

@app.route('/login/spotify')
def login_spotify():
    """Initiate Spotify OAuth flow"""
    if not current_user.is_authenticated:
        return redirect('/login')
    
    if 'spotify_auth_attempts' not in session:
        session['spotify_auth_attempts'] = 0
    
    if session['spotify_auth_attempts'] > 2:
        session.pop('spotify_auth_attempts', None)
        return "Too many redirect attempts. Please try again later."
    
    session['spotify_auth_attempts'] = session['spotify_auth_attempts'] + 1
    
    state = secrets.token_urlsafe(16)
    session['spotify_oauth_state'] = state
    
    cache_handler = DatabaseCacheHandler(current_user.id)
    
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=' '.join(SPOTIFY_SCOPES),
        cache_handler=cache_handler,
        show_dialog=True,
        state=state
    )
    
    auth_url = auth_manager.get_authorize_url()
    return redirect(auth_url)

@app.route('/auth/spotify/callback')
def auth_spotify_callback():
    """Handle Spotify OAuth callback"""
    if not current_user.is_authenticated:
        return redirect('/login')

    session.pop('spotify_auth_attempts', None)
    
    expected_state = session.pop('spotify_oauth_state', None)
    callback_state = request.args.get('state')
    
    if not expected_state or callback_state != expected_state:
        return "Invalid authentication state. Please try again.", 403
    
    code = request.args.get('code')
    if not code:
        error = request.args.get('error')
        if error:
            return f"Authorization failed: {error}"
        return redirect('/')
    
    cache_handler = DatabaseCacheHandler(current_user.id)
    
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=' '.join(SPOTIFY_SCOPES),
        cache_handler=cache_handler
    )
    
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        return redirect('/integrations')
    except Exception as e:
        return f"Error authenticating with Spotify: {str(e)}"

@app.route('/integrations')
@login_required
def integrations_page():
    """Show integrations management page"""
    return send_from_directory('static', 'integrations.html')

@app.route('/api/integrations/spotify/status', methods=['GET'])
def spotify_integration_status():
    """Check if user has linked their Spotify account"""
    if not current_user.is_authenticated:
        return jsonify({"linked": False, "message": "You need to login first"})
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM spotify_tokens WHERE user_id = ?", (current_user.id,))
        token_data = cursor.fetchone()
    
    if token_data:
        spotify = get_spotify_client(current_user.id)
        try:
            current_playback = spotify.current_playback()
            if current_playback:
                return jsonify({
                    "linked": True,
                    "active": True,
                    "message": "Spotify connected and active"
                })
            else:
                return jsonify({
                    "linked": True,
                    "active": False,
                    "message": "Spotify connected, but no active playback detected"
                })
        except:
            return jsonify({
                "linked": True,
                "active": False,
                "message": "Spotify connected, but there was an error checking playback"
            })
    
    return jsonify({
        "linked": False,
        "message": "Spotify not connected"
    })

@app.route('/api/integrations/spotify/disconnect', methods=['POST'])
@login_required
def spotify_disconnect():
    """Disconnect Spotify integration"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM spotify_tokens WHERE user_id = ?", (current_user.id,))
        conn.commit()
    
    return jsonify({"success": True, "message": "Spotify disconnected successfully"})



@app.route('/api/integrations/spotify/now-playing')
def spotify_now_playing():
    if not current_user.is_authenticated:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = current_user.id
    
    spotify_service = get_spotify_service()
    if not spotify_service:
        return jsonify({"error": "Spotify service not available"}), 500
    
    try:
        current_track = spotify_service.get_current_track(user_id)
        if not current_track:
            return jsonify({"error": "No track playing"}), 404
        
        track_data = {
            "track_name": current_track.get("track_name", "Unknown"),
            "artist": current_track.get("artist", "Unknown"),
            "album_art": current_track.get("album_art"),
            "track_url": current_track.get("track_url", "https://open.spotify.com/"),
            "is_playing": current_track.get("is_playing", False),
            "device": current_track.get("device")
        }
        
        return jsonify(track_data)
    except Exception as e:
        app.logger.error(f"Error getting current track: {str(e)}")
        return jsonify({"error": f"Failed to get current track: {str(e)}"}), 500

@app.route('/api/integrations/spotify/control', methods=['POST'])
@login_required
def spotify_control():
    """Control Spotify playback"""
    action = request.json.get('action')
    
    if not action:
        return jsonify({"error": "No action specified"}), 400
    
    spotify = get_spotify_client(current_user.id)
    if not spotify:
        return jsonify({"error": "Spotify not connected"}), 404
    
    try:
        if action == "play":
            spotify.start_playback()
            return jsonify({"success": True, "message": "Playback started"})
        elif action == "pause":
            spotify.pause_playback()
            return jsonify({"success": True, "message": "Playback paused"})
        elif action == "next":
            spotify.next_track()
            return jsonify({"success": True, "message": "Skipped to next track"})
        elif action == "previous":
            spotify.previous_track()
            return jsonify({"success": True, "message": "Skipped to previous track"})
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"error": f"Error controlling playback: {str(e)}"}), 500

@app.route('/logout')
def logout():
    """Log out the current user"""
    logout_user()
    return redirect('/')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if (path == "" or path == "index.html"):
        return send_from_directory('static', 'index.html')
    return send_from_directory('static', path)

def _extract_search_query(self, query: str) -> Optional[str]:
        """Extract search terms from query by removing search indicators"""
        self._add_thought("Looking for search terms in query", None)
        
        search_terms = query.lower()
        
        # Remove common search indicators
        search_indicators = [
            "search for", "search", "find", "look up", "show me", "get", 
            "tell me about", "what is", "who is", "where is", "how is"
        ]
        
        for indicator in search_indicators:
            search_terms = search_terms.replace(indicator, "").strip()
        
        # Clean up extra whitespace
        search_terms = " ".join(search_terms.split())
        
        if search_terms:
            self._add_thought("Extracted search terms", search_terms)
            return search_terms
        
        self._add_thought("No search terms found after removing indicators", None)
        return None
    
if __name__ == '__main__':
    print("\033[91mYOU ARE RUNNING THE SERVER IN DEBUG MODE! DO NOT USE THIS IN PRODUCTION!\033[0m")
    app.run(debug=True, host='0.0.0.0', port=5300)