---
name: 12306-train-query
description: 查询 12306 两个车站之间的直达车次及余票。仅提供查询功能，不支持购票。
---
 
# 12306 直达车次查询 Skill
 
## 用途
 
在需要查询两个车站之间的直达车次、余票信息时使用本 Skill。
 
## 文件
 
- `train_query.py`: 查询脚本
- `SKILL.md`: Skill 说明文档
 
## 使用方法
 
`train_query.py` 接受以下参数：
 
```bash
python3 train_query.py <出发站> <到达站> <日期> [选项]
```
 
### 参数说明
 
- `<出发站>`: 出发站名称，如 `北京`、`上海`
- `<到达站>`: 到达站名称，如 `上海`、`广州`
- `<日期>`: 查询日期，格式为 `YYYY-MM-DD`
 
### 可选参数
 
- `--exact`: 仅查询出发站和到达站完全匹配的车次
- `--only-available`: 仅显示有余票的车次
- `--type`: 筛选车型，可选 `高铁/动车`、`普速`、`全部`
 
## 示例
 
```bash
python3 train_query.py 北京 上海 2026-10-10
```
 
```bash
python3 train_query.py 北京 上海 2026-10-10 --only-available --type 高铁/动车
```
 
## 注意事项
 
- 本 Skill 仅提供查询功能，不支持购票。
- 查询结果依赖 12306 官方接口的可用性。
- 查询数据可能存在延迟，仅供参考。
