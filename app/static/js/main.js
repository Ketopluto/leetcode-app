const AUTO_REFRESH_MS = 120000;

const els = {
  tableBody: () => document.getElementById('tableBody'),
  rankList: () => document.getElementById('rankList'),
  rowCount: () => document.getElementById('rowCount'),
  footNote: () => document.getElementById('tableFootNote'),
  stamp: () => document.getElementById('refreshStamp'),
  search: () => document.getElementById('tableSearch'),
  year: () => document.getElementById('year'),
};

let allRows = [];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function yearOf(row) {
  return row.year_display || row.year || '';
}

function buildTable(rows) {
  const body = els.tableBody();
  body.replaceChildren();

  if (!rows.length) {
    const tr = el('tr');
    const td = el('td');
    td.colSpan = 8;
    td.style.padding = '0';
    const empty = el('div', 'empty');
    empty.append(el('div', 'empty-title', 'No students match'));
    empty.append(el('div', 'empty-text', 'Try a different search term or year filter.'));
    td.append(empty);
    tr.append(td);
    body.append(tr);
    return;
  }

  const frag = document.createDocumentFragment();

  rows.forEach(row => {
    const isHigherStudies = row.username === 'higher studies';
    const tr = el('tr');
    if (row.fetch_error && !isHigherStudies) tr.classList.add('is-error');

    tr.append(el('td', 'cell-mono', row.roll_no));

    const nameCell = el('td');
    const link = el('a', 'name-link', row.actual_name);
    link.href = '/student/' + encodeURIComponent(row.roll_no);
    nameCell.append(link);
    tr.append(nameCell);

    const userCell = el('td');
    if (row.fetch_error && !isHigherStudies) {
      const wrap = el('span', 'username-cell');
      wrap.title = 'Could not fetch: ' + row.fetch_error;
      wrap.insertAdjacentHTML('afterbegin',
        '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 21 20H3Z"/>' +
        '<line x1="12" y1="10" x2="12" y2="14.5"/><line x1="12" y1="16.7" x2="12" y2="17"/></svg>');
      wrap.append(el('span', 'cell-mono', row.username));
      userCell.append(wrap);
    } else {
      userCell.append(el('span', 'cell-mono', row.username));
    }
    tr.append(userCell);

    const yearCell = el('td');
    yearCell.append(el('span', 'badge badge-neutral', yearOf(row)));
    tr.append(yearCell);

    tr.append(el('td', 'num c-easy', row.easy));
    tr.append(el('td', 'num c-medium', row.medium));
    tr.append(el('td', 'num c-hard', row.hard));
    tr.append(el('td', 'num strong', row.total));

    frag.append(tr);
  });

  body.append(frag);
}

function buildLeaderboard(rows) {
  const list = els.rankList();
  list.replaceChildren();

  const top = [...rows].sort((a, b) => b.total - a.total).slice(0, 5);
  if (!top.length) {
    const li = el('li', 'rank-item');
    li.append(el('span', 'text-sm subtle', 'No data yet'));
    list.append(li);
    return;
  }

  top.forEach((row, i) => {
    const li = el('li', 'rank-item');
    li.append(el('span', 'rank-num', i + 1));

    const body = el('div', 'rank-body');
    const name = el('a', 'rank-name', row.actual_name);
    name.href = '/student/' + encodeURIComponent(row.roll_no);
    body.append(name);
    body.append(el('div', 'rank-meta', row.username + ' · ' + yearOf(row)));
    li.append(body);

    const score = el('div', 'rank-score', row.total);
    score.append(el('span', null, 'solved'));
    li.append(score);

    list.append(li);
  });
}

function animateTo(id, target) {
  const node = document.getElementById(id);
  if (!node) return;
  const duration = 520;
  const start = performance.now();

  function tick(now) {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    node.textContent = Math.round(target * eased).toLocaleString();
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function updateMetrics(rows) {
  const total = rows.reduce((sum, r) => sum + r.total, 0);
  const avg = rows.length ? Math.round(total / rows.length) : 0;
  const top = rows.reduce((best, r) => (r.total > (best?.total ?? -1) ? r : best), null);
  const errors = rows.filter(r => r.fetch_error && r.username !== 'higher studies').length;

  animateTo('mStudents', rows.length);
  animateTo('mSolved', total);
  animateTo('mAvg', avg);
  animateTo('mTop', top ? top.total : 0);

  const topMeta = document.getElementById('mTopMeta');
  if (topMeta) topMeta.textContent = top ? top.actual_name : ' ';

  const studentsMeta = document.getElementById('mStudentsMeta');
  if (studentsMeta) {
    studentsMeta.textContent = errors ? errors + ' profile' + (errors === 1 ? '' : 's') + ' unreachable' : 'all profiles resolved';
  }
}

function applySearch() {
  const term = (els.search()?.value || '').trim().toLowerCase();
  const rows = term
    ? allRows.filter(r => [r.actual_name, r.roll_no, r.username, yearOf(r)]
      .some(v => String(v || '').toLowerCase().includes(term)))
    : allRows;

  buildTable(rows);
  const count = els.rowCount();
  if (count) {
    count.textContent = term
      ? rows.length + ' of ' + allRows.length + ' shown'
      : allRows.length + (allRows.length === 1 ? ' student' : ' students');
  }
}

function stamp() {
  const node = els.stamp();
  if (node) {
    node.textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
}

function loadData(year = '') {
  const url = '/api/stats' + (year ? '?year=' + encodeURIComponent(year) : '');

  return fetch(url)
    .then(r => r.json())
    .then(data => {
      allRows = data.results || [];
      applySearch();
      buildLeaderboard(allRows);
      updateMetrics(allRows);
      stamp();

      const link = document.getElementById('downloadLink');
      if (link) link.href = '/download' + (year ? '?year=' + encodeURIComponent(year) : '');

      const foot = els.footNote();
      const stale = allRows.filter(r => r.is_stale).length;
      if (foot) {
        foot.textContent = stale
          ? stale + ' record' + (stale === 1 ? '' : 's') + ' served from cache'
          : 'All records current';
      }
    })
    .catch(() => {
      const foot = els.footNote();
      if (foot) foot.textContent = 'Could not reach the server — showing last loaded data.';
    });
}

document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('filterForm');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      loadData(els.year()?.value || '');
    });
  }

  // Changing the year applies immediately - the submit handler stays for
  // Enter-in-the-search-box and for browsers without JS-driven change events.
  const year = els.year();
  if (year) year.addEventListener('change', () => loadData(year.value || ''));

  const search = els.search();
  if (search) search.addEventListener('input', applySearch);

  loadData();
  setInterval(() => loadData(els.year()?.value || ''), AUTO_REFRESH_MS);
});
