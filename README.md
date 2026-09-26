# Phishing Awareness Classroom Lab

A safe classroom simulation for the theme: **"Give me your email to send you materials of next week's lessons."**

The teacher can create a unique tracking link for each student. The app records only the assigned student name and simulation events (`opened`, `clicked`, `submitted`). **Submitted form values are consumed and discarded; they are never stored.**

## Local

```bash
python3 app.py
```

Open `http://127.0.0.1:5000/`.

Teacher dashboard: `http://127.0.0.1:5000/teacher`

Default local teacher password: `teacher123`. Change `TEACHER_PASSWORD` for any shared deployment.

## Classroom flow

1. Log in to `/teacher`.
2. Enter one student name per line and click **Generate links**.
3. Give each student only their own generated link.
4. The dashboard shows which assigned students opened the link, reached the simulated form, and submitted it.
5. Export CSV after the lesson.

Do not collect real passwords, authentication tokens, or sensitive personal information. The form values are intentionally discarded.

## Render

Push the folder to GitHub and create a Render **Web Service** from that repo. Set `TEACHER_PASSWORD` and keep `COOKIE_SECRET` set to a strong random value (the included Render Blueprint can generate one).

The app listens on Render's `PORT` and binds to `0.0.0.0`.

**Storage note:** SQLite on a typical ephemeral hosting filesystem is not durable across all restarts/redeploys. Use the CSV export for classroom results or migrate the event tables to a managed PostgreSQL database for persistent history.
