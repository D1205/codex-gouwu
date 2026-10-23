/* UI-only replay of the already observed live image response, after wording changes.
   No model/CAD calls. Also checks the actual outgoing per-message history bound. */
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {chromium}=require(path.resolve(__dirname,'../ui/node_modules/playwright'));
const root=path.resolve(__dirname,'..');
const output=path.join(root,'results/image-chat-ui');
const original=JSON.parse(fs.readFileSync(path.join(output,'model-result.json'),'utf8'));
const displayPath=path.join(output,'display-result.json');
const display=JSON.parse(fs.readFileSync(displayPath,'utf8'));
const earlier=JSON.parse(fs.readFileSync(path.join(output,'report.json'),'utf8'));
const report={schema_version:'image-chat-display-verification/1',status:'failed',mode:'local_wording_replay_of_live_response',new_model_requests:0,new_cad_executions:0,checks:[],errors:[],source_sha256:crypto.createHash('sha256').update(fs.readFileSync(displayPath)).digest('hex')};
const check=(id,ok)=>{report.checks.push({id,status:ok?'passed':'failed'});if(!ok)throw new Error(id);};
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1500,height:1050}});page.setDefaultTimeout(15000);
 page.on('pageerror',e=>report.errors.push(e.message));
 let posted=null;
 await page.route('**/api/interpret',route=>{posted=route.request().postDataJSON();return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',operation_id:'wording-replay'})});});
 await page.route('**/api/operations/wording-replay',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'done',result:display})}));
 const session={version:1,mode:'create',input:'',brief:'请根据参考图辨识零件的外形、开孔布局；缺少的尺寸和结构请向我追问。',
  messages:[{id:'reference-user',role:'user',text:'请参考图片辨识外形与开孔。',images:[earlier.reference_image]},{id:'reference-assistant',role:'assistant',text:display.questions.map(q=>`- ${q}`).join('\n')}],
  references:[earlier.reference_image],attachments:[],draft:display};
 await page.addInitScript(session=>{if(!localStorage.getItem('mechanical-design-chat-v1'))localStorage.setItem('mechanical-design-chat-v1',JSON.stringify(session));},session);
 try{
  check('wording_replay_preserves_parameter_values_and_confirmation',JSON.stringify(display.task.parameters)===JSON.stringify(original.task.parameters));
  await page.goto('http://127.0.0.1:8777/',{waitUntil:'domcontentloaded'});
  await page.locator('.c-assistant').waitFor();
  const body=await page.locator('.c-assistant').innerText();
  check('questions_are_concise_and_have_no_parameter_codes',display.questions.length<=8&&!/[a-z]+_[a-z]+/.test(body));
  await page.getByRole('tab',{name:'工程需求',exact:true}).click();
  const labels=await page.locator('.parameter-pick > span:first-child').allTextContents();
  check('dynamic_image_parameters_have_chinese_labels',labels.length===Object.keys(display.task.parameters).length&&labels.every(label=>/[\u4e00-\u9fff]/.test(label)&&!/[a-z]+_[a-z]+/.test(label)));
  check('wording_does_not_enable_unconfirmed_generation',!(await page.getByRole('button',{name:'确认需求并生成',exact:true}).isEnabled()));
  report.screenshot=path.join(output,'image-chat-refined.png');await page.screenshot({path:report.screenshot,fullPage:true});
  // A long assistant turn is display context, never added to authoritative brief.
  const long={...session,messages:[...session.messages,{id:'long-context',role:'assistant',text:'上下文'.repeat(3500)}]};
  await page.evaluate(value=>localStorage.setItem('mechanical-design-chat-v1',JSON.stringify(value)),long);
  await page.reload({waitUntil:'domcontentloaded'});
  const input=page.getByLabel('描述需求或补充信息',{exact:true});await input.fill('尺寸稍后补充。');await page.getByRole('button',{name:'发送需求',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.c-assistant').length>=3);
  check('long_history_obeys_backend_bounds',posted.conversation.length<=80&&posted.conversation.every(m=>m.text.length<=10000)&&posted.conversation.reduce((n,m)=>n+m.text.length,0)<=40000);
  check('assistant_context_not_promoted_to_user_brief',!posted.brief.includes('上下文'.repeat(20)));
  check('no_browser_exceptions',report.errors.length===0);report.status='passed';
 }catch(e){report.error=e.stack;}
 finally{await browser.close();fs.writeFileSync(path.join(output,'display-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.status==='passed'?0:1;}
})();
