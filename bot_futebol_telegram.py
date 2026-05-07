import os, logging, requests
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN","")
CHAT_ID = os.environ.get("CHAT_ID","")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY","")
ODD_MINIMA = 1.50

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
HEADERS = {"x-apisports-key": FOOTBALL_API_KEY}

def buscar_jogos(h_ini, h_fim):
    hoje = datetime.now().strftime("%Y-%m-%d")
    try:
        r = requests.get(f"https://v3.football.api-sports.io/fixtures",headers=HEADERS,params={"date":hoje,"status":"NS"},timeout=10)
        jogos = r.json().get("response",[])
    except: return []
    out = []
    for j in jogos:
        ts = j.get("fixture",{}).get("timestamp",0)
        dt = datetime.fromtimestamp(ts)
        if datetime.now().replace(hour=h_ini,minute=0,second=0) <= dt <= datetime.now().replace(hour=h_fim,minute=0,second=0):
            out.append(j)
    return out

def analisar(jogo):
    home = jogo["teams"]["home"]
    away = jogo["teams"]["away"]
    league = jogo["league"]
    fixture = jogo["fixture"]
    try:
        sh = requests.get("https://v3.football.api-sports.io/teams/statistics",headers=HEADERS,params={"team":home["id"],"league":league["id"],"season":2024},timeout=10).json().get("response",{})
        sa = requests.get("https://v3.football.api-sports.io/teams/statistics",headers=HEADERS,params={"team":away["id"],"league":league["id"],"season":2024},timeout=10).json().get("response",{})
    except: return None
    scores = {}
    try:
        gh = float(sh.get("goals",{}).get("for",{}).get("average",{}).get("total",0) or 0)
        ga = float(sa.get("goals",{}).get("for",{}).get("average",{}).get("total",0) or 0)
        mg = gh + ga
        if mg >= 2.3: scores["⚽ Over 2.5 Gols"]={"odd":1.70,"conf":min(90,int(mg*22))}
    except: pass
    try:
        wh = sh.get("fixtures",{}).get("wins",{}).get("home",0) or 0
        ph = sh.get("fixtures",{}).get("played",{}).get("home",1) or 1
        tw = float(wh)/float(ph)
        if tw >= 0.55: scores["🏠 Vitória Casa (1)"]={"odd":round(max(1.5,2.2-tw*1.2),2),"conf":min(88,int(tw*120))}
        dh = sh.get("fixtures",{}).get("draws",{}).get("home",0) or 0
        t1x = (float(wh)+float(dh))/float(ph)
        if t1x >= 0.65: scores["🏠✖️ Casa ou Empate (1X)"]={"odd":round(max(1.5,1.9-t1x*0.6),2),"conf":min(85,int(t1x*100))}
    except: pass
    try:
        wa = sa.get("fixtures",{}).get("wins",{}).get("away",0) or 0
        pa = sa.get("fixtures",{}).get("played",{}).get("away",1) or 1
        ta = float(wa)/float(pa)
        if ta >= 0.45: scores["✈️ Vitória Fora (2)"]={"odd":round(max(1.5,2.8-ta*1.5),2),"conf":min(82,int(ta*130))}
        da = sa.get("fixtures",{}).get("draws",{}).get("away",0) or 0
        t2x = (float(wa)+float(da))/float(pa)
        if t2x >= 0.60: scores["✈️✖️ Fora ou Empate (2X)"]={"odd":round(max(1.5,2.1-t2x*0.7),2),"conf":min(80,int(t2x*100))}
    except: pass
    if not scores: return None
    melhor = max(scores.items(),key=lambda x:x[1]["conf"])
    m,d = melhor
    hora = fixture.get("date","")[11:16]
    return {"jogo":f"{home['name']} vs {away['name']}","liga":league.get("name",""),"pais":league.get("country",""),"hora":hora,"mercado":m,"odd":d["odd"],"conf":d["conf"]}

def montar_msg(sels, turno):
    emojis={"manhã":"🌅","tarde":"☀️","noite":"🌙"}
    e=emojis.get(turno,"⚽")
    odd_total=1.0
    for s in sels: odd_total*=s["odd"]
    odd_total=round(odd_total,2)
    linhas=[f"{e} *SCOUT BOT — MÚLTIPLA {turno.upper()}*",f"📅 {datetime.now().strftime('%d/%m/%Y')}\n","─"*28]
    for i,s in enumerate(sels,1):
        linhas+=[f"\n*Seleção {i}*",f"🏆 {s['liga']} — {s['pais']}",f"⚽ {s['jogo']}",f"🕐 {s['hora']}",f"📊 {s['mercado']}",f"💰 Odd: `{s['odd']}` | 🎯 {s['conf']}%"]
    linhas+=["\n"+"─"*28,f"\n💎 *ODD TOTAL: `{odd_total}`*",f"💵 R$10 → R${round(10*odd_total,2)}","\n⚠️ _Aposte com responsabilidade._"]
    return "\n".join(linhas)

async def enviar(bot, turno, h_ini, h_fim):
    await bot.send_message(chat_id=CHAT_ID,text=f"🔍 Analisando jogos para múltipla da {turno}...")
    jogos = buscar_jogos(h_ini,h_fim)
    candidatos = []
    for j in jogos[:25]:
        r = analisar(j)
        if r and r["odd"] >= ODD_MINIMA: candidatos.append(r)
    candidatos.sort(key=lambda x:x["conf"],reverse=True)
    top = candidatos[:3]
    if len(top)<3:
        await bot.send_message(chat_id=CHAT_ID,text=f"⚠️ Poucos jogos disponíveis para o turno da {turno}.")
        return
    await bot.send_message(chat_id=CHAT_ID,text=montar_msg(top,turno),parse_mode="Markdown")

async def cmd_start(update,context):
    await update.message.reply_text("⚽ *SCOUT BOT ativo!*\nMúltiplas às 06:00 | 12:00 | 18:00\n\nComandos:\n/multipla\\_agora\n/status",parse_mode="Markdown")

async def cmd_agora(update,context):
    h=datetime.now().hour
    if h<12: t,hi,hf="manhã",6,12
    elif h<18: t,hi,hf="tarde",12,18
    else: t,hi,hf="noite",18,23
    await enviar(context.bot,t,hi,hf)

async def cmd_status(update,context):
    await update.message.reply_text(f"✅ Online | {datetime.now().strftime('%H:%M')} | Odd mín: {ODD_MINIMA}",parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("multipla_agora",cmd_agora))
    app.add_handler(CommandHandler("status",cmd_status))
    sched = AsyncIOScheduler(timezone="America/Recife")
    async def j_m(): await enviar(app.bot,"manhã",6,12)
    async def j_t(): await enviar(app.bot,"tarde",12,18)
    async def j_n(): await enviar(app.bot,"noite",18,23)
    sched.add_job(j_m,"cron",hour=6,minute=0)
    sched.add_job(j_t,"cron",hour=12,minute=0)
    sched.add_job(j_n,"cron",hour=18,minute=0)
    sched.start()
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
