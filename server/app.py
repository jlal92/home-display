"""home-display server: fetches a Google Calendar iCal feed and serves a
server-rendered, ES5-only page for an iPad 2 (Safari 9).

Runs on the Raspberry Pi in its own folder and venv. Plain HTTP on the LAN.

Environment (all optional):
  HD_PORT         default 8090
  HD_TZ           default America/New_York
  HD_ICS_FILE     file holding the secret iCal URL (default: <folder>/secret.url)
  HD_SAMPLE=1     use generated fake events instead of a real calendar
  HD_REFRESH_SEC  how often to re-fetch the calendar in seconds (default 900)
  HD_ALLOW        networks allowed to view the page, e.g. 192.168.1.0/24 (default: anyone who can reach the port)
  HD_CITY         city for the weather panel, e.g. "Springfield" (looked up once with Open-Meteo's geocoder)
  HD_LAT, HD_LON  exact coordinates instead of HD_CITY (more reliable when city names are ambiguous)
  HD_UNITS        fahrenheit (default) or celsius

The iCal URL is a secret: it is read from a file, never printed, never logged.
Only event titles and times are shown (no descriptions, locations, attendees).
"""
import datetime as dt
import html
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("HD_PORT", "8090"))
TZ = ZoneInfo(os.environ.get("HD_TZ", "America/New_York"))
ICS_FILE = os.environ.get("HD_ICS_FILE", os.path.join(HERE, "secret.url"))
SAMPLE = os.environ.get("HD_SAMPLE") == "1"
REFRESH_SEC = int(os.environ.get("HD_REFRESH_SEC", "900"))  # background re-read of the calendar: 15 min
MIN_REFRESH_SEC = 120  # a waking iPad may trigger a re-read, but never more often than this
DAYS_AHEAD = 8   # days shown in the agenda list
FETCH_DAYS = 125  # days ahead parsed, so the month grid can browse and mark busy days about 4 months out
PAST_DAYS = 35   # days back parsed, so tapping an earlier date this month shows what happened
BACK_PX = 50     # height of the "Back to today" row in the tapped-day view
# Pixel budget for the left column, matched to page.html. 704 px is the usable height of
# landscape Safari with its toolbars (the smallest case); 34 px is reserved for "+N more".
HDR_PX, EV_PX, NONE_PX, DAYGAP_PX = 54, 46, 40, 6
BUDGET_PX = 704 - 14 - 34

# HD_ALLOW: comma-separated networks allowed to use the page, e.g. "192.168.1.0/24". Empty = anyone who can
# reach the port. Useful when the host is on two networks (say a main LAN and a guest Wi-Fi).
import ipaddress
ALLOW = [ipaddress.ip_network(n.strip()) for n in os.environ.get("HD_ALLOW", "").split(",") if n.strip()]


def client_allowed(addr):
    if not ALLOW:
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in ALLOW)


state_lock = threading.Lock()
state = {"events": [], "ok": False, "updated": None, "error": "not loaded yet"}


# ---------- formatting helpers (the iPad has no Intl, so the server formats) ----------
def hm(d):
    h = d.hour % 12 or 12
    return "%d:%02d %s" % (h, d.minute, "AM" if d.hour < 12 else "PM")


def hm_short(d):
    """'8 PM' when on the hour, else '8:30 PM' (for the narrow 'until ...' label)."""
    return ("%d %s" % (d.hour % 12 or 12, "AM" if d.hour < 12 else "PM")) if d.minute == 0 else hm(d)


def short(s, n=90):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- calendar loading ----------
def read_ics_url():
    with open(ICS_FILE, "r", encoding="utf-8") as f:
        url = f.read().strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.startswith("https://"):
        raise ValueError("secret.url must hold an https:// or webcal:// address")
    return url


def fetch_ics_text():
    if SAMPLE:
        from sample import make_sample_ics
        return make_sample_ics(dt.datetime.now(TZ).date())
    req = Request(read_ics_url(), headers={"User-Agent": "home-display/1.0"})
    with urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def to_local_dt(v):
    """date -> (date, True); datetime -> (aware local datetime, False)."""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=TZ)
        return v.astimezone(TZ), False
    return v, True


def parse_events(ics_text, now):
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics_text)
    start_day = now.date()
    win_start = dt.datetime.combine(start_day - dt.timedelta(days=PAST_DAYS), dt.time.min, tzinfo=TZ)
    win_end = dt.datetime.combine(start_day, dt.time.min, tzinfo=TZ) + dt.timedelta(days=FETCH_DAYS)
    out = []
    for ev in recurring_ical_events.of(cal).between(win_start, win_end):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s_raw = ev.get("DTSTART").dt
        e_prop = ev.get("DTEND")
        s, all_day = to_local_dt(s_raw)
        if e_prop is not None:
            e, _ = to_local_dt(e_prop.dt)
        elif ev.get("DURATION") is not None:
            e = s + ev.get("DURATION").dt
        else:
            e = s + (dt.timedelta(days=1) if all_day else dt.timedelta(0))
        out.append({"title": short(ev.get("SUMMARY", "(no title)")), "start": s, "end": e, "all_day": all_day})
    out.sort(key=lambda x: (x["start"] if not x["all_day"] else dt.datetime.combine(x["start"], dt.time.min, tzinfo=TZ), not x["all_day"]))
    return out


refresh_lock = threading.Lock()
last_attempt = [0.0]


def do_refresh():
    """Re-read the calendar. One at a time; never raises; never logs the URL."""
    if not refresh_lock.acquire(blocking=False):
        return
    try:
        last_attempt[0] = time.time()
        now = dt.datetime.now(TZ)
        events = parse_events(fetch_ics_text(), now)
        with state_lock:
            state.update(events=events, ok=True, updated=now, error=None)
    except Exception as exc:  # log the type only: the message could contain the URL
        with state_lock:
            state["ok"] = False
            state["error"] = type(exc).__name__
        print("calendar refresh failed:", type(exc).__name__, flush=True)
    finally:
        refresh_lock.release()


def maybe_refresh():
    """Called when the iPad asks for data: re-read in the background if the data is stale enough."""
    if time.time() - last_attempt[0] >= MIN_REFRESH_SEC:
        threading.Thread(target=do_refresh, daemon=True).start()


def refresh_loop():
    while True:
        do_refresh()
        time.sleep(REFRESH_SEC)


# ---------- weather (Open-Meteo: free, no API key; fetched here because the iPad cannot do it) ----------
WX_REFRESH_SEC = 1800     # every 30 minutes
WX_MAX_AGE = 3 * 3600     # hide the weather rather than show data older than this
UNITS = os.environ.get("HD_UNITS", "fahrenheit")  # or "celsius"
LAT, LON, CITY = (os.environ.get(k, "").strip() for k in ("HD_LAT", "HD_LON", "HD_CITY"))
wx_lock = threading.Lock()
wx_state = {"data": None, "at": 0.0}
_wx_place = [None]


def wx_location():
    """(lat, lon) from HD_LAT/HD_LON, or looked up once from HD_CITY. None when weather is not configured."""
    if _wx_place[0]:
        return _wx_place[0]
    if LAT and LON:
        _wx_place[0] = (float(LAT), float(LON))
    elif CITY:
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": CITY, "count": 1, "language": "en", "format": "json"})
        with urlopen(Request(url, headers={"User-Agent": "home-display/1.0"}), timeout=20) as r:
            hit = json.loads(r.read().decode("utf-8"))["results"][0]
        _wx_place[0] = (hit["latitude"], hit["longitude"])
        # Logged so the owner can check it found the right place (the log stays on the host).
        print("weather location resolved to: %s, %s, %s" % (hit.get("name"), hit.get("admin1"), hit.get("country")), flush=True)
    return _wx_place[0]


def wx_glyph(code, is_day):
    """(glyph, word) for a WMO weather code. Glyphs are only ones that rendered on the iPad 2 (iOS 9)."""
    sun = "☀" if is_day else "★"
    if code == 0:
        return sun, "Clear"
    if code == 1:
        return sun, "Mostly clear"
    if code == 2:
        return "☁", "Partly cloudy"
    if code == 3:
        return "☁", "Cloudy"
    if code in (45, 48):
        return "☁", "Fog"
    if 51 <= code <= 57:
        return "☂", "Drizzle"
    if 61 <= code <= 67:
        return "☂", "Rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "❄", "Snow"
    if 80 <= code <= 82:
        return "☂", "Showers"
    if code >= 95:
        return "⚡", "Storms"
    return "☁", "Cloudy"


def wx_fetch():
    today = dt.datetime.now(TZ).date()
    if SAMPLE:  # fake weather so the layout can be tested without a location
        days = [{"date": (today + dt.timedelta(days=i)).isoformat(), "code": c, "hi": h, "lo": l, "rain": p}
                for i, (c, h, l, p) in enumerate([(2, 74, 58, 20), (61, 70, 60, 70), (0, 76, 57, 0), (3, 72, 59, 10)])]
        data = {"temp": 68, "code": 2, "is_day": 1, "days": days}
    else:
        lat, lon = wx_location()
        q = urlencode({
            "latitude": lat, "longitude": lon, "temperature_unit": UNITS, "timezone": TZ.key, "forecast_days": 4,
            "current": "temperature_2m,weather_code,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        })
        with urlopen(Request("https://api.open-meteo.com/v1/forecast?" + q, headers={"User-Agent": "home-display/1.0"}), timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
        d = j["daily"]
        days = [{"date": d["time"][i], "code": d["weather_code"][i], "hi": round(d["temperature_2m_max"][i]),
                 "lo": round(d["temperature_2m_min"][i]), "rain": d["precipitation_probability_max"][i]}
                for i in range(len(d["time"]))]
        c = j["current"]
        data = {"temp": round(c["temperature_2m"]), "code": c["weather_code"], "is_day": c["is_day"], "days": days}
    with wx_lock:
        wx_state["data"], wx_state["at"] = data, time.time()


def wx_loop():
    if not (SAMPLE or (LAT and LON) or CITY):
        return  # weather not configured: the page simply shows none
    while True:
        try:
            wx_fetch()
        except Exception as exc:
            print("weather refresh failed:", type(exc).__name__, flush=True)
        time.sleep(WX_REFRESH_SEC)


def wx_attr():
    """data-wx="temp|glyph|word|hi|lo|rain" for the hidden meta element, or "" when there is no fresh weather."""
    with wx_lock:
        data, at = wx_state["data"], wx_state["at"]
    if not data or time.time() - at > WX_MAX_AGE:
        return ""
    glyph, word = wx_glyph(data["code"], data["is_day"])
    d0 = data["days"][0]
    rain = "" if d0["rain"] is None else d0["rain"]
    return ' data-wx="%s"' % html.escape("|".join(str(x) for x in (data["temp"], glyph, word, d0["hi"], d0["lo"], rain)))


# ---------- rendering ----------
def day_label(day, today):
    delta = (day - today).days
    name = day.strftime("%A")
    if delta == 0:
        return "Today", day.strftime("%a %b ") + str(day.day)
    if delta == 1:
        return "Tomorrow", day.strftime("%a %b ") + str(day.day)
    if delta == -1:
        return "Yesterday", day.strftime("%a %b ") + str(day.day)
    return name, day.strftime("%b ") + str(day.day)


def events_on(events, day):
    d0 = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
    d1 = d0 + dt.timedelta(days=1)
    rows = []
    for e in events:
        if e["all_day"]:
            from_d, to_d = e["start"], e["end"]
            if to_d <= from_d:
                to_d = from_d + dt.timedelta(days=1)
            if from_d <= day < to_d:
                rows.append(e)
        else:
            if e["end"] <= e["start"]:
                if d0 <= e["start"] < d1:
                    rows.append(e)
            elif e["start"] < d1 and e["end"] > d0:
                rows.append(e)
    return rows


def render_agenda(now, center=None):
    """The left column. center=None: today and the next days that have events.
    center=<date>: the day before, that day and the day after (the iPad taps a month-grid date)."""
    with state_lock:
        events = list(state["events"])
        ok, updated, error = state["ok"], state["updated"], state["error"]
    today = now.date()
    parts = []
    used = 0
    shown_ids, hidden_ids = set(), set()
    full = False
    if center is None:
        offsets = list(range(DAYS_AHEAD))
    else:
        offsets = [(center - today).days + k for k in (-1, 0, 1)]
        parts.append('<div class="back">&larr; Back to today</div>')
        used += BACK_PX
    for i in offsets:
        day = today + dt.timedelta(days=i)
        rows = events_on(events, day)
        if center is None and i >= 2 and not rows:
            continue
        if full:
            hidden_ids.update(id(e) for e in rows)
            continue
        room = BUDGET_PX - used - HDR_PX
        need = len(rows) * EV_PX if rows else (NONE_PX if (i < 2 or center is not None) else 0)
        if room < min(need, EV_PX):  # not even the header plus one row fits
            full = True
            hidden_ids.update(id(e) for e in rows)
            continue
        if need > room:
            take = room // EV_PX
            hidden_ids.update(id(e) for e in rows[take:])
            rows = rows[:take]
            need = take * EV_PX
            full = True
        shown_ids.update(id(e) for e in rows)
        used += HDR_PX + need + DAYGAP_PX
        big, small = day_label(day, today)
        parts.append('<div class="day%s"><div class="dayhdr"><span class="dn">%s</span><span class="dd">%s</span></div>' % (
            " sel" if day == center else "", html.escape(big), html.escape(small)))
        if not rows:
            parts.append('<div class="none">Nothing planned</div>')
        for e in rows:
            if e["all_day"]:
                t, s_ts, e_ts, cls = "All day", 0, 0, "ev allday"
                s_ts = int(dt.datetime.combine(day, dt.time.min, tzinfo=TZ).timestamp())
                e_ts = s_ts + 86400
            else:
                d0 = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
                d1 = d0 + dt.timedelta(days=1)
                s_ts, e_ts, cls = int(e["start"].timestamp()), int(max(e["end"], e["start"]).timestamp()), "ev"
                if e["start"] >= d0:
                    t = hm(e["start"])
                elif e["end"] >= d1:  # a timed event that covers this whole day (middle of a trip)
                    t, cls = "All day", "ev allday"
                    s_ts = int(d0.timestamp())
                    e_ts = s_ts + 86400
                else:
                    t, cls = "until " + hm_short(e["end"]), "ev cont"
            parts.append(
                '<div class="%s" data-s="%d" data-e="%d"><span class="t">%s</span><span class="n">%s</span></div>'
                % (cls, s_ts, e_ts, html.escape(t), html.escape(e["title"]))
            )
        parts.append("</div>")
    hidden = len(hidden_ids - shown_ids)  # a multi-day event shown once is not "more"
    if hidden > 0:
        parts.append('<div class="more">+%d more</div>' % hidden)
    return build_meta(now, events, ok, updated) + "".join(parts)


def build_meta(now, events, ok, updated):
    """The hidden #meta element every fragment starts with: status, busy days for the month grid, weather."""
    today = now.date()
    stamp = hm(updated) if updated else "never"
    # Days with at least one event (for the month grid), as YYYY-MM-DD.
    busy = []
    for i in range(-PAST_DAYS, FETCH_DAYS):
        day = today + dt.timedelta(days=i)
        if events_on(events, day):
            busy.append(day.isoformat())
    return '<div id="meta" data-ok="%d" data-stamp="%s" data-now="%d" data-busy="%s"%s></div>' % (
        1 if ok else 0, html.escape(stamp), int(now.timestamp()), ",".join(busy), wx_attr())


def render_forecast(now):
    """Left column while the weather block is tapped: today plus the next three days."""
    with state_lock:
        events = list(state["events"])
        ok, updated = state["ok"], state["updated"]
    parts = [build_meta(now, events, ok, updated), '<div class="back">&larr; Back to today</div>']
    with wx_lock:
        data, at = wx_state["data"], wx_state["at"]
    if not data or time.time() - at > WX_MAX_AGE:
        parts.append('<div class="none">Weather is not available right now.</div>')
        return "".join(parts)
    today = now.date()
    for d in data["days"][:4]:
        glyph, word = wx_glyph(d["code"], True)
        day = dt.date.fromisoformat(d["date"])
        big, small = day_label(day, today)
        rain = "" if d["rain"] is None else "%d%%" % d["rain"]
        parts.append(
            '<div class="fc"><span class="fcd">%s<small>%s</small></span><span class="fci">%s %s</span>'
            '<span class="fct">%d&deg; / %d&deg;</span><span class="fcr">%s</span></div>'
            % (html.escape(big), html.escape(small), glyph, html.escape(word), d["hi"], d["lo"], rain)
        )
    parts.append('<div class="more">Rain = chance of rain</div>')
    return "".join(parts)


def render_page(now):
    with open(os.path.join(HERE, "page.html"), "r", encoding="utf-8") as f:
        page = f.read()
    return page.replace("{{AGENDA}}", render_agenda(now))


# ---------- http ----------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, filename, ctype):
        with open(os.path.join(HERE, "static", filename), "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        now = dt.datetime.now(TZ)
        if not client_allowed(self.client_address[0]):
            self._send(403, "forbidden", "text/plain")
            return
        try:
            if path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
                self._send_file("apple-touch-icon.png", "image/png")
                return
            if path == "/":
                if parse_qs(urlparse(self.path).query).get("force") and time.time() - last_attempt[0] >= 10:
                    do_refresh()  # the iPad's "Refresh" button: re-read Google before rendering (at most once per 10 s)
                self._send(200, render_page(now), "text/html; charset=utf-8")
            elif path == "/agenda":
                if parse_qs(urlparse(self.path).query).get("force"):
                    # "Tap here to refresh" on the iPad: re-read Google now (at most once per 10 s).
                    if time.time() - last_attempt[0] >= 10:
                        do_refresh()
                else:
                    maybe_refresh()  # the iPad woke up or is polling: make sure data is not stale
                self._send(200, render_agenda(now), "text/html; charset=utf-8")
            elif path == "/forecast":
                self._send(200, render_forecast(now), "text/html; charset=utf-8")
            elif path == "/day":
                # Tapped date from the month grid: that day plus the day before and after.
                raw = parse_qs(urlparse(self.path).query).get("date", [""])[0]
                try:
                    center = dt.date.fromisoformat(raw)
                except ValueError:
                    center = now.date()
                lo = now.date() - dt.timedelta(days=PAST_DAYS)
                hi = now.date() + dt.timedelta(days=FETCH_DAYS - 1)
                center = min(max(center, lo), hi)
                self._send(200, render_agenda(now, center), "text/html; charset=utf-8")
            elif path == "/health":
                with state_lock:
                    body = json.dumps({"ok": state["ok"], "updated": state["updated"].isoformat() if state["updated"] else None,
                                       "events": len(state["events"]), "error": state["error"]})
                self._send(200, body, "application/json")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as exc:
            print("request failed:", type(exc).__name__, flush=True)
            self._send(500, "error", "text/plain")

    def log_message(self, fmt, *args):
        if "/agenda" not in (args[0] if args else ""):
            print("%s %s" % (self.client_address[0], fmt % args), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=wx_loop, daemon=True).start()
    print("home-display on 0.0.0.0:%d tz=%s sample=%s" % (PORT, TZ.key, SAMPLE), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
