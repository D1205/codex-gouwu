import { useCallback, useEffect, useState } from 'react';
import { api, operation } from './api';
import Viewport from './Viewport';
import ChatPanel, { ChatIcon } from './ChatPanel';
import SettingsDialog from './SettingsDialog';
import type { ChatMessage, ReferenceImage } from './ChatPanel';
import { familyLabel, featureDescription, parameterChanged, parameterLabel, sourceLabels, unitLabel } from './types';
import type { Asset, DraftResult, ModelView, Parameter, Selection } from './types';

type Receipt = {job_id: string; status: string; error?: string};
const sessionKey = 'mechanical-design-chat-v1';
type ChatSession = {version: 1; mode: 'create' | 'modify'; input: string; brief: string; messages: ChatMessage[]; references: ReferenceImage[]; attachments: ReferenceImage[]; draft: DraftResult | null; baseline?: string};
function restoreSession(): Partial<ChatSession> {
  try {
    const value = JSON.parse(localStorage.getItem(sessionKey) || 'null');
    if (!value || value.version !== 1) return {};
    const validImage = (image: ReferenceImage) => image && typeof image.id === 'string' && /^[a-f0-9]{64}$/.test(image.id) && image.url === `/api/reference-images/${image.id}`;
    return {...value, references: (value.references || []).filter(validImage).slice(0, 6), attachments: (value.attachments || []).filter(validImage).slice(0, 6), messages: (value.messages || []).filter((message: ChatMessage) => ['user', 'assistant'].includes(message.role) && typeof message.text === 'string').map((message: ChatMessage) => ({...message, images: (message.images || []).filter(validImage)}))};
  } catch {return {};}
}
const examples = [
  {label: '圆形法兰盘', text: '做一个圆形法兰盘，外径100毫米、厚度10毫米，中心贯穿孔直径30毫米。在直径75毫米的分布圆上均布6个直径8毫米的贯穿孔，第一个孔位于X正方向。只做几何评审。'},
  {label: '阶梯轴', text: '做一根同轴阶梯轴：第一段直径30毫米、长度20毫米，第二段直径20毫米、长度50毫米，第三段直径15毫米、长度15毫米，三段沿Z正方向依次连接，不加倒角和键槽。只做几何评审。'},
  {label: '套筒', text: '做一个两端开口的圆柱套筒，外径40毫米、内径25毫米、长度50毫米，各段同轴，不加其他结构。只做几何评审。'},
  {label: '垫圈', text: '做一个平垫圈，外径30毫米、内径16毫米、厚度3毫米，中心孔贯穿，不加其他结构。只做几何评审。'},
  {label: '圆盘', text: '做一个实心圆盘，直径80毫米、厚度12毫米，不开孔。只做几何评审。'},
  {label: '矩形块', text: '做一个实心矩形块，长度80毫米、宽度50毫米、高度20毫米，不开孔。只做几何评审。'},
  {label: '四孔底板', text: '做一块长80毫米、宽50毫米、厚4毫米的矩形底板，四个直径5毫米的贯穿孔，孔中心距相邻两条边都是10毫米。只做几何评审。'},
  {label: 'L 形支架', text: '做一个简单L形支架，外部长60毫米、高40毫米，沿Z方向宽30毫米，统一壁厚4毫米，不开孔。只做几何评审。'},
  {label: '无盖盒体', text: '做一个无盖长方形盒体，外部长80毫米、宽50毫米、高30毫米，侧壁和底部都是3毫米厚，不加其他结构。只做几何评审。'},
];
const iconPath = {arrow:'M4 12h15m-6-6 6 6-6 6', refresh:'M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3a7 7 0 0 0 11.5-1', cube:'m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 10 9-5m-9 5L3 8m9 5v9', download:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5', check:'m5 12 4 4 10-10', close:'m6 6 12 12M6 18 18 6', chat:'M20 4H4v13h4l4 4v-4h8V4ZM8 9h8M8 12h5', shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6'};
function Icon({name, size = 18}: {name: keyof typeof iconPath; size?: number}) {return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={iconPath[name]}/></svg>;}
function errorMessage(error: unknown) {return error instanceof Error ? error.message : String(error);}
function Badge({children, tone = ''}: {children: React.ReactNode; tone?: string}) {return <span className={`badge ${tone}`}>{children}</span>;}

export default function App() {
  const [session] = useState(restoreSession);
  const [current, setCurrent] = useState<ModelView | null>(null);
  const [pending, setPending] = useState<ModelView | null>(null);
  const [viewing, setViewing] = useState<'current' | 'pending'>('current');
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [mode, setMode] = useState<'create' | 'modify'>(session.mode === 'modify' ? 'modify' : 'create');
  const [input, setInput] = useState(session.input || '');
  const [accumulatedBrief, setAccumulatedBrief] = useState(session.brief || '');
  const [messages, setMessages] = useState<ChatMessage[]>(session.messages || []);
  const [draft, setDraft] = useState<DraftResult | null>(session.draft || null);
  const [references, setReferences] = useState<ReferenceImage[]>(session.references || []);
  const [attachments, setAttachments] = useState<ReferenceImage[]>(session.attachments || []);
  const [uploading, setUploading] = useState(false);
  const [sessionBaseline, setSessionBaseline] = useState(session.baseline || '');
  const [engineeringOpen, setEngineeringOpen] = useState(() => window.innerWidth >= 1000);
  const [engineeringTab, setEngineeringTab] = useState<'task' | 'model' | 'files'>('model');
  const [selection, setSelection] = useState<Selection | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [lookedAtViews, setLookedAtViews] = useState(false);
  const [checkDetails, setCheckDetails] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const value = await api<ModelView>('/api/current');
      setCurrent(value); setConnected(true);
      if (value.pending_job_id) {
        const candidate = await api<ModelView>(`/api/job/${encodeURIComponent(value.pending_job_id)}`);
        setPending({...candidate, job_id: value.pending_job_id}); setViewing('pending');
      } else {setPending(null); setViewing('current');}
      return value;
    } catch (error) {setConnected(false); setError(errorMessage(error)); return null;}
    finally {setLoading(false);}
  }, []);
  useEffect(() => {void refresh();}, [refresh]);
  useEffect(() => {
    try {
      const value: ChatSession = {version: 1, mode, input, brief: accumulatedBrief, messages, references, attachments, draft, baseline: sessionBaseline};
      localStorage.setItem(sessionKey, JSON.stringify(value));
    } catch {setNotice('浏览器无法保存当前对话。关闭或刷新页面前，请完成需要的补充。');}
  }, [mode, input, accumulatedBrief, messages, references, attachments, draft, sessionBaseline]);

  const displayed = viewing === 'pending' && pending ? pending : current;
  const mapping = displayed?.result?.mapping;
  const assets = displayed?.assets || [];
  const preview = assets.find(asset => asset.kind === 'stl');
  // An incomplete new request must never borrow the published model's task card.
  const requestActive = !pending && (!!draft || !!accumulatedBrief || busy === '正在整理工程需求');
  const task = requestActive ? draft?.task || null : displayed?.state?.task;
  const candidate = draft?.task ? null : draft?.candidate;
  const taskFamily = task?.family || candidate?.family;
  const taskGoal = task?.goal || candidate?.goal;
  const parameterEntries: Array<[string, Parameter & {source_kind?: string; source_reference?: string | null}]> = task
    ? Object.entries(task.parameters)
    : (candidate?.parameters || []).map(parameter => [parameter.name, {...parameter, source_id: null}]);
  const features = task?.features || candidate?.features || [];
  const questions = [...new Set([...(draft?.questions || []), ...(draft?.conflicts || []), ...(draft?.unsupported_requirements || [])])];
  const previousModelVisible = requestActive && viewing === 'current' && !!current?.state;
  const baselineTask = current?.state?.task;
  const currentRevision = current?.state?.revision;
  const pendingRevision = pending?.state?.revision || pending?.result?.revision;
  const checks = displayed?.result?.checks || [];
  const passedChecks = checks.filter(check => check.status === 'passed').length;
  const pictures = assets.filter(asset => asset.kind.startsWith('preview_'));
  const downloadable = assets.filter(asset => ['native', 'step', 'stl', 'mapping'].includes(asset.kind));
  const canRun = draft?.status === 'ready' && !!draft.task && !busy && !pending && !input.trim() && !attachments.length && !uploading && connected && !loading;
  const canReview = !!pending && !!reviewer.trim() && !!reviewNotes.trim() && lookedAtViews && !busy;

  function changeMode(next: 'create' | 'modify') {
    if (busy || pending || next === mode) return;
    resetConversation(next);
  }

  function resetConversation(next: 'create' | 'modify' = 'create') {
    if (busy || pending) return;
    setMode(next); setDraft(null); setMessages([]); setAccumulatedBrief(''); setInput(''); setSelection(null); setError(''); setNotice(''); setReferences([]); setAttachments([]);
    setSessionBaseline(next === 'modify' ? current?.state?.semantic_hash || '' : '');
  }

  const addAttachment = useCallback((image: ReferenceImage) => {
    if (references.some(item => item.id === image.id)) {setNotice('这张图片已在本次参考中，后续补充会继续使用。'); return;}
    setAttachments(previous => previous.some(item => item.id === image.id) ? previous : [...previous, image]);
  }, [references]);

  function openEngineering(tab?: 'task' | 'model' | 'files') {
    if (tab) {setEngineeringOpen(true); setEngineeringTab(tab);} else setEngineeringOpen(value => !value);
  }

  function onSelect(value: Selection | null) {
    if (uploading) return;
    setSelection(value);
    if (value && viewing === 'current' && !busy && !pending) {
      if (mode !== 'modify') {setMode('modify'); setDraft(null); setMessages([]); setAccumulatedBrief(''); setInput(''); setReferences([]); setAttachments([]); setSessionBaseline(current?.state?.semantic_hash || '');}
    }
  }

  async function interpret() {
    if ((!input.trim() && !attachments.length) || busy || pending || uploading || !connected) return;
    if (mode === 'modify' && (!baselineTask || (sessionBaseline && sessionBaseline !== current?.state?.semantic_hash))) {setError('已发布基线发生变化。请新开“修改当前”对话，基于最新模型重新提出修改。'); return;}
    const addition = input.trim();
    const brief = accumulatedBrief ? addition ? `${accumulatedBrief}\n补充：${addition}` : accumulatedBrief : addition;
    const imageContext = [...new Map([...references, ...attachments].map(image => [image.id, image])).values()];
    const sentImages = attachments;
    setError(''); setNotice(''); setDraft(null); setBusy('正在整理工程需求'); setInput(''); setAccumulatedBrief(brief);
    setReferences(imageContext); setAttachments([]);
    setMessages(previous => [...previous, {id: crypto.randomUUID(), role: 'user', text: addition, images: sentImages}]);
    try {
      const value = await operation<DraftResult>('/api/interpret', {
        brief, current_task: mode === 'modify' ? baselineTask : null,
        selection: mode === 'modify' ? selection : null,
        image_ids: imageContext.map(image => image.id),
        conversation: messages.slice(-80).reduceRight<Array<{role: 'user' | 'assistant'; text: string}>>((result, message) => {
          const remaining = 40000 - result.reduce((length, item) => length + item.text.length, 0);
          if (remaining > 0 && message.text) result.unshift({role: message.role, text: message.text.slice(-Math.min(remaining, 10000))});
          return result;
        }, []),
      });
      setDraft(value);
      if (value.status === 'failed') throw new Error(value.error?.message || '需求转换未完成，请查看错误后重试。');
      const questions = [...new Set([...(value.questions || []), ...(value.conflicts || []), ...(value.unsupported_requirements || [])])];
      setMessages(previous => [...previous, {id: crypto.randomUUID(), role: 'assistant', text: value.status === 'ready' ? '工程需求已整理。请在工程面板核对尺寸、来源和建模步骤，确认后即可生成真实模型。' : questions.length > 1 ? questions.map(question => `- ${question}`).join('\n') : questions[0] || '还需要补充关键规格，请完善需求。'}]);
      if (value.status === 'ready') {setEngineeringOpen(true); setEngineeringTab('task');}
    } catch (error) {
      const message = errorMessage(error);
      setError(message);
      setDraft(previous => previous || {status: 'failed', task: null, questions: [], conflicts: [], unsupported_requirements: [], error: {message}});
      setMessages(previous => [...previous, {id: crypto.randomUUID(), role: 'assistant', text: `这次需求整理未完成：${message}\n\n你发送的描述与参考图已经保留，可以补充信息后重试。`}]);
    }
    finally {setBusy('');}
  }

  async function generate() {
    if (!canRun || !draft?.task) return;
    setBusy('正在本机生成并检查模型'); setError(''); setNotice('');
    try {
      await api('/api/validate', {task: draft.task});
      const receipt = await operation<Receipt>('/api/run', {task: draft.task});
      if (receipt.status === 'failed') throw new Error(receipt.error || 'CAD 执行失败，当前发布版本保持不变。');
      if (receipt.status === 'review_required') {
        const view = await api<ModelView>(`/api/job/${encodeURIComponent(receipt.job_id)}`);
        setPending({...view, job_id: receipt.job_id}); setViewing('pending'); setSelection(null);
        setEngineeringOpen(true); setEngineeringTab('model');
        setMessages(previous => [...previous, {id: crypto.randomUUID(), role: 'assistant', text: '模型已生成，几何检查已完成。请在工程面板查看三维模型、原生 CAD 视图与参数；填写实际观察后，再发布为下次修改的基线。'}]);
        setLookedAtViews(false); setReviewNotes(''); setNotice('模型与几何检查已完成。请查看原生 CAD 视图，记录观察后发布。');
      } else if (receipt.status === 'passed') {await refresh(); setNotice('模型已完成并发布。');}
      else throw new Error(`执行状态未完成：${receipt.status}`);
      setDraft(null);
    } catch (error) {setError(errorMessage(error));}
    finally {setBusy('');}
  }

  async function review(approved: boolean) {
    if (!canReview || !pending?.job_id) return;
    setBusy(approved ? '正在核对证据并发布' : '正在退回候选版本'); setError('');
    try {
      const receipt = await operation<Receipt>('/api/review', {job_id: pending.job_id, approved, reviewer: reviewer.trim(), notes: reviewNotes.trim()});
      if (approved && receipt.status !== 'passed') throw new Error(receipt.error || '发布没有完成，请查看结果。');
      setPending(null); setViewing('current'); setSelection(null); setDraft(null); setAccumulatedBrief('');
      setMessages(previous => [...previous, {id: crypto.randomUUID(), role: 'assistant', text: approved ? '模型已审阅并发布。你可以新开对话设计另一个零件，或切换“修改当前”继续完善这个模型。' : '候选模型已退回。你可以继续补充要求，重新整理后生成。'}]);
      setNotice(approved ? '已发布。后续修改将基于这个已审阅版本。' : '候选版本已退回，已发布模型保持不变。');
      await refresh();
    } catch (error) {setError(errorMessage(error));}
    finally {setBusy('');}
  }

  function parameterSelection(name: string) {
    if (!mapping || busy) return;
    const parameter = mapping.parameters.find(parameter => parameter.name === name);
    if (parameter) onSelect({task_id: mapping.task_id, revision: mapping.revision, semantic_hash: mapping.semantic_hash, parameter_id: parameter.parameter_id, parameter_name: name, instance_id: mapping.instance_id});
  }

  return <div className="app-shell">
    <header className="app-header">
      <a className="brand" href="/" aria-label="codex的构物首页"><img className="brand-icon" src="/brand/logo.svg" width="32" height="32" alt=""/><span>codex的构物<span className="brand-en">MECHANICAL</span></span></a>
      <div className="header-divider"/><span className="header-caption">自然语言机械设计</span>
      <div className="header-status"><span className={`dot ${connected ? '' : 'neutral'}`}/>{loading ? '连接本机服务…' : connected ? '本机服务已连接' : '本机服务未连接'}<span className="subtle-divider">|</span>几何评审</div>
      <button type="button" className="settings-trigger" onClick={() => setSettingsOpen(true)} disabled={!!busy || uploading} aria-haspopup="dialog" aria-label="模型设置" title={busy || uploading ? '当前操作完成后可修改模型设置' : '模型设置'}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 3-.7 2.4-2 .9L4 5.7 2 9l1.8 1.7v2.6L2 15l2 3.3 2.3-.6 2 .9L9 21h4l.7-2.4 2-.9 2.3.6 2-3.3-1.8-1.7v-2.6L20 9l-2-3.3-2.3.6-2-.9L13 3H9Z"/><circle cx="11" cy="12" r="3"/></svg><span>设置</span></button>
    </header>

    <main className="c-main">
      {error && <div className="alert error" role="alert"><span><strong>这一步尚未完成</strong> {error}</span><button aria-label="关闭错误" onClick={() => setError('')}><Icon name="close"/></button></div>}
      {notice && <div className="alert notice" role="status"><Icon name="check"/><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}><Icon name="close"/></button></div>}

      <div className={`c-workspace ${engineeringOpen ? 'with-engineering' : 'chat-focused'}`}>
        <ChatPanel messages={messages} input={input} onInput={setInput} onSend={() => void interpret()}
          attachments={attachments} references={references} onAttach={addAttachment} onRemoveAttachment={id => setAttachments(previous => previous.filter(image => image.id !== id))}
          onRemoveReference={id => {setReferences(previous => previous.filter(image => image.id !== id)); setDraft(null); setNotice('已移出本次参考，后续补充不会再发送这张图片；对话中的原图仍保留。');}}
          onUploading={setUploading} mode={mode} onMode={changeMode} onNew={() => resetConversation()} busy={busy} connected={connected} pending={!!pending}
          canModify={!!baselineTask} revision={currentRevision} selection={selection ? parameterLabel(selection.parameter_name) : undefined}
          onClearSelection={() => setSelection(null)} needsInput={draft?.status === 'needs_input'} ready={draft?.status === 'ready'}
          onToggleEngineering={() => openEngineering()} onOpenEngineering={() => openEngineering(pending ? 'model' : 'task')} engineeringOpen={engineeringOpen} examples={examples}/>
        <section className="c-engineering" hidden={!engineeringOpen} aria-label="工程面板">
          <div className="c-engineering-toolbar"><div className="c-engineering-tabs" role="tablist" aria-label="工程资料">{([{id: 'task', label: '工程需求'}, {id: 'model', label: '三维模型'}, {id: 'files', label: '检查与文件'}] as const).map(tab => <button key={tab.id} role="tab" aria-selected={engineeringTab === tab.id} className={engineeringTab === tab.id ? 'active' : ''} onClick={() => setEngineeringTab(tab.id)}>{tab.label}{tab.id === 'task' && draft?.status === 'ready' && <span className="dot"/>}{tab.id === 'model' && pending && <span className="dot amber"/>}</button>)}</div><button className="c-icon-button" aria-label="刷新工程状态" title="刷新状态" onClick={() => {setError(''); void refresh();}} disabled={!!busy || loading}><Icon name="refresh" size={16}/></button><button className="c-icon-button" aria-label="收起工程面板" title="收起工程面板" onClick={() => setEngineeringOpen(false)}><ChatIcon name="close" size={17}/></button></div>
          <div className="c-engineering-content">
          <section className="panel preview-panel" hidden={engineeringTab !== 'model'}>
            <div className="preview-heading"><div><span className="eyebrow">MODEL SPACE</span><h2>{displayed?.state?.task ? familyLabel(displayed.state.task.family) : '模型预览'}</h2>{previousModelVisible && <p className="model-context-label">上一已发布模型 · 与本次需求分开显示</p>}</div><div className="revision-tabs"><button className={viewing === 'current' ? 'active' : ''} onClick={() => {setViewing('current'); setSelection(null);}}>已发布 {currentRevision ? `r${currentRevision}` : '—'}</button>{pending && <button className={viewing === 'pending' ? 'active pending-tab' : ''} onClick={() => {setViewing('pending'); setSelection(null);}}>待审阅 r{pendingRevision}</button>}</div></div>
            <Viewport url={preview?.url} mapping={mapping} selection={selection} onSelect={onSelect}/>
            <div className="preview-meta"><span><i className="marker-dot"/>橙色标记可选择工程参数</span><span>{viewing === 'pending' && pending ? <Badge tone="amber">尚未发布</Badge> : currentRevision ? <Badge tone="green">已审阅 · r{currentRevision}</Badge> : '等待首次生成'}</span></div>
            {selection && <div className="selection-detail"><Icon name="cube"/><div><strong>{selection.parameter_name === 'hole_diameter' && displayed?.state?.task.schema_version === 'engineering-task/1' && displayed.state.task.family === 'plate' ? '四个贯穿孔 · 统一孔径' : parameterLabel(selection.parameter_name)}</strong><span>语义参数 · r{selection.revision}{viewing === 'pending' ? ' · 待审阅模型仅供检查' : ' · 可以用自然语言提出修改'}</span></div><button className="text-button" onClick={() => setSelection(null)}>取消选择</button></div>}
            {requestActive && <div className="draft-preview-note"><span className={`dot ${draft?.status === 'ready' ? '' : 'amber'}`}/>{draft?.status === 'ready' ? '本次需求已就绪，确认后才会生成新模型。' : draft?.status === 'failed' ? '本次需求尚未形成可执行任务，当前预览保留上一模型。' : '正在整理或补齐本次需求，当前预览尚未更新。'}</div>}
            {pending && <div className="c-review-shortcut"><p>查看原生 CAD 视图后，到工程需求页填写审阅记录。</p><button className="button soft" onClick={() => setEngineeringTab('files')}>查看原生视图</button><button className="button primary" onClick={() => setEngineeringTab('task')}>填写审阅并发布 <Icon name="arrow" size={15}/></button></div>}
          </section>

          <section className="panel evidence-panel" hidden={engineeringTab !== 'files'}><div className="evidence-heading"><div><h2>模型检查与文件</h2><p>{checks.length ? `${previousModelVisible ? '上一已发布模型' : '当前展示模型'}的几何与交付检查 ${passedChecks} / ${checks.length} 项通过` : '生成后会在这里展示真实检查结果和文件。'}</p></div>{checks.length > 0 && <button className="text-button" onClick={() => setCheckDetails(!checkDetails)}>{checkDetails ? '收起明细' : '查看明细'} ↗</button>}</div>
            {checkDetails && <div className="check-list">{checks.map(check => <div key={check.id}><span>{check.id}</span><Badge tone={check.status === 'passed' ? 'green' : 'amber'}>{check.status === 'passed' ? '通过' : check.status}</Badge></div>)}</div>}
            {pictures.length > 0 && <div className="native-views">{pictures.map(asset => <a key={asset.kind} href={asset.url} target="_blank" rel="noreferrer" title="打开原生 CAD 视图"><img src={asset.url} alt={viewName(asset.kind)}/><span>{viewName(asset.kind)} ↗</span></a>)}</div>}
            <div className="artifact-list">{downloadable.map(asset => <a key={asset.kind} href={asset.url} download={asset.filename} className="artifact"><span className="file-type">{asset.kind === 'native' ? 'SW' : asset.kind === 'mapping' ? '{ }' : asset.kind.toUpperCase()}</span><span><strong>{assetLabel(asset)}</strong><small>{asset.filename}</small></span><Icon name="download" size={17}/></a>)}</div>
            <div className="scope-note"><Icon name="shield" size={16}/><span>当前范围：几何评审。制造工艺、承载强度、运动与实机性能尚未验证。</span></div>
            {pending && <button className="button primary full c-evidence-review" onClick={() => setEngineeringTab('task')}>前往填写审阅记录 <Icon name="arrow" size={16}/></button>}
          </section>

        <aside className="panel requirements-panel" hidden={engineeringTab !== 'task'}><div className="panel-heading"><h2>工程需求卡</h2><span className="tiny-label">LIVE</span></div>
          <div className="task-summary"><span className="micro-label">{requestActive ? '本次需求' : viewing === 'pending' && pending ? '待审阅版本' : '已发布需求'}</span><h3>{taskFamily ? familyLabel(taskFamily) : requestActive ? '本次需求尚未形成' : '等待整理需求'}</h3><p>{taskGoal || (requestActive ? '正在把你的描述整理为工程任务；关键参数和建模步骤会在这里显示。' : '用途、尺寸与来源，会在这里形成一份明确的工程任务。')}</p><div className="task-tags">{task && <Badge>{task.action === 'modify' ? '修改' : '新建'} · r{task.revision}</Badge>}{requestActive ? <Badge tone={draft?.status === 'ready' ? 'green' : 'amber'}>{draft?.status === 'ready' ? '待你确认' : draft?.status === 'failed' ? '整理未完成' : draft?.status === 'needs_input' ? '待补充 · 尚不可执行' : '正在整理'}</Badge> : task && <Badge tone={viewing === 'pending' && pending ? 'amber' : 'green'}>{viewing === 'pending' && pending ? '待看图审阅' : '已确认'}</Badge>}</div></div>
          {requestActive && !task && <div className="draft-task-note">当前卡片仅展示本次需求草稿，不沿用上一模型的尺寸。{draft?.status === 'failed' && '请查看错误信息，补充需求后重新整理。'}</div>}
          {questions.length > 0 && <div className="draft-questions"><h3>需要你补充或确认</h3><ul>{questions.map((question, index) => <li key={index}>{question}</li>)}</ul></div>}
          <div className="parameters-header"><h3>关键参数</h3><span>按输入单位显示</span></div>
          <div className="parameters">{parameterEntries.length ? parameterEntries.map(([name, parameter], index) => {
            const source = task?.sources.find(source => source.id === parameter.source_id);
            const sourceKind = source?.kind || parameter.source_kind;
            const sourceReference = source?.reference || parameter.source_reference;
            const old = baselineTask?.parameters[name];
            const changed = !!draft && task?.action === 'modify' && old && parameterChanged(old, parameter);
            return <div className={`parameter ${selection?.parameter_name === name ? 'selected' : ''} ${changed ? 'changed' : ''}`} key={`${name}-${index}`}>
              <button className="parameter-pick" title={name} onClick={() => parameterSelection(name)} disabled={requestActive || !mapping || !!busy}><span>{parameterLabel(name)}{task?.hard_constraints[name] !== undefined && <span className="locked" title="受保护参数">锁定</span>}</span><strong>{parameter.value === null ? <span className="unknown">待补充</span> : <>{changed && old && <del>{old.value}<small>{unitLabel(old.unit)}</small></del>}{parameter.value}<small>{unitLabel(parameter.unit)}</small></>}</strong></button>
              <div className="parameter-source" title={sourceReference || '尚无确认来源'}><span className={`dot ${parameter.confirmed ? '' : 'amber'}`}/>{sourceKind ? sourceLabels[sourceKind] || sourceKind : '来源待明确'}<span>{parameter.confirmed ? '已确认' : '未确认'}</span></div>
              {changed && <span className="change-label">本次变更</span>}
            </div>;
          }) : <div className="empty-parameters"><span>—</span>{requestActive ? '本次需求的参数尚待明确' : '明确需求后显示参数'}</div>}</div>
          {features.length > 0 && <div className="feature-steps"><h3>{task ? '建模步骤' : '待确认的建模思路'}</h3><ol>{features.map((feature, index) => <li key={`${feature.id}-${index}`}>{featureDescription(feature)}</li>)}</ol></div>}
          {task && <details className="source-details"><summary>查看尺寸依据与保护约束</summary>{task.sources.map(source => <div key={source.id}><strong>{sourceLabels[source.kind] || source.kind}</strong><p>{source.reference}</p></div>)}{Object.keys(task.hard_constraints).length > 0 && <p>受保护：{Object.keys(task.hard_constraints).map(parameterLabel).join('、')}</p>}</details>}
          {!pending && <div className="confirm-task"><p>{draft?.status === 'ready' ? input.trim() ? '你有尚未整理的补充内容，请先重新整理需求。' : '核对尺寸和来源后，确认这份需求并生成模型。' : '关键尺寸和单位明确后，即可确认生成。'}</p><button className="button primary full" disabled={!canRun} onClick={() => void generate()}><Icon name="cube"/>确认需求并生成<Icon name="arrow"/></button><span className="micro-label">生成完成后仍需看图审阅</span></div>}
          {pending && <div className="review-card"><Badge tone="amber">r{pendingRevision} 等待人工看图</Badge><h3>看过模型，再发布。</h3><p>打开中间的原生 CAD 视图，核对外形、孔位与尺寸。发布后才成为下次修改的基线。</p><label className="check-label"><input type="checkbox" checked={lookedAtViews} onChange={event => setLookedAtViews(event.target.checked)} disabled={!!busy}/>我已检查原生 CAD 视图与尺寸</label><label>审阅人<input value={reviewer} onChange={event => setReviewer(event.target.value)} placeholder="填写姓名或称呼" disabled={!!busy}/></label><label>观察记录<textarea value={reviewNotes} onChange={event => setReviewNotes(event.target.value)} placeholder="记录实际看到的外形、孔位或问题…" disabled={!!busy}/></label><button className="button primary full" onClick={() => void review(true)} disabled={!canReview}><Icon name="check"/>确认外观并发布</button><button className="button soft full" onClick={() => void review(false)} disabled={!canReview}>退回此版本</button></div>}
        </aside>
        </div>
        </section>
      </div>
    </main>
    {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)}/>}
  </div>;
}

function viewName(kind: string) {return ({preview_isometric: '等轴测', preview_front: '正视图', preview_top: '俯视图', preview_right: '右视图'} as Record<string, string>)[kind] || kind;}
function assetLabel(asset: Asset) {return ({native: '可编辑 CAD 模型', step: 'STEP 交换文件', stl: 'STL 预览网格', mapping: '参数映射记录'} as Record<string, string>)[asset.kind] || asset.kind;}
