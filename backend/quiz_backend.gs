/**
 * Quiz backend for the RAS RoboController app (and the web/ build).
 *
 * Deploy this as a Web App (Deploy > New deployment > Web app):
 *   - Execute as:      Me
 *   - Who has access:  Anyone
 * Copy the resulting ".../exec" URL into quiz_config.BACKEND_URL and
 * web/config.js.
 *
 * After editing this file, redeploy: Deploy > Manage deployments >
 * (pencil) > Version: New version > Deploy. The ".../exec" URL is
 * unchanged; a plain code edit without a new version keeps /exec on the
 * old code.
 *
 * Auth model: the client never signs the HTTP request itself. Instead it
 * puts the user's Google ID token in the JSON body; this script verifies
 * it against Google's tokeninfo endpoint on every call, checks the
 * audience (one of the OAuth client ids below), the email domain, and
 * the admin list.
 *
 * Storage: a single spreadsheet with two sheets, "Problems" and
 * "Results", created automatically on first use.
 */

// ======================= CONFIG (edit these) =========================

// Every accepted `aud` (audience) claim -- one entry per OAuth client
// that may talk to this backend. Keep the app's client id
// (quiz_config.GOOGLE_CLIENT_ID) in the list; add the "Web application"
// client id from web/config.js so the browser build validates too.
var CLIENT_IDS = [
  '1090468690005-do85caobta0nv2fjgbvmqijcc5hs4p3k.apps.googleusercontent.com', // Android/iOS app
  '1090468690005-mbihosgo4qstaohs48noutb4v0tita2b.apps.googleusercontent.com',  // web/ build
];

// Email domains allowed to take the quiz. "lnmiit.ac.in" also matches
// "x@dept.lnmiit.ac.in".
var ALLOWED_DOMAINS = ['lnmiit.ac.in'];

// Exact addresses allowed to post problems and read everyone's results.
// Keep this in sync with ADMIN_EMAILS in quiz_config.py.
var ADMIN_EMAILS = [
  '25ucs115@lnmiit.ac.in',
];

// Leave blank to use a spreadsheet bound to this script / auto-created
// one; or paste a specific spreadsheet id to use that.
var SPREADSHEET_ID = '';

// ====================================================================

var PROBLEM_HEADERS = [
  'id', 'question', 'optionA', 'optionB', 'optionC', 'optionD',
  'correct', 'createdBy', 'createdAt', 'active',
];
var RESULT_HEADERS = [
  'submissionId', 'timestamp', 'email', 'name', 'problemId', 'question',
  'selected', 'correct', 'isCorrect', 'score', 'total',
];
var SCORE_HEADERS = [
  'email', 'name', 'answered', 'correct', 'percent', 'lastUpdated',
];


function doGet() {
  return json({ ok: true, data: 'Quiz backend is running. POST to use it.' });
}

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    var claims = verifyToken(body.idToken);
    var email = String(claims.email || '').toLowerCase();
    var name = claims.name || email;

    if (!emailAllowed(email)) {
      return json({ ok: false, error: 'Use your LNMIIT (lnmiit.ac.in) account.' });
    }
    var isAdmin = ADMIN_EMAILS.map(lower).indexOf(email) !== -1;
    var action = body.action;
    var p = body.payload || {};

    if (action === 'list_problems') return json({ ok: true, data: listProblems(isAdmin, email) });
    if (action === 'submit_answers') return json({ ok: true, data: submitAnswers(email, name, p) });
    if (action === 'my_results') return json({ ok: true, data: listResults(email) });

    if (!isAdmin) return json({ ok: false, error: 'Admin only.' });

    if (action === 'create_problem') return json({ ok: true, data: createProblem(email, p) });
    if (action === 'delete_problem') return json({ ok: true, data: deleteProblem(p.id) });
    if (action === 'list_results') return json({ ok: true, data: listResults(null) });
    if (action === 'scoreboard') return json({ ok: true, data: scoreboard() });

    return json({ ok: false, error: 'Unknown action: ' + action });
  } catch (err) {
    return json({ ok: false, error: String(err && err.message || err) });
  }
}

// ------------------------- auth helpers ----------------------------

function verifyToken(idToken) {
  if (!idToken) throw new Error('Missing idToken');
  var url = 'https://oauth2.googleapis.com/tokeninfo?id_token=' +
    encodeURIComponent(idToken);
  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });

  // Parse first, defensively -- a non-200 or a non-JSON body must not
  // fall through to `info.aud` (that's what threw "Cannot read
  // properties of undefined (reading 'aud')").
  var info = null;
  try { info = JSON.parse(resp.getContentText()); } catch (e) { info = null; }
  if (resp.getResponseCode() !== 200 || !info || info.error) {
    throw new Error('Token verification failed: ' + (
      (info && (info.error_description || info.error)) || resp.getResponseCode()
    ));
  }

  if (CLIENT_IDS.indexOf(info.aud) === -1) {
    throw new Error('Token audience mismatch (' + info.aud + ')');
  }
  if (Number(info.exp) * 1000 < Date.now()) throw new Error('Token expired');
  if (String(info.email_verified) !== 'true') throw new Error('Email not verified');
  return info;
}

function emailAllowed(email) {
  var at = email.indexOf('@');
  if (at === -1) return false;
  var domain = email.slice(at + 1);
  for (var i = 0; i < ALLOWED_DOMAINS.length; i++) {
    var d = ALLOWED_DOMAINS[i].toLowerCase();
    if (domain === d || domain.slice(-('.' + d).length) === '.' + d) return true;
  }
  return false;
}

function lower(s) { return String(s).toLowerCase(); }

// ------------------------- storage ------------------------------

function getSheet(name, headers) {
  var ss = SPREADSHEET_ID
    ? SpreadsheetApp.openById(SPREADSHEET_ID)
    : (SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.create('RAS Quiz Data'));
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(headers);
  }
  return sh;
}

function rowsAsObjects(sh) {
  var values = sh.getDataRange().getValues();
  if (values.length < 2) return [];
  var head = values[0];
  var out = [];
  for (var r = 1; r < values.length; r++) {
    var obj = {};
    for (var c = 0; c < head.length; c++) obj[head[c]] = values[r][c];
    obj._row = r + 1;
    out.push(obj);
  }
  return out;
}

// ------------------------- problems ------------------------------

function listProblems(includeAnswers, email) {
  // Returns every active problem (no answered-filter). The app renders
  // already-answered ones locked using `my_results`, and one-attempt is
  // still enforced server-side in submitAnswers(). `correct` is only
  // ever sent to admins.
  var sh = getSheet('Problems', PROBLEM_HEADERS);
  return rowsAsObjects(sh)
    .filter(function (p) { return String(p.active) !== 'false'; })
    .map(function (p) {
      var out = {
        id: String(p.id),
        question: p.question,
        options: { A: p.optionA, B: p.optionB, C: p.optionC, D: p.optionD },
      };
      if (includeAnswers) {
        out.correct = p.correct;
        out.createdBy = p.createdBy;
        out.createdAt = p.createdAt;
      }
      return out;
    });
}

function answeredProblemIds(email) {
  var rs = getSheet('Results', RESULT_HEADERS);
  var out = {};
  rowsAsObjects(rs).forEach(function (r) {
    if (String(r.email).toLowerCase() === String(email).toLowerCase()) {
      out[String(r.problemId)] = true;
    }
  });
  return out;
}

function createProblem(email, p) {
  var opts = p.options || {};
  if (!p.question || !opts.A || !opts.B || !opts.C || !opts.D) {
    throw new Error('Question and all four options are required');
  }
  if (['A', 'B', 'C', 'D'].indexOf(p.correct) === -1) {
    throw new Error('correct must be one of A, B, C, D');
  }
  var sh = getSheet('Problems', PROBLEM_HEADERS);
  var id = 'p' + Date.now();
  sh.appendRow([
    id, p.question, opts.A, opts.B, opts.C, opts.D, p.correct,
    email, nowStamp(), 'true',
  ]);
  return { id: id };
}

function deleteProblem(id) {
  var sh = getSheet('Problems', PROBLEM_HEADERS);
  var rows = rowsAsObjects(sh);
  for (var i = 0; i < rows.length; i++) {
    if (String(rows[i].id) === String(id)) {
      // Soft-delete so historical results still resolve the question.
      sh.getRange(rows[i]._row, PROBLEM_HEADERS.indexOf('active') + 1).setValue('false');
      return { deleted: id };
    }
  }
  throw new Error('Problem not found: ' + id);
}

// ------------------------- results ------------------------------

function submitAnswers(email, name, p) {
  var answers = p.answers || {};
  var sh = getSheet('Problems', PROBLEM_HEADERS);
  var problems = {};
  rowsAsObjects(sh).forEach(function (pr) { problems[String(pr.id)] = pr; });

  // One attempt per problem, enforced server-side too: drop anything
  // unknown or already answered by this user.
  var already = answeredProblemIds(email);
  var ids = Object.keys(answers).filter(function (pid) {
    return problems[pid] && !already[pid];
  });
  if (!ids.length) {
    throw new Error('Nothing to record -- those questions were already attempted.');
  }

  var total = ids.length;
  var score = 0;
  var breakdown = [];
  ids.forEach(function (pid) {
    var pr = problems[pid];
    if (!pr) return;
    var selected = answers[pid];
    var isCorrect = selected === pr.correct;
    if (isCorrect) score++;
    breakdown.push({
      problemId: pid, question: pr.question, selected: selected,
      correct: pr.correct, isCorrect: isCorrect,
    });
  });

  var submissionId = 's' + Date.now() + '_' + Math.floor(Math.random() * 1e6);
  var ts = nowStamp();
  var rs = getSheet('Results', RESULT_HEADERS);
  breakdown.forEach(function (b) {
    rs.appendRow([
      submissionId, ts, email, name, b.problemId, b.question,
      b.selected, b.correct, b.isCorrect ? 'true' : 'false', score, total,
    ]);
  });

  // Refresh the human-readable per-student Scores tab.
  writeScoresSheet();
  var mine = aggregateScores()[email] || { answered: 0, correct: 0 };

  return {
    submissionId: submissionId,
    score: score,
    total: total,
    breakdown: breakdown,
    overall: { answered: mine.answered, correct: mine.correct },
  };
}

// ------------------------- scores ------------------------------

/**
 * email -> {email, name, answered, correct, lastUpdated}, computed live
 * from Results. Old rows stored an ISO-UTC timestamp; normStamp() folds
 * those to the same IST "yyyy-MM-dd HH:mm:ss" as new rows so max / display
 * are consistent.
 */
function aggregateScores() {
  var rs = getSheet('Results', RESULT_HEADERS);
  var acc = {};
  rowsAsObjects(rs).forEach(function (r) {
    var e = String(r.email).toLowerCase();
    if (!e) return;
    if (!acc[e]) {
      acc[e] = { email: e, name: r.name, answered: 0, correct: 0, lastUpdated: '' };
    }
    if (r.name) acc[e].name = r.name;
    acc[e].answered++;
    if (String(r.isCorrect) === 'true') acc[e].correct++;
    var ts = normStamp(r.timestamp);
    if (ts > acc[e].lastUpdated) acc[e].lastUpdated = ts;
  });
  return acc;
}

function normStamp(v) {
  v = String(v || '');
  if (v.length >= 20 && v.charAt(10) === 'T') {  // ISO-8601 UTC
    try {
      return Utilities.formatDate(new Date(v), DISPLAY_TZ, "yyyy-MM-dd HH:mm:ss");
    } catch (e) { /* leave as-is */ }
  }
  return v;
}

/** Sorted array with a percent field -- what the app's Results tab shows. */
function scoreboard() {
  var acc = aggregateScores();
  return Object.keys(acc)
    .map(function (k) {
      var s = acc[k];
      s.percent = s.answered ? Math.round((s.correct / s.answered) * 100) : 0;
      return s;
    })
    .sort(function (a, b) {
      return b.correct - a.correct || b.percent - a.percent;
    });
}

/** Mirror the scoreboard into a "Scores" sheet for whoever reads the file. */
function writeScoresSheet() {
  var sc = getSheet('Scores', SCORE_HEADERS);
  if (sc.getLastRow() > 1) {
    sc.getRange(2, 1, sc.getLastRow() - 1, SCORE_HEADERS.length).clearContent();
  }
  var stamp = nowStamp();
  scoreboard().forEach(function (s) {
    sc.appendRow([
      s.email, s.name, s.answered, s.correct, s.percent + '%', stamp,
    ]);
  });
}

/**
 * If email is null -> every submission (admin). Otherwise just that
 * user's. Returns one object per submission with a per-question
 * breakdown, newest first.
 */
function listResults(email) {
  var rs = getSheet('Results', RESULT_HEADERS);
  var rows = rowsAsObjects(rs);
  var bySub = {};
  rows.forEach(function (r) {
    if (email && String(r.email).toLowerCase() !== email) return;
    var sid = r.submissionId;
    if (!bySub[sid]) {
      bySub[sid] = {
        submissionId: sid, timestamp: normStamp(r.timestamp), email: r.email,
        name: r.name, score: Number(r.score), total: Number(r.total),
        answers: [],
      };
    }
    bySub[sid].answers.push({
      problemId: r.problemId, question: r.question, selected: r.selected,
      correct: r.correct, isCorrect: String(r.isCorrect) === 'true',
    });
  });
  return Object.keys(bySub)
    .map(function (k) { return bySub[k]; })
    .sort(function (a, b) { return (a.timestamp < b.timestamp) ? 1 : -1; });
}

// ------------------------- util ------------------------------

// Timezone for stored timestamps. Apps Script's `new Date().toISOString()`
// is UTC, which showed up ~5.5h off in the app. Format in IST instead.
var DISPLAY_TZ = 'Asia/Kolkata';

function nowStamp() {
  return Utilities.formatDate(new Date(), DISPLAY_TZ, "yyyy-MM-dd HH:mm:ss");
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
