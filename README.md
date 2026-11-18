# home-display

An always-on home display for an **old iPad** (built and tested on an iPad 2 with iOS 9.3.5 and Safari 9, so it
runs on almost anything). It shows a shared Google Calendar: a week agenda, a big clock, and a tappable month grid.

A small Python server on a Raspberry Pi (or any always-on Linux box) reads your calendar and serves a plain,
server-rendered page. The iPad only displays it. No apps to install, no cloud account, no framework.

## What it shows

- **Left:** today, tomorrow and the next days that have events (up to about a week), finished events dimmed, the
  current event highlighted. Titles and times only: no locations, notes or guests.
- **Right:** large clock, weekday and date, a month grid with a dot on days that have events, and a status line.
- **Tap a date:** shows the day before, that day and the day after. It goes back by itself after 60 seconds.
- **‹ ›** browse other months. **Refresh** reloads the page and re-reads the calendar. Tapping the status line
  re-reads the calendar without reloading.
- **Weather** (optional): current temperature, conditions, today's high/low and chance of rain under the date.
  Tap it for a 4-day forecast. Data comes from [Open-Meteo](https://open-meteo.com/) (free, no API key), fetched by
  the server every 30 minutes. It is hidden if no location is set or the data is more than 3 hours old.
- Night theme from 9 PM to 6 AM. The clock shifts a few pixels each hour to limit image retention.
- When the iPad wakes from sleep the page notices and refreshes itself.

## How it works

```
Google Calendar --(secret iCal address, fetched by the server)--> server/app.py --(plain HTML + ES5 JS)--> iPad
```

- The server re-reads the calendar every 15 minutes, and again (at most every 2 minutes) when the iPad asks while
  the data is stale. If Google is unreachable it keeps showing the last good data and says so on screen.
- All date, time zone and recurrence handling is done on the server (`icalendar` and `recurring-ical-events`),
  because Safari 9 has no `Intl` and no time zone support.

## Requirements

- Python 3.9+ on an always-on machine on your home network (a Raspberry Pi 3 is plenty).
- A Google Calendar's **"Secret address in iCal format"** (Calendar settings, the calendar, "Integrate calendar").
  Treat it like a password: anyone with the address can read the whole calendar.
- An iPad (or any browser) on the same network.

## Setup

```bash
git clone https://github.com/jlal92/home-display.git ~/home-display
cd ~/home-display
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

# Put the secret iCal address in this file (one line). It is git-ignored.
nano server/secret.url
chmod 600 server/secret.url

# Optional settings, also git-ignored. Example: only answer devices on your main network.
echo "HD_ALLOW=192.168.1.0/24" > server/config.env

server/run.sh        # starts the server on port 8090
```

Open `http://<host-address>:8090/` on the iPad. With no `secret.url`, the server shows clearly fake **SAMPLE**
events, so you can check the look first.

To keep it running after reboots, add two cron lines (`crontab -e`):

```
@reboot sleep 45 && /home/you/home-display/server/run.sh >/dev/null 2>&1
*/5 * * * * /home/you/home-display/server/run.sh >/dev/null 2>&1
```

`run.sh` does nothing if the server is already running. Give the host a fixed address in your router (a DHCP
reservation) so the iPad's link keeps working.

### Settings (environment variables or `server/config.env`)

| Variable | Default | Meaning |
|---|---|---|
| `HD_PORT` | `8090` | Port to listen on |
| `HD_TZ` | `America/New_York` | Time zone used for "today" and times |
| `HD_ICS_FILE` | `server/secret.url` | File holding the secret iCal address |
| `HD_REFRESH_SEC` | `900` | Background calendar re-read interval |
| `HD_ALLOW` | empty (anyone) | Comma-separated networks allowed to view the page |
| `HD_CITY` | unset | City for the weather panel (looked up once; the resolved place is printed in the log so you can check it) |
| `HD_LAT`, `HD_LON` | unset | Exact coordinates instead of `HD_CITY` (use these if the city name is ambiguous) |
| `HD_UNITS` | `fahrenheit` | `celsius` for Celsius |
| `HD_SAMPLE` | unset | `1` = fake sample events and weather instead of the real ones |

Local trial on any computer: `HD_SAMPLE=1 python server/app.py`, then open `http://localhost:8090/`.

### iPad setup

1. Open the address in Safari, then Share, then **Add to Home Screen**. Launch it from the icon for full screen.
2. Settings, General, **Date & Time**: keep "Set Automatically" on (a manual clock drifted by 40 seconds).
3. Settings, General, **Auto-Lock**: "Never" while it is in use, or lock it by hand when you leave. The page
   refreshes itself when the iPad wakes.
4. Keep it plugged in. If the home icon looks wrong after an update, delete it and add it again.

## Safari 9 limits (measured on a real iPad 2)

If you write pages for an old iPad, these were checked on the device:

| Works | Does not work |
|---|---|
| `const` (not in strict mode), template literals, `class`, destructuring, `for...of`, `Promise`, `Map`/`Set`, `Symbol` | `let`, arrow functions, default parameters, spread/rest, `async`/`await`, `**` |
| XMLHttpRequest, `localStorage` (survives closing Safari), `requestAnimationFrame`, Page Visibility | `fetch`, `Intl`, time zone options, `Object.entries`, `padStart`, service workers |
| Flexbox, `calc()`, `vh`, transitions, `-webkit-sticky` | CSS Grid, CSS variables |
| Meta refresh and `setInterval` for 12+ minutes with the screen on | Both stop while the iPad is locked; `visibilitychange` fires on wake |

This project therefore uses ES5 only (`var`, `function`, XHR) and no emoji newer than iOS 9.

The `probes/` folder has the test pages used to measure this (JavaScript support, storage, XHR, meta refresh, timers,
sleep and wake). Run `python probes/server.py 8099` on a machine on your network and open it from the iPad.

## Files

| Path | What |
|---|---|
| `server/app.py` | The server: fetch, parse, render, serve |
| `server/page.html` | The page (HTML, CSS and ES5 JS) |
| `server/run.sh` | Starts the server if it is not running (use from cron) |
| `server/sample.py` | Generates the fake SAMPLE calendar |
| `server/static/` | Home Screen icon (`python tools/make_icon.py` redraws it) |
| `probes/` | Device test pages |

## Security notes

- Plain HTTP on your home network, no login. Anyone who can reach the port sees the event titles. Do not expose it to
  the internet. If the host is also on a guest Wi-Fi, set `HD_ALLOW` to your main network.
- The secret iCal address lives only in `server/secret.url` (git-ignored). The server never logs it.
- The iOS 9 browser is unpatched. Use the iPad as a display only: no sign-ins, no passwords.

## Status

Personal project, built for one household. No license has been chosen yet, so all rights are reserved by default:
you are welcome to read it and learn from it.
