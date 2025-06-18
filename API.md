# neubot API documentation
comprehensive API reference for neubot's semantic parsing chatbot

![banner](https://github.com/user-attachments/assets/c3f52133-1a6a-49e3-ba75-92c8583017fa)

## base URL
```
http://localhost:5300
```

## authentication
neubot supports OAuth2 authentication with Google and GitHub. Authentication is optional for basic functionality but required for Spotify integration and higher rate limits.

### authentication endpoints

#### `GET /login`
shows the login page with OAuth options

#### `GET /login/google`
initiates Google OAuth flow

#### `GET /auth/google`
handles Google OAuth callback

#### `GET /login/github`  
initiates GitHub OAuth flow

#### `GET /auth/github`
handles GitHub OAuth callback

#### `GET /logout`
logs out the current user

## core API endpoints

### query processing

#### `POST /api/query`
processes natural language queries using semantic parsing

**request body:**
```json
{
  "query": "what's the weather in paris?",
  "timezone": "America/New_York"
}
```

**response:**
```json
{
  "response": "The weather in Paris is clear sky with a temperature of 15.2°C/59.4°F and 65% humidity.",
  "thoughts": [
    {"description": "Received query", "result": "what's the weather in paris?"},
    {"description": "Found tool reference", "result": "weather"},
    {"description": "Weather data retrieved", "result": "{'temp_c': 15.2, 'temp_f': 59.4, 'condition': 'clear sky'}"}
  ],
  "highlightedQuery": "what's the <span class=\"tool-reference\">weather</span> in <span class=\"attribute\">paris</span>?"
}
```

### rate limits

#### `GET /api/limits`
returns current rate limit status for the requesting IP

**response:**
```json
{
  "search": {
    "used": 2,
    "limit": 5,
    "remaining": 3
  },
  "weather": {
    "used": 1,
    "limit": 3,
    "remaining": 2
  },
  "total": {
    "used": 8,
    "limit": 50,
    "remaining": 42
  }
}
```

### user information

#### `GET /api/user`
returns information about the currently authenticated user

**response (authenticated):**
```json
{
  "authenticated": true,
  "user": {
    "id": "google_123456789",
    "name": "John Doe",
    "email": "john@example.com",
    "provider": "google",
    "profile_pic": "https://example.com/photo.jpg"
  }
}
```

**response (not authenticated):**
```json
{
  "authenticated": false
}
```

## spotify integration

### connection status

#### `GET /api/integrations/spotify/status`
checks if user has linked their Spotify account

**response:**
```json
{
  "linked": true,
  "active": true,
  "message": "Spotify connected and active"
}
```

### connect spotify

#### `GET /login/spotify`
initiates Spotify OAuth flow (requires authentication)

#### `GET /auth/spotify/callback`
handles Spotify OAuth callback

### disconnect spotify

#### `POST /api/integrations/spotify/disconnect`
disconnects Spotify integration (requires login)

**response:**
```json
{
  "success": true,
  "message": "Spotify disconnected successfully"
}
```

### now playing

#### `GET /api/integrations/spotify/now-playing`
gets information about the currently playing track

**response:**
```json
{
  "track_name": "Bohemian Rhapsody",
  "artist": "Queen",
  "album_art": "https://i.scdn.co/image/ab67616d0000b273...",
  "track_url": "https://open.spotify.com/track/...",
  "is_playing": true,
  "device": "iPhone"
}
```

### playback control

#### `POST /api/integrations/spotify/control`
controls Spotify playback (requires login)

**request body:**
```json
{
  "action": "play"
}
```

**supported actions:** `play`, `pause`, `next`, `previous`

**response:**
```json
{
  "success": true,
  "message": "Playback started"
}
```

## semantic parsing tools

neubot includes several built-in tools that can be triggered through natural language:

### time tool
- **trigger words:** "time", "clock"
- **functionality:** gets current time for any location
- **example queries:** 
  - "what time is it?"
  - "what's the time in tokyo?"
  - "current time in london"

### weather tool  
- **trigger words:** "weather", "temperature"
- **functionality:** gets weather conditions using OpenWeatherMap API
- **example queries:**
  - "what's the weather in paris?"
  - "temperature in new york"
  - "how's the weather today?"

### date tool
- **trigger words:** "date", "today"
- **functionality:** gets current date
- **example queries:**
  - "what's today's date?"
  - "what date is it?"

### day tool
- **trigger words:** "day", "tomorrow"
- **functionality:** gets day of the week
- **example queries:**
  - "what day is it?"
  - "what day is tomorrow?"

### calculator tool
- **trigger words:** "calculate", "compute", "solve"
- **functionality:** performs mathematical calculations
- **example queries:**
  - "calculate 15 + 27"
  - "what's 42 * 8?"
  - "solve (10 + 5) / 3"

### web search tool
- **trigger words:** "search", "find", "look up"
- **functionality:** searches the web using Brave Search API
- **example queries:**
  - "search for python tutorials"
  - "find information about climate change"
  - "look up latest news"

### spotify tool
- **trigger words:** "spotify", "music", "play", "pause"
- **functionality:** controls Spotify playback and gets track info
- **example queries:**
  - "what's playing on spotify?"
  - "pause the music"
  - "skip to next song"
  - "play music"

## rate limiting

neubot implements rate limiting to manage API usage:

### guest users (not authenticated)
- **total queries:** 50 per month
- **weather requests:** 3 per month  
- **search requests:** 5 per month

### authenticated users
- **total queries:** 500 per month
- **weather requests:** 30 per month
- **search requests:** 50 per month

rate limits reset monthly and do not roll over.

## error responses

all endpoints return appropriate HTTP status codes:

- `200` - success
- `400` - bad request (missing or invalid parameters)
- `401` - unauthorized (authentication required)
- `403` - forbidden (rate limit exceeded)
- `404` - not found
- `500` - internal server error

**error response format:**
```json
{
  "error": "Error message description"
}
```

## static pages

#### `GET /`
serves the main chat interface

#### `GET /integrations`
shows integrations management page (requires login)

#### `GET /login`
shows login page with OAuth options


## semantic parsing features

- **intelligent query understanding:** recognizes intent from natural language
- **entity extraction:** automatically identifies locations, dates, calculations
- **tool routing:** maps queries to appropriate functionality
- **thought process:** provides transparent reasoning steps
- **query highlighting:** highlights recognized elements in queries
- **multi-tool support:** can handle complex queries requiring multiple tools

neubot uses no large language models - everything is handled through rule-based semantic parsing and external APIs.
