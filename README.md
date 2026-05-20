# NewsHub 全球新闻聚合平台

一站式新闻聚合、智能分类、个性化阅读的全栈应用。

## 核心功能

- 多源爬虫：自动抓取央视、新浪、人民网、新华网、BBC、CNN 等 50+ 新闻源
- 智能分类：自动归类为国内、国际、财经、科技、军事、体育等 9 个分类
- 用户系统：注册登录、收藏文章、阅读历史、评论互动
- 管理后台：爬虫监控面板，实时查看各新闻源状态和数据统计
- 全文搜索：支持标题关键词搜索和标签筛选
- 定时任务：每 4 小时自动爬取，每月自动清理旧数据
- 暗色主题：支持明暗切换，PWA 可安装到手机桌面

## 技术栈

- 后端：FastAPI + SQLAlchemy + SQLite
- 前端：Tailwind CSS + Jinja2 模板
- 爬虫：Requests + BeautifulSoup
- 认证：JWT + Cookie 双重认证
- 部署：Cloudflare Tunnel 公网访问

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

访问 http://localhost:8080 即可使用。

## 项目结构

- main.py - 主程序和路由
- config.py - 新闻源和分类配置
- models.py - 数据库模型
- crawlers/ - 爬虫引擎
- templates/ - 页面模板
- data/ - SQLite 数据库
