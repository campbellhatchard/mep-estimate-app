(() => {
  function initCipRangePercentages() {
    const fields = [
      {name: 'low_factor', max: 100, label: 'Low Factor (%)'},
      {name: 'high_factor', max: 200, label: 'High Factor (%)'},
    ];
    fields.forEach(({name, max, label}) => {
      const input = document.querySelector(`input[name="${name}"]`);
      if (!input || input.dataset.percentDisplay === '1') return;
      const raw = Number.parseFloat(input.value);
      if (Number.isFinite(raw)) input.value = String(Math.round(raw * 10000) / 100);
      input.step = '0.1';
      input.min = '0';
      input.max = String(max);
      input.dataset.percentDisplay = '1';
      input.setAttribute('aria-label', label);
      const parent = input.parentElement;
      if (parent && parent.firstChild && parent.firstChild.nodeType === Node.TEXT_NODE) {
        parent.firstChild.textContent = `${label}:`;
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCipRangePercentages);
  } else {
    initCipRangePercentages();
  }
})();
