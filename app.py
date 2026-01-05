from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

# Airtable configuration
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', 'appXXXXXXXXXXXXXX')  # Set in Railway
AIRTABLE_TABLE_NAME = 'Projects'

AIRTABLE_URL = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}'

def get_headers():
    return {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }

@app.route('/')
def health():
    return jsonify({'status': 'ok', 'service': 'dot-remote-api'})

@app.route('/clients', methods=['GET'])
def get_clients():
    """
    Returns unique list of clients from Projects table.
    Only includes clients with active projects (In Progress or On Hold).
    """
    try:
        # Fetch all records, filter to active statuses
        params = {
            'filterByFormula': "OR({Status}='In Progress', {Status}='On Hold')",
            'fields[]': ['Client']
        }
        
        response = requests.get(AIRTABLE_URL, headers=get_headers(), params=params)
        response.raise_for_status()
        data = response.json()
        
        # Extract unique clients
        clients_set = set()
        for record in data.get('records', []):
            client = record.get('fields', {}).get('Client', '')
            if client:
                clients_set.add(client)
        
        # Sort and format
        clients = sorted(list(clients_set))
        
        # Create code from client name (first 3 letters of first word, uppercase)
        result = []
        for client in clients:
            # Generate a simple code - first 3 chars of first word
            code = client.split()[0][:3].upper() if client else ''
            result.append({
                'code': code,
                'name': client
            })
        
        return jsonify(result)
    
    except requests.exceptions.RequestException as e:
        print(f"Airtable API error: {e}")
        return jsonify({'error': 'Failed to fetch clients'}), 500

@app.route('/jobs', methods=['GET'])
def get_jobs():
    """
    Returns jobs for a specific client.
    Query param: client (the client name or partial match)
    Only includes active projects (In Progress or On Hold).
    """
    client_query = request.args.get('client', '')
    
    if not client_query:
        return jsonify({'error': 'Client parameter required'}), 400
    
    try:
        # Filter by client (using FIND for partial match) and active status
        filter_formula = f"AND(FIND('{client_query}', {{Client}}), OR({{Status}}='In Progress', {{Status}}='On Hold'))"
        
        params = {
            'filterByFormula': filter_formula,
            'fields[]': ['Job Number', 'Project Name', 'Client', 'Status', 'Stage'],
            'sort[0][field]': 'Job Number',
            'sort[0][direction]': 'asc'
        }
        
        response = requests.get(AIRTABLE_URL, headers=get_headers(), params=params)
        response.raise_for_status()
        data = response.json()
        
        # Format jobs
        jobs = []
        for record in data.get('records', []):
            fields = record.get('fields', {})
            job_number = fields.get('Job Number', '')
            project_name = fields.get('Project Name', '')
            
            if job_number:
                jobs.append({
                    'id': job_number,
                    'name': f"{job_number} - {project_name}" if project_name else job_number,
                    'status': fields.get('Status', ''),
                    'stage': fields.get('Stage', ''),
                    'recordId': record.get('id', '')
                })
        
        return jsonify(jobs)
    
    except requests.exceptions.RequestException as e:
        print(f"Airtable API error: {e}")
        return jsonify({'error': 'Failed to fetch jobs'}), 500

@app.route('/job/<job_number>', methods=['GET'])
def get_job(job_number):
    """
    Returns details for a specific job by job number.
    """
    try:
        filter_formula = f"{{Job Number}}='{job_number}'"
        
        params = {
            'filterByFormula': filter_formula,
            'maxRecords': 1
        }
        
        response = requests.get(AIRTABLE_URL, headers=get_headers(), params=params)
        response.raise_for_status()
        data = response.json()
        
        records = data.get('records', [])
        if not records:
            return jsonify({'error': 'Job not found'}), 404
        
        record = records[0]
        fields = record.get('fields', {})
        
        return jsonify({
            'recordId': record.get('id'),
            'jobNumber': fields.get('Job Number'),
            'projectName': fields.get('Project Name'),
            'client': fields.get('Client'),
            'status': fields.get('Status'),
            'stage': fields.get('Stage'),
            'description': fields.get('Description'),
            'updateSummary': fields.get('Update Summary'),
            'projectOwner': fields.get('Project Owner')
        })
    
    except requests.exceptions.RequestException as e:
        print(f"Airtable API error: {e}")
        return jsonify({'error': 'Failed to fetch job'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
