// Triage keyboard controller (spec §8). Server renders the card; this swaps fragments and
// maps keys to actions. No external dependencies.
//
// Concurrency: triage is fast key-mashing, so actions must not race. `busy` serialises every
// network action (ignore keys while one is in flight), and `loadToken` drops stale card
// responses so a late fetch can never overwrite a newer render.
"use strict";

const queue = JSON.parse(document.body.dataset.queue || "[]");
let index = 0;
let busy = false;
let loadToken = 0;
let pendingDim = null; // dimension key awaiting a 0-5 value after 1-6
let pendingTimer = null;

const cardEl = document.getElementById("card");
const progressEl = document.getElementById("progress");
const toastEl = document.getElementById("toast");

function toast(msg) {
  toastEl.textContent = msg;
  toastEl.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (toastEl.hidden = true), 1400);
}

function updateProgress() {
  const total = queue.length;
  progressEl.textContent = total ? `${index + 1} / ${total} in queue` : "queue clear";
}

async function loadCard() {
  const token = ++loadToken;
  updateProgress();
  if (queue.length === 0) {
    cardEl.innerHTML = '<div class="empty">Queue clear — nothing left to triage. 🎉</div>';
    return;
  }
  if (index < 0) index = 0;
  if (index >= queue.length) index = queue.length - 1;
  const resp = await fetch(`/problem/${queue[index]}/card`);
  const html = await resp.text();
  if (token !== loadToken) return; // a newer load/mutation superseded this one
  cardEl.innerHTML = html;
}

function currentId() {
  return queue[index];
}

// Swap the card with a freshly-rendered fragment from a mutation response, invalidating any
// in-flight loadCard so it can't clobber this render.
function swapCard(html) {
  loadToken++;
  cardEl.innerHTML = html;
}

async function setStatus(status) {
  const id = currentId();
  if (id === undefined) return;
  busy = true;
  try {
    const resp = await fetch(`/problem/${id}/status`, {
      method: "POST",
      body: new URLSearchParams({ status }),
    });
    if (resp.ok) {
      toast(`#${id} → ${status}`);
      queue.splice(index, 1); // it left the 'new' queue
      await loadCard();
    }
  } finally {
    busy = false;
  }
}

async function override(dim, value) {
  const id = currentId();
  busy = true;
  try {
    const resp = await fetch(`/problem/${id}/override`, {
      method: "POST",
      body: new URLSearchParams({ dimension: dim, value: String(value) }),
    });
    if (resp.ok) {
      swapCard(await resp.text());
      toast(`${dim.replace(/_/g, " ")} → ${value}`);
    } else {
      toast("override failed (score the problem first)");
    }
  } finally {
    busy = false;
  }
}

async function saveStatement() {
  const id = currentId();
  const form = cardEl.querySelector("#statement-edit");
  if (!form) return;
  busy = true;
  try {
    const resp = await fetch(`/problem/${id}/statement`, {
      method: "POST",
      body: new URLSearchParams({ statement: form.querySelector("textarea").value }),
    });
    if (resp.ok) {
      swapCard(await resp.text());
      toast("statement saved");
    }
  } finally {
    busy = false;
  }
}

function dimKeys() {
  return [...cardEl.querySelectorAll(".dim")].map((d) => d.dataset.dim);
}

function clearPending() {
  pendingDim = null;
  clearTimeout(pendingTimer);
}

function toggleStatementEdit() {
  const form = cardEl.querySelector("#statement-edit");
  const text = cardEl.querySelector("#statement-text");
  if (!form) return;
  const showing = !form.hidden;
  form.hidden = showing;
  if (text) text.hidden = !showing;
  if (!showing) {
    const ta = form.querySelector("textarea");
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
}

// --- event wiring ------------------------------------------------------------

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  const editing = tag === "textarea" || tag === "select" || tag === "input";

  if (editing) {
    if (e.key === "Escape") {
      e.target.blur();
      const form = cardEl.querySelector("#statement-edit");
      if (form && !form.hidden) toggleStatementEdit();
    }
    if (tag === "textarea" && e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      saveStatement();
    }
    return; // don't fire global shortcuts while typing
  }

  if (busy) return; // an action is in flight — ignore key-mashing until it settles

  // override value capture: 0-5 after a dimension was chosen
  if (pendingDim !== null && /^[0-5]$/.test(e.key)) {
    const dim = pendingDim;
    clearPending();
    override(dim, Number(e.key));
    return;
  }

  switch (e.key) {
    case "j": index++; loadCard(); break;
    case "k": index--; loadCard(); break;
    case "s": setStatus("shortlist"); break;
    case "p": setStatus("parked"); break;
    case "x": setStatus("dead"); break;
    case "e": toggleStatementEdit(); break;
    case "c": {
      const sel = cardEl.querySelector("#sel-industry");
      if (sel) sel.focus();
      break;
    }
    default:
      if (/^[1-6]$/.test(e.key)) {
        const dim = dimKeys()[Number(e.key) - 1];
        if (dim) {
          pendingDim = dim;
          toast(`override ${dim.replace(/_/g, " ")}: press 0-5`);
          clearTimeout(pendingTimer);
          pendingTimer = setTimeout(clearPending, 3000);
        }
      }
  }
});

// Category change posts on select and swaps the card (keyboard-operable, no mouse needed).
document.addEventListener("change", async (e) => {
  const form = e.target.closest(".cat-form");
  if (!form || busy) return;
  busy = true;
  try {
    const resp = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (resp.ok) {
      swapCard(await resp.text());
      toast("category updated");
    }
  } finally {
    busy = false;
  }
});

loadCard();
