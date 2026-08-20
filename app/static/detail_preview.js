(() => {
  const form = document.getElementById('detailForm');
  if (!form || !window.location.pathname.endsWith('/detail')) return;

  const format = value => {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return '0';
    return number.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
  };

  let timer = null;
  let requestSerial = 0;

  const updateCurrentDev = input => {
    const row = input.closest('[data-detail-line]');
    if (!row) return;
    const base = Number(row.dataset.baseHours || 0);
    const mod = Number(input.value || 0);
    const dev = row.querySelector('.dev-subtotal');
    if (dev && Number.isFinite(base) && Number.isFinite(mod)) dev.textContent = format(base + mod);
  };

  const applyPreview = payload => {
    const rowMap = new Map();
    document.querySelectorAll('[data-detail-line]').forEach(row => rowMap.set(row.dataset.lineKey, row));

    (payload.rows || []).forEach(item => {
      const row = rowMap.get(item.key);
      if (!row) return;
      const dev = row.querySelector('.dev-subtotal');
      const unit = row.querySelector('.unit-testing');
      const total = row.querySelector('.line-total');
      const validation = row.querySelector('.line-validation');
      if (dev) dev.textContent = format(item.dev);
      if (unit) unit.textContent = format(item.unit);
      if (total) total.textContent = format(item.total);
      if (validation) validation.textContent = item.error || '';
      row.classList.toggle('zero-row', Number(item.total || 0) === 0);
    });

    Object.entries(payload.sections || {}).forEach(([section, values]) => {
      const row = [...document.querySelectorAll('[data-detail-section]')].find(node => node.dataset.detailSection === section);
      if (!row) return;
      const assignments = {
        '.section-base': values.base,
        '.section-mod': values.mod,
        '.section-dev': values.dev,
        '.section-unit': values.unit,
        '.section-total': values.total
      };
      Object.entries(assignments).forEach(([selector, value]) => {
        const cell = row.querySelector(selector);
        if (cell) cell.textContent = format(value);
      });
    });

    const impact = document.getElementById('detailEstimateImpact');
    if (impact && payload.estimate) {
      impact.textContent = `Live estimate impact: ${format(payload.estimate.hours)} hours · ${Number(payload.estimate.fees || 0).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}`;
    }
  };

  const preview = async () => {
    const serial = ++requestSerial;
    try {
      const response = await fetch(`${window.location.pathname}/preview`, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'fetch', 'X-Preview': '1'}
      });
      if (!response.ok) {
        if (window.CIErrorModal) await window.CIErrorModal.showResponse(response);
        return;
      }
      const payload = await response.json();
      if (serial !== requestSerial) return;
      applyPreview(payload);
    } catch (_) {
      if (window.CIErrorModal) window.CIErrorModal.show('The Estimate Detail preview could not be calculated. Your entered values have not been lost.');
    }
  };

  const queuePreview = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(preview, 120);
  };

  form.querySelectorAll('input[name^="mod_"]').forEach(input => {
    input.addEventListener('input', () => {
      updateCurrentDev(input);
      queuePreview();
    });
  });

  const factor = form.querySelector('input[name="unit_test_factor_override"]');
  if (factor) factor.addEventListener('input', queuePreview);
})();
