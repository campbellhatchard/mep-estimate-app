(() => {
  const modal = document.getElementById('ciErrorModal');
  const msg = document.getElementById('ciErrorMessage');
  const ok = document.getElementById('ciErrorOk');
  if (!modal || !msg || !ok) return;
  let lastFocus = null;
  const close = () => { modal.hidden = true; document.body.classList.remove('ci-modal-open'); if (lastFocus) lastFocus.focus(); };
  const show = (message, fields=[]) => {
    lastFocus = document.activeElement; msg.textContent = message || 'The requested action could not be completed.';
    document.querySelectorAll('.ci-field-error').forEach(x => x.classList.remove('ci-field-error'));
    (fields || []).forEach(name => document.querySelectorAll(`[name="${CSS.escape(name)}"]`).forEach(x => x.classList.add('ci-field-error')));
    modal.hidden = false; document.body.classList.add('ci-modal-open'); ok.focus();
  };
  ok.addEventListener('click', close);
  modal.addEventListener('click', e => { if (e.target === modal) close(); });
  document.addEventListener('keydown', e => { if (!modal.hidden && e.key === 'Escape') close(); });

  document.addEventListener('submit', async e => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' || form.dataset.nativeSubmit === 'true' || form.target) return;
    e.preventDefault();
    const submitter = e.submitter;
    if (submitter) submitter.disabled = true;
    try {
      const response = await fetch(form.action || location.href, {method:'POST', body:new FormData(form, submitter), credentials:'same-origin', headers:{'X-Requested-With':'fetch'}});
      if (!response.ok) {
        let message = `Unable to complete action (${response.status}).`, fields = [];
        const type = response.headers.get('content-type') || '';
        if (type.includes('application/json')) {
          const body = await response.json(); const detail = body.detail ?? body;
          if (typeof detail === 'string') message = detail;
          else if (detail && typeof detail === 'object') { message = detail.message || detail.detail || message; fields = detail.fields || []; }
        } else {
          const text = (await response.text()).trim();
          if (text) message = text.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
        }
        show(message, fields); return;
      }
      if (response.redirected && response.url) location.assign(response.url); else location.reload();
    } catch (err) {
      show('The action could not be completed because the server could not be reached. Please try again.');
    } finally {
      if (submitter) submitter.disabled = false;
    }
  });
})();
