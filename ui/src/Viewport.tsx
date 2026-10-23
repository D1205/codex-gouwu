import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import type { Mapping, Selection } from './types';

type Props = {url?: string; mapping?: Mapping; selection: Selection | null; onSelect: (selection: Selection | null) => void};
type View = 'iso' | 'top' | 'front';

export default function Viewport({url, mapping, selection, onSelect}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const actions = useRef<{view: (view: View) => void; highlight: (id: string | undefined) => void} | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [phase, setPhase] = useState('等待模型');
  const [error, setError] = useState('');
  const [bounds, setBounds] = useState('');
  const [view, setView] = useState<View>('iso');

  useEffect(() => { actions.current?.highlight(selection?.parameter_id); }, [selection]);

  useEffect(() => {
    const target = host.current;
    if (!target || !url) { setPhase('等待模型'); return; }
    if (!mapping || mapping.units !== 'mm') { setError('预览缺少已确认的毫米单位映射，已停止显示。'); return; }
    let disposed = false;
    let renderer: THREE.WebGLRenderer | undefined;
    let observer: ResizeObserver | undefined;
    let controls: OrbitControls | undefined;
    let scene: THREE.Scene | undefined;
    const resources: Array<{dispose: () => void}> = [];
    setPhase('加载真实模型'); setError(''); setBounds(''); setView('iso');
    async function load() {
      const response = await fetch(url!);
      if (!response.ok) throw new Error(`STL 读取失败：HTTP ${response.status}`);
      const geometry = new STLLoader().parse(await response.arrayBuffer());
      resources.push(geometry);
      geometry.computeVertexNormals(); geometry.computeBoundingBox();
      if (disposed) { geometry.dispose(); return; }
      const box = geometry.boundingBox!;
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const radius = Math.max(size.x, size.y, size.z, 1);
      setBounds([size.x, size.y, size.z].map(value => Number(value.toFixed(2))).join(' × '));
      scene = new THREE.Scene();
      scene.background = new THREE.Color('#f2f3ee');
      const camera = new THREE.PerspectiveCamera(32, target!.clientWidth / Math.max(target!.clientHeight, 1), radius / 1000, radius * 200);
      camera.up.set(0, 0, 1);
      renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(target!.clientWidth, target!.clientHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      target!.replaceChildren(renderer.domElement);
      const material = new THREE.MeshStandardMaterial({color: '#8199ac', roughness: 0.43, metalness: 0.32});
      resources.push(material);
      scene.add(new THREE.Mesh(geometry, material));
      scene.add(new THREE.HemisphereLight(0xffffff, 0x8c9b9b, 2.6));
      const light = new THREE.DirectionalLight(0xffffff, 3.2); light.position.set(radius, -radius, radius * 2); scene.add(light);
      const fill = new THREE.DirectionalLight(0xd0ddea, 1.6); fill.position.set(-radius, radius, radius); scene.add(fill);
      const edges = new THREE.EdgesGeometry(geometry, 25);
      const edgeMaterial = new THREE.LineBasicMaterial({color: '#415b70', transparent: true, opacity: 0.27});
      resources.push(edges, edgeMaterial); scene.add(new THREE.LineSegments(edges, edgeMaterial));
      // GridHelper is Y-up by default. Rotate it onto XY; the native STL stays unchanged.
      const grid = new THREE.GridHelper(radius * 2.6, 26, 0xc7cdc8, 0xe0e4dd);
      grid.rotation.x = Math.PI / 2; grid.position.set(center.x, center.y, box.min.z - radius * .006); scene.add(grid);
      resources.push(grid.geometry);
      const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material]; resources.push(...gridMaterials);
      const axes = new THREE.AxesHelper(radius * .2); axes.position.set(box.min.x - radius * .12, box.min.y - radius * .12, box.min.z); scene.add(axes);
      resources.push(axes.geometry, ...(Array.isArray(axes.material) ? axes.material : [axes.material]));
      controls = new OrbitControls(camera, renderer.domElement);
      controls.target.copy(center); controls.enableDamping = false;
      controls.minDistance = radius * .15; controls.maxDistance = radius * 15;
      const render = () => { if (!disposed && renderer && scene) renderer.render(scene, camera); };
      controls.addEventListener('change', render);
      const markers: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>[] = [];
      for (const marker of mapping!.markers || []) {
        const sphere = new THREE.SphereGeometry(radius * .018, 18, 12);
        const markerMaterial = new THREE.MeshBasicMaterial({color: '#c47e36', depthTest: false, transparent: true, opacity: .9});
        resources.push(sphere, markerMaterial);
        const mesh = new THREE.Mesh(sphere, markerMaterial);
        mesh.position.set(...marker.position_mm); mesh.position.z += radius * .012;
        mesh.renderOrder = 3; mesh.userData.marker = marker;
        scene.add(mesh); markers.push(mesh);
      }
      const setStandardView = (view: View) => {
        const distance = radius * 2.4;
        const direction = view === 'top' ? new THREE.Vector3(.001, -.001, 1) : view === 'front' ? new THREE.Vector3(0, -1, .001) : new THREE.Vector3(1, -1.35, 1.15);
        direction.normalize().multiplyScalar(distance);
        camera.position.copy(center).add(direction); controls!.target.copy(center); controls!.update(); render();
      };
      actions.current = {
        view: setStandardView,
        highlight: id => { for (const marker of markers) { const selected = marker.userData.marker.parameter_id === id; marker.material.color.set(selected ? '#1e5368' : '#c47e36'); marker.scale.setScalar(selected ? 1.45 : 1); } render(); },
      };
      let pointerDown = {x: 0, y: 0};
      renderer.domElement.addEventListener('pointerdown', event => {pointerDown = {x: event.clientX, y: event.clientY};});
      renderer.domElement.addEventListener('click', event => {
        if (Math.hypot(pointerDown.x - event.clientX, pointerDown.y - event.clientY) > 5) return;
        const rect = renderer!.domElement.getBoundingClientRect();
        const ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
        const hit = ray.intersectObjects(markers)[0];
        if (!hit) { onSelectRef.current(null); return; }
        const marker = hit.object.userData.marker as Mapping['markers'][number];
        const parameter = mapping!.parameters.find(parameter => parameter.parameter_id === marker.parameter_id);
        onSelectRef.current({task_id: mapping!.task_id, revision: mapping!.revision, semantic_hash: mapping!.semantic_hash, instance_id: mapping!.instance_id, parameter_id: marker.parameter_id, parameter_name: parameter?.name || marker.parameter_id.split('/').at(-1)!, feature_id: marker.feature_id});
      });
      observer = new ResizeObserver(() => {
        if (!renderer || !target!.clientWidth || !target!.clientHeight) return;
        camera.aspect = target!.clientWidth / target!.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(target!.clientWidth, target!.clientHeight); render();
      });
      observer.observe(target!); setStandardView('iso'); setPhase('真实 STL · 可交互');
    }
    load().catch(error => {if (!disposed) {setError(error instanceof Error ? error.message : String(error)); setPhase('预览加载失败');}});
    return () => {disposed = true; actions.current = null; observer?.disconnect(); controls?.dispose(); for (const resource of resources) resource.dispose(); renderer?.dispose(); target.replaceChildren();};
  }, [url, mapping]);

  return <div className="viewport-shell">
    <div className="viewport-top"><span className="micro-label"><i className={error ? 'dot danger' : url ? 'dot' : 'dot neutral'}/>{phase}</span><span className="unit-label">Z ↑ · {mapping?.units === 'mm' ? 'mm' : '单位待确认'}</span></div>
    <div ref={host} className="viewport-canvas" aria-label="真实三维模型预览"/>
    {!url && <div className="viewport-placeholder"><svg width="70" height="70" viewBox="0 0 70 70" fill="none"><path d="M35 8 60 22v28L35 64 10 50V22L35 8Z" stroke="currentColor" strokeWidth="1.2"/><path d="m10 22 25 15 25-15M35 37v27" stroke="currentColor" strokeWidth="1.2"/></svg><h3>你的第一个模型，从这里开始</h3><p>先说清楚用途和尺寸，再确认工程需求。</p></div>}
    {error && <div className="viewport-error" role="alert">{error}</div>}
    <div className="viewport-bottom"><span>{bounds ? `包络 ${bounds} mm` : '仅显示实际生成的模型'}</span><span>拖动旋转 · 滚轮缩放</span></div>
    <div className="view-controls">{(['iso', 'top', 'front'] as View[]).map(item => <button type="button" className={view === item ? 'active' : ''} key={item} onClick={() => {setView(item); actions.current?.view(item);}} disabled={!url}>{({iso:'等轴测', top:'俯视', front:'正视'})[item]}</button>)}<button type="button" title="重新居中模型" onClick={() => {setView('iso'); actions.current?.view('iso');}} disabled={!url}>居中 ↗</button></div>
  </div>;
}
