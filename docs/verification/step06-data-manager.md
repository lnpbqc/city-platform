# 步骤06：数据管理验收

2026-10-26，在Windows、Edge、Node.js 24、Python 3.13环境验收。前端使用15173端口，后端使用18000端口及独立临时SQLite/文件目录。生产数据库与已有发布文件保持原状。

## 结果

| 操作或检查 | 实际结果 |
| --- | --- |
| 后端回归 | 160项通过，包含发布前/发布后断连回滚与ZIP原始文件名校验 |
| 前端回归 | 102项通过，类型检查与生产构建通过 |
| 浏览器上传300MiB ZIP | 314,573,166字节ZIP，发布后2文件、314,572,946字节，登记和目录同时出现 |
| 传输与校验 | 节流20MiB/s记录102次不同状态：0%→1%…→99%→100%→“传输完成100%，正在校验与发布” |
| 取消 | 浏览器点击取消显示“上传已取消”；另以真实HTTP连接发送部分multipart后断开，均无新增记录/发布目录，tmp为空 |
| 文件内容 | 两次成功上传的逐文件SHA-256一致；清单摘要均为`093283fc27c5fd74cc8d372e7c4e0082c0f3077ede75061d45d1aab2c994c8de` |
| 路径错误 | 原始ZIP条目含反斜杠时返回422，页面显示具体原因、CONTENT_INVALID及trace_id |
| 外部登记 | 名称、来源、坐标说明保存；体积、范围和校验和显示未知；同地址第二图层复用已有资产 |
| 翻页 | 24条资产，第1页20条、第2页4条；全集24条，无重复遗漏 |
| 排序与筛选 | 体积降序将300MiB资产排在未知体积前；改变筛选回到第1页；关键词筛选到单资产后打开正确详情 |
| 失败与竞态 | 请求失败清空旧行；过期分页/统计响应不覆盖新筛选；删除末页后回到有效页 |

大文件样例由tileset.json和300MiB的payload.bin组成，用于传输、目录与指纹验收。场景渲染沿用校区资产，按后续场景浏览步骤验收。构建保留Cesium包体积提示，后端测试保留上游httpx弃用提示。

## 页面证据

- [上传进度](../../output/playwright/step06-upload-progress.png)
- [取消反馈](../../output/playwright/step06-cancelled.png)
- [具体ZIP错误](../../output/playwright/step06-zip-error.png)
- [资产目录](../../output/playwright/step06-catalog.png)
- [外部资产详情](../../output/playwright/step06-external-detail.png)
- [文件校验和详情](../../output/playwright/step06-checksums.png)

## 复核入口

后端运行`uv run pytest -q`，前端使用Node.js 24运行`pnpm test`、`pnpm build`。页面操作入口为`/#/data`，资产列表与统计接口见[API契约](../api_contract.md)。上传大文件时浏览器开发工具可限制上传速率，以观察中间百分比与取消反馈。

文档已按anti-defensive-writing检查：保留上传限制、目录快照和外部资源的实际边界，操作步骤使用直接表述。
