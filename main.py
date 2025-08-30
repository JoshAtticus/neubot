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
import random
import uuid
import secrets
from urllib.parse import urlparse
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
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))

DEFAULT_TIMEZONE = "America/New_York"

GUEST_WEATHER_RATE_LIMIT = 5  # requests per month for non-logged-in users
GUEST_SEARCH_RATE_LIMIT = 10   # requests per month for non-logged-in users
GUEST_TOTAL_QUERY_LIMIT = 100  # total requests per month for non-logged-in users

USER_WEATHER_RATE_LIMIT = 50  # requests per month for logged-in users
USER_SEARCH_RATE_LIMIT = 100   # requests per month for logged-in users
USER_TOTAL_QUERY_LIMIT = 1000  # total requests per month for logged-in users


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
        CREATE TABLE IF NOT EXISTS home_assistant_links (
            user_id TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at INTEGER,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        cursor.execute("PRAGMA table_info(home_assistant_links)")
        ha_cols = [row[1] for row in cursor.fetchall()]
        if 'refresh_token' not in ha_cols:
            try:
                cursor.execute('ALTER TABLE home_assistant_links ADD COLUMN refresh_token TEXT')
            except Exception:
                pass
        if 'expires_at' not in ha_cols:
            try:
                cursor.execute('ALTER TABLE home_assistant_links ADD COLUMN expires_at INTEGER')
            except Exception:
                pass
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
            "turn": "command_query",
            "switch": "command_query",
            "activate": "command_query",
            "run": "command_query",
            "set": "command_query",
            "dim": "command_query",
            "brighten": "command_query",
            "open": "command_query",
            "close": "command_query",
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
            "calculator": self._calculator_tool,
            "calc": self._calculator_tool,
            "homeassistant": self._home_assistant_tool,
        }
        
        self.entity_types = {
            "location": self._extract_location,
            "date": self._extract_date,
            "math_expression": self._extract_math_expression,
        }

        self.ha_action_verbs = {
            "turn on": "turn_on",
            "switch on": "turn_on",
            "activate": "turn_on",
            "start": "turn_on",
            "run": "turn_on",
            "turn off": "turn_off",
            "switch off": "turn_off",
            "deactivate": "turn_off",
            "stop": "turn_off",
            "on": "turn_on",
            "off": "turn_off",
        }
        self.ha_domain_terms = {
            "light": "light",
            "lights": "light",
            "lamp": "light",
            "lamps": "light",
            "bulb": "light",
            "bulbs": "light",
            "downlight": "light",
            "downlights": "light",
            "fan": "fan",
            "fans": "fan",
            "switch": "switch",
            "switches": "switch",
            "scene": "scene",
            "scenes": "scene",
            "script": "script",
            "scripts": "script",
        }

        self.search_indicator_phrases = [
            "what is", "who is", "where is", "when is", "tell me about", "look up", "find", "search for"
        ]
    
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
        
        lowered = " ".join(tokens).lower()
        for phrase in self.search_indicator_phrases:
            if lowered.startswith(phrase) or f" {phrase} " in lowered:
                if "search" not in found_tools:
                    found_tools.add("search")
                    self._add_thought("Inferred search tool from phrase", phrase)
                break
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

            if tool == "homeassistant":
                ha_entities = self._extract_ha_entities(query)
                entities.update(ha_entities)
                # Pass full query to downstream HA tool for fallback parsing
                entities.setdefault("search_query", query)
        
        self._add_thought("Extracted entities", entities)
        return entities
    
    def _extract_location(self, query: str) -> Optional[str]:
        """Extract location entity from query"""
        self._add_thought("Looking for location in query", None)
        
        title_query = query.title()
        
        time_location_pattern = r"\btime\s+(?:in|at|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=$|[.?!,]|\s+(?:and|with|at|is|are|was|were))"
        time_match = re.search(time_location_pattern, title_query, re.IGNORECASE)
        if time_match:
            location = time_match.group(1).strip()
            self._add_thought("Found location in time query", location)
            return location
        
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
        user_id = get_request_user_id()
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
        
        math_operators = ["plus", "minus", "times", "divided by", "multiplied by"]
        for operator in math_operators:
            pattern = fr'\b{operator}\b'
            result = re.sub(pattern, f'<span class="math-operator">{operator}</span>', result, flags=re.IGNORECASE)
            
        symbol_pattern = r'([-+*/])'
        result = re.sub(symbol_pattern, r'<span class="math-operator">\1</span>', result)
        
        if location:
            escaped_location = re.escape(location)
            pattern = fr'\b{escaped_location}\b'
            result = re.sub(pattern, f'<span class="attribute">{location}</span>', result, flags=re.IGNORECASE)
        
        return result

    def _extract_math_expression(self, query: str) -> Optional[str]:
        """Extract a math expression (basic arithmetic) from the query.

        Supports digits, + - * / ( ), decimal points and common words (plus, minus, times, divided by).
        Returns a sanitized expression string safe for eval with restricted context, or None.
        """
        self._add_thought("Looking for math expression", None)
        word_map = {
            r"\bplus\b": "+",
            r"\bminus\b": "-",
            r"\btimes\b": "*",
            r"\bmultiplied by\b": "*",
            r"\bdivided by\b": "/",
            r"\bover\b": "/",
        }
        normalized = query.lower()
        for pattern, repl in word_map.items():
            normalized = re.sub(pattern, repl, normalized)
        match = re.findall(r"[0-9()+\-*/. ]", normalized)
        if not match:
            self._add_thought("No math characters found", None)
            return None
        candidate = "".join(match)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not re.search(r"[+\-*/]", candidate):
            self._add_thought("Expression lacks operators", candidate)
            return None
        if re.search(r"[^0-9()+\-*/. ]", candidate):
            self._add_thought("Disallowed characters in expression", candidate)
            return None
        self._add_thought("Extracted math expression", candidate)
        return candidate

    def _extract_search_query(self, query: str) -> Optional[str]:
        """Extract a search query by trimming leading indicator phrases and filler words."""
        self._add_thought("Extracting search query", None)
        q = query.strip()
        lowered = q.lower()
        # Remove punctuation at ends
        lowered = lowered.strip("?!. ")
        # Remove leading activation phrases
        patterns = [
            r"^(search for|search|look up|find|tell me about|what is|who is|where is|when is)\s+",
        ]
        modified = lowered
        for pat in patterns:
            modified = re.sub(pat, "", modified)
        modified = modified.strip()
        if not modified or modified == lowered:
            # fallback: if original contains 'search for', take substring after it
            for key in ["search for", "search", "look up", "find", "tell me about"]:
                if key in lowered:
                    idx = lowered.find(key) + len(key)
                    modified = lowered[idx:].strip()
                    break
        if modified:
            self._add_thought("Derived search query", modified)
            return modified
        self._add_thought("No search query extracted", None)
        return None

    def _extract_ha_entities(self, query: str) -> Dict[str, Any]:
        """Extract Home Assistant specific entities: action, domain, area/room, device phrase.

        Returns keys: ha_action, ha_domain, ha_area, ha_device_phrase (subset of query).
        """
        self._add_thought("Extracting Home Assistant entities", None)
        ql = query.lower()
        result: Dict[str, Any] = {}

        # Action: prefer two-word verb phrases
        action = None
        for phrase, canonical in self.ha_action_verbs.items():
            if " " in phrase and phrase in ql:
                action = canonical
                break
        if not action:
            # Single token verbs / states
            tokens = re.findall(r"\b\w+\b", ql)
            for i, tok in enumerate(tokens):
                if tok in self.ha_action_verbs and len(tok) > 2:  # avoid 'on'/'off' first
                    action = self.ha_action_verbs[tok]
                    break
            if not action:
                # on/off alone
                if re.search(r"\bturn\s+on\b|\bon\b", ql):
                    action = "turn_on"
                elif re.search(r"\bturn\s+off\b|\boff\b", ql):
                    action = "turn_off"
        if action:
            result["ha_action"] = action

        # Domain
        domain = None
        for term, canonical in self.ha_domain_terms.items():
            if re.search(rf"\b{re.escape(term)}\b", ql):
                domain = canonical
                break
        if domain:
            result["ha_domain"] = domain

        # Area / room heuristic: words before domain term
        ha_area = None
        if domain:
            m = re.search(rf"\b([a-zA-Z ]{{2,40}}?)\b(?:{domain}|{domain}s|lamp|lamps|bulb|bulbs)\b", ql)
            if m:
                candidate = m.group(1).strip()
                # Remove leading verbs/stop words
                candidate = re.sub(r"\b(turn|switch|set|activate|run|start|stop|on|off|the|my|a|to)\b", "", candidate).strip()
                if 0 < len(candidate.split()) <= 3:
                    ha_area = candidate
        if ha_area:
            result["ha_area"] = ha_area

        # Device phrase: capture adjective/noun sequence ending in domain synonym
        device_phrase = None
        domain_pattern = "|".join(sorted(set(self.ha_domain_terms.keys()), key=len, reverse=True))
        dm = re.search(rf"\b([a-zA-Z0-9 ]{{2,50}}?\b(?:{domain_pattern}))\b", ql)
        if dm:
            phrase = dm.group(1).strip()
            phrase = re.sub(r"\b(turn|switch|set|activate|run|start|stop|on|off|the|my|a|to)\b", "", phrase).strip()
            if phrase:
                device_phrase = phrase
        if device_phrase:
            result["ha_device_phrase"] = device_phrase

        self._add_thought("Extracted HA entities", result)
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
            if re.search(r'\b' + re.escape(greeting) + r'\b', query_lower) or query_lower.startswith(greeting):
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

        # Music/Spotify detection removed.

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

        # Home Assistant natural language detection (verbs + domains). Detect before entity extraction.
        ha_detect = False
        for term in self.ha_domain_terms.keys():
            if re.search(rf"\b{re.escape(term)}\b", query_lower):
                ha_detect = True
                break
        if ha_detect and re.search(r"\b(turn|switch|activate|run|start|stop|on|off|set|dim|brighten|open|close)\b", query_lower):
            if "homeassistant" not in tools:
                tools.add("homeassistant")
                self._add_thought("Inferred Home Assistant tool from verbs/domains", None)

        entities = self._extract_entities(query, tools)
        extracted_location = entities.get("location")

        entities["user_timezone"] = user_timezone

        # Add search query for calculator
        if "calculator" in tools or "calc" in tools:
            entities["search_query"] = query

        # Removed spotify entity injection.

        use_search = False
        if len(tools) == 0:
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
                if len(tools) == 0:
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
        user_id = get_request_user_id()
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

    # Removed Spotify action extraction & tool.

    def _home_assistant_tool(self, entities: Dict[str, Any]) -> str:
        """Execute simple Home Assistant device commands based on natural language.

        Supports: lights, fans, switches, scenes, scripts. (Single target heuristic.)
        """
        self._add_thought("Executing Home Assistant tool", None)
        if not current_user.is_authenticated:
            return "You need to login and link Home Assistant first."

        # Load link info
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT base_url, access_token, refresh_token, expires_at FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
            row = cur.fetchone()
        if not row:
            return "You haven't linked Home Assistant yet. Go to Integrations to connect it."

        base_url = row['base_url']

        def _decrypt(val):
            if not val:
                return None
            try:
                return decrypt_token(val)
            except Exception:
                return val

        access_token = _decrypt(row['access_token'])
        refresh_token = _decrypt(row['refresh_token']) if 'refresh_token' in row.keys() and row['refresh_token'] else None
        expires_at = row['expires_at'] if 'expires_at' in row.keys() and row['expires_at'] else 0

        query = entities.get('search_query') or ''
        ql = query.lower()

        # Refresh token if expired
        now_ts = int(time.time())
        if expires_at and expires_at < now_ts - 30 and refresh_token:
            try:
                token_resp = requests.post(
                    f"{base_url}/auth/token",
                    data={
                        'grant_type': 'refresh_token',
                        'refresh_token': refresh_token,
                        'client_id': url_for('ha_callback', _external=True)
                    }, timeout=10
                )
                if token_resp.status_code == 200:
                    td = token_resp.json()
                    access_token = td.get('access_token', access_token)
                    new_expires = int(time.time()) + int(td.get('expires_in', 1800))
                    with get_db_connection() as conn:
                        c2 = conn.cursor()
                        c2.execute('UPDATE home_assistant_links SET access_token = ?, expires_at = ? WHERE user_id = ?', (encrypt_token(access_token), new_expires, current_user.id))
                        conn.commit()
            except Exception:
                pass  # silent fallback

        # Structured entities first
        action = entities.get('ha_action')
        domain = entities.get('ha_domain')
        area = entities.get('ha_area')
        device_phrase = entities.get('ha_device_phrase')

        # Fallback regex detection
        if not action:
            if re.search(r"\b(turn on|switch on|activate|start|run)\b", ql):
                action = 'turn_on'
            elif re.search(r"\b(turn off|switch off|deactivate|stop)\b", ql):
                action = 'turn_off'
        if not domain:
            for term, canonical in self.ha_domain_terms.items():
                if re.search(rf"\b{re.escape(term)}\b", ql):
                    domain = canonical
                    break
        if domain in ('scene', 'script') and not action:
            action = 'turn_on'
        if not domain:
            return json.dumps({"type":"ha_result","error":"no_domain","message":"I couldn't determine what device you want to control."})

        # Area detection fallback
        room = area
        if not room:
            room_match = re.search(r"\b(?:my|the)?\s*([a-zA-Z ]+?)\s+(?:light|lights|fan|fans|switch|switches|lamp|lamps|bulb|bulbs)\b", ql)
            if room_match:
                cand = room_match.group(1).strip()
                if cand and len(cand.split()) <= 3 and not re.search(r"turn|on|off|activate|run|switch|set|dim|brighten", cand):
                    room = cand

        # Fetch states
        try:
            resp = requests.get(
                f"{base_url}/api/states",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                timeout=5
            )
            if resp.status_code != 200:
                return f"Failed to reach Home Assistant ({resp.status_code})."
            states = resp.json()
        except Exception as e:
            return f"Error contacting Home Assistant: {e}"

        # -------------------- Helpers --------------------
        color_words_all = ["warm white","cool white","magenta","yellow","purple","orange","white","green","blue","pink","cyan","red"]

        def detect_colors(text: str):
            found = []
            for cw in color_words_all:
                if cw in text:
                    found.append(cw)
            # de-dupe keep order
            seen = set(); ordered = []
            for c in found:
                if c not in seen:
                    ordered.append(c); seen.add(c)
            return ordered

        def detect_brightness(text: str):
            m_pct = re.search(r"(\d{1,3})%", text)
            if m_pct:
                pct = int(m_pct.group(1)); return max(1, min(100, pct))
            if re.search(r"\bhalf\b", text): return 50
            if re.search(r"\b(full|max(imum)?|bright(est)?)\b", text): return 100
            if re.search(r"\b(dim|low)\b", text): return 25
            if re.search(r"\bmedium\b", text): return 60
            return None

        # -------------- Multi-clause segmentation --------------
        segmentation_trigger = False
        if (' and ' in ql or ' then ' in ql) and domain == 'light':
            group_tokens = {'desk','accent','bed','drawer','under','above'}
            occurrences = sum(1 for t in group_tokens if t in ql)
            color_occ = sum(1 for c in color_words_all if c in ql)
            on_off_occ = len(re.findall(r"\b(turn on|turn off|switch on|switch off|set)\b", ql))
            if occurrences >= 2 or color_occ >= 2 or on_off_occ >= 2:
                segmentation_trigger = True

        if segmentation_trigger:
            raw_segments = re.split(r"\b(?:and then|then|and)\b", ql)
            segments = [s.strip() for s in raw_segments if s.strip()]
            ignore_tokens = {'the','a','my','to','please','all','every','set','make','turn','switch','and','then','at','on','off','lights','light','lamp','lamps','bulb','bulbs'}
            action_regex_on = re.compile(r"\b(turn on|switch on|set .*? to|set .*? on|activate|enable)\b")
            action_regex_off = re.compile(r"\b(turn off|switch off|deactivate|disable)\b")

            # Pre-tokenize entity names
            entity_name_tokens: Dict[str, Tuple[str, Set[str], str]] = {}
            for st in states:
                eid = st.get('entity_id','')
                if not eid.startswith(domain + '.'):
                    continue
                fname = st.get('attributes',{}).get('friendly_name','')
                toks = set(re.findall(r"[a-zA-Z0-9']+", fname.lower()))
                entity_name_tokens[eid] = (fname, toks, st.get('state'))

            clause_results = []
            for seg in segments:
                seg_l = seg.lower()
                seg_action = None
                if action_regex_off.search(seg_l):
                    seg_action = 'turn_off'
                elif action_regex_on.search(seg_l):
                    seg_action = 'turn_on'
                seg_colors = detect_colors(seg_l)
                seg_color = seg_colors[0] if seg_colors else None
                if seg_color and not seg_action:
                    seg_action = 'turn_on'
                seg_brightness = detect_brightness(seg_l)
                raw_tokens = re.findall(r"[a-zA-Z0-9']+", seg_l)
                device_tokens = [t for t in raw_tokens if t not in ignore_tokens and t not in {'to'} and all(cw.find(t) == -1 for cw in color_words_all)]
                device_tokens = [t for t in device_tokens if not t.isdigit()]
                device_tokens_set = set(device_tokens)
                seg_entities = []
                if device_tokens_set:
                    for eid,(fname,toks,state_val) in entity_name_tokens.items():
                        if toks & device_tokens_set:
                            seg_entities.append((eid,fname,state_val))
                if seg_entities and (seg_action or seg_color or seg_brightness):
                    clause_results.append({
                        'action': seg_action or ('turn_on' if (seg_color or seg_brightness) else action or 'turn_on'),
                        'color': seg_color,
                        'colors': seg_colors,
                        'brightness': seg_brightness,
                        'entities': seg_entities
                    })

            if len(clause_results) > 1:
                results = []
                summary_clauses = []
                for c in clause_results:
                    color_cycle: List[str] = []
                    if c['colors'] and len(c['colors']) > 1 and c['action'] == 'turn_on' and domain == 'light':
                        while len(color_cycle) < len(c['entities']):
                            color_cycle.extend(c['colors'])
                        color_cycle = color_cycle[:len(c['entities'])]
                        random.shuffle(color_cycle)
                    color_idx = 0
                    for eid,fname,state_val in c['entities']:
                        svc_data = {'entity_id': eid}
                        assigned_color = None
                        if domain == 'light' and c['action'] == 'turn_on':
                            if c['brightness'] is not None:
                                svc_data['brightness_pct'] = c['brightness']
                            if color_cycle:
                                assigned_color = color_cycle[color_idx]; color_idx += 1
                                svc_data['color_name'] = assigned_color
                            elif c['color']:
                                assigned_color = c['color']; svc_data['color_name'] = assigned_color
                        try:
                            svc = requests.post(
                                f"{base_url}/api/services/{domain}/{c['action']}",
                                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                                json=svc_data,
                                timeout=5
                            )
                            success = svc.status_code in (200,201)
                        except Exception as e:
                            success = False
                            svc = type('obj', (), {'status_code': 0})()  # simple placeholder
                            assigned_error = str(e)
                        results.append({
                            'entity_id': eid,
                            'name': fname,
                            'requested_action': c['action'],
                            'success': success,
                            'code': getattr(svc, 'status_code', 0),
                            'state_before': state_val,
                            'applied_color': assigned_color,
                            'applied_brightness_pct': c['brightness']
                        })
                    names = [e[1] for e in c['entities']]
                    if names:
                        act_word = 'on' if c['action']=='turn_on' else 'off'
                        clause_text = f"{', '.join(names)} {act_word}"
                        if c['color']:
                            clause_text += f" ({c['color']})"
                        summary_clauses.append(clause_text)
                summary_text = '; '.join(summary_clauses) + '.' if summary_clauses else 'Action attempted.'
                return json.dumps({
                    'type':'ha_result',
                    'summary': summary_text,
                    'action': 'multi',
                    'domain': domain,
                    'devices': results,
                    'applied': {}
                })
            # else fall through to single-clause path using original query elements

        # -------------- Single clause path --------------
        # Identify probable entities
        target_entity = None
        friendly = None
        phrase_tokens: List[str] = []
        if device_phrase:
            phrase_tokens = [t for t in re.findall(r"\w+", device_phrase.lower()) if t not in ('the','a','my')]
        best_score = 0.0
        for st in states:
            eid = st.get('entity_id','')
            if not eid.startswith(domain + '.'):
                continue
            fname = st.get('attributes',{}).get('friendly_name','')
            fname_l = fname.lower()
            if phrase_tokens:
                matches = sum(1 for t in phrase_tokens if t in fname_l)
                score = matches / max(1, len(phrase_tokens))
            elif room and room.lower() in fname_l:
                score = 0.6
            else:
                score = 0.1
            if score > best_score and score >= 0.3:
                best_score = score; target_entity = eid; friendly = fname
            if score >= 0.99:
                break

        generic_words = {'turn','on','off','the','a','my','and','to','set','please','light','lights','lamp','lamps','bulb','bulbs','downlight','downlights'}
        q_tokens_raw = re.findall(r"[a-zA-Z0-9']+", ql)
        token_set = set(q_tokens_raw)
        content_tokens = {t for t in q_tokens_raw if t not in generic_words}
        matched_entities: List[Tuple[str,str,str]] = []
        select_all = ('all' in token_set or 'every' in token_set) and any(w in token_set for w in {'light','lights',domain, domain+'s'})
        for st in states:
            eid = st.get('entity_id','')
            if not eid.startswith(domain + '.'):
                continue
            fname = st.get('attributes',{}).get('friendly_name','')
            fname_l = fname.lower()
            name_tokens = [t for t in re.findall(r"[a-zA-Z0-9']+", fname_l) if t not in {'the','and','of'}]
            if select_all:
                matched_entities.append((eid, fname, st.get('state')))
                continue
            if content_tokens and any(nt in content_tokens for nt in name_tokens):
                matched_entities.append((eid, fname, st.get('state')))

        if not matched_entities and target_entity:
            state_val = next((s.get('state') for s in states if s.get('entity_id')==target_entity), None)
            matched_entities = [(target_entity, friendly, state_val)]

        if not matched_entities:
            return json.dumps({"type":"ha_result","error":"no_match","message":"I couldn't find a matching device."})

        ordered_colors = detect_colors(ql)
        color_name = ordered_colors[0] if ordered_colors else None
        brightness_pct = detect_brightness(ql)

        if color_name and not action:
            action = 'turn_on'
        if not action:
            return json.dumps({"type":"ha_result","error":"no_action","message":"Need to know if you want them on or off."})

        results = []
        multi_color_cycle: List[str] = []
        if len(ordered_colors) > 1 and action == 'turn_on' and domain == 'light':
            while len(multi_color_cycle) < len(matched_entities):
                multi_color_cycle.extend(ordered_colors)
            multi_color_cycle = multi_color_cycle[:len(matched_entities)]
            random.shuffle(multi_color_cycle)
        color_idx = 0
        for eid,fname,state_val in matched_entities:
            svc_data = {'entity_id': eid}
            assigned_color = None
            if domain == 'light' and action == 'turn_on':
                if brightness_pct is not None:
                    svc_data['brightness_pct'] = brightness_pct
                if multi_color_cycle:
                    assigned_color = multi_color_cycle[color_idx]; color_idx += 1
                    svc_data['color_name'] = assigned_color
                elif color_name:
                    assigned_color = color_name; svc_data['color_name'] = assigned_color
            try:
                svc = requests.post(
                    f"{base_url}/api/services/{domain}/{action}",
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    json=svc_data,
                    timeout=5
                )
                success = svc.status_code in (200,201)
            except Exception:
                success = False; svc = type('obj', (), {'status_code': 0})()
            results.append({
                'entity_id': eid,
                'name': fname,
                'requested_action': action,
                'success': success,
                'code': getattr(svc,'status_code',0),
                'state_before': state_val,
                'applied_color': assigned_color,
                'applied_brightness_pct': brightness_pct
            })

        success_names = [r['name'] for r in results if r['success']]
        summary_parts: List[str] = []
        if success_names:
            verb = 'on' if action == 'turn_on' else 'off'
            summary_parts.append(f"Set {len(success_names)} {domain}{'s' if len(success_names)!=1 else ''} {verb}")
        if multi_color_cycle:
            summary_parts.append(f"colors {', '.join(ordered_colors)}")
        elif color_name:
            summary_parts.append(f"color {color_name}")
        if brightness_pct is not None:
            summary_parts.append(f"brightness {brightness_pct}%")
        summary_text = (', '.join(summary_parts) + '.') if summary_parts else 'Action attempted.'
        return json.dumps({
            'type':'ha_result',
            'summary': summary_text,
            'action': action,
            'domain': domain,
            'devices': results,
            'applied': {
                'color_name': color_name,
                'brightness_pct': brightness_pct,
                'colors': ordered_colors if len(ordered_colors) > 1 else None
            }
        })

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
            self._add_thought("Calculation error", str(e))
            return "There was an error evaluating that expression. Please check the syntax."

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

# JoshAtticusID oauth registration removed (and related routes pruned)

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
    """Legacy function (Spotify removed). No action required."""
    return


def get_user_id_from_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    
    parts = auth_header.split()
    
    if parts[0].lower() != 'bearer' or len(parts) != 2:
        return None
        
    token = parts[1]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM app_tokens WHERE token = ?", (token,))
        result = cursor.fetchone()
        if result:
            return result['user_id']
    return None

def get_request_user_id():
    """Gets user ID from session or Authorization header token."""
    user_id = current_user.get_id() if current_user.is_authenticated else None
    if not user_id:
        auth_header = request.headers.get('Authorization')
        user_id = get_user_id_from_token(auth_header)
    return user_id


@app.route('/api/query', methods=['POST'])
def process_query():
    data = request.json
    query = data.get('query', '')
    user_timezone = data.get('timezone', DEFAULT_TIMEZONE)
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    ip = get_client_ip()
    user_id = get_request_user_id()
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
    user_id = get_request_user_id()
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
        user_id = get_request_user_id()
        if user_id:
            user = User.get(user_id)
            if user:
                return jsonify({
                    "authenticated": True,
                    "user": {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "provider": user.provider,
                        "profile_pic": user.profile_pic
                    }
                })
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

@app.route('/login/app/github')
def login_app_github():
    """Login with GitHub OAuth for app"""
    state = session.get('app_oauth_state')
    if not state:
        return "Invalid state, please start the login process again.", 400

    redirect_uri = url_for('auth_app_github_callback', _external=True)
    return oauth.github.authorize_redirect(redirect_uri, state=state)

## JoshAtticusID app login removed

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

## JoshAtticusID app callback removed

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

## JoshAtticusID login removed

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

## JoshAtticusID auth callback removed

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

## Spotify login & callback removed (legacy)

@app.route('/integrations')
@login_required
def integrations_page():
    """Show integrations management page"""
    return send_from_directory('static', 'integrations.html')

@app.route('/home-assistant-setup.html')
@login_required
def ha_setup_page():
    return send_from_directory('static', 'home-assistant-setup.html')

## All Spotify endpoints removed

# -------- Home Assistant Integration (OAuth Auth API) --------
@app.route('/api/integrations/home-assistant/start', methods=['POST'])
@login_required
def ha_start():
    data = request.json or {}
    base_url = data.get('base_url', '').strip().rstrip('/')
    if not base_url:
        return jsonify({"success": False, "message": "base_url required"}), 400
    if not base_url.startswith(('http://', 'https://')):
        return jsonify({"success": False, "message": "base_url must start with http:// or https://"}), 400
    state = secrets.token_hex(16)
    session['ha_state'] = state
    session['ha_base_url'] = base_url
    callback_url = url_for('ha_callback', _external=True)
    client_id = callback_url  # HA expects redirect URL as client_id
    authorize_url = (
        f"{base_url}/auth/authorize?response_type=code&client_id="
        f"{requests.utils.quote(client_id, safe='')}"
        f"&redirect_uri={requests.utils.quote(callback_url, safe='')}"
        f"&state={state}"
    )
    return jsonify({"success": True, "authorize_url": authorize_url})

@app.route('/api/integrations/home-assistant/callback')
@login_required
def ha_callback():
    state = request.args.get('state')
    code = request.args.get('code')
    error = request.args.get('error')
    expected = session.get('ha_state')
    base_url = session.get('ha_base_url')
    if error:
        return redirect(url_for('integrations_page') + f"?ha_error={requests.utils.quote(error)}")
    if not state or state != expected or not base_url:
        return "Invalid state", 400
    if not code:
        return "Missing code", 400
    token_url = f"{base_url}/auth/token"
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': url_for('ha_callback', _external=True)
    }
    try:
        r = requests.post(token_url, data=payload, timeout=15)
    except Exception as e:
        return f"Token request failed: {e}", 502
    if r.status_code != 200:
        return f"Token exchange failed ({r.status_code}): {r.text[:200]}", 502
    data = r.json()
    access_token = data.get('access_token')
    refresh_token = data.get('refresh_token')
    expires_in = data.get('expires_in', 1800)
    if not access_token:
        return "No access token", 502
    expires_at = int(time.time()) + int(expires_in)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO home_assistant_links (user_id, base_url, access_token, refresh_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM home_assistant_links WHERE user_id = ?), ?))''',
                  (current_user.id, base_url, encrypt_token(access_token), encrypt_token(refresh_token) if refresh_token else None, expires_at, current_user.id, datetime.now()))
        conn.commit()
    session.pop('ha_state', None)
    session.pop('ha_base_url', None)
    return redirect(url_for('integrations_page') + "?ha_link=1")

@app.route('/api/integrations/home-assistant/status', methods=['GET'])
@login_required
def ha_status():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT base_url, expires_at FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"connected": False})
        return jsonify({"connected": True, "base_url": row['base_url'], "expires_at": row['expires_at']})

@app.route('/api/integrations/home-assistant/link', methods=['DELETE'])
@login_required
def ha_unlink():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        conn.commit()
    return jsonify({"success": True, "message": "Home Assistant disconnected"})


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

if __name__ == '__main__':
    print("\033[91mYOU ARE RUNNING THE SERVER IN DEBUG MODE! DO NOT USE THIS IN PRODUCTION!\033[0m")
    app.run(debug=True, host='0.0.0.0', port=5300)