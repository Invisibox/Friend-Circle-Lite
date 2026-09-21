# Ghost 友链页 → Friend-Circle-Lite → Vercel

本 fork 基于上游 `049a18953736198fbadbaea7d2c27fbd2698ec88`。Ghost 的公开 Friends Page 是唯一人工名单来源，主题通过 `all.json` 展示合计最近 10 篇和一篇随机文章。

## 配置和部署

1. 将 Senna 主题及 Friends Page 发布到公网。页面必须包含 `.friends-page .friends-directory`，其中每张原生 Product 卡片填写名称、图片，并启用按钮、填写主页 URL 和按钮文字。名称和主页 URL 均不能重复。简介只用于 Ghost 展示。
2. 在本仓库 **Settings → Secrets and variables → Actions → Variables** 设置 `GHOST_FRIENDS_URL`，值为该公开页面的完整 URL。不要使用 `localhost:2368`，也不要填写旧博客的 Common Links 参考页。无需 Ghost Admin API key。
3. 启用本 fork 的 Actions，手动运行 **Friend Circle Lite**。每轮先下载页面、提取名单并原子写入 `temp/ghost-friends.json`，再抓取 RSS、校验结果并发布 `page` 分支。默认定时任务为 UTC 每 4 小时第 22 分钟；未配置页面地址时不会自动运行。
4. Vercel 连接 `Invisibox/Friend-Circle-Lite`，Production Branch 设为 `page`，Framework Preset 选 Other，根目录为仓库根目录，不配置构建/安装命令。`page` 已包含最终静态文件和 `vercel.json`，后者设置浏览器读取 JSON 所需的 CORS。只有 `page` 分支触发自动部署。
5. 首次部署成功后检查 `/all.json` 和 `/link.json`，确认 Ghost 页面可以跨域加载。保留现有 `friend.djdog.cc` 域名，使主题的服务地址无需更改。

## 名单和抓取规则

- 只提取目录内 `.kg-product-card` 的名称、头像和 `.kg-product-card-button` 链接；导航、简介里的链接、最近文章和随机文章不会成为名单。
- 去掉 Ghost 添加的主页 `ref` 查询参数及 URL fragment；保留子路径和其他查询参数。相对头像 URL 按页面最终地址解析。
- 每站最多抓取 RSS 当前提供的 10 篇；RSS 自身不足 10 篇时只能得到实际数量。`keep_all_articles: true` 关闭上游全局 150 篇裁剪，保留全部站点的抓取结果供随机池使用。
- 新增、删除、改名、换头像将在下一轮同步体现。上游缓存只用于 RSS 地址和站点检测，不会把已删除站点的文章重新加入新结果。
- `specific_RSS` 仍支持按卡片名称指定特殊 RSS URL；站点改名时，需要同步修改该覆盖项。通常自动探测即可。
- 上游 `CrawlStatistics` 明确使用 `Asia/Shanghai` 生成 `last_updated_time`，与主题现有 `UTC+8` 标注一致。
- 邮件推送与 RSS 邮箱订阅默认关闭，Issue 自动回复任务也须显式启用 `ENABLE_EMAIL_SUBSCRIPTIONS` 才运行。
- `FCL_CONFIG_OVERRIDES` 保留上游功能；不要覆盖 `spider_settings.json_url`、关闭 `keep_all_articles`、启用额外合并源或开启邮件订阅，否则会偏离这里的单一名单约定。

## 失败保护与回退

页面不可达、缺少目录、名单为空、任一卡片无名称/主页或出现重复项时，导入失败，不覆盖上一份本地名单，后续抓取和发布步骤均不执行。故意清空全部友链也会触发此保护，需要另行确认后调整。

抓取结果全空、数量不一致或文章作者/头像不属于本轮名单时，发布校验失败，线上仍保留上一次部署。部分站点失败时沿用上游行为：发布其他成功站点的文章，并通过 `link.json` / `errors.json` 排查失败站点，不伪造旧文章为新结果。

工作流串行发布；`page` 使用普通推送并保留提交历史，不再强制覆写历史。若出现不期望的线上结果，先禁用 **Friend Circle Lite** 工作流，再从 Vercel 将之前正常的 Production Deployment 执行 Rollback。修复页面或代码后重新启用并手动运行。迁移旧服务前应另存旧部署地址和当前公开产物；已删除旧仓库的源码无法从这些产物完整恢复。

## 本地验证

```sh
python -m pip install -r requirements.txt
python -m unittest tests.test_ghost_directory
GHOST_FRIENDS_URL=http://localhost:2368/links/ python -m friend_circle_lite.ghost_directory
TZ=Asia/Shanghai python run.py
python -m friend_circle_lite.ghost_directory --validate-feed all.json
```

本地实例可用于验证提取和抓取，但带 localhost 头像的结果不能作为生产发布结果。完整上游测试为 `python -m unittest discover -s tests`；本次基线已有 3 项失败（静态首页字符串断言、RSS 缓存退避、请求异常耗时 mock），已在未修改基线上复现，新增同步测试独立执行。
