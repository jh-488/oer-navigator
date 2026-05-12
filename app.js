const API = "http://localhost:8000";

let state = {
  classification: null,
  currentAxis: null,
  selectedOption: null,
  lastResults: [],
  lastVisualization: null,
  negativeKeywords: [],
  excludeIds: [],
  refining: false,
  searching: false,
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
const providerBadge = document.getElementById("provider-badge");
const personaAvatar = document.getElementById("persona-avatar");
const brandMascot = document.getElementById("brand-mascot");
const resultsSection = document.getElementById("results-section");
const resultsContainer = document.getElementById("results-container");
const viewLabel = document.getElementById("view-label");
const loading = document.getElementById("loading");
const errorBanner = document.getElementById("error-banner");

// --- Brand mascot state animation ---
function setMascotState(s) {
  if (!brandMascot) return;
  brandMascot.classList.remove("m-idle", "m-loading", "m-eureka", "m-sleep");
  brandMascot.classList.add("m-" + s);
  if (s === "loading") {
    brandMascot.style.animation = "lali-spin 1.4s linear infinite";
  } else if (s === "eureka") {
    brandMascot.style.animation = "lali-pop 0.5s ease-out 1";
    brandMascot.style.transform = "scale(1.05)";
  } else if (s === "sleep") {
    brandMascot.style.animation = "none";
    brandMascot.style.opacity = "0.7";
  } else {
    brandMascot.style.animation = "none";
    brandMascot.style.opacity = "1";
    brandMascot.style.transform = "scale(1)";
  }
}

// --- Event listeners ---
searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query || searchBtn.disabled || state.searching) return;
  await runClassify(query);
});

queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!searchBtn.disabled) searchForm.requestSubmit();
  }
});

clarificationSubmit.addEventListener("click", async () => {
  const answer = state.selectedOption || clarificationFree.value.trim();
  if (!answer) return;
  await runClarify(state.currentAxis, answer);
});

clarificationFree.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    clarificationSubmit.click();
  }
});

// --- API calls ---
async function runClassify(query) {
  if (state.searching) return;
  state.searching = true;
  setLoading(true);
  hideError();
  hide(clarificationSection);
  hide(profileSection);
  resultsContainer.innerHTML = "";
  hide(resultsSection);
  state.negativeKeywords = [];
  state.excludeIds = [];
  state.lastResults = [];

  try {
    const res = await post("/classify", { query });
    state.classification = res.classification;
    updateProfile(res.classification, res.provider);

    if (res.clarification_needed) {
      state.searching = false;
      showClarification(res.question);
    } else {
      await runSearch();
    }
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
    state.searching = false;
  }
}

async function runClarify(axis, answer) {
  setLoading(true);
  hideError();
  hide(clarificationSection);

  try {
    const res = await post("/clarify", {
      classification: state.classification,
      axis,
      answer,
    });
    state.classification = res.classification;
    updateProfile(res.classification);

    if (res.clarification_needed) {
      showClarification(res.question);
    } else {
      await runSearch();
    }
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

async function runSearch() {
  setLoading(true);
  try {
    const res = await post("/search", {
      classification: state.classification,
      size: 12,
      negative_keywords: state.negativeKeywords,
      exclude_ids: state.excludeIds,
    });
    state.lastResults = res.results || [];
    state.lastVisualization = res.visualization;
    renderResults(res);
    show(resultsSection);
    setMascotState(state.lastResults.length ? "eureka" : "sleep");
    setTimeout(() => setMascotState("idle"), 1500);
    resultsSection.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

async function runRefine(rejected, cardEl) {
  if (state.refining) return;
  state.refining = true;
  if (cardEl) cardEl.classList.add("removing");
  setLoading(true);
  hideError();
  try {
    const res = await post("/refine", {
      classification: state.classification,
      rejected,
      candidates: state.lastResults,
      size: 12,
      prior_negative_keywords: state.negativeKeywords,
      prior_exclude_ids: state.excludeIds,
    });

    if (res.classification) {
      state.classification = res.classification;
      updateProfile(res.classification);
    }
    state.negativeKeywords = res.negative_keywords || [];
    state.excludeIds = res.exclude_ids || [];
    state.lastResults = res.results || [];
    state.lastVisualization = res.visualization;

    await new Promise((resolve) => setTimeout(resolve, 0));
    renderResults(res);
    show(resultsSection);
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    if (cardEl) cardEl.classList.remove("removing");
    showError(err.message);
  } finally {
    setLoading(false);
    state.refining = false;
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
      btn.type = "button";
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

function detectPersona(clf) {
  const rolle = clf.rolle;
  const stufe = clf.bildungsstufe;
  if (rolle === "Lernende" && ["Bachelor", "Master", "Promotion"].includes(stufe)) {
    return { name: "Studierender", image: "images/Studierender.jpg" };
  }
  if (rolle === "Lehrende" && ["Sekundarstufe I", "Sekundarstufe II", "Berufsschule"].includes(stufe)) {
    return { name: "Lehrerin", image: "images/Lehrerin.jpg" };
  }
  return null;
}

function updatePersonaAvatar(clf) {
  const persona = detectPersona(clf);
  if (persona) {
    personaAvatar.className = "persona-known";
    personaAvatar.title = persona.name;
    personaAvatar.innerHTML = `<img src="${persona.image}" alt="${persona.name}" />`;
  } else {
    personaAvatar.className = "persona-unknown";
    personaAvatar.title = "Persona unbekannt";
    personaAvatar.innerHTML = `<span class="persona-fallback">?</span>`;
  }
}

function updateProfile(clf, provider) {
  const tags = [];
  if (clf.intention) tags.push(clf.intention);
  if (clf.vorwissen) tags.push(clf.vorwissen);
  if (clf.rolle) tags.push(clf.rolle);
  if (clf.bildungsstufe) tags.push(clf.bildungsstufe);
  if (clf.einsatzkontext) tags.push(clf.einsatzkontext);
  if (clf.suchmodus) tags.push(clf.suchmodus);
  if (clf.thema) tags.push(clf.thema);
  if (clf.format_preferred) tags.push(clf.format_preferred);
  if (clf.language) tags.push(clf.language === "de" ? "Deutsch" : clf.language === "en" ? "Englisch" : clf.language);

  profileTags.innerHTML = tags
    .map((t) => `<span class="profile-tag">${escHtml(t)}</span>`)
    .join("");
  if (provider) {
    providerBadge.textContent = `KI · ${provider}`;
    providerBadge.classList.remove("hidden");
  }
  updatePersonaAvatar(clf);
  show(profileSection);
}

function renderResults(res) {
  const viz = res.visualization;
  const items = res.results || [];
  viewLabel.textContent = `Ansicht: ${viz.name}`;
  resultsContainer.className = "";
  resultsContainer.innerHTML = "";

  if (viz.id === "V3") {
    renderCards(items);
  } else if (viz.id === "V4") {
    renderFaceted(items);
  } else if (viz.id === "V1" || viz.id === "V2" || viz.id === "V5") {
    renderGraph(items);
  } else {
    renderList(items);
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
    item.innerHTML = `<input type="checkbox" /> <span>${escHtml(v)}</span>`;
    group.appendChild(item);
  });
  return group;
}

function renderGraph(items) {
  const canvas = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  canvas.id = "graph-canvas";
  resultsContainer.appendChild(canvas);

  const width = canvas.parentElement.clientWidth || 800;
  const height = Math.max(520, window.innerHeight * 0.7);

  const svg = d3.select("#graph-canvas")
    .attr("width", width)
    .attr("height", height);

  const zoomLayer = svg.append("g");
  const gLink = zoomLayer.append("g");
  const gNode = zoomLayer.append("g");

  svg.call(d3.zoom()
    .scaleExtent([0.3, 3])
    .on("zoom", (e) => zoomLayer.attr("transform", e.transform)));

  const hint = document.createElement("p");
  hint.id = "graph-hint";
  hint.textContent = "Scroll zum Zoomen · Ziehen zum Verschieben · Knoten klicken zum Erweitern";
  canvas.insertAdjacentElement("afterend", hint);

  let nextId = 0;
  const centerNode = { id: nextId++, name: truncate(state.classification?.thema || "Thema", 30), url: "#", isCenter: true };
  const allNodes = [centerNode];
  const allLinks = [];

  items.slice(0, 12).forEach((item) => {
    const n = { id: nextId++, name: truncate(item.name || "?", 28), url: item.id || item["@id"] || "#", item };
    allNodes.push(n);
    allLinks.push({ source: centerNode.id, target: n.id });
  });

  const sim = d3.forceSimulation(allNodes)
    .force("link", d3.forceLink(allLinks).id((d) => d.id).distance(130))
    .force("charge", d3.forceManyBody().strength(-220))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide(40));

  function update() {
    const link = gLink.selectAll("line").data(allLinks, (d) => `${d.source.id ?? d.source}-${d.target.id ?? d.target}`);
    link.enter().append("line").attr("class", "link");
    link.exit().remove();

    const node = gNode.selectAll("g.node").data(allNodes, (d) => d.id);

    const nodeEnter = node.enter().append("g").attr("class", "node")
      .call(d3.drag()
        .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    nodeEnter.append("circle")
      .attr("r", (d) => d.isCenter ? 20 : 12)
      .style("fill", (d) => d.isCenter ? "#9ee64a" : d.expanded ? "#ffd23f" : "#ff6049")
      .style("stroke", "#142a2a")
      .style("stroke-width", "2.5px")
      .style("cursor", (d) => d.isCenter ? "default" : "pointer")
      .on("click", async (e, d) => {
        e.stopPropagation();
        if (d.isCenter || d.expanded) return;
        d.expanded = true;
        d3.select(e.currentTarget).style("fill", "#ffd23f");

        try {
          const res = await post("/search", {
            classification: { ...state.classification, thema: d.name },
            size: 6,
            negative_keywords: state.negativeKeywords,
            exclude_ids: allNodes.filter(n => n.url && n.url !== "#").map(n => n.url),
          });
          (res.results || []).slice(0, 6).forEach((item) => {
            const child = { id: nextId++, name: truncate(item.name || "?", 28), url: item.id || item["@id"] || "#", item, x: d.x, y: d.y };
            allNodes.push(child);
            allLinks.push({ source: d.id, target: child.id });
          });
          sim.nodes(allNodes);
          sim.force("link").links(allLinks);
          sim.alpha(0.4).restart();
          update();
        } catch (_) {}
      });

    nodeEnter.append("text")
      .attr("dy", (d) => d.isCenter ? 36 : 26)
      .attr("text-anchor", "middle")
      .style("font-size", (d) => d.isCenter ? "0.85rem" : "0.72rem")
      .text((d) => d.name);

    nodeEnter.filter((d) => !d.isCenter && d.url && d.url !== "#")
      .append("text")
      .attr("dy", -14)
      .attr("dx", 12)
      .attr("text-anchor", "middle")
      .style("font-size", "0.7rem")
      .style("cursor", "pointer")
      .style("fill", "#142a2a")
      .text("↗")
      .on("click", (e, d) => {
        e.stopPropagation();
        window.open(d.url, "_blank");
      });

    node.exit().remove();

    sim.nodes(allNodes);
    sim.force("link").links(allLinks);
    sim.alpha(0.3).restart();
  }

  sim.on("tick", () => {
    gLink.selectAll("line")
      .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    gNode.selectAll("g.node")
      .attr("transform", (d) => `translate(${d.x},${d.y})`);
  });

  update();
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
    <button class="card-remove" type="button" title="Dieses und ähnliche Ergebnisse entfernen" aria-label="Entfernen">×</button>
    <h3><a href="${url}" target="_blank" rel="noopener">${escHtml(name)}</a></h3>
    ${desc ? `<p class="desc">${escHtml(truncate(desc, 180))}</p>` : ""}
    <div class="meta">
      ${lang ? `<span class="meta-tag">${escHtml(lang)}</span>` : ""}
      ${format ? `<span class="meta-tag">${escHtml(format)}</span>` : ""}
      ${license ? `<span class="meta-tag">${escHtml(truncate(license, 30))}</span>` : ""}
    </div>
  `;
  card.querySelector(".card-remove").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    runRefine(item, card);
  }, { once: true });
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
  if (on) {
    show(loading);
    setMascotState("loading");
  } else {
    hide(loading);
    setMascotState("idle");
  }
}

function showError(msg) {
  errorBanner.textContent = "Fehler: " + msg;
  show(errorBanner);
  setMascotState("sleep");
}

function hideError() { hide(errorBanner); }
function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

// Initial state
setMascotState("idle");
