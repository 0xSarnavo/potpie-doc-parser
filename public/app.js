/* Potpie docs chat — vanilla state machine, no libs, no keys.
 * All assistant wording is fixed template strings + verbatim block text.
 * Backend: POST /api/ask {query} -> {verdict, router, results, usage}.
 */
"use strict";

var CONFIG = {
  API_BASE: "",  /* same-origin: /api/ask — works on Vercel and local uvicorn alike */
  MAX_CHARS: 500,
  MIN_CHARS: 3,
  TIMEOUT_MS: 30000,
  STORE_KEY: "jev-chat-thread-v1"
};

/* Fixed assistant templates (never composed from model output). */
var T = {
  SEARCHING: "Searching docs…",
  PARTIAL_ASK: "The docs touch on this but may not fully answer — did you mean one of these?",
  ABSENT_LEAD: "That's not in the Potpie docs I can see.",
  CLOSEST: "Closest section:",
  RETRY: "Retry",
  STOPPED: "Stopped — nothing saved.",
  ERR_NETWORK: "Couldn't reach the docs server. Check your connection and try again.",
  ERR_TIMEOUT: "The search timed out. Try again with a shorter question.",
  ERR_SHORT: "Query too short — type at least 3 characters.",
  ERR_SERVER: "Search failed on the server (502). Try again.",
  ERR_HTTP: "Request failed. Try again.",
  COPIED: "✓ Copied"
};

var VERDICTS = {
  "answered in this document": { label: "answered", cls: "badge-answered" },
  "partially answered in this document": { label: "partial", cls: "badge-partial" },
  "not in this document": { label: "not in docs", cls: "badge-absent" }
};

var threadEl = document.getElementById("thread");
var heroEl = document.getElementById("hero");
var formEl = document.getElementById("composer-form");
var boxEl = document.getElementById("composer");
var sendEl = document.getElementById("send");
var stopEl = document.getElementById("stop");
var hintEl = document.getElementById("hint");
var chipsEl = document.getElementById("chips");
var countEl = document.getElementById("count");

var pendingCtl = null;
var pendingTimer = null;
var userAborted = false;
var lastQuery = "";
var entries = [];

function lastHeading(path) {
  if (!path || !path.length) return "this section";
  return path[path.length - 1];
}

function isNearBottom() {
  var gap = document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
  return gap < 220;  /* the sticky dock is ~150px tall; 100 was too tight */
}

function scrollStick() {
  if (isNearBottom()) scrollToEnd();
}

function scrollToEnd() {
  /* Instant, not smooth: a smooth scroll is a no-op under reduced-motion in
   * some engines, which silently left new messages hidden behind the dock. */
  window.scrollTo(0, document.documentElement.scrollHeight);
}

function setHeroVisible() {
  var empty = !entries.length;
  heroEl.style.display = empty ? "" : "none";
  if (chipsEl) chipsEl.hidden = !empty;      /* starter chips belong to the empty state */
  document.body.classList.toggle("has-thread", !empty);
}

function saveThread() {
  try { sessionStorage.setItem(CONFIG.STORE_KEY, JSON.stringify(entries)); } catch (e) { /* full — keep going */ }
}

function loadThread() {
  try {
    var raw = sessionStorage.getItem(CONFIG.STORE_KEY);
    if (!raw) return;
    var arr = JSON.parse(raw);
    if (Array.isArray(arr)) entries = arr;
  } catch (e) { entries = []; }
}

/* Minimal Markdown -> HTML for docs blocks. No library: this app ships no
 * dependencies. Input is ESCAPED FIRST, so every branch below operates on
 * inert text and can only emit the small set of tags it constructs itself.
 * Potpie's docs embed raw HTML/JSX (img, a, Accordion, ParamField); those are
 * rendered rather than printed, and their title/label text is preserved — the
 * only things dropped are wrappers that carry no words. `Copy quote` still
 * copies the raw source.
 */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* Undo esc() for an attribute value we captured out of escaped text. */
function mdUnesc(s) {
  return String(s).replace(/&quot;/g, '"').replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

function mdAttr(attrs, name) {
  var m = new RegExp(name + "=&quot;([\\s\\S]*?)&quot;").exec(attrs);
  return m ? mdUnesc(m[1]) : "";
}

function mdSafeUrl(u) {
  return /^https?:\/\//i.test(u) ? u : "";
}

/* Inline: raw img/a/br from the docs, then code, bold, italic, links. */
function mdInline(s) {
  /* <img ...> -> a real figure (https only). alt text is kept as the caption. */
  s = s.replace(/&lt;img\b([\s\S]*?)\/?&gt;/gi, function (_, attrs) {
    var src = mdSafeUrl(mdAttr(attrs, "src"));
    var alt = mdAttr(attrs, "alt");
    if (!src) return alt ? esc(alt) : "";
    return '<img class="md-img" src="' + esc(src) + '" alt="' + esc(alt) +
           '" referrerpolicy="no-referrer" />';
  });
  /* <a href="...">text</a> -> a real link; anything else keeps just the text. */
  s = s.replace(/&lt;a\b([\s\S]*?)&gt;([\s\S]*?)&lt;\/a&gt;/gi, function (_, attrs, text) {
    var href = mdSafeUrl(mdAttr(attrs, "href"));
    return href ? '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + text + "</a>" : text;
  });
  s = s.replace(/&lt;br\s*\/?&gt;/gi, "<br />");

  var parts = s.split(/(`[^`]+`)/g);          // protect code spans first
  for (var i = 0; i < parts.length; i++) {
    if (i % 2) { parts[i] = "<code>" + parts[i].slice(1, -1) + "</code>"; continue; }
    parts[i] = parts[i]
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\[([^\]]+)\]\((\/[^)\s]*)\)/g, "$1")   // internal doc link: keep text only
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  }
  return parts.join("");
}

var MD_CALLOUT = /^&lt;(Note|Tip|Warning|Info|Check)&gt;$/;
/* Components whose title= is the only text they carry. */
var MD_TITLED = /^&lt;(Step|Accordion|Card|Tab)\b([\s\S]*?)&gt;$/;
var MD_PARAM = /^&lt;(ParamField|ResponseField)\b([\s\S]*?)&gt;$/;
/* Pure layout wrappers: no words inside the tag itself. */
var MD_DROP = /^&lt;\/?(Steps|CardGroup|Columns|Frame|AccordionGroup|Tabs|Expandable|Icon|Update)\b[\s\S]*?&gt;$|^&lt;\/(Step|Accordion|Card|Tab|ParamField|ResponseField)&gt;$/;

function mdCells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); });
}

function mdToHtml(src) {
  var lines = esc(src).split("\n");
  var out = [], i = 0;

  function flushList(tag, match, strip) {
    var items = [];
    while (i < lines.length && match.test(lines[i])) {
      items.push("<li>" + mdInline(lines[i].replace(strip, "")) + "</li>");
      i++;
    }
    out.push("<" + tag + ">" + items.join("") + "</" + tag + ">");
  }

  while (i < lines.length) {
    var line = lines[i];

    if (/^\s*```/.test(line)) {                      // fenced code
      var buf = []; i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++;
      out.push("<pre><code>" + buf.join("\n") + "</code></pre>");
      continue;
    }

    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1]) && lines[i + 1].indexOf("|") > -1) {
      var head = mdCells(line); i += 2;
      var body = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { body.push(mdCells(lines[i])); i++; }
      out.push("<table><thead><tr>" +
        head.map(function (c) { return "<th>" + mdInline(c) + "</th>"; }).join("") +
        "</tr></thead><tbody>" +
        body.map(function (r) {
          return "<tr>" + r.map(function (c) { return "<td>" + mdInline(c) + "</td>"; }).join("") + "</tr>";
        }).join("") + "</tbody></table>");
      continue;
    }

    var h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      var lvl = Math.min(h[1].length + 2, 6);
      out.push("<h" + lvl + ">" + mdInline(h[2]) + "</h" + lvl + ">");
      i++; continue;
    }

    var t = line.trim();
    if (MD_DROP.test(t)) { i++; continue; }            // layout wrapper: no text
    if (/^&lt;\/(Note|Tip|Warning|Info|Check)&gt;$/.test(t)) { i++; continue; }

    var call = t.match(MD_CALLOUT);
    if (call) {
      var cbuf = []; i++;
      while (i < lines.length && !/^\s*&lt;\/(Note|Tip|Warning|Info|Check)&gt;\s*$/.test(lines[i])) {
        cbuf.push(lines[i]); i++;
      }
      i++;
      out.push('<div class="callout"><span class="callout-tag">' + call[1] + "</span>" +
               mdInline(cbuf.join(" ").trim()) + "</div>");
      continue;
    }

    var titled = t.match(MD_TITLED);
    if (titled) {
      var title = mdAttr(titled[2], "title");
      if (title) out.push('<p class="step-title">' + mdInline(esc(title)) + "</p>");
      i++; continue;
    }

    var param = t.match(MD_PARAM);
    if (param) {
      var nm = mdAttr(param[2], "body") || mdAttr(param[2], "name") || mdAttr(param[2], "query");
      var ty = mdAttr(param[2], "type");
      if (nm) {
        out.push('<p class="param"><code>' + esc(nm) + "</code>" +
                 (ty ? ' <span class="param-type">' + esc(ty) + "</span>" : "") + "</p>");
      }
      i++; continue;
    }

    if (/^\s*&gt;\s?/.test(line)) {                     // blockquote
      var qbuf = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        qbuf.push(lines[i].replace(/^\s*&gt;\s?/, "")); i++;
      }
      out.push("<blockquote>" + mdInline(qbuf.join(" ")) + "</blockquote>");
      continue;
    }

    if (/^\s*[*-]\s+/.test(line)) { flushList("ul", /^\s*[*-]\s+/, /^\s*[*-]\s+/); continue; }
    if (/^\s*\d+\.\s+/.test(line)) { flushList("ol", /^\s*\d+\.\s+/, /^\s*\d+\.\s+/); continue; }

    if (!t) { i++; continue; }

    var para = [];
    while (i < lines.length && lines[i].trim() &&
           !/^\s*(```|\||#{1,6}\s|[*-]\s|\d+\.\s|&gt;)/.test(lines[i]) &&
           !MD_DROP.test(lines[i].trim()) && !MD_CALLOUT.test(lines[i].trim()) &&
           !MD_TITLED.test(lines[i].trim()) && !MD_PARAM.test(lines[i].trim())) {
      para.push(lines[i]); i++;
    }
    if (para.length) out.push("<p>" + mdInline(para.join(" ")) + "</p>");
    else i++;
  }
  return out.join("");
}

/* Docs images are third-party (Potpie's CDN). If one fails — offline, blocked,
 * moved — swap it for its alt text rather than leaving a broken-image icon.
 * Wired in JS, not an inline onerror attribute, so nothing executable is
 * ever written into innerHTML. */
function wireImages(root) {
  root.querySelectorAll("img.md-img").forEach(function (img) {
    var replaced = false;
    var fallback = function () {
      if (replaced || (img.complete && img.naturalWidth > 0)) return;
      replaced = true;
      var cap = document.createElement("p");
      cap.className = "img-fallback";
      cap.textContent = img.getAttribute("alt")
        ? "[image: " + img.getAttribute("alt") + "]"
        : "[image unavailable]";
      if (img.parentNode) img.parentNode.replaceChild(cap, img);
    };
    img.addEventListener("error", fallback);
    /* A blocked third-party image can fail silently — no error event ever
     * fires — so time out as well and fall back to the alt text. */
    setTimeout(fallback, 8000);
  });
}

var ICONS = {
  copy: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  check: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  source: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  retry: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg>'
};

function iconBtn(name, label, onClick) {
  var b = document.createElement("button");
  b.type = "button";
  b.className = "act";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.innerHTML = ICONS[name];
  b.addEventListener("click", onClick);
  return b;
}

/* ---------- message builders (actions always after text in DOM) ---------- */

function addUserMessage(text) {
  var wrap = document.createElement("div");
  wrap.className = "msg msg-user";
  var who = document.createElement("div");
  who.className = "who visually-hidden";
  who.textContent = "You";
  var bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(who);
  wrap.appendChild(bubble);
  threadEl.appendChild(wrap);
}

function addPending() {
  var wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";
  wrap.id = "pending";
  var who = document.createElement("div");
  who.className = "who visually-hidden";
  who.textContent = "Docs";
  var row = document.createElement("div");
  row.className = "pending";
  var dots = document.createElement("span");
  dots.className = "dots";
  dots.setAttribute("aria-hidden", "true");
  dots.innerHTML = "<i></i><i></i><i></i>";
  var label = document.createElement("span");
  label.textContent = T.SEARCHING;
  row.appendChild(dots);
  row.appendChild(label);
  wrap.appendChild(who);
  wrap.appendChild(row);
  threadEl.appendChild(wrap);
  return wrap;
}

function removePending() {
  var p = document.getElementById("pending");
  if (p && p.parentNode) p.parentNode.removeChild(p);
}

function verdictMeta(verdict) {
  return VERDICTS[verdict] || { label: "partial", cls: "badge-partial" };
}

function sourceBlock(b, showBar) {
  var box = document.createElement("div");
  box.className = "src";
  var head = document.createElement("div");
  head.className = "src-head";
  var id = document.createElement("span");
  id.className = "src-id";
  id.textContent = b.block_id;
  var prob = document.createElement("span");
  prob.className = "src-prob";
  prob.textContent = Number(b.prob).toFixed(2);
  head.appendChild(id);
  head.appendChild(prob);
  box.appendChild(head);
  if (showBar) {
    var bar = document.createElement("div");
    bar.className = "bar";
    var fill = document.createElement("span");
    fill.style.width = Math.round(Number(b.prob) * 100) + "%";
    bar.appendChild(fill);
    box.appendChild(bar);
  }
  var txt = document.createElement("div");
  txt.className = "src-text md";
  txt.innerHTML = mdToHtml(b.text);  // escaped inside mdToHtml
  wireImages(txt);
  box.appendChild(txt);
  return box;
}

function chipRow(headings, verb) {
  var row = document.createElement("div");
  row.className = "chips";
  headings.slice(0, 3).forEach(function (h) {
    if (!h) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = h.length > 48 ? h.slice(0, 47) + "…" : h;
    b.setAttribute("data-ask", verb + " " + h);
    b.addEventListener("click", function () { sendQuery(b.getAttribute("data-ask")); });
    row.appendChild(b);
  });
  return row;
}

function renderAnswer(query, data) {
  var results = data.results || [];
  var lead = results[0];
  var meta = verdictMeta(data.verdict);
  var isAbsent = data.verdict === "not in this document";
  var isPartial = data.verdict === "partially answered in this document";

  var wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";

  var who = document.createElement("div");
  who.className = "who visually-hidden";
  who.textContent = "Docs";
  wrap.appendChild(who);

  var badge = document.createElement("span");
  badge.className = "badge " + meta.cls;
  badge.textContent = meta.label;
  wrap.appendChild(badge);

  var tag = document.createElement("span");
  tag.className = "model-tag";
  tag.textContent = "jev";
  wrap.appendChild(tag);

  if (!isAbsent && lead) {
    var quote = document.createElement("div");
    quote.className = "lead md";
    quote.innerHTML = mdToHtml(lead.text);  // escaped inside mdToHtml
    wireImages(quote);
    wrap.appendChild(quote);

    var src = document.createElement("p");
    src.className = "src-line";
    var a = document.createElement("a");
    a.href = /^https?:\/\//i.test(lead.page_url || "") ? lead.page_url : "#";
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = (lead.heading_path || []).join(" › ") || "Source";
    src.appendChild(a);
    wrap.appendChild(src);
  }

  if (isAbsent) {
    var no = document.createElement("p");
    no.textContent = T.ABSENT_LEAD;
    wrap.appendChild(no);
    var near = document.createElement("p");
    near.className = "src-line";
    near.textContent = T.CLOSEST + " " + ((data.router && data.router.choice) || "—");
    wrap.appendChild(near);
  }

  if (!isAbsent && results.length > 1) {
    var det = document.createElement("details");
    det.className = "sources";
    var sum = document.createElement("summary");
    sum.textContent = "Sources (" + Math.min(results.length - 1, 4) + " more)";
    det.appendChild(sum);
    results.slice(1, 5).forEach(function (b) { det.appendChild(sourceBlock(b, true)); });
    wrap.appendChild(det);
  }

  if (isAbsent && results.length) {
    var detA = document.createElement("details");
    detA.className = "sources";
    var sumA = document.createElement("summary");
    sumA.textContent = "Why this section?";
    detA.appendChild(sumA);
    results.slice(0, 2).forEach(function (b) { detA.appendChild(sourceBlock(b, true)); });
    wrap.appendChild(detA);
  }

  var router = document.createElement("p");
  router.className = "router-line";
  router.textContent = "Best section: " + ((data.router && data.router.choice) || "—") +
    " · confidence " + (data.router && data.router.confidence != null ? Number(data.router.confidence).toFixed(2) : "—");
  wrap.appendChild(router);

  if (isPartial) {
    var fu = document.createElement("div");
    fu.className = "followup";
    var q = document.createElement("p");
    q.textContent = T.PARTIAL_ASK;
    fu.appendChild(q);
    var heads = results.slice(1, 4).map(function (b) { return lastHeading(b.heading_path); });
    fu.appendChild(chipRow(heads, "Tell me about"));
    wrap.appendChild(fu);
  }

  if (isAbsent) {
    var fu2 = document.createElement("div");
    fu2.className = "followup";
    var heads2 = results.slice(0, 2).map(function (b) { return lastHeading(b.heading_path); });
    fu2.appendChild(chipRow(heads2, "Tell me about"));
    wrap.appendChild(fu2);
  }

  /* Actions after text in DOM. */
  var acts = document.createElement("div");
  acts.className = "actions";
  if (!isAbsent && lead) {
    var copy = iconBtn("copy", "Copy quote", function () {
      var done = function () {
        copy.innerHTML = ICONS.check;
        copy.classList.add("ok");
        setTimeout(function () { copy.innerHTML = ICONS.copy; copy.classList.remove("ok"); }, 1200);
      };
      /* copies the RAW block, not the rendered HTML */
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(lead.text).then(done, done);
      } else { done(); }
    });
    acts.appendChild(copy);
    if (/^https?:\/\//i.test(lead.page_url || "")) {
      acts.appendChild(iconBtn("source", "Open source page", function () {
        window.open(lead.page_url, "_blank", "noopener");
      }));
    }
  }
  acts.appendChild(iconBtn("retry", "Ask again", function () { sendQuery(query); }));
  wrap.appendChild(acts);
  threadEl.appendChild(wrap);
}

function renderError(query, message) {
  var wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";
  var who = document.createElement("div");
  who.className = "who visually-hidden";
  who.textContent = "Docs";
  var box = document.createElement("div");
  box.className = "error-box";
  box.textContent = message;
  var acts = document.createElement("div");
  acts.className = "actions";
  var retry = document.createElement("button");
  retry.type = "button";
  retry.className = "mini-btn";
  retry.textContent = T.RETRY;
  retry.addEventListener("click", function () { sendQuery(query); });
  acts.appendChild(retry);
  wrap.appendChild(who);
  wrap.appendChild(box);
  wrap.appendChild(acts);
  threadEl.appendChild(wrap);
}

function renderNote(text) {
  var wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";
  var note = document.createElement("span");
  note.className = "sys-note";
  note.textContent = text;
  wrap.appendChild(note);
  threadEl.appendChild(wrap);
}

function pushNote(text) {
  entries.push({ role: "note", text: text });
  renderNote(text);
  setHeroVisible();
  saveThread();
  scrollStick();
}

/* Slash commands run locally and never reach the API — an unknown one costs
 * no Jev call. Keep this a flat map; it is not worth a command framework. */
var COMMAND_HELP = [
  ["/clear", "wipe this conversation"],
  ["/health", "check the docs server is up"],
  ["/help", "list these commands"]
];

var COMMANDS = {
  "/clear": function () {
    entries = [];
    threadEl.innerHTML = "";
    try { sessionStorage.removeItem(CONFIG.STORE_KEY); } catch (e) { /* ignore */ }
    setHeroVisible();
  },
  "/help": function () {
    pushNote(COMMAND_HELP.map(function (c) { return c[0] + " — " + c[1]; }).join("  ·  "));
  },
  "/health": function () {
    fetch(CONFIG.API_BASE + "/api/health").then(function (r) {
      pushNote(r.ok ? "Docs server is up." : "Docs server answered " + r.status + ".");
    }).catch(function () { pushNote(T.ERR_NETWORK); });
  }
};

/* Rebuild DOM from persisted entries (no refetch). */
function restore() {
  threadEl.innerHTML = "";
  entries.forEach(function (e) {
    if (e.role === "user") addUserMessage(e.text);
    else if (e.role === "answer") renderAnswer(e.query, e.data);
    else if (e.role === "error") renderError(e.query, e.message);
    else if (e.role === "stopped") renderNote(T.STOPPED);
    else if (e.role === "note") renderNote(e.text);
  });
  setHeroVisible();
}

/* ---------- send flow: optimistic user msg, AbortController, honest errors ---------- */

function setPendingUI(on) {
  stopEl.hidden = !on;
  sendEl.disabled = on;
}

function sendQuery(raw) {
  var query = String(raw == null ? "" : raw).trim();
  if (pendingCtl) return;
  if (query.charAt(0) === "/") {
    var cmd = query.toLowerCase().split(/\s+/)[0];
    boxEl.value = "";
    autogrow();
    updateCount();
    closePalette();
    hintEl.textContent = "";
    if (COMMANDS[cmd]) COMMANDS[cmd]();
    else pushNote("Unknown command " + cmd + " — try /help");
    boxEl.focus();
    return;
  }
  if (query.length < CONFIG.MIN_CHARS) {
    hintEl.textContent = T.ERR_SHORT;
    boxEl.focus();
    return;
  }
  if (query.length > CONFIG.MAX_CHARS) query = query.slice(0, CONFIG.MAX_CHARS);
  hintEl.textContent = "";
  lastQuery = query;
  userAborted = false;

  entries.push({ role: "user", text: query });
  addUserMessage(query);
  addPending();
  setHeroVisible();
  saveThread();
  scrollToEnd();
  boxEl.value = "";
  autogrow();
  updateCount();
  boxEl.focus();

  pendingCtl = new AbortController();
  setPendingUI(true);
  pendingTimer = setTimeout(function () {
    if (pendingCtl) pendingCtl.abort();
  }, CONFIG.TIMEOUT_MS);

  fetch(CONFIG.API_BASE + "/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: query }),
    signal: pendingCtl.signal
  }).then(function (resp) {
    if (!resp.ok) {
      var kind = resp.status === 422 ? "short" : (resp.status === 502 ? "server" : "http");
      return resp.json().catch(function () { return {}; }).then(function () {
        throw { kind: kind, status: resp.status };
      });
    }
    return resp.json();
  }).then(function (data) {
    removePending();
    data.results = (data.results || []).slice(0, 5);
    entries.push({ role: "answer", query: query, data: data });
    renderAnswer(query, data);
  }).catch(function (err) {
    removePending();
    if (userAborted) {
      entries.push({ role: "stopped", query: query });
      renderNote(T.STOPPED);
    } else if (err && err.kind === "short") {
      entries.push({ role: "error", query: query, message: T.ERR_SHORT });
      renderError(query, T.ERR_SHORT);
    } else if (err && err.kind === "server") {
      entries.push({ role: "error", query: query, message: T.ERR_SERVER });
      renderError(query, T.ERR_SERVER);
    } else if (err && (err.kind === "http" || (err && err.status))) {
      var msg = T.ERR_HTTP + (err.status ? " (" + err.status + ")" : "");
      entries.push({ role: "error", query: query, message: msg });
      renderError(query, msg);
    } else if (err && err.name === "AbortError") {
      entries.push({ role: "error", query: query, message: T.ERR_TIMEOUT });
      renderError(query, T.ERR_TIMEOUT);
    } else {
      entries.push({ role: "error", query: query, message: T.ERR_NETWORK });
      renderError(query, T.ERR_NETWORK);
    }
  }).then(function () {
    clearTimeout(pendingTimer);
    pendingCtl = null;
    setPendingUI(false);
    setHeroVisible();
    saveThread();
    scrollStick();
    boxEl.focus();
  });
}

/* ---------- slash-command palette ---------- */

var paletteEl = document.getElementById("palette");
var paletteItems = [];
var paletteIndex = 0;

function paletteOpen() {
  return !paletteEl.hidden;
}

function renderPalette() {
  paletteEl.innerHTML = "";
  paletteItems.forEach(function (c, n) {
    var row = document.createElement("div");
    row.className = "palette-row" + (n === paletteIndex ? " is-active" : "");
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", n === paletteIndex ? "true" : "false");
    var name = document.createElement("span");
    name.className = "palette-cmd";
    name.textContent = c[0];
    var desc = document.createElement("span");
    desc.className = "palette-desc";
    desc.textContent = c[1];
    row.appendChild(name);
    row.appendChild(desc);
    /* mousedown, not click: the textarea must not blur before we act. */
    row.addEventListener("mousedown", function (ev) { ev.preventDefault(); acceptPalette(n); });
    paletteEl.appendChild(row);
  });
}

function updatePalette() {
  var v = boxEl.value;
  /* Only while typing the command word itself — a space means they moved on. */
  var show = v.charAt(0) === "/" && v.indexOf(" ") === -1;
  paletteItems = show ? COMMAND_HELP.filter(function (c) {
    return c[0].indexOf(v.toLowerCase()) === 0;
  }) : [];
  if (!paletteItems.length) { closePalette(); return; }
  if (paletteIndex >= paletteItems.length) paletteIndex = 0;
  paletteEl.hidden = false;
  boxEl.setAttribute("aria-expanded", "true");
  renderPalette();
}

function closePalette() {
  paletteEl.hidden = true;
  paletteEl.innerHTML = "";
  paletteItems = [];
  paletteIndex = 0;
  boxEl.setAttribute("aria-expanded", "false");
}

function movePalette(step) {
  paletteIndex = (paletteIndex + step + paletteItems.length) % paletteItems.length;
  renderPalette();
}

function acceptPalette(n) {
  var pick = paletteItems[n === undefined ? paletteIndex : n];
  if (!pick) return;
  closePalette();
  sendQuery(pick[0]);
}

/* ---------- composer: autogrow, Enter=send, live count, stop ---------- */

function autogrow() {
  boxEl.style.height = "auto";
  boxEl.style.height = Math.min(boxEl.scrollHeight, 130) + "px";
}

function updateCount() {
  var n = boxEl.value.length;
  countEl.textContent = n + " / " + CONFIG.MAX_CHARS;
  /* A command is not a short query — don't nag while "/h" is being typed. */
  var typingCommand = boxEl.value.charAt(0) === "/";
  if (!typingCommand && n > 0 && n < CONFIG.MIN_CHARS) hintEl.textContent = T.ERR_SHORT;
  else if (hintEl.textContent === T.ERR_SHORT) hintEl.textContent = "";
}

formEl.addEventListener("submit", function (ev) {
  ev.preventDefault();
  sendQuery(boxEl.value);
});

boxEl.addEventListener("input", function () { autogrow(); updateCount(); updatePalette(); });
boxEl.addEventListener("blur", function () { setTimeout(closePalette, 120); });

boxEl.addEventListener("keydown", function (ev) {
  if (paletteOpen()) {
    if (ev.key === "ArrowDown") { ev.preventDefault(); movePalette(1); return; }
    if (ev.key === "ArrowUp") { ev.preventDefault(); movePalette(-1); return; }
    if (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey)) {
      ev.preventDefault(); acceptPalette(); return;
    }
    if (ev.key === "Escape") { ev.preventDefault(); closePalette(); return; }
  }
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    sendQuery(boxEl.value);
  }
});

stopEl.addEventListener("click", function () {
  if (!pendingCtl) return;
  userAborted = true;
  clearTimeout(pendingTimer);
  pendingCtl.abort();
});

document.querySelectorAll(".chip[data-q]").forEach(function (chip) {
  chip.addEventListener("click", function () { sendQuery(chip.getAttribute("data-q")); });
});

/* ---------- init ---------- */

loadThread();
restore();
autogrow();
updateCount();
