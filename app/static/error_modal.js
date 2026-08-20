(() => {
  const modal = document.getElementById('ciErrorModal');
  const title = document.getElementById('ciErrorTitle');
  const messageNode = document.getElementById('ciErrorMessage');
  const ok = document.getElementById('ciErrorOk');
  if (!modal || !title || !messageNode || !ok) return;

  let lastFocus = null;

  const clearFieldErrors = () => {
    document.querySelectorAll('.ci-field-error').forEach(node => node.classList.remove('ci-field-error'));
  };

  const close = () => {
    modal.hidden = true;
    document.body.classList.remove('ci-modal-open');
    clearFieldErrors();
    if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  };

  const show = (message, fields = [], heading = 'Unable to Complete Action') => {
    lastFocus = document.activeElement;
    title.textContent = heading || 'Unable to Complete Action';
    messageNode.textContent = message || 'The requested action could not be completed.';
    clearFieldErrors();
    (fields || []).forEach(name => {
      document.querySelectorAll(`[name="${CSS.escape(String(name))}"]`).forEach(node => node.classList.add('ci-field-error'));
    });
    modal.hidden = false;
    document.body.classList.add('ci-modal-open');
    ok.focus();
  };

  const extractResponseError = async (response, suppliedText = null) => {
    let text = suppliedText;
    if (text === null) text = await response.text();
    const contentType = response.headers.get('content-type') || '';
    let message = `Unable to complete action (${response.status}).`;
    let fields = [];

    if (contentType.includes('application/json')) {
      try {
        const body = JSON.parse(text || '{}');
        const detail = body.detail ?? body;
        if (typeof detail === 'string') message = detail;
        else if (Array.isArray(detail)) {
          message = detail.map(item => item.msg || item.message || String(item)).join('\n');
          fields = detail.map(item => Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null).filter(Boolean);
        } else if (detail && typeof detail === 'object') {
          message = detail.message || detail.detail || message;
          fields = detail.fields || [];
        }
      } catch (_) {
        // Fall through to the plain-text cleanup below.
      }
    } else if (text) {
      const doc = new DOMParser().parseFromString(text, 'text/html');
      const explicit = doc.querySelector('.error,[role="alert"],.validation-error,.field-error');
      const cleaned = (explicit ? explicit.textContent : doc.body?.textContent || text).replace(/\s+/g, ' ').trim();
      if (cleaned) message = cleaned;
    }

    return {message, fields};
  };

  const showResponse = async (response, suppliedText = null) => {
    const parsed = await extractResponseError(response, suppliedText);
    const heading = response.status === 400 || response.status === 422 ? 'Missing Required Information' : 'Unable to Complete Action';
    show(parsed.message, parsed.fields, heading);
  };

  window.CIErrorModal = {show, close, showResponse};

  ok.addEventListener('click', close);
  document.addEventListener('keydown', event => {
    if (modal.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === 'Tab') {
      event.preventDefault();
      ok.focus();
    }
  });

  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (event.defaultPrevented) return;
    const submitter = event.submitter;
    const method = (submitter?.formMethod || form.method || 'get').toLowerCase();
    if (method !== 'post' || form.dataset.nativeSubmit === 'true' || form.dataset.errorModal === 'off' || form.target) return;

    event.preventDefault();
    if (submitter) submitter.disabled = true;

    try {
      const action = submitter?.formAction || form.action || window.location.href;
      const body = submitter ? new FormData(form, submitter) : new FormData(form);
      const response = await fetch(action, {
        method: 'POST',
        body,
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'fetch'}
      });

      if (!response.ok) {
        await showResponse(response);
        return;
      }

      if (response.redirected && response.url) window.location.assign(response.url);
      else window.location.reload();
    } catch (_) {
      show('The action could not be completed because the server could not be reached. Please try again.');
    } finally {
      if (submitter) submitter.disabled = false;
    }
  });
})();
