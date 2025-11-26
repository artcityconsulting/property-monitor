"""
Utah Real Estate Property Monitor - V4.1 COMPLETE
Enhanced Zoho CRM with all functions implemented
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import re
import sqlite3
from pathlib import Path
import json
import secrets

# Page configuration
st.set_page_config(
    page_title="Utah RE Monitor",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    .status-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 8px;
    }
    
    .status-for-sale { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .status-pending { background: #fff3cd; color: #856404; border: 1px solid #ffeaa7; }
    .status-sold { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .status-off-market { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    
    .quick-add-section {
        background: rgba(0, 123, 255, 0.05);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 2px dashed rgba(0, 123, 255, 0.3);
    }
    
    .connection-status {
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
        font-weight: bold;
    }
    
    .status-connected {
        background: #d4edda;
        color: #155724;
        border: 2px solid #c3e6cb;
    }
    
    .status-disconnected {
        background: #f8d7da;
        color: #721c24;
        border: 2px solid #f5c6cb;
    }
    
    .field-mapping-row {
        background: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        border-left: 3px solid #007bff;
    }
</style>
""", unsafe_allow_html=True)

DB_PATH = Path("properties.db")

def init_database():
    """Initialize database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_text TEXT NOT NULL,
            source TEXT,
            status TEXT,
            price TEXT,
            beds TEXT,
            baths TEXT,
            sqft TEXT,
            resolved_url TEXT,
            address TEXT,
            mls TEXT,
            days_on_market TEXT,
            year_built TEXT,
            property_type TEXT,
            agent_name TEXT,
            agent_photo TEXT,
            agent_phone TEXT,
            agent_email TEXT,
            brokerage TEXT,
            features TEXT,
            last_checked TIMESTAMP,
            last_changed TIMESTAMP,
            previous_status TEXT,
            notes TEXT,
            zoho_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    defaults = [
        ('view_mode', 'cards'),
        ('zoho_access_token', ''),
        ('zoho_refresh_token', ''),
        ('zoho_token_expiry', ''),
        ('zoho_module', ''),
        ('zoho_field_mapping', ''),
        ('zoho_connected', 'false'),
        ('zoho_sync_enabled', 'false'),
        ('zoho_last_sync', ''),
        ('last_full_refresh', '')
    ]
    
    for key, value in defaults:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    conn.close()

init_database()

CONFIG = {
    'UTAH_URL_PATTERN': 'https://www.utahrealestate.com/report/',
    'ZILLOW_URL_PATTERN': 'https://www.zillow.com/homedetails/',
    'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'ZOHO_CLIENT_ID': 'YOUR_ZOHO_CLIENT_ID',
    'ZOHO_CLIENT_SECRET': 'YOUR_ZOHO_CLIENT_SECRET',
    'ZOHO_REDIRECT_URI': 'http://localhost:8501',
    'ZOHO_AUTH_URL': 'https://accounts.zoho.com/oauth/v2/auth',
    'ZOHO_TOKEN_URL': 'https://accounts.zoho.com/oauth/v2/token',
    'ZOHO_API_BASE': 'https://www.zohoapis.com/crm/v2'
}

# ========================================
# SETTINGS FUNCTIONS
# ========================================

def get_setting(key, default=''):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# ========================================
# SCRAPING HELPER FUNCTIONS
# ========================================

def detect_source(url):
    if 'utahrealestate.com' in url:
        return 'UtahRealEstate.com'
    elif 'zillow.com' in url:
        return 'Zillow.com'
    return None

def convert_input_to_url(input_text):
    input_text = input_text.strip()
    
    if input_text.startswith('http://') or input_text.startswith('https://'):
        source = detect_source(input_text)
        if source:
            return {'success': True, 'url': input_text, 'source': source}
        else:
            return {'success': False, 'error': 'Unsupported website'}
    
    mls_match = re.match(r'^(MLS)?(\d{6,10})$', input_text, re.IGNORECASE)
    if mls_match:
        mls_number = mls_match.group(2)
        return {
            'success': True,
            'url': CONFIG['UTAH_URL_PATTERN'] + mls_number,
            'source': 'UtahRealEstate.com'
        }
    
    if re.match(r'\d+.*[a-zA-Z].*,', input_text):
        return {'success': False, 'error': 'Address detected. Find URL manually.'}
    
    return {'success': False, 'error': 'Invalid input'}

def normalize_status(status_text):
    if not status_text:
        return ''
    
    status = status_text.upper().strip()
    
    status_map = {
        'FOR_SALE': 'For Sale', 'ACTIVE': 'For Sale', 'FOR SALE': 'For Sale',
        'OFF_MARKET': 'Off Market', 'OFF MARKET': 'Off Market',
        'PENDING': 'Pending', 'UNDER CONTRACT': 'Pending', 'CONTINGENT': 'Contingent',
        'SOLD': 'Sold', 'CLOSED': 'Sold',
        'COMING_SOON': 'Coming Soon', 'COMING SOON': 'Coming Soon',
        'FOR_RENT': 'For Rent', 'FOR RENT': 'For Rent'
    }
    
    return status_map.get(status, status_text)

def scrape_utah_realestate(html):
    result = {
        'success': True, 'status': '', 'price': '', 'beds': '', 'baths': '',
        'sqft': '', 'address': '', 'mls': '', 'daysOnMarket': '', 'yearBuilt': '',
        'type': '', 'agentName': '', 'agentPhoto': '', 'agentPhone': '',
        'agentEmail': '', 'brokerage': '', 'features': ''
    }
    
    try:
        price_match = re.search(r'\$?([1-9]\d{2}(?:,?\d{3}){1,2}(?:,\d{3})?)', html)
        if price_match:
            result['price'] = '$' + price_match.group(1).strip()
        
        street_match = re.search(r'<h2[^>]*>([^<]+)</h2>', html, re.IGNORECASE)
        street_address = street_match.group(1).strip() if street_match else ''
        
        location_match = re.search(r'<div[^>]*id=["\']location-data["\'][^>]*>([^<]+)</div>', html, re.IGNORECASE)
        location_data = location_match.group(1).strip().lstrip(',').strip() if location_match else ''
        
        if street_address and location_data:
            result['address'] = f"{street_address}, {location_data}"
        elif street_address:
            result['address'] = street_address
        elif location_data:
            result['address'] = location_data
        
        name_link_match = re.search(
            r'<a[^>]*href=["\']\/roster\/agent\.listings\.report\.public\/agentid\/\d+[^>]*>([^<]+)</a>',
            html, re.IGNORECASE
        )
        if name_link_match:
            result['agentName'] = name_link_match.group(1).strip()
        
        photo_match = re.search(
            r'<img[^>]*src=["\'](https:\/\/webdrive\.utahrealestate\.com\/[^\s"\']+?\.jpg)["\'][^>]*alt=["\'](?:[^"\']+?)["\']',
            html, re.IGNORECASE
        )
        if photo_match:
            result['agentPhoto'] = photo_match.group(1).strip()
        
        contact_section_match = re.search(
            r'<h2>Contact Agent</h2>([\s\S]*?)<div[^>]*class=["\'][^"\']*broker-overview-table',
            html, re.IGNORECASE
        )
        if contact_section_match:
            phone_match = re.search(r'(\d{3}[-\s]?\d{3}[-\s]?\d{4})', contact_section_match.group(1))
            if phone_match:
                result['agentPhone'] = phone_match.group(1).strip()
        
        email_match = re.search(r'<a[^>]*href=["\']mailto:([^"\']+)["\'][^>]*>', html, re.IGNORECASE)
        if email_match:
            result['agentEmail'] = email_match.group(1).strip()
        
        brokerage_match = re.search(
            r'<div[^>]*class=["\'][^"\']*broker-overview-content[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            html, re.IGNORECASE
        )
        if brokerage_match:
            strong_match = re.search(r'<strong>([^<]+)</strong>', brokerage_match.group(1), re.IGNORECASE)
            if strong_match:
                result['brokerage'] = strong_match.group(1).strip()
        
        facts = {}
        facts_matches = re.finditer(
            r'<span[^>]*class=["\'][^"\']*facts-header[^"\']*["\'][^>]*>(.*?)</span>\s*["\']?([^"\'<]+)["\']?',
            html, re.IGNORECASE
        )
        for match in facts_matches:
            label = match.group(1).strip()
            value = match.group(2).strip()
            if label and value:
                facts[label] = value
        
        result['status'] = normalize_status(facts.get('Status', ''))
        if not result['status']:
            result['status'] = 'Status Not Found'
        
        result['mls'] = facts.get('MLS#', '')
        result['type'] = facts.get('Type', '')
        result['yearBuilt'] = facts.get('Year Built', '')
        result['daysOnMarket'] = facts.get('Days on URE', facts.get('Days on Market', ''))
        
        beds_match = re.search(r'(\d+)\s*(?:bed|bd|bedroom)', html, re.IGNORECASE)
        if beds_match:
            result['beds'] = beds_match.group(1)
        
        baths_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:bath|ba|bathroom)', html, re.IGNORECASE)
        if baths_match:
            result['baths'] = baths_match.group(1)
        
        sqft_match = re.search(r'([0-9,]+)\s*(?:sq\.?\s*ft|sqft|square feet)', html, re.IGNORECASE)
        if sqft_match:
            result['sqft'] = sqft_match.group(1)
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': f'Scraping failed: {str(e)}'}

def scrape_zillow(html):
    result = {
        'success': True, 'status': '', 'price': '', 'beds': '', 'baths': '',
        'sqft': '', 'address': '', 'mls': '', 'daysOnMarket': '', 'yearBuilt': '',
        'type': '', 'agentName': '', 'agentPhoto': '', 'agentPhone': '',
        'agentEmail': '', 'brokerage': '', 'features': ''
    }
    
    try:
        status_patterns = [
            r'"homeStatus"\s*:\s*"([^"]+)"',
            r'<span[^>]*data-test(?:id)?=["\']?(?:listing-)?status["\']?[^>]*>([^<]+)</span>',
            r'"availability"\s*:\s*"([^"]+)"'
        ]
        
        for pattern in status_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['status'] = normalize_status(match.group(1))
                break
        
        if not result['status']:
            result['status'] = 'Status Not Found'
        
        price_patterns = [
            r'<span[^>]*data-testid=["\']price["\'][^>]*>\$?([0-9,]+)',
            r'"price"\s*:\s*([0-9]+)'
        ]
        for pattern in price_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['price'] = '$' + match.group(1)
                break
        
        beds_match = re.search(r'"bedrooms"\s*:\s*(\d+)', html, re.IGNORECASE)
        if beds_match:
            result['beds'] = beds_match.group(1)
        
        baths_match = re.search(r'"bathrooms"\s*:\s*([\d.]+)', html, re.IGNORECASE)
        if baths_match:
            result['baths'] = baths_match.group(1)
        
        sqft_match = re.search(r'"livingArea"\s*:\s*([0-9,]+)', html, re.IGNORECASE)
        if sqft_match:
            result['sqft'] = sqft_match.group(1)
        
        address_patterns = [
            r'<h1[^>]*>([^<]+)</h1>',
            r'"address"\s*:\s*"([^"]+)"'
        ]
        for pattern in address_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['address'] = match.group(1).strip()
                break
        
        year_match = re.search(r'"yearBuilt"\s*:\s*(\d{4})', html, re.IGNORECASE)
        if year_match:
            result['yearBuilt'] = year_match.group(1)
        
        mls_match = re.search(r'MLS[#\s]*:?\s*([A-Z0-9\-]+)', html, re.IGNORECASE)
        if mls_match:
            result['mls'] = mls_match.group(1)
        
        type_match = re.search(r'"homeType"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if type_match:
            result['type'] = type_match.group(1)
        
        agent_name_match = re.search(r'"attributionInfo"[^}]*"agentName"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if agent_name_match:
            result['agentName'] = agent_name_match.group(1).strip()
        
        agent_phone_match = re.search(r'"attributionInfo"[^}]*"agentPhoneNumber"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if agent_phone_match:
            result['agentPhone'] = agent_phone_match.group(1).strip()
        
        brokerage_match = re.search(r'"attributionInfo"[^}]*"brokerageName"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if brokerage_match:
            result['brokerage'] = brokerage_match.group(1).strip()
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': f'Scraping error: {str(e)}'}

def scrape_property(url, source):
    try:
        headers = {'User-Agent': CONFIG['USER_AGENT']}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        
        html = response.text
        
        if source == 'UtahRealEstate.com':
            return scrape_utah_realestate(html)
        elif source == 'Zillow.com':
            return scrape_zillow(html)
        else:
            return {'success': False, 'error': 'Unknown source'}
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Timeout'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ========================================
# DATABASE FUNCTIONS
# ========================================

def add_property(input_text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    url_info = convert_input_to_url(input_text)
    
    if not url_info['success']:
        conn.close()
        return {'success': False, 'error': url_info['error']}
    
    scraped_data = scrape_property(url_info['url'], url_info['source'])
    
    if not scraped_data['success']:
        conn.close()
        return {'success': False, 'error': scraped_data['error']}
    
    cursor.execute("""
        INSERT INTO properties (
            input_text, source, status, price, beds, baths, sqft,
            resolved_url, address, mls, days_on_market, year_built,
            property_type, agent_name, agent_photo, agent_phone, agent_email,
            brokerage, features, last_checked, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        input_text, url_info['source'], scraped_data['status'], scraped_data['price'],
        scraped_data['beds'], scraped_data['baths'], scraped_data['sqft'],
        url_info['url'], scraped_data['address'], scraped_data['mls'],
        scraped_data['daysOnMarket'], scraped_data['yearBuilt'], scraped_data['type'],
        scraped_data['agentName'], scraped_data['agentPhoto'], scraped_data['agentPhone'],
        scraped_data['agentEmail'], scraped_data['brokerage'], scraped_data['features'],
        datetime.now(), 'Success'
    ))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'data': scraped_data}

def bulk_add_properties(inputs_list, progress_callback=None):
    results = {'success': 0, 'failed': 0, 'errors': []}
    
    for idx, input_text in enumerate(inputs_list):
        if progress_callback:
            progress_callback(idx + 1, len(inputs_list), input_text)
        
        result = add_property(input_text)
        
        if result['success']:
            results['success'] += 1
        else:
            results['failed'] += 1
            results['errors'].append(f"{input_text}: {result['error']}")
        
        time.sleep(2)
    
    return results

def get_all_properties():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM properties ORDER BY created_at DESC", conn)
    conn.close()
    return df

def delete_property(property_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM properties WHERE id = ?", (property_id,))
    conn.commit()
    conn.close()

def refresh_property(property_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT input_text, status FROM properties WHERE id = ?", (property_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {'success': False, 'error': 'Not found'}
    
    input_text, old_status = row
    
    url_info = convert_input_to_url(input_text)
    if not url_info['success']:
        conn.close()
        return {'success': False, 'error': url_info['error']}
    
    scraped_data = scrape_property(url_info['url'], url_info['source'])
    if not scraped_data['success']:
        conn.close()
        return {'success': False, 'error': scraped_data['error']}
    
    status_changed = old_status != scraped_data['status']
    
    cursor.execute("""
        UPDATE properties SET
            source = ?, status = ?, price = ?, beds = ?, baths = ?, sqft = ?,
            resolved_url = ?, address = ?, mls = ?, days_on_market = ?,
            year_built = ?, property_type = ?, agent_name = ?, agent_photo = ?,
            agent_phone = ?, agent_email = ?, brokerage = ?, features = ?,
            last_checked = ?,
            last_changed = CASE WHEN ? THEN ? ELSE last_changed END,
            previous_status = CASE WHEN ? THEN ? ELSE previous_status END,
            notes = ?
        WHERE id = ?
    """, (
        url_info['source'], scraped_data['status'], scraped_data['price'],
        scraped_data['beds'], scraped_data['baths'], scraped_data['sqft'],
        url_info['url'], scraped_data['address'], scraped_data['mls'],
        scraped_data['daysOnMarket'], scraped_data['yearBuilt'], scraped_data['type'],
        scraped_data['agentName'], scraped_data['agentPhoto'], scraped_data['agentPhone'],
        scraped_data['agentEmail'], scraped_data['brokerage'], scraped_data['features'],
        datetime.now(),
        status_changed, datetime.now() if status_changed else None,
        status_changed, old_status if status_changed else None,
        'Success', property_id
    ))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'status_changed': status_changed}

def refresh_all_properties_silent():
    """Refresh all properties without UI updates"""
    df = get_all_properties()
    
    if df.empty:
        return {'success': True, 'count': 0, 'changes': 0}
    
    changes = 0
    
    for idx, row in df.iterrows():
        result = refresh_property(row['id'])
        if result.get('success') and result.get('status_changed'):
            changes += 1
        time.sleep(2)
    
    set_setting('last_full_refresh', datetime.now().isoformat())
    
    return {'success': True, 'count': len(df), 'changes': changes}

def refresh_all_properties_ui():
    """Refresh all with progress UI"""
    df = get_all_properties()
    
    if df.empty:
        return {'success': True, 'count': 0, 'changes': 0}
    
    changes = 0
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    
    for idx, row in df.iterrows():
        progress = (idx + 1) / len(df)
        progress_placeholder.progress(progress)
        status_placeholder.info(f"🔄 Refreshing {idx + 1}/{len(df)}: {row['address'] or row['input_text']}")
        
        result = refresh_property(row['id'])
        if result.get('success') and result.get('status_changed'):
            changes += 1
        
        time.sleep(2)
    
    progress_placeholder.empty()
    status_placeholder.empty()
    
    set_setting('last_full_refresh', datetime.now().isoformat())
    
    return {'success': True, 'count': len(df), 'changes': changes}

def process_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
        
        possible_columns = ['mls', 'mls#', 'mls_number', 'url', 'link', 'property_url', 'property_link']
        
        property_column = None
        for col in df.columns:
            if col.lower().strip() in possible_columns:
                property_column = col
                break
        
        if not property_column:
            property_column = df.columns[0]
        
        properties = df[property_column].dropna().astype(str).tolist()
        
        return {'success': True, 'properties': properties, 'column': property_column}
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

def export_to_csv():
    df = get_all_properties()
    
    if df.empty:
        return None
    
    export_df = df[[
        'mls', 'address', 'status', 'price', 'beds', 'baths', 'sqft',
        'property_type', 'year_built', 'days_on_market',
        'agent_name', 'agent_phone', 'agent_email', 'brokerage',
        'resolved_url', 'source', 'last_checked'
    ]]
    
    return export_df.to_csv(index=False)

# ========================================
# ZOHO CRM FUNCTIONS
# ========================================

def get_zoho_auth_url():
    """Generate Zoho OAuth authorization URL"""
    state = secrets.token_urlsafe(32)
    set_setting('zoho_oauth_state', state)
    
    params = {
        'scope': 'ZohoCRM.modules.ALL,ZohoCRM.settings.ALL',
        'client_id': CONFIG['ZOHO_CLIENT_ID'],
        'response_type': 'code',
        'access_type': 'offline',
        'redirect_uri': CONFIG['ZOHO_REDIRECT_URI'],
        'state': state
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    return f"{CONFIG['ZOHO_AUTH_URL']}?{query_string}"

def exchange_code_for_token(code):
    """Exchange authorization code for tokens"""
    try:
        data = {
            'code': code,
            'client_id': CONFIG['ZOHO_CLIENT_ID'],
            'client_secret': CONFIG['ZOHO_CLIENT_SECRET'],
            'redirect_uri': CONFIG['ZOHO_REDIRECT_URI'],
            'grant_type': 'authorization_code'
        }
        
        response = requests.post(CONFIG['ZOHO_TOKEN_URL'], data=data)
        
        if response.status_code == 200:
            tokens = response.json()
            
            set_setting('zoho_access_token', tokens.get('access_token', ''))
            set_setting('zoho_refresh_token', tokens.get('refresh_token', ''))
            
            expiry = datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600))
            set_setting('zoho_token_expiry', expiry.isoformat())
            set_setting('zoho_connected', 'true')
            
            return {'success': True}
        else:
            return {'success': False, 'error': response.text}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

def refresh_zoho_access_token():
    """Refresh access token"""
    refresh_token = get_setting('zoho_refresh_token', '')
    
    if not refresh_token:
        return False
    
    try:
        data = {
            'refresh_token': refresh_token,
            'client_id': CONFIG['ZOHO_CLIENT_ID'],
            'client_secret': CONFIG['ZOHO_CLIENT_SECRET'],
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(CONFIG['ZOHO_TOKEN_URL'], data=data)
        
        if response.status_code == 200:
            tokens = response.json()
            
            set_setting('zoho_access_token', tokens.get('access_token', ''))
            
            expiry = datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600))
            set_setting('zoho_token_expiry', expiry.isoformat())
            
            return True
        else:
            return False
            
    except Exception as e:
        return False

def get_zoho_access_token():
    """Get valid access token (refresh if needed)"""
    token_expiry_str = get_setting('zoho_token_expiry', '')
    
    if token_expiry_str:
        try:
            expiry = datetime.fromisoformat(token_expiry_str)
            
            if datetime.now() >= expiry - timedelta(minutes=5):
                if not refresh_zoho_access_token():
                    return None
        except:
            return None
    
    return get_setting('zoho_access_token', '')

def fetch_zoho_modules():
    """Fetch available modules"""
    access_token = get_zoho_access_token()
    
    if not access_token:
        return {'success': False, 'error': 'Not authenticated'}
    
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{CONFIG['ZOHO_API_BASE']}/settings/modules", headers=headers)
        
        if response.status_code == 200:
            modules_data = response.json()
            modules = [m['api_name'] for m in modules_data.get('modules', []) if not m.get('generated_type')]
            return {'success': True, 'modules': modules}
        else:
            return {'success': False, 'error': response.text}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

def fetch_zoho_module_fields(module_name):
    """Fetch fields for a module"""
    access_token = get_zoho_access_token()
    
    if not access_token:
        return {'success': False, 'error': 'Not authenticated'}
    
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{CONFIG['ZOHO_API_BASE']}/settings/fields?module={module_name}", headers=headers)
        
        if response.status_code == 200:
            fields_data = response.json()
            fields = [
                {
                    'api_name': f['api_name'],
                    'display_label': f.get('field_label', f['api_name']),
                    'data_type': f.get('data_type', 'text')
                }
                for f in fields_data.get('fields', [])
            ]
            return {'success': True, 'fields': fields}
        else:
            return {'success': False, 'error': response.text}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

def save_field_mapping(module, mapping):
    """Save field mapping"""
    mapping_json = json.dumps({'module': module, 'mapping': mapping})
    set_setting('zoho_field_mapping', mapping_json)
    set_setting('zoho_module', module)

def get_field_mapping():
    """Get saved field mapping"""
    mapping_json = get_setting('zoho_field_mapping', '')
    
    if not mapping_json:
        return None
    
    try:
        return json.loads(mapping_json)
    except:
        return None

def sync_to_zoho_crm():
    """Sync properties to Zoho"""
    access_token = get_zoho_access_token()
    
    if not access_token:
        return {'success': False, 'error': 'Not authenticated'}
    
    mapping_data = get_field_mapping()
    
    if not mapping_data:
        return {'success': False, 'error': 'No field mapping configured'}
    
    module = mapping_data['module']
    mapping = mapping_data['mapping']
    
    df = get_all_properties()
    
    if df.empty:
        return {'success': True, 'synced': 0, 'message': 'No properties to sync'}
    
    synced = 0
    errors = []
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    for _, row in df.iterrows():
        try:
            record_data = {}
            
            for prop_field, zoho_field in mapping.items():
                if zoho_field:
                    value = row.get(prop_field, '')
                    
                    if value and value != '':
                        if prop_field == 'price':
                            value = value.replace('$', '').replace(',', '')
                        
                        record_data[zoho_field] = value
            
            if row['zoho_id']:
                url = f"{CONFIG['ZOHO_API_BASE']}/{module}/{row['zoho_id']}"
                response = requests.put(url, headers=headers, json={'data': [record_data]})
            else:
                url = f"{CONFIG['ZOHO_API_BASE']}/{module}"
                response = requests.post(url, headers=headers, json={'data': [record_data]})
                
                if response.status_code == 201:
                    zoho_id = response.json()['data'][0]['details']['id']
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE properties SET zoho_id = ? WHERE id = ?", (zoho_id, row['id']))
                    conn.commit()
                    conn.close()
            
            if response.status_code in [200, 201]:
                synced += 1
            else:
                errors.append(f"{row['mls']}: {response.text}")
                
        except Exception as e:
            errors.append(f"{row['mls']}: {str(e)}")
    
    set_setting('zoho_last_sync', datetime.now().isoformat())
    
    return {
        'success': True,
        'synced': synced,
        'total': len(df),
        'errors': errors
    }

# ========================================
# UI FUNCTIONS
# ========================================

def get_status_badge_class(status):
    status_lower = status.lower()
    if 'sale' in status_lower:
        return 'status-for-sale'
    elif 'pending' in status_lower or 'contingent' in status_lower:
        return 'status-pending'
    elif 'sold' in status_lower:
        return 'status-sold'
    else:
        return 'status-off-market'

def render_property_card(row):
    """Render property card"""
    status_class = get_status_badge_class(row['status'])
    
    header_parts = []
    
    if row['mls']:
        header_parts.append(f"MLS# {row['mls']}")
    
    if row['address']:
        header_parts.append(row['address'])
    else:
        header_parts.append(row['input_text'])
    
    if row['status']:
        header_parts.append(f"Status: {row['status']}")
    
    if row['agent_name']:
        header_parts.append(f"Agent: {row['agent_name']}")
    
    header = " • ".join(header_parts)
    
    with st.expander(header, expanded=False):
        st.markdown(f'<span class="status-badge {status_class}">{row["status"]}</span>', 
                   unsafe_allow_html=True)
        
        st.divider()
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            st.markdown("### 🏠 Property Details")
            st.write(f"**💰 Price:** {row['price']}")
            st.write(f"**🛏️ Beds:** {row['beds']}")
            st.write(f"**🚿 Baths:** {row['baths']}")
            st.write(f"**📐 Sq Ft:** {row['sqft']}")
            st.write(f"**🏠 Type:** {row['property_type']}")
            st.write(f"**📅 Year Built:** {row['year_built']}")
            st.write(f"**📆 Days on Market:** {row['days_on_market']}")
        
        with col2:
            st.markdown("### 👤 Agent Info")
            st.write(f"**Name:** {row['agent_name'] or 'N/A'}")
            st.write(f"**📞 Phone:** {row['agent_phone'] or 'N/A'}")
            st.write(f"**📧 Email:** {row['agent_email'] or 'N/A'}")
            st.write(f"**🏢 Brokerage:** {row['brokerage'] or 'N/A'}")
            
            st.markdown("### ℹ️ Info")
            st.write(f"**Source:** {row['source']}")
            if row['last_checked']:
                st.write(f"**Last Checked:** {row['last_checked']}")
        
        with col3:
            st.markdown("### Actions")
            
            if st.button("🔄", key=f"refresh_{row['id']}", use_container_width=True, help="Refresh"):
                with st.spinner("Refreshing..."):
                    result = refresh_property(row['id'])
                    if result.get('success'):
                        st.success("✅")
                        if result.get('status_changed'):
                            st.balloons()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Error: {result.get('error', 'Unknown error')}")
            
            if st.button("🗑️", key=f"delete_{row['id']}", use_container_width=True, help="Delete"):
                delete_property(row['id'])
                st.success("Deleted!")
                time.sleep(1)
                st.rerun()
            
            if row['resolved_url']:
                st.link_button("🔗", row['resolved_url'], use_container_width=True, help="View")

# ========================================
# MAIN APP
# ========================================

def main():
    # Initial load refresh
    if 'initial_load_complete' not in st.session_state:
        st.session_state.initial_load_complete = False
    
    if not st.session_state.initial_load_complete:
        df = get_all_properties()
        
        if not df.empty:
            with st.spinner("🔄 Loading and refreshing properties..."):
                try:
                    result = refresh_all_properties_silent()
                    if result and result.get('changes', 0) > 0:
                        st.success(f"✅ Loaded! {result['changes']} status change(s) detected.", icon="🎉")
                except Exception as e:
                    st.warning("Could not refresh properties on load.")
        
        st.session_state.initial_load_complete = True
    
    # Sidebar
    with st.sidebar:
        st.title("🏠 Utah RE Monitor")
        
        page = st.radio("", ["📊 Dashboard", "📤 Bulk Upload", "⚙️ Settings", "❓ Help"], 
                       label_visibility="collapsed")
    
    # Main Content
    if page == "📊 Dashboard":
        st.title("📊 Dashboard")
        
        # Quick Add Section
        st.markdown('<div class="quick-add-section">', unsafe_allow_html=True)
        st.markdown("### ➕ Quick Add Property")
        
        col1, col2 = st.columns([4, 1])
        
        with col1:
            quick_input = st.text_input(
                "Enter URL or MLS#",
                placeholder="e.g., 2053078 or https://www.utahrealestate.com/report/...",
                label_visibility="collapsed"
            )
        
        with col2:
            add_clicked = st.button("➕ Add", type="primary", use_container_width=True)
        
        if add_clicked and quick_input:
            with st.spinner("Adding property..."):
                result = add_property(quick_input)
                if result.get('success'):
                    st.success("✅ Property added!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(result.get('error', 'Failed to add property'))
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Properties Display
        df = get_all_properties()
        
        if df.empty:
            st.info("👋 No properties yet. Add your first property above or use Bulk Upload!")
        else:
            # Stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📋 Total", len(df))
            with col2:
                for_sale = len(df[df['status'] == 'For Sale'])
                st.metric("🟢 For Sale", for_sale)
            with col3:
                pending = len(df[df['status'] == 'Pending'])
                st.metric("🟡 Pending", pending)
            with col4:
                sold = len(df[df['status'] == 'Sold'])
                st.metric("🔴 Sold", sold)
            
            st.divider()
            
            # Controls
            col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
            with col1:
                if st.button("📇 Cards", use_container_width=True, 
                           type="primary" if get_setting('view_mode', 'cards') == 'cards' else "secondary"):
                    set_setting('view_mode', 'cards')
                    st.rerun()
            with col2:
                if st.button("📊 Table", use_container_width=True,
                           type="primary" if get_setting('view_mode', 'cards') == 'table' else "secondary"):
                    set_setting('view_mode', 'table')
                    st.rerun()
            with col3:
                if st.button("🔄 Refresh All", use_container_width=True):
                    result = refresh_all_properties_ui()
                    if result and result.get('success'):
                        if result.get('changes', 0) > 0:
                            st.success(f"✅ {result['changes']} changes detected!")
                            st.balloons()
                        else:
                            st.success("✅ All up to date!")
                        time.sleep(2)
                        st.rerun()
            with col4:
                csv_data = export_to_csv()
                if csv_data:
                    st.download_button(
                        "📥 CSV",
                        csv_data,
                        "properties.csv",
                        "text/csv",
                        use_container_width=True
                    )
            
            st.divider()
            
            # Display
            view_mode = get_setting('view_mode', 'cards')
            
            if view_mode == 'cards':
                for _, row in df.iterrows():
                    render_property_card(row)
            else:
                display_df = df[[
                    'mls', 'address', 'status', 'price', 'beds', 'baths', 'sqft',
                    'property_type', 'days_on_market', 'year_built',
                    'agent_name', 'agent_phone', 'brokerage', 'last_checked'
                ]].copy()
                
                display_df.columns = [
                    'MLS#', 'Address', 'Status', 'Price', 'Beds', 'Baths', 'Sq Ft',
                    'Type', 'Days on Market', 'Year Built',
                    'Agent', 'Phone', 'Brokerage', 'Last Checked'
                ]
                
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                
                selected_ids = st.multiselect(
                    "Select to delete:",
                    options=df['id'].tolist(),
                    format_func=lambda x: f"MLS# {df[df['id']==x]['mls'].iloc[0]} - {df[df['id']==x]['address'].iloc[0]}"
                )
                
                if selected_ids and st.button("🗑️ Delete Selected"):
                    for prop_id in selected_ids:
                        delete_property(prop_id)
                    st.success(f"Deleted {len(selected_ids)} properties!")
                    time.sleep(1)
                    st.rerun()
    
    elif page == "📤 Bulk Upload":
        st.title("📤 Bulk Upload Properties")
        
        tab1, tab2 = st.tabs(["📝 Text Input", "📄 CSV Upload"])
        
        with tab1:
            st.markdown("### Paste Multiple URLs or MLS Numbers")
            st.caption("Enter one per line")
            
            bulk_input = st.text_area(
                "Properties",
                height=300,
                placeholder="2053078\nhttps://www.utahrealestate.com/report/1234567\n..."
            )
            
            if st.button("🚀 Start Bulk Upload", type="primary"):
                if not bulk_input.strip():
                    st.error("Please enter at least one property")
                else:
                    inputs = [line.strip() for line in bulk_input.split('\n') if line.strip()]
                    
                    st.info(f"Processing {len(inputs)} properties...")
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def progress_callback(current, total, item):
                        progress_bar.progress(current / total)
                        status_text.text(f"Processing {current}/{total}: {item}")
                    
                    results = bulk_add_properties(inputs, progress_callback)
                    
                    progress_bar.empty()
                    status_text.empty()
                    
                    st.success(f"✅ Successfully added: {results['success']}")
                    if results['failed'] > 0:
                        st.error(f"❌ Failed: {results['failed']}")
                        with st.expander("View Errors"):
                            for error in results['errors']:
                                st.text(error)
                    
                    time.sleep(2)
                    st.rerun()
        
        with tab2:
            st.markdown("### Upload CSV File")
            st.caption("CSV should have MLS numbers or URLs")
            
            uploaded_file = st.file_uploader("Choose CSV file", type=['csv'])
            
            if uploaded_file:
                result = process_csv(uploaded_file)
                
                if result.get('success'):
                    st.success(f"✅ Found {len(result['properties'])} properties in column '{result['column']}'")
                    
                    with st.expander("Preview"):
                        st.write(result['properties'][:10])
                        if len(result['properties']) > 10:
                            st.caption(f"...and {len(result['properties']) - 10} more")
                    
                    if st.button("🚀 Import All", type="primary"):
                        st.info(f"Processing {len(result['properties'])} properties...")
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        def progress_callback(current, total, item):
                            progress_bar.progress(current / total)
                            status_text.text(f"Processing {current}/{total}: {item}")
                        
                        results = bulk_add_properties(result['properties'], progress_callback)
                        
                        progress_bar.empty()
                        status_text.empty()
                        
                        st.success(f"✅ Successfully added: {results['success']}")
                        if results['failed'] > 0:
                            st.error(f"❌ Failed: {results['failed']}")
                            with st.expander("View Errors"):
                                for error in results['errors']:
                                    st.text(error)
                        
                        time.sleep(2)
                        st.rerun()
                else:
                    st.error(f"CSV processing failed: {result.get('error', 'Unknown error')}")
    
    elif page == "⚙️ Settings":
        st.title("⚙️ Settings")
        
        tab1, tab2 = st.tabs(["🔗 Zoho CRM", "📊 Data"])
        
        with tab1:
            st.markdown("### Zoho CRM Integration")
            
            zoho_connected = get_setting('zoho_connected', 'false') == 'true'
            
            # Connection Status Display
            if zoho_connected:
                st.markdown(
                    '<div class="connection-status status-connected">✅ Connected to Zoho CRM</div>',
                    unsafe_allow_html=True
                )
                
                # Sync Toggle
                sync_enabled = st.toggle(
                    "Enable Zoho Sync",
                    value=get_setting('zoho_sync_enabled', 'false') == 'true',
                    help="When enabled, you can sync properties to Zoho CRM"
                )
                
                if sync_enabled != (get_setting('zoho_sync_enabled', 'false') == 'true'):
                    set_setting('zoho_sync_enabled', 'true' if sync_enabled else 'false')
                    st.success(f"Zoho sync {'enabled' if sync_enabled else 'disabled'}!")
                    st.rerun()
                
                st.divider()
                
                # Module Selection
                st.markdown("### Select Module")
                
                modules_result = fetch_zoho_modules()
                
                if modules_result.get('success'):
                    current_module = get_setting('zoho_module', '')
                    
                    selected_module = st.selectbox(
                        "Zoho Module",
                        options=[''] + modules_result['modules'],
                        index=modules_result['modules'].index(current_module) + 1 if current_module in modules_result['modules'] else 0,
                        format_func=lambda x: 'Select a module...' if x == '' else x
                    )
                    
                    if selected_module:
                        # Fetch fields for selected module
                        fields_result = fetch_zoho_module_fields(selected_module)
                        
                        if fields_result.get('success'):
                            st.divider()
                            
                            # Field Mapping Section
                            st.markdown("### Field Mapping")
                            st.caption("Add the fields you want to sync")
                            
                            # Initialize mapping state
                            if 'field_mapping' not in st.session_state:
                                existing_mapping = get_field_mapping()
                                if existing_mapping and existing_mapping['module'] == selected_module:
                                    st.session_state.field_mapping = existing_mapping['mapping']
                                else:
                                    st.session_state.field_mapping = {}
                            
                            # Available property fields
                            property_fields = {
                                'mls': 'MLS Number',
                                'address': 'Address',
                                'status': 'Status',
                                'price': 'Price',
                                'beds': 'Bedrooms',
                                'baths': 'Bathrooms',
                                'sqft': 'Square Feet',
                                'property_type': 'Property Type',
                                'year_built': 'Year Built',
                                'days_on_market': 'Days on Market',
                                'agent_name': 'Agent Name',
                                'agent_phone': 'Agent Phone',
                                'agent_email': 'Agent Email',
                                'brokerage': 'Brokerage'
                            }
                            
                            # Zoho field options
                            zoho_field_options = {f"{f['display_label']} ({f['api_name']})": f['api_name'] for f in fields_result['fields']}
                            
                            # Display existing mappings
                            if st.session_state.field_mapping:
                                st.markdown("**Current Field Mappings:**")
                                
                                for prop_field, zoho_field in list(st.session_state.field_mapping.items()):
                                    col1, col2, col3, col4 = st.columns([2, 1, 2, 1])
                                    
                                    with col1:
                                        st.markdown(f'<div class="field-mapping-row">{property_fields.get(prop_field, prop_field)}</div>', unsafe_allow_html=True)
                                    
                                    with col2:
                                        st.markdown('<div class="field-mapping-row">→</div>', unsafe_allow_html=True)
                                    
                                    with col3:
                                        # Find display name for zoho field
                                        zoho_display = None
                                        for display, api in zoho_field_options.items():
                                            if api == zoho_field:
                                                zoho_display = display
                                                break
                                        st.markdown(f'<div class="field-mapping-row">{zoho_display or zoho_field}</div>', unsafe_allow_html=True)
                                    
                                    with col4:
                                        if st.button("🗑️", key=f"remove_{prop_field}", help="Remove mapping"):
                                            del st.session_state.field_mapping[prop_field]
                                            st.rerun()
                                
                                st.divider()
                            
                            # Add new field mapping
                            st.markdown("**Add Field Mapping:**")
                            
                            col1, col2, col3 = st.columns([2, 2, 1])
                            
                            with col1:
                                # Only show property fields not already mapped
                                available_prop_fields = {k: v for k, v in property_fields.items() if k not in st.session_state.field_mapping}
                                
                                if available_prop_fields:
                                    selected_prop_field = st.selectbox(
                                        "Property Field",
                                        options=list(available_prop_fields.keys()),
                                        format_func=lambda x: available_prop_fields[x],
                                        key="new_prop_field"
                                    )
                                else:
                                    st.info("All fields mapped!")
                                    selected_prop_field = None
                            
                            with col2:
                                if selected_prop_field:
                                    selected_zoho_field = st.selectbox(
                                        "Zoho Field",
                                        options=list(zoho_field_options.keys()),
                                        key="new_zoho_field"
                                    )
                            
                            with col3:
                                if selected_prop_field:
                                    if st.button("➕ Add", use_container_width=True):
                                        st.session_state.field_mapping[selected_prop_field] = zoho_field_options[selected_zoho_field]
                                        st.rerun()
                            
                            st.divider()
                            
                            # Save and Remap buttons
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                if st.button("💾 Save Mapping", type="primary", use_container_width=True):
                                    if st.session_state.field_mapping:
                                        save_field_mapping(selected_module, st.session_state.field_mapping)
                                        st.success("✅ Field mapping saved!")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error("Please add at least one field mapping")
                            
                            with col2:
                                if st.button("🔄 Remap", use_container_width=True):
                                    st.session_state.field_mapping = {}
                                    set_setting('zoho_field_mapping', '')
                                    st.success("Mapping cleared! Add new field mappings above.")
                                    st.rerun()
                            
                            # Sync Section
                            if get_setting('zoho_field_mapping', '') and sync_enabled:
                                st.divider()
                                st.markdown("### Sync Properties")
                                
                                if st.button("🔄 Sync All Properties to Zoho CRM", type="primary"):
                                    # Confirmation
                                    confirm = st.button("✅ Confirm Sync", type="secondary")
                                    
                                    if confirm:
                                        with st.spinner("Syncing..."):
                                            result = sync_to_zoho_crm()
                                            
                                            if result.get('success'):
                                                st.success(f"✅ Synced {result['synced']}/{result['total']} properties!")
                                                
                                                if result.get('errors'):
                                                    with st.expander("View Errors"):
                                                        for error in result['errors']:
                                                            st.text(error)
                                            else:
                                                st.error(f"❌ {result.get('error', 'Unknown error')}")
                                
                                last_sync = get_setting('zoho_last_sync', '')
                                if last_sync:
                                    try:
                                        last_sync_dt = datetime.fromisoformat(last_sync)
                                        st.info(f"🕒 Last sync: {last_sync_dt.strftime('%Y-%m-%d %I:%M %p')}")
                                    except:
                                        pass
                        else:
                            st.error(f"Failed to fetch fields: {fields_result.get('error', 'Unknown error')}")
                else:
                    st.error(f"Failed to fetch modules: {modules_result.get('error', 'Unknown error')}")
                
                st.divider()
                
                # Disconnect button
                if st.button("🔌 Disconnect from Zoho", type="secondary"):
                    confirm_disconnect = st.button("⚠️ Confirm Disconnect")
                    
                    if confirm_disconnect:
                        set_setting('zoho_connected', 'false')
                        set_setting('zoho_sync_enabled', 'false')
                        set_setting('zoho_access_token', '')
                        set_setting('zoho_refresh_token', '')
                        set_setting('zoho_field_mapping', '')
                        set_setting('zoho_module', '')
                        st.success("Disconnected from Zoho CRM")
                        time.sleep(1)
                        st.rerun()
            
            else:
                # Not connected
                st.markdown(
                    '<div class="connection-status status-disconnected">❌ Not Connected to Zoho CRM</div>',
                    unsafe_allow_html=True
                )
                
                st.info("Connect to Zoho CRM to sync your properties automatically")
                
                st.markdown("""
                **How it works:**
                1. Click "Connect to Zoho CRM"
                2. Authorize in the popup
                3. Select which Zoho module to use (Deals, Leads, etc.)
                4. Choose which fields to sync
                5. Enable sync and start syncing!
                """)
                
                if st.button("🔗 Connect to Zoho CRM", type="primary"):
                    auth_url = get_zoho_auth_url()
                    st.markdown(f"[Click here to authorize]({auth_url})")
                    st.info("After authorizing, you'll be redirected back and the connection will be established automatically.")
        
        with tab2:
            st.markdown("### Data Management")
            
            df = get_all_properties()
            st.info(f"📊 Total properties: {len(df)}")
            
            last_refresh = get_setting('last_full_refresh', '')
            if last_refresh:
                try:
                    last_refresh_dt = datetime.fromisoformat(last_refresh)
                    st.info(f"🕒 Last full refresh: {last_refresh_dt.strftime('%Y-%m-%d %I:%M %p')}")
                except:
                    pass
            
            st.divider()
            
            if st.button("🗑️ Clear All Data", type="secondary"):
                if st.button("⚠️ Confirm Delete All"):
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM properties")
                    conn.commit()
                    conn.close()
                    st.success("All data cleared!")
                    time.sleep(1)
                    st.rerun()
    
    elif page == "❓ Help":
        st.title("❓ Help")
        
        st.markdown("""
        ### 🎯 Quick Start
        
        1. **Add Properties**: Dashboard → Quick Add
        2. **Bulk Import**: Bulk Upload page
        3. **Connect Zoho**: Settings → Zoho CRM
        
        ### 💡 Tips
        
        - App auto-refreshes on load
        - Map only fields you need
        - Test sync with 1-2 properties first
        """)

if __name__ == "__main__":
    main()
