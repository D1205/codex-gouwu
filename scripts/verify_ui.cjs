/* Browser smoke against the real local service; model/CAD calls only in --workflow mode. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'results', 'ui-verification');
fs.mkdirSync(output, { recursive: true });
const report = { schema_version: 'ui-verification/1', status: 'failed', checks: [], errors: [], screenshots: [] };
const check = (id, passed) => { report.checks.push({ id, status: passed ? 'passed' : 'failed' }); if (!passed) throw new Error(id); };
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 }, deviceScaleFactor: 1 });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:8777/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('.header-status')?.textContent?.includes('本机服务已连接'));
    await page.getByText('真实 STL · 可交互', { exact: true }).waitFor();
    const current = await page.evaluate(() => fetch('/api/current').then(r => r.json()));
    check('real_current_revision_loaded', current.status === 'ready' && current.state.revision >= 1);
    check('real_stl_and_mm_mapping', current.assets.some(a => a.kind === 'stl') && current.result.mapping.units === 'mm');
    check('webgl_canvas_rendered', await page.locator('canvas').count() === 1);
    const before = path.join(output, 'workbench.png');
    await page.screenshot({ path: before, fullPage: true, timeout: 15000 });
    report.screenshots.push(before);
    if (current.state.task.family === 'plate') {
      await page.getByRole('button', { name: /贯穿孔直径/ }).click();
      check('parameter_selection_has_group_scope', (await page.locator('body').innerText()).includes('统一孔径'));
    }
    if (process.argv.includes('--workflow')) {
      await page.getByRole('button', {name:'新建零件',exact:true}).click();
      await page.getByRole('textbox', {name:'描述需求或补充信息'}).fill('做一个无盖的空心盒体，外部长80毫米、宽50毫米、高30毫米，底部和侧壁一样厚，不加其他结构，只做几何评审。');
      await page.getByRole('button', {name:'整理工程需求',exact:true}).click();
      await page.locator('.needs-input').waitFor({timeout:130000});
      check('missing_dimension_blocks_generate', !(await page.getByRole('button',{name:'确认需求并生成',exact:true}).isEnabled()));
      const missing = path.join(output,'needs-input.png');
      await page.screenshot({path:missing,fullPage:true}); report.screenshots.push(missing);
      await page.getByRole('textbox',{name:'描述需求或补充信息'}).fill('侧壁和底部厚度都用3毫米。');
      await page.getByRole('button',{name:'补充并重新整理',exact:true}).click();
      await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('确认需求并生成') && !button.disabled),null,{timeout:130000});
      check('clarification_enables_confirmed_generation', true);
      await page.getByRole('button',{name:'确认需求并生成',exact:true}).click();
      await page.locator('.review-card').waitFor({timeout:130000});
      const pending = await page.evaluate(() => fetch('/api/current').then(r=>r.json()));
      check('candidate_does_not_replace_published_model', pending.state.task_id === current.state.task_id && pending.state.revision === current.state.revision && !!pending.pending_job_id);
      report.pending_job_id = pending.pending_job_id;
      const candidate = await page.evaluate(job => fetch(`/api/job/${job}`).then(r=>r.json()),pending.pending_job_id);
      check('real_box_geometry_after_ui_confirmation', candidate.state.task.family === 'box' && candidate.state.task.parameters.wall.value === 3 && candidate.result.checks.every(check=>check.status==='passed'));
      report.candidate_task_id = candidate.state.task_id;
      await page.reload({waitUntil:'domcontentloaded'});
      await page.locator('.review-card').waitFor();
      check('pending_candidate_recovers_after_reload', (await page.locator('body').innerText()).includes('等待人工看图'));
      const candidateImage=path.join(output,'pending-candidate.png');
      await page.screenshot({path:candidateImage,fullPage:true}); report.screenshots.push(candidateImage);
      check('no_browser_exceptions',report.errors.length===0);
      report.status='review_required';
    } else {
      check('no_browser_exceptions', report.errors.length === 0);
      report.status = 'passed';
    }
  } catch (error) {
    report.error = error.stack;
    report.page_text = await page.locator('body').innerText().catch(() => 'unavailable');
    report.api_current = await page.evaluate(() => fetch('/api/current').then(async r => ({status:r.status,body:await r.text()}))).catch(error => error.message);
    const failure = path.join(output, 'failure.png');
    await page.screenshot({path: failure, fullPage: true, timeout: 10000}).then(() => report.screenshots.push(failure)).catch(() => {});
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(output,process.argv.includes('--workflow')?'workflow-report.json':'report.json'), JSON.stringify(report, null, 2), 'utf8');
    console.log(JSON.stringify({status:report.status,checks:report.checks,error:report.error,screenshots:report.screenshots}));
    process.exitCode = ['passed','review_required'].includes(report.status) ? 0 : 1;
  }
})();
