/* Real browser upload -> HTTP -> CLI image understanding, once. Follow-up display
   checks replay that live response and never submit CAD or extra model requests. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'results/image-chat-ui'); fs.mkdirSync(output, {recursive:true});
const fixture = path.join(root,'results/image-chat-verification/reference-01.png');
const expected = JSON.parse(fs.readFileSync(path.join(root,'results/image-chat-verification/expected.json'),'utf8'));
const report={schema_version:'image-chat-ui-verification/1',status:'failed',checks:[],errors:[],screenshots:[],live_model_requests:0,new_cad_executions:0};
const check=(id,ok)=>{report.checks.push({id,status:ok?'passed':'failed'});if(!ok)throw new Error(id);};
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1500,height:1050}});page.setDefaultTimeout(15000);
  page.on('pageerror',error=>report.errors.push(error.message));
  let modelResult=null, operationId=null, uploadCount=0;
  const posts=[];
  page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/api/interpret'))posts.push(request.postDataJSON());});
  page.on('response',async response=>{
    if(response.url().endsWith('/api/reference-images')&&response.request().method()==='POST')uploadCount++;
    if(response.url().includes('/api/operations/')){
      const value=await response.json().catch(()=>null);
      if(value?.status==='done'&&value.result?.runtime?.model_invoked)modelResult=value.result;
    }
  });
  const shot=async name=>{const target=path.join(output,name);await page.screenshot({path:target,fullPage:true});report.screenshots.push(target);};
  const upload=async()=>{
    const promise=page.waitForResponse(r=>r.url().endsWith('/api/reference-images')&&r.request().method()==='POST');
    await page.getByLabel('添加参考图片',{exact:true}).setInputFiles(fixture);
    const response=await promise;check('real_image_upload_http_ok',response.ok());
    const image=await response.json();await page.locator('.c-attachment-list .c-attachment').first().waitFor();return image;
  };
  try{
    await page.goto('http://127.0.0.1:8777/',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>document.body.innerText.includes('本机服务已连接'));
    const before=await page.evaluate(()=>fetch('/api/current').then(r=>r.json()));
    await page.getByRole('button',{name:'新对话',exact:true}).click();
    const input=page.getByLabel('描述需求或补充信息',{exact:true});
    const send=page.getByRole('button',{name:'发送需求',exact:true});
    const image=await upload();report.reference_image=image;
    check('only_registered_reference_url_exposed',image.url===`/api/reference-images/${image.id}`&&!('path'in image));
    await page.locator('.c-attachment-preview').click();await page.locator('.c-image-dialog[open]').waitFor();
    check('reference_can_be_enlarged',await page.locator('.c-image-dialog img').evaluate(img=>img.complete&&img.naturalWidth>0));
    await page.getByRole('button',{name:'关闭图片预览',exact:true}).click();
    for(const type of ['paste','drop']){
      const response=page.waitForResponse(r=>r.url().endsWith('/api/reference-images')&&r.request().method()==='POST');
      await page.evaluate(async({url,type})=>{
        const blob=await fetch(url).then(r=>r.blob());const data=new DataTransfer();
        data.items.add(new File([blob],`${type}.png`,{type:'image/png'}));
        if(type==='paste')document.querySelector('textarea[aria-label="描述需求或补充信息"]').dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
        else document.querySelector('.c-chat').dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}));
      },{url:image.url,type});
      check(`${type}_uses_real_upload_and_deduplicates`,(await response).ok());
      await page.waitForFunction(()=>document.querySelectorAll('.c-attachment-list .c-attachment').length===1);
    }
    await input.fill('输入法测试');await input.dispatchEvent('compositionstart');await input.press('Enter');await input.dispatchEvent('compositionend');
    check('ime_enter_does_not_send',posts.length===0);
    await input.fill('第一行');await input.press('Shift+Enter');await input.pressSequentially('第二行');
    check('shift_enter_inserts_newline',((await input.inputValue()).includes('\n'))&&posts.length===0);
    await input.fill(expected.brief);await shot('reference-composer.png');
    const response=page.waitForResponse(r=>r.url().endsWith('/api/interpret')&&r.request().method()==='POST');
    await input.press('Enter');const accepted=await response;
    check('text_and_image_sent_to_real_interpret',accepted.ok()&&posts[0].image_ids.length===1&&posts[0].image_ids[0]===image.id);
    operationId=(await accepted.json()).operation_id;report.operation_id=operationId;report.live_model_requests=1;
    check('busy_disables_duplicate_send',!(await send.isEnabled()));
    console.log(JSON.stringify({stage:'waiting_for_real_image_model',operation_id:operationId,image_id:image.id}));
    const deadline=Date.now()+145000;
    while(!modelResult&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,250));
    if(!modelResult)throw new Error('No completed real model receipt received');
    fs.writeFileSync(path.join(output,'model-result.json'),JSON.stringify(modelResult,null,2));
    report.agent_evidence=modelResult.evidence_dir;
    check('real_model_received_the_image',modelResult.runtime.model_invoked&&modelResult.runtime.image_count===1&&modelResult.runtime.reference_images[0].sha256===image.sha256);
    check('missing_dimensions_stay_unconfirmed',modelResult.status==='needs_input'&&Object.values(modelResult.task?.parameters||{}).every(p=>!p.confirmed));
    const visible=JSON.stringify({goal:modelResult.candidate?.goal,questions:modelResult.questions,parameters:modelResult.candidate?.parameters});
    check('recognizes_clipped_corner_outline',/削角|倒角|斜角|五边|切角/.test(visible));
    check('recognizes_three_vertical_round_holes',/(三|3).{0,18}(圆孔|孔)|圆孔.{0,18}(三|3)/.test(visible)&&/竖|纵|上下/.test(visible));
    check('recognizes_rectangular_window',/(矩形|长方形).{0,16}(孔|窗|开口)/.test(visible));
    await page.locator('.c-assistant .c-message-content').first().waitFor();
    check('chat_retains_user_image_and_answer',await page.locator('.c-user .c-message-images img').count()===1&&await page.locator('.c-assistant').count()>=1);
    const saved=await page.evaluate(()=>localStorage.getItem('mechanical-design-chat-v1'));
    check('conversation_persists_metadata_without_base64',!!saved&&saved.includes(image.id)&&!saved.includes('base64,'));
    await shot('image-understood.png');
    await page.reload({waitUntil:'domcontentloaded'});await page.locator('.c-user .c-message-images img').waitFor();
    check('reload_restores_reference_context_and_history',await page.locator('.c-reference-context summary').count()===1&&await page.locator('.c-assistant').count()>=1);
    // Reuse the already observed result for UI-only clarification. No extra model call.
    let clarification=null;
    await page.route('**/api/interpret',route=>{clarification=route.request().postDataJSON();return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',operation_id:'image-ui-replay'})});});
    await page.route('**/api/operations/image-ui-replay',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'done',result:modelResult})}));
    await input.fill('厚度稍后补充，请继续保留参考图。');await send.click();
    await page.waitForFunction(()=>document.querySelectorAll('.c-assistant').length>=2);
    check('followup_carries_images_and_prior_conversation',clarification.image_ids.includes(image.id)&&clarification.conversation.some(m=>m.role==='assistant')&&clarification.conversation.some(m=>m.role==='user'));
    if(!(await page.getByRole('tab',{name:'三维模型',exact:true}).isVisible()))await page.locator('.c-engineering-toggle').click();
    await page.getByRole('tab',{name:'三维模型',exact:true}).click();await page.getByText('真实 STL · 可交互',{exact:true}).waitFor();
    check('existing_real_model_still_renders',await page.locator('canvas').evaluate(canvas=>canvas.clientWidth>100&&canvas.clientHeight>100));
    await page.getByRole('tab',{name:'工程需求',exact:true}).click();
    check('unconfirmed_image_request_cannot_generate',!(await page.getByRole('button',{name:'确认需求并生成',exact:true}).isEnabled()));
    await page.getByRole('button',{name:'收起工程面板',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    const box=await input.boundingBox();
    check('mobile_chat_and_composer_fit_viewport',!!box&&box.y>=0&&box.y+box.height<=844&&await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await shot('mobile-chat.png');
    await page.getByRole('button',{name:'新对话',exact:true}).click();
    check('new_conversation_clears_context_only',await page.locator('.c-reference-context').count()===0&&await page.locator('.c-message').count()===0);
    await upload();check('image_only_message_is_sendable',await send.isEnabled());
    await send.click();await page.waitForFunction(()=>document.querySelectorAll('.c-assistant').length>=1);
    check('image_only_message_keeps_image_id',clarification.image_ids.includes(image.id));
    const after=await page.evaluate(()=>fetch('/api/current').then(r=>r.json()));
    check('chat_does_not_change_published_cad',before.state.task_id===after.state.task_id&&before.state.semantic_hash===after.state.semantic_hash&&!after.pending_job_id);
    check('no_browser_exceptions',report.errors.length===0);
    report.upload_requests=uploadCount;report.status='passed';
  }catch(error){report.error=error.stack;report.page_text=await page.locator('body').innerText().catch(()=>null);await shot('failure.png').catch(()=>{});}
  finally{await browser.close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks,error:report.error,agent_evidence:report.agent_evidence}));process.exitCode=report.status==='passed'?0:1;}
})();
