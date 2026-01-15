"""
Ask Dot - The Brain
Handles Claude conversations, memory, tools, and response parsing.
Single source of truth for Dot's personality and capabilities.
"""

import requests
import os
import json
import time
from datetime import datetime

# ===== CONFIGURATION =====
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', 'app8CI7NAZqhQ4G1Y')

AIRTABLE_HEADERS = {
    'Authorization': f'Bearer {AIRTABLE_API_KEY}',
    'Content-Type': 'application/json'
}

def get_airtable_url(table):
    return f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table}'


# ===== CONVERSATION MEMORY =====
conversations = {}
SESSION_TIMEOUT = 30 * 60  # 30 minutes

def get_conversation(session_id):
    """Get or create conversation history for a session"""
    now = time.time()
    
    # Clean up old sessions
    expired = [sid for sid, data in conversations.items() if now - data['last_active'] > SESSION_TIMEOUT]
    for sid in expired:
        del conversations[sid]
    
    if session_id not in conversations:
        conversations[session_id] = {
            'messages': [],
            'last_active': now
        }
    else:
        conversations[session_id]['last_active'] = now
    
    return conversations[session_id]

def add_to_conversation(session_id, role, content):
    """Add a message to conversation history"""
    conv = get_conversation(session_id)
    conv['messages'].append({'role': role, 'content': content})
    
    # Keep only last 10 exchanges (20 messages)
    if len(conv['messages']) > 20:
        conv['messages'] = conv['messages'][-20:]

def clear_conversation(session_id):
    """Clear conversation history for a session"""
    if session_id in conversations:
        del conversations[session_id]
    return True


# ===== TOOLS FOR DOT =====

def tool_search_people(client_code=None, search_term=None):
    """Search People table"""
    try:
        url = get_airtable_url('People')
        
        filters = ["{Active} = TRUE()"]
        if client_code:
            filters.append(f"{{Client Link}} = '{client_code}'")
        
        params = {
            'filterByFormula': f"AND({', '.join(filters)})" if len(filters) > 1 else filters[0]
        }
        
        all_people = []
        offset = None
        
        while True:
            if offset:
                params['offset'] = offset
            
            response = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
            
            for record in data.get('records', []):
                fields = record.get('fields', {})
                name = fields.get('Name', fields.get('Full name', ''))
                if not name:
                    continue
                
                if search_term:
                    searchable = f"{name} {fields.get('Email Address', '')}".lower()
                    if search_term.lower() not in searchable:
                        continue
                
                all_people.append({
                    'name': name,
                    'email': fields.get('Email Address', ''),
                    'phone': fields.get('Phone Number', ''),
                    'clientCode': fields.get('Client Link', '')
                })
            
            offset = data.get('offset')
            if not offset:
                break
        
        return {'count': len(all_people), 'people': all_people}
    
    except Exception as e:
        return {'error': str(e)}


def tool_get_client_detail(client_code):
    """Get detailed client info"""
    try:
        url = get_airtable_url('Clients')
        params = {
            'filterByFormula': f"{{Client code}} = '{client_code}'",
            'maxRecords': 1
        }
        response = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        if not records:
            return {'error': f'Client {client_code} not found'}
        
        fields = records[0].get('fields', {})
        
        def parse_currency(val):
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, str):
                return int(val.replace('$', '').replace(',', '') or 0)
            return 0
        
        rollover = fields.get('Rollover Credit', 0)
        if isinstance(rollover, list):
            rollover = rollover[0] if rollover else 0
        rollover = parse_currency(rollover)
        
        return {
            'code': client_code,
            'name': fields.get('Clients', ''),
            'yearEnd': fields.get('Year end', ''),
            'currentQuarter': fields.get('Current Quarter', ''),
            'monthlyCommitted': parse_currency(fields.get('Monthly Committed', 0)),
            'quarterlyCommitted': parse_currency(fields.get('Quarterly Committed', 0)),
            'thisMonth': parse_currency(fields.get('This month', 0)),
            'thisQuarter': parse_currency(fields.get('This Quarter', 0)),
            'rolloverCredit': rollover,
            'nextJobNumber': fields.get('Next Job #', '')
        }
    
    except Exception as e:
        return {'error': str(e)}


def tool_get_spend_summary(client_code, period='this_month'):
    """Get spend summary for a client"""
    try:
        clients_url = get_airtable_url('Clients')
        clients_response = requests.get(clients_url, headers=AIRTABLE_HEADERS)
        clients_response.raise_for_status()
        
        client_info = None
        for record in clients_response.json().get('records', []):
            fields = record.get('fields', {})
            if fields.get('Client code', '') == client_code:
                def parse_currency(val):
                    if isinstance(val, (int, float)):
                        return float(val)
                    if isinstance(val, str):
                        return float(val.replace('$', '').replace(',', '') or 0)
                    if isinstance(val, list):
                        return float(val[0]) if val else 0
                    return 0
                
                monthly = parse_currency(fields.get('Monthly Committed', 0))
                rollover = parse_currency(fields.get('Rollover Credit', 0))
                rollover_use = fields.get('Rollover use', '')
                
                client_info = {
                    'name': fields.get('Clients', ''),
                    'code': client_code,
                    'monthlyBudget': monthly,
                    'quarterlyBudget': monthly * 3,
                    'currentQuarter': fields.get('Current Quarter', ''),
                    'rollover': rollover,
                    'rolloverUse': rollover_use,
                    'JAN-MAR': parse_currency(fields.get('JAN-MAR', 0)),
                    'APR-JUN': parse_currency(fields.get('APR-JUN', 0)),
                    'JUL-SEP': parse_currency(fields.get('JUL-SEP', 0)),
                    'OCT-DEC': parse_currency(fields.get('OCT-DEC', 0)),
                    'thisMonth': parse_currency(fields.get('This month', 0)),
                }
                break
        
        if not client_info:
            return {'error': f'Client {client_code} not found'}
        
        now = datetime.now()
        current_month_num = now.month
        
        calendar_quarters = {
            1: 'JAN-MAR', 2: 'JAN-MAR', 3: 'JAN-MAR',
            4: 'APR-JUN', 5: 'APR-JUN', 6: 'APR-JUN',
            7: 'JUL-SEP', 8: 'JUL-SEP', 9: 'JUL-SEP',
            10: 'OCT-DEC', 11: 'OCT-DEC', 12: 'OCT-DEC'
        }
        current_cal_quarter = calendar_quarters[current_month_num]
        
        prev_quarters = {
            'JAN-MAR': 'OCT-DEC',
            'APR-JUN': 'JAN-MAR',
            'JUL-SEP': 'APR-JUN',
            'OCT-DEC': 'JUL-SEP'
        }
        last_cal_quarter = prev_quarters[current_cal_quarter]
        
        if period == 'this_quarter':
            quarter_key = current_cal_quarter
            period_label = client_info['currentQuarter']
        elif period == 'last_quarter':
            quarter_key = last_cal_quarter
            current_q_num = int(client_info['currentQuarter'].replace('Q', '') or 1)
            last_q_num = current_q_num - 1 if current_q_num > 1 else 4
            period_label = f'Q{last_q_num}'
        elif period in ['JAN-MAR', 'APR-JUN', 'JUL-SEP', 'OCT-DEC']:
            quarter_key = period
            period_label = period
        elif period == 'this_month':
            return {
                'client': client_info['name'],
                'clientCode': client_code,
                'period': now.strftime('%B'),
                'budget': client_info['monthlyBudget'],
                'spent': client_info['thisMonth'],
                'remaining': client_info['monthlyBudget'] - client_info['thisMonth'],
                'percentUsed': round((client_info['thisMonth'] / client_info['monthlyBudget'] * 100) if client_info['monthlyBudget'] > 0 else 0)
            }
        else:
            quarter_key = current_cal_quarter
            period_label = client_info['currentQuarter']
        
        spent = client_info.get(quarter_key, 0)
        budget = client_info['quarterlyBudget']
        
        if client_info['rolloverUse'] == quarter_key and client_info['rollover'] > 0:
            budget += client_info['rollover']
        
        return {
            'client': client_info['name'],
            'clientCode': client_code,
            'period': period_label,
            'budget': budget,
            'spent': spent,
            'remaining': budget - spent,
            'percentUsed': round((spent / budget * 100) if budget > 0 else 0),
            'rolloverApplied': client_info['rolloverUse'] == quarter_key and client_info['rollover'] > 0,
            'rolloverAmount': client_info['rollover'] if client_info['rolloverUse'] == quarter_key else 0
        }
    
    except Exception as e:
        return {'error': str(e)}


def tool_reserve_job_number(client_code):
    """Reserve the next job number for a client"""
    try:
        url = get_airtable_url('Clients')
        params = {
            'filterByFormula': f"{{Client code}} = '{client_code}'",
            'maxRecords': 1
        }
        response = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        if not records:
            return {'error': f'Client {client_code} not found'}
        
        record = records[0]
        record_id = record.get('id')
        fields = record.get('fields', {})
        client_name = fields.get('Clients', client_code)
        
        next_num_str = fields.get('Next Job #', '')
        if not next_num_str:
            return {'error': f'No job number sequence configured for {client_code}'}
        
        try:
            next_num = int(next_num_str)
        except ValueError:
            return {'error': f'Invalid job number format: {next_num_str}'}
        
        reserved_job_number = f"{client_code} {next_num:03d}"
        new_next_num = f"{next_num + 1:03d}"
        
        update_response = requests.patch(
            f"{url}/{record_id}",
            headers=AIRTABLE_HEADERS,
            json={'fields': {'Next Job #': new_next_num}}
        )
        update_response.raise_for_status()
        
        return {
            'success': True,
            'clientCode': client_code,
            'clientName': client_name,
            'reservedJobNumber': reserved_job_number,
            'nextJobNumber': new_next_num
        }
    
    except Exception as e:
        return {'error': str(e)}


# Tool definitions for Claude
CLAUDE_TOOLS = [
    {
        "name": "search_people",
        "description": "Search for contacts/people in the database. Use this when asked about client contacts, email addresses, phone numbers, or how many people work at a client.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_code": {
                    "type": "string",
                    "description": "Filter by client code (e.g., 'SKY', 'TOW', 'ONE'). Optional."
                },
                "search_term": {
                    "type": "string",
                    "description": "Search for a specific person by name or email. Optional."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_client_detail",
        "description": "Get detailed information about a client including their budget, quarter, commercial setup, and next job number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_code": {
                    "type": "string",
                    "description": "The client code (e.g., 'SKY', 'TOW', 'ONE')"
                }
            },
            "required": ["client_code"]
        }
    },
    {
        "name": "get_spend_summary",
        "description": "Get spend/budget summary for a client. Use this when asked about how much has been spent, budget remaining, or financial tracking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_code": {
                    "type": "string",
                    "description": "The client code (e.g., 'SKY', 'TOW', 'ONE')"
                },
                "period": {
                    "type": "string",
                    "description": "Time period: 'this_month', 'this_quarter', or 'last_quarter'"
                }
            },
            "required": ["client_code"]
        }
    },
    {
        "name": "reserve_job_number",
        "description": "Reserve and lock in the next job number for a client. This WRITES to the database - only use when the user confirms they want to reserve a number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_code": {
                    "type": "string",
                    "description": "The client code (e.g., 'SKY', 'TOW', 'ONE')"
                }
            },
            "required": ["client_code"]
        }
    }
]


def execute_tool(tool_name, tool_input):
    """Execute a tool and return results"""
    if tool_name == "search_people":
        return tool_search_people(
            client_code=tool_input.get('client_code'),
            search_term=tool_input.get('search_term')
        )
    elif tool_name == "get_client_detail":
        return tool_get_client_detail(tool_input.get('client_code'))
    elif tool_name == "get_spend_summary":
        return tool_get_spend_summary(
            client_code=tool_input.get('client_code'),
            period=tool_input.get('period', 'this_month')
        )
    elif tool_name == "reserve_job_number":
        return tool_reserve_job_number(tool_input.get('client_code'))
    else:
        return {'error': f'Unknown tool: {tool_name}'}


# ===== DOT'S PERSONALITY (System Prompt) =====

def get_system_prompt(client_list):
    """Generate the system prompt for Dot"""
    return f"""You're Dot, the admin bot for Hunch creative agency. You're warm, helpful, occasionally cheeky - a friendly colleague who happens to be a robot with perfect memory.

WHAT YOU KNOW ABOUT:

Jobs/Projects - The frontend has all active jobs preloaded. Each job has:
- Job number (e.g., "SKY 017"), project name, description
- Status: Incoming, In Progress, On Hold, Completed
- Stage: Clarify, Simplify, Craft, Refine, Deliver
- Update due date, live date, last updated
- Whether it's currently "with client" (waiting on them)
- Project owner, Teams channel link

Clients - {client_list}
- "One NZ" has three divisions: ONE (Marketing), ONB (Business), ONS (Simplification). For One NZ people queries, search all three.
- "Sky" = Sky TV, "Tower" = Tower Insurance, "Fisher" = Fisher Funds

People - Contact details for client contacts (names, emails, phone numbers)

Budgets - Each client has a monthly committed spend. You can check:
- How much spent this month/quarter
- How much remaining
- Rollover credits from previous quarters
Talk about "this quarter", "last quarter", "next quarter" - not Q1/Q2/Q3/Q4.

YOUR TOOLS:
- search_people: Find contacts, emails, phone numbers
- get_client_detail: Client setup, budget info, next job number
- get_spend_summary: How much spent/remaining (use period: "this_month", "this_quarter", "last_quarter")
- reserve_job_number: Lock in a job number (CONFIRM WITH USER FIRST - this writes to the database)

For job queries, don't use tools - just return a filter and the frontend will display them.

RESPOND WITH ONLY JSON (no other text):
{{
  "message": "Your natural response - be yourself, be warm, be helpful",
  "jobs": {{
    "show": true,
    "client": "SKY or null",
    "status": "In Progress | On Hold | Incoming | Completed | null",
    "dateRange": "today | tomorrow | week | null",
    "withClient": true | false | null,
    "search": ["search", "terms"] or null
  }} or null,
  "nextPrompt": "Short followup question or null"
}}

CRITICAL: Your entire response must be valid JSON. Do not include any text before or after the JSON object. Do not wrap it in markdown code blocks.

GUIDELINES:
- Only include "jobs" if they're asking about jobs/projects/work
- If you need to clarify, just ask naturally in "message"
- If something needs a human (strategy, creative decisions, opinions), say so warmly - "That's one for the humans!" or "Better to ask the team directly"
- For spend/budget questions, use the tools and include the answer in your message
- Be conversational. Be helpful. Be Dot.

EXAMPLES OF GOOD RESPONSES:
- {{"message": "Sky's looking healthy this month - $6.2K spent, $3.8K still to play with.", "jobs": null, "nextPrompt": null}}
- {{"message": "Here's what's due this week:", "jobs": {{"show": true, "dateRange": "week"}}, "nextPrompt": "Want me to filter by client?"}}
- {{"message": "Which client are you thinking?", "jobs": null, "nextPrompt": null}}

Don't be robotic. Don't explain what you're doing. Just help."""


# ===== JSON PARSING =====

def parse_response(assistant_message):
    """
    Parse Claude's response to extract JSON.
    Handles various formats: pure JSON, code blocks, text + JSON mix.
    """
    if not assistant_message:
        return None
    
    clean = assistant_message.strip()
    
    # Try 1: Direct JSON parse (ideal case)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    
    # Try 2: Extract from ```json ... ``` blocks
    if '```json' in clean:
        try:
            start = clean.find('```json') + 7
            end = clean.find('```', start)
            if end > start:
                json_str = clean[start:end].strip()
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Try 3: Extract from plain ``` ... ``` blocks
    if '```' in clean:
        try:
            parts = clean.split('```')
            for part in parts:
                part = part.strip()
                if part.startswith('{') and part.endswith('}'):
                    return json.loads(part)
        except json.JSONDecodeError:
            pass
    
    # Try 4: Find JSON object anywhere in the text
    try:
        # Find the first { and last }
        json_start = clean.find('{')
        json_end = clean.rfind('}')
        if json_start != -1 and json_end > json_start:
            json_str = clean[json_start:json_end + 1]
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # All parsing failed
    return None


# ===== MAIN PROCESS FUNCTION =====

def process_question(question, clients, session_id='default'):
    """
    Process a question through Claude and return parsed response.
    This is the main entry point for Ask Dot.
    """
    if not question:
        return {'error': 'No question provided'}
    
    if not ANTHROPIC_API_KEY:
        return {'error': 'Anthropic API not configured'}
    
    try:
        # Get conversation history
        conv = get_conversation(session_id)
        history = conv['messages']
        
        # Build client list for prompt
        client_list = ', '.join([f"{c['code']} ({c['name']})" for c in clients])
        system_prompt = get_system_prompt(client_list)
        
        # Build messages
        messages = []
        for msg in history[-10:]:
            messages.append(msg)
        messages.append({'role': 'user', 'content': question})
        
        # Call Claude
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 1000,
                'system': system_prompt,
                'messages': messages,
                'tools': CLAUDE_TOOLS
            }
        )
        
        response.raise_for_status()
        result = response.json()
        
        stop_reason = result.get('stop_reason')
        content_blocks = result.get('content', [])
        
        # Handle tool use
        if stop_reason == 'tool_use':
            tool_results = []
            
            for block in content_blocks:
                if block.get('type') == 'tool_use':
                    tool_name = block.get('name')
                    tool_input = block.get('input', {})
                    tool_id = block.get('id')
                    
                    print(f"Executing tool: {tool_name} with input: {tool_input}")
                    tool_result = execute_tool(tool_name, tool_input)
                    print(f"Tool result: {tool_result}")
                    
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': json.dumps(tool_result)
                    })
            
            messages.append({'role': 'assistant', 'content': content_blocks})
            messages.append({'role': 'user', 'content': tool_results})
            
            # Second Claude call with tool results
            response2 = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json'
                },
                json={
                    'model': 'claude-sonnet-4-20250514',
                    'max_tokens': 1000,
                    'system': system_prompt,
                    'messages': messages
                }
            )
            
            response2.raise_for_status()
            result = response2.json()
            content_blocks = result.get('content', [])
        
        # Extract text response
        assistant_message = ''
        for block in content_blocks:
            if block.get('type') == 'text':
                assistant_message = block.get('text', '')
                break
        
        # Parse JSON response
        parsed = parse_response(assistant_message)
        
        if parsed:
            # Update conversation memory
            add_to_conversation(session_id, 'user', question)
            add_to_conversation(session_id, 'assistant', parsed.get('message', '')[:100])
            return {'parsed': parsed}
        else:
            # Parsing failed - return raw message as fallback
            print(f'JSON parse failed. Raw: {assistant_message}')
            add_to_conversation(session_id, 'user', question)
            add_to_conversation(session_id, 'assistant', assistant_message[:100])
            return {'parsed': {'message': assistant_message, 'jobs': None, 'nextPrompt': None}}
    
    except Exception as e:
        print(f'Error in process_question: {e}')
        return {'error': str(e)}
