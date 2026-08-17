(() => {
  function initAssumptions() {
    const block = document.getElementById('assumptionsBlock');
    if (!block) return;

    const mountTarget = document.getElementById('cip-effort-summary') || document.getElementById('estimate-summary');
    if (mountTarget) mountTarget.insertAdjacentElement('afterend', block);
    const detached = document.getElementById('assumptionsDetached');
    if (detached) detached.remove();

    if (block.dataset.readonly === '1') return;

    const rid = block.dataset.revisionId;
    const list = document.getElementById('assumptionsList');
    const addButton = document.getElementById('addAssumptionButton');

    const renumber = () => {
      list.querySelectorAll('.assumption-row').forEach((row, index) => {
        const number = row.querySelector('.assumption-number');
        if (number) number.textContent = `${index + 1}.`;
      });
    };

    const ensureEmptyState = () => {
      const rows = list.querySelectorAll('.assumption-row');
      let empty = list.querySelector('.assumptions-empty');
      if (rows.length === 0 && !empty) {
        empty = document.createElement('div');
        empty.className = 'assumptions-empty subtle';
        empty.textContent = 'No assumptions added.';
        list.appendChild(empty);
      } else if (rows.length > 0 && empty) {
        empty.remove();
      }
    };

    const setStatus = (row, text, state = '') => {
      const status = row.querySelector('.assumption-save-status');
      if (!status) return;
      status.textContent = text;
      status.className = `assumption-save-status ${state}`;
    };

    async function saveRow(row) {
      const aid = row.dataset.assumptionId;
      const textarea = row.querySelector('[data-assumption-text]');
      if (!aid || !textarea) return;
      const body = new FormData();
      body.set('text', textarea.value);
      setStatus(row, 'Saving…', 'saving');
      try {
        const response = await fetch(`/estimate/${rid}/assumptions/${aid}`, {method: 'POST', body});
        if (!response.ok) throw new Error(await response.text());
        const result = await response.json();
        textarea.value = result.text;
        setStatus(row, 'Saved', 'saved');
      } catch (error) {
        setStatus(row, 'Save failed', 'error');
      }
    }

    function wireRow(row) {
      const textarea = row.querySelector('[data-assumption-text]');
      const deleteButton = row.querySelector('[data-assumption-delete]');
      if (textarea) textarea.addEventListener('blur', () => saveRow(row));
      if (deleteButton) {
        deleteButton.addEventListener('click', async () => {
          if (!confirm('Delete this assumption?')) return;
          const aid = row.dataset.assumptionId;
          deleteButton.disabled = true;
          try {
            const response = await fetch(`/estimate/${rid}/assumptions/${aid}/delete`, {method: 'POST'});
            if (!response.ok) throw new Error(await response.text());
            row.remove();
            renumber();
            ensureEmptyState();
          } catch (error) {
            deleteButton.disabled = false;
            setStatus(row, 'Delete failed', 'error');
          }
        });
      }
    }

    list.querySelectorAll('.assumption-row').forEach(wireRow);

    if (addButton) {
      addButton.addEventListener('click', async () => {
        addButton.disabled = true;
        try {
          const response = await fetch(`/estimate/${rid}/assumptions`, {method: 'POST'});
          if (!response.ok) throw new Error(await response.text());
          const result = await response.json();
          const row = document.createElement('div');
          row.className = 'assumption-row';
          row.dataset.assumptionId = result.id;
          row.innerHTML = `
            <span class="assumption-number"></span>
            <textarea class="assumption-textarea" data-assumption-text maxlength="5000" rows="2" placeholder="Enter assumption"></textarea>
            <button type="button" class="button small assumption-delete" data-assumption-delete>Delete</button>
            <span class="assumption-save-status" aria-live="polite"></span>`;
          list.appendChild(row);
          wireRow(row);
          renumber();
          ensureEmptyState();
          row.querySelector('textarea').focus();
        } catch (error) {
          alert('Unable to add assumption. Please try again.');
        } finally {
          addButton.disabled = false;
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAssumptions);
  } else {
    initAssumptions();
  }
})();
