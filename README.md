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


Update check
---

Release builds check GitHub once at startup and, if a newer release exists, show a dialog
with buttons to open the releases page or dismiss it. Source and `./build.sh` builds are
unstamped ("dev") and never check. A failed check is silent; run with `--debug` to see why.

Tests
---

```
pip install -r requirements-test.txt   # or requirements-test-qt5.txt to test the Qt 5 path
python -m pytest
```

`tests/` holds fast unit tests of the core logic. `tests/ui/` drives the real tray app, offscreen
(no display needed), against a fake `.ics` feed served from the test process: reminders, the tray
menu and tooltip, the update dialog and the fallback icon.

CI runs them on Linux (Qt 6 and Qt 5) and Windows, and a release is only built and published
if they pass.

Standalone apps (work in progress)
---

Every push to master publishes a release with standalone apps for macOS (Apple Silicon
and Intel), Linux and Windows; download them from the Releases page. Pushes to other
branches publish `-beta` pre-releases, which are never marked as the latest release. The `build` workflow
also keeps them as artifacts. To build locally instead, run `./build.sh` on the machine
you want to run it on. On macOS the app lands in `dist/Nestcal.app`;
elsewhere it's `dist/nestcal/Nestcal`.

macOS
---

There are two builds per architecture. The default one needs **macOS 13 or later** (it uses Qt 6).
On macOS 11 or 12, download the `-qt5` build instead (`nestcal-macos-amd64-qt5.zip` for Intel,
`nestcal-macos-arm64-qt5.zip` for Apple Silicon); it uses Qt 5.15, which still runs there.
Without it, a too-new macOS requirement makes the app quit at once with no window and no config file.

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
