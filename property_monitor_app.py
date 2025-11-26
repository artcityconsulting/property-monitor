"""
Utah Real Estate Property Monitor - Streamlit App
A simple web-based property monitoring tool
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time
import re
import sqlite3
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Page configuration
st.set_page_config(
    page_title="Utah Real Estate Monitor",
    page_icon="🏠",
    layout="wide"
)

# Database setup
DB_PATH = Path("properties.db")

def init_database():
    """Initialize SQLite database"""
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

# Initialize database on app start
init_database()

# Configuration
CONFIG = {
    'UTAH_URL_PATTERN': 'https://www.utahrealestate.com/report/',
    'ZILLOW_URL_PATTERN': 'https://www.zillow.com/homedetails/',
    'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Helper Functions
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
    
    # Already a URL
    if input_text.startswith('http://') or input_text.startswith('https://'):
        source = detect_source(input_text)
        if source:
            return {'success': True, 'url': input_text, 'source': source}
        else:
            return {'success': False, 'error': 'Unsupported website. Use UtahRealEstate.com or Zillow.com'}
    
    # MLS number
    mls_match = re.match(r'^(MLS)?(\d{6,10})$', input_text, re.IGNORECASE)
    if mls_match:
        mls_number = mls_match.group(2)
        return {
            'success': True,
            'url': CONFIG['UTAH_URL_PATTERN'] + mls_number,
            'source': 'UtahRealEstate.com'
        }
    
    # Address (needs manual lookup)
    if re.match(r'\d+.*[a-zA-Z].*,', input_text):
        return {
            'success': False,
            'error': 'Address detected. Please find the property URL manually and paste it here.'
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
        # Extract price
        price_match = re.search(r'\$?([1-9]\d{2}(?:,?\d{3}){1,2}(?:,\d{3})?)', html)
        if price_match:
            result['price'] = '$' + price_match.group(1).strip()
        
        # Extract address
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
        
        # Extract agent name
        name_link_match = re.search(
            r'<a[^>]*href=["\']\/roster\/agent\.listings\.report\.public\/agentid\/\d+[^>]*>([^<]+)</a>',
            html,
            re.IGNORECASE
        )
        if name_link_match:
            result['agentName'] = name_link_match.group(1).strip()
        
        # Extract agent photo
        photo_match = re.search(
            r'<img[^>]*src=["\'](https:\/\/webdrive\.utahrealestate\.com\/[^\s"\']+?\.jpg)["\'][^>]*alt=["\'](?:[^"\']+?)["\']',
            html,
            re.IGNORECASE
        )
        if photo_match:
            result['agentPhoto'] = photo_match.group(1).strip()
        
        # Extract agent phone
        contact_section_match = re.search(
            r'<h2>Contact Agent</h2>([\s\S]*?)<div[^>]*class=["\'][^"\']*broker-overview-table',
            html,
            re.IGNORECASE
        )
        if contact_section_match:
            phone_match = re.search(r'(\d{3}[-\s]?\d{3}[-\s]?\d{4})', contact_section_match.group(1))
            if phone_match:
                result['agentPhone'] = phone_match.group(1).strip()
        
        # Extract agent email
        email_match = re.search(r'<a[^>]*href=["\']mailto:([^"\']+)["\'][^>]*>', html, re.IGNORECASE)
        if email_match:
            result['agentEmail'] = email_match.group(1).strip()
        
        # Extract brokerage
        brokerage_match = re.search(
            r'<div[^>]*class=["\'][^"\']*broker-overview-content[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            html,
            re.IGNORECASE
        )
        if brokerage_match:
            strong_match = re.search(r'<strong>([^<]+)</strong>', brokerage_match.group(1), re.IGNORECASE)
            if strong_match:
                result['brokerage'] = strong_match.group(1).strip()
        
        # Extract facts
        facts = {}
        facts_matches = re.finditer(
            r'<span[^>]*class=["\'][^"\']*facts-header[^"\']*["\'][^>]*>(.*?)</span>\s*["\']?([^"\'<]+)["\']?',
            html,
            re.IGNORECASE
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
        
        # Extract beds/baths/sqft
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
        # Extract status
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
        
        # Extract price
        price_patterns = [
            r'<span[^>]*data-testid=["\']price["\'][^>]*>\$?([0-9,]+)',
            r'"price"\s*:\s*([0-9]+)'
        ]
        for pattern in price_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['price'] = '$' + match.group(1)
                break
        
        # Extract beds/baths/sqft
        beds_match = re.search(r'"bedrooms"\s*:\s*(\d+)', html, re.IGNORECASE)
        if beds_match:
            result['beds'] = beds_match.group(1)
        
        baths_match = re.search(r'"bathrooms"\s*:\s*([\d.]+)', html, re.IGNORECASE)
        if baths_match:
            result['baths'] = baths_match.group(1)
        
        sqft_match = re.search(r'"livingArea"\s*:\s*([0-9,]+)', html, re.IGNORECASE)
        if sqft_match:
            result['sqft'] = sqft_match.group(1)
        
        # Extract address
        address_patterns = [
            r'<h1[^>]*>([^<]+)</h1>',
            r'"address"\s*:\s*"([^"]+)"'
        ]
        for pattern in address_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                result['address'] = match.group(1).strip()
                break
        
        # Extract other details
        year_match = re.search(r'"yearBuilt"\s*:\s*(\d{4})', html, re.IGNORECASE)
        if year_match:
            result['yearBuilt'] = year_match.group(1)
        
        mls_match = re.search(r'MLS[#\s]*:?\s*([A-Z0-9\-]+)', html, re.IGNORECASE)
        if mls_match:
            result['mls'] = mls_match.group(1)
        
        type_match = re.search(r'"homeType"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
        if type_match:
            result['type'] = type_match.group(1)
        
        # Extract agent info
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
            return {'success': False, 'error': f'HTTP {response.status_code} - Page not accessible'}
        
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

# Database Functions
def add_property(input_text):
    """Add a property to the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Convert input to URL
    url_info = convert_input_to_url(input_text)
    
    if not url_info['success']:
        conn.close()
        return {'success': False, 'error': url_info['error']}
    
    # Scrape property
    scraped_data = scrape_property(url_info['url'], url_info['source'])
    
    if not scraped_data['success']:
        conn.close()
        return {'success': False, 'error': scraped_data['error']}
    
    # Insert into database
    cursor.execute("""
        INSERT INTO properties (
            input_text, source, status, price, beds, baths, sqft,
            resolved_url, address, mls, days_on_market, year_built,
            property_type, agent_name, agent_photo, agent_phone, agent_email,
            brokerage, features, last_checked, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        input_text,
        url_info['source'],
        scraped_data['status'],
        scraped_data['price'],
        scraped_data['beds'],
        scraped_data['baths'],
        scraped_data['sqft'],
        url_info['url'],
        scraped_data['address'],
        scraped_data['mls'],
        scraped_data['daysOnMarket'],
        scraped_data['yearBuilt'],
        scraped_data['type'],
        scraped_data['agentName'],
        scraped_data['agentPhoto'],
        scraped_data['agentPhone'],
        scraped_data['agentEmail'],
        scraped_data['brokerage'],
        scraped_data['features'],
        datetime.now(),
        'Success'
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
    
    # Get current property
    cursor.execute("SELECT input_text, status FROM properties WHERE id = ?", (property_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {'success': False, 'error': 'Property not found'}
    
    input_text, old_status = row
    
    # Convert and scrape
    url_info = convert_input_to_url(input_text)
    if not url_info['success']:
        conn.close()
        return {'success': False, 'error': url_info['error']}
    
    scraped_data = scrape_property(url_info['url'], url_info['source'])
    if not scraped_data['success']:
        conn.close()
        return {'success': False, 'error': scraped_data['error']}
    
    # Check for status change
    status_changed = old_status != scraped_data['status']
    
    # Update database
    cursor.execute("""
        UPDATE properties SET
            source = ?,
            status = ?,
            price = ?,
            beds = ?,
            baths = ?,
            sqft = ?,
            resolved_url = ?,
            address = ?,
            mls = ?,
            days_on_market = ?,
            year_built = ?,
            property_type = ?,
            agent_name = ?,
            agent_photo = ?,
            agent_phone = ?,
            agent_email = ?,
            brokerage = ?,
            features = ?,
            last_checked = ?,
            last_changed = CASE WHEN ? THEN ? ELSE last_changed END,
            previous_status = CASE WHEN ? THEN ? ELSE previous_status END,
            notes = ?
        WHERE id = ?
    """, (
        url_info['source'],
        scraped_data['status'],
        scraped_data['price'],
        scraped_data['beds'],
        scraped_data['baths'],
        scraped_data['sqft'],
        url_info['url'],
        scraped_data['address'],
        scraped_data['mls'],
        scraped_data['daysOnMarket'],
        scraped_data['yearBuilt'],
        scraped_data['type'],
        scraped_data['agentName'],
        scraped_data['agentPhoto'],
        scraped_data['agentPhone'],
        scraped_data['agentEmail'],
        scraped_data['brokerage'],
        scraped_data['features'],
        datetime.now(),
        status_changed,
        datetime.now() if status_changed else None,
        status_changed,
        old_status if status_changed else None,
        'Success',
        property_id
    ))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'status_changed': status_changed}

# Streamlit UI
def main():
    st.title("🏠 Utah Real Estate Property Monitor")
    st.markdown("Monitor property listings from UtahRealEstate.com and Zillow.com")
    
    # Sidebar
    with st.sidebar:
        st.header("📋 Menu")
        page = st.radio("Navigate", ["Dashboard", "Add Property", "Refresh All", "Help"])
    
    # Dashboard
    if page == "Dashboard":
        st.header("📊 Property Dashboard")
        
        df = get_all_properties()
        
        if df.empty:
            st.info("No properties yet. Add your first property using the sidebar!")
        else:
            # Display summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Properties", len(df))
            with col2:
                for_sale = len(df[df['status'] == 'For Sale'])
                st.metric("For Sale", for_sale)
            with col3:
                pending = len(df[df['status'] == 'Pending'])
                st.metric("Pending", pending)
            with col4:
                sold = len(df[df['status'] == 'Sold'])
                st.metric("Sold", sold)
            
            st.divider()
            
            # Display properties
            for _, row in df.iterrows():
                with st.expander(f"{row['address'] or row['input_text']} - {row['status']}"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown(f"**Price:** {row['price']}")
                        st.markdown(f"**Address:** {row['address']}")
                        st.markdown(f"**Beds/Baths:** {row['beds']} bed, {row['baths']} bath")
                        st.markdown(f"**Sq Ft:** {row['sqft']}")
                        st.markdown(f"**MLS#:** {row['mls']}")
                        st.markdown(f"**Type:** {row['property_type']}")
                        st.markdown(f"**Year Built:** {row['year_built']}")
                        st.markdown(f"**Days on Market:** {row['days_on_market']}")
                        
                        if row['agent_name']:
                            st.markdown(f"**Agent:** {row['agent_name']}")
                            if row['agent_phone']:
                                st.markdown(f"**Phone:** {row['agent_phone']}")
                            if row['agent_email']:
                                st.markdown(f"**Email:** {row['agent_email']}")
                        
                        if row['brokerage']:
                            st.markdown(f"**Brokerage:** {row['brokerage']}")
                        
                        if row['features']:
                            st.markdown(f"**Features:** {row['features']}")
                        
                        st.markdown(f"**Source:** {row['source']}")
                        st.markdown(f"**Last Checked:** {row['last_checked']}")
                        
                        if row['resolved_url']:
                            st.markdown(f"[View Listing]({row['resolved_url']})")
                    
                    with col2:
                        if st.button("🔄 Refresh", key=f"refresh_{row['id']}"):
                            with st.spinner("Refreshing..."):
                                result = refresh_property(row['id'])
                                if result['success']:
                                    if result['status_changed']:
                                        st.success("✅ Updated! Status changed.")
                                    else:
                                        st.success("✅ Updated!")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {result['error']}")
                        
                        if st.button("🗑️ Delete", key=f"delete_{row['id']}"):
                            delete_property(row['id'])
                            st.success("Deleted!")
                            st.rerun()
    
    # Add Property
    elif page == "Add Property":
        st.header("➕ Add New Property")
        
        st.markdown("""
        Enter one of the following:
        - **Full URL**: `https://www.utahrealestate.com/report/12345`
        - **MLS Number**: `12345` or `MLS12345`
        
        _Note: Addresses require manual URL lookup_
        """)
        
        input_text = st.text_input("Property URL or MLS#")
        
        if st.button("Add Property"):
            if not input_text:
                st.error("Please enter a URL or MLS#")
            else:
                with st.spinner("Fetching property data..."):
                    result = add_property(input_text)
                    
                    if result['success']:
                        st.success("✅ Property added successfully!")
                        st.balloons()
                        
                        # Show preview
                        data = result['data']
                        st.markdown(f"**Address:** {data['address']}")
                        st.markdown(f"**Price:** {data['price']}")
                        st.markdown(f"**Status:** {data['status']}")
                        st.markdown(f"**Beds/Baths:** {data['beds']} bed, {data['baths']} bath")
                        
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"❌ Error: {result['error']}")
    
    # Refresh All
    elif page == "Refresh All":
        st.header("🔄 Refresh All Properties")
        
        df = get_all_properties()
        
        if df.empty:
            st.info("No properties to refresh")
        else:
            st.warning(f"This will refresh all {len(df)} properties. This may take a few minutes.")
            
            if st.button("Start Refresh"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, row in df.iterrows():
                    status_text.text(f"Refreshing {idx + 1}/{len(df)}: {row['address'] or row['input_text']}")
                    refresh_property(row['id'])
                    progress_bar.progress((idx + 1) / len(df))
                    time.sleep(2)  # Rate limiting
                
                status_text.text("✅ All properties refreshed!")
                st.success("Refresh complete!")
                time.sleep(2)
                st.rerun()
    
    # Help
    elif page == "Help":
        st.header("❓ Help & Instructions")
        
        st.markdown("""
        ### 🎯 Getting Started
        1. Click **Add Property** in the sidebar
        2. Enter a property URL or MLS number
        3. View your properties on the **Dashboard**
        4. Use **Refresh All** to update all properties
        
        ### 📝 Supported Inputs
        - **Full URL**: `https://www.utahrealestate.com/report/2053078`
        - **MLS Number**: `2053078` or `MLS2053078`
        
        ### 🌐 Supported Websites
        - UtahRealEstate.com
        - Zillow.com
        
        ### 💡 Tips
        - Refresh properties regularly to track status changes
        - Use the Refresh button on individual properties for quick updates
        - Check "Last Checked" to see when data was updated
        
        ### 🔒 Privacy
        All data is stored locally in your SQLite database (`properties.db`)
        """)

if __name__ == "__main__":
    main()
