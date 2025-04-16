import re
import json
import datetime
import requests
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple, Set
from flask import Flask, request, jsonify, send_from_directory
import threading
import os
import pytz
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta
import time

load_dotenv()

# Get API keys and config values from environment variables
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "") 
BRAVE_SEARCH_TOKEN = os.getenv("BRAVE_SEARCH_TOKEN", "")

DEFAULT_TIMEZONE = "America/New_York"

WEATHER_RATE_LIMIT = 30  # requests per month
SEARCH_RATE_LIMIT = 50   # requests per month
TOTAL_QUERY_LIMIT = 500  # total requests per month

# SQLite database configuration
DB_FILE = "neubot.db"

@dataclass
class ThoughtStep:
    """Represents a single step in the bot's reasoning process"""
    description: str
    result: Any

class RateLimiter:
    def __init__(self):
        self._init_db()
        
    def _init_db(self):
        """Initialize SQLite database and create tables if they don't exist"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Create requests table to track all API requests
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            req_type TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )
        ''')
        
        # Create reset_dates table to track when limits were last reset
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reset_dates (
            ip TEXT PRIMARY KEY,
            reset_date DATETIME NOT NULL
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def _cleanup_old_requests(self, ip: str, req_type: str):
        """Remove requests older than 1 month"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        now = datetime.now()
        month_ago = now - timedelta(days=30)
        month_ago_str = month_ago.strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if all requests for this IP and type are older than a month
        cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE ip = ? AND req_type = ? AND timestamp > ?
        ''', (ip, req_type, month_ago_str))
        
        recent_count = cursor.fetchone()[0]
        
        # If no recent requests, reset counter by deleting old ones
        if recent_count == 0:
            cursor.execute('''
            DELETE FROM requests 
            WHERE ip = ? AND req_type = ?
            ''', (ip, req_type))
            
            # Update reset date
            cursor.execute('''
            INSERT OR REPLACE INTO reset_dates (ip, reset_date) 
            VALUES (?, ?)
            ''', (ip, now.strftime("%Y-%m-%d %H:%M:%S")))
        else:
            # Otherwise just delete old requests
            cursor.execute('''
            DELETE FROM requests 
            WHERE ip = ? AND req_type = ? AND timestamp < ?
            ''', (ip, req_type, month_ago_str))
        
        conn.commit()
        conn.close()
    
    def _get_next_reset(self, ip: str) -> datetime:
        """Get the next reset date for an IP's limits"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get last reset date
        cursor.execute('''
        SELECT reset_date FROM reset_dates WHERE ip = ?
        ''', (ip,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            last_reset = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        else:
            # If no reset date found, use current time and save it
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
    
    def check_rate_limit(self, ip: str, req_type: str) -> Tuple[bool, int]:
        """Check if request is within rate limits"""
        self._cleanup_old_requests(ip, req_type)
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get count of requests by type and total
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Check specific limit for API calls
        if req_type in ["search", "weather"]:
            limit = SEARCH_RATE_LIMIT if req_type == "search" else WEATHER_RATE_LIMIT
            
            cursor.execute('''
            SELECT COUNT(*) FROM requests 
            WHERE ip = ? AND req_type = ? AND timestamp > ?
            ''', (ip, req_type, month_ago))
            
            current_count = cursor.fetchone()[0]
        
        # Check total queries limit
        cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE ip = ? AND req_type = 'total' AND timestamp > ?
        ''', (ip, month_ago))
        
        total_count = cursor.fetchone()[0]
        conn.close()
        
        # For API calls, check both specific and total limits
        if req_type in ["search", "weather"]:
            return (current_count < limit and total_count < TOTAL_QUERY_LIMIT), \
                   min(limit - current_count, TOTAL_QUERY_LIMIT - total_count)
        
        # For regular queries, only check total limit
        return (total_count < TOTAL_QUERY_LIMIT), (TOTAL_QUERY_LIMIT - total_count)
    
    def add_request(self, ip: str, req_type: str):
        """Record a new request in the database"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert the request
        cursor.execute('''
        INSERT INTO requests (ip, req_type, timestamp)
        VALUES (?, ?, ?)
        ''', (ip, req_type, now))
        
        # Also add to total queries if not already counted
        if req_type != "total":
            cursor.execute('''
            INSERT INTO requests (ip, req_type, timestamp)
            VALUES (?, ?, ?)
            ''', (ip, "total", now))
        
        conn.commit()
        conn.close()
    
    def get_limits(self, ip: str) -> Dict[str, Dict[str, Any]]:
        """Get current rate limit status for an IP"""
        self._cleanup_old_requests(ip, "search")
        self._cleanup_old_requests(ip, "weather")
        self._cleanup_old_requests(ip, "total")
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Get counts for each request type
        cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE ip = ? AND req_type = 'search' AND timestamp > ?
        ''', (ip, month_ago))
        search_count = cursor.fetchone()[0]
        
        cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE ip = ? AND req_type = 'weather' AND timestamp > ?
        ''', (ip, month_ago))
        weather_count = cursor.fetchone()[0]
        
        cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE ip = ? AND req_type = 'total' AND timestamp > ?
        ''', (ip, month_ago))
        total_count = cursor.fetchone()[0]
        
        conn.close()
        
        # Calculate next reset date
        next_reset = self._get_next_reset(ip)
        reset_timestamp = int(next_reset.timestamp())
        
        # Calculate days until reset
        days_remaining = (next_reset - datetime.now()).days
        
        return {
            "search": {
                "limit": SEARCH_RATE_LIMIT,
                "remaining": SEARCH_RATE_LIMIT - search_count,
                "used": search_count
            },
            "weather": {
                "limit": WEATHER_RATE_LIMIT,
                "remaining": WEATHER_RATE_LIMIT - weather_count,
                "used": weather_count
            },
            "total": {
                "limit": TOTAL_QUERY_LIMIT,
                "remaining": TOTAL_QUERY_LIMIT - total_count,
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
        
        # Define question words that indicate different intent types
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
        }
        
        # Define tools/entities we can recognize
        self.known_tools = {
            "time": self._get_time,
            "weather": self._get_weather,
            "date": self._get_date,
            "day": self._get_day,
            "search": self._web_search_tool,  # Change this line
        }
        
        # Define entities we can extract
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
        
        # Check first few words for query indicators
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
                # Weather tool needs a location
                location = self._extract_location(query)
                if location:
                    entities["location"] = location
            
            if tool in ["time", "date", "day"]:
                # Time tools might need date specification
                date_spec = self._extract_date(query)
                if date_spec:
                    entities["date"] = date_spec
        
        self._add_thought("Extracted entities", entities)
        return entities
    
    def _extract_location(self, query: str) -> Optional[str]:
        """Extract location entity from query"""
        self._add_thought("Looking for location in query", None)
        
        # Convert common location words to title case for better matching
        title_query = query.title()
        
        # First try to match locations after prepositions (case insensitive)
        prep_pattern = r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=$|[.?!,]|\s+(?:and|with|at|is|are|was|were))"
        prep_match = re.search(prep_pattern, title_query, re.IGNORECASE)
        if prep_match:
            location = prep_match.group(1).strip()
            self._add_thought("Found location after preposition", location)
            return location
        
        # Then look for potential place names (case insensitive)
        location_pattern = r"\b([A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)*)\b"
        location_matches = re.finditer(location_pattern, title_query)
        
        for match in location_matches:
            location = match.group(1).strip()
            # Verify it's not a common sentence starter or word
            if not any(word.lower() in location.lower() for word in 
                      ["what", "where", "when", "how", "why", "the", "weather", "time"]):
                self._add_thought("Found standalone location", location)
                return location
        
        self._add_thought("No location found", None)
        return None
    
    def _extract_date(self, query: str) -> Optional[str]:
        """Extract date specification from query"""
        self._add_thought("Looking for date specification in query", None)
        
        # Look for specific date indicators
        today_match = re.search(r"today|now", query, re.IGNORECASE)
        if today_match:
            self._add_thought("Found reference to current date/time", "today")
            return "today"
            
        tomorrow_match = re.search(r"tomorrow", query, re.IGNORECASE)
        if tomorrow_match:
            self._add_thought("Found reference to tomorrow", "tomorrow")
            return "tomorrow"
        
        # More complex date parsing could be added here
        
        self._add_thought("No specific date reference found", "today")  # Default to today
        return "today"  # Default assumption
    
    def _get_time(self, entities: Dict[str, Any]) -> str:
        """Get the current time, optionally for a specific location"""
        location = entities.get("location")
        user_timezone = entities.get("user_timezone", DEFAULT_TIMEZONE)
        
        self._add_thought("Executing time tool", {"location": location, "user_timezone": user_timezone})
        
        try:
            if location:
                # Get timezone for the specified location
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
                # Use user's timezone if provided, otherwise default
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
        current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return f"Today's date is {current_date}."
    
    def _get_day(self, entities: Dict[str, Any]) -> str:
        """Get the current day of week"""
        self._add_thought("Executing day tool", None)
        current_day = datetime.datetime.now().strftime("%A")
        return f"Today is {current_day}."
    
    def _get_weather(self, entities: Dict[str, Any]) -> str:
        """Get actual weather information for a location using OpenWeatherMap API"""
        location = entities.get("location", "unknown location")
        self._add_thought("Executing weather tool", {"location": location})
        
        if location == "unknown location":
            return "I need a location to check the weather. Please specify a city or place."
        
        # Check rate limit
        ip = request.remote_addr
        allowed, remaining = rate_limiter.check_rate_limit(ip, "weather")
        if not allowed:
            return f"Sorry, I can't get weather information because you've exceeded your monthly limit."
        
        try:
            # Get coordinates for the location
            geolocator = Nominatim(user_agent="neubot")
            location_data = geolocator.geocode(location)
            
            if not location_data:
                self._add_thought("Could not geocode location", location)
                return f"I couldn't find the location '{location}'. Please check the spelling or try a different location."
            
            # Capitalize location name properly
            capitalized_location = location_data.address.split(',')[0].strip()
            
            lat, lon = location_data.latitude, location_data.longitude
            self._add_thought("Geocoded location", {"lat": lat, "lon": lon})
            
            # Call OpenWeatherMap API
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
            response = requests.get(weather_url)
            
            if response.status_code != 200:
                self._add_thought("OpenWeatherMap API error", {"status": response.status_code})
                return f"Sorry, I couldn't retrieve the weather information for {capitalized_location} right now."
            
            weather_data = response.json()
            temp_c = weather_data["main"]["temp"]
            # Convert Celsius to Fahrenheit
            temp_f = (temp_c * 9/5) + 32
            condition = weather_data["weather"][0]["description"]
            humidity = weather_data["main"]["humidity"]
            
            self._add_thought("Weather data retrieved", {"temp_c": temp_c, "temp_f": temp_f, "condition": condition})
            
            # Record the request if successful
            if response.status_code == 200:
                rate_limiter.add_request(ip, "weather")
            
            return f"The weather in {capitalized_location} is {condition} with a temperature of {temp_c:.1f}°C/{temp_f:.1f}°F and {humidity}% humidity."
        
        except Exception as e:
            self._add_thought("Error getting weather", str(e))
            return f"Sorry, there was an error retrieving weather information for {location}."
    
    def _highlight_query(self, query: str, location: Optional[str] = None) -> str:
        """Add HTML spans for color highlighting query parts"""
        result = query
        
        # Highlight query indicators (purple)
        query_indicators = ["what", "what's", "how", "when", "where", "who", "why", "is", "can", "tell", "show"]
        for indicator in query_indicators:
            pattern = fr'\b{indicator}\b'
            result = re.sub(pattern, f'<span class="query-indicator">{indicator}</span>', result, flags=re.IGNORECASE)
        
        # Highlight tools (red)
        tools = ["time", "weather", "date", "day"]
        for tool in tools:
            pattern = fr'\b{tool}\b'
            result = re.sub(pattern, f'<span class="tool-reference">{tool}</span>', result, flags=re.IGNORECASE)
        
        # Highlight location (yellow) - using passed location
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
        
        # Tokenize the query
        tokens = query.split()
        self._add_thought("Tokenized query", tokens)
        
        # Step 1: Determine query type from question words
        query_type = self._extract_query_type(tokens)
        
        # Step 2: Identify which tools are mentioned or implied
        tools = self._identify_tools(tokens)
        
        # If no explicit tools found, try to infer from context
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
        
        # Step 3: Extract relevant entities based on identified tools
        entities = self._extract_entities(query, tools)
        extracted_location = entities.get("location")  # Store extracted location
        
        # Add user timezone to entities
        entities["user_timezone"] = user_timezone
        
        # Update the search inference logic
        if not tools or query_type == "command_query":
            self._add_thought("No explicit tools found, trying search", None)
            # Extract search terms by removing query indicators
            search_terms = query.lower()
            for indicator in ["search", "find", "show", "get", "look up", "tell me about", "what is", "who is", "where is"]:
                search_terms = search_terms.replace(indicator, "").strip()
            if search_terms:
                tools.add("search")
                entities["search_query"] = search_terms
                self._add_thought("Inferred search tool", {"terms": search_terms})
        
        # Step 4: Execute the appropriate tools
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
        
        self._add_thought("Generated final response", final_response)
        return final_response, self.thoughts, extracted_location

    def _search_tool(self, entities: Dict[str, Any]) -> str:
        """Search through available tools and information"""
        query = entities.get("search_query", "").lower()
        self._add_thought("Executing search tool", {"query": query})
        
        if not query:
            return "What would you like me to search for?"
            
        # Define searchable capabilities
        capabilities = {
            "time": "I can tell you the current time in any location or timezone.",
            "weather": "I can check the weather conditions, temperature, and humidity for any location.",
            "date": "I can tell you today's date or check future dates.",
            "day": "I can tell you the current day of the week.",
        }
        
        # Search through capabilities
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
        
        # Check rate limit
        ip = request.remote_addr
        allowed, remaining = rate_limiter.check_rate_limit(ip, "search")
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
                "query": query,  # Keep the query for displaying
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
            
            # Record the request if successful
            if response.status_code == 200:
                rate_limiter.add_request(ip, "search")
            
            return json.dumps(results)
            
        except Exception as e:
            self._add_thought("Error performing web search", str(e))
            return json.dumps({
                "type": "search_results",
                "error": "Search failed"
            })

# Create a Flask application to serve the API and web UI
app = Flask(__name__, static_folder='static')
parser = SemanticParser()
rate_limiter = RateLimiter()

@app.route('/api/query', methods=['POST'])
def process_query():
    data = request.json
    query = data.get('query', '')
    user_timezone = data.get('timezone', DEFAULT_TIMEZONE)
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    # Check total query limit first
    ip = request.remote_addr
    allowed, remaining = rate_limiter.check_rate_limit(ip, "total")
    if not allowed:
        return jsonify({
            "response": "Sorry, I can't respond because you've exceeded your monthly limit of queries.",
            "thoughts": [],
            "highlightedQuery": query
        })
    
    # Record the query in total count
    rate_limiter.add_request(ip, "total")
    
    # Get response, thoughts, and highlighted query
    response, thoughts, highlighted_query = parser.process_query(query, user_timezone)
    
    # Convert thoughts to serializable format
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
    limits = rate_limiter.get_limits(ip)
    return jsonify(limits)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if (path == "" or path == "index.html"):
        return send_from_directory('static', 'index.html')
    return send_from_directory('static', path)

if __name__ == "__main__":
    # Run Flask app
    app.run(debug=True, port=5300)