/* Scoped browser verification. One live image request; connection test reuses an
   explicitly named real operation so UI testing does not issue another paid call. */
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'results/model-settings-verification');
fs.mkdirSync(output, {recursive: true});
const report = {status:'failed',checks:[],errors:[],new_model_requests:1,new_cad_executions:0,connection_operation:process.argv[2]};
function check(id, ok) {report.checks.push({id,passed:!!ok});if(!ok) throw new Error(id);}
(async()=>{
  const browser = await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1500,height:1050}});page.setDefaultTimeout(15000);
  page.on('pageerror', e=>report.errors.push(e.message));
  const origin = 'http://127.0.0.1:8777';
  const before = await page.request.get(origin+'/api/current').then(r=>r.json());
  const original = await page.request.get(origin+'/api/settings').then(r=>r.json());
  check('deepseek_is_default_and_key_configured', original.active_profile_id==='deepseek' && original.profiles.find(p=>p.id==='deepseek').has_api_key);
  check('settings_get_never_exposes_credentials',!JSON.stringify(original).includes('api_key_encrypted') && !original.profiles.some(p=>'api_key' in p));
  let modelResult;
  try {
    await page.goto(origin,{waitUntil:'domcontentloaded'});
    check('program_brand', await page.title()==='codex的构物');
    await page.getByRole('button',{name:'模型设置',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'模型设置'});await dialog.waitFor();
    await page.locator('#settings-model').waitFor();
    check('deepseek_default_model', await page.locator('#settings-model').inputValue()==='deepseek-flash');
    check('saved_key_is_write_only', await page.locator('#settings-api-key').inputValue()==='' && await dialog.getByText('已保存',{exact:true}).count()===1);
    await page.route('**/api/settings/test', route=>route.fulfill({contentType:'application/json',body:JSON.stringify({operation_id:report.connection_operation,status:'running'})}));
    await dialog.getByRole('button',{name:'测试连接',exact:true}).click();
    await dialog.getByText(/连接成功/).waitFor();
    check('connection_feedback_uses_observed_live_result',await dialog.getByText(/未测试图片识别/).count()===1);
    await page.unroute('**/api/settings/test');
    await dialog.getByRole('button',{name:/Codex CLI/}).click();
    await dialog.getByRole('button',{name:'保存并应用'}).click();
    await dialog.getByText(/已保存。下一次/).waitFor();
    check('switch_to_cli_saved', (await page.request.get(origin+'/api/settings').then(r=>r.json())).active_profile_id==='codex');
    await dialog.getByRole('button',{name:/DeepSeek/}).click();
    await dialog.getByRole('button',{name:'保存并应用'}).click();
    await dialog.getByText(/已保存。下一次/).waitFor();
    check('blank_key_preserves_deepseek_credential',(await page.request.get(origin+'/api/settings').then(r=>r.json())).profiles.find(p=>p.id==='deepseek').has_api_key);
    await dialog.getByRole('button',{name:'＋ 添加自定义 API'}).click();
    await dialog.getByLabel('配置名称',{exact:true}).fill('设置验证临时接口');
    await page.locator('#settings-base-url').fill('https://example.com/v1');
    await page.locator('#settings-model').fill('example-json-model');
    await page.locator('#settings-api-key').fill('settings-ui-test-only');
    check('unsaved_connection_test_disabled',!(await dialog.getByRole('button',{name:'测试连接',exact:true}).isEnabled()));
    await dialog.getByRole('button',{name:'保存并应用'}).click();
    await dialog.getByText(/已保存。下一次/).waitFor();
    const custom = await page.request.get(origin+'/api/settings').then(r=>r.json());
    check('custom_model_endpoint_and_key_saved', custom.profiles.find(p=>p.id===custom.active_profile_id).model==='example-json-model' && custom.profiles.find(p=>p.id===custom.active_profile_id).has_api_key);
    check('password_cleared_after_save',await page.locator('#settings-api-key').inputValue()==='');
    await dialog.getByRole('button',{name:'删除已存密钥',exact:true}).click();
    await dialog.getByRole('button',{name:'保存并应用'}).click();await dialog.getByText(/已保存。下一次/).waitFor();
    check('explicit_clear_only_affects_selected_profile',!(await page.request.get(origin+'/api/settings').then(r=>r.json())).profiles.find(p=>p.id===custom.active_profile_id).has_api_key);
    await dialog.getByRole('button',{name:'删除此配置'}).click();
    await dialog.getByRole('button',{name:/DeepSeek/}).click();
    await dialog.getByRole('button',{name:'保存并应用'}).click();await dialog.getByText(/已保存。下一次/).waitFor();
    await page.screenshot({path:path.join(output,'settings-desktop.png')});
    await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
    check('escape_closes_and_restores_focus',await page.getByRole('button',{name:'模型设置',exact:true}).evaluate(el=>el===document.activeElement));
    await page.getByRole('button',{name:'新对话',exact:true}).click();
    const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/reference-images')&&r.request().method()==='POST');
    await page.getByLabel('添加参考图片',{exact:true}).setInputFiles(path.join(output,'flange-reference.png'));
    const reference=await (await uploaded).json();
    await page.locator('.c-attachment-list .c-attachment').first().waitFor();
    const brief='参考图仅表达结构。做一个圆形平法兰，外径100毫米、厚度10毫米，中心贯穿孔直径40毫米，4个直径9毫米的螺栓贯穿孔均布在75毫米分度圆上，第一孔位于X正方向。不带颈，不加其他结构，只做几何评审。';
    await page.getByLabel('描述需求或补充信息',{exact:true}).fill(brief);
    const accepted=page.waitForResponse(r=>r.url().endsWith('/api/interpret')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'发送需求',exact:true}).click();
    const response=await accepted;check('live_image_request_accepted',response.ok());const receipt=await response.json();
    const deadline=Date.now()+150000;
    while(Date.now()<deadline){
      const operation=await page.request.get(origin+'/api/operations/'+receipt.operation_id).then(r=>r.json());
      if(operation.status==='failed')throw new Error(operation.error);
      if(operation.status==='done'){modelResult=operation.result;break;}
      await new Promise(resolve=>setTimeout(resolve,300));
    }
    if(!modelResult)throw new Error('Live model request did not complete');
    fs.writeFileSync(path.join(output,'live-model-result.json'),JSON.stringify(modelResult,null,2));
    report.agent_evidence=modelResult.evidence_dir;
    check('actual_deepseek_model_used',modelResult.runtime.provider==='openai_compatible'&&modelResult.runtime.model==='deepseek-flash'&&modelResult.runtime.model_invoked);
    check('reference_snapshot_attached',modelResult.runtime.image_count===1&&modelResult.runtime.reference_images[0].sha256===reference.sha256);
    check('complete_flange_passes_local_rules',modelResult.status==='ready'&&modelResult.task?.family==='flange');
    check('three_features_planned',modelResult.task?.features?.length===3);
    await page.waitForFunction(()=>document.body.innerText.includes('圆形平法兰')||document.body.innerText.includes('确认需求'));
    const storage=await page.evaluate(()=>JSON.stringify({...localStorage}));
    check('browser_persistence_contains_no_test_credential',!storage.includes('settings-ui-test-only')&&!storage.includes('api_key'));
    await page.screenshot({path:path.join(output,'deepseek-reference-result.png')});
    await page.getByRole('button',{name:'模型设置',exact:true}).click();await page.locator('#settings-model').waitFor();
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'settings-mobile.png')});
    check('settings_mobile_fits_width',await page.evaluate(()=>document.querySelector('.settings-dialog').getBoundingClientRect().right<=innerWidth&&document.querySelector('.settings-dialog').getBoundingClientRect().left>=0));
    const after=await page.request.get(origin+'/api/current').then(r=>r.json());
    check('existing_cad_baseline_preserved',JSON.stringify(before.state)===JSON.stringify(after.state)&&before.pending_job_id===after.pending_job_id);
    check('no_browser_errors',report.errors.length===0);
    report.status='passed';
  } catch(error){report.errors.push(error.message);await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});}
  finally{
    // Restore the nonsecret original settings. Blank keys preserve DPAPI credentials.
    await page.request.post(origin+'/api/settings',{data:{active_profile_id:original.active_profile_id,profiles:original.profiles}}).catch(()=>{});
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));await browser.close();
  }
  console.log(JSON.stringify(report));if(report.status!=='passed')process.exitCode=1;
})();
