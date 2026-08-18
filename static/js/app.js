/* API Automation Studio — frontend interactions (vanilla JS) */
(function () {
  'use strict';

  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Scroll reveal ─────────────────────────────────── */
  function initReveal() {
    var els = document.querySelectorAll('.reveal');
    if (!els.length || REDUCED || !('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    els.forEach(function (el) { io.observe(el); });
  }

  /* ── Copy button ───────────────────────────────────── */
  function initCopyButtons() {
    document.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = document.querySelector(btn.getAttribute('data-copy'));
        if (!target) return;
        var text = target.textContent.trim();
        var done = function () {
          var old = btn.textContent;
          btn.textContent = 'copied';
          btn.classList.add('copied');
          setTimeout(function () {
            btn.textContent = old;
            btn.classList.remove('copied');
          }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
        } else {
          fallbackCopy(text, done);
        }
      });
    });
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* noop */ }
    document.body.removeChild(ta);
  }

  /* ── Live JSON validation ──────────────────────────── */
  function initJsonValidation() {
    document.querySelectorAll('textarea.json-validate').forEach(function (ta) {
      var hint = document.createElement('p');
      hint.className = 'json-hint';
      ta.parentNode.insertBefore(hint, ta.nextSibling);

      var check = function () {
        var value = ta.value.trim();
        if (!value) {
          ta.classList.remove('json-valid', 'json-invalid');
          hint.textContent = '';
          return;
        }
        try {
          var parsed = JSON.parse(value);
          var ok = parsed && typeof parsed === 'object' && !Array.isArray(parsed);
          if (!ok) throw new Error('expected an object');
          ta.classList.remove('json-invalid');
          ta.classList.add('json-valid');
          hint.textContent = '✓ valid JSON object';
          hint.className = 'json-hint valid';
        } catch (e) {
          ta.classList.remove('json-valid');
          ta.classList.add('json-invalid');
          hint.textContent = '✕ invalid JSON — ' + e.message;
          hint.className = 'json-hint invalid';
        }
      };
      ta.addEventListener('input', check);
    });
  }

  /* ── Hero live demo ────────────────────────────────── */
  function initHeroDemo() {
    var termBody = document.getElementById('demo-term-body');
    var nodes = Array.prototype.slice.call(document.querySelectorAll('.demo-node'));
    if (!termBody || !nodes.length) return;

    var tick = REDUCED ? 0 : 26;
    var queue = [];

    var steps = [
      { cmd: true, line: 'curl -X POST https://studio.app/webhooks/k7Xq9fA2/', indent: false },
      { cmd: true, line: '  -d \'{"order_id":1537,"customer":"Alex","amount":5000}\'', indent: false },
      { node: 0, line: '<span class="term-ok">✓</span> webhook      <span class="term-dim">200 OK · 0.04s</span>' },
      { node: 1, line: '<span class="term-ok">✓</span> condition    <span class="term-dim">amount 5000 &gt; 3000 → true · 0.01s</span>' },
      { node: 2, line: '<span class="term-ok">✓</span> http         <span class="term-dim">POST api.example.com/orders → 201 · 0.31s</span>' },
      { node: 3, line: '<span class="term-ok">✓</span> telegram     <span class="term-dim">message delivered · 0.12s</span>' },
      { done: true, line: 'execution <span class="term-key">#1523</span> → <span class="term-ok">SUCCESS</span> <span class="term-dim">(0.82s)</span>' },
    ];

    function clearAll() {
      termBody.innerHTML = '';
      nodes.forEach(function (n) {
        n.classList.remove('demo-live');
        n.querySelector('.demo-status').textContent = '';
      });
    }

    function resetNodeStatus(n) {
      n.querySelector('.demo-status').textContent = '…';
    }

    function showStep(i) {
      var step = steps[i];
      var line = document.createElement('div');
      line.className = 'term-line';

      if (step.cmd) {
        var span = document.createElement('span');
        span.className = 'term-cmd';
        span.innerHTML = '<span class="prompt">$ </span>' + step.line;
        line.appendChild(span);
      } else {
        line.innerHTML = step.line;
      }
      termBody.appendChild(line);
      termBody.scrollTop = termBody.scrollHeight;

      if (step.node !== undefined) {
        nodes.forEach(function (n) {
          n.classList.remove('demo-live');
          resetNodeStatus(n);
        });
        var active = nodes[step.node];
        active.classList.add('demo-live');
        active.querySelector('.demo-status').textContent = step.done ? '✓' : '→';
      }
      if (step.done) {
        nodes.forEach(function (n) {
          n.classList.remove('demo-live');
          n.querySelector('.demo-status').textContent = '✓';
        });
      }
    }

    function schedule() {
      clearAll();
      var t = 350;
      steps.forEach(function (step, i) {
        queue.push(setTimeout(function () { showStep(i); }, t));
        t += step.cmd ? 420 : (REDUCED ? 60 : 520);
      });
      queue.push(setTimeout(function () {
        var done = document.createElement('div');
        done.className = 'term-line';
        done.innerHTML = '<span class="term-caret"></span>';
        termBody.appendChild(done);
        termBody.scrollTop = termBody.scrollHeight;
        queue.push(setTimeout(schedule, 2600));
      }, t + 500));
    }

    function cancelAll() {
      queue.forEach(clearTimeout);
      queue = [];
    }

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) cancelAll(); else schedule();
    });
    schedule();
  }

  document.addEventListener('DOMContentLoaded', function () {
    initReveal();
    initCopyButtons();
    initJsonValidation();
    initHeroDemo();
  });
})();