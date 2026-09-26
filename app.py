import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http import cookies
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import make_server

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, os.environ.get('DB_FILE', 'events.db'))
COOKIE_SECRET = os.environ.get('COOKIE_SECRET', 'change-me')
TEACHER_PASSWORD = os.environ.get('TEACHER_PASSWORD', 'teacher123')

SCENARIO = {
    'id': 'next-week-materials',
    'subject': "Materials for next week's lessons",
    'from_name': 'Course Materials Team',
    'from_email': 'materials-team@example-training.invalid',
    'body': """Hello!\n\nWe are preparing materials for next week's lessons.\nPlease confirm your personal details using the link below so the materials can be sent to you.\n\nConfirm details""",
    'red_flags': [
        'Unexpected request for personal information',
        'Urgency / pressure to act',
        'Sender or domain is unfamiliar',
        'The link goes to an unrelated training site',
    ],
}


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute('''CREATE TABLE IF NOT EXISTS students(
        token TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_ts TEXT NOT NULL
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_token TEXT NOT NULL,
        event TEXT NOT NULL,
        ts TEXT NOT NULL,
        scenario TEXT NOT NULL
    )''')
    con.commit()
    return con


def log_event(token, event):
    con = db()
    con.execute('INSERT INTO events(student_token,event,ts,scenario) VALUES(?,?,?,?)',
                (token, event, datetime.now(timezone.utc).isoformat(), SCENARIO['id']))
    con.commit()
    con.close()


def sign(value):
    import hashlib
    return hashlib.sha256((value + COOKIE_SECRET).encode()).hexdigest()[:24]


def student_token_from_cookie(env):
    raw = env.get('HTTP_COOKIE', '')
    c = cookies.SimpleCookie()
    c.load(raw)
    morsel = c.get('student_token')
    if not morsel:
        return None
    val = morsel.value
    try:
        token, sig = val.split('.', 1)
    except ValueError:
        return None
    return token if secrets.compare_digest(sig, sign(token)) else None


def set_student_cookie(token):
    c = cookies.SimpleCookie()
    c['student_token'] = token + '.' + sign(token)
    c['student_token']['path'] = '/'
    c['student_token']['httponly'] = True
    c['student_token']['samesite'] = 'Lax'
    return c.output(header='').strip()


def esc(s):
    return (str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            .replace('"','&quot;').replace("'", '&#39;'))


def page(title, body):
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#172033}} .wrap{{max-width:900px;margin:40px auto;padding:20px}} .card{{background:white;border:1px solid #e5e7eb;border-radius:18px;padding:28px;box-shadow:0 8px 30px rgba(0,0,0,.06)}} .muted{{color:#667085}} .mail{{border:1px solid #d0d5dd;border-radius:12px;padding:18px;background:#fafafa}} .btn{{display:inline-block;background:#111827;color:white;text-decoration:none;border:0;border-radius:10px;padding:12px 18px;font-weight:600;cursor:pointer}} input{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #cfd4dc;border-radius:9px;margin:6px 0 14px}} .warn{{background:#fff7ed;border:1px solid #fdba74;padding:14px;border-radius:10px}} .ok{{background:#ecfdf3;border:1px solid #86efac;padding:14px;border-radius:10px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid #eee;text-align:left}} code{{background:#f2f4f7;padding:2px 5px;border-radius:5px}} textarea{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #cfd4dc;border-radius:9px;min-height:140px}}
</style></head><body><div class="wrap"><div class="card">{body}</div></div></body></html>'''


def teacher_auth(env):
    raw = env.get('HTTP_COOKIE','')
    c = cookies.SimpleCookie()
    c.load(raw)
    m = c.get('teacher')
    return bool(m and secrets.compare_digest(m.value, sign('teacher')))


def respond(start_response, status, ctype, body, set_cookie=None, extra=None):
    headers = [('Content-Type', ctype), ('Content-Length', str(len(body.encode('utf-8'))))]
    if set_cookie:
        headers.append(('Set-Cookie', set_cookie))
    if extra:
        headers.extend(extra)
    start_response(status, headers)
    return [body.encode('utf-8')]


def redirect(start_response, location, set_cookie=None):
    headers=[('Location',location)]
    if set_cookie:
        headers.append(('Set-Cookie',set_cookie))
    start_response('302 Found', headers)
    return [b'']


def fetch_dashboard():
    con = db()
    students = {token: name for token, name, _ in con.execute('SELECT token,name,created_ts FROM students ORDER BY name')}
    rows = {}
    for token, event, count, last in con.execute(
        'SELECT student_token,event,COUNT(*),MAX(ts) FROM events GROUP BY student_token,event'
    ):
        rows.setdefault(token, {})[event] = {'count': count, 'last': last}
    con.close()
    result = []
    for token, name in students.items():
        events = rows.get(token, {})
        last_ts = max((v['last'] for v in events.values()), default='')
        result.append((token, name, events, last_ts))
    return result


def handle(environ, start_response):
    path = urlparse(environ.get('PATH_INFO','/')).path
    method = environ.get('REQUEST_METHOD','GET')

    if path == '/healthz':
        return respond(start_response, '200 OK', 'text/plain', 'ok')

    if path.startswith('/c/') and method == 'GET':
        token = path[len('/c/'):]
        con = db()
        row = con.execute('SELECT name FROM students WHERE token=?', (token,)).fetchone()
        con.close()
        if not row:
            return respond(start_response, '404 Not Found', 'text/plain', 'Tracking link not found')
        log_event(token, 'opened')
        return redirect(start_response, '/', set_student_cookie(token))

    if path == '/' and method == 'GET':
        token = student_token_from_cookie(environ)
        if not token:
            token = 'anon-' + secrets.token_hex(4)
            set_cookie = set_student_cookie(token)
            # Anonymous classroom preview token is not stored in students table.
        else:
            set_cookie = None
            # Avoid counting refreshes as new clicks if the tracking link was used before.
            con = db()
            exists = con.execute('SELECT 1 FROM events WHERE student_token=? AND event="opened" LIMIT 1', (token,)).fetchone()
            con.close()
            if not exists:
                log_event(token, 'opened')
        body = f'''<h1>Next week's lesson materials</h1><p class="muted">Please review this message and decide whether you trust it.</p>
        <div class="mail"><p><strong>From:</strong> {esc(SCENARIO['from_name'])} &lt;{esc(SCENARIO['from_email'])}&gt;</p><p><strong>Subject:</strong> {esc(SCENARIO['subject'])}</p>
        <pre style="white-space:pre-wrap;font:inherit">{esc(SCENARIO['body'])}</pre>
        <p><a class="btn" href="/training">Confirm details</a></p></div>
        <p class="muted" style="margin-top:20px">Classroom simulation. Do not enter real passwords or sensitive information.</p>'''
        return respond(start_response, '200 OK', 'text/html; charset=utf-8', page('Lesson Materials', body), set_cookie)

    if path == '/training' and method == 'GET':
        token = student_token_from_cookie(environ)
        if not token:
            return redirect(start_response, '/')
        log_event(token, 'clicked')
        body = '''<h1>Confirm your details</h1><div class="warn"><strong>Training simulation.</strong> This form is intentionally designed to look like a data request. Never use real credentials here.</div>
        <form method="post" action="/training"><label>Name</label><input name="name" placeholder="Your name"><label>Email</label><input name="email" type="email" placeholder="you@example.com"><label>Phone</label><input name="phone" placeholder="Optional"><button class="btn" type="submit">Submit</button></form>'''
        return respond(start_response, '200 OK', 'text/html; charset=utf-8', page('Confirm Details', body))

    if path == '/training' and method == 'POST':
        token = student_token_from_cookie(environ)
        if not token:
            return redirect(start_response, '/')
        length = int(environ.get('CONTENT_LENGTH') or 0)
        if length:
            environ['wsgi.input'].read(length)  # consume, but NEVER parse/store submitted values
        log_event(token, 'submitted')
        body = '''<h1>Simulation complete</h1><div class="ok"><strong>Your response was not stored.</strong> The lab only recorded that this student submitted the simulation.</div>
        <h2>What should you have noticed?</h2><ul>''' + ''.join(f'<li>{esc(x)}</li>' for x in SCENARIO['red_flags']) + '''</ul><p><a class="btn" href="/">Try the scenario again</a></p>'''
        return respond(start_response, '200 OK', 'text/html; charset=utf-8', page('Simulation Complete', body))

    if path == '/teacher' and method == 'GET':
        if not teacher_auth(environ):
            return redirect(start_response, '/teacher/login')
        rows = fetch_dashboard()
        body = '''<h1>Teacher dashboard</h1>
        <p>Create one private link per student. The dashboard records only the assigned student name and simulation actions, not submitted form values.</p>
        <form method="post" action="/teacher/create"><label>Student names (one per line)</label><textarea name="students" placeholder="Anna\nDavid\nMaria"></textarea><p><button class="btn" type="submit">Generate links</button></p></form>
        <p><a class="btn" href="/teacher/export">Export CSV</a> <a href="/teacher/logout">Log out</a></p>'''
        body += '<table><tr><th>Student</th><th>Opened</th><th>Clicked</th><th>Submitted</th><th>Tracking link</th><th>Last event</th></tr>'
        for token, name, events, last_ts in rows:
            base = environ.get('HTTP_X_FORWARDED_PROTO', 'http') + '://' + environ.get('HTTP_HOST', 'localhost:5000')
            link = base + '/c/' + token
            body += f'''<tr><td>{esc(name)}</td><td>{events.get('opened',{}).get('count',0)}</td><td>{events.get('clicked',{}).get('count',0)}</td><td>{events.get('submitted',{}).get('count',0)}</td><td><code>{esc(link)}</code></td><td>{esc(last_ts)}</td></tr>'''
        body += '</table>'
        return respond(start_response, '200 OK', 'text/html; charset=utf-8', page('Teacher Dashboard', body))

    if path == '/teacher/create' and method == 'POST':
        if not teacher_auth(environ):
            return redirect(start_response, '/teacher/login')
        length = int(environ.get('CONTENT_LENGTH') or 0)
        raw = environ['wsgi.input'].read(length).decode('utf-8', 'ignore') if length else ''
        names = [n.strip() for n in parse_qs(raw).get('students',[''])[0].splitlines() if n.strip()]
        con = db()
        for name in names:
            token = secrets.token_urlsafe(12)
            con.execute('INSERT INTO students(token,name,created_ts) VALUES(?,?,?)',
                        (token, name, datetime.now(timezone.utc).isoformat()))
        con.commit(); con.close()
        return redirect(start_response, '/teacher')

    if path == '/teacher/login' and method == 'GET':
        body = '<h1>Teacher login</h1><form method="post" action="/teacher/login"><label>Password</label><input type="password" name="password"><button class="btn" type="submit">Sign in</button></form>'
        return respond(start_response, '200 OK', 'text/html; charset=utf-8', page('Teacher Login', body))

    if path == '/teacher/login' and method == 'POST':
        length = int(environ.get('CONTENT_LENGTH') or 0)
        raw = environ['wsgi.input'].read(length).decode('utf-8', 'ignore') if length else ''
        password = parse_qs(raw).get('password',[''])[0]
        if secrets.compare_digest(password, TEACHER_PASSWORD):
            c = cookies.SimpleCookie(); c['teacher'] = sign('teacher'); c['teacher']['path'] = '/'; c['teacher']['httponly'] = True; c['teacher']['samesite'] = 'Lax'
            return redirect(start_response, '/teacher', c.output(header='').strip())
        return respond(start_response, '401 Unauthorized', 'text/html; charset=utf-8', page('Teacher Login', '<h1>Teacher login</h1><p class="warn">Incorrect password.</p><p><a href="/teacher/login">Try again</a></p>'))

    if path == '/teacher/logout' and method == 'GET':
        c = cookies.SimpleCookie(); c['teacher'] = ''; c['teacher']['path'] = '/'; c['teacher']['max-age'] = 0
        return redirect(start_response, '/teacher/login', c.output(header='').strip())

    if path == '/teacher/export' and method == 'GET':
        if not teacher_auth(environ):
            return redirect(start_response, '/teacher/login')
        con = db(); cur = con.execute('''SELECT s.name,e.event,e.ts,e.scenario FROM events e LEFT JOIN students s ON s.token=e.student_token ORDER BY e.id''')
        data = io.StringIO(); w = csv.writer(data); w.writerow(['student','event','timestamp_utc','scenario']); w.writerows(cur.fetchall()); con.close()
        return respond(start_response, '200 OK', 'text/csv', data.getvalue(), None, [('Content-Disposition','attachment; filename="phishing-lab-events.csv"')])

    return respond(start_response, '404 Not Found', 'text/plain', 'Not found')


if __name__ == '__main__':
    port = int(os.environ.get('PORT','5000'))
    print(f'Phishing awareness lab listening on 0.0.0.0:{port}')
    with make_server('0.0.0.0', port, handle) as httpd:
        httpd.serve_forever()
