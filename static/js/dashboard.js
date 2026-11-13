import {escape as e, number as n, date, badge} from './api.js';
import {icon} from './icons.js';
import {heading, button, empty, notice} from './ui.js';

export function experimentRow(item) {
  return `<a class="experiment-row" href="#experiment/${item.id}"><span class="row-icon">${icon('flask')}</span><div><strong>${e(item.name)}</strong><p>${e(item.model_id)} · ${e(item.dataset_name)} · ${date(item.created_at)}</p></div>${badge(item.status)}${icon('chevron')}</a>`;
}

export function overview(state) {
  const experiments = state.experiments, datasets = state.datasets;
  const approved = Object.keys(state.status.active).length;
  return heading('A better model starts with your data.', 'Turn your team’s expertise into more accurate classifications.', button('New experiment', '#new')) +
  `<section class="hero"><div class="hero-copy"><div class="eyebrow">YOUR EXPERTISE. YOUR MODEL.</div><h2>Teach your model.<br>Keep people in control.</h2><p>Bring your reviewed spreadsheets, define what to learn, and measure the improvement before making it live.</p>${button(experiments.length?'Create an experiment':'Create your first experiment', '#new', 'arrow', 'orange')}</div><div class="hero-art" aria-hidden="true"><div class="flow-art"><div class="art-node">${icon('file')}<small>YOUR DATA</small></div><span>···</span><div class="art-node middle">${icon('cpu')}<small>YOUR MODEL</small></div><span>···</span><div class="art-node">${icon('check')}<small>YOUR APPROVAL</small></div></div><span class="art-caption">FROM REVIEWED DATA TO BETTER DECISIONS</span></div></section>
  <div class="stats">${[
    ['Experiments',experiments.length,'Every improvement, tracked','flask'],
    ['Datasets',datasets.length,`${n(datasets.reduce((a,d)=>a+d.row_count,0))} records in your workspace`,'database'],
    ['Ready for review',experiments.filter(x=>x.status==='trained'||x.status==='evaluated').length,'Compare before you approve','chart'],
    ['Approved models',approved,approved?'Available for local serving':'Your current model is unchanged','shield']
  ].map(([title,value,help,glyph])=>`<div class="stat"><div class="stat-top">${title}${icon(glyph)}</div><strong>${n(value)}</strong><small>${help}</small></div>`).join('')}</div>
  <div class="content-grid"><section><div class="section-heading"><h2>Recent experiments</h2><a class="text-link" href="#experiments">View all ${icon('arrow')}</a></div><div class="panel">${experiments.length ? experiments.slice(0,4).map(experimentRow).join('') : empty('Your first improvement starts here', 'Upload a coded spreadsheet to create an experiment. We’ll help you check the data and choose what the model should learn.', button('New experiment','#new','plus',''))}<div class="section-bottom">${icon('lock')} Experiments never update your active model automatically.</div></div>
  ${state.status.models.map(m=>`<div class="panel model-strip"><div class="model-mark">${icon('cpu')}</div><div><strong>${e(m.name)} model module</strong><p>${m.installed?'Local environment detected. Ready for a training preflight.':'Prepare data now. Install the training module when you’re ready.'}</p></div>${badge(m.installed?'ready':'setup needed')}<a href="#models" class="text-link">${icon('arrow')}</a></div>`).join('')}</section>
  <aside><div class="section-heading"><h2>From data to deployment</h2></div><div class="panel panel-padding"><div class="panel-title">${icon('book')} How it works</div><div class="how-list">${[
    ['Bring your reviewed data','Upload a spreadsheet and map inputs to the classifications your team approved.'],
    ['Run an experiment','Check data quality and train a separate candidate model.'],
    ['Measure the difference','Compare accuracy by language and category on held-out examples.'],
    ['Approve with confidence','Choose the version to serve. Keep previous releases for rollback.']
  ].map(([title,desc],i)=>`<div class="how-row"><span class="step-number">${i+1}</span><div><strong>${title}</strong><p>${desc}</p></div></div>`).join('')}</div><div class="tip"><strong>People set the standard.</strong>Your team’s validated answers are the reference for evaluating improvement.</div></div></aside></div>`;
}

export function experimentsView(state) {
  return heading('Experiments', 'Every candidate has its own data, settings, and evaluation.',button('New experiment','#new')) +
    `<div class="page-toolbar"><div class="search-field">${icon('search')}<input id="search-experiments" type="text" aria-label="Search experiments" placeholder="Search experiments…"></div><select id="status-filter" aria-label="Filter by status"><option value="">All statuses</option>${[...new Set(state.experiments.map(x=>x.status))].map(s=>`<option>${e(s)}</option>`).join('')}</select></div><div class="panel" id="experiment-list">${state.experiments.length?state.experiments.map(experimentRow).join(''):empty('No experiments yet','Create an experiment from your team-reviewed data.',button('New experiment','#new'))}</div>`;
}
export function bindExperiments(state) {
  const filter = () => {
    const query = document.querySelector('#search-experiments').value.toLowerCase();
    const status = document.querySelector('#status-filter').value;
    const records = state.experiments.filter(x=>x.name.toLowerCase().includes(query)&&(!status||x.status===status));
    document.querySelector('#experiment-list').innerHTML = records.length?records.map(experimentRow).join(''):empty('No matches','Try a different search or status.');
  };
  document.querySelector('#search-experiments').oninput=filter;
  document.querySelector('#status-filter').onchange=filter;
}
export function datasetsView(state) {
  return heading('Datasets', 'Your source spreadsheets, stored locally and versioned by import.',button('Upload dataset','#new','upload')) +
    (state.datasets.length ? state.datasets.map(d=>`<section class="panel dataset-panel"><div class="section-heading"><div><h3>${icon('file')} ${e(d.name)}</h3><p>${n(d.row_count)} records · ${d.columns.length} columns · Imported ${date(d.created_at)}</p></div>${button('Use in experiment',`#new/${d.id}`,'arrow','')}</div><div class="category-pills">${d.columns.map(c=>`<span>${e(c.name)}</span>`).join('')}</div><details><summary>Column quality and preview</summary><div><div class="table-wrap"><table><thead><tr><th>Column</th><th>Missing</th><th>Distinct values</th><th>Example</th></tr></thead><tbody>${d.columns.map(c=>`<tr><td>${e(c.name)}</td><td>${n(c.missing)}</td><td>${n(c.unique)}</td><td>${e(c.examples[0])}</td></tr>`).join('')}</tbody></table></div></div></details></section>`).join('') : `<div class="panel empty-full">${empty('Bring your first dataset','Labelled files support supervised training. Unlabelled files can be inspected now and labelled before training.',button('Upload a spreadsheet','#new','upload'),'database')}</div>`);
}
export function modelsView(state) {
  return heading('Model registry', 'Independent model modules. Explicitly approved checkpoints.') + `<div class="registry-grid">${state.status.models.map(m=>{
    const active = state.experiments.find(x=>x.id===state.status.active[m.id]);
    return `<section class="panel"><div class="section-heading"><div class="model-mark">${icon('cpu')}</div>${badge(m.installed?'ready':'setup needed')}</div><h3>${e(m.name)}</h3><p>${e(m.description)}</p><hr class="separator"><div class="outline-item"><span>Approved release</span>${active?`<a class="text-link" href="#experiment/${active.id}">${e(active.name)}</a>`:'No Model Studio release yet'}</div><div class="outline-item"><span>Training setup</span><code>npm run setup:model -- ${e(m.id)}</code></div><p class="help">One-time setup in Model Studio’s own environment. Your existing inference installation is separate.</p><div class="outline-item"><span>Serve an approved version</span><code>npm run serve:model</code></div><p class="help">Starts a separate local server. Restart it after changing an approved release.</p>${button('New experiment','#new','plus')}</section>`;
  }).join('')}</div><h2 class="subheading">Approved version history</h2><div class="panel">${state.experiments.filter(x=>x.status==='approved').map(experimentRow).join('')||empty('No approved versions','Training alone does not create a release. A candidate must pass evaluation and receive your approval.','','shield')}</div>${notice('Adding a model? Create a module with a settings manifest and the shared training, evaluation, and inference interface. See <a class="text-link" href="#guide">Getting started</a> for the extension guide.')}`;
}
