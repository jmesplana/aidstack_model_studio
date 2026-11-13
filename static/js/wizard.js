import {api, post, escape as e, number as n, badge} from './api.js';
import {icon} from './icons.js';
import {heading, notice, busy, toast} from './ui.js';

let draft;
let context;
const stepNames = ['Dataset','Column mapping','Quality review','Experiment setup'];
const options = (columns, selected = '', emptyLabel = 'Not selected') => `<option value="">${e(emptyLabel)}</option>${columns.map(c=>`<option value="${e(c.name)}" ${c.name===selected?'selected':''}>${e(c.name)}</option>`).join('')}`;
const getModel = () => context.status.models.find(m=>m.id===draft.model_id);

export function beginWizard(state, datasetId) {
  context = state;
  draft = {step:0, dataset:state.datasets.find(d=>d.id===datasetId)||null, model_id:state.status.models[0]?.id,
    mapping:{inputs:[],targets:[],review_mode:'',review_confirmed:false,train_fraction:state.status.defaults.train_fraction}, settings:{}, name:'', book:null, report:null};
  if (draft.dataset) selectDataset(draft.dataset);
  render();
}

function selectDataset(dataset) {
  draft.dataset = dataset;
  draft.mapping.inputs = [dataset.suggested_input];
  draft.mapping.targets = [];
  draft.name = dataset.name.replace(/\.[^.]+$/,'') + ' · improvement';
  draft.report = null;
}

function outline() {
  return `<aside class="wizard-aside"><div class="panel outline-card"><h3>Your experiment</h3><div class="outline-item"><span>Dataset</span>${draft.dataset?e(draft.dataset.name):'Choose a spreadsheet'}</div><div class="outline-item"><span>Model module</span>${e(getModel()?.name||'No modules installed')}</div><div class="outline-item"><span>What the model will learn</span>${draft.mapping.targets.length?draft.mapping.targets.map(e).join(', '):'Choose target columns'}</div><div class="outline-item"><span>Label source</span>${draft.mapping.review_mode==='all_verified'?'AI-generated · team validated':draft.mapping.review_mode==='column'?'Review status from your file':'Not confirmed'}</div><div class="tip"><strong>${icon('shield')} Approval stays with you.</strong>Saving an experiment or starting training never changes the active model.</div></div>${notice('Your source data stays on this computer. Use a protected device and keep local backups.')}</aside>`;
}

function render() {
  document.querySelector('#main').innerHTML = heading('New training experiment','Teach a model from the classifications your team has reviewed.') +
    `<div class="steps">${stepNames.map((name,i)=>`<div class="step ${draft.step===i?'current':draft.step>i?'done':''}"><b>${draft.step>i?'✓':i+1}</b>${name}</div>`).join('')}</div><div class="wizard-grid"><div class="wizard-main">${[datasetStep,mappingStep,qualityStep,settingsStep][draft.step]()}<div id="wizard-error" role="alert"></div><div class="wizard-actions"><button class="btn" id="wizard-back">${draft.step?'← Back':'Cancel'}</button><span class="help">Step ${draft.step+1} of 4</span><button class="btn primary" id="wizard-next">${draft.step===3?'Create experiment':draft.step===1?'Inspect dataset':'Continue'} ${icon('arrow')}</button></div></div>${outline()}</div>`;
  document.querySelector('#wizard-back').onclick=()=>{if(draft.step){capture();draft.step--;render();}else location.hash='#overview';};
  document.querySelector('#wizard-next').onclick=event=>busy(event.currentTarget, next);
  [bindDataset,bindMapping,()=>{},bindSettings][draft.step]();
}

function preview(dataset) {
  const columns = dataset.columns.slice(0,5);
  return `<div class="table-wrap"><table class="preview-table"><thead><tr>${columns.map(c=>`<th>${e(c.name)}</th>`).join('')}</tr></thead><tbody>${dataset.preview.slice(0,4).map(row=>`<tr>${columns.map(c=>`<td title="${e(row[c.name])}">${e(row[c.name])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="help">Preview of the first ${Math.min(4,dataset.preview.length)} rows and ${columns.length} columns. All ${n(dataset.row_count)} records will be inspected.</p>`;
}

function datasetStep() {
  return `<section class="panel"><h2>Start with your spreadsheet</h2><p>Bring your coded data from Excel AI Insights or another source.</p>${draft.dataset?`<div class="file-card">${icon('file')}<div><strong>${e(draft.dataset.name)}</strong><p>${n(draft.dataset.row_count)} records · ${draft.dataset.columns.length} columns</p></div><button id="replace-file" class="text-link">Change</button></div>${draft.dataset.sheets.length>1?`<div class="field" style="margin-top:18px"><label for="worksheet">Worksheet</label><select id="worksheet">${draft.dataset.sheets.map(s=>`<option ${s===draft.dataset.sheet?'selected':''}>${e(s)}</option>`).join('')}</select></div>`:''}${preview(draft.dataset)}`:`<label class="upload-zone" id="drop-zone" for="dataset-upload">${icon('upload')}<strong>Drop your spreadsheet here</strong><p>or click to choose a file from your computer</p><span class="btn">${icon('plus')} Choose file</span><small style="margin-top:15px">Excel (.xlsx), CSV, or JSONL · Up to ${context.status.defaults.max_upload_mb} MB</small></label><input class="upload-input" type="file" id="dataset-upload" accept=".xlsx,.csv,.jsonl">${context.datasets.length?`<hr class="separator"><div class="field"><label for="existing-dataset">Or use a dataset already in your workspace</label><select id="existing-dataset"><option value="">Choose a dataset</option>${context.datasets.map(d=>`<option value="${d.id}">${e(d.name)} · ${n(d.row_count)} rows</option>`).join('')}</select></div>`:''}`}${notice('Labelled and unlabelled files are welcome. Only examples with eligible labels can be used for supervised training.')}<div class="section-heading" style="margin-top:24px"><h3>What happens to your file?</h3></div><p class="help">A local copy is saved in your workspace. Your spreadsheet is never sent to a cloud model. Uploading creates a dataset, not a training job.</p></section>`;
}

async function uploadFile(file) {
  if (!file) return;
  const zone=document.querySelector('#drop-zone');
  if(zone) zone.innerHTML='<span class="spinner"></span><p>Reading your spreadsheet…</p>';
  try {
    const data = new FormData(); data.append('file',file);
    const dataset=await api('/datasets',{method:'POST',body:data});
    context.datasets.unshift(dataset); selectDataset(dataset); render(); toast('Dataset imported. Your model is unchanged.');
  } catch(error) {render(); showError(error.message);}
}
function bindDataset() {
  document.querySelector('#dataset-upload')?.addEventListener('change',event=>uploadFile(event.target.files[0]));
  const zone=document.querySelector('#drop-zone');
  if(zone) {
    zone.ondragover=event=>{event.preventDefault();zone.classList.add('dragover');};
    zone.ondragleave=()=>zone.classList.remove('dragover');
    zone.ondrop=event=>{event.preventDefault();uploadFile(event.dataTransfer.files[0]);};
    zone.tabIndex=0; zone.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();document.querySelector('#dataset-upload').click();}};
  }
  document.querySelector('#replace-file')?.addEventListener('click',()=>{draft.dataset=null;render();});
  document.querySelector('#existing-dataset')?.addEventListener('change',event=>{const dataset=context.datasets.find(d=>d.id===event.target.value);if(dataset){selectDataset(dataset);render();}});
  document.querySelector('#worksheet')?.addEventListener('change',async event=>{try {const dataset=await post(`/datasets/${draft.dataset.id}/sheet`,{sheet:event.target.value});selectDataset(dataset);render();}catch(error){showError(error.message);}});
}

function mappingStep() {
  const dataset=draft.dataset, m=draft.mapping;
  const chips=(name,selected)=>dataset.columns.map(c=>`<label class="check-chip"><input type="checkbox" name="${name}" value="${e(c.name)}" ${selected.includes(c.name)?'checked':''}>${e(c.name)}</label>`).join('');
  return `<section class="panel"><h2>Tell the model what to learn</h2><p>Choose the original input and the final classifications your team approved.</p><div class="field"><label for="codebook-upload">Existing coding rules <span class="optional">optional</span></label><label class="btn" for="codebook-upload">${icon('book')} ${draft.book?'Replace codebook':'Import Excel AI Insights codebook'}</label><input class="upload-input" id="codebook-upload" type="file" accept=".json">${draft.book?`<p class="help positive">${draft.book.questions.length} questions imported. Category definitions and option order are preserved.</p>`:'<p class="help">Use Export Configuration in Excel AI Insights. Without a codebook, you can confirm categories and instructions here.</p>'}</div><hr class="separator"><div class="field"><span class="field-label">1. What should the model read?</span><div class="checkbox-list">${chips('input-column',m.inputs)}</div><p class="help">Use only information that will be available when coding new records. Never include the answer.</p></div><div class="field"><span class="field-label">2. Which classifications should it learn?</span><div class="checkbox-list">${chips('target-column',m.targets)}</div><p class="help">Choose the final, corrected label columns. Missing labels are excluded from training.</p></div><div class="form-grid"><div class="field"><label for="language-column">Language column <span class="optional">optional</span></label><select id="language-column">${options(dataset.columns,m.language_column,'Unknown / not recorded')}</select><button class="text-link" type="button" id="suggest-languages" style="margin-top:8px">Suggest languages from a sample ${icon('arrow')}</button></div><div class="field"><label for="group-column">Related-record ID <span class="optional">optional</span></label><select id="group-column">${options(dataset.columns,m.group_column,'Exact duplicates only')}</select><p class="help">Keep feedback from the same source or conversation in one data split.</p></div></div><div id="language-result"></div><div class="field"><label for="slice-column">Additional comparison breakdown <span class="optional">optional</span></label><select id="slice-column">${options(dataset.columns,m.slice_column,'No additional breakdown')}</select><p class="help">For example, criticality, country, or programme.</p></div><hr class="separator"><div class="field"><label for="review-mode">3. How were these labels reviewed?</label><select id="review-mode"><option value="">Choose review status</option><option value="all_verified" ${m.review_mode==='all_verified'?'selected':''}>Generated by AI, then validated or corrected by the team</option><option value="column" ${m.review_mode==='column'?'selected':''}>Review status is recorded in a column</option><option value="unreviewed" ${m.review_mode==='unreviewed'?'selected':''}>Not yet reviewed / unlabelled</option></select></div>${m.review_mode==='all_verified'?`<label class="check-line"><input id="review-confirmed" type="checkbox" ${m.review_confirmed?'checked':''}><span>I confirm that the team checked the selected target labels. The final values include their corrections.</span></label>`:''}${m.review_mode==='column'?`<div class="form-grid"><div class="field"><label for="review-column">Review status column</label><select id="review-column">${options(dataset.columns,m.review_column)}</select></div><div class="field"><label for="verified-values">Values that mean approved</label><input id="verified-values" type="text" placeholder="e.g. Approved, Corrected" value="${e((m.verified_values||[]).join(', '))}"><p class="help">Comma-separated. Values must match the file exactly.</p></div></div><label class="check-line"><input id="include-unverified" type="checkbox" ${m.include_unverified?'checked':''}><span>Also include unreviewed AI labels in training. Evaluation and calibration still use only human-validated labels.</span></label>`:''}${m.review_mode==='unreviewed'?notice('You can inspect the column statistics in Datasets. Add reviewed target labels before creating a supervised experiment.','warning'):''}</section>`;
}

function bindMapping() {
  document.querySelector('#review-mode').onchange=()=>{capture();render();};
  document.querySelector('#codebook-upload').onchange=async event=>{
    try {
      const book=JSON.parse(await event.target.files[0].text());
      draft.book=await post('/codebooks/inspect',book); capture();
      draft.mapping.codebook=draft.book;
      draft.mapping.inputs=(book.sourceColumns||[]).filter(c=>draft.dataset.columns.some(x=>x.name===c));
      if(!draft.mapping.inputs.length) draft.mapping.inputs=[draft.dataset.suggested_input];
      draft.mapping.targets=book.questions.map(q=>q.outputColumnName).filter(c=>draft.dataset.columns.some(x=>x.name===c));
      render();toast('Codebook imported. Confirm the column selections.');
    }catch(error){showError(error.message);}
  };
  document.querySelector('#suggest-languages').onclick=event=>busy(event.currentTarget,async()=>{
    capture();const result=await post(`/datasets/${draft.dataset.id}/languages`,{column:draft.mapping.inputs[0]});
    document.querySelector('#language-result').innerHTML=notice(`${result.counts?Object.entries(result.counts).map(([key,value])=>`${e(key)}: ${n(value)}`).join(' · ')+'<br>':''}${e(result.message)}`,'warning');
  });
}

function qualityStep() {
  const q=draft.report;
  return `<section class="panel"><h2>Review your training data</h2><p>Only eligible records enter the experiment. Check exclusions and category definitions before continuing.</p><div class="quality-stats"><div><span>Records inspected</span><strong>${n(q.total)}</strong></div><div><span>Eligible records</span><strong class="positive">${n(q.eligible)}</strong></div><div><span>Excluded records</span><strong>${n(q.excluded)}</strong></div></div><div class="table-wrap"><table><thead><tr><th>Quality check</th><th>Records excluded</th></tr></thead><tbody>${[['Missing input','missing_input'],['Missing target labels','missing_labels'],['Labels outside the codebook','invalid_labels'],['Duplicate records','duplicate'],['Conflicting classifications','label_conflict'],['Unreviewed or ineligible provenance','unreviewed']].map(([title,key])=>`<tr><td>${title}</td><td>${n(q.counts[key])}</td></tr>`).join('')}</tbody></table></div><h3 class="subheading">Your data splits</h3><div class="split-grid">${Object.entries(q.split_counts).map(([key,count])=>`<div><small>${key==='test'?icon('lock'):''}${key.charAt(0).toUpperCase()+key.slice(1)}</small><strong>${n(count)}</strong></div>`).join('')}</div><p class="help">Counts are by record. All questions from a record stay together. The test reservation is frozen for this dataset; it is opened only for the final evaluation.</p>${q.warnings.map(w=>notice(e(w),'warning')).join('')}<details><summary>Categories and coding instructions</summary><div>${Object.entries(q.questions).map(([name,question])=>`<div class="definition"><strong>${e(name)}</strong><p>${question.type==='noul'?'Yes / no':question.type==='score'?'Ordered levels':'Single category'} · ${Object.keys(q.label_mappings[name]).length} labels</p><div class="category-pills">${Object.keys(q.label_mappings[name]).map(label=>`<span>${e(label)}</span>`).join('')}</div>${draft.book?`<p>${e(typeof question.instructions==='string'?question.instructions:JSON.stringify(question.instructions))}</p>`:`<label class="field-label" style="margin-top:12px" for="instruction-${e(name)}">Coding instructions</label><textarea class="question-instructions" id="instruction-${e(name)}" data-instruction="${e(name)}">${e(question.instructions)}</textarea>`}</div>`).join('')}</div></details>${q.issues.length?`<details><summary>Excluded row numbers · first ${q.issues.length} shown</summary><div><div class="table-wrap"><table><thead><tr><th>Row</th><th>Reason</th></tr></thead><tbody>${q.issues.map(i=>`<tr><td>${i.row}</td><td>${e(i.reason.replaceAll('_',' '))}</td></tr>`).join('')}</tbody></table></div></div></details>`:''}${!draft.book?`<label class="check-line"><input id="taxonomy-confirmed" type="checkbox" ${draft.taxonomy_confirmed?'checked':''}><span>I have reviewed these inferred categories and their coding instructions.</span></label>`:''}</section>`;
}

export function modelFields(model, settings, advanced = false) {
  return model.settings.filter(f=>Boolean(f.advanced)===advanced).map(field=>{
    const value=settings[field.key]??field.default;
    const id='model-setting-'+field.key;
    if(field.type==='boolean')return `<div class="field"><label class="check-line" for="${id}"><input id="${id}" data-setting="${field.key}" type="checkbox" ${value?'checked':''}><span>${e(field.label)}</span></label>${field.help?`<p class="help">${e(field.help)}</p>`:''}</div>`;
    return `<div class="field"><label for="${id}">${e(field.label)}</label>${field.options?`<select id="${id}" data-setting="${field.key}">${field.options.map(option=>`<option value="${e(option)}" ${option===value?'selected':''}>${e(option)}</option>`).join('')}</select>`:`<input id="${id}" data-setting="${field.key}" type="${field.type==='text'?'text':'number'}" ${field.min!=null?`min="${field.min}"`:''} ${field.max!=null?`max="${field.max}"`:''} step="${field.type==='number'?'any':'1'}" value="${e(value)}">`}${field.help?`<p class="help">${e(field.help)}</p>`:''}</div>`;
  }).join('');
}

function settingsStep() {
  const model=getModel();
  return `<section class="panel"><h2>Set up the experiment</h2><p>Save a reproducible configuration. Training starts only when you choose to run it.</p><div class="field"><label for="experiment-name">Experiment name</label><input id="experiment-name" type="text" maxlength="160" value="${e(draft.name)}" placeholder="A name you’ll recognise later"></div><div class="field"><label for="model-module">Model module</label><select id="model-module">${context.status.models.map(m=>`<option value="${m.id}" ${m.id===draft.model_id?'selected':''}>${e(m.name)}</option>`).join('')}</select></div><div class="module-card"><div class="model-mark">${icon('cpu')}</div><div><strong>${e(model.name)}</strong><p>${e(model.description)}</p></div></div>${!model.installed?notice(`You can save the experiment now. To train, install this module once: <code>npm run setup:model -- ${e(model.id)}</code>`):''}<div class="settings-grid">${modelFields(model,draft.settings)}</div><details><summary>Advanced model settings</summary><div class="settings-grid">${modelFields(model,draft.settings,true)}</div></details><hr class="separator"><div class="field"><label for="train-share">Training share (%)</label><input id="train-share" type="number" min="50" max="95" step="0.1" value="${Math.round(draft.mapping.train_fraction*1000)/10}"><p class="help">The remainder is validation. Applied after reserving ${Math.round(draft.dataset.split_policy.test_fraction*100)}% for testing and ${Math.round(draft.dataset.split_policy.calibration_fraction*100)}% of the remainder for calibration. Counts will be recalculated when you save.</p></div><div class="field"><label for="experiment-note">Experiment objective <span class="optional">optional</span></label><textarea id="experiment-note" placeholder="What do you want to improve in this experiment?">${e(draft.note||'')}</textarea><p class="help">Saved as a note for reviewers. The confirmed columns, codebook, and settings above define what is trained.</p></div>${notice('Approval is required. Final test results must pass the acceptance rules before a candidate can be approved. No dataset upload or training run changes the active model.','success')}</section>`;
}
function bindSettings() {
  document.querySelector('#model-module').onchange=event=>{capture();draft.model_id=event.target.value;draft.settings={};render();};
}
function capture() {
  if(draft.step===1) {
    draft.mapping.inputs=[...document.querySelectorAll('[name=input-column]:checked')].map(el=>el.value);
    draft.mapping.targets=[...document.querySelectorAll('[name=target-column]:checked')].map(el=>el.value);
    for(const [key,id] of Object.entries({language_column:'language-column',group_column:'group-column',slice_column:'slice-column',review_mode:'review-mode',review_column:'review-column'}))draft.mapping[key]=document.getElementById(id)?.value||'';
    draft.mapping.review_confirmed=Boolean(document.querySelector('#review-confirmed')?.checked);
    draft.mapping.verified_values=(document.querySelector('#verified-values')?.value||'').split(',').map(x=>x.trim()).filter(Boolean);
    draft.mapping.include_unverified=Boolean(document.querySelector('#include-unverified')?.checked);
  }
  if(draft.step===2) {
    draft.mapping.instructions=Object.fromEntries([...document.querySelectorAll('[data-instruction]')].map(el=>[el.dataset.instruction,el.value]));
    draft.taxonomy_confirmed=Boolean(document.querySelector('#taxonomy-confirmed')?.checked);
  }
  if(draft.step===3) {
    draft.name=document.querySelector('#experiment-name').value;
    draft.note=document.querySelector('#experiment-note').value;
    draft.mapping.train_fraction=Number(document.querySelector('#train-share').value)/100;
    for(const field of getModel().settings) {
      const el=document.getElementById('model-setting-'+field.key);
      draft.settings[field.key]=field.type==='boolean'?el.checked:['number','integer'].includes(field.type)?Number(el.value):el.value;
    }
  }
}

function showError(message) {
  const el=document.querySelector('#wizard-error');
  el.innerHTML=`<div class="error-inline">${e(message)}</div>`;el.scrollIntoView({block:'nearest',behavior:'smooth'});
}
async function next() {
  try {
    capture();
    if(draft.step===0&&!draft.dataset)throw new Error('Choose a spreadsheet to continue.');
    if(draft.step===1) {
      draft.report=await post(`/datasets/${draft.dataset.id}/inspect`,{mapping:draft.mapping,model_id:draft.model_id});
    }
    if(draft.step===2) {
      if(!draft.book&&!draft.taxonomy_confirmed)throw new Error('Confirm the inferred categories and instructions before continuing.');
      if(Object.values(draft.report.split_counts).some(n=>n===0))throw new Error('Every data split needs eligible records. Add more reviewed examples before creating a training experiment.');
    }
    if(draft.step===3) {
      draft.mapping.objective=draft.note;
      draft.mapping.taxonomy_confirmed=draft.taxonomy_confirmed||Boolean(draft.book);
      const experiment=await post('/experiments',{name:draft.name,dataset_id:draft.dataset.id,model_id:draft.model_id,mapping:draft.mapping,settings:draft.settings});
      toast('Experiment saved. Training has not started.');location.hash='#experiment/'+experiment.id;return;
    }
    draft.step++;render();window.scrollTo({top:0,behavior:'smooth'});
  }catch(error){showError(error.message);}
}
