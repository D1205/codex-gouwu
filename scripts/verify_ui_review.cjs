/* Run only after the operator has inspected the named job's native CAD images.
   Arguments: job-id reviewer observation. This never generates a new CAD job. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.resolve(__dirname, '../ui/node_modules/playwright'));
const [jobId, reviewer, observation] = process.argv.slice(2);
if (!jobId || !reviewer || !observation) throw new Error('Required: job-id reviewer observation');
const output = process.argv[5] ? path.resolve(process.argv[5]) : path.resolve(__dirname, '../results/ui-verification');
const report = { schema_version: 'ui-review-verification/1', status: 'failed', job_id: jobId,
  reviewer, observation, checks: [], errors: [] };
const check = (id, passed) => {
  report.checks.push({ id, status: passed ? 'passed' : 'failed' });
  if (!passed) throw new Error(id);
};
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:8777/', { waitUntil: 'domcontentloaded' });
    await page.locator('.review-card').waitFor();
    const candidate = await page.evaluate(id => fetch(`/api/job/${id}`).then(r => r.json()), jobId);
    const before = await page.evaluate(() => fetch('/api/current').then(r => r.json()));
    check('named_pending_candidate_restored', before.pending_job_id === jobId && candidate.status === 'review_required' && candidate.result.visual_review.status === 'pending');
    check('unchecked_visual_review_blocks_publish', !(await page.getByRole('button', { name: '确认外观并发布', exact: true }).isEnabled()));
    await page.getByLabel('我已检查原生 CAD 视图与尺寸').check();
    await page.getByLabel('审阅人', { exact: true }).fill(reviewer);
    await page.getByLabel('观察记录', { exact: true }).fill(observation);
    await page.getByRole('button', { name: '确认外观并发布', exact: true }).click();
    await page.locator('.review-card').waitFor({ state: 'detached', timeout: 30000 });
    await page.waitForFunction(id => fetch('/api/current').then(r => r.json()).then(data =>
      data.status === 'ready' && data.state.task_id === id && !data.pending_job_id), candidate.state.task_id);
    const after = await page.evaluate(() => fetch('/api/current').then(r => r.json()));
    check('explicit_review_publishes_named_candidate', after.state.task_id === candidate.state.task_id && after.state.revision === candidate.state.revision && after.result.status === 'passed');
    check('review_preserves_verified_geometry', after.state.semantic_hash === candidate.state.semantic_hash);
    check('no_browser_exceptions', report.errors.length === 0);
    report.task_id = after.state.task_id;
    report.family = after.state.task.family;
    report.semantic_hash = after.state.semantic_hash;
    fs.mkdirSync(output, { recursive: true });
    report.screenshot = path.join(output, process.argv[5] ? 'published-model.png' : 'published-box.png');
    await page.screenshot({ path: report.screenshot, fullPage: true });
    report.status = 'passed';
  } catch (error) {
    report.error = error.stack;
    report.page_text = await page.locator('body').innerText().catch(() => 'unavailable');
  } finally {
    await browser.close();
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'review-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, checks: report.checks, error: report.error }));
    process.exitCode = report.status === 'passed' ? 0 : 1;
  }
})();
