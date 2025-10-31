import os
import re
import logging
import asyncio
import httpx

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mca-copilot")

MCA_URL = os.getenv("MCA_URL", "").rstrip("/")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

HELP_TEXT = (
    "👋 *Meme Coin Analyser*\n\n"
    "• Send me a BSC token contract address (starts with `0x`)\n"
    "• I’ll reply with a summary score.\n\n"
    "Commands:\n"
    "• /status — Check connection to the analyser\n"
    "• /help — Show this help"
)

def nice_pct(v):
    return "—" if v is None else f"{v:.2f}%"

async def ping_analyzer() -> bool:
    if not MCA_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{MCA_URL}/health")
            return r.status_code == 200 and r.json().get("ok") is True
    except Exception as e:
        log.warning("Health check failed: %s", e)
        return False

async def analyze_address(addr: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{MCA_URL}/analyze", json={"chain": "bsc", "address": addr})
            if r.status_code == 200:
                return r.json()
            log.warning("Analyzer error %s: %s", r.status_code, r.text)
    except Exception as e:
        log.exception("Analyze call failed: %s", e)
    return None

# Handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = await ping_analyzer()
    if ok:
        await update.message.reply_text("✅ Analyzer online")
    else:
        await update.message.reply_text("❌ Analyzer not reachable. Check MCA_URL on Railway.")

async def address_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not ETH_ADDR_RE.fullmatch(text):
        await update.message.reply_text("Please send a *BSC token address* (format: `0x...40 hex chars`).", parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text("⏳ Analyzing…")
    data = await analyze_address(text)
    if not data:
        await update.message.reply_text("❌ Sorry, couldn’t analyze. Check logs or try again.")
        return

    token = data.get("token", {})
    liq = data.get("liquidity", {}) or {}
    supply = data.get("supply", {}) or {}
    factors = data.get("factors", []) or []

    lines = [
        f"*{token.get('name','?')}* ({token.get('symbol','?')})",
        f"`{token.get('address','?')}`",
        "",
        f"*Score:* {data.get('score','?')}  •  *Band:* {data.get('band','?')}",
        "",
        "*Key factors:*"
    ]
    for f in factors[:5]:
        impact = f.get("impact", 0)
        emoji = "🟢" if impact > 0 else ("🔴" if impact < 0 else "⚪")
        ev = "; ".join(f.get("evidence", [])[:1]) or ""
        lines.append(f"{emoji} {f.get('id','?')} — {ev}")

    if liq:
        lines += [
            "",
            "*Liquidity:*",
            f"DEX: {liq.get('dex','?')}",
            f"Pair: `{liq.get('pair','—')}`",
            f"LP locked: {liq.get('lp_locked_pct', 0)}% via {liq.get('locker','—')}",
        ]
    if supply:
        lines += [
            "",
            "*Supply:*",
            f"Total: {supply.get('total','—')}",
            f"Dead wallet: {nice_pct(supply.get('dead_wallet_pct'))}",
            f"Top10: {nice_pct(supply.get('top10_pct'))}",
        ]

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, address_msg))

    log.info("Bot starting…")
    await app.initialize()
    await app.start()
    log.info("Bot started ✅")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    # Keep running forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
