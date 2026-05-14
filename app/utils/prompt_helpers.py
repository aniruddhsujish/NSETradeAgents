def format_market_context(market_context: dict | None) -> str:
    """Format market context dict into a prompt block for LLM agents."""
    if not market_context:
        return ""
    return f"""
Market context:
- Nifty 50 today: {market_context.get('nifty_day_pct', 'N/A')}% (5d: {market_context.get('nifty_5d_pct', 'N/A')}%)
- Market tone: {market_context.get('market_label', 'N/A')}
- Nifty trend: {market_context.get('trend_label', 'N/A')}
- Sector ({market_context.get('sector', 'N/A')}) today: {market_context.get('sector_day_pct', 'N/A')}%
- Distance from 52w high: {market_context.get('pct_from_52w_high', 'N/A')}%
- Distance from 52w low:  {market_context.get('pct_from_52w_low', 'N/A')}%
- {market_context.get('divergence_note', '')}
"""
