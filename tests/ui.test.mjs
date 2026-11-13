import test from 'node:test';
import assert from 'node:assert/strict';
import {modelFields} from '../static/js/wizard.js';
import {overview,experimentRow} from '../static/js/dashboard.js';
import {escape} from '../static/js/api.js';

test('a new module supplies its own settings without frontend registration', () => {
  const model={settings:[
    {key:'custom_depth',label:'Tree depth',type:'integer',default:12,min:1,max:50},
    {key:'backend',label:'Backend',type:'select',default:'cpu',options:['cpu','accelerator']},
    {key:'strategy',label:'Strategy',type:'text',default:'balanced',advanced:true},
  ]};
  const visible=modelFields(model,{custom_depth:9});
  assert.match(visible,/Tree depth/);
  assert.match(visible,/value="9"/);
  assert.match(visible,/accelerator/);
  assert.doesNotMatch(visible,/Strategy/);
  assert.match(modelFields(model,{},true),/Strategy/);
});

test('dataset and experiment strings cannot inject markup into dashboard rows', () => {
  const html=experimentRow({id:'safe-id',name:'<img src=x onerror=alert(1)>',dataset_name:'<script>bad</script>',
    model_id:'custom',status:'draft',created_at:'2026-01-01'});
  assert.doesNotMatch(html,/<img|<script>/);
  assert.match(html,/&lt;img/);
  assert.equal(escape('" onfocus="bad'), '&quot; onfocus=&quot;bad');
});

test('empty workspace reports actual counts and no invented model results', () => {
  const html=overview({datasets:[],experiments:[],status:{models:[],active:{}}});
  assert.match(html,/0 records in your workspace/);
  assert.match(html,/Your first improvement starts here/);
  assert.doesNotMatch(html,/\d+\.\d+%/);
});
