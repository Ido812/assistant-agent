import asyncio
import logging
import yfinance as yf
from mcp.server.fastmcp import FastMCP

# Suppress verbose MCP request logs
logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("stock-tools")


@mcp.tool()
async def get_stock_price(tickers: list[str]) -> str:
    """Get current price and daily market data for one or more stock tickers.
    All tickers are fetched in parallel."""

    def _fetch(ticker: str) -> str:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice", "N/A")
        prev = info.get("previousClose", 0)
        change = f"{price - prev:+.2f}" if isinstance(price, (int, float)) else "N/A"
        return (
            f"{info.get('shortName', ticker)} ({ticker})\n"
            f"Price: {price} ({change})\n"
            f"Day Range: {info.get('dayLow', 'N/A')} - {info.get('dayHigh', 'N/A')}\n"
            f"Volume: {info.get('volume', 'N/A')}"
        )

    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch, t.strip()) for t in tickers)
    )
    return "\n\n---\n\n".join(results)


@mcp.tool()
def get_stock_history(ticker: str, period: str = "1mo") -> str:
    """Get historical price data. period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y."""
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)
    if hist.empty:
        return f"No history found for {ticker}"
    lines = []
    for date, row in hist.iterrows():
        lines.append(
            f"{date.strftime('%Y-%m-%d')}: "
            f"Open={row['Open']:.2f} Close={row['Close']:.2f} Vol={int(row['Volume'])}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_company_info(tickers: list[str]) -> str:
    """Get company fundamentals (sector, market cap, P/E, description) for one or more tickers.
    All tickers are fetched in parallel."""

    def _fetch(ticker: str) -> str:
        stock = yf.Ticker(ticker)
        info = stock.info
        summary = info.get("longBusinessSummary", "N/A")
        if len(summary) > 300:
            summary = summary[:300] + "..."
        return (
            f"Name: {info.get('shortName', 'N/A')}\n"
            f"Sector: {info.get('sector', 'N/A')}\n"
            f"Industry: {info.get('industry', 'N/A')}\n"
            f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            f"P/E Ratio: {info.get('trailingPE', 'N/A')}\n"
            f"52w Range: {info.get('fiftyTwoWeekLow', 'N/A')} - {info.get('fiftyTwoWeekHigh', 'N/A')}\n"
            f"About: {summary}"
        )

    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch, t.strip()) for t in tickers)
    )
    return "\n\n---\n\n".join(results)


if __name__ == "__main__":
    mcp.run()
