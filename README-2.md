# 🏠 Utah Real Estate Property Monitor

A simple web-based tool to monitor property listings from UtahRealEstate.com and Zillow.com

## ✨ Features

- 📊 Track multiple properties in one dashboard
- 🔄 Automatically refresh property data
- 📱 Mobile-friendly web interface
- 💾 Local database storage (SQLite)
- 🎯 Support for MLS numbers and direct URLs
- 📧 Track status changes (For Sale → Pending → Sold)

## 🚀 Quick Deploy (FREE!)

### Step 1: Push to GitHub

1. Create a new repository on GitHub
2. Upload these 3 files:
   - `property_monitor_app.py`
   - `requirements.txt`
   - `README.md` (this file)

### Step 2: Deploy to Streamlit Cloud (100% Free)

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Sign in with your GitHub account
3. Click "New app"
4. Select:
   - **Repository**: Your repo name
   - **Branch**: `main`
   - **Main file path**: `property_monitor_app.py`
5. Click "Deploy"
6. Wait 2-3 minutes ☕
7. Done! Your app is live with a URL like: `your-app-name.streamlit.app`

## 💻 Run Locally (Optional)

If you want to test locally before deploying:

```bash
# Install Python 3.8+ if you don't have it
# Then run:

pip install -r requirements.txt
streamlit run property_monitor_app.py
```

The app will open in your browser at `http://localhost:8501`

## 📖 How to Use

### Adding Properties

1. Click **"Add Property"** in the sidebar
2. Enter one of:
   - Full URL: `https://www.utahrealestate.com/report/2053078`
   - MLS Number: `2053078` or `MLS2053078`
3. Click "Add Property"

### Monitoring Properties

- View all properties on the **Dashboard**
- Click 🔄 to refresh individual properties
- Click 🗑️ to delete properties
- Use **"Refresh All"** to update everything at once

## 🌐 Supported Websites

- ✅ UtahRealEstate.com
- ✅ Zillow.com

## ⚠️ Important Notes

- **Rate Limiting**: Wait 2 seconds between refreshes to avoid being blocked
- **Data Storage**: All data is stored in `properties.db` (SQLite database)
- **Free Tier**: Streamlit Cloud free tier is perfect for personal use

## 🔧 Troubleshooting

**Problem**: "HTTP 403" or "Page not accessible"
- **Solution**: The website may be blocking automated requests. Try again in a few minutes.

**Problem**: App says "Property not found"
- **Solution**: Check that the URL is correct and the listing is still active

**Problem**: Missing data fields
- **Solution**: Some properties may not have all data available (agent info, photos, etc.)

## 📊 Database

Your data is stored in `properties.db` (SQLite). To backup:
1. Go to Streamlit Cloud → App Settings → Secrets
2. Download `properties.db` periodically

## 🆘 Need Help?

- Check the **Help** page in the app
- Review error messages in the "Notes" column
- Try refreshing individual properties instead of all at once

## 📝 License

Free to use for personal and commercial projects.

## 🎉 Tips for Success

1. **Start Small**: Add 2-3 properties first to test
2. **Regular Refreshes**: Check properties daily or weekly
3. **Bookmark Your App**: Save the Streamlit Cloud URL
4. **Mobile Access**: Works great on phones/tablets!

---

**Built with** ❤️ **using Streamlit**
