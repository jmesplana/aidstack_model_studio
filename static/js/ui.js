import {escape as e} from './api.js';
import {icon} from './icons.js';
let timer;
export function toast(message, error = false) {
  const element = document.querySelector('#toast');
  element.textContent = message;
  element.className = error ? 'error' : '';
  element.style.display = 'block';
  clearTimeout(timer);
  timer = setTimeout(() => {element.style.display = 'none';}, error ? 10000 : 4500);
}
export function notice(message, type = '') {return `<div class="notice ${type}">${icon(type === 'success' ? 'check' : 'info')}<div>${message}</div></div>`;}
export function heading(title, description, action = '') {return `<div class="page-heading"><div><div class="eyebrow">MODEL STUDIO</div><h1>${e(title)}</h1><p>${e(description)}</p></div>${action}</div>`;}
export function empty(title, description, action = '', glyph = 'flask') {return `<div class="empty-experiments"><div class="empty-icon">${icon(glyph)}</div><h3>${e(title)}</h3><p>${e(description)}</p>${action}</div>`;}
export function button(label, href, glyph = 'plus', style = 'primary') {return `<a class="btn ${style}" href="${href}">${icon(glyph)}${e(label)}</a>`;}
export async function busy(button, task) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span> Working…';
  try {return await task();}
  catch (error) {toast(error.message, true); return null;}
  finally {if (button.isConnected) {button.disabled = false; button.innerHTML = original;}}
}
export function confirmDialog({title, description, label = 'Continue', reviewer = false, onConfirm}) {
  const dialog = document.querySelector('#dialog');
  document.querySelector('#dialog-content').innerHTML = `<form id="confirm-form"><h2>${e(title)}</h2><p>${e(description)}</p>${reviewer ? '<div class="field"><label for="reviewer">Approving reviewer</label><input id="reviewer" name="reviewer" required placeholder="Your name" autocomplete="name"></div>' : ''}<div class="dialog-actions"><button type="button" class="btn" id="dialog-cancel">Cancel</button><button class="btn primary" type="submit">${e(label)}</button></div></form>`;
  dialog.showModal();
  document.querySelector('#dialog-cancel').onclick = () => dialog.close();
  document.querySelector('#confirm-form').onsubmit = async event => {
    event.preventDefault();
    const name = document.querySelector('#reviewer')?.value;
    await busy(event.submitter, async () => {await onConfirm(name); dialog.close();});
  };
}
