# 检定排程系统

电能表检定排程与库存优化算法服务。原为单文件脚本 `docs/检定排程python代码最新8.03.py`（保留作参考，**勿修改**），现重构为**算法服务 + 模块化代码**：

- **生产环境**：被计量生产调度平台通过 HTTP 调用（接口契约见 `docs/接口说明.md`），JSON 入参 → JSON 出参
- **离线兑底**：命令行读 Excel 出 Excel，用于开发验证与功能等价性验证
- 输入/输出统一以 pandas DataFrame 为边界，两条路径共用同一 `run_pipeline()` 执行流水线

> 算法**串行同步运行**、使用模块级状态，不支持并发/异步；服务以单线程方式启动。

---

## 一、环境准备

```bash
pip install -r requirements.txt
```

依赖：`pandas`、`numpy`、`openpyxl`、`flask`（Python 3.10+）。

---

## 二、文件结构

```
深圳项目/
├── main.py                     # 全局启动脚本 —— HTTP 算法服务（python main.py）
├── cli.py                      # 命令行兑底脚本 —— Excel 兑底（python cli.py）
├── service.py                  # HTTP 服务启动器（向后兼容 python service.py）
├── config.py                   # 环境配置（监听地址 SERVER_HOST/SERVER_PORT、日志级别 LOG_LEVEL）
│
├── common/                     # 与算法无关的公共功能包
│   ├── utils.py                # 纯工具方法（clean_columns / parse_device_category）
│   └── logging_utils.py        # 日志统一配置（幂等 setup_logging）
│
├── data/                       # 数据处理层包
│   ├── constants.py            # 接口枚举字典 + DataSourceConfig（Excel sheet 映射）
│   ├── reader.py               # read_excel（11 sheet）/ read_json（接口 8 集合）
│   └── writer.py               # write_excel（7 DataFrame → Excel）/ write_json（→ 出参 JSON）
│
├── algorithm/                  # 核心算法包
│   ├── constants.py            # SchedulingConfig（算法默认参数）
│   ├── scheduler.py            # 核心算法（核心逻辑零修改，含详细执行日志）
│   ├── prepare.py              # process_data()（DataFrame → 填充算法全局变量）
│   └── pipeline.py             # run_pipeline()（准备→调度→输出 统一流水线）
│
├── server/                     # HTTP 服务包
│   ├── __init__.py             # create_app() 应用工厂 + run_server() 启动
│   └── blueprints/             # 蓝图注册中心（新增算法模块在此追加）
│       └── detect_plan_scheduling.py   # detectPlanScheduling 接口蓝图
│
├── tests/                      # 测试脚本包
│   └── test_interface.py       # 按接口文档格式的接口测试
│
├── docs/                       # 文档与参考文件
│   ├── 接口说明.md              # 接口契约（入参/出参/枚举字典）
│   ├── 检定排程python代码最新8.03.py   # 原算法源文件（勿修改）
│   ├── 检定排程计划_8.03.xlsx   # 原脚本输出样例
│   └── 深圳供电局…交互接口V0.0.1.docx   # 接口文档（Word 版）
│
├── requirements.txt          # 依赖清单
├── Dockerfile                # 容器镜像定义（python:3.10-slim）
└── .dockerignore             # 打包时排除 tests/docs/样例等
```

**数据流**：

```
HTTP（生产）: 平台 ──POST 8个JSON集合──> server蓝图 ──read_json──> 11个DataFrame
       ──run_pipeline()──> 输出 ──write_json──> JSON出参 ──> 平台

CLI（离线） : python cli.py <输入.xlsx> ──read_excel──> 11个DataFrame
       ──同一 run_pipeline()──> 输出 ──write_excel──> 输出 Excel
```

---

## 三、启动方式

### 1. HTTP 算法服务（生产）

```bash
python main.py                          # 直接启动（默认 0.0.0.0:5000）
python main.py serve --host 10.x.x.x --port 8080   # 显式指定
```

或用环境变量配置（推荐，部署参数集中在环境变量）：

```bash
SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py
```

向后兼容启动方式：`python service.py`（等价 `python main.py`）。

环境变量配置与优先级见「三.5 环境变量配置」。

**接口路由（唯一接口）：**

```
POST http://<host>:<port>/restful/busiInterface/ipsService/detectPlanScheduling
```

- 方法：**POST**；入参 8 个 JSON 集合 / 出参定义见「五、输入输出」
- 例：`http://localhost:5000/restful/busiInterface/ipsService/detectPlanScheduling`
- 部署后把 `<host>` 换成企业指定 IP，`<port>` 换成映射端口

> 服务为**单线程串行**处理请求，切勿用多线程/多进程 WSGI 部署。

### 2. 命令行兑底（CLI，离线开发/验证）

读 11-sheet 输入 Excel → 排程 → 写 7-sheet 输出 Excel。

```bash
python cli.py <输入Excel路径> [-o 输出Excel路径]
```

示例：

```bash
# 相对路径
python cli.py ./data/输入.xlsx -o ./output/排程结果.xlsx

# 绝对路径
python cli.py D:\库存数据\输入.xlsx -o D:\库存结果\排程.xlsx

# 不带 -o：输出到默认文件（当前目录）
python cli.py 输入.xlsx

# 详细日志（含子任务级明细）
LOG_LEVEL=DEBUG python cli.py 输入.xlsx -o 排程结果.xlsx
```

**参数说明**

| 参数 | 说明 |
|---|---|
| `输入Excel路径` | 必填，须含 **11 个 sheet**（sheet 清单见 5.3）；支持绝对/相对路径、路径含空格时加引号 |
| `-o` / `--output` | 可选，输出路径；缺省为当前目录下 `检定排程计划_优化版_无加班.xlsx` |

**注意事项**

- 输出文件的**父目录必须已存在**（脚本不自动建目录），否则报错
- 输入路径不存在时报 `输入文件不存在` + 完整调用栈
- 退出码：`0` = 成功，`1` = 失败（失败打印完整异常调用栈）
- 成功后打印 `排程完成！结果保存至: <路径>`，输出 Excel 含 **7 个 sheet**（清单见 5.4）
- `docs/检定排程计划_8.03.xlsx` 是原脚本的**输出样例**（7 sheet），**不是输入**；CLI 输入要 11-sheet 的原始数据文件
- Docker 容器内跑 CLI 见「4.6 容器内跑 CLI 兑底」

### 3. 接口测试

```bash
python tests/test_interface.py
```

无需启动服务器，通过 Flask test_client 直接验证接口。

### 4. 查看完整算法执行日志

```bash
LOG_LEVEL=DEBUG python cli.py <输入.xlsx>
LOG_LEVEL=DEBUG python main.py
```

`INFO` 记录流程里程碑与调度决策，`DEBUG` 额外输出每个检定子任务的分配明细。所有报错均打印完整异常调用栈。

### 5. 环境变量配置

| 变量 | 作用 | 默认 | 备注 |
|---|---|---|---|
| `SERVER_HOST` | 监听地址 | `0.0.0.0` | 本地可指定 IP；容器内**保持 `0.0.0.0` 勿改**（宿主机绑定由 `-p` 控制） |
| `SERVER_PORT` | 监听端口 | `5000` | 容器内须与 `-p` 右侧一致 |
| `SERVER_DEBUG` | Flask 调试模式（`1` 开） | `0` | 生产勿开 |
| `LOG_LEVEL` | 日志级别（`INFO`/`DEBUG`） | `INFO` | `DEBUG` 输出子任务级明细 |

**优先级**：命令行 `--host/--port` > 环境变量 > 默认值。

```bash
# 本地启动
SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py

# Docker 启动（外部端口 8080，容器内也 8080）
docker run -d -p 8080:8080 -e SERVER_PORT=8080 jiankeng-scheduler
```

---

## 四、Docker 打包与部署

### 4.1 打包镜像

```bash
docker build -t jiankeng-scheduler .
```

- 基础镜像 `python:3.10-slim`
- `.dockerignore` 排除了 `docs/`、`tests/`、`*.xlsx`、`*.md` 等运行时不需要的文件，保持镜像精简
- 镜像内以非 root 用户（`appuser`）运行，`/app` 目录可写（便于 CLI 兑底在容器内输出 Excel）

### 4.2 启动容器

```bash
# 默认：外部 5000 → 容器内 5000
docker run -d -p 5000:5000 --name scheduler jiankeng-scheduler
```

| 场景 | 命令 |
|---|---|
| 换外部端口（内部也改） | `docker run -d -p 8080:8080 -e SERVER_PORT=8080 --name scheduler jiankeng-scheduler` |
| 只换外部端口（内部不动） | `docker run -d -p 8080:5000 --name scheduler jiankeng-scheduler` |
| 绑定指定宿主机网卡 | `docker run -d -p 10.x.x.x:5000:5000 --name scheduler jiankeng-scheduler` |

改端口/网卡需**重建容器**：`docker stop scheduler && docker rm scheduler` 后再 `docker run`。

### 4.3 端口映射与地址理解

```
docker run -p 宿主机IP:宿主机端口:容器端口
                 │      │       └─ 容器内 Flask 监听端口（-e SERVER_PORT 控制）
                 │      └─ 对外端口（-p 定死，创建时决定）
                 └─ 绑定的宿主机网卡（-p 定死；不写=所有网卡）
```

- **对外服务地址 = 宿主机 IP + `-p` 左侧端口**（接口地址见「三.1 接口路由」）
- 容器日志里的 `172.17.0.3` 是容器在 Docker 内网地址，**外部访问不到**
- **`SERVER_HOST` 保持 `0.0.0.0` 勿改**：它管容器内 Flask 监听，改成宿主机 IP 会导致端口映射失效
- 宿主机端口/网卡**不能用环境变量改**，只能创建时用 `-p` 定

### 4.4 Docker 环境变量

完整环境变量表见「三.5 环境变量配置」。容器内两点注意：

- `SERVER_HOST` 保持 `0.0.0.0`（管容器内 Flask 监听，宿主机绑定由 `-p` 控制，见 4.3）
- `SERVER_PORT` 须与 `-p` 右侧一致（如 `-p 8080:8080 -e SERVER_PORT=8080`）

### 4.5 测试容器

```bash
# ① 容器健康
docker ps                              # STATUS 应为 Up ... (healthy)

# ② TCP 连通（PowerShell）
Test-NetConnection localhost -Port 5000

# ③ HTTP 通（能返回 JSON 即路由通）
curl.exe -X POST <接口地址> -H "Content-Type: application/json" -d "{}"
# <接口地址> 见「三.1 接口路由」（本地默认 http://localhost:5000）
# 预期：{"resultFlag":"0","errorInfo":"请求体为空或不是合法 JSON"}

# ④ 算法全功能：Body 填 5.1 的完整 8 集合 JSON → resultFlag=1

# 查看日志（含完整算法执行流程）
docker logs -f scheduler
```

### 4.6 容器内跑 CLI 兑底

```bash
docker run --rm -v "$PWD":/data jiankeng-scheduler python cli.py /data/输入.xlsx -o /data/输出.xlsx
```

---

## 五、输入输出

### 5.1 HTTP 入参

8 个 JSON 集合，字段名见 `docs/接口说明.md`：

| 集合 | 说明 |
|---|---|
| `deviceParaList` | 流水线检定仓参数信息 |
| `dmdPlanDetList` | 需求明细信息 |
| `arriveBatchList` | 到货批次信息 |
| `detectSchList` | 检定方案信息（设备码、检定方案耗时） |
| `qualifiedStockList` | 合格品库存信息 |
| `unqualifiedStockList` | 非合格品库存信息 |
| `scheduleTimeList` | 排程时间配置（工作日、上下班时间） |
| `scheduleConfigList` | 流水线调度配置（调度时间间隔等） |

请求示例见 `docs/接口说明.md` 的「请求JSON示例」。

### 5.2 HTTP 出参

```json
{
  "resultFlag": "1",                       // 1=成功 0=失败
  "errorInfo": "",
  "detectPlanSchedulingchList": [          // 排程明细
    {
      "sysNo": "2001",
      "sysName": "线体名称",
      "deviceType": "05",
      "deviceNo": "仓编号",
      "arriveBatchNo": "批次号",
      "equipCateg": "",                    // 待企业确认口径
      "equipCls": "智能量测终端",
      "equipCode": "设备码",
      "equipDesc": "",                     // 待企业确认口径
      "detectSchemeId": "",                // 待企业确认口径
      "projectedStartTime": "2026-03-02 09:00:00",
      "projectedEndTime": "2026-03-02 15:54:00",
      "detectPlanQty": 48,
      "demandFlag": "1",                   // 1=需求优先 0=否
      "weekDayStartAndEnd": ""             // 待企业确认口径
    }
  ]
}
```

### 5.3 Excel 入参（离线兑底）

11 个 sheet（sheet 名可在 `data/constants.py` 的 `DataSourceConfig.input_sheet_names` 修改）：

| sheet 名 | 内容 |
|---|---|
| 整体情况 | 线体/检定仓/所检设备表类型/表位数 |
| 检定线信息表 | 检定线 ID 与名称 |
| 检定仓类型表 | 仓类型 ID 与名称 |
| 检定仓配置表 | 检定线与检定仓的仓类型关联 |
| 到货排程-到货计划旧表 | 到货批次、设备、数量、预计到货日期 |
| 需求明细 | 所属月份、设备码大码、申请数量 |
| 规格设备码信息表 | 设备码、设备分类、接入方式、自动检定时间 |
| 合格品库存信息表 | 设备码、合格品库存、未配送库存、安全库存 |
| 非合格品库存 | 到货批次、设备码、可检库存 |
| 排程时间配置 | 工作日日期、开始/结束时间 |
| 调度时间间隔配置 | 线体编号、调度时间间隔（秒） |

### 5.4 Excel 出参

7 个 sheet（映射见 `DataSourceConfig.output_sheet_names`）：

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

- **启动后局域网都能访问？** 默认绑定 `0.0.0.0`（所有网卡）。生产务必用 `--host` 或 `SERVER_HOST` 绑定企业指定 IP。
- **端口被占用？** 用 `--port` 或 `SERVER_PORT` 换端口；启动失败会打印完整异常调用栈。
- **接口报 resultFlag=0？** 查看服务端日志（完整调用栈），`errorInfo` 为简要错误消息。
