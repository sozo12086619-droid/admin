/* ==========================================================================
   dashboard.js — グラフ描画・手動追加フォーム・削除
   サーバーから渡されたデータは <script id="page-data"> の JSON から読む
   ========================================================================== */
(function () {
  'use strict';

  var dataEl = document.getElementById('page-data');
  var D = dataEl ? JSON.parse(dataEl.textContent) : {};

  var css = getComputedStyle(document.documentElement);
  function cssVar(name, fallback) {
    return (css.getPropertyValue(name) || '').trim() || fallback;
  }
  function yen(n) { return '¥' + Math.round(n).toLocaleString('ja-JP'); }
  function withAlpha(hex, a) {
    var m = /^#([0-9a-f]{6})$/i.exec(hex);
    if (!m) return hex;
    var n = parseInt(m[1], 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  /* ---------- トースト ---------- */
  var toastEl = document.getElementById('toast');
  var toastTimer;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-show'); }, 2200);
  }

  /* ---------- グラフ ---------- */
  function initCharts() {
    if (!window.Chart) return;   // CDN に繋がらない場合は、グラフ以外だけ表示する

    var muted = cssVar('--muted', '#6c7196');
    var line = cssVar('--line', '#e7e9f4');
    var income = cssVar('--income', '#059669');
    var expense = cssVar('--expense', '#e11d48');

    Chart.defaults.color = muted;
    Chart.defaults.borderColor = line;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    // ---- 月別の推移（棒グラフ）----
    var trendCanvas = document.getElementById('trendChart');
    if (trendCanvas && D.trend) {
      var labels = D.trend.labels.map(function (ym) {
        var p = ym.split('-');
        return p[0].slice(2) + '/' + parseInt(p[1], 10);
      });
      // 表示中の月だけ濃く、ほかは少し薄くする
      function tone(color) {
        return D.trend.labels.map(function (ym) {
          return ym === D.month ? color : withAlpha(color, 0.45);
        });
      }
      new Chart(trendCanvas, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: '収入', data: D.trend.incomes, backgroundColor: tone(income), borderRadius: 6, maxBarThickness: 20 },
            { label: '支出', data: D.trend.expenses, backgroundColor: tone(expense), borderRadius: 6, maxBarThickness: 20 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: function (c) { return ' ' + c.dataset.label + '  ' + yen(c.parsed.y); } } }
          },
          scales: {
            x: { grid: { display: false } },
            y: {
              beginAtZero: true,
              grid: { color: line },
              border: { display: false },
              ticks: { callback: function (v) { return v >= 10000 ? (v / 10000) + '万' : v; } }
            }
          }
        }
      });
      // 最新の月が見えるように、右端までスクロールしておく
      var scroller = document.getElementById('trendScroll');
      if (scroller) scroller.scrollLeft = scroller.scrollWidth;
    }

    // ---- 支出の内訳（ドーナツ）----
    var catCanvas = document.getElementById('categoryChart');
    if (catCanvas && D.categories && D.categories.values.length) {
      new Chart(catCanvas, {
        type: 'doughnut',
        data: {
          labels: D.categories.labels,
          datasets: [{ data: D.categories.values, backgroundColor: D.categories.colors, borderWidth: 0, spacing: 2, borderRadius: 4 }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: function (c) { return ' ' + c.label + '  ' + yen(c.parsed); } } }
          }
        }
      });
    }
  }
  initCharts();

  /* ---------- 追加フォーム（ボトムシート） ---------- */
  var sheet = document.getElementById('sheet');
  var form = document.getElementById('addForm');
  var openBtn = document.getElementById('openSheet');
  var errEl = document.getElementById('formError');
  var submitBtn = document.getElementById('submitBtn');
  var catSelect = document.getElementById('categorySelect');
  var amountInput = form.elements['amount'];

  function fillCategories() {
    var type = form.elements['record_type'].value;
    var list = (D.form && D.form[type]) || [];
    catSelect.innerHTML = '';
    list.forEach(function (name) {
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      catSelect.appendChild(opt);
    });
  }
  function openSheet() {
    fillCategories();
    errEl.hidden = true;
    sheet.classList.add('is-open');
    sheet.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-locked');
    setTimeout(function () { amountInput.focus(); }, 280);
  }
  function closeSheet() {
    sheet.classList.remove('is-open');
    sheet.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('is-locked');
    openBtn.focus();
  }

  openBtn.addEventListener('click', openSheet);
  sheet.addEventListener('click', function (e) {
    if (e.target.closest('[data-close]')) closeSheet();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sheet.classList.contains('is-open')) closeSheet();
  });
  form.addEventListener('change', function (e) {
    if (e.target.name === 'record_type') fillCategories();
  });

  // 金額は入力しながら 12,345 の形に整える
  amountInput.addEventListener('input', function () {
    var digits = amountInput.value.replace(/[^\d]/g, '').slice(0, 9);
    amountInput.value = digits ? Number(digits).toLocaleString('ja-JP') : '';
  });

  function showError(msg) {
    errEl.textContent = msg;
    errEl.hidden = false;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var amount = Number(amountInput.value.replace(/[^\d]/g, ''));
    if (!amount) { showError('金額を入力してください'); amountInput.focus(); return; }
    if (!form.elements['record_date'].value) { showError('日付を選んでください'); return; }

    var body = {
      record_type: form.elements['record_type'].value,
      record_date: form.elements['record_date'].value,
      category: catSelect.value,
      title: form.elements['title'].value,
      detail: form.elements['detail'].value,
      amount: amount
    };

    errEl.hidden = true;
    submitBtn.disabled = true;
    submitBtn.textContent = '保存中…';

    fetch('/api/records', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (res) {
        if (!res.ok) throw new Error('save failed: ' + res.status);
        return res.json();
      })
      .then(function () {
        toast('保存しました');
        setTimeout(function () { location.reload(); }, 350);
      })
      .catch(function () {
        showError('保存できませんでした。もう一度お試しください');
        submitBtn.disabled = false;
        submitBtn.textContent = '保存する';
      });
  });

  /* ---------- 削除 ---------- */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-delete]');
    if (!btn) return;
    var id = btn.getAttribute('data-delete');
    var row = document.getElementById('rec-' + id);
    var title = row ? row.querySelector('.rec__title').textContent : 'この記録';
    if (!window.confirm('「' + title + '」を削除しますか？')) return;

    btn.disabled = true;
    fetch('/api/records/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok) throw new Error('delete failed: ' + res.status);
        if (row) row.classList.add('is-removing');
        toast('削除しました');
        // 合計やグラフも変わるので、アニメーションのあとで再読み込みする
        setTimeout(function () { location.reload(); }, 400);
      })
      .catch(function () {
        btn.disabled = false;
        toast('削除できませんでした');
      });
  });
})();
