import http.server
import socketserver
import json
import csv
import os
import sys
import time
import secrets
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PORT = 5000
HOST = "0.0.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
CSV_PATH = os.path.join(DB_DIR, "leads.csv")
JSON_PATH = os.path.join(DB_DIR, "leads.json")
BLOGS_PATH = os.path.join(DB_DIR, "blogs.json")

os.makedirs(DB_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOGO_SRC = r"C:\Users\SHIV\.gemini\antigravity\brain\cd4f5d02-e6d8-4c54-96fd-d800a331c97f\.user_uploaded\media_1791565532574.jpg"
LOGO_DEST = os.path.join(BASE_DIR, "logo.jpg")
if os.path.exists(LOGO_SRC):
    try:
        import shutil
        shutil.copyfile(LOGO_SRC, LOGO_DEST)
    except Exception:
        pass

# ================= IN-MEMORY ANTI-DOS RATE LIMITER =================
_RATE_LIMIT_LOCK = threading.Lock()
_IP_REQUEST_TIMESTAMPS = defaultdict(list)
_AUTH_FAILURES = defaultdict(list)
_ACTIVE_SESSIONS = set()
_TOTAL_REQUESTS_BLOCKED = 0
_TOTAL_REQUESTS_PROCESSED = 0

def check_rate_limit(ip, max_requests=60, window_seconds=3600):
    """Sliding-window in-memory rate limiter for general API requests to prevent DoS (60 requests/hour)"""
    global _TOTAL_REQUESTS_BLOCKED, _TOTAL_REQUESTS_PROCESSED
    now = time.time()
    with _RATE_LIMIT_LOCK:
        _TOTAL_REQUESTS_PROCESSED += 1
        timestamps = _IP_REQUEST_TIMESTAMPS[ip]
        valid_ts = [t for t in timestamps if now - t < window_seconds]
        _IP_REQUEST_TIMESTAMPS[ip] = valid_ts
        if len(valid_ts) >= max_requests:
            _TOTAL_REQUESTS_BLOCKED += 1
            return False
        _IP_REQUEST_TIMESTAMPS[ip].append(now)
        return True

def is_auth_locked(ip, max_attempts=5, lockout_seconds=900):
    """Check if IP is temporarily locked out due to repeated failed login attempts (Brute-Force defense)"""
    now = time.time()
    with _RATE_LIMIT_LOCK:
        attempts = _AUTH_FAILURES[ip]
        valid_attempts = [t for t in attempts if now - t < lockout_seconds]
        _AUTH_FAILURES[ip] = valid_attempts
        return len(valid_attempts) >= max_attempts

def record_auth_failure(ip):
    with _RATE_LIMIT_LOCK:
        _AUTH_FAILURES[ip].append(time.time())

def clear_auth_failures(ip):
    with _RATE_LIMIT_LOCK:
        _AUTH_FAILURES.pop(ip, None)

def get_rate_limiter_stats():
    now = time.time()
    with _RATE_LIMIT_LOCK:
        active_ips = sum(1 for ip, ts in _IP_REQUEST_TIMESTAMPS.items() if any(now - t < 3600 for t in ts))
        locked_ips = sum(1 for ip, att in _AUTH_FAILURES.items() if len([t for t in att if now - t < 900]) >= 5)
        return {
            "status": "active",
            "defense_mode": "Anti-DoS In-Memory Shield",
            "algorithm": "Sliding-Window Token Filter",
            "active_tracked_ips": active_ips,
            "blocked_ips_count": locked_ips,
            "total_requests_processed": _TOTAL_REQUESTS_PROCESSED,
            "total_requests_blocked": _TOTAL_REQUESTS_BLOCKED,
            "api_rate_limit": "60 requests / 1 hour (3600s) per IP",
            "auth_rate_limit": "5 failed attempts / 15 minutes per IP lockout",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

def get_admin_credentials():
    username = "admin"
    password = "shiv21212929@"
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                username = str(cfg.get("admin_username", "admin")).strip()
                password = str(cfg.get("owner_pin", "shiv21212929@")).strip()
        except Exception:
            pass
    return username, password

def get_owner_pin():
    _, pwd = get_admin_credentials()
    return pwd

def set_owner_pin(new_pin):
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    cfg["owner_pin"] = new_pin
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def set_admin_credentials(new_username, new_password):
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if new_username:
        cfg["admin_username"] = new_username
    if new_password:
        cfg["owner_pin"] = new_password
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# Ensure CSV header exists
if not os.path.exists(CSV_PATH):
    with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Timestamp", "Phone", "Name", "Preferences", "Source", "IP"])

class SecureLeadHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # Enable CORS for local testing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def _send_rate_limit_error(self, retry_after=60):
        response = json.dumps({
            "status": "error",
            "error": "Rate limit exceeded (Too Many Requests). In-memory Anti-DoS defense active.",
            "retry_after": retry_after
        }).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Retry-After", str(retry_after))
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        # Strict Anti-Scraping: Block direct access to leads and credentials
        if parsed_url.path.startswith("/database/leads") or parsed_url.path == "/config.json":
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"403 Forbidden")
            return

        # Rate Limiting check on API endpoints (60 requests per hour)
        if parsed_url.path.startswith("/api/"):
            if not check_rate_limit(client_ip, max_requests=60, window_seconds=3600):
                self._send_rate_limit_error(retry_after=3600)
                return

        if parsed_url.path == "/api/security/stats":
            stats = get_rate_limiter_stats()
            response = json.dumps(stats).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/live-scores":
            data = []
            try:
                import scraper
                data = scraper.get_live_scores()
            except Exception:
                pass

            if not data:
                scores_path = os.path.join(DB_DIR, "live_scores.json")
                if os.path.exists(scores_path):
                    try:
                        with open(scores_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = []

            response = json.dumps({"status": "success", "source": "Cricbuzz Live Wire", "count": len(data), "matches": data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/ball-by-ball":
            data = {}
            try:
                import scraper
                data = scraper.get_ball_by_ball()
            except Exception:
                pass

            if not data:
                bbb_path = os.path.join(DB_DIR, "ball_by_ball.json")
                if os.path.exists(bbb_path):
                    try:
                        with open(bbb_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = {}

            response = json.dumps({"status": "success", "source": "Cricbuzz Live Telemetry", "telemetry": data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/live-news":
            news_path = os.path.join(DB_DIR, "live_news.json")
            data = []
            if os.path.exists(news_path):
                try:
                    with open(news_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = []
            response = json.dumps({"status": "success", "source": "Cricbuzz News Wire", "count": len(data), "news": data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/leads":
            query_params = parse_qs(parsed_url.query)
            pin = query_params.get("pin", [None])[0] or self.headers.get("X-Owner-Pin")
            actual_pin = get_owner_pin()
            if not pin or pin != actual_pin:
                response = json.dumps({"status": "error", "message": "Unauthorized: Owner PIN required"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

            leads_list = []
            if os.path.exists(JSON_PATH):
                try:
                    with open(JSON_PATH, "r", encoding="utf-8") as jf:
                        leads_list = json.load(jf)
                except Exception:
                    leads_list = []
            response = json.dumps({"status": "success", "count": len(leads_list), "leads": leads_list}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/leads/export":
            query_params = parse_qs(parsed_url.query)
            pin = query_params.get("pin", [None])[0] or self.headers.get("X-Owner-Pin")
            actual_pin = get_owner_pin()
            if not pin or pin != actual_pin:
                response = json.dumps({"status": "error", "message": "Unauthorized: Owner PIN required"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

            csv_data = b""
            if os.path.exists(CSV_PATH):
                try:
                    with open(CSV_PATH, "rb") as cf:
                        csv_data = cf.read()
                except Exception:
                    csv_data = b""
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="shiva_solution_leads.csv"')
            self.send_header("Content-Length", str(len(csv_data)))
            self.end_headers()
            self.wfile.write(csv_data)
            return

        elif parsed_url.path == "/api/blogs":
            blogs_list = []
            if os.path.exists(BLOGS_PATH):
                try:
                    with open(BLOGS_PATH, "r", encoding="utf-8") as bf:
                        blogs_list = json.load(bf)
                except Exception:
                    blogs_list = []
            response = json.dumps({"status": "success", "count": len(blogs_list), "blogs": blogs_list}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return
        elif parsed_url.path in ("/logo.jpg", "/assets/logo.jpg"):
            target = LOGO_DEST if os.path.exists(LOGO_DEST) else LOGO_SRC
            if os.path.exists(target):
                try:
                    with open(target, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception:
                    pass

        elif parsed_url.path in ("/admin", "/admin/"):
            admin_path = os.path.join(BASE_DIR, "admin.html")
            if os.path.exists(admin_path):
                try:
                    with open(admin_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception:
                    pass

        super().do_GET()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        # Rate Limiting check on API endpoints (60 requests per hour)
        if parsed_url.path.startswith("/api/"):
            if not check_rate_limit(client_ip, max_requests=60, window_seconds=3600):
                self._send_rate_limit_error(retry_after=3600)
                return

        content_length = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            body_json = json.loads(post_body)
        except Exception:
            body_json = {}

        # 1. ADMIN USER/PASSWORD LOGIN (WITH BRUTE-FORCE LOCKOUT)
        if parsed_url.path == "/api/auth/login":
            if is_auth_locked(client_ip):
                response = json.dumps({
                    "status": "error",
                    "message": "Too many failed login attempts. IP temporarily locked out for 15 minutes to prevent brute-force attacks.",
                    "code": "IP_LOCKOUT"
                }).encode("utf-8")
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "900")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

            req_user = str(body_json.get("username", "")).strip()
            req_pass = str(body_json.get("password", "")).strip()
            exp_user, exp_pass = get_admin_credentials()

            if (req_user.lower() == exp_user.lower() or req_user.lower() == "admin") and req_pass == exp_pass:
                clear_auth_failures(client_ip)
                token = f"shiva_token_{secrets.token_hex(16)}"
                _ACTIVE_SESSIONS.add(token)
                response = json.dumps({
                    "status": "success",
                    "message": "SHIVA SOLUTION Admin Authenticated Successfully",
                    "token": token,
                    "username": exp_user
                }).encode("utf-8")
                self.send_response(200)
            else:
                record_auth_failure(client_ip)
                response = json.dumps({
                    "status": "error",
                    "message": "Invalid username or password. Access Denied."
                }).encode("utf-8")
                self.send_response(401)

            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/auth/verify-pin":
            pin = str(body_json.get("pin", "")).strip()
            actual_pin = get_owner_pin()
            if pin and pin == actual_pin:
                response = json.dumps({"status": "success", "message": "Proprietor verified successfully"}).encode("utf-8")
                self.send_response(200)
            else:
                record_auth_failure(client_ip)
                response = json.dumps({"status": "error", "message": "Incorrect Owner Passkey. Access Denied."}).encode("utf-8")
                self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        elif parsed_url.path == "/api/auth/change-pin":
            current_pin = str(body_json.get("current_pin", "")).strip()
            new_pin = str(body_json.get("new_pin", "")).strip()
            new_user = str(body_json.get("new_username", "")).strip()
            actual_pin = get_owner_pin()

            if current_pin != actual_pin:
                response = json.dumps({"status": "error", "message": "Current Owner Passkey is incorrect."}).encode("utf-8")
                self.send_response(401)
            elif len(new_pin) < 4:
                response = json.dumps({"status": "error", "message": "New Passkey must be at least 4 characters long."}).encode("utf-8")
                self.send_response(400)
            else:
                set_admin_credentials(new_user or None, new_pin)
                response = json.dumps({"status": "success", "message": "Admin credentials updated successfully in config.json!"}).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        # 2. BLOG CRUD API (CREATE / EDIT BLOGS)
        elif parsed_url.path == "/api/blogs":
            title = str(body_json.get("title", "")).strip()
            if not title:
                response = json.dumps({"status": "error", "message": "Blog title is required"}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

            blog_id = str(body_json.get("id", "")).strip()
            if not blog_id:
                blog_id = f"blog-{int(time.time() * 1000)}"

            blog_item = {
                "id": blog_id,
                "title": title,
                "category": str(body_json.get("category", "Today Live Match")).strip(),
                "emoji": str(body_json.get("emoji", "🏏")).strip(),
                "author": str(body_json.get("author", "SHIVA SOLUTION Editorial")).strip(),
                "date": str(body_json.get("date", datetime.now().strftime("%Y-%m-%d"))).strip(),
                "readTime": str(body_json.get("readTime", "4 min read")).strip(),
                "excerpt": str(body_json.get("excerpt", "")).strip(),
                "content": str(body_json.get("content", "")).strip(),
                "keywords": body_json.get("keywords", ["cricket", "SHIVA SOLUTION"])
            }

            blogs = []
            if os.path.exists(BLOGS_PATH):
                try:
                    with open(BLOGS_PATH, "r", encoding="utf-8") as bf:
                        blogs = json.load(bf)
                except Exception:
                    blogs = []

            # Check if updating existing
            found_idx = -1
            for i, b in enumerate(blogs):
                if b.get("id") == blog_id:
                    found_idx = i
                    break

            if found_idx >= 0:
                blogs[found_idx] = blog_item
            else:
                blogs.insert(0, blog_item)

            try:
                with open(BLOGS_PATH, "w", encoding="utf-8") as bf:
                    json.dump(blogs, bf, indent=2)
            except Exception as e:
                print(f"[Error saving blog]: {e}")

            response = json.dumps({"status": "success", "message": "Blog post published safely", "blog": blog_item}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        # 3. CUSTOMER LEADS SUBMISSION
        elif parsed_url.path == "/api/leads":
            try:
                data = json.loads(post_body)
            except Exception:
                data = parse_qs(post_body)
                data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in data.items()}

            phone = str(data.get("phone", "")).strip()
            name = str(data.get("name", "Customer")).strip()
            preferences = str(data.get("preferences", "Cricket Alerts")).strip()
            source = str(data.get("source", "Website")).strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lead_id = f"lead_{int(datetime.now().timestamp() * 1000)}"

            if phone:
                # Append to database/leads.csv
                try:
                    with open(CSV_PATH, mode="a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([lead_id, timestamp, f"+91 {phone}", name, preferences, source, client_ip])
                except Exception as e:
                    print(f"[ERROR writing CSV]: {e}")

                # Append to database/leads.json
                try:
                    leads_list = []
                    if os.path.exists(JSON_PATH):
                        with open(JSON_PATH, "r", encoding="utf-8") as jf:
                            try:
                                leads_list = json.load(jf)
                            except Exception:
                                leads_list = []
                    leads_list.insert(0, {
                        "id": lead_id,
                        "timestamp": timestamp,
                        "phone": f"+91 {phone}",
                        "name": name,
                        "preferences": preferences,
                        "source": source,
                        "ip": client_ip
                    })
                    with open(JSON_PATH, "w", encoding="utf-8") as jf:
                        json.dump(leads_list, jf, indent=2)
                except Exception as e:
                    print(f"[ERROR writing JSON]: {e}")

                print(f"[SUCCESS] New Lead Saved: +91 {phone} ({preferences}) at {timestamp}")

                response = json.dumps({"status": "success", "message": "Lead saved safely in database folder", "id": lead_id}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            else:
                response = json.dumps({"status": "error", "message": "Phone number is required"}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

        super().do_POST()

    def do_DELETE(self):
        parsed_url = urlparse(self.path)
        client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

        if parsed_url.path.startswith("/api/"):
            if not check_rate_limit(client_ip, max_requests=60, window_seconds=60):
                self._send_rate_limit_error(retry_after=60)
                return

        if parsed_url.path == "/api/blogs":
            query_params = parse_qs(parsed_url.query)
            target_id = query_params.get("id", [None])[0]

            if not target_id:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    try:
                        b_json = json.loads(self.rfile.read(content_length).decode("utf-8"))
                        target_id = b_json.get("id")
                    except Exception:
                        pass

            if not target_id:
                response = json.dumps({"status": "error", "message": "Blog ID is required for deletion"}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return

            blogs = []
            if os.path.exists(BLOGS_PATH):
                try:
                    with open(BLOGS_PATH, "r", encoding="utf-8") as bf:
                        blogs = json.load(bf)
                except Exception:
                    blogs = []

            filtered = [b for b in blogs if str(b.get("id")) != str(target_id)]
            try:
                with open(BLOGS_PATH, "w", encoding="utf-8") as bf:
                    json.dump(filtered, bf, indent=2)
            except Exception as e:
                print(f"[Error deleting blog]: {e}")

            response = json.dumps({"status": "success", "message": f"Blog {target_id} deleted successfully"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    print("=" * 68)
    print(" 🔱 SHIVA SOLUTION - ENTERPRISE SERVER & ANTI-DOS SHIELD")
    print("=" * 68)
    print(f" * Website Live:            http://localhost:{PORT}")
    print(f" * Public Blog Hub:         http://localhost:{PORT}/blog.html")
    print(f" * NextJS Shadcn Admin:     http://localhost:{PORT}/admin.html")
    print(f" * In-Memory Anti-DoS:      ACTIVE (60 req/min API, 5/15min Auth Lockout)")
    print(f" * Customer Leads File:     {CSV_PATH}")
    print("=" * 68)

    # Start Cricbuzz Real-Time Auto-Scraper Daemon Thread
    try:
        import scraper
        scraper.start_background_scraper()
    except Exception as e:
        print(f"[*] Cricbuzz Scraper Background Notice: {e}")

    with socketserver.TCPServer((HOST, PORT), SecureLeadHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server safely.")
            sys.exit(0)
