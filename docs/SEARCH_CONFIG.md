# 搜索接口配置说明

搜索接口已并入 `config/api_config.py` 统一管理。详见 [LLM_CONFIG_GUIDE.md](./LLM_CONFIG_GUIDE.md)。

## 快速配置

```env
# 搜索供应商：mock | baidu
SEARCH_PROVIDER=baidu
BAIDU_SEARCH_API_KEY=bce-v3/ALTAK-xxx/xxx
# BAIDU_SEARCH_TOP_K=20
```

## 获取方式

- 从统一配置：`from config.api_config import get_search_config`
- 兼容层：`from config.search_config import get_search_config`

## 说明

- 未配置 `BAIDU_SEARCH_API_KEY` 或 `SEARCH_PROVIDER≠baidu` 时自动使用 mock 模式
- 百度千帆 Key 获取：<https://console.bce.baidu.com/qianfan/>
