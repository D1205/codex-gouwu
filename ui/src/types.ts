export type Parameter = {value: number | null; unit: string | null; source_id: string | null; confirmed: boolean};
export type Feature = {id: string; operation: 'add' | 'cut'; profile: {kind: 'circle' | 'rectangle' | 'polygon'; [key: string]: unknown}; pattern?: {kind: 'circular' | 'linear'; [key: string]: unknown} | null; [key: string]: unknown};
export type Task = {schema_version: string; task_id: string; revision: number; action: 'create' | 'modify'; family: string; goal: string; parameters: Record<string, Parameter>; features?: Feature[]; sources: Array<{id: string; kind: string; reference: string}>; hard_constraints: Record<string, number>; baseline: {revision: number; semantic_hash: string} | null; [key: string]: unknown};
export type Marker = {feature_id: string; parameter_id: string; position_mm: [number, number, number]};
export type Mapping = {task_id: string; revision: number; semantic_hash: string; units: string; native_sha256: string; instance_id?: string; parameters: Array<{parameter_id: string; name: string; value?: number; unit?: string; value_mm?: number}>; markers: Marker[]};
export type Selection = {task_id: string; revision: number; semantic_hash: string; parameter_id: string; parameter_name: string; feature_id?: string; instance_id?: string};
export type Asset = {kind: string; url: string; filename: string};
export type CadResult = {status: string; revision?: number; checks: Array<{id: string; status: string; actual?: unknown; expected?: unknown}>; mapping?: Mapping; visual_review?: {status: string; reviewer?: string; notes?: string}; error?: unknown};
export type ModelView = {status: string; job_id?: string; pending_job_id?: string | null; state?: {task_id: string; revision: number; semantic_hash: string; task: Task; job_id?: string}; result?: CadResult; assets?: Asset[]};
export type CandidateParameter = {name: string; value: number | null; unit: string | null; source_kind: string; source_reference: string | null; confirmed: boolean};
export type DraftResult = {status: 'ready' | 'needs_input' | 'failed'; task: Task | null; candidate?: {family?: string; goal?: string; parameters?: CandidateParameter[]; features?: Feature[]} | null; questions: string[]; conflicts: string[]; unsupported_requirements: string[]; error?: {message?: string; code?: string}; evidence_dir?: string};
export const parameterLabels: Record<string, string> = {
  length: '长度', width: '宽度', height: '高度 / 厚度', depth: '深度', thickness: '厚度', wall: '侧壁 / 底厚',
  diameter: '直径', radius: '半径', outer_diameter: '外径', inner_diameter: '内径', bore_diameter: '中心孔径',
  hole_diameter: '孔直径', hole_margin: '孔中心边距', hole_count: '孔数量', bolt_circle_diameter: '孔分布圆直径',
  start_angle: '起始角度', first_hole_angle: '首孔角度', angle: '角度', angle_deg: '角度', count: '数量', bolt_count: '螺栓孔数量', pitch: '间距',
  shaft_diameter: '轴直径', shaft_length: '轴长度', shoulder_diameter: '轴肩直径', shoulder_length: '轴肩长度',
  step_diameter: '台阶直径', step_length: '台阶长度', flange_diameter: '法兰外径', flange_thickness: '法兰厚度',
  hole_pitch: '孔距', left_hole_x: '左侧孔列横向位置',
};
const parameterSubjects: Record<string, string> = {
  top_right: '右上', top_left: '左上', bottom_right: '右下', bottom_left: '左下', upper_right: '右上', upper_left: '左上', lower_right: '右下', lower_left: '左下',
  bolt_circle: '孔分布圆', rectangular_opening: '矩形开口', circular_opening: '圆形开口', rectangular_slot: '矩形槽', mounting_hole: '安装孔', through_hole: '贯穿孔', blind_hole: '盲孔',
  outer: '外侧', inner: '内侧', left: '左侧', right: '右侧', top: '顶部', bottom: '底部', upper: '上部', lower: '下部', front: '前侧', back: '后侧', center: '中心', central: '中心',
  hole: '孔', holes: '孔', bore: '中心孔', opening: '开口', slot: '槽', pocket: '凹槽', recess: '凹槽', notch: '缺口', cutout: '开口', chamfer: '削角', fillet: '圆角', edge: '边缘',
  shaft: '轴', shoulder: '轴肩', step: '台阶', flange: '法兰', boss: '凸台', rib: '加强筋', wall: '壁', base: '底座', body: '主体', plate: '板', outline: '外轮廓', feature: '特征',
  first: '第一', second: '第二', third: '第三', horizontal: '水平', vertical: '竖直', row: '排', column: '列', pattern: '阵列',
};
function parameterSubject(name: string) {
  const words = name.split('_');
  let result = '';
  for (let index = 0; index < words.length;) {
    let consumed = 0;
    for (let length = Math.min(3, words.length - index); length > 0; length--) {
      const phrase = parameterSubjects[words.slice(index, index + length).join('_')];
      if (phrase) {result += phrase; consumed = length; break;}
    }
    if (consumed) index += consumed;
    else {result += /^\d+$/.test(words[index]) ? words[index] : result.endsWith('自定义结构') ? '' : '自定义结构'; index++;}
  }
  return result;
}
export function parameterLabel(name: string) {
  if (parameterLabels[name]) return parameterLabels[name];
  if (/[\u3400-\u9fff]/.test(name)) return name;
  const normalised = name.replace(/([a-z\d])([A-Z])/g, '$1_$2').toLowerCase();
  const overall = normalised.match(/^(?:overall|total)_(width|height|length|thickness|depth)$/);
  if (overall) return `总${({width: '宽', height: '高', length: '长', thickness: '厚', depth: '深'} as Record<string, string>)[overall[1]]}`;
  const compound = normalised.match(/^(.+)_(outer_diameter|inner_diameter|diameter|radius|width|height|length|thickness|depth|count|pitch|spacing|angle_deg|angle|offset|margin|x|y|z)$/);
  if (!compound) return '自定义参数';
  const subject = parameterSubject(compound[1]);
  const measure = compound[2];
  if (['x', 'y', 'z'].includes(measure)) {
    const isChamfer = compound[1].endsWith('chamfer');
    return subject + (isChamfer ? ({x: '水平尺寸', y: '竖直尺寸', z: '深度尺寸'} as Record<string, string>)[measure] : ({x: '横向位置', y: '纵向位置', z: '高度位置'} as Record<string, string>)[measure]);
  }
  if (subject.endsWith('孔') && measure === 'diameter') return `${subject}径`;
  if (subject.endsWith('孔') && measure === 'depth') return `${subject}深`;
  const measures: Record<string, string> = {outer_diameter: '外径', inner_diameter: '内径', diameter: '直径', radius: '半径', width: '宽度', height: '高度', length: '长度', thickness: '厚度', depth: '深度', count: '数量', pitch: '间距', spacing: '间距', angle_deg: '角度', angle: '角度', offset: '偏移', margin: '边距'};
  return subject + measures[measure];
}
export const familyLabels: Record<string, string> = {plate: '板件', bracket: '支架', box: '盒体', flange: '圆形法兰盘', circular_flange: '圆形法兰盘', shaft: '轴', stepped_shaft: '阶梯轴', sleeve: '套筒', washer: '垫圈', disk: '圆盘', disc: '圆盘', block: '矩形块', rectangular_block: '矩形块'};
export const familyLabel = (name: string) => familyLabels[name] || '自定义零件';
export const sourceLabels: Record<string, string> = {user: '你提供的', rule: '规则建议', derived: '软件推导', cad: '模型读回', spec: '规格资料'};
export const unitLabel = (unit: string | null) => unit === 'deg' ? '°' : unit === 'count' ? '个' : unit || '单位待补';
export function parameterChanged(previous: Parameter, next: Parameter) {
  const scales: Record<string, number> = {mm: 1, cm: 10, m: 1000};
  if (previous.value === null || next.value === null) return previous.value !== next.value || previous.unit !== next.unit;
  if (previous.unit && next.unit && scales[previous.unit] && scales[next.unit]) return Math.abs(previous.value * scales[previous.unit] - next.value * scales[next.unit]) > 1e-9;
  return previous.unit !== next.unit || previous.value !== next.value;
}
export function featureDescription(feature: Feature) {
  const profile = {circle: '圆形', rectangle: '矩形', polygon: '多边形'}[feature.profile.kind];
  const action = feature.operation === 'cut' ? `沿 Z 方向切除${profile}截面材料` : `沿 Z 方向添加${profile}截面实体`;
  const pattern = feature.pattern ? feature.pattern.kind === 'circular' ? '，沿圆周重复排列' : '，沿直线重复排列' : '';
  return action + pattern;
}
