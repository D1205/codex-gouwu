/* Read-only canvas picking check against an existing published plate from the real service. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const taskId = process.argv[2];
if (!taskId) throw new Error('Required: an existing published plate task-id');
const output = path.resolve(__dirname, '../results/ui-verification');
const report = { schema_version: 'ui-selection-verification/1', status: 'failed', task_id: taskId,
  mode: 'read_only_real_task_query', checks: [], errors: [] };
const check = (id, passed) => { report.checks.push({id, status: passed ? 'passed' : 'failed'}); if (!passed) throw new Error(id); };
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.errors.push(error.message));
  try {
    // Select an actual existing task for this isolated browser. No response is fabricated.
    await page.route('**/api/current', route => route.continue({url: `http://127.0.0.1:8777/api/current?task_id=${encodeURIComponent(taskId)}`}));
    await page.goto('http://127.0.0.1:8777/', {waitUntil: 'domcontentloaded'});
    await page.getByText('真实 STL · 可交互', {exact: true}).waitFor();
    const current = await page.evaluate(() => fetch('/api/current').then(r => r.json()));
    check('real_plate_revision_loaded_for_picking', current.state.task_id === taskId && current.state.task.family === 'plate' && current.result.mapping.markers.length === 4);
    report.revision = current.state.revision; report.semantic_hash = current.state.semantic_hash;
    check('no_parameter_selected_before_canvas_click', await page.locator('.selection-detail').count() === 0);
    // Coordinates of the left orange marker, inspected in workbench.png at this fixed viewport.
    report.pointer = {x: 620, y: 577};
    await page.mouse.click(report.pointer.x, report.pointer.y);
    await page.locator('.selection-detail').waitFor();
    check('canvas_marker_selects_shared_hole_parameter', (await page.locator('.selection-detail').innerText()).includes('四个贯穿孔 · 统一孔径') && (await page.locator('.parameter.selected').innerText()).includes('贯穿孔直径'));
    report.screenshot = path.join(output, 'canvas-selected.png');
    await page.screenshot({path: report.screenshot, fullPage: true});
    await page.mouse.click(410, 450);
    await page.locator('.selection-detail').waitFor({state:'detached'});
    check('empty_canvas_click_clears_parameter_selection', true);
    check('no_browser_exceptions', report.errors.length === 0);
    report.status = 'passed';
  } catch (error) { report.error = error.stack; }
  finally {
    await browser.close(); fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, 'selection-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report)); process.exitCode = report.status === 'passed' ? 0 : 1;
  }
})();
