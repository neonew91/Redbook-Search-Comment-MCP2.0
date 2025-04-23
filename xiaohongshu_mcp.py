from typing import Any, List, Dict, Optional
import asyncio
import json
import os
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright
from fastmcp import FastMCP

# 初始化 FastMCP 服务器
mcp = FastMCP("xiaohongshu_scraper")

# 全局变量
BROWSER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_data")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# 确保目录存在
os.makedirs(BROWSER_DATA_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# 用于存储浏览器上下文，以便在不同方法之间共享
browser_context = None
main_page = None
is_logged_in = False

async def ensure_browser():
    """确保浏览器已启动并登录"""
    global browser_context, main_page, is_logged_in
    
    if browser_context is None:
        # 启动浏览器
        playwright_instance = await async_playwright().start()
        
        # 使用持久化上下文来保存用户状态
        browser_context = await playwright_instance.chromium.launch_persistent_context(
            user_data_dir=BROWSER_DATA_DIR,
            headless=False,  # 非隐藏模式，方便用户登录
            viewport={"width": 1280, "height": 800},
            timeout=60000
        )
        
        # 创建一个新页面
        if browser_context.pages:
            main_page = browser_context.pages[0]
        else:
            main_page = await browser_context.new_page()
        
        # 设置页面级别的超时时间
        main_page.set_default_timeout(60000)
    
    # 检查登录状态
    if not is_logged_in:
        # 访问小红书首页
        await main_page.goto("https://www.xiaohongshu.com", timeout=60000)
        await asyncio.sleep(3)
        
        # 检查是否已登录
        login_elements = await main_page.query_selector_all('text="登录"')
        if login_elements:
            return False  # 需要登录
        else:
            is_logged_in = True
            return True  # 已登录
    
    return True

@mcp.tool()
async def login() -> str:
    """登录小红书账号"""
    global is_logged_in
    
    await ensure_browser()
    
    if is_logged_in:
        return "已登录小红书账号"
    
    # 访问小红书登录页面
    await main_page.goto("https://www.xiaohongshu.com", timeout=60000)
    await asyncio.sleep(3)
    
    # 查找登录按钮并点击
    login_elements = await main_page.query_selector_all('text="登录"')
    if login_elements:
        await login_elements[0].click()
        
        # 提示用户手动登录
        message = "请在打开的浏览器窗口中完成登录操作。登录成功后，系统将自动继续。"
        
        # 等待用户登录成功
        max_wait_time = 180  # 等待3分钟
        wait_interval = 5
        waited_time = 0
        
        while waited_time < max_wait_time:
            # 检查是否已登录成功
            still_login = await main_page.query_selector_all('text="登录"')
            if not still_login:
                is_logged_in = True
                await asyncio.sleep(2)  # 等待页面加载
                return "登录成功！"
            
            # 继续等待
            await asyncio.sleep(wait_interval)
            waited_time += wait_interval
        
        return "登录等待超时。请重试或手动登录后再使用其他功能。"
    else:
        is_logged_in = True
        return "已登录小红书账号"

@mcp.tool()
async def search_notes(keywords: str, limit: int = 5) -> str:
    """根据关键词搜索笔记
    
    Args:
        keywords: 搜索关键词
        limit: 返回结果数量限制
    """
    login_status = await ensure_browser()
    if not login_status:
        return "请先登录小红书账号"
    
    # 构建搜索URL并访问
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={keywords}"
    try:
        await main_page.goto(search_url, timeout=60000)
        await asyncio.sleep(5)  # 等待页面加载
        
        # 等待页面完全加载
        await asyncio.sleep(5)
        
        # 打印页面HTML用于调试
        page_html = await main_page.content()
        print(f"页面HTML片段: {page_html[10000:10500]}...")
        
        # 使用更精确的选择器获取帖子卡片
        print("尝试获取帖子卡片...")
        post_cards = await main_page.query_selector_all('section.note-item')
        print(f"找到 {len(post_cards)} 个帖子卡片")
        
        if not post_cards:
            # 尝试备用选择器
            post_cards = await main_page.query_selector_all('div[data-v-a264b01a]')
            print(f"使用备用选择器找到 {len(post_cards)} 个帖子卡片")
        
        post_links = []
        post_titles = []
        
        for card in post_cards:
            try:
                # 获取链接
                link_element = await card.query_selector('a[href*="/search_result/"]')
                if not link_element:
                    continue
                
                href = await link_element.get_attribute('href')
                if href and '/search_result/' in href:
                    full_url = f"https://www.xiaohongshu.com{href}"
                    post_links.append(full_url)
                    
                    # 尝试获取帖子标题
                    try:
                        # 打印卡片HTML用于调试
                        card_html = await card.inner_html()
                        print(f"卡片HTML片段: {card_html[:200]}...")
                        
                        # 首先尝试获取卡片内的footer中的标题
                        title_element = await card.query_selector('div.footer a.title span')
                        if title_element:
                            title = await title_element.text_content()
                            print(f"找到标题(方法1): {title}")
                        else:
                            # 尝试直接获取标题元素
                            title_element = await card.query_selector('a.title span')
                            if title_element:
                                title = await title_element.text_content()
                                print(f"找到标题(方法2): {title}")
                            else:
                                # 尝试获取任何可能的文本内容
                                text_elements = await card.query_selector_all('span')
                                potential_titles = []
                                for text_el in text_elements:
                                    text = await text_el.text_content()
                                    if text and len(text.strip()) > 5:
                                        potential_titles.append(text.strip())
                                
                                if potential_titles:
                                    # 选择最长的文本作为标题
                                    title = max(potential_titles, key=len)
                                    print(f"找到可能的标题(方法3): {title}")
                                else:
                                    # 尝试直接获取卡片中的所有文本
                                    all_text = await card.evaluate('el => Array.from(el.querySelectorAll("*")).map(node => node.textContent).filter(text => text && text.trim().length > 5)')
                                    if all_text and len(all_text) > 0:
                                        # 选择最长的文本作为标题
                                        title = max(all_text, key=len)
                                        print(f"找到可能的标题(方法4): {title}")
                                    else:
                                        title = "未知标题"
                                        print("无法找到标题，使用默认值'未知标题'")
                        
                        # 如果获取到的标题为空，设为未知标题
                        if not title or title.strip() == "":
                            title = "未知标题"
                            print("获取到的标题为空，使用默认值'未知标题'")
                    except Exception as e:
                        print(f"获取标题时出错: {str(e)}")
                        title = "未知标题"
                    
                    post_titles.append(title)
            except Exception as e:
                print(f"处理帖子卡片时出错: {str(e)}")
        
        # 去重
        unique_posts = []
        seen_urls = set()
        for url, title in zip(post_links, post_titles):
            if url not in seen_urls:
                seen_urls.add(url)
                unique_posts.append({"url": url, "title": title})
        
        # 限制返回数量
        unique_posts = unique_posts[:limit]
        
        # 格式化返回结果
        if unique_posts:
            result = "搜索结果：\n\n"
            for i, post in enumerate(unique_posts, 1):
                result += f"{i}. {post['title']}\n   链接: {post['url']}\n\n"
            
            return result
        else:
            return f"未找到与\"{keywords}\"相关的笔记"
    
    except Exception as e:
        return f"搜索笔记时出错: {str(e)}"

@mcp.tool()
async def get_note_content(url: str) -> str:
    """获取笔记内容
    
    Args:
        url: 笔记 URL
    """
    login_status = await ensure_browser()
    if not login_status:
        return "请先登录小红书账号"
    
    try:
        # 访问帖子链接
        await main_page.goto(url, timeout=60000)
        await asyncio.sleep(10)  # 增加等待时间到10秒
        
        # 增强滚动操作以确保所有内容加载
        await main_page.evaluate('''
            () => {
                // 先滚动到页面底部
                window.scrollTo(0, document.body.scrollHeight);
                setTimeout(() => { 
                    // 然后滚动到中间
                    window.scrollTo(0, document.body.scrollHeight / 2); 
                }, 1000);
                setTimeout(() => { 
                    // 最后回到顶部
                    window.scrollTo(0, 0); 
                }, 2000);
            }
        ''')
        await asyncio.sleep(3)  # 等待滚动完成和内容加载
        
        # 打印页面结构片段用于分析
        try:
            print("打印页面结构片段用于分析")
            page_structure = await main_page.evaluate('''
                () => {
                    // 获取笔记内容区域
                    const noteContent = document.querySelector('.note-content');
                    const detailDesc = document.querySelector('#detail-desc');
                    const commentArea = document.querySelector('.comments-container, .comment-list');
                    
                    return {
                        hasNoteContent: !!noteContent,
                        hasDetailDesc: !!detailDesc,
                        hasCommentArea: !!commentArea,
                        noteContentHtml: noteContent ? noteContent.outerHTML.slice(0, 500) : null,
                        detailDescHtml: detailDesc ? detailDesc.outerHTML.slice(0, 500) : null,
                        commentAreaFirstChild: commentArea ? 
                            (commentArea.firstElementChild ? commentArea.firstElementChild.outerHTML.slice(0, 500) : null) : null
                    };
                }
            ''')
            print(f"页面结构分析: {json.dumps(page_structure, ensure_ascii=False, indent=2)}")
        except Exception as e:
            print(f"打印页面结构时出错: {str(e)}")
        
        # 获取帖子内容
        post_content = {}
        
        # 获取帖子标题 - 方法1：使用id选择器
        try:
            print("尝试获取标题 - 方法1：使用id选择器")
            title_element = await main_page.query_selector('#detail-title')
            if title_element:
                title = await title_element.text_content()
                post_content["标题"] = title.strip() if title else "未知标题"
                print(f"方法1获取到标题: {post_content['标题']}")
            else:
                print("方法1未找到标题元素")
                post_content["标题"] = "未知标题"
        except Exception as e:
            print(f"方法1获取标题出错: {str(e)}")
            post_content["标题"] = "未知标题"
        
        # 获取帖子标题 - 方法2：使用class选择器
        if post_content["标题"] == "未知标题":
            try:
                print("尝试获取标题 - 方法2：使用class选择器")
                title_element = await main_page.query_selector('div.title')
                if title_element:
                    title = await title_element.text_content()
                    post_content["标题"] = title.strip() if title else "未知标题"
                    print(f"方法2获取到标题: {post_content['标题']}")
                else:
                    print("方法2未找到标题元素")
            except Exception as e:
                print(f"方法2获取标题出错: {str(e)}")
        
        # 获取帖子标题 - 方法3：使用JavaScript
        if post_content["标题"] == "未知标题":
            try:
                print("尝试获取标题 - 方法3：使用JavaScript")
                title = await main_page.evaluate('''
                    () => {
                        // 尝试多种可能的标题选择器
                        const selectors = [
                            '#detail-title',
                            'div.title',
                            'h1',
                            'div.note-content div.title'
                        ];
                        
                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el && el.textContent.trim()) {
                                return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                ''')
                if title:
                    post_content["标题"] = title
                    print(f"方法3获取到标题: {post_content['标题']}")
                else:
                    print("方法3未找到标题元素")
            except Exception as e:
                print(f"方法3获取标题出错: {str(e)}")
        
        # 获取作者 - 方法1：使用username类选择器
        try:
            print("尝试获取作者 - 方法1：使用username类选择器")
            author_element = await main_page.query_selector('span.username')
            if author_element:
                author = await author_element.text_content()
                post_content["作者"] = author.strip() if author else "未知作者"
                print(f"方法1获取到作者: {post_content['作者']}")
            else:
                print("方法1未找到作者元素")
                post_content["作者"] = "未知作者"
        except Exception as e:
            print(f"方法1获取作者出错: {str(e)}")
            post_content["作者"] = "未知作者"
        
        # 获取作者 - 方法2：使用链接选择器
        if post_content["作者"] == "未知作者":
            try:
                print("尝试获取作者 - 方法2：使用链接选择器")
                author_element = await main_page.query_selector('a.name')
                if author_element:
                    author = await author_element.text_content()
                    post_content["作者"] = author.strip() if author else "未知作者"
                    print(f"方法2获取到作者: {post_content['作者']}")
                else:
                    print("方法2未找到作者元素")
            except Exception as e:
                print(f"方法2获取作者出错: {str(e)}")
        
        # 获取作者 - 方法3：使用JavaScript
        if post_content["作者"] == "未知作者":
            try:
                print("尝试获取作者 - 方法3：使用JavaScript")
                author = await main_page.evaluate('''
                    () => {
                        // 尝试多种可能的作者选择器
                        const selectors = [
                            'span.username',
                            'a.name',
                            '.author-wrapper .username',
                            '.info .name'
                        ];
                        
                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el && el.textContent.trim()) {
                                return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                ''')
                if author:
                    post_content["作者"] = author
                    print(f"方法3获取到作者: {post_content['作者']}")
                else:
                    print("方法3未找到作者元素")
            except Exception as e:
                print(f"方法3获取作者出错: {str(e)}")
        
        # 获取发布时间 - 方法1：使用date类选择器
        try:
            print("尝试获取发布时间 - 方法1：使用date类选择器")
            time_element = await main_page.query_selector('span.date')
            if time_element:
                time_text = await time_element.text_content()
                post_content["发布时间"] = time_text.strip() if time_text else "未知"
                print(f"方法1获取到发布时间: {post_content['发布时间']}")
            else:
                print("方法1未找到发布时间元素")
                post_content["发布时间"] = "未知"
        except Exception as e:
            print(f"方法1获取发布时间出错: {str(e)}")
            post_content["发布时间"] = "未知"
        
        # 获取发布时间 - 方法2：使用正则表达式匹配
        if post_content["发布时间"] == "未知":
            try:
                print("尝试获取发布时间 - 方法2：使用正则表达式匹配")
                time_selectors = [
                    'text=/编辑于/',
                    'text=/\\d{2}-\\d{2}/',
                    'text=/\\d{4}-\\d{2}-\\d{2}/',
                    'text=/\\d+月\\d+日/',
                    'text=/\\d+天前/',
                    'text=/\\d+小时前/',
                    'text=/今天/',
                    'text=/昨天/'
                ]
                
                for selector in time_selectors:
                    time_element = await main_page.query_selector(selector)
                    if time_element:
                        time_text = await time_element.text_content()
                        post_content["发布时间"] = time_text.strip() if time_text else "未知"
                        print(f"方法2获取到发布时间: {post_content['发布时间']}")
                        break
                    else:
                        print(f"方法2未找到发布时间元素: {selector}")
            except Exception as e:
                print(f"方法2获取发布时间出错: {str(e)}")
        
        # 获取发布时间 - 方法3：使用JavaScript
        if post_content["发布时间"] == "未知":
            try:
                print("尝试获取发布时间 - 方法3：使用JavaScript")
                time_text = await main_page.evaluate('''
                    () => {
                        // 尝试多种可能的时间选择器
                        const selectors = [
                            'span.date',
                            '.bottom-container .date',
                            '.date'
                        ];
                        
                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el && el.textContent.trim()) {
                                return el.textContent.trim();
                            }
                        }
                        
                        // 尝试查找包含日期格式的文本
                        const dateRegexes = [
                            /编辑于\s*([\d-]+)/,
                            /(\d{2}-\d{2})/,
                            /(\d{4}-\d{2}-\d{2})/,
                            /(\d+月\d+日)/,
                            /(\d+天前)/,
                            /(\d+小时前)/,
                            /(今天)/,
                            /(昨天)/
                        ];
                        
                        const allText = document.body.textContent;
                        for (const regex of dateRegexes) {
                            const match = allText.match(regex);
                            if (match) {
                                return match[0];
                            }
                        }
                        
                        return null;
                    }
                ''')
                if time_text:
                    post_content["发布时间"] = time_text
                    print(f"方法3获取到发布时间: {post_content['发布时间']}")
                else:
                    print("方法3未找到发布时间元素")
            except Exception as e:
                print(f"方法3获取发布时间出错: {str(e)}")
        
        # 获取帖子正文内容 - 方法1：使用精确的ID和class选择器
        try:
            print("尝试获取正文内容 - 方法1：使用精确的ID和class选择器")
            
            # 先明确标记评论区域
            await main_page.evaluate('''
                () => {
                    const commentSelectors = [
                        '.comments-container', 
                        '.comment-list',
                        '.feed-comment',
                        'div[data-v-aed4aacc]',  // 根据您提供的评论HTML结构
                        '.content span.note-text'  // 评论中的note-text结构
                    ];
                    
                    for (const selector of commentSelectors) {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) {
                                el.setAttribute('data-is-comment', 'true');
                                console.log('标记评论区域:', el.tagName, el.className);
                            }
                        });
                    }
                }
            ''')
            
            # 先尝试获取detail-desc和note-text组合
            content_element = await main_page.query_selector('#detail-desc .note-text')
            if content_element:
                # 检查是否在评论区域内
                is_in_comment = await content_element.evaluate('(el) => !!el.closest("[data-is-comment=\'true\']") || false')
                if not is_in_comment:
                    content_text = await content_element.text_content()
                    if content_text and len(content_text.strip()) > 50:  # 增加长度阈值
                        post_content["内容"] = content_text.strip()
                        print(f"方法1获取到正文内容，长度: {len(post_content['内容'])}")
                    else:
                        print(f"方法1获取到的内容太短: {len(content_text.strip() if content_text else 0)}")
                        post_content["内容"] = "未能获取内容"
                else:
                    print("方法1找到的元素在评论区域内，跳过")
                    post_content["内容"] = "未能获取内容"
            else:
                print("方法1未找到正文内容元素")
                post_content["内容"] = "未能获取内容"
        except Exception as e:
            print(f"方法1获取正文内容出错: {str(e)}")
            post_content["内容"] = "未能获取内容"
        
        # 获取帖子正文内容 - 方法2：使用XPath选择器
        if post_content["内容"] == "未能获取内容":
            try:
                print("尝试获取正文内容 - 方法2：使用XPath选择器")
                # 使用XPath获取笔记内容区域
                content_text = await main_page.evaluate('''
                    () => {
                        const xpath = '//div[@id="detail-desc"]/span[@class="note-text"]';
                        const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        const element = result.singleNodeValue;
                        return element ? element.textContent.trim() : null;
                    }
                ''')
                
                if content_text and len(content_text) > 20:
                    post_content["内容"] = content_text
                    print(f"方法2获取到正文内容，长度: {len(post_content['内容'])}")
                else:
                    print(f"方法2获取到的内容太短或为空: {len(content_text) if content_text else 0}")
            except Exception as e:
                print(f"方法2获取正文内容出错: {str(e)}")
        
        # 获取帖子正文内容 - 方法3：使用JavaScript获取最长文本
        if post_content["内容"] == "未能获取内容":
            try:
                print("尝试获取正文内容 - 方法3：使用JavaScript获取最长文本")
                content_text = await main_page.evaluate('''
                    () => {
                        // 定义评论区域选择器
                        const commentSelectors = [
                            '.comments-container', 
                            '.comment-list',
                            '.feed-comment',
                            'div[data-v-aed4aacc]',
                            '.comment-item',
                            '[data-is-comment="true"]'
                        ];
                        
                        // 找到所有评论区域
                        let commentAreas = [];
                        for (const selector of commentSelectors) {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => commentAreas.push(el));
                        }
                        
                        // 查找可能的内容元素，排除评论区
                        const contentElements = Array.from(document.querySelectorAll('div#detail-desc, div.note-content, div.desc, span.note-text'))
                            .filter(el => {
                                // 检查是否在评论区域内
                                const isInComment = commentAreas.some(commentArea => 
                                    commentArea && commentArea.contains(el));
                                
                                if (isInComment) {
                                    console.log('排除评论区域内容:', el.tagName, el.className);
                                    return false;
                                }
                                
                                const text = el.textContent.trim();
                                return text.length > 100 && text.length < 10000;
                            })
                            .sort((a, b) => b.textContent.length - a.textContent.length);
                        
                        if (contentElements.length > 0) {
                            console.log('找到内容元素:', contentElements[0].tagName, contentElements[0].className);
                            return contentElements[0].textContent.trim();
                        }
                        
                        return null;
                    }
                ''')
                
                if content_text and len(content_text) > 100:  # 增加长度阈值
                    post_content["内容"] = content_text
                    print(f"方法3获取到正文内容，长度: {len(post_content['内容'])}")
                else:
                    print(f"方法3获取到的内容太短或为空: {len(content_text) if content_text else 0}")
            except Exception as e:
                print(f"方法3获取正文内容出错: {str(e)}")
        
        # 获取帖子正文内容 - 方法4：区分正文和评论内容
        if post_content["内容"] == "未能获取内容":
            try:
                print("尝试获取正文内容 - 方法4：区分正文和评论内容")
                content_text = await main_page.evaluate('''
                    () => {
                        // 首先尝试获取note-content区域
                        const noteContent = document.querySelector('.note-content');
                        if (noteContent) {
                            // 查找note-text，这通常包含主要内容
                            const noteText = noteContent.querySelector('.note-text');
                            if (noteText && noteText.textContent.trim().length > 50) {
                                return noteText.textContent.trim();
                            }
                            
                            // 如果没有找到note-text或内容太短，返回整个note-content
                            if (noteContent.textContent.trim().length > 50) {
                                return noteContent.textContent.trim();
                            }
                        }
                        
                        // 如果上面的方法都失败了，尝试获取所有段落并拼接
                        const paragraphs = Array.from(document.querySelectorAll('p'))
                            .filter(p => {
                                // 排除评论区段落
                                const isInComments = p.closest('.comments-container, .comment-list');
                                return !isInComments && p.textContent.trim().length > 10;
                            });
                            
                        if (paragraphs.length > 0) {
                            return paragraphs.map(p => p.textContent.trim()).join('\n\n');
                        }
                        
                        return null;
                    }
                ''')
                
                if content_text and len(content_text) > 50:
                    post_content["内容"] = content_text
                    print(f"方法4获取到正文内容，长度: {len(post_content['内容'])}")
                else:
                    print(f"方法4获取到的内容太短或为空: {len(content_text) if content_text else 0}")
            except Exception as e:
                print(f"方法4获取正文内容出错: {str(e)}")
        
        # 获取帖子正文内容 - 方法5：直接通过DOM结构定位
        if post_content["内容"] == "未能获取内容":
            try:
                print("尝试获取正文内容 - 方法5：直接通过DOM结构定位")
                content_text = await main_page.evaluate('''
                    () => {
                        // 根据您提供的HTML结构直接定位
                        const noteContent = document.querySelector('div.note-content');
                        if (noteContent) {
                            const detailTitle = noteContent.querySelector('#detail-title');
                            const detailDesc = noteContent.querySelector('#detail-desc');
                            
                            if (detailDesc) {
                                const noteText = detailDesc.querySelector('span.note-text');
                                if (noteText) {
                                    return noteText.textContent.trim();
                                }
                                return detailDesc.textContent.trim();
                            }
                        }
                        
                        // 尝试其他可能的结构
                        const descElements = document.querySelectorAll('div.desc');
                        for (const desc of descElements) {
                            // 检查是否在评论区
                            const isInComment = desc.closest('.comments-container, .comment-list, .feed-comment');
                            if (!isInComment && desc.textContent.trim().length > 100) {
                                return desc.textContent.trim();
                            }
                        }
                        
                        return null;
                    }
                ''')
                
                if content_text and len(content_text) > 100:
                    post_content["内容"] = content_text
                    print(f"方法5获取到正文内容，长度: {len(post_content['内容'])}")
                else:
                    print(f"方法5获取到的内容太短或为空: {len(content_text) if content_text else 0}")
            except Exception as e:
                print(f"方法5获取正文内容出错: {str(e)}")
        
        # 格式化返回结果
        result = f"标题: {post_content['标题']}\n"
        result += f"作者: {post_content['作者']}\n"
        result += f"发布时间: {post_content['发布时间']}\n"
        result += f"链接: {url}\n\n"
        result += f"内容:\n{post_content['内容']}"
        
        return result
    
    except Exception as e:
        return f"获取笔记内容时出错: {str(e)}"

@mcp.tool()
async def get_note_comments(url: str) -> str:
    """获取笔记评论
    
    Args:
        url: 笔记 URL
    """
    login_status = await ensure_browser()
    if not login_status:
        return "请先登录小红书账号"
    
    try:
        # 访问帖子链接
        await main_page.goto(url, timeout=60000)
        await asyncio.sleep(5)  # 等待页面加载
        
        # 先滚动到评论区
        comment_section_locators = [
            main_page.get_by_text("条评论", exact=False),
            main_page.get_by_text("评论", exact=False),
            main_page.locator("text=评论").first
        ]
        
        for locator in comment_section_locators:
            try:
                if await locator.count() > 0:
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue
        
        # 滚动页面以加载更多评论
        for i in range(8):
            try:
                await main_page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1)
                
                # 尝试点击"查看更多评论"按钮
                more_comment_selectors = [
                    "text=查看更多评论",
                    "text=展开更多评论",
                    "text=加载更多",
                    "text=查看全部"
                ]
                
                for selector in more_comment_selectors:
                    try:
                        more_btn = main_page.locator(selector).first
                        if await more_btn.count() > 0 and await more_btn.is_visible():
                            await more_btn.click()
                            await asyncio.sleep(2)
                    except Exception:
                        continue
            except Exception:
                pass
        
        # 获取评论
        comments = []
        
        # 使用特定评论选择器
        comment_selectors = [
            "div.comment-item", 
            "div.commentItem",
            "div.comment-content",
            "div.comment-wrapper",
            "section.comment",
            "div.feed-comment"
        ]
        
        for selector in comment_selectors:
            comment_elements = main_page.locator(selector)
            count = await comment_elements.count()
            if count > 0:
                for i in range(count):
                    try:
                        comment_element = comment_elements.nth(i)
                        
                        # 提取评论者名称
                        username = "未知用户"
                        username_selectors = ["span.user-name", "a.name", "div.username", "span.nickname", "a.user-nickname"]
                        for username_selector in username_selectors:
                            username_el = comment_element.locator(username_selector).first
                            if await username_el.count() > 0:
                                username = await username_el.text_content()
                                username = username.strip()
                                break
                        
                        # 如果没有找到，尝试通过用户链接查找
                        if username == "未知用户":
                            user_link = comment_element.locator('a[href*="/user/profile/"]').first
                            if await user_link.count() > 0:
                                username = await user_link.text_content()
                                username = username.strip()
                        
                        # 提取评论内容
                        content = "未知内容"
                        content_selectors = ["div.content", "p.content", "div.text", "span.content", "div.comment-text"]
                        for content_selector in content_selectors:
                            content_el = comment_element.locator(content_selector).first
                            if await content_el.count() > 0:
                                content = await content_el.text_content()
                                content = content.strip()
                                break
                        
                        # 如果没有找到内容，可能内容就在评论元素本身
                        if content == "未知内容":
                            full_text = await comment_element.text_content()
                            if username != "未知用户" and username in full_text:
                                content = full_text.replace(username, "").strip()
                            else:
                                content = full_text.strip()
                        
                        # 提取评论时间
                        time_location = "未知时间"
                        time_selectors = ["span.time", "div.time", "span.date", "div.date", "time"]
                        for time_selector in time_selectors:
                            time_el = comment_element.locator(time_selector).first
                            if await time_el.count() > 0:
                                time_location = await time_el.text_content()
                                time_location = time_location.strip()
                                break
                        
                        # 如果内容有足够长度且找到用户名，添加评论
                        if username != "未知用户" and content != "未知内容" and len(content) > 2:
                            comments.append({
                                "用户名": username,
                                "内容": content,
                                "时间": time_location
                            })
                    except Exception:
                        continue
                
                # 如果找到了评论，就不继续尝试其他选择器了
                if comments:
                    break
        
        # 如果没有找到评论，尝试使用其他方法
        if not comments:
            # 获取所有用户名元素
            username_elements = main_page.locator('a[href*="/user/profile/"]')
            username_count = await username_elements.count()
            
            if username_count > 0:
                for i in range(username_count):
                    try:
                        username_element = username_elements.nth(i)
                        username = await username_element.text_content()
                        
                        # 尝试获取评论内容
                        content = await main_page.evaluate('''
                            (usernameElement) => {
                                const parent = usernameElement.parentElement;
                                if (!parent) return null;
                                
                                // 尝试获取同级的下一个元素
                                let sibling = usernameElement.nextElementSibling;
                                while (sibling) {
                                    const text = sibling.textContent.trim();
                                    if (text) return text;
                                    sibling = sibling.nextElementSibling;
                                }
                                
                                // 尝试获取父元素的文本，并过滤掉用户名
                                const allText = parent.textContent.trim();
                                if (allText && allText.includes(usernameElement.textContent.trim())) {
                                    return allText.replace(usernameElement.textContent.trim(), '').trim();
                                }
                                
                                return null;
                            }
                        ''', username_element)
                        
                        if username and content:
                            comments.append({
                                "用户名": username.strip(),
                                "内容": content.strip(),
                                "时间": "未知时间"
                            })
                    except Exception:
                        continue
        
        # 格式化返回结果
        if comments:
            result = f"共获取到 {len(comments)} 条评论：\n\n"
            for i, comment in enumerate(comments, 1):
                result += f"{i}. {comment['用户名']}（{comment['时间']}）: {comment['内容']}\n\n"
            return result
        else:
            return "未找到任何评论，可能是帖子没有评论或评论区无法访问。"
    
    except Exception as e:
        return f"获取评论时出错: {str(e)}"

@mcp.tool()
async def analyze_note(url: str) -> dict:
    """获取并分析笔记内容，返回笔记的详细信息供AI生成评论
    
    Args:
        url: 笔记 URL
    """
    login_status = await ensure_browser()
    if not login_status:
        return {"error": "请先登录小红书账号"}
    
    try:
        # 直接调用get_note_content获取笔记内容
        note_content_result = await get_note_content(url)
        
        # 检查是否获取成功
        if note_content_result.startswith("请先登录") or note_content_result.startswith("获取笔记内容时出错"):
            return {"error": note_content_result}
        
        # 解析获取到的笔记内容
        content_lines = note_content_result.strip().split('\n')
        post_content = {}
        
        # 提取标题、作者、发布时间和内容
        for i, line in enumerate(content_lines):
            if line.startswith("标题:"):
                post_content["标题"] = line.replace("标题:", "").strip()
            elif line.startswith("作者:"):
                post_content["作者"] = line.replace("作者:", "").strip()
            elif line.startswith("发布时间:"):
                post_content["发布时间"] = line.replace("发布时间:", "").strip()
            elif line.startswith("内容:"):
                # 内容可能有多行，获取剩余所有行
                content_text = "\n".join(content_lines[i+1:]).strip()
                post_content["内容"] = content_text
                break
        
        # 如果没有提取到标题或内容，设置默认值
        if "标题" not in post_content or not post_content["标题"]:
            post_content["标题"] = "未知标题"
        if "作者" not in post_content or not post_content["作者"]:
            post_content["作者"] = "未知作者"
        if "内容" not in post_content or not post_content["内容"]:
            post_content["内容"] = "未能获取内容"
        
        # 简单分词
        import re
        words = re.findall(r'\w+', f"{post_content.get('标题', '')} {post_content.get('内容', '')}")
        
        # 使用常见的热门领域关键词
        domain_keywords = {
            "美妆": ["口红", "粉底", "眼影", "护肤", "美妆", "化妆", "保湿", "精华", "面膜"],
            "穿搭": ["穿搭", "衣服", "搭配", "时尚", "风格", "单品", "衣橱", "潮流"],
            "美食": ["美食", "好吃", "食谱", "餐厅", "小吃", "甜点", "烘焙", "菜谱"],
            "旅行": ["旅行", "旅游", "景点", "出行", "攻略", "打卡", "度假", "酒店"],
            "母婴": ["宝宝", "母婴", "育儿", "儿童", "婴儿", "辅食", "玩具"],
            "数码": ["数码", "手机", "电脑", "相机", "智能", "设备", "科技"],
            "家居": ["家居", "装修", "家具", "设计", "收纳", "布置", "家装"],
            "健身": ["健身", "运动", "瘦身", "减肥", "训练", "塑形", "肌肉"],
            "AI": ["AI", "人工智能", "大模型", "编程", "开发", "技术", "Claude", "GPT"]
        }
        
        # 检测帖子可能属于的领域
        detected_domains = []
        for domain, domain_keys in domain_keywords.items():
            for key in domain_keys:
                if key.lower() in post_content.get("标题", "").lower() or key.lower() in post_content.get("内容", "").lower():
                    detected_domains.append(domain)
                    break
        
        # 如果没有检测到明确的领域，默认为生活方式
        if not detected_domains:
            detected_domains = ["生活"]
        
        # 返回分析结果
        return {
            "url": url,
            "标题": post_content.get("标题", "未知标题"),
            "作者": post_content.get("作者", "未知作者"),
            "内容": post_content.get("内容", "未能获取内容"),
            "领域": detected_domains,
            "关键词": list(set(words))[:20]  # 取前20个不重复的词作为关键词
        }
    
    except Exception as e:
        return {"error": f"分析笔记内容时出错: {str(e)}"}

@mcp.tool()
async def post_smart_comment(url: str, comment_type: str = "引流") -> dict:
    """根据帖子内容发布智能评论，增加曝光并引导用户关注或私聊
    
    Args:
        url: 笔记 URL
        comment_type: 评论类型，可选值:
                     "引流" - 引导用户关注或私聊
                     "点赞" - 简单互动获取好感
                     "咨询" - 以问题形式增加互动
                     "专业" - 展示专业知识建立权威
    """
    # 获取笔记内容
    note_info = await analyze_note(url)
    
    if "error" in note_info:
        return {"error": note_info["error"]}
    
    # 返回笔记分析结果和评论类型，让MCP客户端(如Claude)生成评论
    # MCP客户端生成评论后，应调用post_comment函数发布评论
    return {
        "note_info": note_info,
        "comment_type": comment_type,
        "message": "请根据笔记内容和评论类型，生成一条自然、相关的评论，要求口语化表达，简短凝练，不超过30字，然后使用post_comment函数发布"
    }

# 我们已经将原来的post_smart_comment函数重构为三个独立的函数：
# 1. analyze_note - 获取并分析笔记内容
# 2. post_comment - 发布评论
# 3. post_smart_comment - 结合前两个功能，使用MCP客户端的AI能力生成评论

@mcp.tool()
async def post_comment(url: str, comment: str) -> str:
    """发布评论到指定笔记
    
    Args:
        url: 笔记 URL
        comment: 要发布的评论内容
    """
    login_status = await ensure_browser()
    if not login_status:
        return "请先登录小红书账号，才能发布评论"
    
    try:
        # 访问帖子链接
        await main_page.goto(url, timeout=60000)
        await asyncio.sleep(5)  # 等待页面加载
        
        # 基于页面快照定位评论输入框
        # 先定位评论区域
        try:
            # 先尝试找到评论数量区域，它通常包含"条评论"文本
            comment_count_selectors = [
                'text="条评论"',
                'text="共 " >> xpath=..',
                'text=/\\d+ 条评论/',
            ]
            
            for selector in comment_count_selectors:
                try:
                    comment_count_element = await main_page.query_selector(selector)
                    if comment_count_element:
                        await comment_count_element.scroll_into_view_if_needed()
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue
                
            # 定位评论输入框
            input_box_selectors = [
                'paragraph:has-text("说点什么...")',
                'text="说点什么..."',
                'text="评论发布后所有人都能看到"',
                'div[contenteditable="true"]'
            ]
            
            comment_input = None
            for selector in input_box_selectors:
                try:
                    input_element = await main_page.query_selector(selector)
                    if input_element and await input_element.is_visible():
                        await input_element.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        comment_input = input_element
                        break
                except Exception:
                    continue
                    
            # 如果上面的方法都失败了，尝试使用JavaScript查找
            if not comment_input:
                comment_input = await main_page.evaluate('''
                    () => {
                        // 查找包含"说点什么..."的元素
                        const elements = Array.from(document.querySelectorAll('*'))
                            .filter(el => el.textContent && el.textContent.includes('说点什么...'));
                        if (elements.length > 0) return elements[0];
                        
                        // 查找可编辑的div元素
                        const editableDivs = Array.from(document.querySelectorAll('div[contenteditable="true"]'));
                        if (editableDivs.length > 0) return editableDivs[0];
                        
                        return null;
                    }
                ''')
                
                if comment_input:
                    comment_input = await main_page.query_selector_all('*')[-1]  # 使用最后一个元素作为占位符
            
            if not comment_input:
                return "未能找到评论输入框，无法发布评论"
            
            # 点击评论输入框
            await comment_input.click()
            await asyncio.sleep(1)
            
            # 使用键盘输入评论内容
            await main_page.keyboard.type(comment)
            await asyncio.sleep(1)
            
            # 尝试使用Enter键发送
            try:
                # 寻找发送按钮
                send_button_selectors = [
                    'button:has-text("发送")',
                    'button[aria-ref^="s"]'
                ]
                
                send_button = None
                for selector in send_button_selectors:
                    elements = await main_page.query_selector_all(selector)
                    for element in elements:
                        text_content = await element.text_content()
                        if text_content and '发送' in text_content:
                            send_button = element
                            break
                    if send_button:
                        break
                
                if send_button:
                    await send_button.click()
                else:
                    # 如果找不到发送按钮，使用Enter键
                    await main_page.keyboard.press('Enter')
                
                await asyncio.sleep(3)  # 等待评论发送完成
                
                return f"已成功发布评论：{comment}"
            except Exception as e:
                # 如果点击发送按钮失败，尝试通过Enter键发送
                try:
                    await main_page.keyboard.press('Enter')
                    await asyncio.sleep(3)
                    return f"已通过Enter键发送评论：{comment}"
                except Exception as press_error:
                    return f"尝试发送评论时出错: {str(e)}，尝试Enter键也失败: {str(press_error)}"
                
        except Exception as e:
            return f"操作评论区时出错: {str(e)}"
    
    except Exception as e:
        return f"发布评论时出错: {str(e)}"

async def _generate_smart_comment(post_content, comment_type):
    """根据帖子内容和评论类型生成智能评论"""
    title = post_content.get("标题", "")
    content = post_content.get("内容", "")
    author = post_content.get("作者", "")
    
    # 提取帖子关键词
    keywords = []
    
    # 简单分词
    import re
    words = re.findall(r'\w+', f"{title} {content}")
    
    # 使用常见的热门领域关键词
    domain_keywords = {
        "美妆": ["口红", "粉底", "眼影", "护肤", "美妆", "化妆", "保湿", "精华", "面膜"],
        "穿搭": ["穿搭", "衣服", "搭配", "时尚", "风格", "单品", "衣橱", "潮流"],
        "美食": ["美食", "好吃", "食谱", "餐厅", "小吃", "甜点", "烘焙", "菜谱"],
        "旅行": ["旅行", "旅游", "景点", "出行", "攻略", "打卡", "度假", "酒店"],
        "母婴": ["宝宝", "母婴", "育儿", "儿童", "婴儿", "辅食", "玩具"],
        "数码": ["数码", "手机", "电脑", "相机", "智能", "设备", "科技"],
        "家居": ["家居", "装修", "家具", "设计", "收纳", "布置", "家装"],
        "健身": ["健身", "运动", "瘦身", "减肥", "训练", "塑形", "肌肉"]
    }
    
    # 检测帖子可能属于的领域
    detected_domains = []
    for domain, domain_keys in domain_keywords.items():
        for key in domain_keys:
            if key in title.lower() or key in content.lower():
                detected_domains.append(domain)
                break
    
    # 如果没有检测到明确的领域，默认为生活方式
    if not detected_domains:
        detected_domains = ["生活"]
    
    # 根据评论类型生成评论模板
    templates = {
        "引流": [
            f"这个{detected_domains[0]}分享真不错！我也在研究相关内容，欢迎私信交流~",
            f"谢谢分享，{author}的见解很独到！我也整理了一些相关资料，感兴趣可以找我聊聊",
            f"看了你的分享受益匪浅，我在公号上也写过类似的内容，感兴趣可以来找我",
            f"非常喜欢你的分享风格！我也做{detected_domains[0]}相关内容，可以互相关注交流",
            f"太有共鸣了！我也遇到过类似情况，想了解更多可以私信我",
            f"这篇帖子信息量好大！我收藏了，有问题可以一起讨论哦~"
        ],
        "点赞": [
            f"太赞了！{author}的分享总是这么实用",
            f"每次看到{author}的分享都很有收获，继续关注了",
            f"这篇内容整理得超详细，学到了很多，感谢分享！",
            f"喜欢这种深度分享，比一般的{detected_domains[0]}帖子有内涵多了",
            f"已经收藏并点赞了，很有参考价值",
            f"这种高质量内容太少见了，感谢博主分享"
        ],
        "咨询": [
            f"请问博主，对于{detected_domains[0]}有什么入门建议吗？",
            f"这个{detected_domains[0]}技巧看起来很实用，适合新手尝试吗？",
            f"博主分享的经验太宝贵了，能详细说说你是怎么开始的吗？",
            f"看完很受启发，想请教一下{author}，如何能做到这么专业的水平？",
            f"对这个领域很感兴趣，有没有推荐的学习资源可以分享？",
            f"博主的见解很独到，能不能分享一下你的学习路径？"
        ],
        "专业": [
            f"作为{detected_domains[0]}领域从业者，很认同博主的观点，特别是关于{title[:10]}这部分",
            f"从专业角度来看，这篇分享涵盖了关键点，我还想补充的是...",
            f"这个内容分析很到位，我在实践中也发现了类似规律，非常认同",
            f"很专业的分享！我从事相关工作多年，这些方法确实有效",
            f"这篇内容的深度令人印象深刻，展现了博主的专业素养",
            f"从技术角度看，博主分享的方法非常具有可行性，值得一试"
        ]
    }
    
    import random
    
    # 确保评论类型有效
    if comment_type not in templates:
        comment_type = "引流"  # 默认使用引流模板
    
    # 随机选择一个模板
    selected_template = random.choice(templates[comment_type])
    
    # 如果是专业类型的评论，可以添加一些行业术语
    if comment_type == "专业":
        domain_terms = {
            "美妆": ["妆效", "质地", "显色度", "持妆力", "上妆", "哑光", "珠光"],
            "穿搭": ["版型", "剪裁", "廓形", "叠穿", "层次感", "色调", "质感"],
            "美食": ["口感", "层次", "搭配", "技法", "火候", "调味", "食材"],
            "旅行": ["行程", "攻略", "体验", "风土人情", "当地特色", "隐藏景点"],
            "母婴": ["早教", "成长", "发育", "营养", "互动", "认知"],
            "数码": ["性能", "体验", "配置", "系统", "兼容性", "功耗", "散热"],
            "家居": ["空间规划", "采光", "色彩搭配", "功能区", "动线"],
            "健身": ["训练计划", "组数", "强度", "恢复", "代谢", "肌肉增长"]
        }
        
        # 为检测到的每个领域随机添加一个术语
        for domain in detected_domains:
            if domain in domain_terms:
                terms = domain_terms[domain]
                selected_term = random.choice(terms)
                if random.random() > 0.5:  # 50%的概率添加术语
                    selected_template += f"，特别是在{selected_term}方面的见解很独到"
    
    # 在部分评论中添加吸引私信的结尾
    if comment_type == "引流" or (comment_type == "咨询" and random.random() > 0.7):
        endings = [
            "有更多问题欢迎私信我~",
            "感兴趣的话可以来我主页看看哦",
            "想了解更多可以找我聊聊",
            "关注我了解更多相关内容",
            "私信我有惊喜哦~"
        ]
        selected_template += " " + random.choice(endings)
    
    return selected_template

if __name__ == "__main__":
    # 初始化并运行服务器
    print("启动小红书MCP服务器...")
    print("请在MCP客户端（如Claude for Desktop）中配置此服务器")
    mcp.run(transport='stdio')