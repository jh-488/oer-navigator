const API = "http://localhost:8000";

// Watch the results container for being cleared/hidden by any code path
window.addEventListener("DOMContentLoaded", () => {
  const target = document.getElementById("results-container");
  const section = document.getElementById("results-section");
  if (target) {
    new MutationObserver((muts) => {
      muts.forEach((m) => {
        if (m.type === "childList") {
          console.log("[mutation] results-container childList: +", m.addedNodes.length, "-", m.removedNodes.length, "now:", target.children.length);
          if (m.removedNodes.length > 0) console.trace("[mutation] removal stack");
        }
      });
    }).observe(target, { childList: true });
  }
  if (section) {
    new MutationObserver((muts) => {
      muts.forEach((m) => {
        if (m.attributeName === "class") {
          const hidden = section.classList.contains("hidden");
          console.log("[mutation] results-section class changed, hidden=", hidden);
          if (hidden) console.trace("[mutation] hide stack");
        }
      });
    }).observe(section, { attributes: true, attributeFilter: ["class"] });
  }
});

let state = {
  classification: null,
  currentAxis: null,
  selectedOption: null,
};

// --- DOM refs ---
const searchForm = document.getElementById("search-form");
const queryInput = document.getElementById("query-input");
const searchBtn = document.getElementById("search-btn");
const clarificationSection = document.getElementById("clarification-section");
const clarificationQuestion = document.getElementById("clarification-question");
const clarificationOptions = document.getElementById("clarification-options");
const clarificationFree = document.getElementById("clarification-free");
const clarificationSubmit = document.getElementById("clarification-submit");
const profileSection = document.getElementById("profile-section");
const profileTags = document.getElementById("profile-tags");
const resultsSection = document.getElementById("results-section");
const resultsContainer = document.getElementById("results-container");
const viewLabel = document.getElementById("view-label");
const loading = document.getElementById("loading");
const errorBanner = document.getElementById("error-banner");

// --- Event listeners ---
searchForm.addEventListener("submit", async (e) => {
  console.log("[evt] form submit", { isTrusted: e.isTrusted, cancelable: e.cancelable, submitter: e.submitter });
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query || searchBtn.disabled) return;
  await runClassify(query);
});

// Enter in textarea submits, Shift+Enter adds newline
queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    console.log("[evt] textarea Enter -> requestSubmit");
    e.preventDefault();
    searchForm.requestSubmit();
  }
});

clarificationSubmit.addEventListener("click", async (e) => {
  console.log("[evt] clarificationSubmit click", { isTrusted: e.isTrusted });
  const answer = state.selectedOption || clarificationFree.value.trim();
  if (!answer) return;
  await runClarify(state.currentAxis, answer);
});

clarificationFree.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    console.log("[evt] clarificationFree Enter");
    e.preventDefault();
    clarificationSubmit.click();
  }
});

window.addEventListener("beforeunload", (e) => {
  console.warn("[evt] BEFOREUNLOAD — page is about to reload/navigate!");
});

window.addEventListener("pagehide", () => {
  console.warn("[evt] PAGEHIDE");
});

// --- API calls ---
async function runClassify(query) {
  console.log("[runClassify] START — clearing results", { query });
  console.trace("[runClassify] call stack");
  setLoading(true);
  hideError();
  hide(clarificationSection);
  hide(profileSection);
  resultsContainer.innerHTML = "";
  hide(resultsSection);

  try {
    const res = await post("/classify", { query });
    console.log("[runClassify] response", res);
    state.classification = res.classification;
    updateProfile(res.classification);

    if (res.clarification_needed) {
      console.log("[runClassify] -> showClarification");
      showClarification(res.question);
    } else {
      console.log("[runClassify] -> runSearch");
      await runSearch();
    }
  } catch (err) {
    console.error("[runClassify] error", err);
    showError(err.message);
  } finally {
    setLoading(false);
    console.log("[runClassify] END");
  }
}

async function runClarify(axis, answer) {
  console.log("[runClarify] START", { axis, answer });
  console.trace("[runClarify] call stack");
  setLoading(true);
  hideError();
  hide(clarificationSection);

  try {
    const res = await post("/clarify", {
      classification: state.classification,
      axis,
      answer,
    });
    console.log("[runClarify] response", res);
    state.classification = res.classification;
    updateProfile(res.classification);

    if (res.clarification_needed) {
      console.log("[runClarify] -> showClarification");
      showClarification(res.question);
    } else {
      console.log("[runClarify] -> runSearch");
      await runSearch();
    }
  } catch (err) {
    console.error("[runClarify] error", err);
    showError(err.message);
  } finally {
    setLoading(false);
    console.log("[runClarify] END");
  }
}

async function runSearch() {
  console.log("[runSearch] START", { classification: state.classification });
  setLoading(true);
  try {
    const res = await post("/search", { classification: state.classification, size: 12 });
    console.log("[runSearch] response", { total: res.total, viz: res.visualization?.id, results: res.results });
    renderResults(res);
    show(resultsSection);
    console.log("[runSearch] results section shown, container children:", resultsContainer.children.length);
    resultsSection.scrollIntoView({ behavior: "smooth" });
    setTimeout(() => {
      console.log("[runSearch] +500ms check — results visible?", !resultsSection.classList.contains("hidden"), "children:", resultsContainer.children.length);
    }, 500);
    setTimeout(() => {
      console.log("[runSearch] +2000ms check — results visible?", !resultsSection.classList.contains("hidden"), "children:", resultsContainer.children.length);
    }, 2000);
  } catch (err) {
    console.error("[runSearch] error", err);
    showError(err.message);
  } finally {
    setLoading(false);
    console.log("[runSearch] END");
  }
}

async function post(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// --- UI helpers ---
function showClarification(question) {
  state.currentAxis = question.axis;
  state.selectedOption = null;
  clarificationQuestion.textContent = question.frage;
  clarificationOptions.innerHTML = "";
  clarificationFree.value = "";

  if (question.optionen) {
    question.optionen.forEach((opt) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.textContent = opt;
      btn.addEventListener("click", () => {
        document.querySelectorAll(".option-btn").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
        state.selectedOption = opt;
      });
      clarificationOptions.appendChild(btn);
    });
  }

  show(clarificationSection);
}

function updateProfile(clf) {
  const tags = [];
  if (clf.intention) tags.push(clf.intention);
  if (clf.vorwissen) tags.push(clf.vorwissen);
  if (clf.rolle) tags.push(clf.rolle);
  if (clf.thema) tags.push(clf.thema);
  if (clf.format_preferred) tags.push(clf.format_preferred);
  if (clf.language) tags.push(clf.language === "de" ? "Deutsch" : clf.language === "en" ? "Englisch" : clf.language);

  profileTags.innerHTML = tags
    .map((t) => `<span class="profile-tag">${t}</span>`)
    .join("");
  show(profileSection);
}

function renderResults(res) {
  const viz = res.visualization;
  viewLabel.textContent = `Ansicht: ${viz.name}`;
  resultsContainer.className = "";
  resultsContainer.innerHTML = "";

  const intention = state.classification?.intention || "orientieren";

  if (viz.id === "V3") {
    renderCards(res.results);
  } else if (viz.id === "V4") {
    renderFaceted(res.results);
  } else if (viz.id === "V5") {
    renderGraph(res.results);
  } else {
    renderList(res.results);
  }
}

function renderList(items) {
  if (!items.length) {
    resultsContainer.innerHTML = "<p style='color:var(--muted)'>Keine Ergebnisse gefunden.</p>";
    return;
  }
  items.forEach((item) => resultsContainer.appendChild(makeCard(item, false)));
}

function renderCards(items) {
  if (!items.length) {
    resultsContainer.innerHTML = "<p style='color:var(--muted)'>Keine Ergebnisse gefunden.</p>";
    return;
  }
  resultsContainer.classList.add("cards-view");
  items.forEach((item) => resultsContainer.appendChild(makeCard(item, true)));
}

function renderFaceted(items) {
  const wrapper = document.createElement("div");
  wrapper.id = "faceted-wrapper";

  const sidebar = document.createElement("div");
  sidebar.id = "facet-sidebar";

  const formats = [...new Set(items.flatMap((i) => {
    const lrt = i.learningResourceType || [];
    return lrt.map((l) => l?.prefLabel?.de || l?.prefLabel?.en || "").filter(Boolean);
  }))];
  const langs = [...new Set(items.map((i) => i.inLanguage).filter(Boolean))];

  if (formats.length) sidebar.appendChild(makeFacetGroup("Format", formats));
  if (langs.length) sidebar.appendChild(makeFacetGroup("Sprache", langs));

  const list = document.createElement("div");
  list.id = "faceted-results";
  items.forEach((item) => list.appendChild(makeCard(item, false)));

  wrapper.appendChild(sidebar);
  wrapper.appendChild(list);
  resultsContainer.appendChild(wrapper);
}

function makeFacetGroup(label, values) {
  const group = document.createElement("div");
  group.className = "facet-group";
  const h4 = document.createElement("h4");
  h4.textContent = label;
  group.appendChild(h4);
  values.forEach((v) => {
    const item = document.createElement("label");
    item.className = "facet-item";
    item.innerHTML = `<input type="checkbox" /> ${v}`;
    group.appendChild(item);
  });
  return group;
}

function renderGraph(items) {
  const canvas = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  canvas.id = "graph-canvas";
  resultsContainer.appendChild(canvas);

  const width = canvas.parentElement.clientWidth || 800;
  const height = 480;

  const svg = d3.select("#graph-canvas")
    .attr("width", width)
    .attr("height", height);

  const nodes = items.slice(0, 20).map((item, i) => ({
    id: i,
    name: truncate(item.name || "?", 30),
    url: item.id || item["@id"] || "#",
  }));

  const centerNode = { id: -1, name: state.classification?.thema || "Thema", url: "#", isCenter: true };
  const allNodes = [centerNode, ...nodes];
  const links = nodes.map((n) => ({ source: -1, target: n.id }));

  const sim = d3.forceSimulation(allNodes)
    .force("link", d3.forceLink(links).id((d) => d.id).distance(120))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(width / 2, height / 2));

  const link = svg.append("g").selectAll("line")
    .data(links).join("line").attr("class", "link");

  const node = svg.append("g").selectAll("g")
    .data(allNodes).join("g").attr("class", "node")
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  node.append("circle")
    .attr("r", (d) => d.isCenter ? 16 : 8)
    .style("fill", (d) => d.isCenter ? "#1d4ed8" : "var(--primary)")
    .style("cursor", (d) => d.url !== "#" ? "pointer" : "default")
    .on("click", (e, d) => { if (d.url && d.url !== "#") window.open(d.url, "_blank"); });

  node.append("text")
    .attr("dy", (d) => d.isCenter ? 30 : 20)
    .attr("text-anchor", "middle")
    .text((d) => d.name);

  sim.on("tick", () => {
    link
      .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    node.attr("transform", (d) => `translate(${d.x},${d.y})`);
  });
}

function makeCard(item, cardStyle) {
  const card = document.createElement("div");
  card.className = "result-card" + (cardStyle ? " card-style" : "");

  const url = item.id || item["@id"] || item.url || "#";
  const name = item.name || "Ohne Titel";
  const desc = item.description || item.abstract || "";
  const lang = item.inLanguage || "";
  const lrt = item.learningResourceType || [];
  const format = lrt[0]?.prefLabel?.de || lrt[0]?.prefLabel?.en || "";
  const license = item.license?.id || item.license || "";

  card.innerHTML = `
    <h3><a href="${url}" target="_blank" rel="noopener">${escHtml(name)}</a></h3>
    ${desc ? `<p class="desc">${escHtml(truncate(desc, 160))}</p>` : ""}
    <div class="meta">
      ${lang ? `<span class="meta-tag">${escHtml(lang)}</span>` : ""}
      ${format ? `<span class="meta-tag">${escHtml(format)}</span>` : ""}
      ${license ? `<span class="meta-tag">${escHtml(truncate(license, 30))}</span>` : ""}
    </div>
  `;
  return card;
}

function escHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + "…" : str;
}

function setLoading(on) {
  searchBtn.disabled = on;
  on ? show(loading) : hide(loading);
}

function showError(msg) {
  errorBanner.textContent = "Fehler: " + msg;
  show(errorBanner);
}

function hideError() { hide(errorBanner); }
function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }
