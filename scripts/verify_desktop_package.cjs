/* Packaged HTTP/UI resources only. No model request or CAD write is made. */
const fs=require('node:fs');const path=require('node:path');const crypto=require('node:crypto');
const {chromium}=require(path.resolve(__dirname,'../ui/node_modules/playwright'));
const output=path.resolve(__dirname,'../results/model-settings-verification');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1500,height:1050}});page.setDefaultTimeout(15000);
  const report={status:'failed',checks:[],errors:[],model_requests:0,cad_executions:0};
  page.on('pageerror',error=>report.errors.push(error.message));
  function check(id,ok){report.checks.push({id,passed:!!ok});if(!ok)throw new Error(id);}
  try{
    await page.goto('http://127.0.0.1:8777',{waitUntil:'domcontentloaded'});
    await page.getByText('真实 STL · 可交互',{exact:true}).waitFor();
    check('packaged_ui_title',await page.title()==='codex的构物');
    const state=await page.request.get('http://127.0.0.1:8777/api/current').then(r=>r.json());
    check('published_flange_retained',state.status==='ready'&&state.state.task_id==='task-198b1c300ce2465a935b4746fd0351af'&&state.state.revision===1&&!state.pending_job_id);
    const mesh=state.assets.find(a=>a.filename.toLowerCase().endsWith('.stl'));
    const binary=await page.request.get('http://127.0.0.1:8777'+mesh.url).then(r=>r.body());
    check('original_mesh_download_integrity',binary.length===mesh.size_bytes&&crypto.createHash('sha256').update(binary).digest('hex')===mesh.sha256);
    check('webgl_canvas_present',await page.locator('canvas').count()===1);
    await page.getByRole('button',{name:'模型设置',exact:true}).click();await page.locator('#settings-model').waitFor();
    check('packaged_settings_work',await page.locator('#settings-model').inputValue()==='deepseek-flash'&&await page.locator('#settings-api-key').inputValue()==='');
    await page.screenshot({path:path.join(output,'packaged-program.png')});
    check('no_browser_errors',report.errors.length===0);report.status='passed';
  }catch(error){report.errors.push(error.message);}
  finally{fs.writeFileSync(path.join(output,'packaged-ui-report.json'),JSON.stringify(report,null,2));await browser.close();}
  console.log(JSON.stringify(report));if(report.status!=='passed')process.exitCode=1;
})();
