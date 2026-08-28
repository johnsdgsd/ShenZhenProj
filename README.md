# 检定排程算法服务

电能表检定排程与库存优化算法服务。核心调度算法从 8.28 脚本
`docs/算法脚本/检定排程/检定排程python代码_8.28最新.py` **零修改迁移**（原脚本保留作参考，勿改），
重构为**算法服务 + 模块化代码**：

- **生产环境**：被计量生产调度平台通过 HTTP 调用，JSON 入参（9 集合）→ JSON 出参
- **离线兑底**：命令行读 Excel 出 Excel，用于开发验证与功能等价性验证
- 输入/输出统一以 pandas DataFrame 为边界，两条路径共用同一 `run_pipeline()`

> 算法**串行同步运行**、使用模块级状态（非重入），**不支持并发/异步**；服务以单线程方式启动，切勿用多线程/多进程 WSGI 部署。

---

## 一、目录结构

```
深圳项目/
├── main.py                     # HTTP 算法服务启动（python main.py / main.py serve）
├── cli.py                      # 命令行兑底（python cli.py <输入Excel> [-o 输出]）
├── service.py                  # HTTP 启动器（向后兼容 python service.py）
├── config.py                   # 环境配置（仅监听地址/日志级别，供各模块导入）
├── common/                     # 公共功能包（与算法无关）
│   ├── utils.py                # 纯工具（clean_columns 等）
│   └── logging_utils.py        # 日志统一配置（幂等 setup_logging）
├── modules/                    # 算法模块注册中心（每个算法域一个自包含包）
│   ├── base.py                 # AlgorithmModule 数据类（模块契约）
│   ├── __init__.py             # all_modules() / get_module() 注册中心
│   ├── detect/                 # 检定排程模块（8.28 核心，已接入 HTTP）
│   │   ├── __init__.py         # MODULE 注册声明（interface_path 非 None）
│   │   ├── constants.py        # 接口枚举字典 + 8.16 统一码值字典（硬编码）+ SchedulingConfig
│   │   ├── category.py         # 设备分类解析（中文名/码 双分类器）
│   │   ├── reader.py           # read_excel（12 sheet）/ read_json（9 集合）→ 12 个 DataFrame
│   │   ├── extractor.py        # 接口数据提取器（V2.0，仅提取无推断）
│   │   ├── prepare.py          # process_data()（DataFrame → 填充 scheduler 全局变量）
│   │   ├── scheduler.py        # 核心算法（核心逻辑零修改）+ run_scheduling() + build_output_dataframes()
│   │   ├── pipeline.py         # run_pipeline()（三阶段流程）
│   │   └── writer.py           # write_excel（7 DataFrame → Excel）/ write_json（→ 出参 JSON）
│   ├── arrival/                # 到货排程模块（骨架，MODULE=None，预留）
│   └── distribution/           # 配送模块（骨架，MODULE=None，预留）
├── server/                     # HTTP 服务包
│   ├── __init__.py             # create_app() 应用工厂 + run_server()（单线程）
│   └── blueprints/__init__.py  # 蓝图注册中心（通用工厂，遍历 modules 自动注册）
├── tests/                      # 测试脚本（开发验证用，发布包可不带）
├── docs/                       # 文档与参考文件
│   ├── README.md               # 文件索引
│   ├── 接口文档/               # 接口说明v2.0.md / 接口说明.md / 差异清单 / Word 版
│   ├── 报文/                   # 真实请求报文（0807 / 0812 / 0812_单请求.json 等）
│   ├── 算法脚本/               # 原始算法脚本基线（勿修改）
│   ├── 导出数据/               # 码值映射字典.xlsx / 检定数据记录文档.md 等
│   └── 样例/                   # 输入/输出样例 Excel
├── requirements.txt            # 依赖清单
├── Dockerfile                  # 容器镜像定义（python:3.10-slim）
├── .dockerignore               # 镜像构建排除清单
└── 现场部署包/                  # 打包产物（见「四、打包与部署」）
```

**数据流**：

```
HTTP（生产）: 平台 ──POST 9个JSON集合──> server蓝图（通用工厂按 modules 注册中心生成）
       ──modules/detect/reader.read_json──> 12个DataFrame
       ──pipeline.run_pipeline()──> 输出 ──writer.write_json──> JSON出参 ──> 平台

CLI（离线） : python cli.py <输入.xlsx> ──reader.read_excel──> 12个DataFrame
       ──同一 run_pipeline()──> 输出 ──writer.write_excel──> 输出 Excel
```

---

## 二、环境准备

```bash
pip install -r requirements.txt
```

- 依赖：`pandas` / `numpy` / `openpyxl` / `flask`（Python 3.10+）

---

## 三、启动方式

### 1. HTTP 算法服务（生产）

```bash
python main.py                                    # 直接启动（默认 0.0.0.0:5000）
python main.py serve --host 0.0.0.0 --port 8080   # 显式指定
```

或用环境变量配置（推荐，部署参数集中在环境变量）：

```bash
SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py serve
```

向后兼容：`python service.py`（等价 `python main.py`）。

**接口路由（唯一接口）：**

```
POST http://<host>:<port>/restful/busiInterface/ipsService/detectPlanScheduling
Content-Type: application/json
```

- 方法：**POST**；入参 9 个 JSON 集合 / 出参定义见「五、接口契约」
- 本机测试：`http://localhost:5000/restful/busiInterface/ipsService/detectPlanScheduling`
- 部署后把 `<host>` 换成企业指定 IP、`<port>` 换成映射端口

### 2. 命令行兑底（CLI，离线开发/验证）

读 12-sheet 输入 Excel → 排程 → 写 7-sheet 输出 Excel。

```bash
python cli.py <输入Excel路径> [-o 输出Excel路径]
```

| 参数 | 说明 |
|---|---|
| `输入Excel路径` | 必填，须含 **12 个 sheet**（清单见 5.3） |
| `-o` / `--output` | 可选，缺省输出到当前目录 `检定排程计划_优化版_支持加班.xlsx` |

注意：输出文件的**父目录必须已存在**；退出码 `0`=成功 `1`=失败。

### 3. 接口测试（无需启动服务器）

```bash
python tests/test_interface.py
```

### 4. 查看完整算法执行日志

```bash
LOG_LEVEL=DEBUG python cli.py <输入.xlsx>
LOG_LEVEL=DEBUG python main.py
```

`INFO` 记录流程里程碑与调度决策；`DEBUG` 额外输出子任务分配明细；
**数据/计算问题以 `WARNING` 留痕**（分类失败、缺口未满足、批次被跳过等）；
所有报错打印完整异常调用栈。

### 5. 环境变量配置

| 变量 | 作用 | 默认 | 备注 |
|---|---|---|---|
| `SERVER_HOST` | 监听地址 | `0.0.0.0` | 生产绑定企业指定 IP；容器内保持 `0.0.0.0` 勿改 |
| `SERVER_PORT` | 监听端口 | `5000` | 容器内须与 `-p` 右侧一致 |
| `SERVER_DEBUG` | Flask 调试模式（`1` 开） | `0` | 生产勿开 |
| `LOG_LEVEL` | 日志级别（`INFO`/`DEBUG`） | `INFO` | `DEBUG` 输出子任务级明细 |

**优先级**：命令行 `--host/--port` > 环境变量 > 默认值。

---

## 四、打包与部署

### 4.1 方式一：离线 ZIP 包（Windows 现场直跑）【推荐】

现场通常是无外网/不方便拉镜像的 Windows 机器，直接用源码 ZIP 包即可。

**打包内容**（仅运行时代码，排除开发/缓存/参考目录）：

```
现场部署包/
├── main.py  cli.py  service.py  config.py
├── common/   modules/   server/
├── requirements.txt  Dockerfile  .dockerignore
├── README.md
└── docs/接口文档/                  # 接口契约（现场对接参考）
    docs/报文/0812_单请求.json      # 真实请求样例（验证用）
```

**打包命令**（项目根目录，Windows PowerShell）：

```powershell
# 在项目根目录执行；或直接复用仓库内的 现场部署包/ 后重新压缩
Compress-Archive -Path main.py, cli.py, service.py, config.py, common, modules, server,
                 requirements.txt, Dockerfile, .dockerignore, README.md,
                 docs\接口文档, docs\报文\0812_单请求.json
                 -DestinationPath 现场部署包.zip
```

**现场安装与启动**：

```powershell
# ① 安装 Python 3.10+（勾选 Add to PATH）
# ② 解压 zip，进入目录后装依赖
pip install -r requirements.txt
# ③ 启动（默认 0.0.0.0:5000）
python main.py
# 或指定端口
SERVER_PORT=8080 python main.py serve
# ④ 平台配置接口地址
#    http://<服务器IP>:8080/restful/busiInterface/ipsService/detectPlanScheduling
# ⑤ 验证：Postman/curl 发 docs\报文\0812_单请求.json → resultFlag=1，明细 18 条
```

> Windows 下环境变量写法 `SERVER_PORT=8080 python main.py serve` 在 **cmd 用 `set SERVER_PORT=8080 && python main.py serve`**。

### 4.2 方式二：Docker 镜像

```bash
# 打包镜像（.dockerignore 已排除 docs/tests/样例等，镜像精简）
docker build -t jiankeng-scheduler .

# 启动（外部 5000 → 容器内 5000）
docker run -d -p 5000:5000 --name scheduler jiankeng-scheduler

# 换端口：docker run -d -p 8080:8080 -e SERVER_PORT=8080 --name scheduler jiankeng-scheduler
# 看日志：docker logs -f scheduler
```

容器内注意：`SERVER_HOST` 保持 `0.0.0.0`（宿主机绑定由 `-p` 控制）；
`SERVER_PORT` 须与 `-p` 右侧一致。对外服务地址 = **宿主机 IP + `-p` 左侧端口**。

容器内跑 CLI 兑底：

```bash
docker run --rm -v "$PWD":/data jiankeng-scheduler python cli.py /data/输入.xlsx -o /data/输出.xlsx
```

---

## 五、接口契约

完整字段定义见 `docs/接口文档/接口说明v2.0.md`（V0.0.2，当前基准）。

### 5.1 HTTP 入参（9 个集合，全部必填）

| 集合 | 说明 |
|---|---|
| `deviceParaList` | 流水线检定仓参数（线体/仓/所检设备表类型/表位数） |
| `dmdPlanDetList` | 需求明细（月份/设备类型码大码/数量/设备分类 equipCls） |
| `arriveBatchList` | 到货批次（批次号/设备码/数量/到货日期/equipCls/sampleFlag 是否已抽检/sampleQty 抽样数量） |
| `detectSchList` | 检定方案（设备码、检定方案耗时 schTime、detectSchemeId、detectType） |
| `qualifiedStockList` | 合格品库存 |
| `unqualifiedStockList` | 非合格品库存（含 sampleFlag 是否已抽检/sampleQty 抽样数量） |
| `scheduleTimeList` | 排程时间配置（工作日、上下班时间） |
| `scheduleConfigList` | 流水线调度配置（调度时间间隔、允许加班时长） |
| `nonDmdAimEquipCodeCfgList` | 非需求设备目标设备类型码分配配置 |

**真实请求样例**：`docs/报文/0812_单请求.json`（0812 报文第一个请求的合法单 JSON，
9 集合齐全，可直接作 Postman Body）；`docs/报文/0812_单请求_补抽检字段.json`
（v0.0.6 形态：全部批次补 sampleFlag/sampleQty，含 2 个到货批次 + 1 个非合格品批次未抽检）；
`docs/报文/0825_检定仓情况_转json.json`（由 `tests/excel_to_json_payload.py` 从
`docs/样例/检定仓情况-20260825.xlsx` 按 v0.0.6 转换生成——**HTTP 与 CLI 用同一份数据，
两条路径排程结果一致**）。

### 5.2 HTTP 出参

```json
{
  "resultFlag": "1",                       // 1=成功 0=失败
  "errorInfo": "",
  "detectPlanSchedulingchList": [          // 排程明细
    {
      "sysNo": "2001",                     // 线体编号
      "sysName": "线体名称",
      "deviceType": "01",                  // 检定仓类型编码（VW_DEVICE_TYPE）
      "deviceNo": "仓编号",
      "arriveBatchNo": "批次号",
      "equipCateg": "09",                  // 设备类别编码（VW_EQUIP_CATEG）
      "equipCls": "19",                    // 设备分类编码（VW_EQUIP_CLS）
      "equipCode": "设备码",
      "aimEquipCode": "目标设备类型码",
      "equipDesc": "",                     // 待企业确认口径
      "detectSchemeId": 129,               // 检定方案标识（8.17：spec.参数标识，查不到为空串）
      "projectedStartTime": "2026-08-12 09:00:00",
      "projectedEndTime": "2026-08-12 15:54:00",
      "detectPlanQty": 20,
      "demandFlag": "0",                   // 1=需求优先 0=否
      "weekDayStartAndEnd": "",            // 待企业确认口径
      "detectType": "03"                   // 检定类别：02 抽样试验 / 03 首次检定（8.25）
    }
  ]
}
```

> 码值：`equipCls`/`equipCateg`/`deviceType` 均为 2 位码（8.16 统一码值体系）。
> `detectSchemeId` 自 8.17 起生产（来源 spec 参数标识，含大小码回退，查不到返回空串）。
> `detectType`（检定类别）自 8.25 起生产：未抽检批次先安排 02 抽样试验，之后 03 首次检定。
> **输出全部码值化（8.28 起，Excel 与 JSON 同步）**：能找到码值映射的中文一律输出编码字符
> （VW 编码列 2 位字符串、需求优先 '1'/'0'，Excel 中文名称列已删除）；无码值映射的字段
> （线体名称 sysName、月份、批次号、设备码等标识）保持原样。
> `equipDesc` / `weekDayStartAndEnd` 算法暂不生产，返回空串，待企业确认口径。

### 5.3 Excel 入参（离线兑底，12 个 sheet）

| sheet 名 | 内容 |
|---|---|
| 整体情况 | 线体/检定仓/所检设备表类型/表位数 |
| 检定线信息表 | 检定线 ID 与名称 |
| 检定仓类型表 | 仓类型 ID 与名称 |
| 检定仓配置表 | 检定线与检定仓的仓类型关联 |
| 到货排程-到货计划旧表 | 到货批次、设备、数量、预计到货日期、是否已抽检、抽检数量 |
| 需求明细 | 所属月份、设备码大码、申请数量、设备码、设备分类 |
| 规格设备码信息表 | 设备码、设备分类、接入方式、自动检定时间、设备码描述、参数标识 |
| 合格品库存信息表 | 设备码、合格品库存、未配送库存、安全库存 |
| 非合格品库存 | 到货批次、设备码、设备分类、可检库存、是否已抽检、抽检数量 |
| 排程时间配置 | 工作日日期、开始/结束时间 |
| 调度时间间隔配置 | 线体编号、调度时间间隔（秒）、允许加班时长 |
| 非需求设备目标设备类型配置 | 设备类型码大码、目标设备类型码、分配比例 |

sheet 名映射在 `modules/detect/constants.py` 的 `DataSourceConfig.input_sheet_names`。

### 5.4 Excel 出参（7 个 sheet）

| sheet 名 | 内容 |
|---|---|
| 检定排程明细 | 按月份/线体/设备汇总的检定计划 |
| 检定时间明细 | 每个检定子任务的时间排程（逐批） |
| 仓利用率统计 | 各仓批次数与总检定量 |
| 到货批次分配明细 | 批次→设备的分配量 |
| 原始到货批次 | 输入的到货批次清单 |
| 月度需求汇总 | 各月份设备需求 |
| 检定仓配置 | 仓编号、类型、每仓最大容量 |

---

## 六、常见问题

- **启动后局域网都能访问？** 默认绑定 `0.0.0.0`。生产务必用 `--host` 或 `SERVER_HOST` 绑定企业指定 IP。
- **端口被占用？** 用 `--port` 或 `SERVER_PORT` 换端口；启动失败打印完整调用栈。
- **接口报 resultFlag=0？** 看服务端日志（完整调用栈），`errorInfo` 为简要错误消息。
- **Postman 粘贴 0812 原文件失败？** 原 `智能排程报文0812.json` 是两个请求拼接的，用 `docs/报文/0812_单请求.json`（已提取的单请求）。
- **缺字段出参为空？** `equipDesc` / `weekDayStartAndEnd` 待企业确认口径，属已知缺口；`detectSchemeId` 为空说明该设备码在 detectSchList（及大小码映射）中无方案标识。
