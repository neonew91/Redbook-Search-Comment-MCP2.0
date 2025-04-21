from fastmcp import FastMCP

# 创建一个简单的MCP服务器
mcp = FastMCP("test_server")

@mcp.tool()
async def hello() -> str:
    """返回一个简单的问候"""
    return "你好，这是一个测试MCP服务器！"

if __name__ == "__main__":
    print("启动测试MCP服务器...")
    mcp.run(transport='stdio')
