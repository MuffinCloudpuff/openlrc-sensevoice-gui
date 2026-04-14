# PySide6 迁移方案

## 文档目的

这份文档用于说明：如何把当前基于 Streamlit 的 GUI 迁移到 PySide6，同时尽量保持现有页面布局和用户操作流程不变。

这次迁移的重点不是重做产品，也不是重新设计界面。
重点是替换 GUI 框架，并把现有逻辑整理成更适合桌面应用的结构。

## 当前问题

这个项目本质上是一个 Windows 本地工具，但现在的主界面是用 Streamlit 写的。

这种组合会持续带来一些不顺手的问题：

- 选择本地目录不自然
- widget 状态受 Streamlit rerun 机制限制
- 长时间运行的 ASR 和翻译任务不容易稳定管理
- 进度、日志、确认状态都耦合在单页面反复重跑的逻辑里
- `openlrc/gui_streamlit/home.py` 现在同时承担了界面、状态、参数校验、任务编排、日志和执行流程

这并不代表项目不能继续维护，但会让日常 GUI 修改变得比必要的更脆弱。

## 迁移目标

把 GUI 层从 Streamlit 迁移到 PySide6，并尽量保留以下行为不变：

- 当前整体页面布局
- 当前左侧配置分组
- 当前目录批处理工作流
- 当前 `.openlrc_cache` 复用逻辑
- 当前翻译前确认流程
- 当前 `.lrc` 输出到源文件旁边的行为

如果不是为了把 UI 和后端逻辑解耦，就不要随意修改核心处理流程。

## 非目标

第一阶段不做这些事情：

- 不重设计界面
- 不调整现有业务流程
- 不增加时间轴编辑、波形编辑
- 不改造成 Web 架构
- 不引入插件系统或复杂 GUI 框架
- 不重写 ASR 或翻译核心流程

## 可行性评估

可行性评分：`8/10`

原因：

- 项目本身就是本地优先，和 PySide6 的适配度较高
- 目录选择、进度展示、日志展示、任务控制都更符合桌面 GUI 的能力边界
- 核心后端模块，例如 `openlrc/directory_workflow.py`，已经具备一定复用价值
- 真正难的不是画界面，而是把 `openlrc/gui_streamlit/home.py` 里的编排逻辑拆出来

本次迁移的主要风险不是 PySide6 本身。
主要风险是把过多 Streamlit 风格的逻辑原样搬进新的桌面界面。

## 需要保持的页面布局

第一阶段应尽量保持和当前 Streamlit 页面一致的信息结构。

目标布局如下：

- 左侧配置区
  - ASR
  - 翻译
  - 费用与性能
  - 输出与高级
- 主内容区
  - 步骤 1：根目录与任务参数
  - 步骤 2：任务摘要
  - 步骤 3：翻译确认
  - 处理进度
  - 实时日志

也就是说，桌面版在第一阶段应该是“把当前页面翻译成原生控件”，而不是做一个全新的产品界面。

## 推荐技术方向

建议使用 `PySide6` 作为 GUI 外壳，继续复用当前已有的处理逻辑。

推荐技术组合：

- GUI：`PySide6`
- 后台执行：`QThread` + worker `QObject`
- 日志桥接：Python `logging.Handler` + Qt signal
- 配置持久化：继续使用当前 JSON 配置文件
- 处理核心：继续使用现有 `openlrc` 后端模块

不要把核心业务逻辑直接塞进 `QMainWindow`。

## 目标目录结构

建议新增一个桌面 GUI 包：

```text
openlrc/
  gui_qt/
    __init__.py
    app.py
    main_window.py
    config_store.py
    models.py
    signals.py
    widgets/
      config_panel.py
      task_panel.py
      confirmation_dialog.py
      log_panel.py
      summary_panel.py
    workers/
      process_worker.py
      model_detect_worker.py
    services/
      orchestrator.py
      validation.py
      runtime_context.py
      log_bridge.py
```

各层职责建议如下：

- `main_window.py`
  - 主窗口和主要控件拼装
- `widgets/`
  - 页面各个区域的原生控件封装
- `services/orchestrator.py`
  - 负责目录扫描、ASR、翻译、导出等流程编排
- `workers/`
  - 负责长任务后台执行
- `config_store.py`
  - 负责 `.openlrc_gui_config.json` 读写
- `validation.py`
  - 统一管理参数校验规则

## 哪些部分应当继续复用

这些模块应继续作为后端行为的主要来源：

- `openlrc/directory_workflow.py`
- `openlrc` 下现有处理类，例如 `LRCer`、`TranscriptionConfig`、`TranslationConfig`
- 当前 `.openlrc_gui_config.json` 配置格式
- 当前 `<root>/.openlrc_cache/` 缓存布局

这些内容不应作为最终架构保留，而应作为拆分来源：

- `openlrc/gui_streamlit/home.py`

## 在做 UI 迁移前必须先做的拆分

在写 PySide6 界面之前，应先从 `openlrc/gui_streamlit/home.py` 中抽出这些职责：

- 配置加载与保存
- 参数规范化
- 参数校验
- 翻译确认状态构建
- 任务编排
- 进度上报
- 日志文件初始化
- 模型探测调用

这样做的目标是先得到一组不依赖 Streamlit 的服务层逻辑，让 Streamlit 和 PySide6 在过渡期都可以调用同一套后端。

## Streamlit 控件到 PySide6 控件的映射

桌面版保持布局，但控件实现建议替换如下：

| 当前 Streamlit 行为 | PySide6 替代方案 |
|---|---|
| 侧边栏配置面板 | 左侧固定面板或 dock |
| 根目录文本框 | `QLineEdit` |
| 目录选择按钮 | `QFileDialog.getExistingDirectory` |
| selectbox | `QComboBox` |
| checkbox | `QCheckBox` |
| slider | `QSlider` 或 `QSpinBox` |
| 任务摘要卡片 | `QFrame` + layout |
| 多选翻译确认 | `QDialog` + 可勾选列表或表格 |
| 进度条 | `QProgressBar` |
| 实时日志框 | `QPlainTextEdit` |
| expander | `QGroupBox` 或折叠控件 |

## 任务编排模型

桌面版应该改成显式事件驱动，而不是继续沿用 Streamlit 的 rerun 驱动模型。

建议流程如下：

1. 用户修改左侧配置项。
2. 界面更新本地表单状态。
3. 用户点击扫描，触发目录扫描服务。
4. 用户点击开始处理，先进行参数校验。
5. 如果需要翻译确认，则弹出确认对话框。
6. 确认后启动后台 worker。
7. worker 通过 signal 持续发出：
   - 阶段变化
   - 文件级进度
   - 费用估算
   - 日志输出
   - 成功结果
   - 失败结果
8. 主线程只负责刷新界面。

这样就不再需要 Streamlit 风格的 `session_state` 管理。

## Worker 设计建议

第一阶段建议先只做一个主处理 worker。

这个 worker 的职责应包括：

- 接收一份冻结后的运行配置
- 执行目录扫描、ASR 缓存复用检查、ASR、翻译估算、翻译确认后的翻译和导出
- 发出进度事件
- 发出任务状态更新
- 发出日志事件
- 发出最终成功或失败结果

worker 不要直接访问任何 widget。
所有 UI 更新都必须通过 Qt signal 回到主线程处理。

## 日志方案

建议增加一个面向 Qt 的日志桥接层：

- 文件日志仍然保留，方便调试
- 增加一个自定义 `logging.Handler`
- 把格式化后的日志通过 signal 发送给主线程
- 主线程把日志追加到实时日志面板

这比继续模仿 Streamlit 的“读日志尾部”方式更适合桌面程序。

## 配置策略

建议继续沿用当前的配置文件路径和大部分字段名：

- `.openlrc_gui_config.json`

这样做的好处：

- 迁移期间兼容现有用户配置
- Streamlit 和 PySide6 可以短期并存
- 降低迁移时的心智负担

如果后续需要调整字段，建议在 `config_store.py` 里做兼容迁移，而不是修改每一个调用点。

## 分阶段实施方案

### 第一阶段：后端逻辑拆分

交付内容：

- 与 GUI 框架无关的配置读写模块
- 与 GUI 框架无关的参数校验模块
- 与 GUI 框架无关的任务编排服务
- 统一的运行配置对象
- 统一的进度与结果事件结构

完成标准：

- 当前处理流程可以在不依赖 Streamlit widget 的情况下被调用

### 第二阶段：PySide6 窗口骨架

交付内容：

- `QMainWindow` 主窗口
- 左侧配置区
- 根目录选择区域
- 任务摘要区
- 任务列表区
- 日志区
- 已连接基础事件的开始按钮

完成标准：

- 桌面窗口能以当前页面布局为参考搭出完整框架

### 第三阶段：接入真实处理流程

交付内容：

- 根目录扫描
- 基于 `scan_directory` 的任务表展示
- 基于 worker 线程的开始处理流程
- 进度刷新
- 实时日志输出
- 完成与失败状态展示

完成标准：

- 用户可以在 PySide6 中完成和当前 Streamlit 一致的主流程

### 第四阶段：翻译确认对齐

交付内容：

- 文件级费用估算
- 翻译确认对话框
- 只翻译选中文件的流程

完成标准：

- 第 3 步翻译确认流程与当前产品目标一致

### 第五阶段：打包与切换

交付内容：

- 桌面版启动入口
- 可选的 Windows 打包方案
- 是否保留 Streamlit 作为备用界面的决定

完成标准：

- PySide6 成为本地 GUI 的首选入口

## 主要风险与应对

### 风险 1：把 `home.py` 的杂糅逻辑原样搬进桌面窗口

问题：

如果只是换框架，不拆逻辑，那么只是把维护问题从 Streamlit 挪到 PySide6。

应对：

- 先拆编排服务，再做窗口
- 保持 `QMainWindow` 足够薄
- 明确定义服务接口和事件结构

### 风险 2：长任务阻塞主线程

问题：

如果 ASR 或翻译直接跑在主线程，桌面界面会卡死。

应对：

- 长任务统一放进 `QThread`
- worker 不直接操作控件
- 所有状态更新通过 signal 发送

### 风险 3：迁移时顺手重做 UX

问题：

如果在迁移期同时改布局和流程，范围会迅速失控，也不利于验证回归。

应对：

- 第一阶段严格保持当前布局
- 功能对齐完成后，再单独讨论界面优化

## 建议结论

建议采用下面这条路径：

1. 保持当前页面布局不变
2. 先把 Streamlit 中的编排逻辑抽出来
3. 再做一个布局近似当前页面的 PySide6 外壳
4. 先做到功能对齐
5. 最后再考虑体验优化

这条路径风险最低，也最适合当前项目状态。

## 验收标准

满足以下条件时，可以认为迁移成功：

- 桌面版保留当前页面布局和工作流结构
- 用户可以通过原生目录选择器选择根目录
- 扫描和缓存复用行为与当前一致
- 翻译前仍然存在确认步骤
- 日志和进度可以实时刷新，且界面不会卡死
- `.lrc` 仍然输出到源文件旁边
- 核心处理逻辑不再依赖 Streamlit 状态模型

## 建议的实际落地顺序

建议按以下顺序开始做：

1. 新建 `openlrc/gui_qt/`
2. 从 `home.py` 拆出配置和参数校验
3. 拆出任务编排和事件结构
4. 搭建主窗口，布局对齐当前页面
5. 接入目录扫描
6. 接入后台 worker
7. 接入翻译确认对话框
8. 对照当前 Streamlit 工作流做功能回归

## 文档路径

本方案文档保存在：

```text
PYSIDE6_MIGRATION_PLAN.md
```

除非后续出现更细化的实施文档，否则这份文件可以作为当前迁移工作的基线说明。
