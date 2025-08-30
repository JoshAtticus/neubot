# neubot API documentation
comprehensive API reference for neubot

![banner](https://github.com/user-attachments/assets/c3f52133-1a6a-49e3-ba75-92c8583017fa)

## base URL
```
https://neubot.joshatticus.site/
```

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

## Authentication
neubot supports OAuth2 authentication with Google and GitHub. Authentication is optional for basic functionality but provides higher rate limits and enables account‑scoped integrations (e.g. Home Assistant).

To make authenticated requests to the API, you need to include an `Authorization` header with your API token. The token should be included as a `Bearer` token.

**Header format:**
```
Authorization: Bearer [YOUR_TOKEN]
```

Replace `[YOUR_TOKEN]` with the token you received after a successful login.

**Example using `curl`:**
```bash
curl -X GET https://neubot.joshatticus.site/api/limits \
     -H "Authorization: Bearer [YOUR_TOKEN]"
```

### App Authentication

To authenticate users from your application, you can redirect them to the neubot login page with a special `callbackURL`. This URL must contain a parameter with the value `[TOKEN]`.

After the user successfully authenticates, they will be redirected back to this URL, with `[TOKEN]` replaced by their API token.

## Home Assistant Integration (Beta)

Link a Home Assistant instance you control to issue natural‑language smart home commands through the chat interface.

### `POST /api/integrations/home-assistant/start`
Initiate the Home Assistant Auth API OAuth-like flow. Provide the root URL of your HA instance.

Request JSON:
```
{ "base_url": "https://your-ha.example.com" }
```
Response:
```
{ "success": true, "authorize_url": "https://your-ha.example.com/auth/authorize?..." }
```
Open the returned `authorize_url` in a new browser tab/window while logged into Home Assistant, approve the consent screen, and you'll be redirected back to neubot which will exchange the code for tokens.

Token handling:
- Access & refresh tokens are stored encrypted (Fernet) with expiry (expires_at epoch seconds).
- Tokens are refreshed automatically when expired.
- Use HTTPS for your HA base URL whenever possible.

### `GET /api/integrations/home-assistant/status`
Returns whether the current user has a linked HA configuration.

Success response example:
```
{ "connected": true, "base_url": "https://your-ha.example.com", "expires_at": 1729999999 }
```

### Planned Endpoints (not yet implemented)
- `GET /api/integrations/home-assistant/entities` list cached / live entities
- `POST /api/integrations/home-assistant/service` invoke arbitrary domain.service with entity_id(s)
- `DELETE /api/integrations/home-assistant/link` unlink & purge stored tokens

### Natural Language Examples
Examples of queries that will trigger the `homeassistant` tool:
- "turn on the kitchen lights"
- "switch off all bedroom fans"
- "activate the movie scene"
- "run the bedtime script"

Natural language detection automatically triggers the Home Assistant tool when a control verb (turn on/off, activate, run, start, stop) appears together with a supported domain word (light(s), fan(s), switch(es), scene(s), script(s)). The parser currently picks one matching entity; multi‑entity / area fan‑out is on the roadmap.

**Login URL format:**

`https://neubot.joshatticus.site/login/app?callbackURL=[YOUR_CALLBACK_URL]`

**Example `callbackURL`:**

`https://yourapp.com/auth/neubot?token=[TOKEN]`

**Example login URL:**

`https://neubot.joshatticus.site/login/app?callbackURL=https://yourapp.com/auth/neubot?token=%5BTOKEN%5D`

Note that the `callbackURL` must be URL encoded.

## semantic parsing features

- **intelligent query understanding:** recognizes intent from natural language
- **entity extraction:** automatically identifies locations, dates, calculations
- **tool routing:** maps queries to appropriate functionality
- **thought process:** provides transparent reasoning steps
- **query highlighting:** highlights recognized elements in queries
- **multi-tool support:** can handle complex queries requiring multiple tools

neubot uses no large language models - everything is handled through rule-based semantic parsing and external APIs.
