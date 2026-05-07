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

async function loadData() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now());
    const data = await res.json();
    allArticles = data.articles || [];
    document.getElementById('last-updated').textContent = formatUpdated(data.last_updated);
    renderArticles();
  } catch (err) {
    document.getElementById('articles-grid').innerHTML =
      `<div class="empty-state"><p>Could not load articles. Please refresh.</p></div>`;
    console.error('Failed to load articles:', err);
  }
}

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
