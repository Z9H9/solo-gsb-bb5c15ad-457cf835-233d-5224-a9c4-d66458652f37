# 🧪 实验室配液约束求解器

使用 **Python FastAPI + SQLite + 原生 HTML/JavaScript** 构建的实验室配液约束求解 Web 应用。

录入多种**库存溶液**（浓度、密度、可用体积及各自单位）与**目标配方**（总体积、各溶质目标浓度）后，
服务端会统一全部单位，并求解同时满足以下约束的取液方案：

1. **体积守恒**：各库存液用量 + 稀释剂补量 = 目标总体积；
2. **浓度约束**：混合后每种溶质的实际浓度等于目标浓度（质量 / 摩尔 / 体积分数守恒）；
3. **库存上限**：任一库存液用量不超过其可用体积。

可行时返回**每种库存液的用量、稀释剂补量**（并附逐溶质配制明细与回算校验）；
不可行时返回**明确的不可行原因**（库存缺某溶质、单位族不兼容、库存总量不足、取液量超过总体积等）。

---

## 🚀 快速开始（Docker Compose，推荐）

```bash
docker compose up --build -d
```

启动后在浏览器访问：

### 👉 http://localhost:8000

- 页面端口：**8000**
- API 文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

停止：

```bash
docker compose down          # 保留数据（命名卷 solver-data）
docker compose down -v       # 同时删除数据库
```

## 🐳 仅用 Docker

```bash
docker build -t lab-solution-solver .
docker run -d -p 8000:8000 -v solver-data:/data --name lab-solver lab-solution-solver
```

## 🐍 本地直接运行（无需 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
SOLVER_DB=./solver.db uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000 。

---

## 🧑‍🔬 使用步骤

页面按 5 个区块组织：

1. **库存溶液**：添加 / 编辑 / 删除库存液。字段包括溶液名称、溶质、浓度与单位、
   密度与单位（使用 `%(w/w)` 质量分数时必填）、可用体积与单位。
   也可点击「载入演示数据」快速获得 4 条示例库存（5 M NaCl、0.5 M NaCl、
   200 g/L 葡萄糖、37%(w/w) 浓盐酸 ρ=1.19 g/mL）。
2. **目标配方**：填写目标总体积（mL / L / µL）与各溶质的目标浓度。
3. **求解取液方案**：点击后展示可行性结论。
   - 可行：库存液取用合计、**稀释剂补量**、每种库存液用量及其库存占用率、
     逐溶质来源明细、混合后浓度的回算校验（相对误差应为 1e-15 量级）。
   - 不可行：红色提示框给出**具体原因**，库存不足时还列出每种溶质的需要量 / 可提供量 / 缺口。
4. **保存方案**：命名后把配方快照与本次结果保存到 SQLite。
5. **已保存方案**：可随时
   - 「查看结果」——载入保存时的配方与结果；
   - 「用最新库存再计算」——库存增减或修改后，对同一配方重新求解并更新结果；
   - 删除。

---

## 📐 数学模型

设第 *j* 种库存液取用 *xⱼ* (mL)，稀释剂补量 *x_d*，目标总体积 *V*，
库存液 *j* 对溶质 *i* 的规范浓度为 *c_ij*，目标浓度为 *C_i*，库存上限为 *U_j*：

```
对每种溶质 i:   Σ_j c_ij · x_j = C_i · V      # 溶质（质量/摩尔/体积）守恒
                Σ_j x_j + x_d = V             # 体积守恒
                0 ≤ x_j ≤ U_j,   x_d ≥ 0
```

每种溶质的子问题是一维线性可行问题。求解器按**浓度从高到低贪心取用**：
浓度越高，提供相同溶质量所需体积越小，因此所得库存液总用量最小
（留给稀释剂的空间最大，也最可能可行）。贪心对该线性模型是全局最优的，
不依赖任何外部求解器（无 scipy 依赖，镜像更小）。

## 单位统一规则

服务端将所有单位换算到内部规范量纲后再求解：

| 类别 | 支持单位 | 内部规范 |
|---|---|---|
| 体积 | `L`、`mL`、`µL/uL` | mL |
| 密度 | `g/mL`、`g/L`、`kg/L`、`kg/m3` | g/mL |
| 摩尔浓度 | `M`、`mM`、`µM/uM`、`mol/L`、`mmol/L` | mol/L |
| 质量浓度 | `g/L`、`mg/L`、`mg/mL`、`g/mL`、`µg/mL`、`kg/m3` | g/L |
| 体积分数 | `%(v/v)`、`v/v` | mL/mL |
| 质量分数 | `%(w/w)`、`w/w`（仅限库存液，需密度） | g/mL（质量分数 × 密度） |

- 同一溶质的库存液与目标必须属于同一单位族（摩尔族 / 质量族 / 体积分数族），
  质量分数 `w/w` 归入质量族；跨族（如用 mM 的库存去配 g/L 的目标）需要摩尔质量，
  应用会明确报错而不是猜测。
- 目标浓度不支持 `%(w/w)`：最终混合液的密度在配制前未知。
- 溶质名称匹配忽略大小写与首尾空格。

## 不可行原因（示例）

- 库存中没有任何含该溶质的溶液；
- 库存液与目标浓度单位族不兼容（摩尔 vs 质量 vs 体积分数）；
- 使用 `%(w/w)` 的库存液未提供密度；
- 库存溶质量不足：给出需要量、可提供量与缺口；
- 库存溶质量不足：给出需要量、可提供量与缺口（当所有库存液都比目标更稀且体积受限时，
  首先表现为该诊断）；
- 所有库存浓度均低于目标浓度（稀释无法得到更浓的溶液）：若库存体积不受限，
  则表现为满足浓度所需取液量超过总体积，给出超量体积；

---

## 🔌 HTTP API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/meta` | 单位选项元数据 |
| GET/POST | `/api/stocks` | 列出 / 新增库存液 |
| PUT/DELETE | `/api/stocks/{id}` | 修改 / 删除库存液 |
| POST | `/api/solve` | 求解（请求体可携带临时库存；不带则用数据库库存） |
| GET/POST | `/api/plans` | 列出 / 保存方案（保存时即用当前库存计算） |
| GET/DELETE | `/api/plans/{id}` | 查看 / 删除方案 |
| POST | `/api/plans/{id}/recalculate` | 用最新库存对已保存配方再计算 |
| POST | `/api/demo` | 库存为空时载入演示数据 |

### `/api/solve` 请求示例

```json
{
  "total_volume": 100,
  "volume_unit": "mL",
  "targets": [
    {"solute": "NaCl", "concentration": 150, "concentration_unit": "mM"},
    {"solute": "葡萄糖", "concentration": 10, "concentration_unit": "g/L"}
  ]
}
```

成功响应（节选）：

```json
{
  "feasible": true,
  "total_volume_display": "100 mL",
  "total_stock_volume_display": "8 mL",
  "diluent_volume_display": "92 mL",
  "used_stocks": [
    {"stock_name": "NaCl 储液", "volume_display": "3 mL", "utilization_pct": 1.5}
  ],
  "per_solute": [ "...逐溶质明细..." ],
  "verification": [ "...回算校验..." ]
}
```

不可行时：`{"feasible": false, "reason": "……明确原因……", "details": [...]}`。

---

## 📁 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI 路由与请求模型
│   ├── solver.py      # 约束求解器（贪心 + 不可行诊断）
│   ├── units.py       # 单位换算与数字格式化
│   └── database.py    # SQLite 持久化（库存液 / 方案）
├── static/
│   ├── index.html     # 单页界面
│   ├── style.css
│   └── app.js         # 原生 JavaScript 交互
├── tests/
│   └── test_solver.py # 求解器单元测试（仅依赖标准库）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## ✅ 运行测试

```bash
python3 -m unittest discover -s tests -v
```

## 🗄️ 数据持久化

SQLite 数据库文件位于容器内 `/data/solver.db`，通过 Compose 命名卷
`solver-data` 持久化；本地运行时可用环境变量 `SOLVER_DB` 指定路径。
