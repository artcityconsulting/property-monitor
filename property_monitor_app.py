"""
Utah Real Estate Property Monitor - Modern UI (V2)
A sleek web-based property monitoring tool with auto-refresh
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

# Page configuration
st.set_page_config(
    page_title="Utah RE Monitor",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern styling
st.markdown("""
<style>
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Modern card styling */
    .property-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 16px;
        border-left: 4px solid #1f77b4;
    }
    
    /* Floating action button */
    .floating-button {
        position: fixed;
        bottom: 30px;
        right: 30px;
        z-index: 999;
    }
    
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .status-for-sale { background: #d4edda; color: #155724; }
    .status-pending { background: #fff3cd; color: #856404; }
    .status-sold { background: #f8d7da; color: #721c24; }
    .status-off-market { background: #e2e3e5; color: #383d41; }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 12px;
        text-align: center;
    }
    
    /* Table styling */
    .dataframe {
        font-size: 14px;
    }
    
    /* View toggle buttons */
    .view-toggle {
        display: flex;
        gap: 8px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# Database setup
DB_PATH = Path("properties.db")

def init_database():
    """Initialize SQLite database with settings table"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Properties table
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Settings table for auto-refresh configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Initialize default settings
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                   ('auto_refresh_enabled', 'true'))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                   ('refresh_interval_days', '1'))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                   ('last_refresh', ''))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                   ('view_mode', 'cards'))
    
    conn.commit()
    conn.close()

init_database()

# Configuration
CONFIG = {
    'UTAH_URL_PATTERN': 'https://www.utahrealestate.com/report/',
    'ZILLOW_URL_PATTERN': 'https://www.zillow.com/homedetails/',
    'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ========================================
# SETTINGS FUNCTIONS
# ========================================

def get_setting(key, default=''):
    """Get a setting value from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default

def set_setting(key, value):
    """Set a setting value in database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def should_auto_refresh():
    """Check if auto-refresh should run based on settings"""
    auto_refresh_enabled = get_setting('auto_refresh_enabled', 'true') == 'true'
    if not auto_refresh_enabled:
        return False
    
    last_refresh_str = get_setting('last_refresh', '')
    if not last_refresh_str:
        return True
    
    try:
        last_refresh = datetime.fromisoformat(last_refresh_str)
        interval_days = int(get_setting('refresh_interval_days', '1'))
        next_refresh = last_refresh + timedelta(days=interval_days)
        return datetime.now() >= next_refresh
    except:
        return True

# ========================================
# HELPER FUNCTIONS (Same as before)
# ========================================

def detect_source(url):
    """Detect which website the URL is from"""
    if 'utahrealestate.com' in url:
        return 'UtahRealEstate.com'
    elif 'zillow.com' in url:
        return 'Zillow.com'
    return None

def convert_input_to_url(input_text):
    """Convert MLS number or URL to full URL"""
    input_text = input_text.strip()
    
    if input_text.startswith('http://') or input_text.startswith('https://'):
        source = detect_source(input_text)
        if source:
            return {'success': True, 'url': input_text, 'source': source}
        else:
            return {'success': False, 'error': 'Unsupported website. Use UtahRealEstate.com or Zillow.com'}
    
    mls_match = re.match(r'^(MLS)?(\d{6,10})$', input_text, re.IGNORECASE)
    if mls_match:
        mls_number = mls_match.group(2)
        return {
            'success': True,
            'url': CONFIG['UTAH_URL_PATTERN'] + mls_number,
            'source': 'UtahRealEstate.com'
        }
    
    if re.match(r'\d+.*[a-zA-Z].*,', input_text):
        return {
            'success': False,
            'error': 'Address detected. Please find the property URL manually.'
        }
    
    return {
        'success': False,
        'error': 'Invalid input. Enter a URL or MLS#.'
    }

def normalize_status(status_text):
    """Normalize status across different sources"""
    if not status_text:
        return ''
    
    status = status_text.upper().strip()
    
    status_map = {
        'FOR_SALE': 'For Sale',
        'ACTIVE': 'For Sale',
        'FOR SALE': 'For Sale',
        'OFF_MARKET': 'Off Market',
        'OFF MARKET': 'Off Market',
        'PENDING': 'Pending',
        'UNDER CONTRACT': 'Pending',
        'CONTINGENT': 'Contingent',
        'SOLD': 'Sold',
        'CLOSED': 'Sold',
        'COMING_SOON': 'Coming Soon',
        'COMING SOON': 'Coming Soon',
        'FOR_RENT': 'For Rent',
        'FOR RENT': 'For Rent'
    }
    
    return status_map.get(status, status_text)

def scrape_utah_realestate(html):
    """Scrape UtahRealEstate.com"""
    result = {
        'success': True,
        'status': '',
        'price': '',
        'beds': '',
        'baths': '',
        'sqft': '',
        'address': '',
        'mls': '',
        'daysOnMarket': '',
        'yearBuilt': '',
        'type': '',
        'agentName': '',
        'agentPhoto': '',
        'agentPhone': '',
        'agentEmail': '',
        'brokerage': '',
        'features': ''
    }
    
    try:
        # Price
        price_match = re.search(r'\$?([1-9]\d{2}(?:,?\d{3}){1,2}(?:,\d{3})?)', html)
        if price_match:
            result['price'] = '$' + price_match.group(1).strip()
        
        # Address
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
        
        # Agent info
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
        
        # Brokerage
        brokerage_match = re.search(
            r'<div[^>]*class=["\'][^"\']*broker-overview-content[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            html, re.IGNORECASE
        )
        if brokerage_match:
            strong_match = re.search(r'<strong>([^<]+)</strong>', brokerage_match.group(1), re.IGNORECASE)
            if strong_match:
                result['brokerage'] = strong_match.group(1).strip()
        
        # Facts
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
        
        # Beds/baths/sqft
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
        return {'success': False, 'error': f'Utah RE scraping failed: {str(e)}'}

def scrape_zillow(html):
    """Scrape Zillow.com"""
    result = {
        'success': True,
        'status': '',
        'price': '',
        'beds': '',
        'baths': '',
        'sqft': '',
        'address': '',
        'mls': '',
        'daysOnMarket': '',
        'yearBuilt': '',
        'type': '',
        'agentName': '',
        'agentPhoto': '',
        'agentPhone': '',
        'agentEmail': '',
        'brokerage': '',
        'features': ''
    }
    
    try:
        # Status
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
        
        # Price
        price_patterns = [
            r'<span[^>]*data-testid=["\']price["\'][^>]*>\$?([0-9,]+)',
            r'"price"\s*:\s*([0-9]+)'
        ]
        for pattern in price_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['price'] = '$' + match.group(1)
                break
        
        # Beds/baths/sqft
        beds_match = re.search(r'"bedrooms"\s*:\s*(\d+)', html, re.IGNORECASE)
        if beds_match:
            result['beds'] = beds_match.group(1)
        
        baths_match = re.search(r'"bathrooms"\s*:\s*([\d.]+)', html, re.IGNORECASE)
        if baths_match:
            result['baths'] = baths_match.group(1)
        
        sqft_match = re.search(r'"livingArea"\s*:\s*([0-9,]+)', html, re.IGNORECASE)
        if sqft_match:
            result['sqft'] = sqft_match.group(1)
        
        # Address
        address_patterns = [
            r'<h1[^>]*>([^<]+)</h1>',
            r'"address"\s*:\s*"([^"]+)"'
        ]
        for pattern in address_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['address'] = match.group(1).strip()
                break
        
        # Other details
        year_match = re.search(r'"yearBuilt"\s*:\s*(\d{4})', html, re.IGNORECASE)
        if year_match:
            result['yearBuilt'] = year_match.group(1)
        
        mls_match = re.search(r'MLS[#\s]*:?\s*([A-Z0-9\-]+)', html, re.IGNORECASE)
        if mls_match:
            result['mls'] = mls_match.group(1)
        
        type_match = re.search(r'"homeType"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if type_match:
            result['type'] = type_match.group(1)
        
        # Agent info
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
        return {'success': False, 'error': f'Zillow scraping error: {str(e)}'}

def scrape_property(url, source):
    """Fetch and scrape a property URL"""
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
        return {'success': False, 'error': 'Request timed out'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ========================================
# DATABASE FUNCTIONS
# ========================================

def add_property(input_text):
    """Add a property to the database"""
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

def get_all_properties():
    """Retrieve all properties from database"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM properties ORDER BY created_at DESC", conn)
    conn.close()
    return df

def delete_property(property_id):
    """Delete a property from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM properties WHERE id = ?", (property_id,))
    conn.commit()
    conn.close()

def refresh_property(property_id):
    """Refresh a single property's data"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT input_text, status FROM properties WHERE id = ?", (property_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {'success': False, 'error': 'Property not found'}
    
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

def refresh_all_properties():
    """Refresh all properties with progress tracking"""
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
        if result['success'] and result.get('status_changed'):
            changes += 1
        
        time.sleep(2)  # Rate limiting
    
    progress_placeholder.empty()
    status_placeholder.empty()
    
    # Update last refresh timestamp
    set_setting('last_refresh', datetime.now().isoformat())
    
    return {'success': True, 'count': len(df), 'changes': changes}

# ========================================
# UI HELPER FUNCTIONS
# ========================================

def get_status_badge_class(status):
    """Get CSS class for status badge"""
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
    """Render a property in card view"""
    status_class = get_status_badge_class(row['status'])
    
    st.markdown(f"""
    <div class="property-card">
        <h3>{row['address'] or row['input_text']}</h3>
        <span class="status-badge {status_class}">{row['status']}</span>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        st.markdown(f"**💰 Price:** {row['price']}")
        st.markdown(f"**🛏️ Beds/Baths:** {row['beds']} bed, {row['baths']} bath")
        st.markdown(f"**📐 Sq Ft:** {row['sqft']}")
        st.markdown(f"**🏷️ MLS#:** {row['mls']}")
        st.markdown(f"**🏠 Type:** {row['property_type']}")
    
    with col2:
        if row['agent_name']:
            st.markdown(f"**👤 Agent:** {row['agent_name']}")
            if row['agent_phone']:
                st.markdown(f"**📞 Phone:** {row['agent_phone']}")
            if row['agent_email']:
                st.markdown(f"**📧 Email:** {row['agent_email']}")
        if row['brokerage']:
            st.markdown(f"**🏢 Brokerage:** {row['brokerage']}")
        st.markdown(f"**🕒 Last Checked:** {row['last_checked']}")
    
    with col3:
        if st.button("🔄", key=f"refresh_{row['id']}", help="Refresh this property"):
            with st.spinner("Refreshing..."):
                result = refresh_property(row['id'])
                if result['success']:
                    st.success("✅ Updated!")
                    if result['status_changed']:
                        st.balloons()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"Error: {result['error']}")
        
        if st.button("🗑️", key=f"delete_{row['id']}", help="Delete this property"):
            delete_property(row['id'])
            st.success("Deleted!")
            time.sleep(1)
            st.rerun()
        
        if row['resolved_url']:
            st.markdown(f"[🔗 View]({row['resolved_url']})")

# ========================================
# MAIN APP
# ========================================

def main():
    # Sidebar
    with st.sidebar:
        st.title("🏠 Utah RE Monitor")
        
        page = st.radio("", ["📊 Dashboard", "⚙️ Settings", "❓ Help"], label_visibility="collapsed")
        
        st.divider()
        
        # Quick Add Form in Sidebar
        with st.expander("➕ Quick Add Property", expanded=False):
            with st.form("quick_add_form", clear_on_submit=True):
                property_input = st.text_input("URL or MLS#", placeholder="e.g., 2053078")
                submit = st.form_submit_button("Add Property", use_container_width=True)
                
                if submit and property_input:
                    with st.spinner("Adding property..."):
                        result = add_property(property_input)
                        if result['success']:
                            st.success("✅ Added!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(result['error'])
    
    # Main Content Area
    if page == "📊 Dashboard":
        # Check if auto-refresh should run on app open
        if 'app_loaded' not in st.session_state:
            st.session_state.app_loaded = True
            
            if should_auto_refresh():
                df = get_all_properties()
                if not df.empty:
                    st.info("🔄 Auto-refresh initiated...")
                    result = refresh_all_properties()
                    if result['success']:
                        if result['changes'] > 0:
                            st.success(f"✅ Auto-refresh complete! {result['changes']} status change(s) detected.")
                        else:
                            st.success(f"✅ Auto-refresh complete! All {result['count']} properties up to date.")
                        st.rerun()
        
        st.title("📊 Property Dashboard")
        
        df = get_all_properties()
        
        if df.empty:
            st.info("👋 No properties yet. Use the '➕ Quick Add Property' in the sidebar to get started!")
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
            
            # View Toggle
            col1, col2, col3 = st.columns([1, 1, 4])
            with col1:
                if st.button("📇 Card View", use_container_width=True, 
                           type="primary" if get_setting('view_mode', 'cards') == 'cards' else "secondary"):
                    set_setting('view_mode', 'cards')
                    st.rerun()
            with col2:
                if st.button("📊 Table View", use_container_width=True,
                           type="primary" if get_setting('view_mode', 'cards') == 'table' else "secondary"):
                    set_setting('view_mode', 'table')
                    st.rerun()
            with col3:
                if st.button("🔄 Refresh All Properties", use_container_width=True):
                    result = refresh_all_properties()
                    if result['success']:
                        if result['changes'] > 0:
                            st.success(f"✅ Refreshed {result['count']} properties! {result['changes']} status change(s) detected.")
                            st.balloons()
                        else:
                            st.success(f"✅ All {result['count']} properties up to date!")
                        time.sleep(2)
                        st.rerun()
            
            st.divider()
            
            # Display properties
            view_mode = get_setting('view_mode', 'cards')
            
            if view_mode == 'cards':
                # Card View
                for _, row in df.iterrows():
                    render_property_card(row)
            else:
                # Table View
                display_df = df[[
                    'address', 'status', 'price', 'beds', 'baths', 'sqft',
                    'mls', 'property_type', 'days_on_market', 'year_built',
                    'agent_name', 'agent_phone', 'brokerage', 'last_checked'
                ]].copy()
                
                # Rename columns for better display
                display_df.columns = [
                    'Address', 'Status', 'Price', 'Beds', 'Baths', 'Sq Ft',
                    'MLS#', 'Type', 'Days on Market', 'Year Built',
                    'Agent', 'Phone', 'Brokerage', 'Last Checked'
                ]
                
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Address": st.column_config.TextColumn("Address", width="large"),
                        "Status": st.column_config.TextColumn("Status", width="small"),
                        "Price": st.column_config.TextColumn("Price", width="small"),
                    }
                )
                
                # Action buttons for table view
                st.markdown("### Actions")
                selected_ids = st.multiselect(
                    "Select properties to delete:",
                    options=df['id'].tolist(),
                    format_func=lambda x: df[df['id']==x]['address'].iloc[0] or df[df['id']==x]['input_text'].iloc[0]
                )
                
                if selected_ids:
                    if st.button("🗑️ Delete Selected", type="secondary"):
                        for prop_id in selected_ids:
                            delete_property(prop_id)
                        st.success(f"Deleted {len(selected_ids)} properties!")
                        time.sleep(1)
                        st.rerun()
    
    elif page == "⚙️ Settings":
        st.title("⚙️ Settings")
        
        st.markdown("### Auto-Refresh Configuration")
        
        auto_refresh_enabled = st.toggle(
            "Enable Auto-Refresh on App Open",
            value=get_setting('auto_refresh_enabled', 'true') == 'true',
            help="Automatically refresh all properties when you open the app"
        )
        
        refresh_interval = st.number_input(
            "Refresh Interval (days)",
            min_value=1,
            max_value=30,
            value=int(get_setting('refresh_interval_days', '1')),
            help="How many days between automatic refreshes"
        )
        
        if st.button("💾 Save Settings", type="primary"):
            set_setting('auto_refresh_enabled', 'true' if auto_refresh_enabled else 'false')
            set_setting('refresh_interval_days', str(refresh_interval))
            st.success("✅ Settings saved!")
            time.sleep(1)
            st.rerun()
        
        st.divider()
        
        # Display last refresh info
        last_refresh = get_setting('last_refresh', '')
        if last_refresh:
            try:
                last_refresh_dt = datetime.fromisoformat(last_refresh)
                st.info(f"🕒 Last auto-refresh: {last_refresh_dt.strftime('%Y-%m-%d %I:%M %p')}")
                
                interval_days = int(get_setting('refresh_interval_days', '1'))
                next_refresh = last_refresh_dt + timedelta(days=interval_days)
                st.info(f"⏭️ Next auto-refresh: {next_refresh.strftime('%Y-%m-%d %I:%M %p')}")
            except:
                pass
        
        st.divider()
        
        st.markdown("### Data Management")
        
        df = get_all_properties()
        st.info(f"📊 Total properties in database: {len(df)}")
        
        if st.button("🗑️ Clear All Data", type="secondary"):
            if st.button("⚠️ Confirm Delete All", type="secondary"):
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM properties")
                conn.commit()
                conn.close()
                st.success("All data cleared!")
                time.sleep(1)
                st.rerun()
    
    elif page == "❓ Help":
        st.title("❓ Help & Instructions")
        
        st.markdown("""
        ### 🎯 Getting Started
        
        1. **Add Properties**: Use the "Quick Add Property" form in the sidebar
        2. **Monitor**: View your properties on the Dashboard
        3. **Refresh**: Properties auto-refresh based on your settings
        
        ### 📝 Supported Inputs
        
        - **Full URL**: `https://www.utahrealestate.com/report/2053078`
        - **MLS Number**: `2053078` or `MLS2053078`
        
        ### 🌐 Supported Websites
        
        - ✅ UtahRealEstate.com
        - ✅ Zillow.com
        
        ### 🔄 Auto-Refresh
        
        The app can automatically refresh all properties when you open it:
        
        - Go to **Settings**
        - Enable "Auto-Refresh on App Open"
        - Set your preferred interval (days)
        - Properties will auto-update based on your schedule
        
        ### 💡 Tips
        
        - **Card View**: Best for detailed property information
        - **Table View**: Best for comparing multiple properties
        - **Manual Refresh**: Click 🔄 next to any property for instant updates
        - **Bulk Actions**: Use Table View for multi-select operations
        
        ### 🔒 Privacy
        
        All data is stored locally in your SQLite database (`properties.db`)
        
        ### 📱 Mobile Access
        
        This app works great on mobile! Add it to your home screen for quick access.
        """)

if __name__ == "__main__":
    main()
