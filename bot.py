import os
import re
import json
import time
import threading
import requests
from datetime import datetime as dt
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from google_play_scraper import app

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

REGIONS = {'in': '🇮🇳 IN', 'us': '🇺🇸 US', 'gb': '🇬🇧 UK', 'br': '🇧🇷 BR'}
ALL_REGIONS = [
    "af","al","dz","ad","ao","ag","ar","am","au","at","az","bs","bh","bd","bb","by","be","bz","bj","bt","bo",
    "ba","bw","br","bn","bg","bf","bi","kh","cm","ca","cv","cf","td","cl","cn","co","km","cg","cd","cr","ci",
    "hr","cu","cy","cz","dk","dj","dm","do","ec","eg","sv","gq","er","ee","sz","et","fj","fi","fr","ga","gm",
    "ge","de","gh","gr","gd","gt","gn","gw","gy","ht","hn","hu","is","in","id","ir","iq","ie","il","it","jm",
    "jp","jo","kz","ke","ki","kp","kr","kw","kg","la","lv","lb","ls","lr","ly","li","lt","lu","mg","mw","my",
    "mv","ml","mt","mh","mr","mu","mx","fm","md","mc","mn","me","ma","mz","mm","na","nr","np","nl","nz","ni",
    "ne","ng","mk","no","om","pk","pw","pa","pg","py","pe","ph","pl","pt","qa","ro","ru","rw","kn","lc","vc",
    "ws","sm","st","sa","sn","rs","sc","sl","sg","sk","si","sb","so","za","ss","es","lk","sd","sr","se","ch",
    "sy","tj","tz","th","tl","tg","to","tt","tn","tr","tm","tv","ug","ua","ae","gb","us","uy","uz","vu","ve",
    "vn","ye","zm","zw"
]

bot = telebot.TeleBot(BOT_TOKEN)

# --- UPSTASH CLOUD DATABASE CONNECTIVITY ---
def load_database():
    if not UPSTASH_URL or not UPSTASH_TOKEN: return {}
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        r = requests.get(f"{UPSTASH_URL}/get/play_tracker_data", headers=headers)
        res = r.json()
        if "result" in res and res["result"]:
            data = json.loads(res["result"])
            for pkg, info in data.items():
                if 'versions' not in info: info['versions'] = {}
                if 'dates' not in info: info['dates'] = {}
                if 'history' not in info: info['history'] = {}
            return data
    except Exception as e: print(f"Upstash Load Error: {e}")
    return {}

def save_database(data):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return False
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        payload = json.dumps(data)
        r = requests.post(f"{UPSTASH_URL}/set/play_tracker_data", data=payload, headers=headers)
        return r.json().get("result") == "OK"
    except Exception as e: print(f"Upstash Save Error: {e}")
    return False

def format_date(timestamp):
    if not timestamp or timestamp == 0: return "Unknown Date"
    return dt.fromtimestamp(timestamp).strftime('%d %b %Y')

def find_first_rollout(dates_dict):
    valid_dates = {k: v for k, v in dates_dict.items() if isinstance(v, (int, float)) and v > 0}
    if not valid_dates: return "Unknown"
    oldest_region = min(valid_dates, key=valid_dates.get)
    return f"{REGIONS.get(oldest_region, oldest_region.upper())} on {format_date(valid_dates[oldest_region])}"

# --- TELEGRAM KEYBOARD MENU ---
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("➕ Add New App"), KeyboardButton("📋 View Tracked Apps"))
    markup.add(KeyboardButton("🗑️ Delete App"), KeyboardButton("🇮🇳 Standard Check"))
    markup.add(KeyboardButton("📤 Broadcast Scan (4 Regions)"), KeyboardButton("🌍 Global Deep Scan (195+)"))
    return markup

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    bot.send_message(message.chat.id, "📱 *PLAY STORE PRO TRACKER - LIVE CLOUD BOT*\n\nNiche diye gaye buttons ka use karein 👇", parse_mode="Markdown", reply_markup=main_menu())

# --- BOT LOGIC / HANDLERS ---
@bot.message_handler(func=lambda msg: True)
def handle_menu_options(message):
    chat_id = message.chat.id
    text = message.text.strip()
    data = load_database()

    if text == "➕ Add New App":
        msg = bot.send_message(chat_id, "✍️ App ka **Package Name** ya **Play Store Link** bhejein:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_app)

    elif text == "📋 View Tracked Apps":
        if not data: return bot.send_message(chat_id, "📭 Aapki list khali hai!")
        for pkg, info in data.items():
            msg_txt = f"📦 *{info.get('name')}*\n🆔 `{pkg}`\n🇮🇳 Version: `{info.get('versions', {}).get('in', 'N/A')}` (📅 {format_date(info.get('dates', {}).get('in', 0))})"
            hist = info.get('history', {})
            if hist:
                msg_txt += "\n\n⏳ *History (Purana Data):*"
                for reg, h_info in hist.items():
                    msg_txt += f"\n   -> {REGIONS.get(reg, reg.upper())}: `{h_info.get('old_version')}` (📅 {format_date(h_info.get('old_date'))})"
            bot.send_message(chat_id, msg_txt, parse_mode="Markdown")

    elif text == "🗑️ Delete App":
        if not data: return bot.send_message(chat_id, "📭 List pehle se khali hai!")
        msg_txt = "🗑️ *DELETE APP*\n\nKaun si app delete karni hai? Number type karke bhejein:\n"
        keys = list(data.keys())
        for i, pkg in enumerate(keys): msg_txt += f"\n{i+1}. {data[pkg].get('name')}"
        msg = bot.send_message(chat_id, msg_txt, parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_delete_app(m, keys))

    elif text == "🇮🇳 Standard Check":
        if not data: return bot.send_message(chat_id, "📭 List khali hai! Pehle app add karein.")
        status = bot.send_message(chat_id, "⏳ India Region check ho raha hai...")
        found_any = False
        for pkg, info in data.items():
            try:
                res = app(pkg, lang='en', country='in')
                live_v = res.get('version') or 'Varies with device'
                live_d = res.get('updated') or 0
                old_v = info.get('versions', {}).get('in', 'Unknown')
                old_d = info.get('dates', {}).get('in', 0)
                
                if (live_v != old_v and live_v != 'Varies with device' and old_v != 'Unknown') or (live_d > old_d and old_d != 0):
                    found_any = True
                    alert = (f"🔴 *🚨 [NAYA UPDATE DETECTED!] 🚨*\n\n📦 *{info.get('name')}*\n🔄 Version: `{old_v}` ➡️ `{live_v}`\n📅 Date: `{format_date(old_d)}` ➡️ `{format_date(live_d)}`")
                    bot.send_message(chat_id, alert, parse_mode="Markdown")
                    if 'history' not in data[pkg]: data[pkg]['history'] = {}
                    data[pkg]['history']['in'] = {'old_version': old_v, 'old_date': old_d}
                    data[pkg]['versions']['in'], data[pkg]['dates']['in'] = live_v, live_d
            except: pass
        if not found_any: bot.send_message(chat_id, "🟢 India me koi naya update nahi mila.")
        save_database(data)
        bot.delete_message(chat_id, status.message_id)

    elif text == "📤 Broadcast Scan (4 Regions)":
        if not data: return bot.send_message(chat_id, "📭 List khali hai!")
        msg_txt = "📤 *BROADCAST SCAN OPTION*\n\n👉 *ALL* likhkar bhejein sabhi apps ke liye\n👉 Ya fir specific apps ke numbers likhein (Jaise: *1, 2, 3*):\n"
        keys = list(data.keys())
        for i, pkg in enumerate(keys): msg_txt += f"\n{i+1}. {data[pkg].get('name')}"
        msg = bot.send_message(chat_id, msg_txt, parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_multi_scan(m, keys, mode="broadcast"))

    elif text == "🌍 Global Deep Scan (195+)":
        if not data: return bot.send_message(chat_id, "📭 List khali hai!")
        msg_txt = "🌍 *195+ REGIONS DEEP SCAN*\n\n👉 Jin apps ka deep scan karna hai, unke numbers likhein (Jaise: *1, 3*):\n"
        keys = list(data.keys())
        for i, pkg in enumerate(keys): msg_txt += f"\n{i+1}. {data[pkg].get('name')}"
        msg = bot.send_message(chat_id, msg_txt, parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_multi_scan(m, keys, mode="deep"))

def process_add_app(message):
    link = message.text.strip()
    match = re.search(r'id=([a-zA-Z0-9._]+)', link)
    pkg = match.group(1) if match else link if re.match(r'^[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)+$', link) else None
    
    if not pkg: return bot.send_message(message.chat.id, "❌ Galat Package ID!")
    data = load_database()
    if pkg in data: return bot.send_message(message.chat.id, "⚠️ Ye app pehle se tracked hai!")
        
    status = bot.send_message(message.chat.id, "🔍 Play Store se data nikal raha hoon...")
    try:
        res = app(pkg, lang='en', country='in')
        app_name = res.get('title', 'Unknown')
        data[pkg] = {'name': app_name, 'versions': {}, 'dates': {}, 'history': {}}
        for c_code in REGIONS.keys():
            try:
                c_res = app(pkg, lang='en', country=c_code)
                data[pkg]['versions'][c_code] = c_res.get('version') or 'Varies with device'
                data[pkg]['dates'][c_code] = c_res.get('updated') or 0
            except:
                data[pkg]['versions'][c_code] = 'Unknown'
                data[pkg]['dates'][c_code] = 0
        save_database(data)
        bot.edit_message_text(f"🎉 *Successfully Added:*\n📦 {app_name}\n🆔 `{pkg}`", message.chat.id, status.message_id, parse_mode="Markdown")
    except: bot.edit_message_text("❌ App nahi mila! Kripya sahi link/ID bhejein.", message.chat.id, status.message_id)

def process_delete_app(message, keys):
    try:
        idx = int(message.text.strip()) - 1
        if 0 <= idx < len(keys):
            data = load_database()
            name = data[keys[idx]].get('name')
            del data[keys[idx]]
            save_database(data)
            bot.send_message(message.chat.id, f"✅ *{name}* ko database se hata diya gaya.", parse_mode="Markdown")
        else: bot.send_message(message.chat.id, "❌ Galat number!")
    except: bot.send_message(message.chat.id, "❌ Invalid Input!")

def process_multi_scan(message, keys, mode="broadcast"):
    input_text = message.text.strip()
    data = load_database()
    target_apps = []
    
    if mode == "broadcast" and input_text.upper() == "ALL": target_apps = keys
    else:
        nums = [int(x) for x in re.findall(r'\d+', input_text)]
        for num in nums:
            if 1 <= num <= len(keys): target_apps.append(keys[num - 1])
            
    if not target_apps: return bot.send_message(message.chat.id, "❌ Koi valid app select nahi hui!")
    status = bot.send_message(message.chat.id, f"🚀 Scanning {len(target_apps)} App(s)... Kripya thoda wait karein.")

    for pkg in target_apps:
        info = data[pkg]
        if mode == "broadcast":
            msg_txt = f"📦 *APP:* {info.get('name')} | 🆔 `{pkg}`\n"
            live_dates = {}
            for c_code, region_name in REGIONS.items():
                try:
                    res = app(pkg, lang='en', country=c_code)
                    live_v = res.get('version') or 'Varies with device'
                    live_d = res.get('updated') or 0
                    old_v = info.get('versions', {}).get(c_code, 'Unknown')
                    old_d = info.get('dates', {}).get(c_code, 0)
                    live_dates[c_code] = live_d
                    
                    if (live_v != old_v and live_v != 'Varies with device' and old_v != 'Unknown') or (live_d > old_d and old_d != 0):
                        msg_txt += f"\n🔴 -> *🚨 {region_name}:* `{old_v}` ➡️ `{live_v}` (📅 {format_date(old_d)} ➡️ {format_date(live_d)}) *[NEW]*"
                        if 'history' not in data[pkg]: data[pkg]['history'] = {}
                        data[pkg]['history'][c_code] = {'old_version': old_v, 'old_date': old_d}
                    else:
                        msg_txt += f"\n🟢 -> *{region_name}:* `{live_v}` (📅 {format_date(live_d)})"
                    
                    data[pkg]['versions'][c_code], data[pkg]['dates'][c_code] = live_v, live_d
                except:
                    msg_txt += f"\n❌ -> *{region_name}:* Not Available"
            
            msg_txt += f"\n\n⚡ *FIRST ROLLOUT:* {find_first_rollout(live_dates)}"
            bot.send_message(message.chat.id, msg_txt, parse_mode="Markdown")
            
        elif mode == "deep":
            bot.send_message(message.chat.id, f"⏳ Global Deep Scan Running for: *{info.get('name')}* (195+ regions)...", parse_mode="Markdown")
            results = {}
            for code in ALL_REGIONS:
                try:
                    res = app(pkg, lang='en', country=code)
                    v = res.get('version') or 'Varies with device'
                    d = res.get('updated') or 0
                    if (v, d) not in results: results[(v, d)] = []
                    results[(v, d)].append(code.upper())
                except: pass
            
            report = f"🌍 *DEEP SCAN REPORT FOR {info.get('name')}*\n" + "-"*40
            sorted_res = sorted(results.keys(), key=lambda x: x[1], reverse=True)
            for i, (v, d) in enumerate(sorted_res):
                countries = results[(v, d)]
                c_str = ", ".join(countries[:12]) + ("..." if len(countries) > 12 else "")
                if i == 0 and len(sorted_res) > 1:
                    report += f"\n\n🔴 *🚨 LATEST HIDDEN UPDATE DETECTED!*\n🔄 Version : `{v}`\n📅 Date    : `{format_date(d)}`\n🌍 Regions : {c_str}"
                else: report += f"\n\n🟢 Version : `{v}`\n📅 Date    : `{format_date(d)}`\n🌍 Regions : {c_str}"
            bot.send_message(message.chat.id, report, parse_mode="Markdown")
            
    save_database(data)
    bot.delete_message(message.chat.id, status.message_id)
    bot.send_message(message.chat.id, "✅ *Scanning Complete!* Data saved to Upstash Cloud.", parse_mode="Markdown")


# --- FAKE WEB SERVER (RENDER FREE TIER BYPASS) ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is Alive and Running on Render Cloud!"

def run_bot():
    print("🚀 Cloud Telegram Bot Starting...")
    bot.infinity_polling()

if __name__ == "__main__":
    # 1. Telegram bot ko background me start karein
    threading.Thread(target=run_bot).start()
    
    # 2. Render ki requirement poori karne ke liye Web Server start karein
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)