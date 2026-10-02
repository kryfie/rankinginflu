const state = {
  creators: [],
  excluded: [],
  filtered: [],
  category: "Wszystkie",
  query: "",
  verifiedOnly: false,
  sort: "rank",
  city: "Wszystkie",
  page: 1,
  pageSize: 100,
  generatedAt: null,
};

const $ = (selector) => document.querySelector(selector);

const els = {
  body: $("#rankingBody"),
  categories: $("#categoryFilters"),
  search: $("#searchInput"),
  sort: $("#sortSelect"),
  city: $("#citySelect"),
  verified: $("#verifiedOnly"),
  pageSize: $("#pageSizeSelect"),
  pagination: $("#pagination"),
  paginationButtons: $("#paginationButtons"),
  pageRange: $("#pageRange"),
  topThree: $("#topThree"),
  backdrop: $("#drawerBackdrop"),
  drawer: $("#creatorDrawer"),
  drawerContent: $("#drawerContent"),
  drawerClose: $("#drawerClose"),
};

const categoryLabels = {
  "Entertainment": "Entertainment",
  "Lifestyle": "Lifestyle",
  "Beauty": "Beauty",
  "Fashion": "Fashion",
  "Gaming": "Gaming",
  "Food": "Food",
  "Sport & Fitness": "Sport & Fitness",
  "Tech": "Tech",
  "Education": "Education",
  "Travel": "Travel",
  "Music": "Music",
  "Finance": "Finance",
  "Other": "Other",
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatCompact(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("pl-PL", {
    notation: "compact",
    maximumFractionDigits: n >= 1_000_000 ? 1 : 0,
  }).format(n);
}

function formatNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("pl-PL", {
    maximumFractionDigits: 0,
  }).format(n);
}

function formatPercent(value, digits = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

function formatScore(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("pl-PL", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function median(values) {
  const a = values
    .map(Number)
    .filter(Number.isFinite)
    .sort((x, y) => x - y);
  if (!a.length) return 0;
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}

function avatarMarkup(creator, extraClass = "") {
  const src = escapeHtml(creator.avatar || "");
  const fallback = escapeHtml((creator.name || creator.handle || "?").slice(0, 1).toUpperCase());
  if (!src) {
    return `<span class="avatar ${extraClass}" style="display:grid;place-items:center;font-weight:900;color:#8fa4bd">${fallback}</span>`;
  }
  return `<img class="avatar ${extraClass}" src="${src}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="avatar ${extraClass}" style="display:none;place-items:center;font-weight:900;color:#8fa4bd">${fallback}</span>`;
}

function verifiedMarkup(creator) {
  return creator.verified ? `<span class="verified-mark" title="Zweryfikowane konto">✓</span>` : "";
}

function renderSkeleton() {
  els.body.innerHTML = Array.from({ length: 8 }, () => `
    <tr class="skeleton-row">
      <td><span class="skeleton" style="width:22px"></span></td>
      <td><span class="skeleton" style="width:170px"></span></td>
      <td><span class="skeleton" style="width:72px"></span></td>
      <td><span class="skeleton" style="width:78px"></span></td>
      <td><span class="skeleton" style="width:58px;margin-left:auto"></span></td>
      <td><span class="skeleton" style="width:67px;margin-left:auto"></span></td>
      <td><span class="skeleton" style="width:48px;margin-left:auto"></span></td>
      <td><span class="skeleton" style="width:25px;margin-left:auto"></span></td>
      <td><span class="skeleton" style="width:75px;margin-left:auto"></span></td>
    </tr>
  `).join("");
}

function applyFilters() {
  const q = state.query.trim().toLowerCase();

  let rows = state.creators.filter((c) => {
    const categoryOk = state.category === "Wszystkie" || c.category === state.category;
    const cityOk = state.city === "Wszystkie" || c.city === state.city;
    const verifiedOk = !state.verifiedOnly || Boolean(c.verified);
    const searchOk = !q ||
      String(c.name || "").toLowerCase().includes(q) ||
      String(c.handle || "").toLowerCase().includes(q) ||
      String(c.city || "").toLowerCase().includes(q) ||
      String(c.home_city || "").toLowerCase().includes(q);
    return categoryOk && cityOk && verifiedOk && searchOk;
  });

  rows = [...rows].sort((a, b) => {
    if (state.sort === "followers") return Number(b.followers || 0) - Number(a.followers || 0);
    if (state.sort === "views") return Number(b.views || 0) - Number(a.views || 0);
    if (state.sort === "engagement") return Number(b.engagement || 0) - Number(a.engagement || 0);
    return Number(a.rank || 999999) - Number(b.rank || 999999);
  });

  state.filtered = rows;
  const pageCount = Math.max(1, Math.ceil(rows.length / state.pageSize));
  state.page = Math.min(state.page, pageCount);
  renderTable();
}

function renderCategories() {
  const counts = new Map();
  for (const c of state.creators) {
    counts.set(c.category || "Other", (counts.get(c.category || "Other") || 0) + 1);
  }

  const categories = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
  const all = ["Wszystkie", ...categories];

  els.categories.innerHTML = all.map((category) => {
    const count = category === "Wszystkie" ? state.creators.length : counts.get(category);
    return `
      <button class="category-chip ${state.category === category ? "active" : ""}"
              data-category="${escapeHtml(category)}"
              type="button">
        ${escapeHtml(categoryLabels[category] || category)}
        <span>${count}</span>
      </button>
    `;
  }).join("");

  els.categories.querySelectorAll(".category-chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.category = button.dataset.category;
      state.page = 1;
      renderCategories();
      applyFilters();
    });
  });
}

function renderCities() {
  const counts = new Map();
  for (const c of state.creators) {
    if (!c.city) continue;
    counts.set(c.city, (counts.get(c.city) || 0) + 1);
  }

  const cities = [...counts.keys()].sort((a, b) =>
    a.localeCompare(b, "pl", { sensitivity: "base" })
  );

  els.city.innerHTML = [
    `<option value="Wszystkie">Wszystkie miasta</option>`,
    ...cities.map((city) => `<option value="${escapeHtml(city)}">${escapeHtml(city)} (${counts.get(city)})</option>`),
  ].join("");

  if (cities.includes(state.city)) {
    els.city.value = state.city;
  } else {
    state.city = "Wszystkie";
    els.city.value = "Wszystkie";
  }
}

function renderTopThree() {
  const top = [...state.creators]
    .sort((a, b) => Number(a.rank || 999999) - Number(b.rank || 999999))
    .slice(0, 3);

  els.topThree.innerHTML = top.map((c) => `
    <article class="podium-card" data-handle="${escapeHtml(c.handle)}" role="button" tabindex="0">
      <span class="podium-rank rank-${c.rank}">#${c.rank}</span>
      <div class="table-creator">
        ${avatarMarkup(c, "podium-avatar")}
        <div class="creator-main">
          <div class="creator-name-row">
            <span class="creator-name">${escapeHtml(c.name || c.handle)}</span>
            ${verifiedMarkup(c)}
          </div>
          <div class="creator-handle">@${escapeHtml(c.handle)}</div>
          ${c.city ? `<div class="creator-city">${escapeHtml(c.city)}</div>` : ""}
        </div>
      </div>
      <div class="podium-score">
        <strong>${formatScore(c.score)}</strong>
        <small>SCORE</small>
      </div>
    </article>
  `).join("");

  els.topThree.querySelectorAll(".podium-card").forEach((card) => {
    const open = () => openDrawer(card.dataset.handle);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
}

function renderPagination(totalRows) {
  const pageCount = Math.max(1, Math.ceil(totalRows / state.pageSize));
  const startRow = totalRows ? (state.page - 1) * state.pageSize + 1 : 0;
  const endRow = Math.min(totalRows, state.page * state.pageSize);
  els.pageRange.textContent = totalRows ? `${startRow}–${endRow} z ${totalRows}` : "0 wyników";

  if (pageCount <= 1) {
    els.paginationButtons.innerHTML = "";
    return;
  }

  const pages = new Set([1, pageCount, state.page - 2, state.page - 1, state.page, state.page + 1, state.page + 2]);
  const ordered = [...pages].filter((p) => p >= 1 && p <= pageCount).sort((a, b) => a - b);
  const parts = [];

  parts.push(`<button class="page-button page-arrow" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""} aria-label="Poprzednia strona">‹</button>`);

  let previous = 0;
  for (const page of ordered) {
    if (previous && page - previous > 1) {
      parts.push(`<span class="page-ellipsis">…</span>`);
    }
    parts.push(`<button class="page-button ${page === state.page ? "active" : ""}" data-page="${page}">${page}</button>`);
    previous = page;
  }

  parts.push(`<button class="page-button page-arrow" data-page="${state.page + 1}" ${state.page === pageCount ? "disabled" : ""} aria-label="Następna strona">›</button>`);
  els.paginationButtons.innerHTML = parts.join("");

  els.paginationButtons.querySelectorAll("button[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = Number(button.dataset.page);
      if (!Number.isFinite(next) || next < 1 || next > pageCount || next === state.page) return;
      state.page = next;
      renderTable();
      document.querySelector(".ranking-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function renderTable() {
  const start = (state.page - 1) * state.pageSize;
  const visibleRows = state.filtered.slice(start, start + state.pageSize);

  $("#resultsCount").textContent = `${state.filtered.length} ${state.filtered.length === 1 ? "wynik" : "wyników"}`;

  if (!visibleRows.length) {
    els.body.innerHTML = `
      <tr><td colspan="9" class="empty-state">
        Brak twórców pasujących do wybranych filtrów.
      </td></tr>
    `;
  } else {
    els.body.innerHTML = visibleRows.map((c) => {
      const growth = Number.isFinite(Number(c.growth))
        ? `<span class="${Number(c.growth) >= 0 ? "engagement-good" : ""}">${formatPercent(c.growth)}</span>`
        : `<span class="muted-value" title="Wzrost 30D pojawi się po zebraniu historii">—</span>`;

      const city = c.city
        ? `<span class="city-badge" title="Powiązanie z miastem na podstawie publicznych sygnałów GEO">${escapeHtml(c.city)}</span>`
        : `<span class="muted-value">—</span>`;

      return `
        <tr data-handle="${escapeHtml(c.handle)}">
          <td><span class="rank-number">#${escapeHtml(c.rank)}</span></td>
          <td>
            <div class="table-creator">
              ${avatarMarkup(c)}
              <div class="creator-main">
                <div class="creator-name-row">
                  <span class="creator-name">${escapeHtml(c.name || c.handle)}</span>
                  ${verifiedMarkup(c)}
                </div>
                <div class="creator-handle">@${escapeHtml(c.handle)}</div>
              </div>
            </div>
          </td>
          <td><span class="category-badge">${escapeHtml(categoryLabels[c.category] || c.category || "Other")}</span></td>
          <td>${city}</td>
          <td class="numeric"><span class="numeric-value">${formatCompact(c.followers)}</span></td>
          <td class="numeric"><span class="numeric-value">${formatCompact(c.views)}</span></td>
          <td class="numeric"><span class="numeric-value ${Number(c.engagement) >= 5 ? "engagement-good" : ""}">${formatPercent(c.engagement)}</span></td>
          <td class="numeric">${growth}</td>
          <td class="numeric">
            <span class="score-cell">
              <span class="score-bar"><span style="width:${Math.min(100, Math.max(0, Number(c.score || 0)))}%"></span></span>
              <span class="score-number">${formatScore(c.score)}</span>
            </span>
          </td>
        </tr>
      `;
    }).join("");
  }

  els.body.querySelectorAll("tr[data-handle]").forEach((row) => {
    row.addEventListener("click", () => openDrawer(row.dataset.handle));
  });

  renderPagination(state.filtered.length);
}

function componentRows(components = {}) {
  const rows = [
    ["Widownia", components.audience],
    ["Zasięg", components.reach],
    ["Zaangażowanie", components.engagement],
    ["Regularność", components.consistency],
    ["Wzrost 30D", components.momentum],
  ];

  return rows.map(([label, value]) => {
    const active = Number.isFinite(Number(value));
    const width = active ? Math.min(100, Math.max(0, Number(value))) : 0;
    return `
      <div class="component-row">
        <span>${escapeHtml(label)}</span>
        <span class="component-track"><span style="width:${width}%;opacity:${active ? 1 : 0.18}"></span></span>
        <span class="component-value">${active ? formatScore(value) : "—"}</span>
      </div>
    `;
  }).join("");
}

function geoDetailsMarkup(c) {
  const contentCities = Array.isArray(c.content_cities) ? c.content_cities.slice(0, 5) : [];
  if (!c.city && !c.home_city && !contentCities.length) {
    return `
      <div class="geo-section">
        <div class="geo-section-head">
          <h4>GEO</h4>
          <span class="geo-confidence muted-value">brak danych</span>
        </div>
        <p class="geo-note">Nie znaleźliśmy jeszcze wystarczająco mocnego publicznego sygnału lokalizacji.</p>
      </div>
    `;
  }

  const chips = contentCities.map((item) => `
    <span class="geo-chip">
      ${escapeHtml(item.city || "—")}
      <small>${formatScore(item.confidence)}%</small>
    </span>
  `).join("");

  return `
    <div class="geo-section">
      <div class="geo-section-head">
        <h4>GEO</h4>
        <span class="geo-confidence">confidence ${formatScore(c.geo_confidence)}%</span>
      </div>
      <div class="geo-primary-grid">
        <div>
          <span>Powiązane miasto</span>
          <strong>${escapeHtml(c.city || "—")}</strong>
        </div>
        <div>
          <span>Miasto z bio</span>
          <strong>${escapeHtml(c.home_city || "—")}</strong>
        </div>
      </div>
      ${chips ? `<div class="geo-chips">${chips}</div>` : ""}
      <p class="geo-note">GEO jest wnioskowane z publicznego bio, treści postów i POI TikToka. „Powiązane miasto” nie musi oznaczać miejsca zamieszkania.</p>
    </div>
  `;
}

function openDrawer(handle) {
  const c = state.creators.find((row) => row.handle === handle);
  if (!c) return;

  els.drawerContent.className = "drawer-content";
  els.drawerContent.innerHTML = `
    <div class="drawer-profile">
      ${avatarMarkup(c, "drawer-avatar")}
      <div>
        <div class="creator-name-row">
          <h3>${escapeHtml(c.name || c.handle)}</h3>
          ${verifiedMarkup(c)}
        </div>
        <div class="drawer-handle">@${escapeHtml(c.handle)}</div>
      </div>
    </div>

    <div class="drawer-rankline">
      <span class="drawer-pill accent">#${escapeHtml(c.rank)} w rankingu</span>
      <span class="drawer-pill">${escapeHtml(categoryLabels[c.category] || c.category || "Other")}</span>
      <span class="drawer-pill">PL confidence ${formatScore(c.pl_confidence)}%</span>
      ${c.city ? `<span class="drawer-pill geo-pill">${escapeHtml(c.city)}</span>` : ""}
    </div>

    <div class="drawer-stats">
      <div class="drawer-stat">
        <span>KtoWybija Score</span>
        <strong>${formatScore(c.score)}</strong>
      </div>
      <div class="drawer-stat">
        <span>Followers</span>
        <strong>${formatNumber(c.followers)}</strong>
      </div>
      <div class="drawer-stat">
        <span>Mediana views</span>
        <strong>${formatNumber(c.views)}</strong>
      </div>
      <div class="drawer-stat">
        <span>Zaangażowanie</span>
        <strong>${formatPercent(c.engagement)}</strong>
      </div>
    </div>

    ${geoDetailsMarkup(c)}

    <div class="component-section">
      <h4>Składniki KtoWybija Score</h4>
      ${componentRows(c.components || {})}
    </div>

    <p class="drawer-disclaimer">
      Score jest obecnie prowizoryczny. Wzrost 30D nie jest jeszcze wliczane,
      dopóki profil nie ma wystarczającej historii followerów.
      Pomiar obejmuje ${escapeHtml(c.posts_measured || "—")} ostatnich postów.
    </p>

    <a class="button button-primary tiktok-link"
       href="https://www.tiktok.com/@${encodeURIComponent(c.handle)}"
       target="_blank"
       rel="noopener noreferrer">
      Otwórz profil na TikTok
    </a>
  `;

  els.backdrop.hidden = false;
  els.drawer.classList.add("open");
  els.drawer.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

function closeDrawer() {
  els.drawer.classList.remove("open");
  els.drawer.setAttribute("aria-hidden", "true");
  els.backdrop.hidden = true;
  document.body.style.overflow = "";
}

function updateSummary() {
  const creators = state.creators;
  const top = [...creators].sort((a, b) => Number(a.rank) - Number(b.rank))[0];
  const totalFollowers = creators.reduce((sum, c) => sum + Number(c.followers || 0), 0);
  const categories = new Set(creators.map((c) => c.category).filter(Boolean)).size;
  const medFollowers = median(creators.map((c) => c.followers));
  const creatorsWithCity = creators.filter((c) => Boolean(c.city)).length;
  const uniqueCities = new Set(creators.map((c) => c.city).filter(Boolean)).size;

  $("#heroTopScore").textContent = top ? formatScore(top.score) : "—";
  $("#heroTopName").textContent = top ? (top.name || top.handle) : "—";
  $("#heroTopHandle").textContent = top ? `@${top.handle}` : "";
  $("#heroCreators").textContent = formatNumber(creators.length);
  $("#heroCategories").textContent = formatNumber(categories);
  $("#heroFollowers").textContent = formatCompact(totalFollowers);

  $("#statCreators").textContent = formatNumber(creators.length);
  $("#statGeo").textContent = `${formatNumber(creatorsWithCity)} / ${formatNumber(creators.length)}`;
  $("#statGeoNote").textContent = `${formatNumber(uniqueCities)} unikalnych miast`;
  $("#statMedianFollowers").textContent = formatCompact(medFollowers);
  $("#statUpdated").textContent = formatDate(state.generatedAt);

  const shortDate = state.generatedAt ? formatDate(state.generatedAt) : "—";
  $("#headerUpdate").innerHTML = `<span class="status-dot"></span><span>Aktualizacja ${shortDate}</span>`;
  $("#datasetLabel").textContent = `${creators.length} twórców • ${shortDate}`;

  const pct = top ? Math.min(100, Math.max(0, Number(top.score || 0))) : 0;
  const ring = document.querySelector(".score-ring");
  ring.style.background = `conic-gradient(var(--accent) 0 ${pct}%, rgba(255,255,255,0.08) ${pct}% 100%)`;
}

async function init() {
  renderSkeleton();

  try {
    const response = await fetch("./data/creators.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const payload = await response.json();
    state.creators = Array.isArray(payload.creators)
      ? payload.creators.filter((c) => c.ranking_eligible !== false)
      : [];
    state.excluded = Array.isArray(payload.excluded_creators) ? payload.excluded_creators : [];
    state.generatedAt = payload.generated_at || null;

    updateSummary();
    renderTopThree();
    renderCategories();
    renderCities();

    state.filtered = [...state.creators];
    applyFilters();
  } catch (error) {
    console.error(error);
    els.body.innerHTML = `
      <tr><td colspan="9" class="empty-state">
        Nie udało się wczytać danych rankingu. Sprawdź plik <code>data/creators.json</code>.
      </td></tr>
    `;
    $("#datasetLabel").textContent = "Błąd danych";
  }
}

els.search.addEventListener("input", (event) => {
  state.query = event.target.value;
  state.page = 1;
  applyFilters();
});

els.sort.addEventListener("change", (event) => {
  state.sort = event.target.value;
  state.page = 1;
  applyFilters();
});

els.city.addEventListener("change", (event) => {
  state.city = event.target.value;
  state.page = 1;
  applyFilters();
});

els.verified.addEventListener("change", (event) => {
  state.verifiedOnly = event.target.checked;
  state.page = 1;
  applyFilters();
});

els.pageSize.addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value) || 100;
  state.page = 1;
  applyFilters();
});

els.drawerClose.addEventListener("click", closeDrawer);
els.backdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

init();
