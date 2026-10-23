/* Reuse an explicitly named LIVE agent receipt in the UI (no new model request).
   Default: read-only display regression, including null-task and transport faults.
   --integrate: confirm that receipt in UI and execute REAL CAD; stops for visual review.
   Does not approve a view automatically. Usage: node script.js receipt.json [--integrate] */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const root = path.resolve(__dirname, '..');
const source = path.resolve(process.argv[2]);
const reuseJobIndex = process.argv.indexOf('--pending-display');
const reuseJob = reuseJobIndex >= 0 ? process.argv[reuseJobIndex + 1] : null;
const integrate = process.argv.includes('--integrate') || !!reuseJob;
const receipt = JSON.parse(fs.readFileSync(source, 'utf8'));
const sourceInput = JSON.parse(fs.readFileSync(path.join(path.dirname(source), 'input.json'), 'utf8'));
if (!receipt.runtime?.model_invoked || !['ready', 'needs_input'].includes(receipt.status)) throw new Error('Require a successful live-agent source receipt');
if (integrate && receipt.status !== 'ready') throw new Error('CAD integration requires a ready source task');
const output = path.join(root, 'results/open-ui'); fs.mkdirSync(output, {recursive: true});
const report = {schema_version:'open-ui-verification/1',status:'failed',mode:integrate ? 'recorded_live_language_to_real_ui_cad' : 'real_current_model_and_recorded_live_language_display_with_fault_injection',
  source: {path:source,sha256:crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex')},
  new_model_requests:0, new_cad_executions: integrate && !reuseJob ? 1 : 0, reused_job: reuseJob,
  checks:[], errors:[], screenshots:[]};
const check = (id, passed) => {report.checks.push({id,status:passed?'passed':'failed'});if(!passed)throw new Error(id);};
(async()=>{
  const browser = await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1500,height:1100}}); page.setDefaultTimeout(15000);
  page.on('pageerror',error=>report.errors.push(error.message));
  let response=receipt, failTransport=false;
  await page.route('**/api/interpret',route=>route.fulfill({status:failTransport?409:200,contentType:'application/json',body:JSON.stringify(failTransport?{error:'Injected transport failure'}:{operation_id:'recorded-language-result',status:'running'})}));
  await page.route('**/api/operations/recorded-language-result',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'done',result:response})}));
  if(reuseJob){
    report.mode='pending_card_regression_reusing_existing_real_cad_job';
    const actual=await page.request.get('http://127.0.0.1:8777/api/current').then(r=>r.json());
    // Recreate the pre-generation conversation state; all geometry/job reads stay real.
    await page.route('**/api/current',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...actual,pending_job_id:null})}));
    await page.route('**/api/run',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',operation_id:'existing-cad-job'})}));
    await page.route('**/api/operations/existing-cad-job',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'done',result:{status:'review_required',job_id:reuseJob}})}));
  }
  async function submit(brief) {
    await page.getByRole('textbox',{name:'描述需求或补充信息'}).fill(brief);
    await page.getByRole('button',{name:/^(整理工程需求|补充并重新整理)$/}).click();
    await page.waitForFunction(()=>![...document.querySelectorAll('button')].some(b=>b.textContent.includes('正在整理')));
  }
  async function shot(name){const p=path.join(output,name);await page.screenshot({path:p,fullPage:true});report.screenshots.push(p);}
  try {
    await page.goto('http://127.0.0.1:8777/',{waitUntil:'domcontentloaded'});
    await page.getByText('真实 STL · 可交互',{exact:true}).waitFor();
    const before=await page.evaluate(()=>fetch('/api/current').then(r=>r.json()));
    check('real_previous_model_is_loaded',before.status==='ready' && !!before.result.mapping);
    await page.getByRole('button',{name:'新建零件',exact:true}).click();
    await submit(sourceInput.brief);
    await page.waitForFunction(()=>document.querySelector('.requirements-panel .task-summary h3')?.textContent?.includes('法兰'));
    check('flange_request_card_keeps_its_own_identity',(await page.locator('.requirements-panel .task-summary h3').innerText()).includes('法兰'));
    check('previous_model_is_explicitly_separate',(await page.locator('.model-context-label').innerText()).includes('上一已发布模型'));
    if(integrate){
      const button=page.getByRole('button',{name:'确认需求并生成',exact:true}); await button.waitFor();
      check('real_ready_parameters_enable_generate',await button.isEnabled());
      check('feature_steps_visible',await page.locator('.feature-steps li').count()===receipt.task.features.length);
      const countParam=Object.entries(receipt.task.parameters).find(([,p])=>p.unit==='count');
      check('count_is_displayed_as_count',!!countParam && (await page.locator(`button[title="${countParam[0]}"]`).innerText()).includes('个'));
      await button.click(); await page.locator('.review-card').waitFor({timeout:180000});
      const current=await page.evaluate(()=>fetch('/api/current').then(r=>r.json()));
      const pendingId=reuseJob || current.pending_job_id;
      const job=await page.evaluate(id=>fetch(`/api/job/${id}`).then(r=>r.json()),pendingId);
      check('real_v2_flange_cad_passed',job.state.task.schema_version==='engineering-task/2' && job.state.task.family==='flange' && job.result.checks.every(c=>c.status==='passed'));
      check('candidate_waits_for_visual_review',job.status==='review_required' && current.state.task_id===before.state.task_id);
      check('pending_requirement_card_matches_generated_task',(await page.locator('.requirements-panel .task-summary h3').innerText()).includes('法兰') && await page.locator('.draft-task-note').count()===0 && await page.locator('.feature-steps li').count()===receipt.task.features.length);
      report.job_id=pendingId;report.task_id=job.state.task_id;report.cad_checks=job.result.checks.length;
      report.native_iso=job.assets.find(a=>a.kind==='preview_isometric');
      await shot(reuseJob?'flange-pending-card-fixed.png':'flange-pending.png'); report.status='review_required';
    }else{
      check('unknown_dimensions_block_generation',!(await page.getByRole('button',{name:'确认需求并生成',exact:true}).isEnabled()));
      check('old_box_dimensions_not_reused',await page.locator('.requirements-panel button[title="wall"]').count()===0);
      await shot('flange-needs-input.png');
      // Exercise the exact original bug boundary with the same live candidate but no task.
      response={...receipt,task:null};
      await submit('请继续明确上述法兰需求。');
      await page.locator('.draft-task-note').waitFor();
      check('null_task_preserves_candidate_not_old_box',(await page.locator('.requirements-panel .task-summary h3').innerText()).includes('法兰') && (await page.locator('.draft-task-note').innerText()).includes('不沿用上一模型'));
      failTransport=true;
      await submit('补充信息提交失败的回归检查。');
      await page.getByRole('alert').waitFor();
      check('failed_interpretation_never_reuses_old_task',(await page.locator('.requirements-panel .task-summary h3').innerText()).includes('本次需求尚未形成') && !(await page.getByRole('button',{name:'确认需求并生成',exact:true}).isEnabled()));
      await shot('failed-request-separate.png');
      const after=await page.evaluate(()=>fetch('/api/current').then(r=>r.json()));
      check('read_only_regression_preserves_publication',after.state.task_id===before.state.task_id && after.state.semantic_hash===before.state.semantic_hash && !after.pending_job_id);
      report.status='passed';
    }
    check('no_browser_exceptions',report.errors.length===0);
  } catch(error){report.error=error.stack;report.page_text=await page.locator('body').innerText().catch(()=>null);report.status='failed';}
  finally{await browser.close();fs.writeFileSync(path.join(output,reuseJob?'pending-display-report.json':integrate?'integration-report.json':'regression-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks,error:report.error,job_id:report.job_id}));process.exitCode=['passed','review_required'].includes(report.status)?0:1;}
})();
