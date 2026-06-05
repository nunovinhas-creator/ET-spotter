/* ET-Spotter i18n — i18next UMD + JSON fetch + auto-detect */
/* zero backend, zero ES6 imports, GitHub Pages compatible    */

(function () {
  'use strict';

  /* ── helpers ─────────────────────────────────────────────── */

  function baseUrl() {
    var scripts = document.getElementsByTagName('script');
    for (var i = 0; i < scripts.length; i++) {
      var src = scripts[i].src || '';
      if (src.indexOf('i18n.js') !== -1) {
        return src.replace(/i18n\.js.*$/, '');
      }
    }
    return './';
  }

  function langDetect() {
    /* 1 — URL param ?lang=xx */
    try {
      var p = new URLSearchParams(window.location.search);
      if (p.has('lang')) return p.get('lang').substring(0, 2).toLowerCase();
    } catch (e) {}
    /* 2 — localStorage */
    try {
      var s = localStorage.getItem('et_lang');
      if (s) return s;
    } catch (e) {}
    /* 3 — browser language */
    var bl = (navigator.language || navigator.userLanguage || 'pt')
               .substring(0, 2).toLowerCase();
    return bl === 'en' ? 'en' : 'pt';
  }

  /* ── DOM updater ──────────────────────────────────────────── */

  function applyTranslations(i18n) {
    /* text content */
    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute('data-i18n');
      var val = i18n.t(key);
      if (val && val !== key) els[i].textContent = val;
    }
    /* placeholder attributes */
    var pls = document.querySelectorAll('[data-i18n-ph]');
    for (var j = 0; j < pls.length; j++) {
      var pk = pls[j].getAttribute('data-i18n-ph');
      var pv = i18n.t(pk);
      if (pv && pv !== pk) pls[j].placeholder = pv;
    }
    /* title attributes */
    var tls = document.querySelectorAll('[data-i18n-title]');
    for (var k = 0; k < tls.length; k++) {
      var tk = tls[k].getAttribute('data-i18n-title');
      var tv = i18n.t(tk, {
        spy:   tls[k].dataset.spy   || '',
        sma:   tls[k].dataset.sma   || '',
        arrow: tls[k].dataset.arrow || '>'
      });
      if (tv && tv !== tk) tls[k].title = tv;
    }
    /* html lang attribute */
    document.documentElement.lang = i18n.language === 'en' ? 'en' : 'pt';
    /* PT | EN split toggle — highlight active language */
    var ptBtn = document.getElementById('lang-pt');
    var enBtn = document.getElementById('lang-en');
    if (ptBtn) {
      ptBtn.style.color      = i18n.language === 'pt' ? '#00D4FF' : '#4A6080';
      ptBtn.style.fontWeight = i18n.language === 'pt' ? '700' : '400';
    }
    if (enBtn) {
      enBtn.style.color      = i18n.language === 'en' ? '#00D4FF' : '#4A6080';
      enBtn.style.fontWeight = i18n.language === 'en' ? '700' : '400';
    }
    /* JS-rendered table: inject translated strings for badge rendering */
    window._ET_SIGNAL_LABELS = {
      'STRONG_BUY': i18n.t('signal.strong_buy'),
      'BUY':        i18n.t('signal.buy'),
      'POTENTIAL':  i18n.t('signal.potential')
    };
    /* re-render ETF table if already on screen */
    if (typeof applyFilters === 'function') {
      try { applyFilters(); } catch (e) {}
    }
  }

  /* ── init ─────────────────────────────────────────────────── */

  function boot(resources) {
    var lng = langDetect();
    i18next.init({
      lng:          lng,
      fallbackLng:  'en',
      resources:    resources,
      interpolation: { escapeValue: false }
    }, function (err) {
      if (!err) {
        applyTranslations(i18next);
        /* re-apply on every language change (covers programmatic changes too) */
        i18next.on('languageChanged', function () {
          applyTranslations(i18next);
        });
        /* public API */
        window.setLanguage = function (lang) {
          try { localStorage.setItem('et_lang', lang); } catch (e) {}
          i18next.changeLanguage(lang);
        };
        window.toggleLang = function () {
          var cur = i18next.language || 'pt';
          window.setLanguage(cur === 'pt' ? 'en' : 'pt');
        };
      }
    });
  }

  /* ── fetch JSON files ─────────────────────────────────────── */

  var BASE = baseUrl();
  var resources = { pt: { translation: {} }, en: { translation: {} } };
  var pending = 2;

  function done() {
    pending--;
    if (pending === 0) boot(resources);
  }

  function loadJSON(lang) {
    var url = BASE + 'i18n/' + lang + '.json?_=' + Date.now();
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {
        try {
          resources[lang].translation = JSON.parse(xhr.responseText);
        } catch (e) { /* keep empty fallback */ }
      }
      done();
    };
    xhr.onerror = function () { done(); };
    xhr.send();
  }

  /* wait for i18next to be available (loaded from CDN) */
  function waitForI18next(tries) {
    if (typeof i18next !== 'undefined') {
      loadJSON('pt');
      loadJSON('en');
    } else if (tries > 0) {
      setTimeout(function () { waitForI18next(tries - 1); }, 50);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { waitForI18next(20); });
  } else {
    waitForI18next(20);
  }

})();
