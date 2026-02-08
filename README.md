# maimai_selfie_plugin

用于在群聊中按上下文自动生成“同一角色自拍图”，并提供底图管理命令。

## 安装与启用

1. 将目录放到 MaiBot 根目录 `plugins/` 下。  
2. 在插件配置中启用 `plugin.enabled=true` 与 `selfie.enabled=true`。  
3. 配置 `llm.*` 与 `image.*` 的 API 地址、密钥、模型。  

## 用法

- 设置底图：`/selfie_base set`（建议引用一条图片消息后执行）
- 查看底图：`/selfie_base show`
- 清空底图：`/selfie_base clear`
- 自动触发：聊天中出现关键词（默认：`自拍`、`照片`、`来张`、`发张`、`看看你`）
