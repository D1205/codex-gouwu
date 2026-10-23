import { useEffect, useRef, useState } from 'react';
import { api } from './api';

export type ReferenceImage = {id: string; name: string; mime_type: string; width: number; height: number; size_bytes: number; sha256: string; url: string};
export type ChatMessage = {id: string; role: 'user' | 'assistant'; text: string; images?: ReferenceImage[]};
type Upload = {key: string; file: File; preview: string; status: 'uploading' | 'failed'; error?: string};
type Props = {
  messages: ChatMessage[]; input: string; onInput: (value: string) => void; onSend: () => void;
  attachments: ReferenceImage[]; references: ReferenceImage[]; onAttach: (image: ReferenceImage) => void;
  onRemoveAttachment: (id: string) => void; onRemoveReference: (id: string) => void; onUploading: (value: boolean) => void;
  mode: 'create' | 'modify'; onMode: (mode: 'create' | 'modify') => void; onNew: () => void;
  busy: string; connected: boolean; pending: boolean; canModify: boolean; revision?: number;
  selection?: string; onClearSelection: () => void; needsInput: boolean; ready: boolean;
  onOpenEngineering: () => void; onToggleEngineering: () => void; engineeringOpen: boolean; examples: Array<{label: string; text: string}>;
};

export function ChatIcon({name, size = 19}: {name: 'plus' | 'arrow' | 'close' | 'image' | 'new' | 'panel' | 'check' | 'retry'; size?: number}) {
  const paths = {plus: 'M12 5v14M5 12h14', arrow: 'M12 19V5m-6 6 6-6 6 6', close: 'm6 6 12 12M6 18 18 6', image: 'M4 4h16v16H4V4Zm0 12 5-5 4 4 3-3 4 4M15 8h.01', new: 'M14 4H5v15h15v-9M11 13l2-5 6-6 3 3-6 6-5 2Z', panel: 'M3 4h18v16H3V4Zm11 0v16', check: 'm5 12 4 4 10-10', retry: 'M20 5v6h-6M19 11a7 7 0 1 0-1 7'};
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}

function MessageBody({text}: {text: string}) {
  return <div className="c-prose">{text.split(/\n\s*\n/).filter(Boolean).map((block, index) => {
    const lines = block.split('\n');
    if (lines.every(line => /^\s*[-*•]\s+/.test(line))) return <ul key={index}>{lines.map((line, i) => <li key={i}>{line.replace(/^\s*[-*•]\s+/, '')}</li>)}</ul>;
    if (lines.every(line => /^\s*\d+[.、)]\s*/.test(line))) return <ol key={index}>{lines.map((line, i) => <li key={i}>{line.replace(/^\s*\d+[.、)]\s*/, '')}</li>)}</ol>;
    return <p key={index}>{block}</p>;
  })}</div>;
}

export default function ChatPanel(props: Props) {
  const {messages, input, onInput, attachments, references, busy, pending} = props;
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const history = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const uploadLock = useRef(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [attachmentError, setAttachmentError] = useState('');
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const [enlarged, setEnlarged] = useState<{url: string; name: string} | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const locked = !!busy || pending;
  const uploading = uploads.some(upload => upload.status === 'uploading');
  const failed = uploads.some(upload => upload.status === 'failed');
  const canSend = !locked && !uploading && !failed && props.connected && (!!input.trim() || attachments.length > 0);
  const contextIds = new Set([...references, ...attachments].map(image => image.id));

  useEffect(() => {
    const element = textarea.current;
    if (element) {element.style.height = 'auto'; element.style.height = `${Math.min(element.scrollHeight, 200)}px`;}
  }, [input]);
  useEffect(() => {if (history.current) history.current.scrollTop = history.current.scrollHeight;}, [messages.length, busy]);
  useEffect(() => {props.onUploading(uploading || failed);}, [uploading, failed, props.onUploading]);
  useEffect(() => {if (enlarged) dialog.current?.showModal(); else dialog.current?.close();}, [enlarged]);

  async function addFiles(files: File[]) {
    if (locked || uploadLock.current) return;
    setAttachmentError('');
    const available = Math.max(0, 6 - contextIds.size);
    if (!available) {setAttachmentError('当前对话最多使用 6 张参考图。可先移出不再需要的参考图。'); return;}
    const accepted: File[] = [];
    const errors: string[] = [];
    for (const file of files) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {errors.push(`${file.name}：仅支持 PNG、JPEG 和 WEBP 图片。`); continue;}
      if (file.size > 8 * 1024 * 1024) {errors.push(`${file.name}：图片不能超过 8 MiB。`); continue;}
      if (accepted.length >= available) {errors.push('当前对话最多使用 6 张参考图。'); break;}
      accepted.push(file);
    }
    if (errors.length) setAttachmentError([...new Set(errors)].join(' '));
    if (!accepted.length) return;
    uploadLock.current = true;
    const batch: Upload[] = accepted.map(file => ({key: crypto.randomUUID(), file, preview: URL.createObjectURL(file), status: 'uploading'}));
    setUploads(previous => [...previous, ...batch]);
    try {
      for (const upload of batch) await uploadFile(upload);
    } finally {uploadLock.current = false;}
  }

  async function uploadFile(upload: Upload) {
    setUploads(previous => previous.map(item => item.key === upload.key ? {...item, status: 'uploading', error: undefined} : item));
    try {
      const data_url = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error('图片读取失败，请重新选择。'));
        reader.readAsDataURL(upload.file);
      });
      const image = await api<ReferenceImage>('/api/reference-images', {name: upload.file.name, data_url});
      props.onAttach(image);
      setUploads(previous => previous.filter(item => item.key !== upload.key));
      URL.revokeObjectURL(upload.preview);
    } catch (error) {
      setUploads(previous => previous.map(item => item.key === upload.key ? {...item, status: 'failed', error: error instanceof Error ? error.message : String(error)} : item));
    }
  }

  function removeUpload(upload: Upload) {URL.revokeObjectURL(upload.preview); setUploads(previous => previous.filter(item => item.key !== upload.key));}
  function send() {if (canSend) {props.onSend(); requestAnimationFrame(() => textarea.current?.focus());}}
  function clearUploads() {setUploads(previous => {previous.forEach(upload => URL.revokeObjectURL(upload.preview)); return [];}); setAttachmentError('');}
  function newConversation() {if (locked || uploadLock.current) return; clearUploads(); props.onNew();}
  function changeMode(mode: 'create' | 'modify') {if (locked || uploadLock.current || mode === props.mode) return; clearUploads(); props.onMode(mode);}

  return <section className={`c-chat ${dragging ? 'c-dragging' : ''}`} aria-label="工程设计对话"
    onDragEnter={event => {if (event.dataTransfer.types.includes('Files') && !locked) {event.preventDefault(); dragDepth.current += 1; setDragging(true);}}}
    onDragOver={event => {if (event.dataTransfer.types.includes('Files')) event.preventDefault();}}
    onDragLeave={event => {event.preventDefault(); dragDepth.current -= 1; if (dragDepth.current <= 0) {dragDepth.current = 0; setDragging(false);}}}
    onDrop={event => {event.preventDefault(); setDragging(false); dragDepth.current = 0; void addFiles(Array.from(event.dataTransfer.files));}}>
    <div className="c-chat-toolbar"><div className="c-mode-switch" aria-label="需求模式"><button className={props.mode === 'create' ? 'active' : ''} onClick={() => changeMode('create')} disabled={locked || uploading}>新建零件</button><button className={props.mode === 'modify' ? 'active' : ''} onClick={() => changeMode('modify')} disabled={locked || uploading || !props.canModify}>修改当前{props.mode === 'modify' && props.revision ? ` · r${props.revision}` : ''}</button></div><div className="c-toolbar-actions"><button className="c-icon-button" title="新对话" aria-label="新对话" disabled={locked || uploading} onClick={newConversation}><ChatIcon name="new"/></button><button className={`c-engineering-toggle ${props.engineeringOpen ? 'active' : ''}`} onClick={props.onToggleEngineering} aria-expanded={props.engineeringOpen}><ChatIcon name="panel"/><span>{props.engineeringOpen ? '专注对话' : '工程面板'}</span></button></div></div>
    <div className="c-history" ref={history} tabIndex={0} aria-label="对话记录">
      {messages.length === 0 ? <div className="c-welcome"><img className="c-welcome-mark" src="/brand/logo.svg" width="53" height="53" alt=""/><span className="c-eyebrow">从想法，到看得见的零件</span><h1>你想设计什么？</h1><p>说说它的用途，或发来一张参考图。<br/>我们一起把形状、尺寸和安装方式说清楚。</p><div className="c-example-grid">{props.examples.slice(0, 6).map(example => <button key={example.label} disabled={locked || uploading} onClick={() => onInput(example.text)}><span>{example.label}</span><span aria-hidden="true">↗</span></button>)}</div><span className="c-welcome-note">不需要掌握 CAD 命令，缺少的信息会继续向你确认。</span></div> : <div className="c-message-stack">{messages.map(message => <article className={`c-message c-${message.role}`} key={message.id}><div className="c-message-author">{message.role === 'assistant' ? <><span className="c-assistant-mark">构</span>构物</> : '你'}</div><div className="c-message-content">{message.images && message.images.length > 0 && <div className="c-message-images">{message.images.map(image => <button key={image.id} onClick={() => setEnlarged(image)} title={`查看参考图：${image.name}`}><img src={image.url} alt={image.name}/><span>{image.name}</span></button>)}</div>}{message.text && <MessageBody text={message.text}/>}</div></article>)}
        {busy && <div className="c-working" role="status"><span className="c-working-dot"/>{busy}…</div>}
      </div>}
    </div>
    <div className="c-composer-dock">
      {references.length > 0 && <details className="c-reference-context"><summary><ChatIcon name="image" size={14}/>本次参考 · {references.length} 张<span>后续补充会继续使用</span></summary><div className="c-context-images">{references.map(image => <div key={image.id}><button className="c-context-image" title={`查看参考图：${image.name}`} onClick={() => setEnlarged(image)}><img src={image.url} alt={image.name}/><span>{image.name}</span></button><button className="c-remove-reference" disabled={locked || uploading} onClick={() => props.onRemoveReference(image.id)} title={`移出本次参考：${image.name}`}>移出参考</button></div>)}</div></details>}
      {(props.needsInput || props.ready || pending || props.selection) && <div className="c-context-bar">{props.selection ? <span className="c-selection-chip">已选 · {props.selection}<button aria-label="取消选中参数" onClick={props.onClearSelection}><ChatIcon name="close" size={13}/></button></span> : pending ? <button className="c-context-action" onClick={props.onOpenEngineering}><span className="dot amber"/>模型已生成，打开工程面板看图并审阅 ↗</button> : props.ready ? <button className="c-context-action" onClick={props.onOpenEngineering}><ChatIcon name="check" size={15}/>需求已整理，前往工程面板确认并生成 ↗</button> : <span><span className="dot amber"/> 补充关键规格后，即可继续生成</span>}</div>}
      <div className="c-composer">
        {(attachments.length > 0 || uploads.length > 0) && <div className="c-attachment-list">{attachments.map(image => <div className="c-attachment" key={image.id}><button className="c-attachment-preview" onClick={() => setEnlarged(image)}><img src={image.url} alt={image.name}/></button><span><strong>{image.name}</strong><small>{image.width} × {image.height} · 已上传</small></span><button className="c-attachment-remove" aria-label={`移除附件：${image.name}`} disabled={locked} onClick={() => props.onRemoveAttachment(image.id)}><ChatIcon name="close" size={14}/></button></div>)}{uploads.map(upload => <div className={`c-attachment ${upload.status === 'failed' ? 'failed' : ''}`} key={upload.key}><img src={upload.preview} alt={upload.file.name}/><span><strong>{upload.file.name}</strong><small>{upload.status === 'uploading' ? '正在上传…' : upload.error}</small></span>{upload.status === 'failed' && <><button className="c-upload-retry" title="重试上传" aria-label={`重试上传：${upload.file.name}`} onClick={() => {if (!uploadLock.current) {uploadLock.current = true; void uploadFile(upload).finally(() => {uploadLock.current = false;});}}}><ChatIcon name="retry" size={15}/></button><button className="c-attachment-remove" aria-label={`移除失败附件：${upload.file.name}`} onClick={() => removeUpload(upload)}><ChatIcon name="close" size={14}/></button></>}</div>)}</div>}
        <textarea ref={textarea} aria-label="描述需求或补充信息" rows={2} placeholder={pending ? '先审阅本次模型，再继续新的需求…' : messages.length ? '继续补充尺寸、说明用途，或添加参考图…' : props.mode === 'modify' ? '描述想修改的地方，也可以贴入参考图…' : '描述你想做的零件，或拖入参考图片…'} value={input} onChange={event => onInput(event.target.value)} disabled={locked}
          onCompositionStart={() => {composing.current = true;}} onCompositionEnd={() => {composing.current = false;}}
          onPaste={event => {const images = Array.from(event.clipboardData.items).filter(item => item.kind === 'file').map(item => item.getAsFile()).filter((file): file is File => !!file); if (images.length) {event.preventDefault(); void addFiles(images);}}}
          onKeyDown={event => {if (event.key !== 'Enter' || composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return; if (!event.shiftKey && !event.altKey) {event.preventDefault(); send();}}}/>
        <div className="c-composer-bottom"><input ref={fileInput} className="c-file-input" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="添加参考图片" disabled={locked || uploading} onChange={event => {void addFiles(Array.from(event.target.files || [])); event.target.value = '';}}/><button className="c-add-button" title="添加参考图片（PNG、JPEG、WEBP）" aria-label="选择参考图片" onClick={() => fileInput.current?.click()} disabled={locked || uploading || contextIds.size >= 6}><ChatIcon name="plus" size={21}/></button><span className="c-composer-hint">{uploading ? '正在上传参考图片' : '添加图片 / 拖拽 / 粘贴'}</span><span className="c-send-hint">Enter 发送 · Shift + Enter 换行</span><button className="c-send-button" aria-label="发送需求" title="发送需求" disabled={!canSend} onClick={send}>{busy ? <span className="c-send-spinner"/> : <ChatIcon name="arrow" size={20}/>}</button></div>
      </div>
      {attachmentError && <div className="c-upload-error" role="alert">{attachmentError}<button aria-label="关闭附件提示" onClick={() => setAttachmentError('')}><ChatIcon name="close" size={13}/></button></div>}
      <p className="c-footnote">参考图用于理解形状；图片中不清晰或未标注的尺寸，会向你确认。</p>
    </div>
    {dragging && <div className="c-drop-overlay"><ChatIcon name="image" size={34}/><strong>放下图片，加入工程需求</strong><span>PNG、JPEG、WEBP · 单张不超过 8 MiB</span></div>}
    <dialog ref={dialog} className="c-image-dialog" onCancel={() => setEnlarged(null)} onClick={event => {if (event.target === event.currentTarget) setEnlarged(null);}}>{enlarged && <div><div className="c-image-dialog-header"><span>{enlarged.name}</span><button aria-label="关闭图片预览" onClick={() => setEnlarged(null)}><ChatIcon name="close" size={22}/></button></div><img src={enlarged.url} alt={enlarged.name}/></div>}</dialog>
  </section>;
}
