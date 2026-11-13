import {api, escape as e} from './api.js';
import {hydrateIcons} from './icons.js';
import {overview,experimentsView,bindExperiments,datasetsView,modelsView} from './dashboard.js';
import {beginWizard} from './wizard.js';
import {experimentView,bindExperiment,resetExperiment} from './experiment.js';
import {settingsView,bindSettings,guideView} from './settings.js';
import {notice} from './ui.js';

let state, poll, generation=0, lastDetail;
const titles={overview:'Overview',experiments:'Experiments',datasets:'Datasets',models:'Model registry',settings:'Settings',guide:'Getting started',new:'New experiment',experiment:'Experiment'};
async function load(){const [status,datasets,experiments]=await Promise.all([api('/status'),api('/datasets'),api('/experiments')]);return {status,datasets,experiments};}
async function render(refresh=true){
  clearTimeout(poll);
  const token=++generation;
  const [route='overview',id]=(location.hash.slice(1)||'overview').split('/');
  try {
    if(refresh||!state)state=await load();
    if(token!==generation)return;
    const main=document.querySelector('#main');
    document.querySelector('#page-name').textContent=titles[route]||'Overview';
    document.querySelector('#machine').textContent=state.status.platform==='Darwin'?'Apple Silicon / Mac':state.status.platform;
    document.querySelector('#experiment-count').textContent=state.experiments.length;
    document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===(['new','experiment'].includes(route)?'experiments':route)));
    document.querySelector('.sidebar').classList.remove('open');
    if(route==='new'){beginWizard(state,id);return;}
    if(route==='experiment'){
      const item=state.experiments.find(x=>x.id===id)||await api('/experiments/'+encodeURIComponent(id));
      if(lastDetail!==id){resetExperiment();lastDetail=id;}
      main.innerHTML=experimentView(item,state.status);
      await bindExperiment(item,state.status,render);
      if(item.status==='running')poll=setTimeout(()=>render(),2500);
    } else {
      lastDetail=null;
      main.innerHTML=({overview,experiments:experimentsView,datasets:datasetsView,models:modelsView,settings:settingsView,guide:guideView}[route]||overview)(state);
      if(route==='experiments')bindExperiments(state);
      if(route==='settings')bindSettings();
    }
  }catch(error){document.querySelector('#main').innerHTML=notice(`<strong>Could not open the workspace.</strong><br>${e(error.message)}<br>Check that the local server is running, then refresh the page.`,'error');}
}
document.querySelector('#menu').onclick=()=>document.querySelector('.sidebar').classList.toggle('open');
window.addEventListener('hashchange',()=>{window.scrollTo(0,0);render();});
hydrateIcons();
render();
