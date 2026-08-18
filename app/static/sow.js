(() => {
  const hyper = document.getElementById('hypercareRows');
  const devices = document.getElementById('deviceRows');
  function wireRemove(root){ if(!root) return; root.querySelectorAll('.remove-repeat').forEach(b => b.onclick = () => b.closest('.repeat-row').remove()); }
  wireRemove(hyper); wireRemove(devices);
  const addH = document.getElementById('addHypercare');
  if(addH) addH.onclick = () => { hyper.insertAdjacentHTML('beforeend', `<div class="repeat-row hypercare-row"><input name="hypercare_description" placeholder="Location Description"><input name="hypercare_country" placeholder="Country"><select name="hypercare_support_type"><option>Remote</option><option>On-Site</option></select><input name="hypercare_hours" type="number" step="0.25" min="0" value="0" placeholder="Hours"><button type="button" class="button small secondary remove-repeat">Remove</button></div>`); wireRemove(hyper); };
  const addD = document.getElementById('addDevice');
  if(addD) addD.onclick = () => { devices.insertAdjacentHTML('beforeend', `<div class="repeat-row device-row"><select name="device_type"><option>Handheld Unit</option><option>Vehicle Mount Unit</option><option>Desktop Environment</option><option>Other</option></select><input name="device_make_model" placeholder="Make / Model"><input name="device_os_version" placeholder="OS / Version"><button type="button" class="button small secondary remove-repeat">Remove</button></div>`); wireRemove(devices); };
})();
