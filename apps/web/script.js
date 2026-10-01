const demoCreators = [
  {name:'Maja Nowak',handle:'@majanowak',category:'Lifestyle',followers:1800000,views:2600000,engagement:11.8,growth:12.4,score:94.7},
  {name:'Kuba Wolski',handle:'@kubawolski',category:'Entertainment',followers:3900000,views:3100000,engagement:9.6,growth:8.1,score:93.2},
  {name:'Ola Wrona',handle:'@olawrona',category:'Beauty',followers:742000,views:1500000,engagement:14.7,growth:18.6,score:92.4},
  {name:'Mati Tech',handle:'@matitech',category:'Tech',followers:614000,views:1100000,engagement:13.9,growth:21.2,score:91.8},
  {name:'Nina Fit',handle:'@ninafit',category:'Sport & Fitness',followers:1200000,views:1400000,engagement:10.8,growth:6.4,score:90.9},
  {name:'Bartek Zieliński',handle:'@bartekz',category:'Gaming',followers:2700000,views:1900000,engagement:8.5,growth:3.1,score:89.8},
  {name:'Zuzia Food',handle:'@zuziafood',category:'Food',followers:486000,views:893000,engagement:15.1,growth:24.5,score:89.3},
  {name:'Lena Style',handle:'@lenastyle',category:'Fashion',followers:856000,views:980000,engagement:10.2,growth:5.3,score:88.4},
  {name:'Klara Daily',handle:'@klaradaily',category:'Lifestyle',followers:1400000,views:1200000,engagement:8.9,growth:-1.2,score:86.9},
  {name:'Filip Finanse',handle:'@filipfinanse',category:'Finance',followers:302000,views:612000,engagement:12.7,growth:16.8,score:86.2},
  {name:'Ania Games',handle:'@aniagames',category:'Gaming',followers:918000,views:744000,engagement:8.1,growth:2.4,score:83.7},
  {name:'Piotr Wiedza',handle:'@piotrwiedza',category:'Education',followers:533000,views:508000,engagement:9.4,growth:-0.8,score:81.5},
  {name:'Kasia Travel',handle:'@kasiatravel',category:'Travel',followers:428000,views:691000,engagement:10.9,growth:13.6,score:84.9},
  {name:'Miko Music',handle:'@mikomusic',category:'Music',followers:2100000,views:1700000,engagement:7.8,growth:4.8,score:87.8}
];

let creators = [...demoCreators];


const categoryList = [
  'Wszystkie',
  'Entertainment',
  'Lifestyle',
  'Beauty',
  'Fashion',
  'Gaming',
  'Food',
  'Sport & Fitness',
  'Tech',
  'Education',
  'Travel',
  'Music',
  'Finance',
  'Other'
];

const rankingBody = document.getElementById('rankingBody');
const emptyState = document.getElementById('emptyState');
const searchInput = document.getElementById('searchInput');
const categoryFilters = document.getElementById('categoryFilters');
const rankingSection = document.getElementById('ranking');
const instagramSection = document.getElementById('instagramSection');
const methodology = document.getElementById('methodology');
const sortSelect = document.getElementById('sortSelect');
const sortDirectionBtn = document.getElementById('sortDirection');

let activeCategory = 'Wszystkie';
let sortKey = 'score';
let sortDirection = 'desc';

categoryFilters.innerHTML = categoryList.map(c => `<button class="category-btn ${c === 'Wszystkie' ? 'active' : ''}" data-category="${c}">${c}</button>`).join('');

function initials(name){
  return name.split(' ').map(p => p[0]).join('').slice(0,2).toUpperCase();
}

function compactNumber(value){
  if (value >= 1000000) return `${(value / 1000000).toFixed(value >= 10000000 ? 0 : 1).replace('.0','')}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 100000 ? 0 : 1).replace('.0','')}K`;
  return String(value);
}

function compareCreators(a, b){
  let av = a[sortKey];
  let bv = b[sortKey];
  if (sortKey === 'name' || sortKey === 'category') {
    av = String(av).toLocaleLowerCase('pl');
    bv = String(bv).toLocaleLowerCase('pl');
    return sortDirection === 'asc' ? av.localeCompare(bv, 'pl') : bv.localeCompare(av, 'pl');
  }
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  return sortDirection === 'asc' ? av - bv : bv - av;
}

function syncSortUI(){
  sortSelect.value = sortKey;
  sortDirectionBtn.textContent = sortDirection === 'desc' ? '↓ Malejąco' : '↑ Rosnąco';
  sortDirectionBtn.setAttribute('aria-label', sortDirection === 'desc' ? 'Sortowanie malejąco. Kliknij, aby zmienić na rosnąco.' : 'Sortowanie rosnąco. Kliknij, aby zmienić na malejąco.');

  document.querySelectorAll('th[data-sort]').forEach(th => {
    const active = th.dataset.sort === sortKey;
    th.classList.toggle('sort-active', active);
    const arrow = active ? (sortDirection === 'desc' ? ' ↓' : ' ↑') : '';
    const label = th.dataset.label || th.textContent.replace(/[↑↓]/g,'').trim();
    th.dataset.label = label;
    th.querySelector('.th-label').textContent = `${label}${arrow}`;
    th.setAttribute('aria-sort', active ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none');
  });
}

function render(){
  const q = searchInput.value.trim().toLowerCase();
  const filtered = creators
    .filter(c => {
      const matchesSearch = !q || `${c.name} ${c.handle} ${c.category}`.toLowerCase().includes(q);
      const matchesCategory = activeCategory === 'Wszystkie' || c.category === activeCategory;
      return matchesSearch && matchesCategory;
    })
    .sort(compareCreators);

  rankingBody.innerHTML = filtered.map((c, index) => `
    <tr>
      <td class="rank ${index <= 2 ? 'top' : ''}">#${index + 1}</td>
      <td>
        <div class="creator">
          <span class="avatar">${initials(c.name)}</span>
          <span><span class="creator-name">${c.name}${c.verified ? ` <span class="verified-badge" title="Zweryfikowane konto">✓</span>` : ``}</span><span class="creator-handle">${c.handle}</span></span>
        </div>
      </td>
      <td><span class="category-tag">${c.category}</span></td>
      <td class="num">${compactNumber(c.followers)}</td>
      <td class="num">${compactNumber(c.views)}</td>
      <td class="num">${c.engagement.toFixed(1)}%</td>
      <td class="num ${c.growth == null ? '' : (c.growth >= 0 ? 'growth-up' : 'growth-down')}">${c.growth == null ? '—' : `${c.growth >= 0 ? '+' : ''}${c.growth.toFixed(1)}%`}</td>
      <td class="num score-cell" title="${c.scoreStatus === 'provisional_no_30d_history' ? 'Score tymczasowy: brak pełnej historii 30D' : 'Influence Score'}">${c.score.toFixed(1)}${c.scoreStatus === 'provisional_no_30d_history' ? '<sup>*</sup>' : ''}<span class="score-bar"><i style="width:${c.score}%"></i></span></td>
    </tr>
  `).join('');

  emptyState.hidden = filtered.length !== 0;
  syncSortUI();
}

categoryFilters.addEventListener('click', e => {
  const btn = e.target.closest('[data-category]');
  if (!btn) return;
  activeCategory = btn.dataset.category;
  [...categoryFilters.querySelectorAll('.category-btn')].forEach(b => b.classList.toggle('active', b === btn));
  render();
});

searchInput.addEventListener('input', render);

sortSelect.addEventListener('change', () => {
  sortKey = sortSelect.value;
  render();
});

sortDirectionBtn.addEventListener('click', () => {
  sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
  render();
});

document.querySelector('thead').addEventListener('click', e => {
  const th = e.target.closest('th[data-sort]');
  if (!th) return;
  const requestedKey = th.dataset.sort;
  if (sortKey === requestedKey) {
    sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
  } else {
    sortKey = requestedKey;
    sortDirection = requestedKey === 'name' || requestedKey === 'category' ? 'asc' : 'desc';
  }
  render();
});

function showPlatform(platform){
  document.querySelectorAll('.nav-tab').forEach(btn => btn.classList.toggle('active', btn.dataset.platform === platform));
  const tikTokVisible = platform === 'tiktok';
  rankingSection.hidden = !tikTokVisible;
  methodology.hidden = !tikTokVisible;
  instagramSection.hidden = tikTokVisible;
  if (!tikTokVisible) instagramSection.scrollIntoView({behavior:'smooth', block:'start'});
}

document.querySelectorAll('.nav-tab').forEach(btn => btn.addEventListener('click', () => showPlatform(btn.dataset.platform)));
document.getElementById('backToTiktok').addEventListener('click', () => {
  showPlatform('tiktok');
  rankingSection.scrollIntoView({behavior:'smooth'});
});

const modal = document.getElementById('methodModal');
const methodBtn = document.getElementById('methodBtn');
const modalClose = document.getElementById('modalClose');

function openModal(){
  modal.hidden = false;
  modal.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  modalClose.focus();
}

function closeModal(){
  modal.hidden = true;
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  methodBtn.focus();
}

methodBtn.addEventListener('click', openModal);
modalClose.addEventListener('click', closeModal);
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });

modal.hidden = true;
modal.setAttribute('aria-hidden', 'true');

async function loadRealData(){
  try {
    const response = await fetch(`data/creators.json?v=${Date.now()}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (Array.isArray(payload.creators) && payload.creators.length) {
      creators = payload.creators.map(c => ({
        name: c.name || c.handle || '—',
        handle: c.handle ? `@${String(c.handle).replace(/^@/,'')}` : '',
        category: c.category || '—',
        followers: Number(c.followers || 0),
        views: Number(c.views || 0),
        engagement: Number(c.engagement || 0),
        growth: c.growth == null ? null : Number(c.growth),
        score: Number(c.score || 0),
        scoreStatus: c.score_status || '',
        verified: Boolean(c.verified)
      }));
      const updated = document.getElementById('updatedAt');
      if (updated) updated.textContent = payload.generated_at ? new Date(payload.generated_at).toLocaleString('pl-PL') : 'real data';
      const disclaimer = document.getElementById('dataDisclaimer');
      if (disclaimer) disclaimer.innerHTML = '<strong>Dane skanera.</strong> Ranking korzysta z ostatniego snapshotu publicznych danych TikToka. Metodologia i klasyfikacja są nadal w wersji MVP.';
    }
  } catch (err) { console.info('Real dataset unavailable; using demo fallback.', err); }
  render();
}
loadRealData();
