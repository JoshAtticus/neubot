import re
import json
import requests
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple, Set
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, session
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
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "") 
BRAVE_SEARCH_TOKEN = os.getenv("BRAVE_SEARCH_TOKEN", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))

DEFAULT_TIMEZONE = "America/New_York"

GUEST_WEATHER_RATE_LIMIT = 3  # requests per month for non-logged-in users
GUEST_SEARCH_RATE_LIMIT = 5   # requests per month for non-logged-in users
GUEST_TOTAL_QUERY_LIMIT = 50  # total requests per month for non-logged-in users

USER_WEATHER_RATE_LIMIT = 30  # requests per month for logged-in users
USER_SEARCH_RATE_LIMIT = 50   # requests per month for logged-in users
USER_TOTAL_QUERY_LIMIT = 500  # total requests per month for logged-in users

DB_FILE = "neubot.db"

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
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            return User(
                id=user_data['id'],
                name=user_data['name'],
                email=user_data['email'],
                provider=user_data['provider'],
                profile_pic=user_data['profile_pic']
            )
        return None

def init_db():
    conn = sqlite3.connect(DB_FILE)
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
    
    cursor.execute("PRAGMA table_info(requests)")
    columns = cursor.fetchall()
    column_names = [column[1] for column in columns]
    
    if 'user_id' not in column_names:
        cursor.execute('ALTER TABLE requests ADD COLUMN user_id TEXT')
    
    conn.commit()
    conn.close()

class RateLimiter:
    def __init__(self):
        self._init_db()
        
    def _init_db(self):
        """Initialize SQLite database and create tables if they don't exist"""
        conn = sqlite3.connect(DB_FILE)
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
        conn.close()
    
    def _cleanup_old_requests(self, ip: str, req_type: str, user_id: Optional[str] = None):
        """Remove requests older than 1 month"""
        conn = sqlite3.connect(DB_FILE)
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
        conn.close()
    
    def _get_next_reset(self, ip: str) -> datetime:
        """Get the next reset date for an IP's limits"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT reset_date FROM reset_dates WHERE ip = ?
        ''', (ip,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            last_reset = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        else:
            last_reset = datetime.now()
            self._save_reset_date(ip, last_reset)
        
        return last_reset + timedelta(days=30)
    
    def _save_reset_date(self, ip: str, reset_date: datetime):
        """Save reset date to database"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT OR REPLACE INTO reset_dates (ip, reset_date) 
        VALUES (?, ?)
        ''', (ip, reset_date.strftime("%Y-%m-%d %H:%M:%S")))
        
        conn.commit()
        conn.close()
    
    def check_rate_limit(self, ip: str, req_type: str, user_id: Optional[str] = None) -> Tuple[bool, int]:
        """Check if request is within rate limits"""
        self._cleanup_old_requests(ip, req_type, user_id)
        
        conn = sqlite3.connect(DB_FILE)
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
        
        conn.close()
        
        if req_type in ["search", "weather"]:
            limit = search_limit if req_type == "search" else weather_limit
            return (current_count < limit and total_count < total_limit), \
                min(limit - current_count, total_limit - total_count)
        
        return (total_count < total_limit), (total_limit - total_count)
    
    def add_request(self, ip: str, req_type: str, user_id: Optional[str] = None):
        """Record a new request in the database"""
        conn = sqlite3.connect(DB_FILE)
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
        conn.close()
    
    def get_limits(self, ip: str, user_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get current rate limit status for a user or IP"""
        self._cleanup_old_requests(ip, "search", user_id)
        self._cleanup_old_requests(ip, "weather", user_id)
        self._cleanup_old_requests(ip, "total", user_id)
        
        conn = sqlite3.connect(DB_FILE)
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
        
        conn.close()
        
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
        }
        
        self.entity_types = {
            "location": self._extract_location,
            "date": self._extract_date,
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
            if tool == "weather":
                location = self._extract_location(query)
                if location:
                    entities["location"] = location
            
            if tool in ["time", "date", "day"]:
                date_spec = self._extract_date(query)
                if date_spec:
                    entities["date"] = date_spec
        
        self._add_thought("Extracted entities", entities)
        return entities
    
    def _extract_location(self, query: str) -> Optional[str]:
        """Extract location entity from query"""
        self._add_thought("Looking for location in query", None)
        
        title_query = query.title()
        
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
        
        ip = request.remote_addr
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
        
        query_indicators = ["what", "what's", "how", "when", "where", "who", "why", "is", "can", "tell", "show"]
        for indicator in query_indicators:
            pattern = fr'\b{indicator}\b'
            result = re.sub(pattern, f'<span class="query-indicator">{indicator}</span>', result, flags=re.IGNORECASE)
        
        tools = ["time", "weather", "date", "day"]
        for tool in tools:
            pattern = fr'\b{tool}\b'
            result = re.sub(pattern, f'<span class="tool-reference">{tool}</span>', result, flags=re.IGNORECASE)
        
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
        
        entities = self._extract_entities(query, tools)
        extracted_location = entities.get("location")
        
        entities["user_timezone"] = user_timezone
        
        if not tools or query_type == "command_query":
            self._add_thought("No explicit tools found, trying search", None)
            search_terms = query.lower()
            for indicator in ["search", "find", "show", "get", "look up", "tell me about", "what is", "who is", "where is"]:
                search_terms = search_terms.replace(indicator, "").strip()
            if search_terms:
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
            return f"I couldn't find anything matching '{query}'. I can help with: time, weather, date, and day information."

    def _web_search_tool(self, entities: Dict[str, Any]) -> str:
        """Search the web using Brave Search API"""
        query = entities.get("search_query", "")
        self._add_thought("Executing web search", {"query": query})
        
        if not query:
            return "What would you like me to search for?"
        
        ip = request.remote_addr
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

app = Flask(__name__, static_folder='static')
app.secret_key = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'

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

@app.route('/api/query', methods=['POST'])
def process_query():
    data = request.json
    query = data.get('query', '')
    user_timezone = data.get('timezone', DEFAULT_TIMEZONE)
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    ip = request.remote_addr
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
    ip = request.remote_addr
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

@app.route('/login/google')
def login_google():
    """Login with Google OAuth"""
    redirect_uri = url_for('auth_google', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/login/github')
def login_github():
    """Login with GitHub OAuth"""
    redirect_uri = url_for('auth_github', _external=True)
    return oauth.github.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def auth_google():
    """Handle Google OAuth callback"""
    token = oauth.google.authorize_access_token()
    
    # Fix: Use the full URL for the userinfo endpoint
    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    
    user_id = f"google_{user_info['sub']}"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    existing_user = cursor.fetchone()
    
    if not existing_user:
        cursor.execute(
            "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
            (user_id, user_info.get('name'), user_info.get('email'), 'google', user_info.get('picture'))
        )
        conn.commit()
    
    conn.close()
    
    user = User(
        id=user_id,
        name=user_info.get('name'),
        email=user_info.get('email'),
        provider='google',
        profile_pic=user_info.get('picture')
    )
    login_user(user)
    
    return redirect('/')

@app.route('/auth/github')
def auth_github():
    """Handle GitHub OAuth callback"""
    token = oauth.github.authorize_access_token()
    resp = oauth.github.get('https://api.github.com/user', token=token)
    user_info = resp.json()
    
    email_resp = oauth.github.get('https://api.github.com/user/emails', token=token)
    emails = email_resp.json()
    primary_email = next((email['email'] for email in emails if email['primary']), 
                          emails[0]['email'] if emails else 'no-email@example.com')
    
    user_id = f"github_{user_info['id']}"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    existing_user = cursor.fetchone()
    
    if not existing_user:
        cursor.execute(
            "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
            (user_id, user_info.get('name', user_info.get('login')), primary_email, 'github', user_info.get('avatar_url'))
        )
        conn.commit()
    
    conn.close()
    
    user = User(
        id=user_id,
        name=user_info.get('name', user_info.get('login')),
        email=primary_email,
        provider='github',
        profile_pic=user_info.get('avatar_url')
    )
    login_user(user)
    
    return redirect('/')

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

if __name__ == "__main__":
    app.run(debug=True, port=5300)