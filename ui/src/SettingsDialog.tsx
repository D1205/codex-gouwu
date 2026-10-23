import { useEffect, useRef, useState } from 'react';
import { api, operation } from './api';
import './settings.css';

type ModelProfile = {
  id: string;
  name: string;
  kind: 'codex' | 'openai_compatible';
  preset: 'deepseek' | 'custom' | 'codex';
  base_url: string;
  model: string;
  vision: boolean;
  has_api_key: boolean;
};
type ModelSettings = {version: 1; active_profile_id: string; profiles: ModelProfile[]};
type CredentialEdit = {value: string; clear: boolean};
type ConnectionResult = {status: 'ready' | 'failed'; message?: string; provider?: string; model?: string};
type Feedback = {tone: 'success' | 'error'; text: string};

function messageOf(error: unknown) {return error instanceof Error ? error.message : String(error);}
function profileLabel(profile: ModelProfile) {return profile.preset === 'deepseek' ? 'DeepSeek' : profile.kind === 'codex' ? 'Codex CLI' : profile.name || '自定义 API';}
function safeSettings(value: ModelSettings): ModelSettings {
  return {version: 1, active_profile_id: value.active_profile_id, profiles: value.profiles.map(profile => ({
    id: profile.id, name: profile.name, kind: profile.kind, preset: profile.preset,
    base_url: profile.base_url, model: profile.model, vision: profile.vision, has_api_key: profile.has_api_key,
  }))};
}

export default function SettingsDialog({onClose}: {onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [savedValue, setSavedValue] = useState('');
  const [savedActive, setSavedActive] = useState('');
  const [credentials, setCredentials] = useState<Record<string, CredentialEdit>>({});
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<'save' | 'test' | ''>('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = dialog.current;
    element?.showModal();
    return () => {element?.close(); previous?.focus();};
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true); setLoadError('');
    void api<ModelSettings>('/api/settings').then(value => {
      if (!alive) return;
      const clean = safeSettings(value);
      setSettings(clean); setSavedValue(JSON.stringify(clean)); setSavedActive(clean.active_profile_id); setCredentials({});
    }).catch(error => {if (alive) setLoadError(messageOf(error));}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [reload]);

  const selected = settings?.profiles.find(profile => profile.id === settings.active_profile_id);
  const secret = selected ? credentials[selected.id] || {value: '', clear: false} : {value: '', clear: false};
  const dirty = !!settings && (JSON.stringify(settings) !== savedValue || Object.values(credentials).some(item => !!item.value.trim() || item.clear));
  const locked = !!working;

  function updateProfile(patch: Partial<ModelProfile>) {
    if (!settings || !selected || locked) return;
    setSettings({...settings, profiles: settings.profiles.map(profile => profile.id === selected.id ? {...profile, ...patch} : profile)});
    setFeedback(null);
  }

  function updateCredential(patch: Partial<CredentialEdit>) {
    if (!selected || locked) return;
    setCredentials(previous => ({...previous, [selected.id]: {...secret, ...patch}}));
    setFeedback(null);
  }

  function addCustom() {
    if (!settings || locked || settings.profiles.length >= 20) return;
    const id = `custom-${crypto.randomUUID().slice(0, 8)}`;
    setSettings({...settings, active_profile_id: id, profiles: [...settings.profiles, {
      id, name: '自定义 API', kind: 'openai_compatible', preset: 'custom', base_url: '', model: '', vision: false, has_api_key: false,
    }]});
    setFeedback(null);
  }

  function removeCustom() {
    if (!settings || !selected || selected.preset !== 'custom' || locked) return;
    const profiles = settings.profiles.filter(profile => profile.id !== selected.id);
    setSettings({...settings, profiles, active_profile_id: profiles.find(profile => profile.id === savedActive)?.id || profiles[0].id});
    setCredentials(previous => Object.fromEntries(Object.entries(previous).filter(([id]) => id !== selected.id)));
    setFeedback(null);
  }

  async function save() {
    if (!settings || locked) return;
    const incomplete = settings.profiles.find(profile => !profile.name.trim() || (profile.kind !== 'codex' && (!profile.base_url.trim() || !profile.model.trim())));
    if (incomplete) {
      setSettings({...settings, active_profile_id: incomplete.id});
      setFeedback({tone: 'error', text: `请完善“${profileLabel(incomplete)}”的名称、API 地址和模型名称，或删除该配置。`});
      return;
    }
    setWorking('save'); setFeedback(null);
    try {
      const value = await api<ModelSettings>('/api/settings', {
        active_profile_id: settings.active_profile_id,
        profiles: settings.profiles.map(profile => ({
          id: profile.id, name: profile.name.trim(), kind: profile.kind, preset: profile.preset,
          base_url: profile.base_url.trim(), model: profile.model.trim(), vision: profile.vision,
          ...(credentials[profile.id]?.clear ? {clear_api_key: true} : credentials[profile.id]?.value.trim() ? {api_key: credentials[profile.id].value.trim()} : {}),
        })),
      });
      const clean = safeSettings(value);
      setSettings(clean); setSavedValue(JSON.stringify(clean)); setSavedActive(clean.active_profile_id); setCredentials({});
      const active = clean.profiles.find(profile => profile.id === clean.active_profile_id);
      setFeedback({tone: 'success', text: `已保存。下一次需求整理将使用 ${active ? profileLabel(active) : '所选配置'}${active?.model ? ` · ${active.model}` : ''}。`});
    } catch (error) {setFeedback({tone: 'error', text: `保存未完成：${messageOf(error)}`});}
    finally {setWorking('');}
  }

  async function test() {
    if (!settings || dirty || locked) return;
    setWorking('test'); setFeedback(null);
    try {
      const result = await operation<ConnectionResult>('/api/settings/test', {});
      setFeedback({tone: result.status === 'ready' ? 'success' : 'error', text: result.message || (result.status === 'ready' ? '连接测试通过。' : '连接测试未通过，请检查配置后重试。')});
    } catch (error) {setFeedback({tone: 'error', text: `连接测试未通过：${messageOf(error)}`});}
    finally {setWorking('');}
  }

  return <dialog className="settings-dialog" ref={dialog} aria-labelledby="settings-title" aria-describedby="settings-description"
    onCancel={event => {event.preventDefault(); onClose();}}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    }}>
    <div className="settings-heading"><div><span className="settings-eyebrow">MODEL SETTINGS</span><h2 id="settings-title">模型设置</h2><p id="settings-description">选择需求整理使用的模型，保存后在下一次发送时生效。</p></div><button type="button" className="c-icon-button settings-close" aria-label="关闭模型设置" onClick={onClose} autoFocus><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></div>
    {loading ? <div className="settings-loading" role="status">正在读取模型设置…</div> : loadError ? <div className="settings-load-error"><p role="alert">{loadError}</p><button type="button" className="button soft" onClick={() => setReload(value => value + 1)}>重新读取</button></div> : settings && selected ? <form onSubmit={event => {event.preventDefault(); void save();}}>
      <div className="settings-layout">
        <nav className="settings-profiles" aria-label="模型接入方式">
          <span className="settings-section-label">接入方式</span>
          {settings.profiles.map(profile => <button key={profile.id} type="button" className={`settings-profile ${selected.id === profile.id ? 'selected' : ''}`} aria-pressed={selected.id === profile.id} disabled={locked} onClick={() => {setSettings({...settings, active_profile_id: profile.id}); setFeedback(null);}}><span className="settings-profile-mark">{profile.preset === 'deepseek' ? 'D' : profile.kind === 'codex' ? 'C' : '↗'}</span><span><strong>{profileLabel(profile)}</strong><small>{profile.kind === 'codex' ? '本机登录' : profile.preset === 'deepseek' ? '默认接入' : 'OpenAI 兼容接口'}</small></span>{profile.id === savedActive && <span className="settings-active-dot" title="已保存的当前接入" aria-label="当前使用"/>}</button>)}
          <button type="button" className="settings-add" onClick={addCustom} disabled={locked || settings.profiles.length >= 20}>＋ 添加自定义 API</button>
        </nav>
        <section className="settings-fields" aria-label={`${profileLabel(selected)} 设置`}>
          <div className="settings-provider-title"><h3>{profileLabel(selected)}</h3><span className="badge">{selected.kind === 'codex' ? 'CLI' : 'API'}</span>{selected.preset === 'custom' && <button type="button" className="settings-remove-profile" onClick={removeCustom} disabled={locked}>删除此配置</button>}</div>
          {selected.kind === 'codex' ? <div className="settings-codex-info"><p>使用本机已登录的 Codex CLI，模型由 CLI 配置决定。</p><p>无需在此填写 API 密钥。请先在本机完成 Codex 登录，再测试连接。</p><div className="settings-capability">参考图通过 Codex CLI 传入；实际识图能力取决于所用模型。</div></div> : <>
            {selected.preset === 'custom' && <label className="settings-field">配置名称<input value={selected.name} onChange={event => updateProfile({name: event.target.value})} disabled={locked} required maxLength={80} placeholder="例如：我的模型服务"/></label>}
            <label className="settings-field" htmlFor="settings-base-url">API 地址<input id="settings-base-url" type="url" value={selected.base_url} onChange={event => updateProfile({base_url: event.target.value})} disabled={locked} required maxLength={500} placeholder="https://api.example.com/v1" autoComplete="off" spellCheck={false}/><span>填写接口根地址，无需添加 /chat/completions。</span></label>
            <label className="settings-field" htmlFor="settings-model">模型名称<input id="settings-model" value={selected.model} onChange={event => updateProfile({model: event.target.value})} disabled={locked} required maxLength={200} placeholder="填写服务商提供的模型 ID" autoComplete="off" spellCheck={false}/></label>
            <div className="settings-field"><label htmlFor="settings-api-key">API 密钥 <span className={`settings-key-status ${secret.clear ? 'pending' : selected.has_api_key ? 'saved' : ''}`}>{secret.clear ? '保存后删除' : secret.value.trim() ? '待保存新密钥' : selected.has_api_key ? '已保存' : '未保存'}</span></label><input id="settings-api-key" type="password" value={secret.value} onChange={event => updateCredential({value: event.target.value, clear: false})} disabled={locked} placeholder={selected.has_api_key ? '留空保留已保存的密钥' : '输入 API 密钥'} autoComplete="new-password" spellCheck={false} maxLength={4096}/><span>密钥仅提交到本机服务；保存后不会回显，也不会存入浏览器。</span>{selected.has_api_key && <button type="button" className="settings-clear-key" disabled={locked} onClick={() => updateCredential({clear: !secret.clear, value: ''})}>{secret.clear ? '撤销删除密钥' : '删除已存密钥'}</button>}</div>
            <label className="settings-vision"><input type="checkbox" checked={selected.vision} onChange={event => updateProfile({vision: event.target.checked})} disabled={locked}/><span><strong>允许模型读取参考图</strong><small>需要所填模型及接口支持图片输入。此开关用于声明能力；上传参考图前请确认服务商支持。连接测试仅检查文本回复。</small></span></label>
          </>}
        </section>
      </div>
      <div className="settings-bottom">
        {feedback && <div className={`settings-feedback ${feedback.tone}`} role={feedback.tone === 'error' ? 'alert' : 'status'}>{feedback.text}</div>}
        <div className="settings-footer"><span className="settings-save-hint">{working === 'test' ? '正在测试已保存的连接，请稍候…' : dirty ? '有未保存的修改，请先保存再测试。' : '设置保存在本机。测试使用已保存的接入方式。'}</span><div><button type="button" className="button soft" disabled={locked || dirty} onClick={() => void test()}>{working === 'test' ? '正在测试…' : '测试连接'}</button><button type="submit" className="button primary" disabled={locked || !dirty}>{working === 'save' ? '正在保存…' : '保存并应用'}</button></div></div>
      </div>
    </form> : <div className="settings-load-error" role="alert">未找到可用的模型配置。</div>}
  </dialog>;
}
