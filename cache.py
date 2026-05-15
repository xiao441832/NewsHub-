"""NewsHub - 内存缓存模块（TTL 过期 + 模式清除）

使用方式：
    from cache import cache, clear_cache

    @cache(ttl=300)  # 缓存 5 分钟
    def get_stats():
        ...

    clear_cache("tags")     # 清除所有 key 包含 "tags" 的缓存
    clear_cache()           # 清除全部缓存
"""
import time
import functools
import threading
from typing import Callable, Any

# 线程安全的缓存存储：{ key: (expire_timestamp, value) }
_cache_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def cache(ttl: int = 300):
    """
    内存缓存装饰器

    参数：
        ttl: 缓存过期时间（秒），默认 300 秒（5 分钟）

    用法：
        @cache(ttl=600)
        def my_func(arg1, arg2):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存 key：函数名 + 参数
            key_parts = [func.__qualname__]
            key_parts.extend(str(a) for a in args[1:])  # 跳过第一个 self/request 参数
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = "|".join(key_parts)

            # 检查缓存是否命中且未过期
            with _lock:
                if cache_key in _cache_store:
                    expire_ts, value = _cache_store[cache_key]
                    if time.time() < expire_ts:
                        return value
                    # 已过期，删除
                    del _cache_store[cache_key]

            # 缓存未命中，执行原函数
            result = func(*args, **kwargs)

            # 写入缓存
            with _lock:
                _cache_store[cache_key] = (time.time() + ttl, result)

            return result
        return wrapper
    return decorator


def clear_cache(pattern: str = ""):
    """
    清除缓存

    参数：
        pattern: 只清除 key 中包含此字符串的缓存；为空则清除全部
    """
    with _lock:
        if not pattern:
            count = len(_cache_store)
            _cache_store.clear()
            print(f"[Cache] 已清除全部缓存（{count} 条）")
        else:
            keys_to_remove = [k for k in _cache_store if pattern in k]
            for k in keys_to_remove:
                del _cache_store[k]
            print(f"[Cache] 已清除包含 '{pattern}' 的缓存（{len(keys_to_remove)} 条）")


def get_cache_stats() -> dict:
    """获取缓存统计信息（调试用）"""
    with _lock:
        now = time.time()
        total = len(_cache_store)
        expired = sum(1 for exp_ts, _ in _cache_store.values() if now >= exp_ts)
        return {
            "total_entries": total,
            "active": total - expired,
            "expired": expired,
        }
