# Deploying the demo

The goal is a URL a reviewer can click.

**On a paid Railway plan, use Railway.** It gives you two things the free
options can't: no cold starts, and a persistent volume — which means the queue,
traces and metrics survive restarts instead of resetting to zero every time.

---

## Railway (recommended on a paid plan)

```bash
cd ~/figma-test/email-agent
git init && git add -A && git commit -m "Email production agent"
gh repo create email-agent --private --source=. --push
```

Then in Railway: **New Project → Deploy from GitHub repo**.

### If the build fails with "No start command detected"

Railway now builds with **Railpack**, which sniffs for FastAPI, Flask or Django
and starts them with uvicorn or gunicorn. This app is a stdlib `http.server`, so
none of those detectors fire.

Four launch paths are included so it boots whichever builder runs:

| File | Read by |
|---|---|
| `railpack.json` | Railpack (current Railway builder) |
| `railway.json` | Railway's own deploy config |
| `Procfile` | Heroku-style buildpacks |
| `main.py` | Railpack's last-resort fallback — it runs `main.py` from the project root |

`main.py` is the belt-and-braces one: even with no config recognised at all,
Railpack will execute it, and it just calls the same entry point as
`python -m src.webapp`.

If it still won't start, set it explicitly in the dashboard:
**Service → Settings → Deploy → Custom Start Command**:

```
python -m src.webapp
```

That overrides every config file and always wins.

### Add the volume — this is the part worth doing

**Service → Settings → Volumes → New Volume**, mount path `/data`.

Then **Variables**:

| Variable | Value |
|---|---|
| `DATA_DIR` | `/data` |
| `LLM_BACKEND` | `stub` |

`DATA_DIR` is what makes the volume useful. Everything the app *writes* — run
traces, the SQLite database, the review queue, rendered previews — moves to the
mount. Everything it *reads* — prompts, brand rules, the component manifest —
stays in the repo where it belongs under version control.

Without it the app still runs, but state lives in the container filesystem and
disappears on every deploy. With it, the Metrics tab accumulates real numbers
across sessions, which is the difference between a dashboard that demonstrates
something and one that always reads zero.

Railway sets `PORT` itself; the app binds `0.0.0.0` when it sees it.

### Cost

A single small service on Hobby sits inside the $5/month credit for a demo that
gets opened occasionally. Railway bills per second on actual consumption, so an
idle container costs very little — but the plan price is a floor, not a cap.
Volume storage is billed separately at a few cents per GB-month; this app writes
kilobytes.

---

## Render (the free option)

```bash
cd ~/figma-test/email-agent
git init && git add -A && git commit -m "Email production agent"
gh repo create email-agent --private --source=. --push    # or push manually
```

Then at render.com: **New → Blueprint → pick the repo**. `render.yaml` supplies
the rest. No credit card, no Dockerfile.

Or without the blueprint, **New → Web Service**:

| Field | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m src.webapp` |
| Instance type | Free |
| Env var | `LLM_BACKEND=stub` |

### What the free tier actually means

**It sleeps.** Free services spin down after ~15 minutes with no traffic and
take about a minute to wake. If you're sending the link to a reviewer, open it
yourself a couple of minutes beforehand so they don't sit on a loading page.

**State resets.** The filesystem is ephemeral — the queue, traces and SQLite
rows disappear on every restart. For this demo that's arguably a feature: each
reviewer gets a clean slate rather than inheriting someone else's test data.
It does mean the Metrics tab starts at zero each time.

**750 instance hours/month**, enough to keep one service available full-time.

## Why not Vercel

Wrong shape, not a limitation to work around. Vercel runs serverless functions
with an ephemeral filesystem and no long-lived process. This is a persistent
HTTP server that holds thread state and writes files. Porting it would mean
rewriting the transport layer and moving state into a hosted store — real work,
for a demo, with nothing gained.

## Railway on the free plan

Worth knowing if you ever drop off Hobby: the free plan is $1/month of usage
credit on one small replica, and a card is required at signup. If the credit
runs out the service pauses — a bad thing to discover while someone is
reviewing your take-home.

## Security

**The deployed app has no authentication.** Anyone with the URL can run the
pipeline. On the stub backend that costs nothing, which is exactly why
`render.yaml` pins `LLM_BACKEND=stub`.

**Do not put a real `ANTHROPIC_API_KEY` on a public URL.** An unauthenticated
endpoint wired to a paid API is an open invitation to spend your money. Run the
live backend locally, or add auth before hosting it.

This matters more on Railway than on Render, because a Railway service doesn't
sleep — it's reachable around the clock, and usage-based billing means someone
hammering it costs you twice: your Anthropic spend and your compute.

## Keeping it awake (optional)

A free uptime pinger (UptimeRobot and similar) hitting the URL every 10 minutes
avoids cold starts. It's a workaround rather than a supported feature, and it
burns your 750 hours faster. For a demo that gets opened a handful of times,
warming it manually beforehand is simpler and more reliable.
