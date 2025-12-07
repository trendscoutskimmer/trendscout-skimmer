// ---------- STATE ----------
let products = [];
let filtered = [];
let currentSortKey = "agentScore";
let currentSortDirection = "desc"; // "asc" | "desc"

// ---------- API LOAD ----------
async function loadProducts() {
  try {
    const res = await fetch("/api/products");
    const data = await res.json();

    products = data.products || [];
    filtered = [...products];

    renderTable();
  } catch (err) {
    console.error("Failed to load products", err);
    products = [];
    filtered = [];
    renderTable();
  }
}

// ---------- UTILITIES ----------
function formatCurrency(value) {
  if (value == null || isNaN(value)) return "$0.00";
  return `$${Number(value).toFixed(2)}`;
}

function formatNumber(value) {
  const n = Number(value) || 0;
  if (n >= 1_000_000) {
    return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  }
  if (n >= 1_000) {
    return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  }
  return n.toString();
}

function buildStars(rating) {
  const r = Number(rating) || 0;
  const full = Math.floor(r);
  const hasHalf = r - full >= 0.25 && r - full < 0.75;
  const totalStars = 5;

  let stars = "";
  for (let i = 0; i < totalStars; i++) {
    if (i < full) {
      stars += "★";
    } else if (i === full && hasHalf) {
      stars += "☆"; // could be half icon later
    } else {
      stars += "☆";
    }
  }
  return stars;
}

function sortProducts(list, key, direction) {
  const sorted = [...list].sort((a, b) => {
    const aVal = a[key];
    const bVal = b[key];

    if (typeof aVal === "number" || typeof bVal === "number") {
      const an = Number(aVal) || 0;
      const bn = Number(bVal) || 0;
      return direction === "asc" ? an - bn : bn - an;
    }

    const aStr = String(aVal || "").toLowerCase();
    const bStr = String(bVal || "").toLowerCase();
    if (aStr < bStr) return direction === "asc" ? -1 : 1;
    if (aStr > bStr) return direction === "asc" ? 1 : -1;
    return 0;
  });

  return sorted;
}

function toLabel(key) {
  switch (key) {
    case "price":
      return "Price";
    case "commission":
      return "Commission %";
    case "agentScore":
      return "Agent Score";
    case "virality":
      return "Virality";
    case "views7d":
      return "7-Day Views";
    case "rating":
      return "Rating";
    case "name":
      return "Name";
    default:
      return key;
  }
}

// ---------- RENDER ----------
function renderTable() {
  const tbody = document.getElementById("product-tbody");
  if (!tbody) return;

  tbody.innerHTML = "";

  const sorted = sortProducts(filtered, currentSortKey, currentSortDirection);

  sorted.forEach((p) => {
    const tr = document.createElement("tr");

    const name = p.name || "";
    const category = p.category || "Unknown";
    const price = Number(p.price) || 0;
    const commission = Number(p.commission) || 0;
    const agentScore = Number(p.agentScore) || 0;
    const virality = Number(p.virality) || 0;
    const views7d = Number(p.views7d) || 0;
    const rating = Number(p.rating) || 0;
    const tiktokUrl = p.tiktokUrl || "#";
    const shopUrl = p.shopUrl || "#";

    tr.innerHTML = `
      <td>
        <div class="ts-name-cell">
          <span class="ts-name">${name}</span>
          <span class="ts-category-pill">${category}</span>
        </div>
      </td>
      <td>
        <span class="ts-num">${formatCurrency(price)}</span>
      </td>
      <td>
        <span class="ts-num">${commission}%</span>
      </td>
      <td>
        <div class="ts-agent-pill">
          <span class="ts-agent-label">Agent</span>
          <span class="ts-agent-score ts-num">${agentScore.toFixed(2)}</span>
        </div>
      </td>
      <td>
        <span class="ts-num">${virality.toFixed(1)}</span>
      </td>
      <td>
        <div class="ts-num ts-num-muted">${formatNumber(views7d)}</div>
      </td>
      <td>
        <div class="ts-rating-cell">
          <span class="ts-stars">${buildStars(rating)}</span>
          <span class="ts-rating-score">${rating.toFixed(1)}</span>
        </div>
      </td>
      <td class="col-links">
        <div class="ts-links">
          <a href="${tiktokUrl}" class="ts-link-btn ts-link-tiktok" target="_blank" rel="noopener noreferrer">
            TikTok
          </a>
          <a href="${shopUrl}" class="ts-link-btn ts-link-shop" target="_blank" rel="noopener noreferrer">
            Shop
          </a>
        </div>
      </td>
    `;

    tbody.appendChild(tr);
  });

  const countLabel = document.getElementById("product-count");
  if (countLabel) {
    countLabel.textContent = `${sorted.length} product${sorted.length !== 1 ? "s" : ""}`;
  }

  const sortLabel = document.getElementById("active-sort-label");
  if (sortLabel) {
    const directionLabel = currentSortDirection === "asc" ? "asc" : "desc";
    sortLabel.textContent = `Sorted by ${toLabel(currentSortKey)} (${directionLabel})`;
  }

  updateHeaderSortState();
}

// ---------- SORT HEADER UI ----------
function updateHeaderSortState() {
  const ths = document.querySelectorAll("#product-table thead th");
  ths.forEach((th) => {
    th.classList.remove("is-active-sort", "desc");
    const key = th.getAttribute("data-sort-key");
    if (!key) return;
    if (key === currentSortKey) {
      th.classList.add("is-active-sort");
      if (currentSortDirection === "desc") {
        th.classList.add("desc");
      }
    }
  });
}

// ---------- FILTERS ----------
function applySearchFilter(term) {
  const t = term.trim().toLowerCase();
  if (!t) {
    filtered = [...products];
  } else {
    filtered = products.filter((p) => {
      const nameMatch = (p.name || "").toLowerCase().includes(t);
      const categoryMatch = (p.category || "").toLowerCase().includes(t);
      return nameMatch || categoryMatch;
    });
  }
  renderTable();
}

// ---------- EVENTS ----------
document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("search-input");
  const clearSearchBtn = document.getElementById("clear-search");
  const sortPayoutBtn = document.getElementById("sort-payout-btn");
  const sortViralityBtn = document.getElementById("sort-virality-btn");

  // Load data from backend
  loadProducts();

  // Search
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      applySearchFilter(e.target.value);
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      if (searchInput) {
        searchInput.value = "";
      }
      applySearchFilter("");
      if (searchInput) searchInput.focus();
    });
  }

  // Column header sorting
  const headerCells = document.querySelectorAll("#product-table thead th[data-sort-key]");
  headerCells.forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort-key");
      if (!key) return;

      if (currentSortKey === key) {
        currentSortDirection = currentSortDirection === "asc" ? "desc" : "asc";
      } else {
        currentSortKey = key;
        currentSortDirection = key === "name" ? "asc" : "desc";
      }

      renderTable();
    });
  });

  // Helper buttons
  if (sortPayoutBtn) {
    sortPayoutBtn.addEventListener("click", () => {
      currentSortKey = "agentScore";
      currentSortDirection = "desc";
      renderTable();
    });
  }

  if (sortViralityBtn) {
    sortViralityBtn.addEventListener("click", () => {
      currentSortKey = "virality";
      currentSortDirection = "desc";
      renderTable();
    });
  }
});

