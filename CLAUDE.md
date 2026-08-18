# 检定排程系统 — 算法服务 + 模块化重构

## Context

电能表检定排程与库存优化算法，当前基线为 8.17 脚本 `docs/算法脚本/检定排程/检定排程python代码_8.17.py`（引入统一码值体系 + detectSchemeId 输出，保留作为参考，**勿修改**）；
最早单文件脚本 `检定排程python代码最新8.03.py`（~564 行）亦保留作历史参考。输入/输出均硬编码 Excel。
现重构为**算法服务**，核心调度算法**零修改**迁移到 `modules/detect/`：

- **生产环境**：被计量生产调度平台通过 HTTP 调用（契约见 `docs/接口文档/接口说明.md`），JSON 入参 → JSON 出参
- **离线兑底**：命令行读 Excel 出 Excel，用于开发验证与功能等价性验证
- **输入/输出统一以 pandas DataFrame 为边界**

## 目录结构

```
深圳项目/
├── main.py                    # 全局启动脚本（HTTP 算法服务启动，`python main.py`）
├── cli.py                     # 命令行兑底脚本（Excel 兑底，离线开发/验证，`python cli.py <输入Excel> [-o 输出] [--module detect]`）
├── service.py                 # HTTP 服务启动器（向后兼容 `python service.py`）
├── config.py                  # 环境配置（仅监听地址/日志级别，供其他模块导入）
├── common/                    # 与算法无关的公共功能包
│   ├── utils.py               # 纯工具方法（clean_columns / parse_device_category，原样迁移）
│   └── logging_utils.py       # 日志统一配置（幂等 setup_logging，级别取 LOG_LEVEL 环境变量）
├── modules/                   # 算法模块注册中心（每个算法域一个自包含包）
│   ├── base.py                # AlgorithmModule 数据类（模块契约：接口路径 / reader / pipeline / writer）
│   ├── __init__.py            # all_modules() / get_module(name) 注册中心（import 即注册）
│   ├── detect/                # 检定排程模块（8.17 核心，已接入 HTTP）
│   │   ├── __init__.py        # MODULE = AlgorithmModule(...) 注册声明（interface_path 非 None）
│   │   ├── constants.py       # 接口枚举字典 + 8.16 统一码值字典（硬编码）+ SchedulingConfig + DataSourceConfig
│   │   ├── category.py        # 设备分类解析（8.16 版：中文名→VW_DETECT_EQUIP_TYPE 码 + 码值推导 helper）
│   │   ├── reader.py          # read_excel（12 sheet）/ read_json（接口 9 JSON 集合）→ 12 个 DataFrame
│   │   ├── extractor.py       # 接口数据提取器（V2.0）：请求 9 集合 + 码值映射 7 视图原样提取，无业务推断
│   │   ├── prepare.py         # process_data()（DataFrame → 填充 scheduler 全局变量，逐步日志）
│   │   ├── scheduler.py       # 核心算法（核心逻辑零修改，含详细执行日志）+ run_scheduling() + build_output_dataframes()
│   │   ├── pipeline.py        # run_pipeline()（三阶段流程 + 计时日志）
│   │   └── writer.py          # write_excel（7 DataFrame → Excel）/ write_json（→ detectPlanSchedulingchList JSON）
│   ├── arrival/               # 到货排程模块（骨架，MODULE=None，预留命名空间，未实现）
│   └── distribution/          # 配送模块（骨架，MODULE=None，预留命名空间，未实现）
├── server/                    # HTTP 服务包
│   ├── __init__.py            # create_app() 应用工厂 + run_server() 启动（threaded=False）
│   └── blueprints/__init__.py # 蓝图注册中心（通用工厂：遍历 modules 注册中心自动生成蓝图，无需逐模块新增）
├── tests/                     # 测试脚本包
│   └── test_interface.py      # 按接口文档格式的接口测试（Flask test_client）
└── docs/                      # 文档与参考文件
    ├── README.md              # 文件索引（按时间顺序）
    ├── 算法脚本/              # 原始算法脚本（勿修改）
    │   ├── 检定排程/          # 检定 8.03 / 8.06 / 8.07 / 8.11 / 8.16 / 8.17
    │   └── 到货排程/          # 到货 8.13 / 8.14
    ├── 报文/                  # 真实请求报文（0807 / 0812 等）
    ├── 导出数据/              # 码值映射字典.xlsx / 检定仓情况-20260807.xlsx / 检定数据记录文档.md 等
    ├── 样例/                  # 输入/输出样例 Excel
    └── 接口文档/              # 接口说明.md / 接口说明v2.0.md / 差异清单 / Word 版
```

## 数据流

```
生产环境（HTTP）:
  平台 ──POST 9个JSON集合──> server/blueprints（通用工厂按 modules 注册中心生成蓝图）
       ──> modules.detect.reader.read_json ──> 12个DataFrame
       ──> modules.detect.pipeline.run_pipeline()（prepare.process_data → scheduler.run_scheduling → build_output_dataframes）
       ──> modules.detect.writer.write_json ──> JSON出参 ──> 平台

离线兑底（CLI）:
  python cli.py <输入Excel路径> [-o 输出路径] [--module detect]
       ──> modules.detect.reader.read_excel ──> 12个DataFrame ──> 同一 run_pipeline()
       ──> modules.detect.writer.write_excel ──> 输出 Excel
```

CLI 与 HTTP 共用 `modules.detect.pipeline.run_pipeline()`，行为完全一致。

## 关键设计

1. **包分层**：`common`（公共功能）/ `modules`（算法域自包含包，注册中心 `modules/__init__.py`）/ `server`（接口暴露）；`config.py` 只做环境配置，业务常量按归属分放 `modules/detect/constants.py`。
2. **read_excel / read_json 返回同构 DataFrame**（`modules/detect/reader.py`）：key 与列名均与 `process_data()` 期望一致，核心算法对两条路径完全复用。
3. **接口集合 → DataFrame 映射**（`modules/detect/reader.py`）：`deviceParaList` 拆成 overall/line_info/chamber_type/chamber_config；`detectSchList` + 需求/到货 合成 spec（设备分类优先按 **detectEquipType** 推断——枚举有文档、能经 8.16 分类器推出算法认可的中文分类名；`equipCls` 在接口入参中是编码，经 VW_EQUIP_CLS 码→名兜底，仅当已是中文分类名时直接采用）；枚举码自动转名称。
4. **8.16 统一码值体系**：设备分类以 **VW_DETECT_EQUIP_TYPE 码（int）为统一键**——spec / chambers / demand 三处分类身份以码对齐（修复 8.11「spec 为 三相直接表、chambers 键为折叠 三相电能表 → 不匹配 → 三相排程失败」）；`dev_code_to_cat` 存码 + 并行映射 `dev_code_to_cat_name` 存中文名；`spec_time` / `chambers.capacity` 均以码为键。出参码值：`equipCls`=VW_EQUIP_CLS 码、`equipCateg`=VW_EQUIP_CATEG 码、`deviceType`=VW_DEVICE_TYPE 码（`检定仓类型编码` 取 `chamber_type_id_map`，仓类型ID 即码，**不采用 8.16 的仓类型名称→码反查**——仓类型名称有三套口径，反查必失败）。码值映射全部硬编码在 `modules/detect/constants.py`（8.16 L33-103 原文 + 接口 v2.0 §2 字典），不读外部 xlsx。
5. **接入方式推断**：接口无"接入方式"字段，从 detectEquipType 编码推断（11-14=经互感，15-18=直接），用于仓类型 5 的终端过滤规则。
6. **出参缺口字段**：`equipDesc` / `weekDayStartAndEnd` 接口要求但算法不生产，暂返回空字符串，待企业确认口径（`equipCateg` 已按 8.16 填码）；`detectSchemeId` 8.17 起已生产——来源 spec.参数标识（JSON 路径 = detectSchList.detectSchemeId），`get_detect_scheme_id()` 含大小码回退（`dev_code_to_big_code`），查不到返回空串（与 8.17 原脚本一致）。
7. **串行同步**：算法串行同步运行、使用模块级全局变量（有状态、非重入），不支持并发/异步；server 以单线程模式启动（`threaded=False`，见 `server.run_server`），请求按到达顺序天然串行处理，切勿用多线程/多进程 WSGI 部署。
8. **日志与异常**：`common/logging_utils.setup_logging()` 幂等配置（级别取 `LOG_LEVEL` 环境变量）；算法执行流程有详细日志——pipeline 记录三阶段里程碑与耗时、prepare 记录各准备步骤规模、scheduler 记录按月/设备/批次的调度决策，子任务级明细用 DEBUG（`LOG_LEVEL=DEBUG` 开启）；**数据与计算问题均以 WARNING 留痕**——数据层（reader/prepare）：spec 设备码无法推断分类（缺 detectEquipType 且缺 equipCls / equipCls 兜底不被分类体系识别）、无分类设备带 schTime 无法归属、需求设备码无法建立分类映射；计算层（scheduler）：批次耗尽仍欠缺口、批次无分类/无对应仓被跳过、未生成任何子任务；仓行跳过原因 / 默认时长与子类型回退 / 无分类设备码映射为空 等明细用 DEBUG；**所有报错均打印完整异常调用栈**（统一用 `logger.exception`，`read_excel` 用 `raise ... from e` 保留原始链）；server 异常记录完整堆栈后返回 `resultFlag=0` + `errorInfo`（接口契约仅返回错误消息，不泄漏堆栈）；空排程明细时 `build_output_dataframes` 返回空表而非报错。
9. **编号类型统一**：线体编号等转 int，保证 `chambers` key 与 `line_name_map` / `chamber_config` 一致。
10. **模块可扩展**：新增算法模块 = 新建 `modules/<域>/` 包 + 声明 `MODULE = AlgorithmModule(interface_path=...)`，`server/blueprints` 通用工厂按 `modules.all_modules()` 自动生成蓝图，无需改动 server/cli 本体（骨架模块 `MODULE=None` 不注册）。
11. **路径操作统一 pathlib**：所有文件/路径操作用 `pathlib.Path`（读入 `read_excel(file_path: Path)`、写出 `write_excel(..., output_path: Path)`、配置 `DataSourceConfig.output_path`、测试根目录定位），不用 `os.path`；CLI 入口处把 argparse 字符串参数转为 `Path`。

## 启动方式

```
# HTTP 服务（生产）——无参数直接启动，监听默认 0.0.0.0:5000
python main.py
# 或显式 serve 子命令 / 向后兼容 service.py
python main.py serve
SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py serve
SERVER_HOST=10.x.x.x SERVER_PORT=8080 python service.py

# 离线兑底
python cli.py <输入Excel路径> [-o 输出Excel路径]

# 接口测试（无需启动服务器）
python tests/test_interface.py
```

## 测试

```
python tests/test_interface.py
```
按 `docs/接口文档/接口说明.md` 格式构造 9 集合入参，校验出参字段、值、总量；覆盖空请求体、缺集合、非法 JSON 场景。

## 待企业方确认

- 部署 IP / 端口（通过环境变量 `SERVER_HOST` / `SERVER_PORT` 配置，如 `SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py serve`）
- 出参缺口 2 字段的口径（`equipDesc` / `weekDayStartAndEnd`）
- `detectSchList` 若某设备码缺失 `schTime` 的兜底值
- 已知项（`docs/导出数据/检定数据记录文档.md` §2-C）：VW_DETECT_EQUIP_TYPE 码 12/13/16/17 转出的 负荷管理终端/配变监测计量终端 不在 8.16 分类关键词集内，对应仓会被静默跳过——待算法负责人确认是否补关键词
