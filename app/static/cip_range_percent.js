(() => {
  function initCipRangePercentages() {
    const fields = [
      {name: 'low_factor', max: 100},
      {name: 'high_factor', max: 200},
    ];
    fields.forEach(({name, max}) => {
      const input = document.querySelector(`input[name="${name}"]`);
      if (!input || input.dataset.percentDisplay === '1') return;
      const raw = Number.parseFloat(input.value);
      if (Number.isFinite(raw)) input.value = String(Math.round(raw * 10000) / 100);
      input.step = '0.1';
      input.min = '0';
      input.max = String(max);
      input.dataset.percentDisplay = '1';
      input.setAttribute('aria-label', `${name === 'low_factor' ? 'Low' : 'High'} Factor percent`);
      if (!input.nextElementSibling || !input.nextElementSibling.classList.contains('factor-percent-note')) {
        const suffix = document.createElement('span');
        suffix.className = 'factor-percent-note';
        suffix.textContent = '%';
        input.insertAdjacentElement('afterend', suffix);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCipRangePercentages);
  } else {
    initCipRangePercentages();
  }
})();
