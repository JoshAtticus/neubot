import re
import json
import time
import requests
import random
import threading
from typing import Dict, Any, Optional, Callable, List, Tuple, Set
from flask import url_for
from flask_login import current_user
from backend.database import get_db_connection
from backend.security import encrypt_token, decrypt_token
from backend.config import Config

HA_ACTION_VERBS = {
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
    "set": "turn_on",
}

HA_DOMAIN_TERMS = {
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

def is_home_assistant_query(query: str) -> bool:
    """Detects if a query is intended for Home Assistant."""
    ql = query.lower()
    
    # Check for sensor keywords
    sensor_keywords = ["temperature", "temp", "humidity", "humid", "presence", "motion", "occupancy", "movement", "someone", "somebody", "anyone", "anybody"]
    has_sensor_keyword = any(re.search(rf"\b{re.escape(k)}\b", ql) for k in sensor_keywords)
    if has_sensor_keyword:
        question_indicators = ["what", "how", "is", "are", "check", "get", "read", "show", "status", "tell", "state", "find", "who"]
        if any(re.search(rf"\b{re.escape(qi)}\b", ql) for qi in question_indicators) or "temperature" in ql or "humidity" in ql:
            return True
            
    # Check for direct domains
    has_domain = False
    for term in HA_DOMAIN_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", ql):
            has_domain = True
            break
    
    if has_domain:
        # Check for action words
        for verb in HA_ACTION_VERBS:
            if verb in ql:
                return True
        
        # Check for state questions "is/are ... on/off"
        if re.search(r"^\s*(is|are)\b", ql):
            return True
            
        # Check for explicitly asking for status/state
        if re.search(r"\b(status|state)\b", ql):
            return True

    return False

def extract_ha_entities(query: str, thought_logger: Callable[[str, Any], None]) -> Dict[str, Any]:
    thought_logger("Extracting Home Assistant entities", None)
    ql = query.lower()
    result: Dict[str, Any] = {}

    sensor_keywords = ["temperature", "temp", "humidity", "humid", "presence", "motion", "occupancy", "movement", "someone", "somebody", "anyone", "anybody"]
    has_sensor_keyword = any(re.search(rf"\b{re.escape(k)}\b", ql) for k in sensor_keywords)

    if has_sensor_keyword:
        result["ha_action"] = "get_state"
        
        sensor_types = []
        if "temp" in ql or "temperature" in ql or "warm" in ql or "cold" in ql or "hot" in ql:
            sensor_types.append("temperature")
        if "humid" in ql or "humidity" in ql or "moisture" in ql:
            sensor_types.append("humidity")
        if any(k in ql for k in ["presence", "motion", "someone", "somebody", "anyone", "anybody", "movement", "occupancy", "occupied"]):
            sensor_types.append("presence")
            
        if sensor_types:
            result["ha_sensor_types"] = sensor_types
            result["ha_sensor_type"] = sensor_types[0]
            result["ha_domain"] = "sensor" if "presence" not in sensor_types or len(sensor_types) > 1 else "binary_sensor"

        ha_area = None
        
        # 1. Match area after sensor keywords
        kw_pattern = r"\b(?:temperature|temp|humidity|humid|presence|motion|occupancy|movement|someone)\b"
        area_after_match = re.search(
            rf"{kw_pattern}(?:\s+(?:and|or)\s+{kw_pattern})?\s*(?:in|at|for|of)?\s*(?:the|my)?\s*([a-zA-Z ]{{2,30}})",
            ql
        )
        if area_after_match:
            candidate = area_after_match.group(1).strip()
            candidate = re.sub(r"\b(please|now|right|today|sensor|sensors|is|are|get|read|show|check|tell|what|whats)\b", "", candidate).strip()
            candidate = candidate.rstrip('?').strip()
            if candidate and len(candidate.split()) <= 3:
                ha_area = candidate

        # 2. Preposition fallback
        if not ha_area:
            area_match = re.search(r"\b(?:in|at|for|of)\s+(?:the|my)?\s*([a-zA-Z ]{2,30})", ql)
            if area_match:
                candidate = area_match.group(1).strip()
                candidate = re.sub(r"\b(please|now|right|today|sensor|sensors)\b", "", candidate).strip()
                candidate = candidate.rstrip('?').strip()
                if candidate and len(candidate.split()) <= 3:
                    ha_area = candidate

        # 3. Backward match fallback
        if not ha_area:
            for kw in sensor_keywords:
                m = re.search(rf"\b([a-zA-Z ]{{2,30}}?)\b{re.escape(kw)}\b", ql)
                if m:
                    candidate = m.group(1).strip()
                    candidate = re.sub(r"\b(turn|switch|set|activate|run|start|stop|on|off|the|my|a|to|what|whats|is|are|check|get|read)\b", "", candidate).strip()
                    if candidate and len(candidate.split()) <= 3:
                        ha_area = candidate
                        break

        if ha_area:
            result["ha_area"] = ha_area
            
        return result

    action = None
    # Check for state inquiries
    if re.search(r"^\s*(is|are)\b.*\b(on|off)\b", ql) or "status" in ql or re.search(r"\b(check|what)\b.*\b(is|are)\b", ql):
        action = "get_state"

    if not action and re.search(r"\bset\b.*\b(off|stop|disable)\b", ql):
        action = "turn_off"

    if not action:
        for phrase, canonical in HA_ACTION_VERBS.items():
            if " " in phrase and phrase in ql:
                action = canonical
                break
    if not action:
        tokens = re.findall(r"\b\w+\b", ql)
        for i, tok in enumerate(tokens):
            if tok in HA_ACTION_VERBS and len(tok) > 2: 
                action = HA_ACTION_VERBS[tok]
                break
        if not action:
            if re.search(r"\bturn\s+on\b|\bon\b", ql):
                action = "turn_on"
            elif re.search(r"\bturn\s+off\b|\boff\b", ql):
                action = "turn_off"
    if action:
        result["ha_action"] = action

    domain = None
    for term, canonical in HA_DOMAIN_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", ql):
            domain = canonical
            break
    if domain:
        result["ha_domain"] = domain

    ha_area = None
    if domain:
        m = re.search(rf"\b([a-zA-Z ]{{2,40}}?)\b(?:{domain}|{domain}s|lamp|lamps|bulb|bulbs)\b", ql)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(r"\b(turn|switch|set|activate|run|start|stop|on|off|the|my|a|to)\b", "", candidate).strip()
            if 0 < len(candidate.split()) <= 3:
                ha_area = candidate
    if ha_area:
        result["ha_area"] = ha_area
        
    return result

def format_ha_summary(action: str, domain: str, results: List[Dict[str, Any]]) -> str:
    """Generates a natural language summary for HA actions."""
    if not results:
        return "I couldn't find any devices to control."

    names = [r['name'] for r in results]
    count = len(names)
    
    # State inquiry summary
    if action == 'get_state':
        on_devices = []
        off_devices = []
        for r in results:
            state = r.get('state_current', 'unknown')
            if state == 'on':
                details = r['name']
                attrs = r.get('attributes', {})
                if attrs.get('brightness'):
                    pct = round(int(attrs['brightness']) / 255 * 100)
                    details += f" at {pct}% brightness"
                on_devices.append(details)
            else:
                off_devices.append(r['name'])
        
        parts = []
        if on_devices:
            if len(on_devices) == count and count > 1:
                parts.append(f"All {count} {domain}s are on")
                # Check if all have same brightness
                # For simplicity, just listing details if few, or generic if many
                if count <= 3:
                    parts[-1] = f"{', '.join(on_devices)} are on"
            else:
                parts.append(f"{', '.join(on_devices)} {'is' if len(on_devices)==1 else 'are'} on")
        
        if off_devices:
            parts.append(f"{', '.join(off_devices)} {'is' if len(off_devices)==1 else 'are'} off")
            
        return "; ".join(parts) + "."

    # Control action summary
    success_items = [r for r in results if r['success']]
    if not success_items:
        return f"I failed to {action.replace('_', ' ')} the {domain}s."
    
    verb = "turned on" if action == "turn_on" else "turned off"
    
    if len(success_items) == 1:
        item = success_items[0]
        text = f"I {verb} {item['name']}"
        if item.get('applied_brightness_pct'):
            text += f" to {item['applied_brightness_pct']}%"
        if item.get('applied_color'):
             text += f" ({item['applied_color']})"
        return text + "."
    
    # Multiple items
    brightness_set = {r.get('applied_brightness_pct') for r in success_items if r.get('applied_brightness_pct')}
    color_set = {r.get('applied_color') for r in success_items if r.get('applied_color')}
    
    text = f"I {verb} {len(success_items)} {domain}s"
    
    if len(brightness_set) == 1:
        text += f" to {list(brightness_set)[0]}% brightness"
    
    if len(color_set) == 1:
        text += f" ({list(color_set)[0]})"
    elif len(color_set) > 1:
        text += " with multiple colors"
        
    return text + "."

def execute_ha_tool(entities: Dict[str, Any], thought_logger: Callable[[str, Any], None]) -> Tuple[str, List[Dict[str, Any]]]:
    thought_logger("Executing Home Assistant tool", None)
    if not current_user.is_authenticated:
        return "You need to login and link Home Assistant first.", []
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT base_url, access_token, refresh_token, expires_at FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        row = cur.fetchone()
    if not row:
        return "You haven't linked Home Assistant yet. Go to Integrations to connect it.", []

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

    now_ts = int(time.time())
    # Refresh if expires in less than 5 minutes (300s) or already expired
    if expires_at and expires_at < now_ts + 300 and refresh_token:
        try:
            token_resp = requests.post(
                f"{base_url}/auth/token",
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token,
                    'client_id': url_for('api.ha_callback', _external=True)
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
            pass 

    action = entities.get('ha_action')
    domain = entities.get('ha_domain')
    area = entities.get('ha_area')
    device_phrase = entities.get('ha_device_phrase')
    
    if not action:
        if re.search(r"\b(turn on|switch on|activate|start|run)\b", ql):
            action = 'turn_on'
        elif re.search(r"\b(turn off|switch off|deactivate|stop)\b", ql):
            action = 'turn_off'
    if not domain:
        for term, canonical in HA_DOMAIN_TERMS.items():
            if re.search(rf"\b{re.escape(term)}\b", ql):
                domain = canonical
                break
    if domain in ('scene', 'script') and not action:
        action = 'turn_on'
    if not domain:
        return "I couldn't determine what device you want to control.", []

    room = area
    if not room:
        room_match = re.search(r"\b(?:my|the)?\s*([a-zA-Z ]+?)\s+(?:light|lights|fan|fans|switch|switches|lamp|lamps|bulb|bulbs)\b", ql)
        if room_match:
            cand = room_match.group(1).strip()
            if cand and len(cand.split()) <= 3 and not re.search(r"turn|on|off|activate|run|switch|set|dim|brighten", cand):
                room = cand

    try:
        resp = requests.get(
            f"{base_url}/api/states",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=5
        )
        if resp.status_code != 200:
            return f"Failed to reach Home Assistant ({resp.status_code}).", []
        states = resp.json()
    except Exception as e:
        return f"Error contacting Home Assistant: {e}", []

    sensor_types = entities.get('ha_sensor_types') or []
    if not sensor_types and entities.get('ha_sensor_type'):
        sensor_types = [entities.get('ha_sensor_type')]

    if sensor_types:
        user_name = None
        if current_user.is_authenticated and hasattr(current_user, 'name') and current_user.name:
            user_name = current_user.name.split()[0].lower()

        areas = []
        if area:
            raw_areas = re.split(r'\band\b|\bor\b|,', area)
            for ra in raw_areas:
                cleaned = ra.strip()
                if cleaned:
                    cleaned = re.sub(r'^(the|my|a)\s+', '', cleaned).strip()
                    if cleaned:
                        if cleaned.endswith('s') and len(cleaned) > 3:
                            singular = cleaned[:-1]
                            areas.append(singular)
                        areas.append(cleaned)
        else:
            areas = []

        selected_candidates = []
        
        for s_type in sensor_types:
            candidates = []
            for st in states:
                eid = st.get('entity_id', '')
                
                # Temperature & Humidity queries must ONLY match sensor.* entities
                if s_type in ('temperature', 'humidity'):
                    if not eid.startswith('sensor.'):
                        continue
                else:
                    if not (eid.startswith('sensor.') or eid.startswith('binary_sensor.')):
                        continue
                    
                fname = st.get('attributes', {}).get('friendly_name', '') or ''
                fname_l = fname.lower()
                eid_l = eid.lower()
                
                is_type_match = False
                unit = st.get('attributes', {}).get('unit_of_measurement', '') or ''
                device_class = st.get('attributes', {}).get('device_class', '') or ''
                
                if s_type == 'temperature':
                    if 'temperature' in fname_l or 'temp' in fname_l or device_class == 'temperature' or '°' in unit or unit in ('C', 'F'):
                        is_type_match = True
                elif s_type == 'humidity':
                    # Smart filter: exclude dehumidifiers from humidity queries
                    if ('humidity' in fname_l or 'humid' in fname_l) and 'dehumid' not in fname_l and 'dehumid' not in eid_l:
                        is_type_match = True
                elif s_type == 'presence':
                    presence_keywords = ['motion', 'presence', 'occupancy', 'movement', 'occupant', 'pir', 'occupy', 'someone', 'somebody', 'person']
                    if any(kw in fname_l or kw in eid_l for kw in presence_keywords) or device_class in ('motion', 'occupancy', 'presence', 'moving'):
                        is_type_match = True
                        
                if not is_type_match:
                    continue
                    
                # Score candidate based on area/room
                score = 0.0
                if areas:
                    for a in areas:
                        a_l = a.lower()
                        a_words = [w for w in re.findall(r"\w+", a_l) if w not in ('the', 'my', 'a', 'in', 'at')]
                        
                        if a_l in fname_l or a_l in eid_l:
                            score = max(score, 1.0)
                            
                        word_matches = sum(1 for w in a_words if w in fname_l or w in eid_l)
                        if a_words:
                            match_ratio = (word_matches / len(a_words)) * 0.8
                            score = max(score, match_ratio)
                            
                        # Special veranda front door matching
                        if 'front door' in a_l and ('front' in fname_l or 'door' in fname_l or 'veranda' in fname_l):
                            score = max(score, 0.5)
                            
                    # Personalization boost: if query has "my" and sensor friendly name contains user name
                    if 'my' in ql and user_name:
                        if user_name in fname_l or user_name in eid_l:
                            score += 0.5
                            thought_logger(f"Applied personal context for user '{user_name}' on sensor '{fname}'", None)
                else:
                    score = 0.1
                    
                # Prioritize binary_sensors for presence
                if s_type == 'presence' and eid.startswith('binary_sensor.'):
                    score += 0.1
                    
                # Slightly lower score for unavailable/unknown sensors so active ones are preferred
                state_val = st.get('state', 'unknown')
                if state_val.lower() in ('unavailable', 'unknown'):
                    score -= 0.2
                    
                candidates.append((score, st, fname, eid, s_type))
                
            # Filter and keep candidates with score >= 0.5 that are close to the highest score
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                highest_score = candidates[0][0]
                for cand in candidates:
                    c_score = cand[0]
                    if c_score >= 0.5:
                        if c_score >= highest_score - 0.2:
                            selected_candidates.append(cand)

        # Fallback if no match is found
        if area and not selected_candidates:
            all_sensors_of_type = []
            for st in states:
                eid = st.get('entity_id', '')
                if not (eid.startswith('sensor.') or eid.startswith('binary_sensor.')):
                    continue
                fname = st.get('attributes', {}).get('friendly_name', '') or ''
                fname_l = fname.lower()
                device_class = st.get('attributes', {}).get('device_class', '') or ''
                unit = st.get('attributes', {}).get('unit_of_measurement', '') or ''
                
                is_type_match = False
                for s_type in sensor_types:
                    if s_type == 'temperature':
                        if eid.startswith('sensor.'):
                            if 'temperature' in fname_l or 'temp' in fname_l or device_class == 'temperature' or '°' in unit or unit in ('C', 'F'):
                                is_type_match = True
                    elif s_type == 'humidity':
                        if eid.startswith('sensor.'):
                            if ('humidity' in fname_l or 'humid' in fname_l) and 'dehumid' not in fname_l and 'dehumid' not in eid_l:
                                is_type_match = True
                    elif s_type == 'presence':
                        presence_keywords = ['motion', 'presence', 'occupancy', 'movement', 'occupant', 'pir', 'occupy', 'someone', 'somebody', 'person']
                        if any(kw in fname_l or kw in eid_l for kw in presence_keywords) or device_class in ('motion', 'occupancy', 'presence', 'moving'):
                            is_type_match = True
                        
                if is_type_match:
                    cleaned = fname
                    for suffix in [" Temperature", " temperature", " Temp", " temp", " Humidity", " humidity", " Presence", " presence", " Motion", " motion", " Occupancy", " occupancy", " Sensor", " sensor"]:
                        cleaned = cleaned.replace(suffix, "")
                    if cleaned and cleaned not in all_sensors_of_type:
                        all_sensors_of_type.append(cleaned)
            
            type_words = []
            for s_type in sensor_types:
                type_words.append("temperature" if s_type == "temperature" else "humidity" if s_type == "humidity" else "presence")
            type_word = " and ".join(type_words)
            
            msg = f"I couldn't find a {type_word} sensor for the '{area}'."
            if all_sensors_of_type:
                msg += f" Available areas: {', '.join(all_sensors_of_type)}."
            else:
                msg += f" I couldn't find any {type_word} sensors linked to your Home Assistant."
            return msg, []
            
        if not selected_candidates:
            type_word = "temperature" if "temperature" in sensor_types else "humidity" if "humidity" in sensor_types else "presence"
            return f"I couldn't find any active {type_word} sensors in your Home Assistant configuration.", []

        def format_area_with_preposition(area_name: str) -> str:
            lower_name = area_name.lower()
            if "'s" in lower_name or lower_name.startswith("josh") or lower_name.startswith("jesse"):
                return area_name
            else:
                return f"the {area_name}"

        # If multiple sensors selected (e.g. plural or multiple rooms/types requested)
        if len(selected_candidates) > 1:
            area_readings = {}
            results = []
            for score, st, fname, eid, s_type in selected_candidates:
                curr_state = st.get('state', 'unknown')
                attrs = st.get('attributes', {})
                unit = attrs.get('unit_of_measurement', '') or ''
                
                if curr_state.lower() in ("unavailable", "unknown"):
                    unit_str = ""
                else:
                    unit_str = unit or ("°C" if s_type == "temperature" else "%" if s_type == "humidity" else "")
                
                cleaned_area = fname
                for suffix in [" Temperature", " temperature", " Temp", " temp", " Humidity", " humidity", " Presence", " presence", " Motion", " motion", " Occupancy", " occupancy", " Sensor", " sensor"]:
                    cleaned_area = cleaned_area.replace(suffix, "")
                    
                results.append({
                    'entity_id': eid,
                    'name': fname,
                    'requested_action': 'get_state',
                    'success': True,
                    'code': 200,
                    'state_current': curr_state,
                    'attributes': attrs,
                    'state_before': curr_state
                })
                
                if cleaned_area not in area_readings:
                    area_readings[cleaned_area] = []
                area_readings[cleaned_area].append((s_type, curr_state, unit_str))
                
            area_summaries = []
            for cleaned_area, readings in area_readings.items():
                if len(readings) == 1:
                    s_type, state, unit_str = readings[0]
                    if state.lower() in ("unavailable", "unknown"):
                        area_summaries.append(f"the sensor in {format_area_with_preposition(cleaned_area)} is {state.lower()}")
                    else:
                        if s_type == 'temperature':
                            area_summaries.append(f"the temperature in {format_area_with_preposition(cleaned_area)} is {state}{unit_str}")
                        elif s_type == 'humidity':
                            area_summaries.append(f"the humidity in {format_area_with_preposition(cleaned_area)} is {state}{unit_str}")
                        elif s_type == 'presence':
                            status = "someone is detected" if state == 'on' else "clear"
                            area_summaries.append(f"{format_area_with_preposition(cleaned_area)} is {status}")
                else:
                    reading_texts = []
                    for s_type, state, unit_str in readings:
                        if state.lower() in ("unavailable", "unknown"):
                            reading_texts.append(f"the {s_type} sensor is {state.lower()}")
                        elif s_type == 'presence':
                            status = "someone is detected" if state == 'on' else "clear"
                            reading_texts.append(status)
                        else:
                            reading_texts.append(f"{s_type} is {state}{unit_str}")
                    area_summaries.append(f"in {format_area_with_preposition(cleaned_area)}, {', '.join(reading_texts[:-1])} and {reading_texts[-1]}")
            
            summary_text = "; ".join(area_summaries)
            if summary_text:
                summary_text = summary_text[0].upper() + summary_text[1:] + "."
                
            widget = {
                'type': 'home_assistant',
                'data': {
                    'summary': summary_text,
                    'action': 'get_state',
                    'domain': 'sensor',
                    'devices': results
                }
            }
            return summary_text, [widget]

        # Single sensor matched
        score, st, fname, eid, s_type = selected_candidates[0]
        current_state = st.get('state', 'unknown')
        attrs = st.get('attributes', {})
        unit = attrs.get('unit_of_measurement', '') or ''
        
        cleaned_area = fname
        for suffix in [" Temperature", " temperature", " Temp", " temp", " Humidity", " humidity", " Presence", " presence", " Motion", " motion", " Occupancy", " occupancy", " Sensor", " sensor"]:
            cleaned_area = cleaned_area.replace(suffix, "")
            
        results = [{
            'entity_id': eid,
            'name': fname,
            'requested_action': 'get_state',
            'success': True,
            'code': 200,
            'state_current': current_state,
            'attributes': attrs,
            'state_before': current_state
        }]
        
        unit_str = "" if current_state.lower() in ("unavailable", "unknown") else (unit or ("°C" if s_type == "temperature" else "%" if s_type == "humidity" else ""))
        
        if current_state.lower() in ("unavailable", "unknown"):
            if s_type == 'temperature':
                summary_text = f"The temperature sensor in {format_area_with_preposition(cleaned_area)} is {current_state.lower()}."
            elif s_type == 'humidity':
                summary_text = f"The humidity sensor in {format_area_with_preposition(cleaned_area)} is {current_state.lower()}."
            elif s_type == 'presence':
                summary_text = f"The presence sensor in {format_area_with_preposition(cleaned_area)} is {current_state.lower()}."
        else:
            if s_type == 'temperature':
                summary_text = f"The temperature in {format_area_with_preposition(cleaned_area)} is {current_state}{unit_str}."
            elif s_type == 'humidity':
                summary_text = f"The humidity in {format_area_with_preposition(cleaned_area)} is {current_state}{unit_str}."
            elif s_type == 'presence':
                prep = "at" if "door" in cleaned_area.lower() or "veranda" in cleaned_area.lower() else "in"
                has_someone = any(kw in ql for kw in ["someone", "somebody", "person", "anyone", "anybody"])
                if current_state == 'on':
                    if has_someone:
                        summary_text = f"Yes, someone is {prep} {format_area_with_preposition(cleaned_area)}."
                    else:
                        summary_text = f"Yes, motion is detected {prep} {format_area_with_preposition(cleaned_area)}."
                else:
                    if has_someone:
                        summary_text = f"No, there is no one {prep} {format_area_with_preposition(cleaned_area)}."
                    else:
                        summary_text = f"No, there is no motion detected {prep} {format_area_with_preposition(cleaned_area)}."
                    
        widget = {
            'type': 'home_assistant',
            'data': {
                'summary': summary_text,
                'action': 'get_state',
                'domain': eid.split('.')[0],
                'devices': results
            }
        }
        return summary_text, [widget]

    color_words_all = ["warm white","cool white","magenta","yellow","purple","orange","white","green","blue","pink","cyan","red"]

    def detect_colors(text: str):
        found = []
        for cw in color_words_all:
            if cw in text:
                found.append(cw)
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
            prior_states = []
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
                    # Capture prior attributes to enable restore
                    try:
                        prior_attrs = next((s.get('attributes',{}) for s in states if s.get('entity_id')==eid), {})
                    except Exception:
                        prior_attrs = {}
                    prior_states.append({
                        'entity_id': eid,
                        'state': state_val,
                        'brightness': prior_attrs.get('brightness'),
                        'color_name': prior_attrs.get('color_name'),
                        'rgb_color': prior_attrs.get('rgb_color'),
                        'color_temp': prior_attrs.get('color_temp')
                    })
                    assigned_color = None
                    if domain == 'light' and c['action'] == 'turn_on':
                        if c['brightness'] is not None:
                            svc_data['brightness_pct'] = c['brightness']
                        if color_cycle:
                            assigned_color = color_cycle[color_idx]; color_idx += 1
                            svc_data['color_name'] = assigned_color
                        elif c['color']:
                            assigned_color = c['color']; svc_data['color_name'] = assigned_color
                        # Preserve brightness if not explicitly requested by including previous brightness
                        if 'brightness_pct' not in svc_data and prior_attrs.get('brightness') is not None:
                            try:
                                svc_data['brightness'] = int(prior_attrs.get('brightness'))
                            except Exception:
                                pass
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
                        svc = type('obj', (), {'status_code': 0})()
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
            
            widget = {
                'type': 'home_assistant',
                'data': {
                    'summary': summary_text,
                    'action': 'multi',
                    'domain': domain,
                    'devices': results,
                    'applied': { 'restore_in_seconds': 0 }
                }
            }
            return summary_text, [widget]

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
        return "I couldn't find a matching device.", []

    if action == 'get_state':
        results = []
        for eid, fname, state_val in matched_entities:
            full_state = next((s for s in states if s.get('entity_id') == eid), {})
            current_state = full_state.get('state', 'unknown')
            attrs = full_state.get('attributes', {})
            
            # Use current_state for widget consistency
            results.append({
                'entity_id': eid,
                'name': fname,
                'requested_action': 'get_state',
                'success': True,
                'code': 200,
                'state_current': current_state,
                'attributes': attrs,
                # Explicitly populate state_before so frontend logic (if using it) sees current state
                'state_before': current_state
            })
            
        summary_text = format_ha_summary(action, domain, results)
        
        widget = {
            'type': 'home_assistant',
            'data': {
                'summary': summary_text,
                'action': action,
                'domain': domain,
                'devices': results
            }
        }
        return summary_text, [widget]

    ordered_colors = detect_colors(ql)
    color_name = ordered_colors[0] if ordered_colors else None
    brightness_pct = detect_brightness(ql)

    if (color_name or (brightness_pct is not None)) and not action:
        action = 'turn_on'
    if not action:
        return "Need to know if you want them on or off.", []

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
        
        # Capture prior attributes before action for restore
        try:
            prior_attrs = next((s.get('attributes',{}) for s in states if s.get('entity_id')==eid), {})
        except Exception:
            prior_attrs = {}
        # Preserve brightness when turning on with color but no brightness provided
        if domain == 'light' and action == 'turn_on' and 'color_name' in svc_data and 'brightness_pct' not in svc_data:
            if prior_attrs.get('brightness') is not None:
                try:
                    svc_data['brightness'] = int(prior_attrs.get('brightness'))
                except Exception:
                    pass
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
    
    summary_text = format_ha_summary(action, domain, results)
    
    widget = {
        'type': 'home_assistant',
        'data': {
            'summary': summary_text,
            'action': action,
            'domain': domain,
            'devices': results,
            'applied': {
                'color_name': color_name,
                'brightness_pct': brightness_pct,
                'colors': ordered_colors if len(ordered_colors) > 1 else None,
                'restore_in_seconds': 0
            }
        }
    }
    return summary_text, [widget]
