import re
import json
import requests
import pytz
import math
import random
import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Set, Tuple
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim
from flask_login import current_user
from flask import url_for

from backend.config import Config
from backend.database import get_db_connection
from backend.utils import get_client_ip, get_request_user_id
from backend.core.rate_limiter import RateLimiter
from backend.integrations.home_assistant import extract_ha_entities, execute_ha_tool, is_home_assistant_query
from backend.security import decrypt_token

@dataclass
class ThoughtStep:
    description: str
    result: Any

class SemanticParser:
    def __init__(self):
        self.thoughts: List[ThoughtStep] = []
        self.rate_limiter = RateLimiter()
        
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
            "good morning", "good afternoon", "good evening", "good night"
        ]
        
        self.greeting_responses = [
            "Hello to you too,",
            "Hi there,",
            "Hey,",
            "Nice to see you,",
            "Greetings,",
            "Hello,"
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
            "fun": self._fun_tool,
            "personal": self._personal_tool,
            "chitchat": self._chitchat_tool,
        }
        
        self.entity_types = {
            "location": self._extract_location,
            "date": self._extract_date,
            "math_expression": self._extract_math_expression,
        }

        self.search_indicator_phrases = [
            "what is", "who is", "where is", "when is", "tell me about", "look up", "find", "search for"
        ]
    
    def _reset_thoughts(self):
        self.thoughts = []
    
    def _add_thought(self, description: str, result: Any):
        self.thoughts.append(ThoughtStep(description, result))
    
    def _extract_query_type(self, tokens: List[str]) -> str:
        self._add_thought("Looking for query indicators", tokens[:3])
        
        # Check greeting phrases first (supports multi-word greetings like "good evening")
        ql = " ".join(tokens).lower()
        for gp in self.greeting_phrases:
            if ql.startswith(gp) or f" {gp} " in ql:
                self._add_thought(f"Matched greeting phrase '{gp}'", "greeting_query")
                return "greeting_query"
        
        for i in range(min(3, len(tokens))):
            word = tokens[i].lower().strip(".,?!")
            if word in self.query_indicators:
                query_type = self.query_indicators[word]
                self._add_thought(f"Found query indicator '{word}'", query_type)
                return query_type
        
        self._add_thought("No clear query indicator found", "unknown_query")
        return "unknown_query"
    
    def _identify_tools(self, tokens: List[str]) -> Set[str]:
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

        # Check for Home Assistant
        if "homeassistant" not in found_tools:
            if is_home_assistant_query(lowered):
                found_tools.add("homeassistant")
                self._add_thought("Inferred Home Assistant tool from verbs/domains", None)

        # Check for fun keywords
        fun_keywords = ["joke", "jokes", "destruct", "rainbow", "good morning", "good afternoon", "good evening", "good night", "goodnight"]
        if any(re.search(rf"\b{re.escape(kw)}\b", lowered) for kw in fun_keywords):
            found_tools.add("fun")
            self._add_thought("Inferred fun tool from query keyword/phrase", None)

        # Check for personal user identity query keywords
        personal_patterns = [
            r"\bmy name\b",
            r"\bwho am i\b",
            r"\bwhat is my name\b",
            r"\bdo you know my name\b",
            r"\bdo you know who i am\b",
            r"\bmy email\b",
            r"\bwhat is my email\b",
            r"\bam i logged in\b",
            r"\bmy account\b"
        ]
        if any(re.search(pat, lowered) for pat in personal_patterns):
            found_tools.add("personal")
            self._add_thought("Inferred personal tool from user identity query", None)

        # Check for chatbot chitchat keywords
        chitchat_patterns = [
            r"\b(who are you|your name|what are you called|what is your name)\b",
            r"\b(i'm neubot, nice to meet you|i'm neubot, nice to meet you!|my name is neubot|i'm neubot|im neubot|neubot is my name)\b",
            r"\b(how are you|how's it going|how are you doing)\b",
            r"\b(what can you do|what are your abilities|help me|what tools do you have)\b"
        ]
        if any(re.search(pat, lowered) for pat in chitchat_patterns):
            found_tools.add("chitchat")
            self._add_thought("Inferred chitchat tool from general query", None)

        # Logic to determine if we should fallback to search
        # If we already have specific tools (weather, time, calculator, etc),
        # strictly reserve search for EXPLICIT search commands.
        explicit_search = False
        generic_search_intent = False

        explicit_search_phrases = ["search for", "search", "look up", "find"]
        generic_search_phrases = ["what is", "who is", "where is", "when is", "tell me about"]

        for phrase in explicit_search_phrases:
            if lowered.startswith(phrase) or f" {phrase} " in lowered:
                explicit_search = True
                self._add_thought("Explicit search requested", phrase)
                break
        
        if not explicit_search:
             for phrase in generic_search_phrases:
                if lowered.startswith(phrase) or f" {phrase} " in lowered:
                    generic_search_intent = True
                    break

        if explicit_search:
            if "search" not in found_tools:
                found_tools.add("search")
        elif generic_search_intent:
            # Only add search if NO other tools found
            if not found_tools and "search" not in found_tools:
                found_tools.add("search")
                self._add_thought("Inferred search tool from generic phrase (no other tools found)", generic_search_intent)
                
        return found_tools

    def _extract_entities(self, query: str, tools: Set[str]) -> Dict[str, Any]:
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
                ha_entities = extract_ha_entities(query, self._add_thought)
                entities.update(ha_entities)
                entities.setdefault("search_query", query)
        
        entities.setdefault("search_query", query)
        self._add_thought("Extracted entities", entities)
        return entities
    
    def _extract_location(self, query: str) -> Optional[str]:
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
        location = entities.get("location")
        user_timezone = entities.get("user_timezone", Config.DEFAULT_TIMEZONE)
        
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
        self._add_thought("Executing date tool", None)
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        return f"Today's date is {current_date}."
    
    def _get_day(self, entities: Dict[str, Any]) -> str:
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
        location = entities.get("location", "unknown location")
        self._add_thought("Executing weather tool", {"location": location})
        
        if location == "unknown location":
            return "I need a location to check the weather. Please specify a city or place."
        
        ip = get_client_ip()
        user_id = get_request_user_id()
        allowed, remaining = self.rate_limiter.check_rate_limit(ip, "weather", user_id)
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
            
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={Config.OPENWEATHER_API_KEY}&units=metric"
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
                self.rate_limiter.add_request(ip, "weather", user_id)
            
            text_response = f"The weather in {capitalized_location} is {condition} with a temperature of {temp_c:.1f}°C/{temp_f:.1f}°F, and {humidity}% humidity."
            
            weather_widget = {
                "type": "weather",
                "data": {
                    "location": capitalized_location,
                    "condition": condition,
                    "temperature": {
                        "celsius": temp_c,
                        "fahrenheit": temp_f
                    },
                    "humidity": humidity,
                    "description": text_response
                }
            }
            
            return text_response, [weather_widget]
        
        except Exception as e:
            self._add_thought("Error getting weather", str(e))
            return f"Sorry, there was an error retrieving weather information for {location}.", []
    
    def _highlight_query(self, query: str, location: Optional[str] = None) -> str:
        # Use single pass replacement to avoid nesting tags
        query_indicators = ["what", "what's", "how", "when", "where", "who", "why", "is", "can", "tell", "show", "calculate", "compute", "solve"]
        tools = ["time", "weather", "date", "day", "calculator", "calc"]
        math_operators = ["plus", "minus", "times", "divided by", "multiplied by"]
        symbols = ["+", "-", "*", "/"]

        # Combine all patterns into one regex, sorted by length descending to match longest first
        all_patterns = []
        for p in query_indicators: all_patterns.append((p, "query-indicator"))
        for p in tools: all_patterns.append((p, "tool-reference"))
        for p in math_operators: all_patterns.append((p, "math-operator"))
        for p in symbols: all_patterns.append((p, "math-operator"))
        
        if location:
            all_patterns.append((location, "entity-location"))
            
        # Sort by length of pattern (descending)
        all_patterns.sort(key=lambda x: len(x[0]), reverse=True)
        
        # Build the master regex: (pattern1|pattern2|...)
        # We handle word boundaries conditionally based on content
        
        pattern_map = {p.lower(): cls for p, cls in all_patterns}
        pattern_parts = []
        
        for p, _ in all_patterns:
            escaped = re.escape(p)
            # If it starts with a word character, require word boundary at start
            # If it ends with a word character, require word boundary at end
            # This handles "weather" -> \bweather\b
            # And "+" -> \+ (no boundary)
            # And "Winston-Salem" -> \bWinston\-Salem\b
            
            part = escaped
            if p[0].isalnum():
                part = r'\b' + part
            if p[-1].isalnum():
                part = part + r'\b'
            
            pattern_parts.append(part)

        master_pattern = '(' + '|'.join(pattern_parts) + ')'
        
        def replace_match(match):
            word = match.group(0)
            # keys in pattern_map are lowercased
            cls = pattern_map.get(word.lower())
            if cls:
                return f'<span class="{cls}">{word}</span>'
            return word
            
        try:
            result = re.sub(master_pattern, replace_match, query, flags=re.IGNORECASE)
        except Exception:
            # Fallback if regex fails
            return query
            
        return result

    def _extract_math_expression(self, query: str) -> Optional[str]:
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
        self._add_thought("Extracting search query", None)
        q = query.strip()
        lowered = q.lower()
        lowered = lowered.strip("?!. ")
        patterns = [
            r"^(search for|search|look up|find|tell me about|what is|who is|where is|when is)\s+",
        ]
        for pattern in patterns:
            match = re.match(pattern, lowered)
            if match:
                return q[match.end():].strip()
        return q

    def _web_search_tool(self, entities: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
        query = entities.get("search_query", "")
        self._add_thought("Executing web search", {"query": query})
        
        if not query:
            return "What would you like me to search for?", []
        
        ip = get_client_ip()
        user_id = get_request_user_id()
        allowed, remaining = self.rate_limiter.check_rate_limit(ip, "search", user_id)
        if not allowed:
            return "Sorry, I can't search the web because you've exceeded your monthly limit.", []
        
        try:
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": Config.BRAVE_SEARCH_TOKEN
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
                return "I encountered an error while searching the web.", []
            
            data = response.json()
            
            search_items = []
            if "web" in data and "results" in data["web"]:
                web_results = data["web"]["results"]
                self._add_thought("Retrieved search results", len(web_results))
                
                for result in web_results:
                    search_items.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("description", ""),
                        "favicon": result.get("favicon", "")
                    })
            
            count = len(search_items)
            results_data = {
                "query": query,
                "spellcheck": data.get("spellcheck", None),
                "results": search_items,
                "meta": {
                    "total": count,
                    "header": f"Here's what I found on the web for \"{query}\""
                }
            }

            if response.status_code == 200 and count > 0:
                self.rate_limiter.add_request(ip, "search", user_id)
            
            if count > 0:
                text_response = f"I found {count} results for \"{query}\". The top result is {search_items[0]['title']}."
            else:
                text_response = f"I didn't find any results for \"{query}\"."
            
            widget = {
                "type": "search_results",
                "data": results_data
            }
            
            return text_response, [widget]
            
        except Exception as e:
            self._add_thought("Error performing web search", str(e))
            return "An error occurred while searching.", []

    def _home_assistant_tool(self, entities: Dict[str, Any]) -> str:
        return execute_ha_tool(entities, self._add_thought)

    def _calculator_tool(self, entities: Dict[str, Any]) -> str:
        self._add_thought("Executing calculator tool", None)
        
        math_expression = self._extract_math_expression(entities.get("search_query", ""))
        if not math_expression:
            return "I need a mathematical expression to calculate. Try something like '5 + 3' or '10 * 4'."
        
        try:
            expression = math_expression.lower()
            expression = re.sub(r'\bplus\b', '+', expression)
            expression = re.sub(r'\bminus\b', '-', expression)
            expression = re.sub(r'\btimes\b|\bmultiplied by\b', '*', expression)
            expression = re.sub(r'\bdivided by\b', '/', expression)
            cleaned_expr = re.sub(r'[^0-9+\-*/().\s]', '', expression)
            cleaned_expr = cleaned_expr.strip()
            self._add_thought("Evaluating expression", cleaned_expr)
            result = eval(cleaned_expr, {"__builtins__": {}})
            self._add_thought("Calculation result", result)
            if isinstance(result, int):
                return f"The result of {math_expression} is {result}."
            else:
                return f"The result of {math_expression} is {result:.4f}."
        except Exception as e:
            self._add_thought("Calculation error", str(e))
            return "There was an error evaluating that expression. Please check the syntax."

    def _fun_tool(self, entities: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
        self._add_thought("Executing fun tool", None)
        raw_query = entities.get("search_query") or ""
        if not raw_query:
            raw_query = ""
        q = raw_query.lower()

        jokes = [
            "Why did the web developer leave the restaurant? Because of the table layout.",
            "I would tell you a UDP joke, but you might not get it.",
            "Why do Java developers wear glasses? Because they don't C#.",
            "I told my computer I needed a break, and it said 'No problem — I'll go to sleep.'",
            "What do you call 8 hobbits? A hobbyte." ,
        ]

        def pick_joke():
            return random.choice(jokes)

        base_text = None
        widgets = []

        now = datetime.now()
        hour = now.hour
        if "good morning" in q:
            base_text = "Good morning! ☀️ Wishing you a productive day." if hour < 12 else "It's technically not morning anymore, but good day!" 
        elif "good night" in q or "goodnight" in q:
            base_text = "Good night! 🌙 Sleep well." if hour >= 18 else "It's a bit early, but have a relaxing evening anyway!" 
        elif "good evening" in q:
            base_text = "Good evening! 🌆" if 16 <= hour <= 23 else "It's not quite evening here, but hello!" 
        elif "good afternoon" in q:
            base_text = "Good afternoon! ☀️" if 12 <= hour < 17 else "It's not afternoon right now, but hello!" 
        elif "tell me a joke" in q or q.strip() == "joke" or "another joke" in q:
            base_text = pick_joke()
        elif "self destruct" in q or "self-destruct" in q:
            base_text = "Initiating self destruct sequence..."
            countdown_seconds = 5
            # HA logic for self destruct omitted for brevity/modularity, can be added back if needed
            widgets.append({
                "type": "fun_result",
                "variant": "self_destruct",
                "countdown": countdown_seconds,
                "finalText": "💥 BOOM!"
            })
        elif "rainbow" in q and ("light" in q or "lights" in q):
            base_text = "Launching rainbow sequence 🌈"
            # HA logic for rainbow omitted for brevity/modularity
            widgets.append({
                "type": "fun_result",
                "variant": "rainbow",
                "sequence": ["red","orange","yellow","green","blue","purple"],
                "text": "Rainbow cycle complete"
            })
        else:
            base_text = pick_joke()

        return base_text, widgets

    def _personal_tool(self, entities: Dict[str, Any]) -> str:
        from flask_login import current_user
        if current_user.is_authenticated and hasattr(current_user, 'name') and current_user.name:
            response = f"Your name is {current_user.name}."
            if hasattr(current_user, 'email') and current_user.email:
                response += f" You are logged in with the email {current_user.email}."
            self._add_thought("Answered personal query about user identity", response)
            return response
        else:
            response = "I don't know your name yet. Please sign in so I can get to know you!"
            self._add_thought("Personal query failed - user not authenticated", response)
            return response

    def _chitchat_tool(self, entities: Dict[str, Any]) -> str:
        raw_query = entities.get("search_query") or ""
        ql = raw_query.lower()
        
        bot_responses = {
            r"\b(who are you|your name|what are you called|what is your name)\b": [
                "I'm neubot, nice to meet you!",
                "I'm neubot, what's your name?",
                "People call me neubot!"
            ],
            r"\b(i'm neubot, nice to meet you|i'm neubot, nice to meet you!|my name is neubot|i'm neubot|im neubot|neubot is my name)\b": [
                "Wow, really? Me too!",
                "Are you sure? I thought I was neubot!",
                "What a coincidence, that's my name too!",
                "That line sounds familiar!"
            ],
            r"\b(how are you|how's it going|how are you doing)\b": [
                "I'm doing great, thank you! How can I help you today?",
                "Doing fantastic! How are you?",
                "All systems nominal and ready to help!"
            ],
            r"\b(what can you do|what are your abilities|help me|what tools do you have)\b": [
                "I can check the weather, tell you the time, control your smart home, search the web and so much more! What can I help you with?"
            ]
        }
        for pat, resp in bot_responses.items():
            if re.search(pat, ql):
                selected_resp = random.choice(resp) if isinstance(resp, list) else resp
                self._add_thought("Answered chatbot identity/chitchat query", selected_resp)
                return selected_resp
        return "I'm here to help you! How can I assist you?"

    def _should_split_query(self, query: str) -> List[str]:
        if ' and ' not in query.lower() and ' then ' not in query.lower():
            return []
            
        pattern = r'\s+and\s+then\s+|\s+then\s+|\s+and\s+'
        segments = re.split(pattern, query, flags=re.IGNORECASE)
        if len(segments) < 2:
            return []
            
        action_indicators = {
            "what", "how", "when", "where", "who", "why", "is", "are", "can", "could", "would", "should",
            "turn", "switch", "set", "dim", "brighten", "open", "close", "activate", "run", "start", "stop",
            "play", "pause", "tell", "show", "find", "get", "check", "read", "status", "state", "was", "were",
            "has", "have", "temperature", "temp", "tempature", "temperatue", "temperatur", "humidity", "humid", "humdity", "humidy", "humidty", "presence", "motion"
        }
        
        valid_segments = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            words = set(re.findall(r"\w+", seg.lower()))
            if words & action_indicators:
                valid_segments.append(seg)
                
        if len(valid_segments) == len(segments) and len(valid_segments) > 1:
            return valid_segments
        return []

    def process(self, query: str, user_timezone: str = Config.DEFAULT_TIMEZONE) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], str]:
        segments = self._should_split_query(query)
        if segments:
            responses = []
            all_widgets = []
            all_thoughts = []
            highlighted_parts = []
            
            for seg in segments:
                if query.rstrip().endswith('?') and not seg.rstrip().endswith('?'):
                    if seg == segments[-1]:
                        seg += '?'
                
                resp, widgets, thoughts, highlighted = self.process_single(seg, user_timezone)
                responses.append(resp)
                all_widgets.extend(widgets)
                all_thoughts.extend(thoughts)
                highlighted_parts.append(highlighted)
                
            combined_response = " and ".join([r.strip().rstrip('.') for r in responses if r.strip()])
            if combined_response:
                combined_response = combined_response[0].upper() + combined_response[1:] + "."
                
            combined_highlighted = " <span class=\"conjunction\">and</span> ".join(highlighted_parts)
            return combined_response, all_widgets, all_thoughts, combined_highlighted
            
        return self.process_single(query, user_timezone)

    def process_single(self, query: str, user_timezone: str = Config.DEFAULT_TIMEZONE) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], str]:
        self._reset_thoughts()
        self._add_thought("Received query", query)
        
        ql = query.lower()
        tokens = re.findall(r"[\w']+|[.,!?;]", query)
        
        query_type = self._extract_query_type(tokens)
        tools = self._identify_tools(tokens)
        
        if not tools:
            if query_type == "greeting_query":
                response = f"{random.choice(self.greeting_responses)} how can I help you today?"
                self._add_thought("Generated greeting response", response)
                return response, [], [t.__dict__ for t in self.thoughts], self._highlight_query(query)
            elif query_type == "information_query":
                tools.add("search")
                self._add_thought("Defaulting to search for information query", None)
            elif query_type == "calculator_query":
                tools.add("calculator")
                self._add_thought("Defaulting to calculator", None)
            else:
                tools.add("search")
                self._add_thought("Defaulting to search", None)
        
        entities = self._extract_entities(query, tools)
        entities["user_timezone"] = user_timezone
        
        responses = []
        all_widgets = []
        
        for tool in tools:
            if tool in self.known_tools:
                result = self.known_tools[tool](entities)
                if isinstance(result, tuple) and len(result) == 2:
                    text, widgets = result
                    responses.append(text)
                    if widgets:
                        all_widgets.extend(widgets)
                else:
                    responses.append(str(result))
        
        final_response = " ".join(responses)
        self._add_thought("Final response generated", final_response)
        
        return final_response, all_widgets, [t.__dict__ for t in self.thoughts], self._highlight_query(query, entities.get("location"))
