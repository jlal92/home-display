"""Generates a FAKE iCal feed (clearly fake events) relative to today, so the real
parsing path can be tested without any real calendar. Used when HD_SAMPLE=1."""
import datetime as dt


def make_sample_ics(today):
    def d(days, h=None, m=0):
        day = today + dt.timedelta(days=days)
        if h is None:
            return day.strftime("%Y%m%d")
        return day.strftime("%Y%m%d") + "T%02d%02d00" % (h, m)

    ev = []

    def add(uid, summary, start, end=None, extra=""):
        s = ["BEGIN:VEVENT", "UID:%s@sample" % uid, "SUMMARY:%s" % summary]
        if len(start) == 8:
            s.append("DTSTART;VALUE=DATE:%s" % start)
            if end:
                s.append("DTEND;VALUE=DATE:%s" % end)
        else:
            s.append("DTSTART;TZID=America/New_York:%s" % start)
            if end:
                s.append("DTEND;TZID=America/New_York:%s" % end)
        if extra:
            s.append(extra)
        s.append("END:VEVENT")
        ev.append("\r\n".join(s))

    add("a1", "SAMPLE Breakfast with Sam", d(0, 8, 0), d(0, 9, 0))
    add("a2", "SAMPLE Trash day", d(0), d(1))
    add("a3", "SAMPLE Call with the plumber\\, 2nd visit", d(0, 13, 30), d(0, 14, 0))
    add("a4", "SAMPLE Dinner at home", d(0, 18, 30), d(0, 20, 0))
    add("b1", "SAMPLE Gym", d(1, 7, 0), d(1, 8, 0), "RRULE:FREQ=WEEKLY;COUNT=6")
    add("b2", "SAMPLE Dentist", d(1, 15, 0), d(1, 16, 0))
    add("c1", "SAMPLE Trip (3 days, all day)", d(2), d(5))
    add("c2", "SAMPLE Movie night with a very long title that should be cut off with an ellipsis", d(3, 19, 0), d(3, 21, 30))
    add("c3", "SAMPLE Cancelled thing (must not show)", d(2, 10, 0), d(2, 11, 0), "STATUS:CANCELLED")
    add("t1", "SAMPLE Road trip (timed, several days)", d(1, 7, 0), d(4, 20, 0))
    add("p1", "SAMPLE Yesterday lunch", d(-1, 12, 0), d(-1, 13, 0))
    add("d1", "SAMPLE Late party past midnight", d(4, 22, 0), d(5, 1, 0))
    add("d2", "SAMPLE Brunch", d(5, 11, 0), d(5, 12, 30))
    add("d3", "SAMPLE Weekly planning", d(6, 9, 0), d(6, 9, 30), "RRULE:FREQ=DAILY;COUNT=3")

    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//home-display sample//EN\r\n" + "\r\n".join(ev) + "\r\nEND:VCALENDAR\r\n"
