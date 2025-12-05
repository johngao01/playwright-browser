def get_network_stats(page):
    """
    仿 Chrome DevTools 底部统计条，获取：
    请求数、传输大小(流量)、资源大小(解压后)、DOMContentLoaded时间、Load时间
    """
    stats = page.evaluate("""() => {
        // 1. 获取所有资源性能数据
        const resources = performance.getEntriesByType("resource");

        // 2. 获取导航性能数据 (用于计算 DCL 和 Load 时间)
        // 使用 navigation API (v2) 或 timing API (v1 兼容)
        const nav = performance.getEntriesByType("navigation")[0] || performance.timing;

        // 计算 DCL (DOMContentLoaded) 和 Load 时间
        // 注意：navigation API 返回的是相对时间，timing API 返回的是绝对时间戳
        let dclTime = 0;
        let loadTime = 0;

        if (performance.getEntriesByType("navigation")[0]) {
            dclTime = nav.domContentLoadedEventEnd;
            loadTime = nav.loadEventEnd;
        } else {
            // 兼容旧版写法
            dclTime = nav.domContentLoadedEventEnd - nav.navigationStart;
            loadTime = nav.loadEventEnd - nav.navigationStart;
        }

        // 3. 累加资源大小
        let totalTransferSize = 0; // 传输大小 (压缩后/网络消耗)
        let totalDecodedSize = 0;  // 资源大小 (解压后/实际内容)

        resources.forEach(res => {
            // transferSize 为 0 通常意味着是从缓存读取
            totalTransferSize += res.transferSize; 
            totalDecodedSize += res.decodedBodySize;
        });

        return {
            requests: resources.length,
            transferSize: totalTransferSize,
            decodedSize: totalDecodedSize,
            domContentLoaded: dclTime,
            load: loadTime
        };
    }""")

    # 格式化输出函数
    def format_bytes(size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} MB"

    def format_time(ms):
        if ms > 1000:
            return f"{ms / 1000:.2f} 秒"
        return f"{ms:.0f} 毫秒"

    print("\n" + "=" * 15 + " 📊 页面加载统计 (DevTools) " + "=" * 15)
    print(f"请求总数: {stats['requests']} 次")
    print(f"已传输 (流量): {format_bytes(stats['transferSize'])}")
    print(f"资源大小 (解压后): {format_bytes(stats['decodedSize'])}")
    print(f"DOM Ready: {format_time(stats['domContentLoaded'])}")
    print(f"Load 完成: {format_time(stats['load'])}")
    print("=" * 50 + "\n")
