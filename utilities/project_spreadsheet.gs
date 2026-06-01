/**
 * project_spreadsheet.gs
 *
 * Fetches completed (NOT_INVOICED) jobs from the XTRF vendor portal and
 * appends new rows to the first sheet for invoicing.
 *
 * Shares XTRF_BASE, loginToXTRF(), and xtrfFetch() with scheduler_xtrf.gs
 * (all files in the same Apps Script project share the same global scope).
 *
 * Script Properties required (same as scheduler_xtrf.gs):
 *   XTRF_EMAIL    — vendor portal login email
 *   XTRF_PASSWORD — vendor portal login password
 *
 * Spreadsheet columns (matches original layout):
 *   1  Project Number
 *   2  Description  (idNumber + EPO title)
 *   3  Client
 *   4  Total Words
 *   5  Hours
 *   6  Job Type     (MTPE / Proofreading / Unknown)
 *   7  Language Pair
 *   8  Start Date   (DD-MM-YYYY)
 *   9  Deadline     (DD-MM-YYYY)
 *   10 Value (EUR)
 *   11 Value (EUR)  (duplicate kept for legacy compatibility)
 *   12 Status
 *   13 Job URL
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('XTRF Invoicing')
    .addItem('Fetch Completed Jobs', 'fetchNotInvoicedJobs')
    .addToUi();
}

/**
 * Trigger-safe entry point — set a time-based trigger to call this function.
 */
function processXtrfJobsForInvoicing() {
  fetchNotInvoicedJobs();
}

/**
 * Main: fetches NOT_INVOICED jobs from XTRF, resolves EPO titles via the
 * job-detail endpoint, and appends new rows (skipping duplicates).
 */
function fetchNotInvoicedJobs() {
  const sessionCookie = loginToXTRF();
  if (!sessionCookie) {
    Logger.log('XTRF login failed — aborting.');
    return;
  }

  const jobs = getNotInvoicedJobs(sessionCookie);
  Logger.log('Found ' + jobs.length + ' NOT_INVOICED job(s).');

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const existingIds = getExistingJobIds(sheet);

  let added = 0;

  jobs.forEach(function(job) {
    if (existingIds.indexOf(String(job.id)) >= 0) {
      Logger.log('Skip (already in sheet): job ' + job.id);
      return;
    }

    const overview = job.overview;
    const quantities = (overview.jobQuantities && overview.jobQuantities.totalQuantities) || [];

    const hoursEntry = quantities.find(function(q) { return q.unit === '1h'; });
    const hours = hoursEntry ? parseFloat(hoursEntry.value) : 0;

    // Fetch individual job detail to obtain the instructions HTML (EPO title).
    const detail = getJobDetail(sessionCookie, job.id);
    const epoTitle = extractEpoTitle(detail ? detail.instructions : null);

    // Project number: extract token like HALA_2605_P0419 from projectName.
    const projMatch = (overview.projectName || '').match(/([a-zA-Z]+_\d+_P\d+)/);
    const projectNumber = projMatch
      ? projMatch[1]
      : (overview.projectName || '').replace(/^Patents \| /, '').trim();

    const idNumber = overview.idNumber || '';
    const description = epoTitle ? idNumber + ' - ' + epoTitle : idNumber;

    const sourceWordEntry = quantities.find(function(q) { return q.unit === 'source word'; });
    const totalWords = sourceWordEntry ? sourceWordEntry.value : 0;

    const jobType = determineJobType(idNumber, overview.type);
    const startDate = formatTimestamp(overview.startDate);
    const deadline = formatTimestamp(overview.deadline);

    // Use the contracted job value from XTRF; fall back to hours * 25.
    const jobValue = (overview.jobValue && overview.jobValue.value) || (hours * 25);
    const jobUrl = XTRF_BASE + '/vendors/#/job/classic/' + job.id;

    sheet.appendRow([
      projectNumber,
      description,
      'Comunica.dk Translations, S.L.',
      totalWords,
      hours,
      jobType,
      'EN>DE',
      startDate,
      deadline,
      jobValue,
      jobValue,
      'To Be Invoiced',
      jobUrl
    ]);

    Logger.log('Added job ' + job.id + ': ' + projectNumber + ' (' + hours + 'h, ' + jobValue + ' EUR)');
    added++;
  });

  Logger.log('Done. Added ' + added + ' new row(s).');
}

// ─── XTRF API CALLS ──────────────────────────────────────────────────────────

/**
 * Returns all jobs with status NOT_INVOICED.
 */
function getNotInvoicedJobs(sessionCookie) {
  const response = xtrfFetch(sessionCookie, '/vendors/jobs?statuses=NOT_INVOICED', 'get');
  if (response.getResponseCode() !== 200) {
    Logger.log('getNotInvoicedJobs failed: HTTP ' + response.getResponseCode());
    return [];
  }
  return JSON.parse(response.getContentText());
}

/**
 * Returns the full detail object for a single job (includes instructions HTML).
 */
function getJobDetail(sessionCookie, jobId) {
  const response = xtrfFetch(sessionCookie, '/vendors/jobs/classic/' + jobId, 'get');
  if (response.getResponseCode() !== 200) {
    Logger.log('getJobDetail(' + jobId + ') failed: HTTP ' + response.getResponseCode());
    return null;
  }
  return JSON.parse(response.getContentText());
}

// ─── HELPERS ─────────────────────────────────────────────────────────────────

/**
 * Parses the EPO title from the job instructions HTML.
 * Returns "German title / English title" or '' if not found.
 * The instructions field contains an HTML block like:
 *   <p>German: RESOLVERQUADRANTENERKENNUNG</p>
 *   <p>English: RESOLVER QUADRANT DETECTION</p>
 *   <p>French: DÉTECTION DE QUADRANT DE RÉSOLVEUR</p>
 */
function extractEpoTitle(instructionsHtml) {
  if (!instructionsHtml) return '';
  // Convert block-level closing tags to newlines so each title stays on its own line,
  // then strip remaining tags. This prevents trailing instruction paragraphs (e.g.
  // Siemens guidelines text) from leaking into the captured title.
  var lined = instructionsHtml
    .replace(/<\/(p|h[1-6]|li|div|br)>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/[ \t]+/g, ' ');
  var deMatch = lined.match(/^German:\s*(.+)/im);
  var enMatch = lined.match(/^English:\s*(.+)/im);
  if (!deMatch && !enMatch) return '';
  if (deMatch && enMatch) return deMatch[1].trim() + ' / ' + enMatch[1].trim();
  return (deMatch || enMatch)[1].trim();
}

/**
 * Formats a Unix millisecond timestamp as DD-MM-YYYY.
 */
function formatTimestamp(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  return String(d.getDate()).padStart(2, '0') + '-' +
         String(d.getMonth() + 1).padStart(2, '0') + '-' +
         d.getFullYear();
}

/**
 * Determines job type from the XTRF idNumber suffix or type string.
 *   1/1 or Post-editing → MTPE
 *   1/2 or 1/4         → Proofreading
 *   otherwise          → the XTRF type string (or 'Unknown')
 */
function determineJobType(idNumber, type) {
  if (type === 'Post-editing' || idNumber.endsWith('1/1')) return 'MTPE';
  if (idNumber.endsWith('1/2') || idNumber.endsWith('1/4')) return 'Proofreading';
  return type || 'Unknown';
}

/**
 * Reads the job URLs from column 13 and extracts the numeric job IDs
 * already present in the sheet to prevent duplicate rows.
 */
function getExistingJobIds(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  const values = sheet.getRange(2, 13, lastRow - 1, 1).getValues();
  return values
    .map(function(row) {
      const match = String(row[0]).match(/\/(\d+)$/);
      return match ? match[1] : null;
    })
    .filter(function(id) { return id !== null; });
}

// ─── DEBUG ────────────────────────────────────────────────────────────────────

/**
 * Logs raw NOT_INVOICED jobs without writing to the sheet — use to verify
 * the API response and EPO title extraction before running for real.
 */
function debugNotInvoicedJobs() {
  const sessionCookie = loginToXTRF();
  if (!sessionCookie) return;

  const jobs = getNotInvoicedJobs(sessionCookie);
  Logger.log('Total jobs: ' + jobs.length);

  jobs.forEach(function(job) {
    const overview = job.overview;
    const quantities = (overview.jobQuantities && overview.jobQuantities.totalQuantities) || [];
    const hoursEntry = quantities.find(function(q) { return q.unit === '1h'; });
    const hours = hoursEntry ? parseFloat(hoursEntry.value) : 0;
    const detail = getJobDetail(sessionCookie, job.id);
    const epoTitle = extractEpoTitle(detail ? detail.instructions : null);

    Logger.log([
      job.id,
      overview.idNumber,
      overview.projectName,
      overview.type,
      hours + 'h',
      (overview.jobValue ? overview.jobValue.value + ' EUR' : ''),
      'EPO: ' + (epoTitle || '(not found)')
    ].join(' | '));
  });
}
