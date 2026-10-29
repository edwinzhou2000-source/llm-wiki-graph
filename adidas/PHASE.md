# PHASE — 设计取舍与诚实边界

## 为何 Neo4j 独立容器

- 与 medical（`7687/7474`、独立 `graph/.env` 凭据）完全隔离，避免清图/约束互相踩踏。
- adidas 图规模更大（约 6k+ 节点 / 2 万+ 边），独立 volume 便于重灌与排障。
- 运维成本：多一个容器、bolt 依赖、`load_data` 重灌（无自动与源 KB 同步）。

## 为何边 = frontmatter 字段，不是一事一页

- adidas 源 KB 产品页已有 `series:` / `tags:` / `type:` 等结构化字段，确定性派生即可。
- 避免为每条边维护独立 Wiki 页的编辑成本；图是检索索引，不是第二事实源。
- 代价：frontmatter 噪声会直接进图（见下）。

## 诚实边界

1. **Series 噪声**：`series:` 混有 `ORIGINALS` / `TRAINING` / 描述性短语等；图如实反映数据，覆盖质量取决于 frontmatter 规范程度。
2. **确定性否定**：`products_by_tech` 返回空 = 覆盖集内无产品边指向该科技，前提是 `tags`/`attributes` 已规范填写。
3. **Product stem 碰撞**：同名 stem 跨品类会合并为一个 `Product` 节点（唯一约束按 `name`）。
4. **本版本是检索架构演示**，不是生产系统；答案由 LLM 读源 KB 原文合成，图只做召回。
5. **本版本是检索架构演示**，不是生产系统；答案由 LLM 读源 KB 原文合成，图只做召回。
5b. **门户写入走 overlay**：上传/审核/保存只写 `adidas/_accepted` 等，源 KB 只读。
6. **不照搬 medical 全量 ingest AI**：上传 MVP 对 md/txt 自动生成提案；PDF 等附件需人工补正文后批准。

## 可抄 / 不可抄 medical

| 可抄接入样板 | 不可抄 |
|---|---|
| compose、`load_data` MERGE、`_run_cypher` 壳、rewrite 门形态、smoke/benchmark 结构 | medical 路由、全量 `server.py`、`graph-entity-map.yml`、一事一页 extract |
