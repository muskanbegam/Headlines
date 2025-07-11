from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO)
from pytz import timezone  # Add this at the top
kolkata_tz = timezone('Asia/Kolkata')

#################################
# ── Standard Library ──────────
#################################
import os
import re
from dotenv import load_dotenv
load_dotenv()  # Load .env file
#################################
# ── Third‑Party ───────────────
#################################
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, Float
from flask_apscheduler import APScheduler
from bs4 import BeautifulSoup
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import secrets  # This is the critical missing import
from datetime import timedelta  # Add this import


from dateutil import parser as dtparser          # pip install python-dateutil
from geopy.geocoders import Nominatim            # pip install geopy

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

__version__ = "1.0.0"

#################################
# ── PostgreSQL Config ──────

import os
from urllib.parse import quote_plus

def get_database_uri():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        return "postgresql://postgres:%28muskan%29@localhost:5432/newsight_db"
    
    # Handle Heroku-style postgres:// URLs
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    
    return db_url
    
    # Local development fallback (with URL-encoded password)
    return "postgresql://postgres:%28muskan%29@localhost:5432/newsight_db"

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_timeout': 30
}
# Security Configuration
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))  # Set secret key from env or generate
app.config.update(
    SESSION_COOKIE_SECURE=True,    # Only send cookies over HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Prevent client-side JS cookie access
    SESSION_COOKIE_SAMESITE='Lax', # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(days=1)  # Session expiration
)

# Additional Production Recommendations
if not app.debug:
    app.config.update(
        PREFERRED_URL_SCHEME='https',  # Force HTTPS URLs
        JSONIFY_PRETTYPRINT_REGULAR=False  # Disable pretty print in production
    )


# Initialize extensions
db = SQLAlchemy(app)
#################################
# ── Models ─────────────────
#################################
class Content(db.Model):
    id:         Mapped[int]   = mapped_column(Integer, primary_key=True)
    heading:    Mapped[str]   = mapped_column(String(250), unique=True, nullable=False)
    subheading: Mapped[str]   = mapped_column(String(250), nullable=False)
    content:    Mapped[str]   = mapped_column(String(427), nullable=False)
    link:       Mapped[str]   = mapped_column(String, nullable=False)
    location:   Mapped[str]   = mapped_column(String, nullable=False)
    image:      Mapped[str]   = mapped_column(String, nullable=False)
    latitude:   Mapped[float] = mapped_column(Float)
    longitude:  Mapped[float] = mapped_column(Float)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(kolkata_tz))
    
class Users(db.Model):
    id:       Mapped[int] = mapped_column(Integer, primary_key=True)
    name:     Mapped[str] = mapped_column(String(250), nullable=False)
    email:    Mapped[str] = mapped_column(String, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)


def get_lat_long(place: str) -> tuple[float | None, float | None]:
    if not place or place == "Unknown":
        return None, None
    try:
        geolocator = Nominatim(user_agent="newsight_app", timeout=10)
        loc        = geolocator.geocode(place)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except Exception:
        return None, None


def get_bbc_full_article_content(article_url: str) -> str:
    try:
        article_html = requests.get(article_url, timeout=10).text
        article_soup = BeautifulSoup(article_html, "html.parser")
        article_main = article_soup.find("main")
        if not article_main:
            return "Full article content not found."
        paragraphs = article_main.find_all("p")
        content = " ".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return content if content else "No detailed content available."
    except Exception as e:
        logging.error(f"[BBC scrape error] {e}")
        return "Error fetching full article."

# The scheduled job function
def scheduled_scrape():
    with app.app_context():
        now = datetime.now(kolkata_tz)
        print(f"[{now}] Running scheduled scrape in Kolkata time...")
        
        # List to store all scraped articles before filtering duplicates
        all_articles = []
        
        # 1. Inshorts Scraping - get 5 articles
        url = "https://inshorts.com/en/read"
        try:
            html = requests.get(url, timeout=10).text
            soup = BeautifulSoup(html, "html.parser")

            cards = soup.find_all("div", class_="LUWdd1C_3UqqulVsopn0")
            for card in cards[:5]:  # Get 5 Inshorts articles
                try:
                    bg_div = card.find_previous_sibling("div").find("div", class_="GXPWASMx93K0ajwCIcCA")
                    img_url = "https://via.placeholder.com/300"
                    if bg_div and "style" in bg_div.attrs:
                        m = re.search(r'url\(([^)]+)\)', bg_div["style"])
                        if m:
                            img_url = m.group(1).strip('"').strip("'")

                    heading = card.find("span", class_="ddVzQcwl2yPlFt4fteIE")
                    heading_text = heading.get_text(strip=True) if heading else "Untitled"

                    # Skip if this article already exists
                    if Content.query.filter_by(heading=heading_text).first():
                        continue

                    date_span = card.find("span", class_="date")
                    date = date_span.get_text(strip=True) if date_span else "Unknown date"

                    content = card.find("div", class_="KkupEonoVHxNv4A_D7UG")
                    content_text = content.get_text(strip=True) if content else "No content"

                    source_link = card.find("a", class_="LFn0sRS51HkFD0OHeCdA")
                    external_url = source_link["href"] if source_link and source_link.has_attr("href") else "#"
                    lat, lon = get_lat_long("India")

                    all_articles.append({
                        'source': 'Inshorts',
                        'heading': heading_text,
                        'subheading': date,
                        'content': content_text[:427],
                        'link': external_url,
                        'location': "India",
                        'image': img_url,
                        'latitude': lat,
                        'longitude': lon,
                    })
                except Exception as e:
                    print(f"Error processing Inshorts article: {e}")
                    continue
        except Exception as e:
            print(f"Error fetching Inshorts: {e}")

        # 2. BBC Scraping - get 6 articles
        bbc_url = "https://www.bbc.com/news"
        try:
            bbc_html = requests.get(bbc_url, timeout=10).text
            bbc_soup = BeautifulSoup(bbc_html, "html.parser")
            bbc_cards = bbc_soup.find_all("div", class_="sc-cb78bbba-1 fYSNbR")

            for bbc_card in bbc_cards[:6]:  # Get 6 BBC articles
                try:
                    bbc_img_tag = bbc_card.find("div").find("img", class_="sc-d1200759-0 dvfjxj")
                    bbc_img_url = bbc_img_tag.get("src") if bbc_img_tag else "Image not found"

                    bbc_heading = bbc_card.find("h2", class_="sc-9d830f2a-3 fWzToZ")
                    bbc_heading_text = bbc_heading.get_text(strip=True) if bbc_heading else "Untitled"

                    # Skip if this article already exists
                    if Content.query.filter_by(heading=bbc_heading_text).first():
                        continue

                    bbc_meta_div = bbc_card.find("div", class_="sc-ac6bc755-0 kOnnpG")
                    bbc_date = bbc_meta_div.get_text(separator=" · ", strip=True) if bbc_meta_div else "Unknown metadata"

                    bbc_date_span = bbc_card.find("span", class_="sc-ac6bc755-2 ivCQgh")
                    bbc_loc = bbc_date_span.get_text(strip=True) if bbc_date_span else "Unknown date"

                    anchor_tag = bbc_card.find_parent("a", href=True)
                    bbc_href = anchor_tag['href'] if anchor_tag else ""
                    bbc_external_url = "https://www.bbc.com" + bbc_href if bbc_href.startswith("/") else bbc_href

                    bbc_content_text = get_bbc_full_article_content(bbc_external_url)
                    if len(bbc_content_text) > 424:
                        bbc_content_text = bbc_content_text[:423] + '...'
                    bbc_lat, bbc_lon = get_lat_long(bbc_loc)

                    all_articles.append({
                        'source': 'BBC',
                        'heading': bbc_heading_text,
                        'subheading': bbc_date,
                        'content': bbc_content_text[:427],
                        'link': bbc_external_url,
                        'location': bbc_loc,
                        'image': bbc_img_url,
                        'latitude': bbc_lat,
                        'longitude': bbc_lon,
                    })
                except Exception as e:
                    print(f"Error processing BBC article: {e}")
                    continue
        except Exception as e:
            print(f"Error fetching BBC: {e}")

        # Add ALL articles to database at once
        added_count = 0
        for article in all_articles:
            try:
                # Final duplicate check
                if not Content.query.filter_by(heading=article['heading']).first():
                    db.session.add(Content(
                        heading=article['heading'],
                        subheading=article['subheading'],
                        content=article['content'],
                        link=article['link'],
                        location=article['location'],
                        image=article['image'],
                        latitude=article['latitude'],
                        longitude=article['longitude'],
                        timestamp=datetime.now(kolkata_tz)
                    ))
                    added_count += 1
            except Exception as e:
                db.session.rollback()
                print(f"Error adding article {article['heading']}: {e}")

        try:
            db.session.commit()
            print(f"✅ Added {added_count} new articles ({len(all_articles)} scraped). Scraping finished.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error committing to database: {e}")

        # BBC Scraping - get 6 articles
        bbc_url = "https://www.bbc.com/news"
        bbc_html = requests.get(bbc_url).text
        bbc_soup = BeautifulSoup(bbc_html, "html.parser")
        bbc_cards = bbc_soup.find_all("div", class_="sc-cb78bbba-1 fYSNbR")

        for bbc_card in bbc_cards[:6]:  # Get 6 BBC articles
            try:
                bbc_img_tag = bbc_card.find("div").find("img", class_="sc-d1200759-0 dvfjxj")
                bbc_img_url = bbc_img_tag.get("src") if bbc_img_tag else "Image not found"

                bbc_heading = bbc_card.find("h2", class_="sc-9d830f2a-3 fWzToZ")
                bbc_heading_text = bbc_heading.get_text(strip=True) if bbc_heading else "Untitled"

                # Skip if this article already exists
                if Content.query.filter_by(heading=bbc_heading_text).first():
                    continue

                bbc_meta_div = bbc_card.find("div", class_="sc-ac6bc755-0 kOnnpG")
                bbc_date = bbc_meta_div.get_text(separator=" · ", strip=True) if bbc_meta_div else "Unknown metadata"

                bbc_date_span = bbc_card.find("span", class_="sc-ac6bc755-2 ivCQgh")
                bbc_loc = bbc_date_span.get_text(strip=True) if bbc_date_span else "Unknown date"

                anchor_tag = bbc_card.find_parent("a", href=True)
                bbc_href = anchor_tag['href'] if anchor_tag else ""
                bbc_external_url = "https://www.bbc.com" + bbc_href if bbc_href.startswith("/") else bbc_href

                bbc_content_text = get_bbc_full_article_content(bbc_external_url)
                if len(bbc_content_text) > 424:
                    bbc_content_text = bbc_content_text[:423] + '...'
                bbc_lat, bbc_lon = get_lat_long(bbc_loc)

                all_articles.append({
                    'source': 'BBC',
                    'heading': bbc_heading_text,
                    'subheading': bbc_date,
                    'content': bbc_content_text[:427],
                    'link': bbc_external_url,
                    'location': bbc_loc,
                    'image': bbc_img_url,
                    'latitude': bbc_lat,
                    'longitude': bbc_lon,
                })
            except Exception as e:
                print(f"Error processing BBC article: {e}")
                continue

        
        try:
            db.session.commit()
            print(f"✅ Added {added_count} new articles. Scraping finished.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error committing to database: {e}")

# Initialize APScheduler
scheduler = APScheduler()
scheduler.init_app(app)

scheduler.add_job(
    id='news_scraping_job',
    func=scheduled_scrape,
    trigger='cron',
    hour=16,  # 10 AM Kolkata time
    minute=40   ,
    timezone=kolkata_tz  # Explicitly set timezone
)

# Start the scheduler
scheduler.start()
#################################
# ── Routes ────────────────
#################################
@app.route("/")
def home():
    content_db = Content.query.order_by(Content.timestamp.desc()).all()
    return render_template("index.html", data=content_db, length=len(content_db), so=0)

@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        if request.method == "POST":
            email    = request.form.get("email")
            password = request.form.get("password")
            if email == "admin@gmail.com" and password == "(Adminnewsight.1)":
                # DEBUG LOGGING
                print("Admin login triggered.")
                content_db = Content.query.all()  # 🔥 likely causing crash
                print("Fetched content:", content_db)
                return render_template("admin-dashboard.html", data=content_db, length=len(content_db))
            user = Users.query.filter_by(email=email).first()
            if user and user.password == password:
                return redirect(url_for("logged_in", so=1))
            return render_template("login.html", error="Invalid credentials.")
        return render_template("login.html")
    except Exception as e:
        print("💥 ERROR:", e)
        return f"Server Error: {e}"
     

@app.route("/loggedIn/<int:so>")
def logged_in(so: int):
    content_db = Content.query.all()
    return render_template("index.html", so=so, data=content_db, length=len(content_db)) if so == 1 else redirect(url_for("home"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name     = request.form.get("name")
        email    = request.form.get("email")
        password = request.form.get("password")
        db.session.add(Users(name=name, email=email, password=password))
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route('/new-post', methods=["GET", "POST"])
def new_post():
    if request.method == "POST":
        image         = request.form.get("image")
        heading       = request.form.get("heading")
        subheading    = request.form.get("subheading")
        content_text  = request.form.get("content")
        link          = request.form.get("link")
        location_name = request.form.get("location")
        lat, lon      = get_lat_long(location_name)

        db.session.add(Content(
            heading     = heading,
            subheading  = subheading,
            content     = content_text[:427],
            link        = link,
            location    = location_name,
            image       = image,
            latitude    = lat,
            longitude   = lon,
        ))
        db.session.commit()
        return redirect(url_for("home"))

    return render_template("new-post.html")

@app.route("/delete/<int:item_id>")
def delete(item_id: int):
    row = db.session.get(Content, item_id)
    if row:
        db.session.delete(row)
        db.session.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin-dashboard")
def admin_dashboard():
    content_db = Content.query.all()
    return render_template("admin-dashboard.html", data=content_db, length=len(content_db))

if __name__ == "__main__":
    print("👋 STARTING MAIN")
    
        # After db = SQLAlchemy(app)
    with app.app_context():
        try:
            print("⏳ Creating database tables...")
            db.create_all()
            print("✅ Database tables created successfully")
        except Exception as e:
            print(f"❌ Error creating tables: {str(e)}")
            # Fallback to SQLite if PostgreSQL fails
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fallback.db'
            db.create_all()
            print("⚠️ Using SQLite fallback database")

    # Start Flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)