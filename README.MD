# C.E.L.I.N.A

C.E.L.I.N.A is Celine's Exclusive Life Information & Network Assistant. It is a personal assistant for Celine. She installs it on her iPhone from Safari with Add to Home Screen, then opens it from that icon.

It does two things. She uploads a photo of her weekly class schedule, or types entries herself, and the app works out when to wake up, when to sleep, and which bus to take. Through the day it reminds her to eat and drink water, including while the app is closed.

## High level design

The phone app is a web app hosted on Vercel. One page shows three cards. Vercel functions build those cards, save her plan, and send reminders. Upstash Redis is the only stored data. Upstash QStash calls the app every five minutes to send due reminders. Google Maps supplies the next transit route when the home card is rebuilt.

```text
Photo of weekly schedule, or a schedule she types
        │
        ▼
  She confirms the classes
        │
        ▼
  If two entries overlap, she picks the current schedule or the new one
        │
        ▼
  Redis: schedule, settings, reminders
        │
        ├── Home page reads three cards (bus looked up from Google, cached briefly)
        │
        └── Every five minutes, QStash asks which reminders are due
                │
                ▼
         Lock screen notification
```

Wake time and bedtime are calculated from the confirmed classes and her settings. They are not stored on their own. The live bus route is cached for a few minutes, then looked up again, because the best bus changes.

## Cards

The home page shows three cards.

**Next bus.** The next time she changes place. Before the first class, that is the bus from home to campus, timed to arrive a few minutes early. After the last class, that is the bus from campus to home. Classes in between do not need a bus. A one-time entry with a date, such as a stop after class, replaces that ride on that day only. The card names the route and includes a Google Maps link she can follow.

**Wake or sleep.** Whichever comes next. In the evening the card shows bedtime. After bedtime it shows the next wake-up. Wake-up is the latest time that still leaves room to get ready, catch the bus, and arrive before class. Bedtime is that wake-up minus how long she wants to sleep. The morning alarm itself is set in the iPhone Clock app. This card tells her the time.

**Next meal or water.** The soonest drink or meal that is still ahead and not checked off. A meal is preferred when a meal and a drink are close together. She can check the card off. Checking off water early plans the next drink from that moment.

## APIs

### `GET /api/home`

Called by the web app when she opens the page.

No input.

The function returns the cached home card when it is still valid. Otherwise it rebuilds the three cards, saves them under the `home` key for a few minutes, and returns them.

```json
{
  "bus": {
    "label": "Bus to campus",
    "leaveAt": "2026-10-13T07:10:00-07:00",
    "summary": "Route 14 from Main St to Campus Dr",
    "mapsUrl": "https://www.google.com/maps/dir/?api=1&travelmode=transit"
  },
  "rest": {
    "kind": "wake",
    "at": "2026-10-13T06:25:00-07:00"
  },
  "nudge": {
    "id": "rem_water_1530",
    "kind": "water",
    "at": "2026-10-12T15:30:00-07:00"
  }
}
```

`rest.kind` is `wake` or `sleep`. `nudge.kind` is `water` or `meal`. `nudge` is `null` when nothing is due later today.

### `POST /api/schedule/scan`

Called by the web app when she uploads a photo of her weekly schedule.

Input is the image. Output is the classes read from it, for her to correct before anything is saved.

```json
{
  "classes": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    }
  ]
}
```

### `PUT /api/schedule`

Called by the web app after she confirms the classes from a photo, and again whenever she types a schedule herself. A typed entry can be a weekly class, or a one-time plan with a `date` so it does not repeat next week. The app sends the full list.

Input:

```json
{
  "classes": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    },
    {
      "date": "2026-10-13",
      "title": "Library",
      "start": "16:00",
      "end": "18:00",
      "location": "City Library"
    }
  ]
}
```

Two entries conflict when their times intersect. A weekly class uses its weekday. A one-time entry conflicts only on its date. Ending at 10:15 and starting at 10:15 is allowed.

When nothing conflicts, the function saves `schedule`, rebuilds meal and water reminders, deletes the cached `home` card, and returns the saved list. The web app then calls `GET /api/home` and shows the new cards.

```json
{
  "classes": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    }
  ]
}
```

When there is a conflict, nothing is saved yet. The function returns the schedule already stored and the schedule she just submitted.

```json
{
  "conflict": true,
  "old": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    }
  ],
  "new": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    },
    {
      "day": "monday",
      "title": "Lab",
      "start": "10:00",
      "end": "11:00",
      "location": "Building B"
    }
  ]
}
```

The web app asks her whether she wants the old schedule or the new one. She chooses, and the app sends that choice:

```json
{
  "choice": "new",
  "classes": [
    {
      "day": "monday",
      "title": "CHEM 210",
      "start": "09:00",
      "end": "10:15",
      "location": "Building A"
    },
    {
      "day": "monday",
      "title": "Lab",
      "start": "10:00",
      "end": "11:00",
      "location": "Building B"
    }
  ]
}
```

`choice` is `old` or `new`. `classes` is the matching list from the conflict response. The function writes that list, rebuilds reminders, deletes the cached `home` card, and returns the saved classes. The web app then calls `GET /api/home`.

### `PUT /api/settings`

Called by the web app when her home, campus, morning routine, sleep length, or water interval changes.

Input:

```json
{
  "home": "123 Main St",
  "campus": "Campus Dr and University Ave",
  "readyMinutes": 45,
  "arrivalBufferMinutes": 10,
  "sleepHours": 8,
  "waterIntervalMinutes": 90
}
```

The function saves `settings`, rebuilds reminders, deletes the cached `home` card, and returns the same settings object.

### `POST /api/reminders/{id}/complete`

Called by the web app when she checks off a meal or a drink.

No body. The id is the reminder id from the nudge card.

The function sets `completedAt` on that reminder. For water, it also creates the next drink from the current time, skipping class and sleep. It deletes the cached `home` card and returns the completed reminder.

```json
{
  "id": "rem_water_1530",
  "kind": "water",
  "dueAt": "2026-10-12T15:30:00-07:00",
  "completedAt": "2026-10-12T15:10:00-07:00"
}
```

### `POST /api/push`

Called by the web app once, after she allows notifications.

Input is the browser push subscription:

```json
{
  "endpoint": "https://web.push.apple.com/...",
  "keys": {
    "p256dh": "...",
    "auth": "..."
  }
}
```

The function saves it under `push` and returns:

```json
{
  "ok": true
}
```

### `POST /api/remind`

Called by QStash every five minutes. The request must include the shared secret. There is no other input.

The function loads reminders, sends a push for each one that is due and not yet sent, marks those as sent, and returns:

```json
{
  "sent": ["rem_water_1530"]
}
```

## Redis

Redis holds the plan and one short-lived copy of the home page. The plan keys have no expiry. The `home` key expires after a few minutes.

**`schedule`** is the saved list. A weekly class has a `day`. A one-time plan has a `date` and is ignored after that day.

```json
[
  {
    "day": "monday",
    "title": "CHEM 210",
    "start": "09:00",
    "end": "10:15",
    "location": "Building A"
  },
  {
    "date": "2026-10-13",
    "title": "Library",
    "start": "16:00",
    "end": "18:00",
    "location": "City Library"
  }
]
```

**`settings`** is how her mornings, sleep, and water reminders work.

```json
{
  "home": "123 Main St",
  "campus": "Campus Dr and University Ave",
  "readyMinutes": 45,
  "arrivalBufferMinutes": 10,
  "sleepHours": 8,
  "waterIntervalMinutes": 90
}
```

**`reminders`** is the list of meals and drinks. A reminder leaves the home card when its time passes or when `completedAt` is set, whichever comes first. `sentAt` stops the five-minute check from pushing it twice.

```json
[
  {
    "id": "rem_water_1530",
    "kind": "water",
    "dueAt": "2026-10-12T15:30:00-07:00",
    "completedAt": null,
    "sentAt": null
  }
]
```

**`push`** is her phone's notification subscription. Same shape as the body of `POST /api/push`.

**`home`** is the three cards returned by `GET /api/home`. It is deleted when the schedule, settings, or a completed reminder changes, and it expires on its own so the bus route is looked up again.
