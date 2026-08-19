(() => {
  const root = document.getElementById('deliverableRows');
  if (!root) return;
  const reindex = () => {
    root.querySelectorAll('[data-deliverable-row]').forEach((row, i) => {
      const cb = row.querySelector('input[type="checkbox"][name^="deliverable_included_"]');
      if (cb) cb.name = `deliverable_included_${i}`;
    });
  };
  const wire = () => root.querySelectorAll('.remove-deliverable').forEach(btn => {
    btn.onclick = () => { btn.closest('[data-deliverable-row]').remove(); reindex(); };
  });
  wire();
  const add = document.getElementById('addDeliverable');
  if (add) add.onclick = () => {
    const i = root.querySelectorAll('[data-deliverable-row]').length;
    root.insertAdjacentHTML('beforeend', `<div class="deliverable-card" data-deliverable-row>
      <input type="hidden" name="deliverable_key" value="CUSTOM_${Date.now()}">
      <label class="checkbox-line"><input type="checkbox" name="deliverable_included_${i}" checked> Include in SOW</label>
      <label>Deliverable Name<input name="deliverable_title" value=""></label>
      <label>Scope Description<textarea name="deliverable_description" rows="3"></textarea></label>
      <label>Detailed Requirements / Bullets<textarea name="deliverable_details" rows="4"></textarea></label>
      <button type="button" class="button secondary small remove-deliverable">Remove</button></div>`);
    wire(); reindex();
  };
})();
