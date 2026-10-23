export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error(`服务未返回 JSON（HTTP ${response.status}），请确认本机服务已启动。`); }
  if (!response.ok) {
    const detail = (value as {error?: unknown; message?: string}).error || (value as {message?: string}).message;
    throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `请求失败：HTTP ${response.status}`);
  }
  return value as T;
}

export async function operation<T>(path: string, body: unknown): Promise<T> {
  const receipt = await api<{operation_id: string; status: string}>(path, body);
  if (!receipt.operation_id) throw new Error('服务未返回任务编号，请检查本机服务。');
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    const state = await api<{status: string; result?: T; error?: unknown}>(`/api/operations/${encodeURIComponent(receipt.operation_id)}`);
    if (state.status === 'done') {
      if (state.result === undefined) throw new Error('任务完成，但服务未返回结果。');
      return state.result;
    }
    if (state.status === 'failed') throw new Error(typeof state.error === 'string' ? state.error : JSON.stringify(state.error || '任务执行失败'));
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error('等待任务超时。任务可能仍在本机运行，请先刷新状态，避免重复提交。');
}
