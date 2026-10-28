Nestcal
---

A small systray app to monitor an .ics link for a calendar and notify you based on your
own personal preferences before events start.

The use-case is that I kept missing meetings because Thunderbird would only notify if I'd
added a notification or if the meeting was originally set up with a notification.

You can get an .ics link to your google calendar by following instructions here:
https://support.google.com/calendar/answer/37648?hl=en#zippy=%2Cget-your-calendar-view-only

Usage
---

Run once to create a config file at ~/.config/nestcal.ini. The app won't stay open, but now
you can go and configure it:

```
# nestcal config
# One entry per calendar under [calendars] as: label~~~~ = ICS_URL
# Use the Google Calendar "Secret address in iCal format".
# These URLs are secrets.

[settings]
# how often to poll the .ics link, in seconds
poll_interval = 300
# pop up a notification this many minutes before a meeting is due to start
lead_minutes = 2
# only consider the next 24 hours for current processing
window_hours = 24
# how long snooze should snooze for
snooze_minutes = 1
# how often, in minutes, to check for anything tha may have slipped
#  through the cracks, eg a meeting for now that was only discovered
#  during startup, or a meeting you weren't in, which has already been 
#  started, and you've just been added
check_interval = 5

[calendars]
work = https://calendar.google.com/calendar/ical/...
home = https://calendar.google.com/calendar/ical/...
```

Mouse-over the systray icon to see the next upcoming event.

Requirements
---

- Python 3 and pyqt6 or pyqt5 (failover)
- Python libs:
  - requests
  - icalendar
  - recurring_ical_events


Standalone apps (work in progress)
---

CI builds standalone apps for macOS (Apple Silicon and Intel), Linux and Windows;
see the `build` workflow's artifacts. To build locally instead, run `./build.sh`
on the machine you want to run it on. On macOS the app lands in `dist/Nestcal.app`;
elsewhere it's `dist/nestcal/Nestcal`.

macOS
---

The app lives in the menu bar only: no Dock icon, no window until a meeting is due.

Before the first launch:

1. Create `~/.config/nestcal.ini` as shown above. If it's missing, the app writes
   a stub and exits, and because there's no console you won't see why.
   Then `chmod 600 ~/.config/nestcal.ini`.
2. If you downloaded the app from CI rather than building it, macOS will refuse
   to open it because it isn't notarized. Run `xattr -cr Nestcal.app` once, or
   right-click the app and choose Open.

If nothing appears in the menu bar, run it from a terminal to see what went wrong:

```
Nestcal.app/Contents/MacOS/Nestcal --debug
```

Known limitations on macOS:

- The "next event" tooltip doesn't show in the menu bar.
- The reminder window may not appear over full-screen apps or take keyboard focus.
- Recent PyQt6 releases need a recent macOS. If the app won't start on an older
  one, report your macOS version.

Linux and Windows
---

Run `dist/nestcal/Nestcal` (`Nestcal.exe` on Windows); add `--debug` from a terminal
to see what it's doing. Create `~/.config/nestcal.ini` first, as on macOS.

- Linux: GNOME needs the AppIndicator extension to show tray icons.
- Windows: the exe isn't signed, so SmartScreen will warn on first run.
