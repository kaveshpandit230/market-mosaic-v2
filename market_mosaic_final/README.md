# Market Mosaic — Flask Marketing SaaS

A full-featured marketing agency website + client dashboard built with Flask and SQLite.

---

## Features

### Public Website
- Home, About, Services, Pricing, Contact pages
- Blog with 3 starter articles
- Elegant light/minimal design (Cormorant Garamond + DM Sans)

### Auth System
- Sign up / Login / Logout
- Password reset via email (configure Flask-Mail)
- Session-based authentication
- API key generation per user

### Marketing Dashboard
| Section | Features |
|---|---|
| **Overview** | KPI cards, recent campaigns & leads |
| **Campaigns** | Create, edit, delete, filter by status, export CSV |
| **Leads** | Create, edit, delete, search, filter by status/source, export CSV |
| **Analytics** | 6 Chart.js charts (clicks, impressions, spend, conversions, lead source/status) |
| **Reports** | Print-ready performance summary with bar charts |
| **Proposals** | Live proposal builder with line items, print to PDF |
| **Email Templates** | 6 ready-to-use client email templates with copy button |
| **Notifications** | In-app activity feed |
| **Settings** | Profile, password change, API key management |

### Admin Panel (`/admin`)
- View all users, promote/demote admin, delete users

### REST API
```
GET /api/v1/campaigns   — returns all campaigns as JSON
GET /api/v1/leads       — returns all leads as JSON
GET /api/v1/stats       — returns summary stats
```
Pass API key as `X-API-Key` header or `?api_key=` query param.

---

## Local Development

```bash
# 1. Clone / unzip the project
cd market_mosaic

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install flask werkzeug

# 4. Set environment variable
export SECRET_KEY="your-long-random-secret"   # Windows: set SECRET_KEY=...

# 5. Run
python app.py
```

Open http://localhost:5000 — sign up for an account and demo data is seeded automatically.

---

## Deploy to GoDaddy (cPanel Shared Hosting)

### Step 1 — Upload files
- Log into cPanel → File Manager
- Upload and unzip `market_mosaic.zip` to `public_html/` or a subdirectory

### Step 2 — Set up Python App
- cPanel → **Setup Python App**
- Python version: **3.x** (choose highest available)
- Application root: `market_mosaic` (relative to home)
- Application URL: `/` (or subdomain)
- Application startup file: `passenger_wsgi.py`
- Application Entry point: `application`
- Click **Create**

### Step 3 — Install dependencies
- In the Python App panel, click **Open Terminal** (or SSH in)
```bash
cd ~/market_mosaic
source ../virtualenv/market_mosaic/3.x/bin/activate
pip install flask werkzeug
```

### Step 4 — Set environment variable
- In cPanel Python App → Environment Variables
- Add: `SECRET_KEY` = (a long random string)
- Generate one: `python -c "import secrets; print(secrets.token_hex(32))"`

### Step 5 — Restart
- Click **Restart** in the Python App panel
- Visit your domain — the app should be live

### Troubleshooting
- Check **Error Logs** in cPanel if the app doesn't load
- Make sure `passenger_wsgi.py` is in the app root
- Database (`market_mosaic.db`) is created automatically on first run
- If you see a permissions error on the DB, set it to 644: `chmod 644 market_mosaic.db`

---

## Adding Email (Password Reset)

1. Uncomment `Flask-Mail==0.9.1` in `requirements.txt` and `pip install flask-mail`
2. Add to `app.py`:
```python
from flask_mail import Mail, Message
app.config.update(
    MAIL_SERVER=os.environ.get('MAIL_SERVER','smtp.gmail.com'),
    MAIL_PORT=587, MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
)
mail = Mail(app)
```
3. In the `forgot_password` route, replace the flash with:
```python
msg = Message('Reset your password', recipients=[email])
msg.body = f'Click to reset: {reset_url}'
mail.send(msg)
```

---

## Making Yourself Admin

After signing up, run this in the Python console or SSH:
```bash
cd ~/market_mosaic
python3 -c "
import sqlite3
db = sqlite3.connect('market_mosaic.db')
db.execute(\"UPDATE users SET is_admin=1 WHERE email='your@email.com'\")
db.commit()
print('Done')
"
```
Then visit `/admin` while logged in.

---

## File Structure

```
market_mosaic/
├── app.py                  — Main Flask application (729 lines)
├── passenger_wsgi.py       — GoDaddy cPanel entry point
├── requirements.txt        — Python dependencies
├── .env.example            — Environment variable template
├── market_mosaic.db        — SQLite database (auto-created)
└── templates/
    ├── base.html           — Public site base layout + nav
    ├── dash_base.html      — Dashboard layout with sidebar
    ├── home.html           — Landing page
    ├── about.html
    ├── services.html
    ├── pricing.html
    ├── contact.html
    ├── blog.html / blog_post.html
    ├── signup.html / login.html
    ├── forgot_password.html / reset_password.html
    ├── dashboard.html      — Overview
    ├── campaigns.html / new_campaign.html / edit_campaign.html
    ├── leads.html / new_lead.html / edit_lead.html
    ├── analytics.html
    ├── reports.html
    ├── proposals.html
    ├── email_templates.html
    ├── notifications.html
    ├── settings.html
    ├── admin.html
    ├── 404.html / 500.html
```

---

## Built With
- **Flask** — Python web framework
- **SQLite** — Database (zero config, file-based)
- **Chart.js** — Analytics charts
- **Cormorant Garamond + DM Sans** — Typography
- **Vanilla CSS + JS** — No frontend framework needed

---

*Built by Market Mosaic · hello@marketmosaic.in*
