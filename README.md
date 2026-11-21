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
