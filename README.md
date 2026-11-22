# 公共宣传折页的多栏文字和易读改写

街道宣传折页的页内文字块、编校稿和接收端的载体说明。材料中的人、机构及经营记录是合成的。

每份资料为 UTF-8 JSON 数组。id 在同一份资料内唯一，原始文字按收到的形式保留。

- `data/layout.json`。出版稿文字块。原始坐标是页内像素，bbox 依次为左、上、右、下。flows 只表示印刷物上打印的符号，不保证语义。
- `data/copy.json`。编校台与接收方的合成草稿和更正。source_ref 是编辑认为有关的原稿编号，尚需复核。
- `data/channels.json`。印刷与读屏接收方约定。budget 按可见 Unicode 字符计，音频按送读文字计。priority 由小到大排列，段落引用如果指向另一交付单元，此单元可能无法同时获得。

使用 Python 3.11 标准库，无需安装软件包或连接外部服务。

以下命令分别读取一份原始资料、检查资料中的字段与关联。

```sh
python3 -m json.tool data/layout.json
python3 -m unittest discover -s tests -v
```

## 编校工具 `editorial`

在印刷和送读屏之前同时检查两类问题：逐栏抄录把例外接到另一问题下，
以及简写把“可以请求说明”改成“窗口一定会办”。

模块只依赖标准库。隔离运行（不从当前目录或环境变量加载第三方代码）
请用仓库根目录的启动器：

```sh
python3 -I run_editorial.py check data/layout.json data/copy.json \
    data/channels.json --plan examples/plan_demo.json
```

### 检查环节

1. **布局读序（`geometry.py`）**：按 bbox 水平重叠聚栏，给出逐栏读序
   （从左到右、栏内自上而下）与逐行读序；两种读序先后相反且涉及限制/条件块时，
   报告错接风险。接续块（带 flows 或标注“接续”）不参与聚栏。
2. **话语衔接（`discourse.py`）**：识别“见背面注二”等显式跳转、
   “上列/下列情形”回指和接续块指向。语言证据（同栏、情形清单、语言锚点）
   与版面几何证据矛盾时不擅自决定，输出 `reading_order_conflict` 阻止项，
   由编校员在方案 `decisions` 中裁决；裁决后状态变为 `decided`。
3. **语义核对（`semantics.py`）**：逐小句识别力度（请求/许可/义务/承诺/限制）、
   动作、施事人、条件与反例。核对改写是否发生力度漂移、是否与限制方向相反、
   限制或条件是否丢失、施事人与服务台指向是否保留、动作是否有 source_ref 出处。
   条件式许可（“仅持委托……可以递交”）与否定限制（“现场不改”）分开识别。
4. **出版裁决（`publishing.py`）**：按渠道单元检查自足性与预算。
   - 可独立领取/播放的单元，必要注释必须一同可读；选读性跳转允许保留明确跳转。
   - 预算按可见 Unicode 字符计；放不下只能取更狭义而仍真实的说法
     （方案条目标注 `narrowed:`），或撤下整条并给出到哪里询问的提示。
   - 条目按渠道 priority 排序，顺序即读屏顺序，不为塞内容重排或丢限制。
   - 裁决为 `ready`（可交印/可朗读）、`gated`（依附单元不独立）或
     `blocked`（存在阻止项）。
5. **更正换发（`corrections.py`）**：对 `signed_correction` 构造引用图，
   判定印刷页可独立换发还是须整份换发（已发页号保留供读者询问），
   电子片段在残缺内容不能独立成立时暂停，其余节目继续可读。

### 方案文件 `examples/plan_demo.json`

- `assignments`：把原稿块（`block`）、改写（`copy`）或内联易读文字（`text`
  须带 `source_ref`）指派到渠道单元；`role: support` 表示就地注释依据，
  不计预算；`withdraw: true` 必须带 `pointer_text`。
- `decisions`：编校员对读序冲突的裁决，注明目标块与理由。

### 更正影响分析

```sh
python3 -I run_editorial.py correct data/layout.json data/copy.json \
    data/channels.json examples/plan_demo.json E5
```

输出每个印刷页的 `reissue_independent` / `whole_document` / `keep` 结论、
待替换已发件、电子片段门控，以及每条结论关联的原稿位置和当前改写。

两个子命令都支持 `--json 路径` 输出结构化报告。
