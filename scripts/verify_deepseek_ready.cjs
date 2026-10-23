/* Follow-up only: live image-to-ready path after the Chinese-axis evidence fix.
   Earlier settings checks are retained in model-settings-verification/report.json. */
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require(path.resolve(__dirname,'../ui/node_modules/playwright'));
const root=path.resolve(__dirname,'..');const output=path.join(root,'results/model-settings-verification');
const report={status:'failed',checks:[],errors:[],new_model_requests:1,new_cad_executions:0};
function check(id,ok){report.checks.push({id,passed:!!ok});if(!ok)throw new Error(id);}
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1500,height:1050}});page.setDefaultTimeout(15000);
  page.on('pageerror',e=>report.errors.push(e.message));const origin='http://127.0.0.1:8777';
  const before=await page.request.get(origin+'/api/current').then(r=>r.json());
  try{
    await page.goto(origin,{waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'新对话',exact:true}).click();
    const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/reference-images')&&r.request().method()==='POST');
    await page.getByLabel('添加参考图片',{exact:true}).setInputFiles(path.join(output,'flange-reference.png'));
    const reference=await(await uploaded).json();await page.locator('.c-attachment-list .c-attachment').first().waitFor();
    const brief='参考图仅表达结构。做一个圆形平法兰，外径100毫米、厚度10毫米，中心贯穿孔直径40毫米，4个直径9毫米的螺栓贯穿孔均布在75毫米分度圆上，第一孔位于X正方向。不带颈，不加其他结构，只做几何评审。';
    await page.getByLabel('描述需求或补充信息',{exact:true}).fill(brief);
    const accepted=page.waitForResponse(r=>r.url().endsWith('/api/interpret')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'发送需求',exact:true}).click();const response=await accepted;
    check('real_interpret_accepted',response.ok());const receipt=await response.json();let result;
    const deadline=Date.now()+150000;
    while(Date.now()<deadline){
      const op=await page.request.get(origin+'/api/operations/'+receipt.operation_id).then(r=>r.json());
      if(op.status==='failed')throw new Error(op.error);if(op.status==='done'){result=op.result;break;}
      await new Promise(resolve=>setTimeout(resolve,300));
    }
    if(!result)throw new Error('No completed live response');
    report.agent_evidence=result.evidence_dir;
    fs.writeFileSync(path.join(output,'ready-model-result.json'),JSON.stringify(result,null,2));
    check('deepseek_flash_really_invoked',result.runtime.provider==='openai_compatible'&&result.runtime.model==='deepseek-flash'&&result.runtime.model_invoked);
    check('real_image_attached',result.runtime.image_count===1&&result.runtime.reference_images[0].sha256===reference.sha256);
    check('complete_flange_passes_local_rules',result.status==='ready'&&result.task?.family==='flange');
    check('three_features_planned',result.task.features.length===3);
    check('textual_axis_confirmed',result.task.parameters.first_hole_angle.confirmed&&result.task.parameters.first_hole_angle.value===0);
    check('all_parameters_traceably_confirmed',Object.values(result.task.parameters).every(p=>p.confirmed));
    await page.waitForFunction(()=>document.body.innerText.includes('已整理'));
    const storage=await page.evaluate(()=>JSON.stringify({...localStorage}));
    check('no_credentials_in_browser_storage',!storage.includes('api_key')&&!storage.includes('settings-ui-test-only'));
    await page.screenshot({path:path.join(output,'deepseek-ready-desktop.png')});
    await page.getByRole('button',{name:'模型设置',exact:true}).click();await page.locator('#settings-model').waitFor();
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'settings-mobile.png')});
    check('settings_mobile_fits_width',await page.evaluate(()=>{const box=document.querySelector('.settings-dialog').getBoundingClientRect();return box.right<=innerWidth&&box.left>=0;}));
    check('configured_key_stays_write_only',await page.locator('#settings-api-key').inputValue()==='');
    const after=await page.request.get(origin+'/api/current').then(r=>r.json());
    check('published_baseline_unchanged',JSON.stringify(before.state)===JSON.stringify(after.state)&&before.pending_job_id===after.pending_job_id);
    check('no_browser_errors',report.errors.length===0);report.status='passed';
  }catch(error){report.errors.push(error.message);await page.screenshot({path:path.join(output,'ready-failure.png')}).catch(()=>{});}
  finally{fs.writeFileSync(path.join(output,'ready-report.json'),JSON.stringify(report,null,2));await browser.close();}
  console.log(JSON.stringify(report));if(report.status!=='passed')process.exitCode=1;
})();
