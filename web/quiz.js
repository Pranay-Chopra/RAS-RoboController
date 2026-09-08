/* RAS Quiz - browser client.
 *
 * A second frontend for the same Google Apps Script backend the Android
 * app talks to (screens/quiz.py). Auth here is Google Identity Services
 * (ID-token flow); the token goes in the POST body exactly like the app,
 * and the backend re-verifies it, enforces the email domain and the
 * admin whitelist, and reads/writes the shared Sheet.
 */
(function () {
  "use strict";

  var CFG = window.QUIZ_CONFIG || {};

  var idToken = null;
  var profile = null;          // decoded JWT claims: {email, name, ...}
  var isAdmin = false;
  var problems = [];
  var myResults = [];
  var answers = {};            // problemId -> "A".."D"  (pending only)
  var pendingIds = [];
  var currentTab = "manage";
  var resultsRows = [];
  var resultsLoaded = false;
  var sortKey = "name";        // "name" | "email" | "percent"
  var sortDesc = false;

  var $ = function (id) { return document.getElementById(id); };
  var elAccount = $("account"),
      elAccountLabel = $("account-label"),
      elStatus = $("status"),
      elTabs = $("tabs"),
      elViewQuiz = $("view-quiz"),
      elViewResults = $("view-results"),
      elToast = $("toast"),
      elModalRoot = $("modal-root");

  // ---------------------------- helpers ----------------------------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function show(n) { n.classList.remove("hidden"); }
  function hide(n) { n.classList.add("hidden"); }
  function setStatus(t) { elStatus.textContent = t || ""; }

  var toastTimer;
  function toast(t) {
    elToast.textContent = t;
    show(elToast);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { hide(elToast); }, 2600);
  }

  function parseJwt(tok) {
    var b64 = tok.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    var raw = atob(b64), pct = "";
    for (var i = 0; i < raw.length; i++) {
      pct += "%" + ("00" + raw.charCodeAt(i).toString(16)).slice(-2);
    }
    return JSON.parse(decodeURIComponent(pct));
  }

  // ---------------------------- api -------------------------------
  // text/plain keeps this a CORS "simple request" (no preflight) --
  // Apps Script can't answer an OPTIONS preflight, but it does parse the
  // JSON body regardless of content type and serves the response with
  // Access-Control-Allow-Origin: *.
  function api(action, payload) {
    return fetch(CFG.backendUrl, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({
        idToken: idToken, action: action, payload: payload || {}
      })
    }).then(function (res) {
      if (!res.ok) throw new Error("Server error " + res.status);
      return res.json();
    }).then(function (body) {
      if (!body.ok) throw new Error(body.error || "Request failed");
      return body.data;
    });
  }

  function isAuthError(e) {
    var m = (e && e.message || "").toLowerCase();
    return m.indexOf("expired") !== -1 ||
           m.indexOf("audience") !== -1 ||
           m.indexOf("missing idtoken") !== -1;
  }

  function handleLoadError(e) {
    if (isAuthError(e)) {
      setStatus("Session expired - sign in again.");
      signOut();
      return true;
    }
    return false;
  }

  // ---------------------------- auth ------------------------------
  function waitForGis(cb) {
    if (window.google && google.accounts && google.accounts.id) return cb();
    setTimeout(function () { waitForGis(cb); }, 120);
  }

  function initAuth() {
    if (!CFG.webClientId || CFG.webClientId.indexOf("PASTE_") === 0) {
      renderMessage("This site isn't configured yet - set QUIZ_CONFIG.webClientId "
        + "in config.js (see README.md).");
      return;
    }
    google.accounts.id.initialize({
      client_id: CFG.webClientId,
      callback: onCredential,
      auto_select: false,
      itp_support: true,
      use_fedcm_for_prompt: true
    });
    // Drop any remembered auto-select session -- a stale one from a
    // different client id is what makes the GIS library throw
    // "Cannot read properties of undefined (reading 'aud')".
    try { google.accounts.id.disableAutoSelect(); } catch (e) {}
    renderSignin();
  }

  function onCredential(resp) {
    if (!resp || !resp.credential) {
      setStatus("Google sign-in returned no credential. Allow pop-ups / "
        + "third-party sign-in for this site and try again.");
      return;
    }
    idToken = resp.credential;
    try {
      profile = parseJwt(idToken);
    } catch (e) {
      setStatus("Could not read the sign-in token.");
      return;
    }
    setStatus("Loading...");
    loadProblems();
  }

  function signOut() {
    try { google.accounts.id.disableAutoSelect(); } catch (e) {}
    idToken = null; profile = null; isAdmin = false;
    problems = []; myResults = []; answers = {}; pendingIds = [];
    resultsRows = []; resultsLoaded = false; currentTab = "manage";
    hide(elAccount); hide(elTabs); hide(elViewResults); show(elViewQuiz);
    setStatus("");
    renderSignin();
  }
  $("signout").addEventListener("click", signOut);

  // ------------------------ top-level views -----------------------
  function renderMessage(text) {
    hide(elTabs); hide(elAccount); hide(elViewResults); show(elViewQuiz);
    elViewQuiz.innerHTML = "";
    var w = el("div", "signin");
    w.appendChild(el("p", null, text));
    elViewQuiz.appendChild(w);
  }

  function renderSignin() {
    hide(elTabs); hide(elAccount); hide(elViewResults); show(elViewQuiz);
    elViewQuiz.innerHTML = "";
    var w = el("div", "signin");
    w.appendChild(el("p", null, "Sign in with your "
      + (CFG.allowedDomainNote || "school") + " Google account to take the quiz."));
    var host = el("div");
    w.appendChild(host);
    elViewQuiz.appendChild(w);
    google.accounts.id.renderButton(host, {
      theme: "filled_black", size: "large", shape: "pill", text: "signin_with"
    });
    // No google.accounts.id.prompt() One Tap: it's blocked by Safari's
    // third-party-cookie policy anyway, and a stale One Tap session is
    // the usual trigger for the GIS "reading 'aud'" crash.
  }

  function showAccount() {
    elAccountLabel.textContent = (profile.name || profile.email)
      + "  ·  " + (isAdmin ? "Admin" : "Student");
    show(elAccount);
  }

  function loadProblems() {
    setStatus("Loading...");
    api("list_problems").then(function (data) {
      problems = data || [];
      // list_problems returns `correct` only to admins; fall back to a
      // scoreboard probe when there are no problems to sniff.
      isAdmin = problems.some(function (p) { return p.correct !== undefined; });
      if (isAdmin) return null;
      return api("scoreboard").then(function () { isAdmin = true; }, function () {});
    }).then(function () {
      return api("my_results").then(
        function (d) { myResults = d || []; },
        function () { myResults = []; }
      );
    }).then(function () {
      setStatus("");
      showAccount();
      renderLayout();
    }).catch(function (e) {
      if (handleLoadError(e)) return;
      setStatus(e.message || "Failed to load.");
      elViewQuiz.innerHTML = "";
      var w = el("div", "signin");
      var again = el("button", "btn-primary", "USE A DIFFERENT ACCOUNT");
      again.addEventListener("click", signOut);
      w.appendChild(again);
      elViewQuiz.appendChild(w);
    });
  }

  function renderLayout() {
    if (isAdmin) {
      show(elTabs);
      setTab(currentTab);
    } else {
      hide(elTabs); hide(elViewResults); show(elViewQuiz);
      renderQuiz();
    }
  }

  // ---------------------------- tabs ------------------------------
  Array.prototype.forEach.call(elTabs.querySelectorAll(".tab"), function (btn) {
    btn.addEventListener("click", function () { setTab(btn.dataset.tab); });
  });

  function setTab(name) {
    currentTab = name;
    Array.prototype.forEach.call(elTabs.querySelectorAll(".tab"), function (b) {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    if (name === "results") {
      hide(elViewQuiz); show(elViewResults);
      if (!resultsLoaded) { resultsLoaded = true; loadResults(); }
    } else {
      show(elViewQuiz); hide(elViewResults);
      renderQuiz();
    }
  }

  // ---------------------------- quiz ------------------------------
  function answeredMap() {
    var m = {};
    myResults.forEach(function (sub) {
      (sub.answers || []).forEach(function (a) { m[String(a.problemId)] = a; });
    });
    return m;
  }

  function renderQuiz() {
    elViewQuiz.innerHTML = "";

    if (isAdmin) {
      var row = el("div", "fab-row");
      var add = el("button", "fab", "+");
      add.title = "Post a problem";
      add.addEventListener("click", openPostModal);
      row.appendChild(add);
      elViewQuiz.appendChild(row);
    }

    if (!problems.length) {
      elViewQuiz.appendChild(el("div", "muted", "No questions yet."));
      return;
    }

    var answered = answeredMap();
    pendingIds = [];
    problems.forEach(function (p, i) {
      var state = answered[String(p.id)] || null;
      elViewQuiz.appendChild(questionCard(i + 1, p, state));
      if (!state) pendingIds.push(String(p.id));
    });

    if (pendingIds.length) {
      var submitBtn = el("button", "btn-primary", "SUBMIT ANSWERS");
      submitBtn.addEventListener("click", submit);
      elViewQuiz.appendChild(submitBtn);
    }
  }

  function questionCard(number, problem, state) {
    var card = el("div", "card");
    card.appendChild(el("div", "q", number + ". " + (problem.question || "")));

    var pid = String(problem.id);
    var opts = problem.options || {};
    ["A", "B", "C", "D"].forEach(function (k) {
      if (!(k in opts)) return;
      var o = el("button", "opt", k + ".  " + opts[k]);
      if (!state) {
        o.addEventListener("click", function () {
          answers[pid] = k;
          Array.prototype.forEach.call(card.querySelectorAll(".opt"), function (x) {
            x.classList.toggle("sel", x === o);
          });
        });
      } else {
        o.classList.add("lock");
        if (k === state.correct) o.classList.add("correct");
        else if (k === state.selected) o.classList.add("wrong");
        else o.classList.add("plain");
      }
      card.appendChild(o);
    });

    if (state) {
      var ok = state.isCorrect;
      var tail = ok ? "correct" : ("wrong - answer was " + state.correct);
      card.appendChild(el("div", "verdict " + (ok ? "ok" : "no"),
        (ok ? "✓" : "✗") + "  You answered "
        + state.selected + " - " + tail));
    }
    return card;
  }

  function submit() {
    var missing = pendingIds.filter(function (p) { return !(p in answers); });
    if (missing.length) {
      setStatus("Answer the " + pendingIds.length + " new question(s) first.");
      return;
    }
    var payload = {};
    pendingIds.forEach(function (p) { payload[p] = answers[p]; });
    setStatus("Submitting...");
    api("submit_answers", { answers: payload }).then(function (data) {
      var o = (data && data.overall) || {};
      toast("Recorded. Your total: " + (o.correct || 0) + "/" + (o.answered || 0));
      answers = {};
      loadProblems();
    }).catch(function (e) {
      if (handleLoadError(e)) return;
      setStatus(e.message || "Submit failed.");
    });
  }

  // --------------------- post problem (admin) ---------------------
  function openPostModal() {
    var correct = "A";
    var overlay = el("div", "overlay");
    var m = el("div", "modal");
    m.appendChild(el("h3", null, "Post a Problem"));

    var q = el("input");
    q.placeholder = "Question";
    m.appendChild(q);

    var fields = {};
    ["A", "B", "C", "D"].forEach(function (k) {
      var f = el("input");
      f.placeholder = "Option " + k;
      fields[k] = f;
      m.appendChild(f);
    });

    m.appendChild(el("div", "label", "Correct answer"));
    var chips = el("div", "chips");
    var chipEls = {};
    ["A", "B", "C", "D"].forEach(function (k) {
      var c = el("button", "chip" + (k === "A" ? " on" : ""), k);
      c.addEventListener("click", function () {
        correct = k;
        Object.keys(chipEls).forEach(function (x) {
          chipEls[x].classList.toggle("on", x === k);
        });
      });
      chipEls[k] = c;
      chips.appendChild(c);
    });
    m.appendChild(chips);

    var actions = el("div", "modal-actions");
    var cancel = el("button", "btn-flat", "CANCEL");
    var post = el("button", "btn-primary", "POST");
    actions.appendChild(cancel);
    actions.appendChild(post);
    m.appendChild(actions);

    overlay.appendChild(m);
    elModalRoot.appendChild(overlay);

    function close() {
      if (overlay.parentNode) elModalRoot.removeChild(overlay);
    }
    cancel.addEventListener("click", close);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });

    post.addEventListener("click", function () {
      var question = q.value.trim();
      var options = {};
      var allFilled = true;
      ["A", "B", "C", "D"].forEach(function (k) {
        options[k] = fields[k].value.trim();
        if (!options[k]) allFilled = false;
      });
      if (!question || !allFilled) {
        toast("Fill in the question and all four options");
        return;
      }
      post.disabled = cancel.disabled = true;
      toast("Posting...");
      api("create_problem", {
        question: question, options: options, correct: correct
      }).then(function () {
        toast("Problem posted");
        close();
        loadProblems();
      }).catch(function (e) {
        post.disabled = cancel.disabled = false;
        toast(e.message || "Failed to post");
      });
    });
  }

  // -------------------------- results ----------------------------
  function loadResults() {
    elViewResults.innerHTML = "";
    elViewResults.appendChild(el("div", "muted", "Loading results..."));
    api("scoreboard").then(function (data) {
      resultsRows = data || [];
      renderResults();
    }).catch(function (e) {
      elViewResults.innerHTML = "";
      elViewResults.appendChild(
        el("div", "muted", e.message || "Failed to load results."));
    });
  }

  function sortBy(key) {
    if (sortKey === key) {
      sortDesc = !sortDesc;
    } else {
      sortKey = key;
      sortDesc = (key === "percent");   // text A->Z, percentage high->low
    }
    renderResults();
  }

  function renderResults() {
    elViewResults.innerHTML = "";

    var head = el("div", "results-head");
    head.appendChild(el("h2", null, "Final score per student"));
    var refresh = el("button", "icon-btn");
    refresh.title = "Refresh";
    refresh.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.65 6.35A7.96 '
      + '7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.63 '
      + '4.28 1.72L13 11h7V4l-2.35 2.35z"/></svg>';
    refresh.addEventListener("click", loadResults);
    head.appendChild(refresh);
    elViewResults.appendChild(head);

    if (!resultsRows.length) {
      elViewResults.appendChild(el("div", "muted", "No submissions yet."));
      return;
    }

    var rows = resultsRows.slice();
    rows.sort(function (a, b) {
      var r;
      if (sortKey === "percent") {
        r = (a.percent || 0) - (b.percent || 0);
      } else {
        var av = String(a[sortKey] || a.email || "").toLowerCase();
        var bv = String(b[sortKey] || b.email || "").toLowerCase();
        r = av < bv ? -1 : (av > bv ? 1 : 0);
      }
      return sortDesc ? -r : r;
    });

    var table = el("table", "scores");
    var thead = el("thead");
    var htr = el("tr");
    [["Name", "name", "col-name"],
     ["Email", "email", "col-email"],
     ["Score", null, "col-score"],
     ["%", "percent", "col-pct"]].forEach(function (c) {
      var th = el("th", c[2], c[0]);
      if (c[1]) {
        th.classList.add("sortable");
        if (sortKey === c[1]) {
          th.appendChild(el("span", "arrow", sortDesc ? "▼" : "▲"));
        }
        th.addEventListener("click", (function (k) {
          return function () { sortBy(k); };
        })(c[1]));
      }
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(cell(r.name || r.email || "—"));
      tr.appendChild(cell(r.email || ""));
      tr.appendChild(cell((r.correct || 0) + "/" + (r.answered || 0)));
      tr.appendChild(cell((r.percent || 0) + "%"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    elViewResults.appendChild(table);
  }

  function cell(text) {
    var d = el("td", null, text);
    d.title = text;
    return d;
  }

  // ---------------------------- go -------------------------------
  window.addEventListener("load", function () { waitForGis(initAuth); });
})();
