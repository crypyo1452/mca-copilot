import os, asyncio, json
from typing import Optional
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MCA_URL = os.getenv("MCA_URL", "https://YOUR-ANALYZER.onrender.com")
RENDER_HOOK_URL = os.getenv("RENDER_HOOK_URL", "")
BSCSCAN_KEY_FOR_BOT = os.getenv("BSCSCAN_API_KEY", "")

HELP = (
    "🤖 meme coin analyser\n"
    "Send a BSC CA (0x...) to analyze.\n\n"
    "Commands:\n"
    "/start – help\n"
    "/status – check analyzer + key\n"
    "/redeploy – trigger Render redeploy\n"
)

async def fetch_json(method: str, url: str, **kwargs) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method, url, **kwargs)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None

def normalize_addr(text: str) -> Optional[str]:
    t = (text or "").strip()
    if t.startswith("0x") and len(t) == 42:
        return t
    return None

def format_result(data: dict) -> str:
    liq = data.get("liquidity", {}) or {}
    sup = data.get("supply", {}) or {}
    fxs = data.get("factors", []) or []
    own = next((f for f in fxs if f.get("id") == "ownership"), None)
    mkt = next((f for f in fxs if f.get("id") == "market_integrity"), None)
    own_ev = (own or {}).get("evidence") or []
    mkt_ev = (mkt or {}).get("evidence") or []
    lines = [
        f"**MCA Result**  Score: {data.get('score')}  Band: {data.get('band')}",
        f"DEX: {liq.get('dex') or 'n/a'}",
        f"Pair/Pool: {liq.get('pair')}",
        f"LP Lock: {liq.get('lp_locked_pct') or 0}% via {liq.get('locker') or 'n/a'}",
        f"Supply: {sup.get('total') or 'n/a'}  Dead%: {sup.get('dead_wallet_pct') or 'n/a'}  Top10%: {sup.get('top10_pct') or 'n/a'}",
        f"Ownership: {(own_ev or ['unknown'])[0]}",
    ]
    if mkt_ev:
        lines.append("Market: " + "; ".join(mkt_ev))
    return "\n".join(lines)

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    health = await fetch_json("GET", f"{MCA_URL}/health")
    ok = (health or {}).get("ok") is True
    dbg = await fetch_json("GET", f"{MCA_URL}/debug/bscscan?address=0x0000000000000000000000000000000000000000")
    abi_state = (dbg or {}).get("abi_status", "unknown")
    key_present = (dbg or {}).get("key_present", False)
    msg = [
        f"Analyzer reachable: {ok}",
        f"Analyzer ABI status: {abi_state}",
        f"Analyzer BSCSCAN_API_KEY present: {key_present}",
        f"Bot has BSCSCAN_API_KEY: {bool(BSCSCAN_KEY_FOR_BOT)}",
        f"MCA_URL: {MCA_URL}",
    ]
    await update.message.reply_text("\n".join(msg))

async def redeploy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not RENDER_HOOK_URL:
        return await update.message.reply_text("❌ RENDER_HOOK_URL not set.")
    await update.message.reply_text("🔁 Triggering Render redeploy...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(RENDER_HOOK_URL, json={})
            ok = r.status_code in (200, 201, 202)
    except Exception:
        ok = False
    await update.message.reply_text("✅ Deploy hook called." if ok else "❌ Failed to call deploy hook.")

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    addr = normalize_addr(update.message.text)
    if not addr:
        return await update.message.reply_text("Please send a valid BSC contract address (0x...)")
    payload = {"chain": "bsc", "address": addr}
    data = await fetch_json("POST", f"{MCA_URL}/analyze", json=payload)
    if not data:
        return await update.message.reply_text("❌ Couldn’t reach analyzer. Use /status to check.")
    await update.message.reply_text(format_result(data), disable_web_page_preview=True)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("redeploy", redeploy_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
