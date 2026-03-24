from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os, json, secrets, csv, io
import psycopg2, psycopg2.extras
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production-please')
GOOGLE_CLIENT_ID=os.environ.get('GOOGLE_CLIENT_ID','')
GOOGLE_CLIENT_SECRET=os.environ.get('GOOGLE_CLIENT_SECRET','')
GOOGLE_REDIRECT_URI=os.environ.get('GOOGLE_REDIRECT_URI','https://market-mosaic-v2.onrender.com/auth/google/callback')
DATABASE_URL=os.environ.get('DATABASE_URL','')
class PGConn:
    def __init__(self): self.conn=psycopg2.connect(DATABASE_URL,cursor_factory=psycopg2.extras.RealDictCursor)
    def execute(self,sql,p=None):
        c=self.conn.cursor(); c.execute(sql,p or ()); return PGCursor(c)
    def executemany(self,sql,data):
        c=self.conn.cursor()
        [c.execute(sql,r) for r in data]; c.close()
    def __enter__(self): return self
    def __exit__(self,et,ev,tb): (self.conn.rollback if et else self.conn.commit)(); self.conn.close()
class PGCursor:
    def __init__(self,c): self.cur=c
    def fetchone(self):
        r=self.cur.fetchone()
        return ScalarRow(dict(r)) if r else ScalarRow(None)
    def fetchall(self): return [dict(r) for r in self.cur.fetchall()]
    def __iter__(self): return iter(self.fetchall())
class ScalarRow:
    def __init__(self,d): self.data=d or {}
    def __getitem__(self,k): return (list(self.data.values())[k] if self.data else None) if isinstance(k,int) else self.data.get(k)
    def __bool__(self): return bool(self.data)
    def get(self,k,d=None): return self.data.get(k,d) if self.data else d
    def keys(self): return self.data.keys()
    def values(self): return self.data.values()
    def items(self): return self.data.items()
def get_db(): return PGConn()

def init_db():
    _T=['CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY,name TEXT NOT NULL,company TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,plan TEXT DEFAULT \'free\',is_admin INTEGER DEFAULT 0,api_key TEXT UNIQUE,phone TEXT,notif_app INTEGER DEFAULT 1,notif_whatsapp INTEGER DEFAULT 0,notif_sms INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)','CREATE TABLE IF NOT EXISTS campaigns (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,channel TEXT NOT NULL,status TEXT DEFAULT \'draft\',budget REAL DEFAULT 0,spent REAL DEFAULT 0,impressions INTEGER DEFAULT 0,clicks INTEGER DEFAULT 0,conversions INTEGER DEFAULT 0,notes TEXT DEFAULT \'\',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS leads (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,company TEXT,phone TEXT,status TEXT DEFAULT \'new\',source TEXT DEFAULT \'organic\',notes TEXT DEFAULT \'\',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS password_resets (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,expires_at TIMESTAMP NOT NULL,used INTEGER DEFAULT 0,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS notifications (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,message TEXT NOT NULL,read INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS payments (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,order_id TEXT,payment_id TEXT,plan TEXT NOT NULL,amount REAL DEFAULT 0,status TEXT DEFAULT \'pending\',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS contacts (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,email TEXT,phone TEXT,company TEXT,title TEXT,source TEXT DEFAULT \'manual\',stage TEXT DEFAULT \'lead\',owner TEXT,tags TEXT DEFAULT \'\',notes TEXT DEFAULT \'\',last_contacted TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS deals (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,title TEXT NOT NULL,contact_id INTEGER,value REAL DEFAULT 0,stage TEXT DEFAULT \'prospecting\',probability INTEGER DEFAULT 10,close_date TEXT,owner TEXT,notes TEXT DEFAULT \'\',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS activities (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,contact_id INTEGER,deal_id INTEGER,type TEXT NOT NULL,subject TEXT NOT NULL,notes TEXT DEFAULT \'\',due_date TEXT,completed INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,title TEXT NOT NULL,related_to TEXT DEFAULT \'\',due_date TEXT,priority TEXT DEFAULT \'medium\',status TEXT DEFAULT \'open\',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS clients (id SERIAL PRIMARY KEY,agency_user_id INTEGER NOT NULL,name TEXT NOT NULL,company TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (agency_user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS email_templates (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,subject TEXT NOT NULL,body_html TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)','CREATE TABLE IF NOT EXISTS sent_emails (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL,to_email TEXT NOT NULL,to_name TEXT DEFAULT \'\',subject TEXT NOT NULL,template_name TEXT DEFAULT \'\',status TEXT DEFAULT \'simulated\',error TEXT DEFAULT \'\',sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)']
    with get_db() as db:
        c=db.conn.cursor()
        [c.execute(s) for s in _T]
        db.conn.commit(); c.close()

init_db()

# ── HELPERS ───────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session:
            flash('Please log in.', 'error'); return redirect(url_for('login'))
        return f(*a, **kw)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session: return redirect(url_for('login'))
        u = get_current_user()
        if not u or not u['is_admin']:
            flash('Access denied.', 'error'); return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return d

def get_current_user():
    if 'user_id' in session:
        with get_db() as db:
            u=db.execute('SELECT * FROM users WHERE id=%s',(session['user_id'],)).fetchone()
            if not u: session.clear()
            return u
    return None

def add_notification(uid, msg):
    with get_db() as db:
        db.execute('INSERT INTO notifications (user_id,message) VALUES (%s,%s)', (uid, msg))

def unread(uid):
    with get_db() as db:
        r=db.execute('SELECT COUNT(*) FROM notifications WHERE user_id=%s AND read=0',(uid,)).fetchone()
        return r[0] if r else 0

def api_auth():
    key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if not key: return None
    with get_db() as db:
        return db.execute('SELECT * FROM users WHERE api_key=%s', (key,)).fetchone()

# ── PUBLIC ────────────────────────────────────────────────
@app.route('/')
def home(): return render_template('home.html', user=get_current_user())

@app.route('/about')
def about(): return render_template('about.html', user=get_current_user())

@app.route('/services')
def services(): return render_template('services.html', user=get_current_user())

@app.route('/pricing')
def pricing(): return render_template('pricing.html', user=get_current_user())

@app.route('/contact', methods=['GET','POST'])
def contact():
    if request.method == 'POST':
        flash("Thanks! We'll be in touch within 24 hours.", 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html', user=get_current_user())

# ── BLOG ──────────────────────────────────────────────────
BLOG_POSTS = [
    {'slug':'brand-identity-india-2026','title':'What Makes a Brand Identity Work in India in 2026',
     'tag':'Brand Strategy','date':'March 10, 2026','author':'Saira Mehta',
     'excerpt':'Indian consumers are more brand-literate than ever. Here is what separates the brands that stick from the ones that fade.',
     'icon':'◎','bg':'linear-gradient(135deg,#f0ebe2,#e0d5c4)',
     'content':'''<p>India's brand landscape has shifted dramatically. A decade ago, a recognisable logo and a catchy jingle were enough. Today, consumers expect authenticity, visual coherence, and a brand that reflects their values.</p>
<h2>The Trust Deficit</h2><p>Indian consumers distrust advertising at higher rates than global counterparts. The brands that win lead with proof: customer stories, transparent sourcing, and consistent delivery.</p>
<blockquote>A brand is not what you say it is. It is what your customers say when you are not in the room.</blockquote>
<h2>Visual Identity That Travels</h2><p>With mobile-first consumption the norm, brand identities must work at thumbnail size and on a billboard alike. Complexity is the enemy.</p>
<h3>What to prioritise:</h3><ul><li>A wordmark that reads clearly at 32px</li><li>A colour palette of no more than three colours</li><li>Typography that is distinctive without being illegible</li></ul>
<p>At Market Mosaic, every brand identity engagement begins with a positioning workshop before a single pixel is placed.</p>'''},
    {'slug':'digital-marketing-roi-smes','title':'How Indian SMEs Can Get Real ROI from Digital Marketing',
     'tag':'Digital Marketing','date':'February 22, 2026','author':'Rohan Kapoor',
     'excerpt':'Most small businesses waste their digital marketing budgets. Here is the framework we use to turn Rs 1 into Rs 5.',
     'icon':'△','bg':'linear-gradient(135deg,#e8e4dd,#d8cfc2)',
     'content':'''<p>Digital marketing promises are seductive. The reality for most Indian SMEs is far messier — scattered spend, unclear attribution, and agencies that report vanity metrics instead of revenue.</p>
<h2>The Three Mistakes SMEs Make</h2>
<h3>1. Channels before customers</h3><p>The first question should never be "should we run Instagram ads%s" It should be "where does our customer spend their attention%s"</p>
<h3>2. Awareness and conversion as one campaign</h3><p>A first-time visitor and a returning prospect need fundamentally different messages.</p>
<h3>3. Measuring clicks instead of cash</h3><p>Revenue is the metric. Build reporting around spend-to-sale, not spend-to-engagement.</p>
<blockquote>If you cannot draw a line from your marketing activity to a business outcome, you have activity — not strategy.</blockquote>
<ul><li>Fix your conversion rate before scaling spend</li><li>Start with retargeting before prospecting</li><li>Run campaigns for at least 90 days before drawing conclusions</li></ul>'''},
    {'slug':'content-marketing-2026','title':'Content Marketing in 2026: What Still Works',
     'tag':'Content','date':'January 15, 2026','author':'Ananya Iyer',
     'excerpt':'AI has flooded the internet with mediocre content. Here is how to stand out by doing the opposite of everyone else.',
     'icon':'□','bg':'linear-gradient(135deg,#f2ede6,#e6ddd0)',
     'content':'''<p>The content marketing playbook that worked in 2020 is broken. AI-generated articles have made the internet noisier than ever. This creates an enormous opportunity for brands willing to invest in genuine, human-led content.</p>
<h2>What Has Not Changed</h2><p>People still want to learn, be entertained, and feel seen. Original insight and a genuine point of view are more valuable now than ever — precisely because they are so rare.</p>
<h2>The New Rules</h2>
<h3>Depth over frequency</h3><p>One genuinely useful piece outperforms ten generic posts every time.</p>
<h3>First-person perspective</h3><p>AI cannot have an experience. Your founder's perspective and your customers' stories are irreplaceable assets.</p>
<blockquote>Create content you would actually want to read. Then tell everyone you know about it.</blockquote>
<ul><li>One long-form piece per month beats daily short-form</li><li>Repurpose: one article becomes five LinkedIn posts, one email, one video</li><li>Build an email list — it is the only audience you own</li></ul>'''},
]

@app.route('/blog')
def blog(): return render_template('blog.html', user=get_current_user(), posts=BLOG_POSTS)

@app.route('/blog/<slug>')
def blog_post(slug):
    post = next((p for p in BLOG_POSTS if p['slug']==slug), None)
    if not post: flash('Post not found.','error'); return redirect(url_for('blog'))
    return render_template('blog_post.html', user=get_current_user(), post=post)

# ── AUTH ──────────────────────────────────────────────────
@app.route('/signup', methods=['GET','POST'])
def signup():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name=request.form.get('name','').strip(); company=request.form.get('company','').strip()
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        confirm=request.form.get('confirm','')
        if not all([name,company,email,password]): flash('All fields are required.','error')
        elif password!=confirm: flash('Passwords do not match.','error')
        elif len(password)<8: flash('Password must be at least 8 characters.','error')
        else:
            try:
                api_key='mm_'+secrets.token_hex(24)
                with get_db() as db:
                    db.execute('INSERT INTO users (name,company,email,password,api_key) VALUES (%s,%s,%s,%s,%s)',
                               (name,company,email,generate_password_hash(password),api_key))
                    user=db.execute('SELECT * FROM users WHERE email=%s',(email,)).fetchone()
                    _seed_demo(db, user['id'])
                    _seed_crm_demo(db, user['id'])
                    seed_email_templates(user['id'])
                    send_notification(user['id'], f'Welcome to Market Mosaic, {name}! Your dashboard is ready.', channels=('app','whatsapp','sms'))
                session['user_id']=user['id']; session['user_name']=name
                flash(f'Welcome to Market Mosaic, {name}!','success')
                return redirect(url_for('dashboard'))
            except Exception as _e:
                if 'unique' in str(_e).lower() or 'duplicate' in str(_e).lower(): flash('An account with that email already exists.','error')
                else: app.logger.error(f'Signup error: {_e}')
    return render_template('signup.html', user=None)

@app.route('/login', methods=['GET','POST'])
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        with get_db() as db:
            user=db.execute('SELECT * FROM users WHERE email=%s',(email,)).fetchone()
        if user and check_password_hash(user['password'],password):
            session['user_id']=user['id']; session['user_name']=user['name']
            flash(f'Welcome back, {user["name"]}!','success'); return redirect(url_for('dashboard'))
        flash('Invalid email or password.','error')
    return render_template('login.html', user=None)

@app.route('/logout')
def logout(): session.clear(); flash('Logged out.','success'); return redirect(url_for('home'))

@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    if request.method == 'POST':
        email=request.form.get('email','').strip().lower()
        with get_db() as db:
            user=db.execute('SELECT * FROM users WHERE email=%s',(email,)).fetchone()
            if user:
                token=secrets.token_urlsafe(32); expires=datetime.now()+timedelta(hours=1)
                db.execute('INSERT INTO password_resets (user_id,token,expires_at) VALUES (%s,%s,%s)',(user['id'],token,expires))
                reset_url=url_for('reset_password',token=token,_external=True)
                flash(f'[DEV — wire up Flask-Mail in production] Reset link: {reset_url}','success')
            else: flash('If that email is registered, a reset link has been sent.','success')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html', user=None)

@app.route('/reset-password/<token>', methods=['GET','POST'])
def reset_password(token):
    with get_db() as db:
        reset=db.execute('SELECT * FROM password_resets WHERE token=%s AND used=0 AND expires_at>%s',(token,datetime.now())).fetchone()
    valid=reset is not None
    if request.method=='POST' and valid:
        pw=request.form.get('password',''); cf=request.form.get('confirm','')
        if pw!=cf: flash('Passwords do not match.','error')
        elif len(pw)<8: flash('Min 8 characters.','error')
        else:
            with get_db() as db:
                db.execute('UPDATE users SET password=%s WHERE id=%s',(generate_password_hash(pw),reset['user_id']))
                db.execute('UPDATE password_resets SET used=1 WHERE id=%s',(reset['id'],))
            flash('Password updated! Please log in.','success'); return redirect(url_for('login'))
    return render_template('reset_password.html', user=None, valid=valid, token=token)

# ── DASHBOARD ─────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    user=get_current_user()
    if not user: session.clear(); return redirect(url_for('login'))
    with get_db() as db:
        campaigns=db.execute('SELECT * FROM campaigns WHERE user_id=%s ORDER BY created_at DESC LIMIT 5',(user['id'],)).fetchall()
        leads=db.execute('SELECT * FROM leads WHERE user_id=%s ORDER BY created_at DESC LIMIT 5',(user['id'],)).fetchall()
        stats={
            'total_campaigns': db.execute('SELECT COUNT(*) FROM campaigns WHERE user_id=%s',(user['id'],)).fetchone()[0],
            'active_campaigns':db.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=%s AND status='active'",(user['id'],)).fetchone()[0],
            'total_leads':     db.execute('SELECT COUNT(*) FROM leads WHERE user_id=%s',(user['id'],)).fetchone()[0],
            'total_spend':     db.execute('SELECT SUM(spent) FROM campaigns WHERE user_id=%s',(user['id'],)).fetchone()[0] or 0,
            'total_clicks':    db.execute('SELECT SUM(clicks) FROM campaigns WHERE user_id=%s',(user['id'],)).fetchone()[0] or 0,
            'total_impressions':db.execute('SELECT SUM(impressions) FROM campaigns WHERE user_id=%s',(user['id'],)).fetchone()[0] or 0,
            'total_conversions':db.execute('SELECT SUM(conversions) FROM campaigns WHERE user_id=%s',(user['id'],)).fetchone()[0] or 0,
        }
    return render_template('dashboard.html', user=user, campaigns=campaigns, leads=leads,
                           stats=stats, now_hour=datetime.now().hour, unread=unread(user['id']))

# ── CAMPAIGNS ─────────────────────────────────────────────
@app.route('/dashboard/campaigns')
@login_required
def campaigns():
    user=get_current_user(); sf=request.args.get('status','')
    with get_db() as db:
        q='SELECT * FROM campaigns WHERE user_id=%s'; p=[user['id']]
        if sf: q+=' AND status=%s'; p.append(sf)
        rows=db.execute(q+' ORDER BY created_at DESC',p).fetchall()
    return render_template('campaigns.html', user=user, campaigns=rows, status_filter=sf, unread=unread(user['id']))

@app.route('/dashboard/campaigns/new', methods=['GET','POST'])
@login_required
def new_campaign():
    user=get_current_user()
    if request.method=='POST':
        name=request.form.get('name','').strip(); channel=request.form.get('channel','')
        budget=float(request.form.get('budget',0) or 0); status=request.form.get('status','draft')
        notes=request.form.get('notes','').strip()
        if name and channel:
            with get_db() as db:
                db.execute('INSERT INTO campaigns (user_id,name,channel,budget,status,notes) VALUES (%s,%s,%s,%s,%s,%s)',
                           (user['id'],name,channel,budget,status,notes))
            send_notification(user['id'], f'Campaign "{name}" created successfully.', channels=('app','whatsapp','sms'))
            flash('Campaign created!','success'); return redirect(url_for('campaigns'))
        flash('Name and channel required.','error')
    return render_template('new_campaign.html', user=user, unread=unread(user['id']))

@app.route('/dashboard/campaigns/<int:cid>/edit', methods=['GET','POST'])
@login_required
def edit_campaign(cid):
    user=get_current_user()
    with get_db() as db:
        c=db.execute('SELECT * FROM campaigns WHERE id=%s AND user_id=%s',(cid,user['id'])).fetchone()
    if not c: flash('Not found.','error'); return redirect(url_for('campaigns'))
    if request.method=='POST':
        with get_db() as db:
            db.execute('''UPDATE campaigns SET name=%s,channel=%s,budget=%s,spent=%s,impressions=%s,
                          clicks=%s,conversions=%s,status=%s,notes=%s WHERE id=%s AND user_id=%s''',
                       (request.form.get('name'),request.form.get('channel'),
                        float(request.form.get('budget',0) or 0),float(request.form.get('spent',0) or 0),
                        int(request.form.get('impressions',0) or 0),int(request.form.get('clicks',0) or 0),
                        int(request.form.get('conversions',0) or 0),request.form.get('status'),
                        request.form.get('notes',''),cid,user['id']))
        flash('Campaign updated!','success'); return redirect(url_for('campaigns'))
    return render_template('edit_campaign.html', user=user, campaign=c, unread=unread(user['id']))

@app.route('/dashboard/campaigns/<int:cid>/delete', methods=['POST'])
@login_required
def delete_campaign(cid):
    user=get_current_user()
    with get_db() as db: db.execute('DELETE FROM campaigns WHERE id=%s AND user_id=%s',(cid,user['id']))
    flash('Campaign deleted.','success'); return redirect(url_for('campaigns'))

@app.route('/dashboard/campaigns/export')
@login_required
def export_campaigns():
    user=get_current_user()
    with get_db() as db:
        rows=db.execute('SELECT * FROM campaigns WHERE user_id=%s ORDER BY created_at DESC',(user['id'],)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(['ID','Name','Channel','Status','Budget','Spent','Impressions','Clicks','Conversions','CTR%','Created'])
    for r in rows:
        ctr=f"{r['clicks']/r['impressions']*100:.2f}" if r['impressions']>0 else '0'
        w.writerow([r['id'],r['name'],r['channel'],r['status'],r['budget'],r['spent'],
                    r['impressions'],r['clicks'],r['conversions'],ctr,r['created_at'][:10]])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':'attachment;filename=campaigns_export.csv'})

# ── LEADS ─────────────────────────────────────────────────
@app.route('/dashboard/leads')
@login_required
def leads():
    user=get_current_user(); sf=request.args.get('status',''); search=request.args.get('q','').strip()
    with get_db() as db:
        q='SELECT * FROM leads WHERE user_id=%s'; p=[user['id']]
        if sf: q+=' AND status=%s'; p.append(sf)
        if search:
            q+=' AND (name LIKE %s OR email LIKE %s OR company LIKE %s)'
            p+=[f'%{search}%',f'%{search}%',f'%{search}%']
        rows=db.execute(q+' ORDER BY created_at DESC',p).fetchall()
    return render_template('leads.html', user=user, leads=rows, status_filter=sf, search=search, unread=unread(user['id']))

@app.route('/dashboard/leads/new', methods=['GET','POST'])
@login_required
def new_lead():
    user=get_current_user()
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip()
        company=request.form.get('company','').strip(); phone=request.form.get('phone','').strip()
        source=request.form.get('source','organic'); status=request.form.get('status','new')
        notes=request.form.get('notes','').strip()
        if name and email:
            with get_db() as db:
                db.execute('INSERT INTO leads (user_id,name,email,company,phone,source,status,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                           (user['id'],name,email,company,phone,source,status,notes))
            send_notification(user['id'], f'New lead "{name}" added to your pipeline.', channels=('app','whatsapp','sms'))
            flash('Lead added!','success'); return redirect(url_for('leads'))
        flash('Name and email required.','error')
    return render_template('new_lead.html', user=user, unread=unread(user['id']))

@app.route('/dashboard/leads/<int:lid>/edit', methods=['GET','POST'])
@login_required
def edit_lead(lid):
    user=get_current_user()
    with get_db() as db:
        lead=db.execute('SELECT * FROM leads WHERE id=%s AND user_id=%s',(lid,user['id'])).fetchone()
    if not lead: flash('Not found.','error'); return redirect(url_for('leads'))
    if request.method=='POST':
        with get_db() as db:
            db.execute('UPDATE leads SET name=%s,email=%s,company=%s,phone=%s,source=%s,status=%s,notes=%s WHERE id=%s AND user_id=%s',
                       (request.form.get('name'),request.form.get('email'),request.form.get('company'),
                        request.form.get('phone'),request.form.get('source'),request.form.get('status'),
                        request.form.get('notes',''),lid,user['id']))
        flash('Lead updated!','success'); return redirect(url_for('leads'))
    return render_template('edit_lead.html', user=user, lead=lead, unread=unread(user['id']))

@app.route('/dashboard/leads/<int:lid>/delete', methods=['POST'])
@login_required
def delete_lead(lid):
    user=get_current_user()
    with get_db() as db: db.execute('DELETE FROM leads WHERE id=%s AND user_id=%s',(lid,user['id']))
    flash('Lead deleted.','success'); return redirect(url_for('leads'))

@app.route('/dashboard/leads/export')
@login_required
def export_leads():
    user=get_current_user()
    with get_db() as db:
        rows=db.execute('SELECT * FROM leads WHERE user_id=%s ORDER BY created_at DESC',(user['id'],)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(['ID','Name','Email','Company','Phone','Source','Status','Notes','Created'])
    for r in rows:
        w.writerow([r['id'],r['name'],r['email'],r['company'] or '',r['phone'] or '',
                    r['source'],r['status'],r['notes'] or '',r['created_at'][:10]])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':'attachment;filename=leads_export.csv'})

# ── ANALYTICS ─────────────────────────────────────────────
@app.route('/dashboard/analytics')
@login_required
def analytics():
    user=get_current_user()
    with get_db() as db:
        camp=db.execute('SELECT * FROM campaigns WHERE user_id=%s',(user['id'],)).fetchall()
        lsrc=db.execute('SELECT source,COUNT(*) as cnt FROM leads WHERE user_id=%s GROUP BY source',(user['id'],)).fetchall()
        lst=db.execute('SELECT status,COUNT(*) as cnt FROM leads WHERE user_id=%s GROUP BY status',(user['id'],)).fetchall()
    chart_data={
        'labels':[c['name'] for c in camp],'clicks':[c['clicks'] for c in camp],
        'impressions':[c['impressions'] for c in camp],'spent':[c['spent'] for c in camp],
        'conversions':[c['conversions'] for c in camp],
        'lead_sources':[r['source'] for r in lsrc],'lead_source_counts':[r['cnt'] for r in lsrc],
        'lead_statuses':[r['status'] for r in lst],'lead_status_counts':[r['cnt'] for r in lst],
    }
    return render_template('analytics.html', user=user, chart_data=json.dumps(chart_data), unread=unread(user['id']))

# ── NOTIFICATIONS ─────────────────────────────────────────
@app.route('/dashboard/notifications')
@login_required
def notifications():
    user=get_current_user()
    with get_db() as db:
        notifs=db.execute('SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC',(user['id'],)).fetchall()
        db.execute('UPDATE notifications SET read=1 WHERE user_id=%s',(user['id'],))
    return render_template('notifications.html', user=user, notifs=notifs, unread=0)

# ── SETTINGS ──────────────────────────────────────────────
@app.route('/dashboard/settings', methods=['GET','POST'])
@login_required
def settings():
    user=get_current_user()
    if request.method=='POST':
        action=request.form.get('action','profile')
        if action=='profile':
            name=request.form.get('name','').strip(); company=request.form.get('company','').strip()
            if name and company:
                with get_db() as db: db.execute('UPDATE users SET name=%s,company=%s WHERE id=%s',(name,company,user['id']))
                session['user_name']=name; flash('Profile updated!','success')
        elif action=='password':
            curr=request.form.get('current_password',''); npw=request.form.get('new_password',''); conf=request.form.get('confirm_password','')
            if not check_password_hash(user['password'],curr): flash('Current password incorrect.','error')
            elif npw!=conf: flash('New passwords do not match.','error')
            elif len(npw)<8: flash('Min 8 characters.','error')
            else:
                with get_db() as db: db.execute('UPDATE users SET password=%s WHERE id=%s',(generate_password_hash(npw),user['id']))
                flash('Password changed!','success')
        elif action=='regenerate_key':
            nk='mm_'+secrets.token_hex(24)
            with get_db() as db: db.execute('UPDATE users SET api_key=%s WHERE id=%s',(nk,user['id']))
            flash('API key regenerated.','success')
        return redirect(url_for('settings'))
    user=get_current_user()
    return render_template('settings.html', user=user, unread=unread(user['id']))

# ── ADMIN ─────────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin():
    with get_db() as db:
        users=db.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
        stats={'total_users':db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
               'total_campaigns':db.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0],
               'total_leads':db.execute('SELECT COUNT(*) FROM leads').fetchone()[0]}
    return render_template('admin.html', user=get_current_user(), users=users, stats=stats)

@app.route('/admin/users/<int:uid>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(uid):
    with get_db() as db:
        u=db.execute('SELECT * FROM users WHERE id=%s',(uid,)).fetchone()
        if u and u['id']!=session['user_id']:
            db.execute('UPDATE users SET is_admin=%s WHERE id=%s',(0 if u['is_admin'] else 1,uid))
    flash('User updated.','success'); return redirect(url_for('admin'))

@app.route('/admin/users/<int:uid>/delete', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid==session['user_id']: flash("You can't delete yourself.",'error'); return redirect(url_for('admin'))
    with get_db() as db:
        for t in ['campaigns','leads','notifications','password_resets']:
            db.execute(f'DELETE FROM {t} WHERE user_id=%s',(uid,))
        db.execute('DELETE FROM users WHERE id=%s',(uid,))
    flash('User deleted.','success'); return redirect(url_for('admin'))

# ── REST API ──────────────────────────────────────────────
@app.route('/api/v1/campaigns')
def api_campaigns():
    u=api_auth()
    if not u: return jsonify({'error':'Unauthorized'}),401
    with get_db() as db: rows=db.execute('SELECT * FROM campaigns WHERE user_id=%s',(u['id'],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/v1/leads')
def api_leads():
    u=api_auth()
    if not u: return jsonify({'error':'Unauthorized'}),401
    with get_db() as db: rows=db.execute('SELECT * FROM leads WHERE user_id=%s',(u['id'],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/v1/stats')
def api_stats():
    u=api_auth()
    if not u: return jsonify({'error':'Unauthorized'}),401
    with get_db() as db:
        return jsonify({'campaigns':db.execute('SELECT COUNT(*) FROM campaigns WHERE user_id=%s',(u['id'],)).fetchone()[0],
                        'leads':db.execute('SELECT COUNT(*) FROM leads WHERE user_id=%s',(u['id'],)).fetchone()[0],
                        'spend':db.execute('SELECT SUM(spent) FROM campaigns WHERE user_id=%s',(u['id'],)).fetchone()[0] or 0,
                        'clicks':db.execute('SELECT SUM(clicks) FROM campaigns WHERE user_id=%s',(u['id'],)).fetchone()[0] or 0})

# ── ERRORS ────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e): return render_template('404.html', user=get_current_user()), 404

@app.errorhandler(500)
def server_error(e): return render_template('500.html', user=get_current_user()), 500

# ── SEED ──────────────────────────────────────────────────
def _seed_demo(db, uid):
    db.executemany('INSERT INTO campaigns (user_id,name,channel,status,budget,spent,impressions,clicks,conversions) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        [(uid,'Q2 Brand Awareness','Social Media','active',50000,31200,420000,8400,312),
         (uid,'Google Search — India','Search','active',30000,18750,180000,5400,189),
         (uid,'Email Nurture Series','Email','paused',8000,4200,22000,3100,87),
         (uid,'LinkedIn B2B Push','LinkedIn','draft',20000,0,0,0,0)])
    db.executemany('INSERT INTO leads (user_id,name,email,company,source,status) VALUES (%s,%s,%s,%s,%s,%s)',
        [(uid,'Priya Sharma','priya@techcorp.in','TechCorp India','LinkedIn','qualified'),
         (uid,'Rohan Mehta','rohan@startup.io','LaunchPad','Organic','new'),
         (uid,'Ananya Iyer','ananya@brandco.com','BrandCo','Referral','contacted'),
         (uid,'Vikram Das','vikram@retail.in','Retail Plus','Google','new'),
         (uid,'Sunita Rao','sunita@fmcg.co','FMCG Pvt Ltd','Email','qualified')])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'production') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)

# ── REPORTS ───────────────────────────────────────────────
@app.route('/dashboard/reports')
@login_required
def reports():
    user = get_current_user()
    with get_db() as db:
        campaigns = db.execute('SELECT * FROM campaigns WHERE user_id=%s ORDER BY spent DESC', (user['id'],)).fetchall()
        lead_by_status = db.execute('SELECT status, COUNT(*) as cnt FROM leads WHERE user_id=%s GROUP BY status', (user['id'],)).fetchall()
        lead_by_source = db.execute('SELECT source, COUNT(*) as cnt FROM leads WHERE user_id=%s GROUP BY source ORDER BY cnt DESC', (user['id'],)).fetchall()
        channel_spend  = db.execute('SELECT channel, SUM(spent) as spend FROM campaigns WHERE user_id=%s GROUP BY channel ORDER BY spend DESC', (user['id'],)).fetchall()
        qualified_leads = db.execute("SELECT COUNT(*) FROM leads WHERE user_id=%s AND status='qualified'", (user['id'],)).fetchone()[0]
        stats = {
            'total_campaigns':  db.execute('SELECT COUNT(*) FROM campaigns WHERE user_id=%s', (user['id'],)).fetchone()[0],
            'active_campaigns': db.execute("SELECT COUNT(*) FROM campaigns WHERE user_id=%s AND status='active'", (user['id'],)).fetchone()[0],
            'total_leads':      db.execute('SELECT COUNT(*) FROM leads WHERE user_id=%s', (user['id'],)).fetchone()[0],
            'qualified_leads':  qualified_leads,
            'total_spend':      db.execute('SELECT SUM(spent) FROM campaigns WHERE user_id=%s', (user['id'],)).fetchone()[0] or 0,
            'total_clicks':     db.execute('SELECT SUM(clicks) FROM campaigns WHERE user_id=%s', (user['id'],)).fetchone()[0] or 0,
            'total_impressions':db.execute('SELECT SUM(impressions) FROM campaigns WHERE user_id=%s', (user['id'],)).fetchone()[0] or 0,
            'total_conversions':db.execute('SELECT SUM(conversions) FROM campaigns WHERE user_id=%s', (user['id'],)).fetchone()[0] or 0,
        }
    return render_template('reports.html', user=user, campaigns=campaigns, stats=stats,
                           lead_by_status=lead_by_status, lead_by_source=lead_by_source,
                           channel_spend=channel_spend, now=datetime.now().strftime('%d %b %Y'),
                           unread=unread(user['id']))

# ── PROPOSALS ─────────────────────────────────────────────
@app.route('/dashboard/proposals')
@login_required
def proposals():
    user = get_current_user()
    return render_template('proposals.html', user=user, now=datetime.now().strftime('%d %b %Y'),
                           unread=unread(user['id']))

# ── EMAIL TEMPLATES ───────────────────────────────────────
EMAIL_TEMPLATES = [
    {
        'name': 'New Client Welcome',
        'tag': 'Onboarding',
        'subject': 'Welcome to Market Mosaic — Next Steps',
        'body': """Hi [Client Name],

Welcome aboard! We're thrilled to be partnering with [Company Name] on this journey.

Here's what happens next:

1. Kick-off call — We'll schedule a 60-minute session to align on goals, timelines, and key contacts.
2. Discovery questionnaire — You'll receive a short form to help us understand your brand, audience, and competitors.
3. Strategy draft — Within 5 working days of our kick-off, we'll share an initial strategy for your review.

In the meantime, feel free to reach out with any questions at hello@marketmosaic.in.

Looking forward to building something great together.

Warm regards,
[Your Name]
Market Mosaic"""
    },
    {
        'name': 'Monthly Report',
        'tag': 'Reporting',
        'subject': '[Company Name] — Marketing Report — [Month Year]',
        'body': """Hi [Client Name],

Please find below your marketing performance summary for [Month Year].

CAMPAIGN HIGHLIGHTS
-------------------
• Impressions: [X]
• Clicks: [X] (CTR: [X]%)
• Conversions: [X]
• Total Spend: Rs [X]
• Cost per Conversion: Rs [X]

WHAT WORKED WELL
• [Insight 1]
• [Insight 2]

FOCUS FOR NEXT MONTH
• [Action 1]
• [Action 2]

The full report with breakdowns is attached. Happy to walk through it on a call — just let me know.

Best,
[Your Name]
Market Mosaic"""
    },
    {
        'name': 'Proposal Follow-Up',
        'tag': 'Sales',
        'subject': 'Following up — Marketing Proposal for [Company Name]',
        'body': """Hi [Client Name],

I wanted to follow up on the proposal we shared on [Date].

We've put together what we believe is a strong approach for [Company Name] — one that balances quick wins with a longer-term brand-building strategy.

A few things I'd love to get your perspective on:
• Does the scope feel right for your current priorities%s
• Are there any services you'd like to adjust or swap out%s
• Do you have any questions about the investment%s

I'm happy to jump on a 20-minute call to address any questions. You can book a time here: [Calendar Link]

Looking forward to hearing from you.

Best,
[Your Name]
Market Mosaic"""
    },
    {
        'name': 'Campaign Launch',
        'tag': 'Campaigns',
        'subject': '[Campaign Name] Is Live — Here\'s What to Expect',
        'body': """Hi [Client Name],

Great news — [Campaign Name] is officially live!

CAMPAIGN DETAILS
----------------
• Channel: [Channel]
• Start Date: [Date]
• Budget: Rs [Amount]
• Goal: [Objective]

WHAT TO EXPECT IN THE FIRST 2 WEEKS
The first two weeks are primarily a learning phase. Algorithms need data to optimise, and we typically see performance improve steadily after the first 7–10 days.

We'll share a mid-point check-in in 2 weeks with early data and any optimisation notes.

In the meantime, if you have any questions or feedback, don't hesitate to reach out.

Exciting times ahead!

Best,
[Your Name]
Market Mosaic"""
    },
    {
        'name': 'Invoice / Payment Request',
        'tag': 'Finance',
        'subject': 'Invoice #[Number] — Market Mosaic — [Month Year]',
        'body': """Hi [Client Name],

Please find Invoice #[Number] for services rendered in [Month Year].

INVOICE SUMMARY
---------------
• Service: [Description]
• Period: [Start Date] to [End Date]
• Amount: Rs [Total]
• Due Date: [Due Date]

Payment can be made to:
Account Name: Market Mosaic
Account No: [XXXX]
IFSC: [XXXX]
UPI: [ID]

Please use Invoice #[Number] as the payment reference.

If you have any questions, please don't hesitate to get in touch.

Thank you for your continued partnership.

Best,
[Your Name]
Market Mosaic"""
    },
    {
        'name': 'Feedback Request',
        'tag': 'Retention',
        'subject': 'A Quick Note from Market Mosaic',
        'body': """Hi [Client Name],

It's been [X months] since we started working together, and I wanted to take a moment to check in.

We're always looking to improve, and your feedback matters to us. I have two quick questions:

1. On a scale of 1–10, how satisfied are you with our work so far%s
2. Is there anything we could be doing better or differently%s

Feel free to reply directly to this email — even a few words would be incredibly helpful.

Thank you for taking the time. We genuinely value this partnership.

Warm regards,
[Your Name]
Market Mosaic"""
    },
]

@app.route('/dashboard/email-templates')
@login_required
def email_templates():
    user = get_current_user()
    return render_template('email_templates.html', user=user, templates=EMAIL_TEMPLATES,
                           templates_json=json.dumps(EMAIL_TEMPLATES), unread=unread(user['id']))

# ════════════════════════════════════════════════════════
# PAYMENTS — Razorpay (UPI + Cards + Netbanking)
# ════════════════════════════════════════════════════════
# pip install razorpay
# Set env vars: RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
# Sign up free at razorpay.com — no monthly fee, 2% per txn

import hmac, hashlib

RAZORPAY_KEY_ID     = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')

PLANS = {
    'starter': {'name': 'Starter', 'price': 0,    'amount_paise': 0,      'plan_id': 'free'},
    'growth':  {'name': 'Growth',  'price': 2999,  'amount_paise': 299900, 'plan_id': 'growth'},
    'agency':  {'name': 'Agency',  'price': 7999,  'amount_paise': 799900, 'plan_id': 'agency'},
}

def razorpay_client():
    try:
        import razorpay
        return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    except ImportError:
        return None

@app.route('/dashboard/billing')
@login_required
def billing():
    user = get_current_user()
    with get_db() as db:
        payments = db.execute(
            'SELECT * FROM payments WHERE user_id=%s ORDER BY created_at DESC', (user['id'],)
        ).fetchall()
    return render_template('billing.html', user=user, plans=PLANS,
                           payments=payments, razorpay_key=RAZORPAY_KEY_ID,
                           unread=unread(user['id']))

@app.route('/billing/create-order', methods=['POST'])
@login_required
def create_order():
    user = get_current_user()
    plan_id = request.form.get('plan_id')
    plan = PLANS.get(plan_id)
    if not plan or plan['amount_paise'] == 0:
        flash('Invalid plan.', 'error')
        return redirect(url_for('billing'))

    client = razorpay_client()
    if not client:
        flash('Payment system not configured. Install razorpay: pip install razorpay', 'error')
        return redirect(url_for('billing'))

    order = client.order.create({
        'amount':   plan['amount_paise'],
        'currency': 'INR',
        'notes':    {'user_id': str(user['id']), 'plan': plan_id}
    })

    return render_template('checkout.html', user=user,
                           order=order, plan=plan,
                           razorpay_key=RAZORPAY_KEY_ID,
                           unread=unread(user['id']))

@app.route('/billing/verify', methods=['POST'])
@login_required
def verify_payment():
    user = get_current_user()
    data = request.form

    razorpay_order_id   = data.get('razorpay_order_id', '')
    razorpay_payment_id = data.get('razorpay_payment_id', '')
    razorpay_signature  = data.get('razorpay_signature', '')
    plan_id             = data.get('plan_id', '')

    # Verify signature
    msg     = f'{razorpay_order_id}|{razorpay_payment_id}'.encode()
    secret  = RAZORPAY_KEY_SECRET.encode()
    gen_sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

    if gen_sig == razorpay_signature:
        plan = PLANS.get(plan_id, {})
        with get_db() as db:
            db.execute('UPDATE users SET plan=%s WHERE id=%s', (plan_id, user['id']))
            db.execute(
                'INSERT INTO payments (user_id,order_id,payment_id,plan,amount,status) VALUES (%s,%s,%s,%s,%s,%s)',
                (user['id'], razorpay_order_id, razorpay_payment_id,
                 plan_id, plan.get('price', 0), 'success')
            )
        add_notification(user['id'], f'Payment successful! You are now on the {plan.get("name","")} plan.')
        _send_whatsapp(user['id'], f'✅ Payment confirmed! Your Market Mosaic account has been upgraded to the {plan.get("name","")} plan.')
        _send_sms(user['id'], f'Payment confirmed. Market Mosaic account upgraded to {plan.get("name","")} plan.')
        flash(f'Payment successful! You are now on the {plan.get("name","")} plan.', 'success')
    else:
        with get_db() as db:
            db.execute(
                'INSERT INTO payments (user_id,order_id,payment_id,plan,amount,status) VALUES (%s,%s,%s,%s,%s,%s)',
                (user['id'], razorpay_order_id, razorpay_payment_id, plan_id, 0, 'failed')
            )
        flash('Payment verification failed. Please contact support.', 'error')

    return redirect(url_for('billing'))

@app.route('/billing/webhook', methods=['POST'])
def razorpay_webhook():
    """Razorpay webhook endpoint — set this URL in Razorpay dashboard"""
    webhook_secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
    payload        = request.get_data()
    signature      = request.headers.get('X-Razorpay-Signature', '')

    if webhook_secret:
        gen = hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        if gen != signature:
            return jsonify({'error': 'Invalid signature'}), 400

    event = request.json
    if event.get('event') == 'payment.captured':
        payment = event['payload']['payment']['entity']
        notes   = payment.get('notes', {})
        user_id = notes.get('user_id')
        plan_id = notes.get('plan')
        if user_id and plan_id:
            with get_db() as db:
                db.execute('UPDATE users SET plan=%s WHERE id=%s', (plan_id, user_id))
    return jsonify({'status': 'ok'})


# ════════════════════════════════════════════════════════
# NOTIFICATIONS — WhatsApp (Twilio) + SMS (Fast2SMS)
# ════════════════════════════════════════════════════════
# WhatsApp: pip install twilio — free sandbox at twilio.com
# SMS:      Free at fast2sms.com (Indian numbers, no registration needed for dev)
# Set env vars: TWILIO_SID, TWILIO_TOKEN, TWILIO_WHATSAPP_FROM
#               FAST2SMS_KEY

TWILIO_SID            = os.environ.get('TWILIO_SID', '')
TWILIO_TOKEN          = os.environ.get('TWILIO_TOKEN', '')
TWILIO_WHATSAPP_FROM  = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')  # Twilio sandbox
FAST2SMS_KEY          = os.environ.get('FAST2SMS_KEY', '')

def _get_user_phone(user_id):
    """Fetch a user's phone number from the DB"""
    with get_db() as db:
        row = db.execute('SELECT phone FROM users WHERE id=%s', (user_id,)).fetchone()
        return row['phone'] if row and row['phone'] else None

def _send_whatsapp(user_id, message):
    """Send a WhatsApp message via Twilio. Silently skips if not configured or user opted out."""
    if not all([TWILIO_SID, TWILIO_TOKEN]):
        return
    with get_db() as db:
        u = db.execute('SELECT phone, notif_whatsapp FROM users WHERE id=%s', (user_id,)).fetchone()
        if not u or not u['notif_whatsapp'] or not u['phone']:
            return
    phone = u['phone']
    try:
        try:
            from twilio.rest import Client
        except ImportError:
            return
        to_wa = f'whatsapp:{phone}' if not phone.startswith('whatsapp:') else phone
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(from_=TWILIO_WHATSAPP_FROM, to=to_wa, body=message)
    except Exception as e:
        app.logger.warning(f'WhatsApp send failed: {e}')

def _send_sms(user_id, message):
    """Send SMS via Fast2SMS (India). Silently skips if not configured or user opted out."""
    if not FAST2SMS_KEY:
        return
    with get_db() as db:
        u = db.execute('SELECT phone, notif_sms FROM users WHERE id=%s', (user_id,)).fetchone()
        if not u or not u['notif_sms'] or not u['phone']:
            return
    phone = u['phone']
    # Strip +91 or 0 prefix for Fast2SMS
    number = phone.strip().lstrip('+').lstrip('91').lstrip('0')
    if len(number) != 10:
        return
    try:
        import urllib.request, urllib.parse
        payload = urllib.parse.urlencode({
            'sender_id': 'FSTSMS',
            'message':   message,
            'language':  'english',
            'route':     'q',
            'numbers':   number,
        }).encode()
        req = urllib.request.Request(
            'https://www.fast2sms.com/dev/bulkV2',
            data=payload,
            headers={'authorization': FAST2SMS_KEY, 'Content-Type': 'application/x-www-form-urlencoded'},
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        app.logger.warning(f'SMS send failed: {e}')

def send_notification(user_id, message, channels=('app', 'whatsapp', 'sms')):
    """Unified notification dispatcher — send to any combination of channels."""
    if 'app' in channels:
        add_notification(user_id, message)
    if 'whatsapp' in channels:
        _send_whatsapp(user_id, f'Market Mosaic: {message}')
    if 'sms' in channels:
        _send_sms(user_id, f'Market Mosaic: {message}')

# ── NOTIFICATION SETTINGS (user preferences) ─────────────
@app.route('/dashboard/notification-settings', methods=['GET', 'POST'])
@login_required
def notification_settings():
    user = get_current_user()
    if request.method == 'POST':
        phone         = request.form.get('phone', '').strip()
        notif_app     = 1 if request.form.get('notif_app') else 0
        notif_whatsapp= 1 if request.form.get('notif_whatsapp') else 0
        notif_sms     = 1 if request.form.get('notif_sms') else 0
        with get_db() as db:
            db.execute(
                'UPDATE users SET phone=%s, notif_app=%s, notif_whatsapp=%s, notif_sms=%s WHERE id=%s',
                (phone, notif_app, notif_whatsapp, notif_sms, user['id'])
            )
        # Send test messages if requested
        if request.form.get('test_whatsapp') and phone:
            _send_whatsapp(user['id'], '👋 Test message from Market Mosaic! WhatsApp notifications are working.')
        if request.form.get('test_sms') and phone:
            _send_sms(user['id'], 'Test message from Market Mosaic. SMS notifications working.')
        flash('Notification preferences saved!', 'success')
        return redirect(url_for('notification_settings'))
    user = get_current_user()
    return render_template('notification_settings.html', user=user,
                           twilio_configured=bool(TWILIO_SID),
                           fast2sms_configured=bool(FAST2SMS_KEY),
                           unread=unread(user['id']))

# ── MANUAL NOTIFICATION SEND (admin/testing) ──────────────
@app.route('/dashboard/send-notification', methods=['POST'])
@login_required
def send_test_notification():
    user = get_current_user()
    msg      = request.form.get('message', '').strip()
    channels = request.form.getlist('channels')
    if msg:
        send_notification(user['id'], msg, channels=channels)
        flash(f'Notification sent via: {", ".join(channels) if channels else "none"}', 'success')
    return redirect(url_for('notification_settings'))

# ════════════════════════════════════════════════════════
# CRM — CONTACTS
# ════════════════════════════════════════════════════════

CONTACT_STAGES = ['lead','prospect','qualified','customer','churned']
DEAL_STAGES    = ['prospecting','qualification','proposal','negotiation','closed_won','closed_lost']
ACTIVITY_TYPES = ['call','email','meeting','demo','follow_up','note']

@app.route('/crm')
@login_required
def crm():
    return redirect(url_for('crm_dashboard'))

@app.route('/crm/dashboard')
@login_required
def crm_dashboard():
    user = get_current_user()
    with get_db() as db:
        total_contacts  = db.execute('SELECT COUNT(*) FROM contacts WHERE user_id=%s',(user['id'],)).fetchone()[0]
        total_deals     = db.execute('SELECT COUNT(*) FROM deals WHERE user_id=%s',(user['id'],)).fetchone()[0]
        pipeline_value  = db.execute("SELECT SUM(value) FROM deals WHERE user_id=%s AND stage NOT IN ('closed_won','closed_lost')",(user['id'],)).fetchone()[0] or 0
        won_value       = db.execute("SELECT SUM(value) FROM deals WHERE user_id=%s AND stage='closed_won'",(user['id'],)).fetchone()[0] or 0
        won_count       = db.execute("SELECT COUNT(*) FROM deals WHERE user_id=%s AND stage='closed_won'",(user['id'],)).fetchone()[0]
        lost_count      = db.execute("SELECT COUNT(*) FROM deals WHERE user_id=%s AND stage='closed_lost'",(user['id'],)).fetchone()[0]
        open_tasks      = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=%s AND status='open'",(user['id'],)).fetchone()[0]
        recent_contacts = db.execute('SELECT * FROM contacts WHERE user_id=%s ORDER BY created_at DESC LIMIT 6',(user['id'],)).fetchall()
        recent_deals    = db.execute('SELECT d.*,c.name as contact_name FROM deals d LEFT JOIN contacts c ON d.contact_id=c.id WHERE d.user_id=%s ORDER BY d.created_at DESC LIMIT 6',(user['id'],)).fetchall()
        stage_counts    = db.execute('SELECT stage,COUNT(*) as cnt FROM deals WHERE user_id=%s GROUP BY stage',(user['id'],)).fetchall()
        contact_sources = db.execute('SELECT source,COUNT(*) as cnt FROM contacts WHERE user_id=%s GROUP BY source ORDER BY cnt DESC',(user['id'],)).fetchall()
        upcoming_tasks  = db.execute("SELECT * FROM tasks WHERE user_id=%s AND status='open' ORDER BY due_date LIMIT 5",(user['id'],)).fetchall()
        conv_rate = round(won_count/(won_count+lost_count)*100,1) if (won_count+lost_count)>0 else 0
        stats = dict(total_contacts=total_contacts,total_deals=total_deals,
                     pipeline_value=pipeline_value,won_value=won_value,
                     won_count=won_count,conv_rate=conv_rate,open_tasks=open_tasks)
    return render_template('crm_dashboard.html', user=user, stats=stats,
                           recent_contacts=recent_contacts, recent_deals=recent_deals,
                           stage_counts=stage_counts, contact_sources=contact_sources,
                           upcoming_tasks=upcoming_tasks, unread=unread(user['id']),
                           stage_data=json.dumps({'labels':[r['stage'] for r in stage_counts],'counts':[r['cnt'] for r in stage_counts]}))

# ── CONTACTS ──────────────────────────────────────────────
@app.route('/crm/contacts')
@login_required
def crm_contacts():
    user = get_current_user()
    stage_f = request.args.get('stage','')
    source_f= request.args.get('source','')
    q       = request.args.get('q','').strip()
    with get_db() as db:
        sql = 'SELECT * FROM contacts WHERE user_id=%s'; p=[user['id']]
        if stage_f:  sql+=' AND stage=%s';  p.append(stage_f)
        if source_f: sql+=' AND source=%s'; p.append(source_f)
        if q: sql+=' AND (name LIKE %s OR email LIKE %s OR company LIKE %s)'; p+=[f'%{q}%']*3
        rows = db.execute(sql+' ORDER BY created_at DESC', p).fetchall()
        sources = db.execute('SELECT DISTINCT source FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
    return render_template('crm_contacts.html', user=user, contacts=rows,
                           stages=CONTACT_STAGES, sources=[s['source'] for s in sources],
                           stage_f=stage_f, source_f=source_f, q=q, unread=unread(user['id']))

@app.route('/crm/contacts/new', methods=['GET','POST'])
@login_required
def crm_new_contact():
    user = get_current_user()
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('INSERT INTO contacts (user_id,name,email,phone,company,title,source,stage,owner,tags,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (user['id'],f.get('name'),f.get('email'),f.get('phone'),f.get('company'),
                        f.get('title'),f.get('source','manual'),f.get('stage','lead'),
                        f.get('owner'),f.get('tags',''),f.get('notes','')))
        send_notification(user['id'],f'Contact "{f.get("name")}" added.',channels=('app',))
        flash('Contact added!','success'); return redirect(url_for('crm_contacts'))
    return render_template('crm_contact_form.html', user=user, contact=None,
                           stages=CONTACT_STAGES, unread=unread(user['id']))

@app.route('/crm/contacts/<int:cid>')
@login_required
def crm_contact_detail(cid):
    user = get_current_user()
    with get_db() as db:
        contact    = db.execute('SELECT * FROM contacts WHERE id=%s AND user_id=%s',(cid,user['id'])).fetchone()
        if not contact: flash('Not found','error'); return redirect(url_for('crm_contacts'))
        deals      = db.execute('SELECT * FROM deals WHERE contact_id=%s AND user_id=%s',(cid,user['id'])).fetchall()
        activities = db.execute('SELECT * FROM activities WHERE contact_id=%s AND user_id=%s ORDER BY created_at DESC',(cid,user['id'])).fetchall()
    return render_template('crm_contact_detail.html', user=user, contact=contact,
                           deals=deals, activities=activities, deal_stages=DEAL_STAGES,
                           activity_types=ACTIVITY_TYPES, unread=unread(user['id']))

@app.route('/crm/contacts/<int:cid>/edit', methods=['GET','POST'])
@login_required
def crm_edit_contact(cid):
    user = get_current_user()
    with get_db() as db:
        contact = db.execute('SELECT * FROM contacts WHERE id=%s AND user_id=%s',(cid,user['id'])).fetchone()
    if not contact: return redirect(url_for('crm_contacts'))
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('UPDATE contacts SET name=%s,email=%s,phone=%s,company=%s,title=%s,source=%s,stage=%s,owner=%s,tags=%s,notes=%s,last_contacted=%s WHERE id=%s AND user_id=%s',
                       (f.get('name'),f.get('email'),f.get('phone'),f.get('company'),f.get('title'),
                        f.get('source'),f.get('stage'),f.get('owner'),f.get('tags',''),f.get('notes',''),
                        f.get('last_contacted') or None, cid, user['id']))
        flash('Contact updated!','success'); return redirect(url_for('crm_contact_detail',cid=cid))
    return render_template('crm_contact_form.html', user=user, contact=contact,
                           stages=CONTACT_STAGES, unread=unread(user['id']))

@app.route('/crm/contacts/<int:cid>/delete', methods=['POST'])
@login_required
def crm_delete_contact(cid):
    user = get_current_user()
    with get_db() as db:
        db.execute('DELETE FROM contacts WHERE id=%s AND user_id=%s',(cid,user['id']))
    flash('Contact deleted.','success'); return redirect(url_for('crm_contacts'))

@app.route('/crm/contacts/export')
@login_required
def crm_export_contacts():
    user = get_current_user()
    with get_db() as db:
        rows = db.execute('SELECT * FROM contacts WHERE user_id=%s ORDER BY created_at DESC',(user['id'],)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(['ID','Name','Email','Phone','Company','Title','Source','Stage','Owner','Tags','Created'])
    for r in rows:
        w.writerow([r['id'],r['name'],r['email'] or '',r['phone'] or '',r['company'] or '',
                    r['title'] or '',r['source'],r['stage'],r['owner'] or '',r['tags'] or '',r['created_at'][:10]])
    out.seek(0)
    return Response(out.getvalue(),mimetype='text/csv',
                    headers={'Content-Disposition':'attachment;filename=contacts.csv'})

# ── DEALS / PIPELINE ──────────────────────────────────────
@app.route('/crm/deals')
@login_required
def crm_deals():
    user = get_current_user()
    with get_db() as db:
        deals = db.execute('''SELECT d.*,c.name as contact_name FROM deals d
                              LEFT JOIN contacts c ON d.contact_id=c.id
                              WHERE d.user_id=%s ORDER BY d.created_at DESC''',(user['id'],)).fetchall()
        contacts = db.execute('SELECT id,name FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
        pipeline = {}
        for s in DEAL_STAGES:
            pipeline[s] = [d for d in deals if d['stage']==s]
    return render_template('crm_deals.html', user=user, deals=deals, pipeline=pipeline,
                           stages=DEAL_STAGES, contacts=contacts, unread=unread(user['id']))

@app.route('/crm/deals/new', methods=['GET','POST'])
@login_required
def crm_new_deal():
    user = get_current_user()
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('INSERT INTO deals (user_id,title,contact_id,value,stage,probability,close_date,owner,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (user['id'],f.get('title'),f.get('contact_id') or None,
                        float(f.get('value',0) or 0),f.get('stage','prospecting'),
                        int(f.get('probability',10) or 10),f.get('close_date') or None,
                        f.get('owner'),f.get('notes','')))
        flash('Deal created!','success'); return redirect(url_for('crm_deals'))
    with get_db() as db:
        contacts = db.execute('SELECT id,name FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
    return render_template('crm_deal_form.html', user=user, deal=None, contacts=contacts,
                           stages=DEAL_STAGES, unread=unread(user['id']))

@app.route('/crm/deals/<int:did>/edit', methods=['GET','POST'])
@login_required
def crm_edit_deal(did):
    user = get_current_user()
    with get_db() as db:
        deal = db.execute('SELECT * FROM deals WHERE id=%s AND user_id=%s',(did,user['id'])).fetchone()
        contacts = db.execute('SELECT id,name FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
    if not deal: return redirect(url_for('crm_deals'))
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('UPDATE deals SET title=%s,contact_id=%s,value=%s,stage=%s,probability=%s,close_date=%s,owner=%s,notes=%s WHERE id=%s AND user_id=%s',
                       (f.get('title'),f.get('contact_id') or None,float(f.get('value',0) or 0),
                        f.get('stage'),int(f.get('probability',10) or 10),
                        f.get('close_date') or None,f.get('owner'),f.get('notes',''),did,user['id']))
        flash('Deal updated!','success'); return redirect(url_for('crm_deals'))
    return render_template('crm_deal_form.html', user=user, deal=deal, contacts=contacts,
                           stages=DEAL_STAGES, unread=unread(user['id']))

@app.route('/crm/deals/<int:did>/delete', methods=['POST'])
@login_required
def crm_delete_deal(did):
    user = get_current_user()
    with get_db() as db:
        db.execute('DELETE FROM deals WHERE id=%s AND user_id=%s',(did,user['id']))
    flash('Deal deleted.','success'); return redirect(url_for('crm_deals'))

# ── ACTIVITIES ────────────────────────────────────────────
@app.route('/crm/activities')
@login_required
def crm_activities():
    user = get_current_user()
    with get_db() as db:
        activities = db.execute('''SELECT a.*,c.name as contact_name FROM activities a
                                   LEFT JOIN contacts c ON a.contact_id=c.id
                                   WHERE a.user_id=%s ORDER BY a.created_at DESC''',(user['id'],)).fetchall()
        contacts = db.execute('SELECT id,name FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
    return render_template('crm_activities.html', user=user, activities=activities,
                           contacts=contacts, types=ACTIVITY_TYPES, unread=unread(user['id']))

@app.route('/crm/activities/new', methods=['GET','POST'])
@login_required
def crm_new_activity():
    user = get_current_user()
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('INSERT INTO activities (user_id,contact_id,deal_id,type,subject,notes,due_date,completed) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       (user['id'],f.get('contact_id') or None,f.get('deal_id') or None,
                        f.get('type'),f.get('subject'),f.get('notes',''),
                        f.get('due_date') or None,1 if f.get('completed') else 0))
        flash('Activity logged!','success'); return redirect(url_for('crm_activities'))
    with get_db() as db:
        contacts = db.execute('SELECT id,name FROM contacts WHERE user_id=%s',(user['id'],)).fetchall()
        deals    = db.execute('SELECT id,title FROM deals WHERE user_id=%s',(user['id'],)).fetchall()
    return render_template('crm_activity_form.html', user=user, activity=None,
                           contacts=contacts, deals=deals, types=ACTIVITY_TYPES, unread=unread(user['id']))

@app.route('/crm/activities/<int:aid>/complete', methods=['POST'])
@login_required
def crm_complete_activity(aid):
    user = get_current_user()
    with get_db() as db:
        db.execute('UPDATE activities SET completed=1 WHERE id=%s AND user_id=%s',(aid,user['id']))
    flash('Marked complete!','success'); return redirect(url_for('crm_activities'))

# ── TASKS ─────────────────────────────────────────────────
@app.route('/crm/tasks')
@login_required
def crm_tasks():
    user = get_current_user()
    status_f = request.args.get('status','open')
    with get_db() as db:
        tasks = db.execute('SELECT * FROM tasks WHERE user_id=%s AND status=%s ORDER BY due_date,priority',(user['id'],status_f)).fetchall()
    return render_template('crm_tasks.html', user=user, tasks=tasks, status_f=status_f, unread=unread(user['id']))

@app.route('/crm/tasks/new', methods=['GET','POST'])
@login_required
def crm_new_task():
    user = get_current_user()
    if request.method=='POST':
        f = request.form
        with get_db() as db:
            db.execute('INSERT INTO tasks (user_id,title,related_to,due_date,priority,status) VALUES (%s,%s,%s,%s,%s,%s)',
                       (user['id'],f.get('title'),f.get('related_to',''),
                        f.get('due_date') or None,f.get('priority','medium'),'open'))
        flash('Task added!','success'); return redirect(url_for('crm_tasks'))
    return render_template('crm_task_form.html', user=user, unread=unread(user['id']))

@app.route('/crm/tasks/<int:tid>/complete', methods=['POST'])
@login_required
def crm_complete_task(tid):
    user = get_current_user()
    with get_db() as db:
        db.execute("UPDATE tasks SET status='done' WHERE id=%s AND user_id=%s",(tid,user['id']))
    flash('Task done!','success'); return redirect(url_for('crm_tasks'))

@app.route('/crm/tasks/<int:tid>/delete', methods=['POST'])
@login_required
def crm_delete_task(tid):
    user = get_current_user()
    with get_db() as db:
        db.execute('DELETE FROM tasks WHERE id=%s AND user_id=%s',(tid,user['id']))
    flash('Task deleted.','success'); return redirect(url_for('crm_tasks'))

# ── CRM ANALYTICS ─────────────────────────────────────────
@app.route('/crm/analytics')
@login_required
def crm_analytics():
    user = get_current_user()
    with get_db() as db:
        stage_data  = db.execute('SELECT stage,COUNT(*) as cnt,SUM(value) as val FROM deals WHERE user_id=%s GROUP BY stage',(user['id'],)).fetchall()
        source_data = db.execute('SELECT source,COUNT(*) as cnt FROM contacts WHERE user_id=%s GROUP BY source ORDER BY cnt DESC',(user['id'],)).fetchall()
        monthly     = db.execute("""SELECT TO_CHAR(created_at,'YYYY-MM') as mo, COUNT(*) as cnt
                                    FROM contacts WHERE user_id=%s GROUP BY mo ORDER BY mo DESC LIMIT 6""",(user['id'],)).fetchall()
        top_deals   = db.execute("SELECT * FROM deals WHERE user_id=%s AND stage='closed_won' ORDER BY value DESC LIMIT 5",(user['id'],)).fetchall()
        won         = db.execute("SELECT COUNT(*),SUM(value) FROM deals WHERE user_id=%s AND stage='closed_won'",(user['id'],)).fetchone()
        lost        = db.execute("SELECT COUNT(*) FROM deals WHERE user_id=%s AND stage='closed_lost'",(user['id'],)).fetchone()[0]
        total_d     = db.execute('SELECT COUNT(*) FROM deals WHERE user_id=%s',(user['id'],)).fetchone()[0]
        avg_deal    = (won[1] or 0)/won[0] if won[0] else 0
        # Smart insights
        insights = []
        for c in db.execute('SELECT * FROM campaigns WHERE user_id=%s',(user['id'],)).fetchall():
            if c['spent']>5000 and c['clicks']>0 and c['conversions']/c['clicks']<0.02:
                insights.append({'type':'warning','msg':f'Campaign "{c["name"]}" has high spend (Rs{c["spent"]:,.0f}) but low conversion rate ({c["conversions"]/c["clicks"]*100:.1f}%)'})
            if c['clicks']>0 and c['conversions']/c['clicks']>0.05:
                insights.append({'type':'success','msg':f'Campaign "{c["name"]}" is performing well — {c["conversions"]/c["clicks"]*100:.1f}% conversion rate'})
        chart = {
            'stage_labels':[r['stage'] for r in stage_data],
            'stage_vals':  [r['val'] or 0 for r in stage_data],
            'stage_cnts':  [r['cnt'] for r in stage_data],
            'src_labels':  [r['source'] for r in source_data],
            'src_cnts':    [r['cnt'] for r in source_data],
            'mo_labels':   [r['mo'] for r in monthly][::-1],
            'mo_cnts':     [r['cnt'] for r in monthly][::-1],
        }
    return render_template('crm_analytics.html', user=user, chart=json.dumps(chart),
                           top_deals=top_deals, insights=insights,
                           won_count=won[0], won_value=won[1] or 0,
                           lost_count=lost, total_deals=total_d, avg_deal=avg_deal,
                           conv_rate=round(won[0]/(won[0]+lost)*100,1) if (won[0]+lost)>0 else 0,
                           unread=unread(user['id']))

# ── SEED CRM DEMO DATA ────────────────────────────────────
def _seed_crm_demo(db, uid):
    import random
    contacts_data = [
        (uid,'Priya Sharma','priya@techcorp.in','+91 98200 11111','TechCorp India','VP Marketing','LinkedIn','customer','Kavesh'),
        (uid,'Rohan Mehta','rohan@startup.io','+91 98200 22222','LaunchPad','Founder','Organic','qualified','Kavesh'),
        (uid,'Ananya Iyer','ananya@brandco.com','+91 98200 33333','BrandCo','CMO','Referral','prospect','Kavesh'),
        (uid,'Vikram Das','vikram@retail.in','+91 98200 44444','Retail Plus','Director','Google','lead','Kavesh'),
        (uid,'Sunita Rao','sunita@fmcg.co','+91 98200 55555','FMCG Pvt Ltd','Head of Growth','Email','qualified','Kavesh'),
        (uid,'Arjun Nair','arjun@finance.in','+91 98200 66666','FinEdge','CFO','LinkedIn','customer','Kavesh'),
        (uid,'Meera Pillai','meera@ecomm.com','+91 98200 77777','ShopNow','Ecom Head','Instagram','prospect','Kavesh'),
        (uid,'Karan Shah','karan@realty.in','+91 98200 88888','PropMax','MD','Cold Outreach','lead','Kavesh'),
        (uid,'Kiran Pandit','kiran@marketmosaic.in','+91 91606 43434','Market Mosaic','Founder','Direct','customer','Kavesh'),
    ]
    db.executemany('INSERT INTO contacts (user_id,name,email,phone,company,title,source,stage,owner) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', contacts_data)
    cids = [r[0] for r in db.execute('SELECT id FROM contacts WHERE user_id=%s ORDER BY id DESC LIMIT 8',(uid,)).fetchall()][::-1]
    deals_data = [
        (uid,'TechCorp Annual Contract',cids[0],480000,'closed_won',100,'2026-02-28','Kavesh'),
        (uid,'LaunchPad Brand Refresh',cids[1],120000,'negotiation',70,'2026-04-15','Kavesh'),
        (uid,'BrandCo Campaign Q2',cids[2],95000,'proposal',50,'2026-04-30','Kavesh'),
        (uid,'Retail Plus Digital Push',cids[3],60000,'qualification',30,'2026-05-15','Kavesh'),
        (uid,'FMCG Social Media Bundle',cids[4],180000,'closed_won',100,'2026-03-15','Kavesh'),
        (uid,'FinEdge SEO Package',cids[5],75000,'prospecting',20,'2026-06-01','Kavesh'),
        (uid,'ShopNow Influencer Deal',cids[6],55000,'closed_lost',0,'2026-02-01','Kavesh'),
        (uid,'PropMax Lead Generation',cids[7],90000,'proposal',60,'2026-05-01','Kavesh'),
    ]
    db.executemany('INSERT INTO deals (user_id,title,contact_id,value,stage,probability,close_date,owner) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', deals_data)
    activities_data = [
        (uid,cids[0],None,'call','Discovery call — TechCorp','Great call, moving forward',1),
        (uid,cids[1],None,'email','Sent proposal to LaunchPad','Awaiting response',0),
        (uid,cids[2],None,'meeting','Strategy meeting BrandCo','Discussed Q2 goals',1),
        (uid,cids[3],None,'follow_up','Follow up with Retail Plus','Send case studies',0),
        (uid,cids[4],None,'demo','Product demo FMCG','Very interested',1),
    ]
    db.executemany('INSERT INTO activities (user_id,contact_id,deal_id,type,subject,notes,completed) VALUES (%s,%s,%s,%s,%s,%s,%s)', activities_data)
    tasks_data = [
        (uid,'Send proposal to BrandCo','Deal: BrandCo Campaign','2026-03-25','high','open'),
        (uid,'Follow up with Retail Plus','Contact: Vikram Das','2026-03-24','medium','open'),
        (uid,'Prepare Q2 report','Internal','2026-03-28','medium','open'),
        (uid,'Call FinEdge re: SEO scope','Contact: Arjun Nair','2026-03-26','low','open'),
    ]
    db.executemany('INSERT INTO tasks (user_id,title,related_to,due_date,priority,status) VALUES (%s,%s,%s,%s,%s,%s)', tasks_data)

# ════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ════════════════════════════════════════════════════════
import urllib.request, urllib.parse, urllib.error

GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI  = os.environ.get('GOOGLE_REDIRECT_URI',
    'https://market-mosaic-v2.onrender.com/auth/google/callback')

@app.route('/auth/google')
def google_auth():
    if not GOOGLE_CLIENT_ID:
        flash('Google login is not configured yet.', 'error')
        return redirect(url_for('login'))
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    params = urllib.parse.urlencode({
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'offline',
    })
    return redirect(f'https://accounts.google.com/o/oauth2/v2/auth?{params}')

@app.route('/auth/google/callback')
def google_callback():
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('OAuth state mismatch. Please try again.', 'error')
        return redirect(url_for('login'))
    code = request.args.get('code')
    if not code:
        flash('Google login was cancelled.', 'warning')
        return redirect(url_for('login'))
    try:
        # Exchange code for token
        token_data = urllib.parse.urlencode({
            'code': code, 'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code',
        }).encode()
        req = urllib.request.Request(
            'https://oauth2.googleapis.com/token', data=token_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req) as r:
            token_resp = json.loads(r.read())
        access_token = token_resp['access_token']
        # Get user info
        info_req = urllib.request.Request(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {access_token}'})
        with urllib.request.urlopen(info_req) as r:
            info = json.loads(r.read())
        email = info['email'].lower()
        name  = info.get('name', email.split('@')[0].title())
        with get_db() as db:
            user = db.execute('SELECT * FROM users WHERE email=%s', (email,)).fetchone()
            if not user:
                api_key = 'mm_' + secrets.token_hex(24)
                db.execute('INSERT INTO users (name,company,email,password,api_key) VALUES (%s,%s,%s,%s,%s)',
                           (name, '', email, generate_password_hash(secrets.token_hex(16)), api_key))
                user = db.execute('SELECT * FROM users WHERE email=%s', (email,)).fetchone()
                _seed_demo(db, user['id'])
                _seed_crm_demo(db, user['id'])
            user_id   = user['id']
            user_name = user['name']
        session['user_id']   = user_id
        session['user_name'] = user_name
        flash(f'Welcome, {user_name}!', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        import traceback; app.logger.error(f'Google OAuth error: {e}\n{traceback.format_exc()}')
        flash(f'Google login failed: {str(e)}', 'error')
        return redirect(url_for('login'))


# ════════════════════════════════════════════════════════
# CLIENT PORTAL
# ════════════════════════════════════════════════════════
def client_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'client_id' not in session:
            return redirect(url_for('client_login'))
        return f(*a, **kw)
    return dec

def get_client():
    if 'client_id' in session:
        with get_db() as db:
            return db.execute('SELECT * FROM clients WHERE id=%s', (session['client_id'],)).fetchone()
    return None

# clients table now in init_db()

@app.route('/client/login', methods=['GET', 'POST'])
def client_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pwd   = request.form.get('password', '')
        with get_db() as db:
            c = db.execute('SELECT * FROM clients WHERE email=%s', (email,)).fetchone()
        if c and check_password_hash(c['password'], pwd):
            session['client_id'] = c['id']
            return redirect(url_for('client_dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('client_login.html', user=None)

@app.route('/client/logout')
def client_logout():
    session.pop('client_id', None)
    return redirect(url_for('client_login'))

@app.route('/client/dashboard')
@client_required
def client_dashboard():
    c = get_client()
    with get_db() as db:
        aid = c['agency_user_id']
        campaigns = db.execute('SELECT * FROM campaigns WHERE user_id=%s', (aid,)).fetchall()
        leads     = db.execute('SELECT * FROM leads WHERE user_id=%s', (aid,)).fetchall()
        deals     = db.execute('SELECT * FROM deals WHERE user_id=%s', (aid,)).fetchall()
    return render_template('client_dashboard.html', client=dict(c),
        campaigns=campaigns, leads=leads, deals=deals,
        now=datetime.now().strftime('%Y-%m-%d'))

@app.route('/dashboard/clients')
@login_required
def client_list():
    user = get_current_user()
    with get_db() as db:
        clients = db.execute('SELECT * FROM clients WHERE agency_user_id=%s ORDER BY created_at DESC', (user['id'],)).fetchall()
    return render_template('client_list.html', user=user, clients=clients, unread=unread(user['id']))

@app.route('/dashboard/clients/new', methods=['GET', 'POST'])
@login_required
def new_client():
    user = get_current_user()
    if request.method == 'POST':
        email   = request.form.get('email', '').strip().lower()
        name    = request.form.get('name', '').strip()
        company = request.form.get('company', '').strip()
        pwd     = request.form.get('password', '')
        try:
            with get_db() as db:
                db.execute('INSERT INTO clients (agency_user_id,name,company,email,password) VALUES (%s,%s,%s,%s,%s)',
                           (user['id'], name, company, email, generate_password_hash(pwd)))
            flash(f'Client portal created for {name}. Login URL: /client/login', 'success')
            return redirect(url_for('client_list'))
        except Exception:
            flash('That email is already registered as a client.', 'error')
    return render_template('new_client.html', user=user, unread=unread(user['id']))

@app.route('/dashboard/clients/<int:cid>/delete', methods=['POST'])
@login_required
def delete_client(cid):
    user = get_current_user()
    with get_db() as db:
        db.execute('DELETE FROM clients WHERE id=%s AND agency_user_id=%s', (cid, user['id']))
    flash('Client removed.', 'success')
    return redirect(url_for('client_list'))


# ════════════════════════════════════════════════════════
# EMAIL CAMPAIGNS (via Resend.com — free 3000/month)
# ════════════════════════════════════════════════════════
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
FROM_EMAIL     = os.environ.get('FROM_EMAIL', 'onboarding@resend.dev')

def send_resend_email(to_email, subject, html_body):
    """Send email via Resend API. Returns (success, error_msg)."""
    if not RESEND_API_KEY:
        return False, 'RESEND_API_KEY not set'
    try:
        payload = json.dumps({
            'from': f'Market Mosaic <{FROM_EMAIL}>',
            'to': [to_email],
            'subject': subject,
            'html': html_body,
        }).encode()
        req = urllib.request.Request(
            'https://api.resend.com/emails',
            data=payload,
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json',
            })
        with urllib.request.urlopen(req) as r:
            return True, None
    except Exception as e:
        return False, str(e)

# email tables now in init_db()

@app.route('/dashboard/email-campaigns')
@login_required
def email_campaigns():
    user = get_current_user()
    with get_db() as db:
        templates = db.execute('SELECT * FROM email_templates WHERE user_id=%s ORDER BY created_at DESC', (user['id'],)).fetchall()
        sent      = db.execute('SELECT * FROM sent_emails WHERE user_id=%s ORDER BY sent_at DESC LIMIT 50', (user['id'],)).fetchall()
        contacts  = db.execute('SELECT name,email FROM leads WHERE user_id=%s UNION SELECT name,email FROM contacts WHERE user_id=%s', (user['id'], user['id'])).fetchall()
    return render_template('email_campaigns.html', user=user,
        templates=templates, sent=sent, contacts=contacts,
        resend_ok=bool(RESEND_API_KEY), unread=unread(user['id']))

@app.route('/dashboard/email-campaigns/template/new', methods=['GET', 'POST'])
@login_required
def new_email_template():
    user = get_current_user()
    if request.method == 'POST':
        with get_db() as db:
            db.execute('INSERT INTO email_templates (user_id,name,subject,body_html) VALUES (%s,%s,%s,%s)',
                       (user['id'], request.form['name'], request.form['subject'], request.form['body_html']))
        flash('Template saved.', 'success')
        return redirect(url_for('email_campaigns'))
    return render_template('new_email_template.html', user=user, unread=unread(user['id']))

@app.route('/dashboard/email-campaigns/send', methods=['POST'])
@login_required
def send_email_campaign():
    user     = get_current_user()
    tid      = request.form.get('template_id')
    to_email = request.form.get('to_email', '').strip()
    to_name  = request.form.get('to_name', '').strip()
    with get_db() as db:
        tmpl = db.execute('SELECT * FROM email_templates WHERE id=%s AND user_id=%s', (tid, user['id'])).fetchone()
    if not tmpl or not to_email:
        flash('Template and recipient email are required.', 'error')
        return redirect(url_for('email_campaigns'))
    subject  = tmpl['subject'].replace('{{name}}', to_name)
    body     = tmpl['body_html'].replace('{{name}}', to_name)
    if RESEND_API_KEY:
        ok, err = send_resend_email(to_email, subject, body)
        status = 'sent' if ok else 'failed'
    else:
        ok, err, status = True, None, 'simulated'
    with get_db() as db:
        db.execute('INSERT INTO sent_emails (user_id,to_email,to_name,subject,template_name,status,error) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                   (user['id'], to_email, to_name, subject, tmpl['name'], status, err or ''))
    if status == 'sent':
        flash(f'Email sent to {to_email}.', 'success')
    elif status == 'simulated':
        flash(f'Email simulated (add RESEND_API_KEY to send real emails).', 'info')
    else:
        flash(f'Send failed: {err}', 'error')
    return redirect(url_for('email_campaigns'))

def seed_email_templates(uid):
    """Seed 4 starter templates for new users."""
    templates = [
        ('Welcome Email', 'Welcome to Market Mosaic, {{name}}!',
         '<h2>Welcome aboard! 🎉</h2><p>Hi {{name}},</p><p>We\'re thrilled to have you. Your growth journey starts now.</p>'),
        ('Monthly Report', 'Your Monthly Marketing Report',
         '<h2>Monthly Highlights</h2><p>Hi {{name}},</p><p>Here\'s a summary of your campaign performance this month.</p>'),
        ('Proposal Follow-up', 'Following up on your proposal',
         '<p>Hi {{name}},</p><p>Just checking in on the proposal we sent. Happy to answer any questions!</p>'),
        ('Campaign Launch', '🚀 Your campaign is live!',
         '<p>Hi {{name}},</p><p>Your campaign just went live. We\'ll update you with results in 48 hours.</p>'),
    ]
    with get_db() as db:
        for name, subj, body in templates:
            db.execute('INSERT INTO email_templates (user_id,name,subject,body_html) VALUES (%s,%s,%s,%s)',
                       (uid, name, subj, body))

