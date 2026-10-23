# 本机设计台 HTTP API v1

对应实现为 `mechanical_app/server.py`。浏览器界面与桌面启动程序共用 `DesignService`、工程规则和真实模型/CAD 适配器。默认地址为 `http://127.0.0.1:8777`，只监听 `127.0.0.1`。

请求和返回的 JSON 使用 UTF-8。POST 要求 `Content-Type: application/json`、顶层对象和非空请求体。普通接口上限为 1 MiB；仅 `POST /api/reference-images` 允许最大 12 MiB 的 JSON 请求体，以容纳图片的 base64 编码。Host 仅接受当前端口的 `127.0.0.1` 或 `localhost`；Origin 如存在，仅接受当前服务和本机 `5175`。Vite 代理需要 `changeOrigin:true`，将 Host 改为后端端口。模型 API 密钥只允许经设置 POST 写入，由 Windows DPAPI 加密；设置 GET、模型记录及浏览器持久存储不包含密钥。Codex CLI 继续使用本机登录。

## 端点

| 方法与路径 | 输入 | 返回与作用 |
| --- | --- | --- |
| `GET /api/health` | 无 | `app,status,scope,transport`，用于确认服务身份；不证明模型或 SolidWorks 可用 |
| `GET /api/settings` | 无 | 配置版本、当前配置 ID、提供方列表和预设；密钥只返回 `has_api_key` |
| `POST /api/settings` | `active_profile_id,profiles` | 保存并返回公开设置，详见下文 |
| `POST /api/settings/test` | `{}` | 异步测试当前已保存配置；返回 operation ID，不执行 CAD |
| `GET /api/current` | 可选查询 `task_id` | 已发布模型、公开结果、资产和 `pending_job_id` |
| `GET /api/job/<job_id>` | 服务产生的 job ID | 指定执行的候选或已发布模型视图；未产生结果时仅返回状态/错误 |
| `POST /api/reference-images` | `{name,data_url}` | 同步上传并净化参考图，直接返回公开图片对象 |
| `GET /api/reference-images/<id>` | 上传返回的图片 ID | 重验登记和文件指纹，返回规范化 PNG；服务重启后仍可读取 |
| `POST /api/interpret` | `brief,current_task,selection,image_ids,conversation` | 异步需求整理，返回 operation ID；图片与上下文均可省略 |
| `POST /api/validate` | `{task}` | 同步规则校验，成功返回 `{status:"ready",plan}`；不执行 CAD、不推进台账 |
| `POST /api/run` | `{task}` | 本地编译通过后串行提交真实 CAD 执行，返回 operation ID |
| `POST /api/review` | `job_id,approved,reviewer,notes` | 异步登记人工看图结论并发布或退回 |
| `GET /api/operations/<operation_id>` | 当前进程中的 operation ID | `running/done/failed`；结束时含结果或错误 |
| `GET /api/artifacts/<sha256>` | 前序模型视图登记的资产 ID | 读取白名单文件，读取前校验文件大小和 SHA-256 |

同一服务进程一次只接受一个未结束的异步操作；繁忙时返回 HTTP 409。静态页面由 `ui/dist` 提供，静态路径必须在该目录内。

## 模型设置

设置格式为 `{version:1,active_profile_id,profiles,presets}`。每个公开配置包含 `id,name,kind,preset,base_url,model,vision,has_api_key`。`kind` 为 `codex` 或 `openai_compatible`；后者调用用户指定服务的 Chat Completions 接口，要求支持 JSON 对象输出。接口地址填写 API 根地址，例如 `https://api.deepseek.com` 或兼容服务的 `https://example.com/v1`，程序附加 `/chat/completions`。只接受 HTTPS；本机回环服务可用 HTTP。地址不得夹带账号、密码、查询串或片段。

保存请求提交完整 `profiles` 数组和 `active_profile_id`；各配置可附加只写的 `api_key`。省略或空值保留该配置原密钥，`clear_api_key:true` 显式删除。密钥按配置独立保存，切换提供方不会将另一配置的密钥带过去。配置文件默认位于 `%LOCALAPPDATA%/CodexGouwu/settings.json`，不能复制到其他 Windows 用户后直接解密。

测试成功结果含 `ok:true,status:"ready",provider,model,message` 及安全运行信息；失败为 operation 的 `failed` 与经过处理的错误。测试只验证当前已保存模型的最小文字请求；图片支持开关是用户配置的能力声明，不能以连接测试成功推断视觉能力通过。

`interpret` 排队前取得配置快照，期间保存设置只影响后续请求。所有提供方共用技能锁、输出契约、尺寸来源、图片待确认规则和本地几何门禁。调用失败会保留具体错误，不会自动改用其他提供方。密钥只从后端发给对应接口；前端发送的需求不包含密钥。

## 已发布模型与候选模型

`GET /api/current` 未指定 `task_id` 时，选择修改时间最新的已发布设计。指定时读取该设计。存在待审阅候选时返回 `pending_job_id`；没有已发布模型也可以有待审阅候选。

模型视图结构：

| 字段 | 定义 |
| --- | --- |
| `status` | current 为 `ready/empty`；job 为执行回执状态，如 `review_required/passed/failed` |
| `state` | `task_id,revision,semantic_hash,task`；空状态为 `null` |
| `result` | 公开的 `status,checks,mapping,visual_review,not_covered,geometry` 等实际存在字段；空状态为 `null` |
| `assets` | 公开产物数组，每项 `kind,url,filename,sha256,size_bytes` |
| `job_id` | 产生这份结果的执行任务；empty 响应不包含此字段 |
| `pending_job_id` | current 响应中的待审阅 job ID，没有时为 `null` |

公开 `result.artifacts` 与 `assets` 使用相同资产格式。客户端只使用服务返回的 `url`，不拼接服务器文件路径。`mapping` 带修订、语义指纹、毫米单位、原生模型指纹、参数与标记。v2 的映射参数含 `value/unit`，长度参数还可含兼容的 `value_mm`；角度和数量不能当作毫米。STL 没有自描述单位，UI 必须结合映射整体的 `units:mm`，以毫米、右手系、Z-up 显示。

刷新后先读取 current，再用 `pending_job_id` 请求 job，以恢复待审阅预览。候选视图与已发布 current 分开显示；读取、预览和下载都不会发布版本。

## 自然语言与澄清

新建请求示例：

```json
{
  "brief": "做一个外径100毫米、厚10毫米的圆形法兰盘，中心孔直径30毫米，在直径75毫米分布圆上均布6个直径8毫米贯穿孔，第一个孔位于X正方向。",
  "current_task": null,
  "selection": null,
  "image_ids": [],
  "conversation": []
}
```

`brief` 为字符串，长度不超过 20,000 字符；至少需要非空文字或一张已上传参考图。仅图片时可以省略 `brief` 或传空字符串，服务会使用“根据参考图整理需求并追问缺项”的中文请求。`image_ids` 默认为 `[]`，必须是本服务登记的 ID 数组，最多 6 张且不得重复；任意路径、外部 URL、未登记 ID 或篡改的图像都会在排队前被拒绝。

`conversation` 可省略或为 `null`/`[]`，用于理解前一轮问题与选项，格式为 `[{"role":"assistant","text":"请补充外径。"},{"role":"user","text":"外径100毫米。"}]`。最多 80 条，每条 `text` 最多 10,000 字符，总计最多 40,000 字符；只接受 `user/assistant` 角色，转发前仅保留 `role,text`。上下文不提供额外指令权限，助手给出的尺寸不能作为用户确认；用户的数字确认仍须累计在 `brief` 中，或来自已确认的修改基线。

`interpret` 的异步业务结果与 `agent.py` 一致：

- `ready`：有就绪 `task`，等待用户核对；不自动执行。
- `needs_input`：有追问或冲突，关键未知参数保留 `null`，不能生成；`task` 也可能为 `null`，此时只能展示本次 `candidate` 草稿。
- `failed`：真实调用、结构解析或规则环节失败，含错误与证据位置；不能退回预录结果当作成功。

结果还包含 `questions,conflicts,unsupported_requirements,candidate,error,runtime,skill,evidence_dir`。`candidate.parameters` 为带 `name,value,unit,source_kind,source_reference,confirmed` 的数组，任务书中的 `task.parameters` 为按名称索引的对象；v2 候选与任务另含 `features`。UI 动态显示全部返回参数、来源和待补状态，并将增料、切除、阵列特征解释为中文建模步骤。模型输出候选由本地严格契约和工程规则决定是否就绪，模型不能自行声称 CAD 已通过。

新建澄清需要累计原始需求，例如将“补充：孔均布在直径75毫米的分布圆上”追加至 brief 后再次提交，`current_task` 仍为 `null`。未完成草稿不能作为已发布修改基线。整理中、失败或 `task:null` 时，需求卡不能回退显示上一模型的 task；旧三维模型可保留，但需明确标注“上一已发布模型”，其检查和文件也属于上一模型。

修改请求的 `current_task` 必须与台账中当前已发布 task 完全一致，服务同时检查当前证据。可选 `selection` 至少关联 `task_id,revision,semantic_hash,parameter_id`；完整语义路径的末段必须是已知参数名，UI 还可附 `parameter_name,feature_id,instance_id`。过期选择会被拒绝。

旧 v1 四孔模板的四个 marker 共同关联 `hole_diameter`，一次孔径修改同步四孔。其他任务按各自标记的 `parameter_id` 关联参数，不能统一标成“四个孔”。标记不是任意面的 CAD 拾取能力，网格 UUID 不能作为工程对象身份。

## 参考图上传与读取

上传 JSON 为 `{"name":"零件照片.jpg","data_url":"data:image/jpeg;base64,<实际编码>"}`。仅接受 PNG、JPEG、WebP 的 base64 data URL；原图单张最大 8 MiB、最多 20,000,000 像素，动画或多帧文件不接受。服务会实际解码、纠正方向、按比例将长边缩至不超过 4096 像素，并保存去除元数据的 RGB/RGBA PNG。返回的宽高对应处理后的模型输入，`size_bytes` 对应该 PNG 文件；JPEG 转 PNG 后大小可能增加。

返回值直接是以下对象，外层没有 `image` 或 `data` 包装：

```json
{
  "id": "<规范化PNG的64位小写SHA-256>",
  "name": "零件照片.jpg",
  "mime_type": "image/png",
  "width": 1200,
  "height": 800,
  "size_bytes": 123456,
  "sha256": "<与id相同>",
  "url": "/api/reference-images/<id>"
}
```

示例数值只展示字段格式。`name` 保留安全的原始文件名，仅作展示；下载内容始终为 PNG。相同规范化字节去重并沿用第一次登记名称。服务只返回 URL 和元数据，不返回本地路径。图片保存于应用存储的 `reference-images/`；读取时验证登记、文件归属、大小、SHA、格式与宽高。未登记或变更的图片 GET 返回 409，错误上传或解释引用返回 400。

传给模型的是本次解释证据目录中的已核验图像快照，通过真实 Codex CLI 的 `--image` 附件参数发送。图片形状和标注用于提出需求；图像比例或 OCR 数字不能自动变成已确认工程尺寸，也不能冒充 `cad/spec` 来源。具体处理与确认规则见 [REFERENCE-IMAGES-v1.md](REFERENCE-IMAGES-v1.md)。

## 异步操作与执行状态

interpret、run 和 review 接受后返回：

```json
{"operation_id":"<服务生成的ID>","status":"running"}
```

客户端轮询对应 operation。`done` 表示函数返回，业务 `result.status` 仍需单独检查；例如真实 CAD 失败可以表现为 operation `done`、result `failed`。operation 自身异常为 `failed` 并带 `error`。

operation ID 是进程内临时状态，重启后不保留。已生成的 job、任务修订、current 和待审阅指针写入存储，重启后应通过 current/job 恢复，不重新提交同一操作冒充轮询。

run 在调度前编译规则，提交服务在串行执行锁内重新检查基线、证据和保护尺寸。带 preview 的成功执行会返回 `review_required`，包括真实数值回读、STL、原生截图与相关产物。没有 preview 的任务可以在规定交付校验通过后直接发布；UI 当前使用含 preview 的交付流程。

## 人工看图与发布

```json
{
  "job_id": "<待审阅的job ID>",
  "approved": true,
  "reviewer": "<审阅人>",
  "notes": "<实际查看原生CAD视图后的观察记录>"
}
```

`approved` 必须是布尔值，reviewer 和 notes 必须非空。用户应先查看原生 PNG 与尺寸，再提交决定；服务不根据“有截图”“生成完成”或按钮默认值推断看图通过。

发布时重新验证待审阅任务与计划指纹、当前版本与基线、活动候选身份、交付检查和文件哈希。通过后写入当前版本，视觉结果记为 `passed`。退回时保留执行记录、记为失败并清理活动候选指针，旧 current 保持。存在未处理候选时，服务阻止该设计继续提交下一修订。

## 来源、规则锁与版本约束

工程字段详见 [RULES-v1.md](RULES-v1.md)。关键执行条件包括：

- v1 保留原有三族尺寸集合；v2 不设置零件类别白名单，使用动态参数与受结构约束的特征组合。未知、缺单位、未确认、来源缺失或冲突均不能执行。
- 参数来源只支持 `user/rule/derived/cad/spec`。rule/derived 提议不能自行声明用户确认；自然语言适配保留原话引用，权威 CAD/规格来源需要相应证据。
- `rules/lock.json` 锁定技能和引用文件，规则与技能指纹必须一致；不通过模型输入更新规则。
- 新建为修订 1、无 baseline；修改引用上一已发布 `revision/semantic_hash`，并且 revision 连续。
- 本地计划统一长度为毫米，区分角度和数量；特征操作及顺序受规则约束，不接收任意代码。当前 v2 表达 XY 圆形/矩形/多边形截面沿 Z 增料或切除，以及圆周或直线阵列。
- 修改按已发布任务重建新文件，旧文件不被原位覆盖。语义哈希关联执行语义，是一致性校验，不是调用者认证或签名。

`/api/validate` 只检查输入的内部规则和技能锁，不读取权威台账完成发布级基线校验；提交与审阅阶段仍必须检查服务当前版本。

## 资产读取与错误

资产由 current/job 的实际回执登记到当前进程的白名单，文件必须位于应用存储根目录下。读取 URL 的 SHA-256 ID 必须已登记，并且当前文件仍与回执中的大小和哈希一致。变更后返回 HTTP 409；未登记返回 404，客户端可重新加载 current/job 后再读取。此接口不是任意本地文件读取口。

错误通常返回 `{"error":"说明"}`：

| HTTP 状态 | 当前用途 |
| --- | --- |
| `400` | POST JSON、参数或工程规则输入不符合要求 |
| `403` | Host/Origin 不匹配，或静态文件路径越界 |
| `404` | operation/资产/路由不存在，或未构建 UI |
| `409` | 异步操作繁忙、基线/文件冲突，或读取时检测到证据改变 |

客户端展示真实错误，繁忙时禁用重复提交，不制造进度百分比。当前检查范围是 `geometry_review`；结果不能解释为制造、强度、运动或实机认证。
