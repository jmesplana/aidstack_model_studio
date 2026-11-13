export async function api(path, options = {}) {
  const response = await fetch('/api' + path, { ...options, headers: {
    ...(options.body instanceof FormData ? {} : {'Content-Type': 'application/json'}),
    'X-Studio-Request': '1', ...options.headers
  }});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request failed.');
  return result;
}
export const post = (path, value = {}) => api(path, {method: 'POST', body: JSON.stringify(value)});
export const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const number = value => Number(value || 0).toLocaleString();
export const percent = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
export const date = value => new Date(value).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'});
export const badge = value => `<span class="badge ${escape(value)}">${escape(value.replaceAll('_',' '))}</span>`;
