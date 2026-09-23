# 本地中文 Embedding 服务

提供 OpenAI 兼容的 `/v1/embeddings` 接口，默认使用 FastEmbed 的
`BAAI/bge-small-zh-v1.5`（512 维、MIT 许可）。模型缓存在
`data/embedding-cache`，不会随容器重建重复下载。

```bash
docker compose -f docker-compose.yml -f docker-compose.embedding.yml up -d embedding-service
```

平台模型配置使用：`provider=local`、`api_base_url=http://embedding-service:8080/v1`、
`model_name=BAAI/bge-small-zh-v1.5`、`capabilities=["embedding"]`。
