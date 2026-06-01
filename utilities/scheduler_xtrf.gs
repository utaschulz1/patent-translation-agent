/**
 * MAIN FUNCTION: Set this to run on a Time-Based Trigger
 * (Every 10 minutes, Mon-Fri 7h-18h GMT)
 *
 * Required Script Properties (set via Project Settings → Script Properties):
 *   XTRF_EMAIL    — your XTRF vendor portal login email
 *   XTRF_PASSWORD — your XTRF vendor portal login password
 */
function masterProjectAutomationXtrf() {
  const now = new Date();
  const hour = now.getHours();
  const day = now.getDay(); // 0=Sunday, 6=Saturday

  if (day === 0 || day === 6 || hour < 7 || hour >= 21) {
    Logger.log("Outside working hours, skipping.");
    return;
  }

  checkAndProcessOffers();
}

// ─── XTRF API ──────────────────────────────────────────────────────────────

const XTRF_BASE = 'https://comunicadk.s.xtrf.eu';

/**
 * Logs in to XTRF and returns the session cookie string, or null on failure.
 * Credentials are read from Script Properties: XTRF_EMAIL, XTRF_PASSWORD.
 */
function loginToXTRF() {
  const props = PropertiesService.getScriptProperties();
  const email = props.getProperty('XTRF_EMAIL');
  const password = props.getProperty('XTRF_PASSWORD');

  if (!email || !password) {
    Logger.log('XTRF credentials not configured. Set XTRF_EMAIL and XTRF_PASSWORD in Script Properties.');
    return null;
  }

  const response = UrlFetchApp.fetch(XTRF_BASE + '/vendors/sign-in', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ email: email, password: password }),
    muteHttpExceptions: true,
    followRedirects: false
  });

  const code = response.getResponseCode();
  if (code !== 204 && code !== 200) {
    Logger.log('XTRF login failed, HTTP ' + code + ': ' + response.getContentText());
    return null;
  }

  const allHeaders = response.getAllHeaders();
  let setCookie = allHeaders['Set-Cookie'] || allHeaders['set-cookie'] || '';
  if (Array.isArray(setCookie)) setCookie = setCookie.join('; ');

  const match = setCookie.match(/VP_PLAY_SESSION=([^;]+)/);
  if (!match) {
    Logger.log('XTRF login: no VP_PLAY_SESSION cookie in response');
    return null;
  }

  Logger.log('XTRF login successful');
  return 'VP_PLAY_SESSION=' + match[1];
}

/**
 * Makes an authenticated GET/PUT request to the XTRF vendor portal.
 */
function xtrfFetch(sessionCookie, path, method, body) {
  const options = {
    method: method || 'get',
    headers: {
      'Cookie': sessionCookie,
      'Accept': 'application/json, text/plain',
      'time-zone-offset-in-minutes': '60'
    },
    muteHttpExceptions: true
  };
  if (body !== undefined) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(body);
  }
  return UrlFetchApp.fetch(XTRF_BASE + path, options);
}

/**
 * Returns the list of available job offers from XTRF (status NEW).
 */
function getXtrfOffers(sessionCookie) {
  const response = xtrfFetch(sessionCookie, '/vendors/offers', 'get');
  if (response.getResponseCode() !== 200) {
    Logger.log('Failed to fetch offers: HTTP ' + response.getResponseCode());
    return [];
  }
  const offers = JSON.parse(response.getContentText());
  Logger.log('Found ' + offers.length + ' offer(s) on XTRF');
  return offers;
}

/**
 * Sends a PUT to accept an offer. Returns true if the server responds with name="WON".
 */
function acceptXtrfOffer(sessionCookie, offerId) {
  const response = xtrfFetch(sessionCookie, '/vendors/offers/classic/' + offerId + '/accept', 'put');
  const code = response.getResponseCode();
  if (code !== 200) {
    Logger.log('Accept offer ' + offerId + ' failed: HTTP ' + code);
    return false;
  }
  const result = JSON.parse(response.getContentText());
  Logger.log('Accept offer ' + offerId + ' result: ' + result.name);
  return result.name === 'WON';
}

/**
 * Converts an XTRF offer object into the data shape used by the calendar functions.
 * Returns null if the offer carries no hours (e.g. unpaid issues-resolution tasks).
 */
function extractDataFromOffer(offer) {
  const overview = offer.overview;
  const projectName = overview.projectName || '';

  // Extract the standard project-number token, e.g. HALA_2605_P0441
  const projMatch = projectName.match(/([a-zA-Z]+_\d+_P\d+)/);
  const projectNumber = projMatch ? projMatch[1] : projectName.replace(/^Patents \| /, '').trim();

  // Hours are in totalQuantities as unit "1h"
  const quantities = (overview.jobQuantities && overview.jobQuantities.totalQuantities) || [];
  const hoursEntry = quantities.find(function(q) { return q.unit === '1h'; });
  const hours = hoursEntry ? parseFloat(hoursEntry.value) : 0;

  // Offers with 0 hours (e.g. mandatory but unpaid issues-resolution tasks that accompany a
  // translation job) are skipped — there is nothing to schedule and no time to check.
  if (!hours || hours <= 0) {
    Logger.log('Skipping offer (no billable hours): ' + projectNumber + ' [' + offer.id + ']');
    return null;
  }

  // Format deadline as DD-MM-YYYY for compatibility with scheduleProjectInCalendar
  const dl = new Date(overview.deadline);
  const dd = String(dl.getDate()).padStart(2, '0');
  const mm = String(dl.getMonth() + 1).padStart(2, '0');
  const yyyy = dl.getFullYear();

  const sourceWordEntry = quantities.find(function(q) { return q.unit === 'source word'; });

  return {
    projectNumber: projectNumber,
    deadline: dd + '-' + mm + '-' + yyyy,
    quantity: String(hours),
    totalWords: sourceWordEntry ? sourceWordEntry.value : 0
  };
}

// ─── MAIN PROCESSING LOGIC ────────────────────────────────────────────────

/**
 * Fetches open offers from XTRF, checks calendar availability for each,
 * accepts those that fit, and schedules them immediately.
 */
function checkAndProcessOffers() {
  const sessionCookie = loginToXTRF();
  if (!sessionCookie) return;

  const offers = getXtrfOffers(sessionCookie);
  if (!offers.length) {
    Logger.log('No open offers to process.');
    return;
  }

  // claimedSlots tracks time blocked by offers accepted earlier in this same run.
  // Calendar events from previous runs are already visible to getAvailableSlots via
  // CalendarApp, so only within-run conflicts need this extra list.
  const claimedSlots = [];

  offers.forEach(function(offer) {
    const data = extractDataFromOffer(offer);
    if (!data) return;

    Logger.log('Processing offer: ' + data.projectNumber + ' | ' + data.quantity + 'h | deadline ' + data.deadline);

    const parts = data.deadline.split('-');
    const deadlineDate = new Date(parts[2], parts[1] - 1, parts[0], 13, 0, 0);

    const hoursNeeded = parseFloat(data.quantity);
    const available = getAvailableSlots(new Date(), deadlineDate, hoursNeeded, claimedSlots);

    if (available.totalFound >= hoursNeeded) {
      const accepted = acceptXtrfOffer(sessionCookie, offer.id);
      if (accepted) {
        // Accept returned "WON" — the offer is confirmed. Schedule immediately.
        scheduleProjectInCalendar(data, deadlineDate, claimedSlots);
        Logger.log('✓ Accepted and scheduled: ' + data.projectNumber);
      } else {
        // Accept did not return "WON" — the offer was likely grabbed by someone else
        // between our availability check and the PUT. Skip scheduling.
        Logger.log('✗ Offer no longer available: ' + data.projectNumber);
      }
    } else {
      Logger.log('✗ Insufficient time for ' + data.projectNumber +
        ' (need ' + hoursNeeded + 'h, found ' + available.totalFound.toFixed(2) + 'h before deadline ' + data.deadline + ')');
    }
  });
}

// ─── AVAILABILITY LOGIC ───────────────────────────────────────────────────

/**
 * Finds free slots in the 8h–13h window between start and end,
 * skipping calendar events and already-claimed slots.
 * Ignores gaps shorter than 20 minutes.
 */
function getAvailableSlots(start, end, hoursNeeded, claimedSlots) {
  claimedSlots = claimedSlots || [];
  const calendar = CalendarApp.getDefaultCalendar();
  let totalFound = 0;
  let slots = [];

  let current = new Date(start);

  while (current < end) {
    if (current.getDay() !== 0 && current.getDay() !== 6) {
      let dayStart = new Date(current);
      dayStart.setHours(8, 0, 0, 0);

      let dayEnd = new Date(current);
      dayEnd.setHours(13, 0, 0, 0);

      const now = new Date();

      if (dayEnd <= now) {
        Logger.log("Skipping past window: " + dayStart);
        current.setDate(current.getDate() + 1);
        current.setHours(0, 0, 0, 0);
        continue;
      }

      let effectiveStart = (dayStart < start) ? new Date(start) : new Date(dayStart);

      let busyIntervals = [];

      let events = calendar.getEvents(effectiveStart, dayEnd);
      events.forEach(function(e) {
        if (!e.isAllDayEvent()) {
          busyIntervals.push({ start: e.getStartTime(), end: e.getEndTime() });
        }
      });

      claimedSlots.forEach(function(claimed) {
        const overlapStart = Math.max(claimed.start.getTime(), effectiveStart.getTime());
        const overlapEnd = Math.min(claimed.end.getTime(), dayEnd.getTime());
        if (overlapEnd > overlapStart) {
          busyIntervals.push({ start: new Date(overlapStart), end: new Date(overlapEnd) });
        }
      });

      busyIntervals.sort(function(a, b) { return a.start - b.start; });

      let cursor = new Date(effectiveStart);

      for (let i = 0; i <= busyIntervals.length; i++) {
        let gapEnd = (i < busyIntervals.length)
          ? new Date(Math.min(busyIntervals[i].start.getTime(), dayEnd.getTime()))
          : new Date(dayEnd);

        if (cursor < gapEnd) {
          let gapHours = (gapEnd - cursor) / 3600000;

          if (gapHours >= (20 / 60)) {
            let actualToUse = Math.min(gapHours, hoursNeeded - totalFound);
            slots.push({ date: new Date(cursor), hours: actualToUse });
            totalFound += actualToUse;
            Logger.log("Slot added: " + cursor + " for " + actualToUse.toFixed(2) + "h");
          }
        }

        if (totalFound >= hoursNeeded) break;

        if (i < busyIntervals.length) {
          cursor = new Date(Math.max(cursor.getTime(), busyIntervals[i].end.getTime()));
        }
      }
    }

    if (totalFound >= hoursNeeded) break;
    current.setDate(current.getDate() + 1);
    current.setHours(0, 0, 0, 0);
  }

  Logger.log("getAvailableSlots result: totalFound=" + totalFound +
    " slots=" + slots.length + " hoursNeeded=" + hoursNeeded);
  return { totalFound: totalFound, slots: slots };
}

// ─── SCHEDULER ────────────────────────────────────────────────────────────

/**
 * Creates distributed calendar events for a project, adding a 10-minute buffer.
 * Updates claimedSlots so subsequent jobs in the same run avoid overlap.
 */
function scheduleProjectInCalendar(data, deadlineDate, claimedSlots) {
  claimedSlots = claimedSlots || [];
  const calendar = CalendarApp.getDefaultCalendar();
  const hoursNeeded = parseFloat(data.quantity) + (10 / 60);

  const todayStart = new Date();
  todayStart.setHours(8, 0, 0, 0);
  const todayEnd = new Date();
  todayEnd.setHours(13, 0, 0, 0);

  const existingEvents = calendar.getEvents(todayStart, todayEnd);
  let startFrom = new Date();

  existingEvents.forEach(function(e) {
    if (e.getTitle().startsWith("PROJECT:") && e.getEndTime() > startFrom) {
      startFrom = e.getEndTime();
    }
  });

  claimedSlots.forEach(function(claimed) {
    if (claimed.end > startFrom && claimed.start >= todayStart && claimed.end <= todayEnd) {
      startFrom = claimed.end;
    }
  });

  Logger.log("Starting scheduling from: " + startFrom);

  const schedule = getAvailableSlots(startFrom, deadlineDate, hoursNeeded, claimedSlots);

  schedule.slots.forEach(function(slot, index) {
    const title = 'PROJECT: ' + data.projectNumber + ' (' + (index + 1) + '/' + schedule.slots.length + ')';
    const startTime = new Date(slot.date);
    const endTime = new Date(startTime.getTime() + (slot.hours * 3600000));

    Logger.log("Creating event: " + title + " from " + startTime + " to " + endTime);
    calendar.createEvent(title, startTime, endTime, {
      description: 'Deadline: ' + data.deadline + '\nWords: ' + data.totalWords + '\nHours: ' + slot.hours.toFixed(2)
    });

    claimedSlots.push({ start: startTime, end: endTime });
  });
}

// ─── DEBUG HELPERS ────────────────────────────────────────────────────────

function testLoginAndOffers() {
  const cookie = loginToXTRF();
  if (!cookie) return;
  const offers = getXtrfOffers(cookie);
  offers.forEach(function(o) {
    Logger.log(JSON.stringify(extractDataFromOffer(o)));
  });
}

function testAllDayEventFix() {
  const start = new Date(2026, 3, 30, 10, 0, 0);
  const end = new Date(2026, 4, 5, 13, 0, 0);
  const result = getAvailableSlots(start, end, 5);
  Logger.log("Test result: " + JSON.stringify(result.slots.map(function(s) {
    return { date: s.date.toString(), hours: s.hours.toFixed(2) };
  })));
}

function debugEvents() {
  const calendar = CalendarApp.getDefaultCalendar();
  const start = new Date(2026, 4, 18, 5, 0, 0);
  const end = new Date(2026, 4, 18, 13, 0, 0);
  const events = calendar.getEvents(start, end);
  events.forEach(function(e) {
    Logger.log(e.getTitle() + " | " + e.getStartTime() + " → " + e.getEndTime() + " | allDay: " + e.isAllDayEvent());
  });
}

function debugCalendars() {
  const allCalendars = CalendarApp.getAllCalendars();
  allCalendars.forEach(function(cal) {
    Logger.log(cal.getName() + " | " + cal.getId());
  });
}

function debugSlots() {
  const start = new Date();
  const end = new Date(2026, 4, 19, 13, 0, 0);
  const result = getAvailableSlots(start, end, 0.9, []);
  Logger.log("Slots found: " + JSON.stringify(result.slots.map(function(s) {
    return { date: s.date.toString(), hours: s.hours.toFixed(2) };
  })));
}
