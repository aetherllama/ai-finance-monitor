const DATA_URL = 'data/articles.json';
const CATEGORY_COLORS = {
  Banking: 'cat-Banking',
  Trading: 'cat-Trading',
  RegTech: 'cat-RegTech',
  InsurTech: 'cat-InsurTech',
  Payments: 'cat-Payments',
};

let allArticles = [];
let activeCategory = 'All';
let searchQuery = '';
let currentLastUpdated = null;
const POLL_INTERVAL = 60 * 60 * 1000; // 60 minutes

function formatDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatUpdated(isoStr) {
  const d = new Date(isoStr);
  return 'Updated ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function buildCard(article) {
  const a = document.createElement('a');
  a.className = 'card';
  a.href = article.url || '#';
  a.target = article.url && article.url !== '#' ? '_blank' : '_self';
  a.rel = 'noopener noreferrer';

  const catClass = CATEGORY_COLORS[article.category] || 'cat-Default';
  const tags = (article.tags || []).map(t => `<span class="tag">${t}</span>`).join('');

  a.innerHTML = `
    <div class="card-meta">
      <span class="card-category ${catClass}">${article.category}</span>
      <span class="card-date">${formatDate(article.date)}</span>
    </div>
    <h2 class="card-title">${article.title}</h2>
    <p class="card-summary">${article.summary}</p>
    <div class="card-footer">
      <span class="card-source">${article.source}</span>
      <div class="card-tags">${tags}</div>
    </div>
  `;
  return a;
}

function renderArticles() {
  const grid = document.getElementById('articles-grid');
  const countEl = document.getElementById('article-count');

  let filtered = allArticles;

  if (activeCategory !== 'All') {
    filtered = filtered.filter(a => a.category === activeCategory);
  }

  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = filtered.filter(a =>
      a.title.toLowerCase().includes(q) ||
      a.summary.toLowerCase().includes(q) ||
      a.source.toLowerCase().includes(q) ||
      (a.tags || []).some(t => t.toLowerCase().includes(q))
    );
  }

  filtered.sort((a, b) => new Date(b.date) - new Date(a.date));

  grid.innerHTML = '';

  if (filtered.length === 0) {
    grid.innerHTML = `<div class="empty-state"><p>No developments match your filter.</p></div>`;
    countEl.textContent = '0 results';
    return;
  }

  countEl.textContent = `${filtered.length} development${filtered.length !== 1 ? 's' : ''}`;
  filtered.forEach(article => grid.appendChild(buildCard(article)));
}

const CAT_ORDER = ['Banking', 'Trading', 'RegTech', 'Payments', 'InsurTech'];

function renderTrending(trending) {
  const list = document.getElementById('trending-list');
  if (!trending || trending.length === 0) {
    list.innerHTML = '<span class="dash-empty">Not enough data yet</span>';
    return;
  }
  const max = trending[0].count;
  list.innerHTML = trending.map(({ topic, count }) => `
    <button class="trend-row" data-query="${topic.toLowerCase()}">
      <span class="trend-label">${topic}</span>
      <span class="trend-bar-wrap">
        <span class="trend-bar" style="width:${Math.round((count / max) * 100)}%"></span>
      </span>
      <span class="trend-count">${count}</span>
    </button>
  `).join('');

  list.querySelectorAll('.trend-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.query;
      const input = document.getElementById('search');
      input.value = q;
      searchQuery = q;
      renderArticles();
      document.getElementById('articles-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function renderCategoryBreakdown() {
  const breakdown = document.getElementById('cat-breakdown');
  const totalEl = document.getElementById('cat-total');
  const counts = {};
  CAT_ORDER.forEach(c => { counts[c] = 0; });
  allArticles.forEach(a => { counts[a.category] = (counts[a.category] || 0) + 1; });

  const total = allArticles.length;
  totalEl.textContent = `${total} article${total !== 1 ? 's' : ''}`;

  const max = Math.max(...Object.values(counts), 1);
  breakdown.innerHTML = CAT_ORDER.map(cat => {
    const n = counts[cat] || 0;
    const pct = Math.round((n / max) * 100);
    return `
      <button class="cat-row cat-row-${cat}" data-cat="${cat}">
        <span class="cat-row-label">${cat}</span>
        <span class="cat-row-bar-wrap">
          <span class="cat-row-bar" style="width:${pct}%"></span>
        </span>
        <span class="cat-row-count">${n}</span>
      </button>
    `;
  }).join('');

  breakdown.querySelectorAll('.cat-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const cat = btn.dataset.cat;
      document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
      document.querySelector(`.cat-btn[data-cat="${cat}"]`)?.classList.add('active');
      activeCategory = cat;
      renderArticles();
      document.getElementById('articles-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

async function fetchData(silent = false) {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now());
    const data = await res.json();

    if (silent && data.last_updated === currentLastUpdated) return; // nothing new

    currentLastUpdated = data.last_updated;
    allArticles = data.articles || [];
    document.getElementById('last-updated').textContent = formatUpdated(data.last_updated);
    renderTrending(data.trending || []);
    renderCategoryBreakdown();
    renderArticles();
  } catch (err) {
    if (!silent) {
      document.getElementById('articles-grid').innerHTML =
        `<div class="empty-state"><p>Could not load articles. Please refresh.</p></div>`;
      console.error('Failed to load articles:', err);
    }
  }
}

function loadData() { return fetchData(false); }

setInterval(() => fetchData(true), POLL_INTERVAL);

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') fetchData(true);
});

document.getElementById('categories').addEventListener('click', e => {
  const btn = e.target.closest('.cat-btn');
  if (!btn) return;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  activeCategory = btn.dataset.cat;
  renderArticles();
});

let debounceTimer;
document.getElementById('search').addEventListener('input', e => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    searchQuery = e.target.value.trim();
    renderArticles();
  }, 200);
});

function syncHeaderHeight() {
  const h = document.querySelector('header').offsetHeight;
  document.documentElement.style.setProperty('--header-h', h + 'px');
}
syncHeaderHeight();
window.addEventListener('resize', syncHeaderHeight);

loadData();
