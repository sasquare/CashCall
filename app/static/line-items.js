/*
 * Dynamic line-item rows for the submission forms (new.html / urgent_new.html).
 * Rows are cloned client-side from a hidden <template id="li-row-template">
 * (index placeholder "__IDX__") — no server round-trip needed.
 */

function getRowCount() {
  return document.querySelectorAll('#line-items-container .li-row').length;
}

function updateCounter() {
  const count = getRowCount();
  const counterEl = document.getElementById('li-counter');
  if (counterEl) counterEl.textContent = count + ' / 10';
  const btn = document.getElementById('add-li-btn');
  if (btn) {
    btn.disabled = count >= 10;
    btn.classList.toggle('opacity-50', count >= 10);
    btn.classList.toggle('cursor-not-allowed', count >= 10);
  }
}

function addLineItem() {
  const container = document.getElementById('line-items-container');
  const template = document.getElementById('li-row-template');
  if (!container || !template) return;
  if (getRowCount() >= 10) return;

  const nextIdx = getRowCount();
  const html = template.innerHTML.split('__IDX__').join(String(nextIdx));
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html.trim();
  container.appendChild(wrapper.firstElementChild);
  updateCounter();
}

function recountRows() {
  // Keep every row's name/id/for attributes sequential (0..N-1) after a removal.
  const rows = document.querySelectorAll('#line-items-container .li-row');
  rows.forEach((rowEl, newIdx) => {
    const oldIdx = rowEl.id.replace('li-row-', '');
    if (String(oldIdx) === String(newIdx)) return;

    rowEl.id = 'li-row-' + newIdx;
    const oldSuffix = '_' + oldIdx;
    const newSuffix = '_' + newIdx;
    rowEl.querySelectorAll('[name],[id],[for]').forEach((el) => {
      if (el.name && el.name.endsWith(oldSuffix)) {
        el.name = el.name.slice(0, -oldSuffix.length) + newSuffix;
      }
      if (el.id && el.id.endsWith(oldSuffix)) {
        el.id = el.id.slice(0, -oldSuffix.length) + newSuffix;
      }
      if (el.htmlFor && el.htmlFor.endsWith(oldSuffix)) {
        el.htmlFor = el.htmlFor.slice(0, -oldSuffix.length) + newSuffix;
      }
    });
    const arrearCheckbox = rowEl.querySelector('input[type="checkbox"][id^="is_arrear_"]');
    if (arrearCheckbox) {
      arrearCheckbox.setAttribute('onchange', 'toggleArrearType(' + newIdx + ', this.checked)');
    }
  });
  updateCounter();
}

function toggleArrearType(idx, checked) {
  const wrap = document.getElementById('arrear_type_wrap_' + idx);
  if (wrap) {
    wrap.classList.toggle('hidden', !checked);
    const sel = wrap.querySelector('select');
    if (sel) sel.required = checked;
  }
}

document.addEventListener('DOMContentLoaded', updateCounter);
