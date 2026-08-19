(() => {
  const form = document.getElementById('calcForm');
  if (!form || !window.location.pathname.endsWith('/calculations')) return;

  const number = (value) => {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return '0';
    return n.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
  };

  const currency = (value) => {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0.00';
  };

  const rowByKey = (key) => {
    for (const hidden of form.querySelectorAll('input[name^="line_key_"]')) {
      if (hidden.value === key) return hidden.closest('tr');
    }
    return null;
  };

  const phaseRow = (phase) => {
    for (const row of form.querySelectorAll('tr.phase-row')) {
      const first = row.cells && row.cells[0];
      if (first && first.textContent.trim() === phase) return row;
    }
    return null;
  };

  let timer = null;
  let controller = null;

  const apply = (payload) => {
    const isCip = payload.product === 'CIP';
    (payload.rows || []).forEach(item => {
      const row = rowByKey(item.key);
      if (!row) return;
      const standardCell = row.querySelector('.standard, .calculated');
      const totalCell = row.querySelector('.total-cell');
      if (standardCell) standardCell.textContent = number(item.standard);
      if (totalCell) totalCell.textContent = number(isCip ? item.investment : item.extended);
      if (isCip) {
        const calculated = row.querySelectorAll('.calculated');
        if (calculated.length) calculated[calculated.length - 1].textContent = number(item.task);
      }
    });

    Object.entries(payload.phase_totals || {}).forEach(([phase, total]) => {
      const row = phaseRow(phase);
      if (!row || !row.cells) return;
      row.cells[1].textContent = number(total.standard);
      row.cells[3].textContent = number(isCip ? total.investment : total.extended);
      if (isCip && row.cells.length > 5) {
        row.cells[4].textContent = number(total.non_billable);
        row.cells[5].textContent = number(total.task);
      }
    });

    const grand = form.querySelector('tr.grand-total');
    if (grand && grand.cells && grand.cells.length > 3) {
      if (isCip) {
        grand.cells[3].textContent = number(payload.summary.investment_hours);
        if (grand.cells.length > 5) {
          grand.cells[4].textContent = number(payload.summary.non_billable_hours);
          grand.cells[5].textContent = number(payload.summary.total_internal_hours);
        }
      } else {
        grand.cells[3].textContent = number(payload.summary.hours);
      }
    }

    if (!isCip) {
      const kpis = document.querySelectorAll('.calc-kpis span b');
      if (kpis.length > 0) kpis[0].textContent = `${number(payload.summary.hours)} h`;
      if (kpis.length > 1) kpis[1].textContent = currency(payload.summary.fees);
    } else {
      const card = document.querySelector('.calc-summary-card');
      if (card) {
        card.innerHTML = `<strong>Customer Investment:</strong> ${number(payload.summary.investment_hours)} hours · ${currency(payload.summary.fees)} &nbsp; <strong>Plan Not Billable:</strong> ${number(payload.summary.non_billable_hours)} hours &nbsp; <strong>Total Internal:</strong> ${number(payload.summary.total_internal_hours)} hours`;
      }
    }
  };

  const preview = async () => {
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const response = await fetch(`${window.location.pathname}/preview`, {
        method: 'POST',
        body: new FormData(form),
        headers: {'X-Calculation-Preview': '1'},
        signal: controller.signal
      });
      if (!response.ok) return;
      apply(await response.json());
    } catch (error) {
      if (error.name !== 'AbortError') console.warn('Calculation preview failed', error);
    }
  };

  const queue = () => {
    clearTimeout(timer);
    timer = setTimeout(preview, 120);
  };

  form.querySelectorAll('input[name^="adjust_"], input[name^="nonbillable_"]').forEach(input => {
    input.addEventListener('input', () => {
      const row = input.closest('tr');
      if (row && input.name.startsWith('adjust_')) {
        const standardCell = row.querySelector('.standard, .calculated');
        const totalCell = row.querySelector('.total-cell');
        if (standardCell && totalCell) {
          const standard = Number(standardCell.textContent.trim() || 0);
          const adjust = Number(input.value || 0);
          if (Number.isFinite(standard) && Number.isFinite(adjust)) totalCell.textContent = number(standard + adjust);
        }
      }
      queue();
    });
  });
})();
