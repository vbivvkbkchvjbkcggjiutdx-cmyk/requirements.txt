import os
import sys
import time
import asyncio
import logging
import requests
import threading
import random
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneNumberInvalidError

# --- লগিং কনফিগারেশন ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- গ্লোবাল প্রক্সি ও ডাটা ট্র্যাকিং ভ্যারিয়েবল ---
PROXY_SETTINGS = None  
TOTAL_PROXY_BYTES_SENT = 0
TOTAL_PROXY_BYTES_RECV = 0

# --- প্যানেল কনফিগারেশনসমূহ ---
DURIAN_HOSTS = [
    "https://mm.durianrcs.com",
    "https://api.durianrcs.com",
]
DURIAN_USERNAME = "Alex584"
DURIAN_API_KEY = "SjQrcGFDd2ZYQ1NNbFJzcWphM3ZaZz09"

TELEGRAM_BOT_TOKEN = "8901309570:AAGdKiwWJRXssTRrCceuNTY5YAbKAoRMxIg"
ALLOWED_USER_ID = 2109625230
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# মেমোরি ট্র্যাকিং ও গ্লোবাল স্টেট
CURRENT_COUNTRY = "bo"
SELECTED_COUNTRIES = ["bo", "co"]
WAITING_FOR_COUNTRY = False
WAITING_FOR_ADD_COUNTRIES = False
WAITING_FOR_REMOVE_COUNTRIES = False
WAITING_FOR_SET_PREFIX = False
WAITING_FOR_REMOVE_PREFIX = False
WAITING_FOR_SEE_PREFIX = False
BULK_ACTIVE = False
SINGLE_LOOP_ACTIVE = True  
ADMIN_CHAT_ID = None
TELEGRAM_CHECKER_ON = True  

ACTIVE_POLLING_NUMBERS = set()
PID_6003_COUNTRIES = {"eg", "us", "do", "gt", "ru", "tr", "ve", "it"}

# --- চেকার সেশন ভ্যারিয়েবল ও ফাইল ---
user_states = {}  
active_sessions = []  
current_account_index = 0
SESSION_DATA_FILE = "saved_sessions.txt"

COUNTRY_PREFIX_MAP = {
    "98": "ir", "591": "bo", "57": "co", "1": "us", "7": "ru", "20": "eg", "90": "tr", 
    "58": "ve", "39": "it", "502": "gt", "1809": "do", "1829": "do", "1849": "do",
    "86": "cn", "91": "in", "62": "id", "66": "th", "60": "my", "84": "vn", 
    "63": "ph", "880": "bd", "92": "pk", "55": "br", "52": "mx", "34": "es",
    "44": "gb", "966": "sa", "971": "ae", "234": "ng", "254": "ke", "27": "za"
}

# ==========================================================
# --- প্রিফিক্স ম্যানেজার ক্লাস ---
# ==========================================================
class PrefixManager:
    def __init__(self, file_path="prefixes.json"):
        self.file_path = file_path
        self.data = self._load_data()

    def _load_data(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_data(self):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def set_prefix(self, country_code, prefixes_input):
        country_code = country_code.upper().strip()
        clean_input = prefixes_input.replace('.', ',').replace(' ', ',')
        new_prefixes = [p.strip() for p in clean_input.split(',') if p.strip()]

        if country_code not in self.data:
            self.data[country_code] = []

        for p in new_prefixes:
            if p not in self.data[country_code]:
                self.data[country_code].append(p)

        self._save_data()
        return f"✅ {country_code} এর জন্য প্রিফিক্স সফলভাবে সেট করা হয়েছে।\nবর্তমান প্রিফিক্স: {', '.join(self.data[country_code])}"

    def remove_prefix(self, country_code, prefixes_input):
        country_code = country_code.upper().strip()
        clean_input = prefixes_input.replace('.', ',').replace(' ', ',')
        remove_prefixes = [p.strip() for p in clean_input.split(',') if p.strip()]

        if country_code not in self.data:
            return f"❌ {country_code} কান্ট্রি কোডটি লিস্টে নেই।"

        removed_list = []
        for p in remove_prefixes:
            if p in self.data[country_code]:
                self.data[country_code].remove(p)
                removed_list.append(p)

        if not self.data[country_code]:
            del self.data[country_code]
            
        self._save_data()
        
        if removed_list:
            return f"✅ {country_code} থেকে {', '.join(removed_list)} রিমুভ করা হয়েছে।"
        return f"❌ উল্লেখিত প্রিফিক্সগুলো {country_code} এর লিস্টে পাওয়া যায়নি।"

    def see_prefix(self, country_code=None):
        if country_code:
            country_code = country_code.upper().strip()
            if country_code in self.data:
                return f"📋 {country_code} এর প্রিফিক্সসমূহ:\n{', '.join(self.data[country_code])}"
            return f"❌ {country_code} কান্ট্রি কোডের কোনো প্রিফিক্স সেট করা নেই।"
        else:
            if not self.data:
                return "❌ বর্তমানে কোনো প্রিফিক্স সেট করা নেই।"
            
            result = "📋 সেট করা সকল প্রিফিক্স:\n"
            for code, prefixes in self.data.items():
                result += f"👉 {code}: {', '.join(prefixes)}\n"
            return result.strip()

prefix_manager = PrefixManager("prefixes.json")

# ==========================================================
# --- প্রিফিক্স ভ্যালিডেশন ফাংশন ---
# ==========================================================
def is_prefix_allowed(phone_number, country_code):
    """চেক করে যে নম্বরটির প্রিফিক্স অনুমোদিত লিস্টে আছে কিনা"""
    if not phone_number:
        return False
    
    prefix_file = "prefixes.json"
    if not os.path.exists(prefix_file):
        return True
    
    try:
        with open(prefix_file, 'r', encoding='utf-8') as f:
            prefix_data = json.load(f)
        
        country = country_code.upper().strip() if country_code else None
        if not country or country not in prefix_data:
            return True
        
        allowed_prefixes = prefix_data[country]
        cleaned_num = phone_number.lstrip('+')
        
        for prefix in allowed_prefixes:
            if cleaned_num.startswith(prefix):
                return True
        
        logging.warning(f"❌ প্রিফিক্স ম্যাচ নয়! Number: {phone_number}, Country: {country}, Allowed: {allowed_prefixes}")
        return False
    except Exception as e:
        logging.error(f"Prefix validation error: {e}")
        return True

# --- কাস্টম প্রক্সি সকেট ট্র্যাকার ---
class MonitoredSocket:
    def __init__(self, sock):
        self._sock = sock
    def recv(self, buflen, flags=0):
        data = self._sock.recv(buflen, flags)
        global TOTAL_PROXY_BYTES_RECV
        TOTAL_PROXY_BYTES_RECV += len(data)
        return data
    def send(self, data, flags=0):
        global TOTAL_PROXY_BYTES_SENT
        TOTAL_PROXY_BYTES_SENT += len(data)
        return self._sock.send(data, flags)
    def __getattr__(self, attr):
        return getattr(self._sock, attr)

def load_sessions():
    global active_sessions
    active_sessions.clear()
    if os.path.exists(SESSION_DATA_FILE):
        with open(SESSION_DATA_FILE, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 3:
                    active_sessions.append({
                        "session_path": parts[0],
                        "api_id": int(parts[1]),
                        "api_hash": parts[2]
                    })
        logging.info(f"Loaded {len(active_sessions)} sessions from file.")

def save_session_to_file(name, api_id, api_hash):
    with open(SESSION_DATA_FILE, "a") as f:
        f.write(f"{name}|{api_id}|{api_hash}\n")

def get_telethon_proxy():
    if not PROXY_SETTINGS:
        return None
    import socks
    ptype = PROXY_SETTINGS['type'].lower()
    proxy_map = {'socks4': socks.SOCKS4, 'socks5': socks.SOCKS5, 'http': socks.HTTP}
    
    if not hasattr(socks.socksocket, '_patched'):
        orig_recv = socks.socksocket.recv
        orig_send = socks.socksocket.send
        def new_recv(self, buflen, flags=0):
            data = orig_recv(self, buflen, flags)
            global TOTAL_PROXY_BYTES_RECV
            TOTAL_PROXY_BYTES_RECV += len(data)
            return data
        def new_send(self, data, flags=0):
            global TOTAL_PROXY_BYTES_SENT
            TOTAL_PROXY_BYTES_SENT += len(data)
            return orig_send(self, data, flags)
        socks.socksocket.recv = new_recv
        socks.socksocket.send = new_send
        socks.socksocket._patched = True

    return (
        proxy_map.get(ptype, socks.SOCKS5),
        PROXY_SETTINGS['addr'],
        PROXY_SETTINGS['port'],
        True,
        PROXY_SETTINGS.get('user'),
        PROXY_SETTINGS.get('pass')
    )

async def get_next_active_client():
    global current_account_index, active_sessions
    if not active_sessions:
        return None, None
    attempts = 0
    total_acc = len(active_sessions)
    proxy_settings = get_telethon_proxy()
    
    while attempts < total_acc:
        acc = active_sessions[current_account_index]
        client = TelegramClient(acc["session_path"], acc["api_id"], acc["api_hash"], proxy=proxy_settings)
        session_num = current_account_index + 1
        current_account_index = (current_account_index + 1) % total_acc
        try:
            await client.connect()
            if await client.is_user_authorized():
                return client, session_num
            else:
                await client.disconnect()
        except Exception as e:
            logging.error(f"Session {session_num} connection failed: {e}")
            try: await client.disconnect()
            except: pass
        attempts += 1
    return None, None

async def telethon_check_number_status(phone_number: str):
    global active_sessions, TELEGRAM_CHECKER_ON
    if not TELEGRAM_CHECKER_ON: return "Checker OFF ⚪"
    if not active_sessions: return "No Session ⚪"
    
    formatted_num = phone_number if phone_number.startswith('+') else f"+{phone_number}"
    client, session_num = await get_next_active_client()
    if not client: return "Session Error ⚪"
        
    try:
        from telethon.tl.functions.contacts import ImportContactsRequest
        from telethon.tl.types import InputPhoneContact
        await asyncio.sleep(random.uniform(1.5, 3.0))
        
        contact = InputPhoneContact(client_id=0, phone=formatted_num, first_name="Check", last_name="")
        result = await client(ImportContactsRequest([contact]))
        await client.disconnect()
        if result.users: return f"Active 🟢 (S-{session_num})"
        else: return "Not Active 🔴"
    except FloodWaitError:
        try: await client.disconnect()
        except: pass
        return "Flood/Limit ⚠️"
    except Exception:
        try: await client.disconnect()
        except: pass
        return "Unknown ⚪"

# --- Durian RCS API লজিক ---
def detect_country_by_number(phone_num):
    if not phone_num: return "unknown"
    cleaned_num = phone_num.lstrip('+').lstrip('0')
    if cleaned_num[:4] in COUNTRY_PREFIX_MAP: return COUNTRY_PREFIX_MAP[cleaned_num[:4]]
    if cleaned_num[:3] in COUNTRY_PREFIX_MAP: return COUNTRY_PREFIX_MAP[cleaned_num[:3]]
    if cleaned_num[:2] in COUNTRY_PREFIX_MAP: return COUNTRY_PREFIX_MAP[cleaned_num[:2]]
    if cleaned_num[:1] in COUNTRY_PREFIX_MAP: return COUNTRY_PREFIX_MAP[cleaned_num[:1]]
    return "unknown"

def get_correct_pid(country_code):
    if not country_code: return "0257"
    code = country_code.strip().lower()
    if code in PID_6003_COUNTRIES: return "6003"
    return "0257"

def durian_get(path, params):
    for host in DURIAN_HOSTS:
        try:
            url = f"{host}/out/ext_api/{path}"
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 404: continue
            response.raise_for_status()
            try: return response.json(), None
            except ValueError:
                if "getUserInfo" in path and response.text: return {"code": 200, "data": {"score": response.text.strip()}}, None
                return None, f"Invalid JSON"
        except Exception: pass
    return None, "API Connection Error"

def api_ok(res):
    if not res: return False
    code = res.get("code")
    return code == 200 or str(code) == "200" or res.get("msg") in ["Success", "success"]

def fetch_phone_number(country, pid):
    params = {"name": DURIAN_USERNAME, "ApiKey": DURIAN_API_KEY, "pid": pid, "num": 1, "noblack": 0, "serial": 2}
    if country is not None: params["cuy"] = country.strip().lower()
    
    for endpoint in ["getPhoneNum", "getMobile"]:
        res, err = durian_get(endpoint, params)
        if not err and res:
            if isinstance(res, dict):
                if api_ok(res) and res.get("data"):
                    data_str = str(res["data"]).split(",")
                    phone_num = data_str[0]
                    detected_cuy = data_str[1].strip().lower() if (len(data_str) > 1 and data_str[1].isalpha()) else (country or detect_country_by_number(phone_num))
                    
                    if not is_prefix_allowed(phone_num, country or detected_cuy):
                        logging.warning(f"❌ প্রিফিক্স ম্যাচ নয়! Number: {phone_num}, Country: {country or detected_cuy}")
                        return None, None, f"প্রিফিক্স অনুমোদিত নয়: {phone_num}"
                    
                    return phone_num, detected_cuy, None
            elif isinstance(res, str) and "," in res:
                data_str = res.split(",")
                phone_num = data_str[0]
                detected_cuy = data_str[1].strip().lower() if (len(data_str) > 1 and data_str[1].isalpha()) else (country or detect_country_by_number(phone_num))
                
                if not is_prefix_allowed(phone_num, country or detected_cuy):
                    logging.warning(f"❌ প্রিফিক্স ম্যাচ নয়! Number: {phone_num}, Country: {country or detected_cuy}")
                    return None, None, f"প্রিফিক্স অনুমোদিত নয়: {phone_num}"
                
                return phone_num, detected_cuy, None
    return None, None, "স্টক খালি বা এপিআই রেসপন্স এরর"

def get_user_balance():
    params = {"name": DURIAN_USERNAME, "ApiKey": DURIAN_API_KEY}
    res, err = durian_get("getUserInfo", params)
    if err: return "0.00"
    if res and isinstance(res, dict):
        data = res.get("data", {})
        if isinstance(data, dict): return data.get("score") or data.get("money") or res.get("score") or "0.00"
        elif isinstance(data, (str, int, float)): return data
    return "0.00"

def send_telegram_request(method, payload):
    url = f"{TELEGRAM_API}/{method}"
    try: return requests.post(url, json=payload, timeout=20).json()
    except Exception: return None

def get_main_menu_text():
    balance = get_user_balance()
    bulk_status = "RUNNING " if BULK_ACTIVE else "STOPPED "
    checker_status = "ACTIVE 🟢" if TELEGRAM_CHECKER_ON else "DISABLED "
    
    total_mb_used = (TOTAL_PROXY_BYTES_SENT + TOTAL_PROXY_BYTES_RECV) / (1024 * 1024)
    proxy_status = f"CONNECTED 🌐 ({PROXY_SETTINGS['type'].upper()})" if PROXY_SETTINGS else "NONE ⚠️"
    
    countries = ", ".join(c.upper() for c in SELECTED_COUNTRIES) or "None"
    sessions_count = len(active_sessions)
    return (
        f"🤖 *SMS Control & Telethon Checker Bot*\n\n"
        f"👤 User: `{DURIAN_USERNAME}` | 🔋 সেশন পুল: `{sessions_count}` টি\n"
        f"⚙️ Telegram Checker: *{checker_status}*\n"
        f" Checker Proxy: `{proxy_status}`\n"
        f"📊 Proxy Data Used: `{total_mb_used:.2f} MB`\n"
        f"💰 *Current Balance: {balance}*\n"
        f"🌍 Single Country: `{CURRENT_COUNTRY.upper()}` (PID: {get_correct_pid(CURRENT_COUNTRY)})\n"
        f"📋 Bulk Countries: `{countries}`\n"
        f"⚡ Bulk Status: *{bulk_status}*\n\n"
        f"নম্বর চেক করতে সরাসরি প্লাস (+) সহ নম্বর পাঠান। অথবা প্যানেল ইউজ করুন:"
    )

def get_reply_keyboard():
    return {
        "keyboard": [
            [{"text": " Project: 0257 (Global)"}, {"text": "📦 Project: 6003 (Special)"}], 
            [{"text": "🎯 Single Number"}, {"text": "🎯 Set Single Country"}], 
            [{"text": "🌍 Add Countries"}, {"text": "📋 Selected Countries"}],
            [{"text": "🗑️ Remove Countries"}, {"text": "📊 Report"}],
            [{"text": "⚙️ Set Prefix"}, {"text": "👁️ See Prefix"}],
            [{"text": "🗑️ Remove Prefix"}],
            [{"text": "🚀 Bulk Start"}, {"text": "🛑 Bulk Stop"}],
            [{"text": "🛑 TOTAL BOT STOP"}, {"text": "🏁 Start / Refresh"}] 
        ], "resize_keyboard": True, "one_time_keyboard": False
    }

def live_otp_countdown_poller(chat_id, message_id, p_num, used_pid, country_code=None, is_bulk=False):
    global ACTIVE_POLLING_NUMBERS
    if p_num in ACTIVE_POLLING_NUMBERS: return
    ACTIVE_POLLING_NUMBERS.add(p_num)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: tg_status = loop.run_until_complete(telethon_check_number_status(p_num))
    except Exception: tg_status = "Unknown ⚪"
    finally: loop.close()

    params = {"name": DURIAN_USERNAME, "ApiKey": DURIAN_API_KEY, "pn": p_num, "pid": used_pid, "serial": 2}
    total_seconds, start_time, otp_found, stopped_manually, last_ui_update = 300, time.time(), False, False, 0
    c_display = country_code.upper() if (country_code and country_code != "unknown") else "DETECTED"

    while time.time() - start_time < total_seconds:
        if p_num not in ACTIVE_POLLING_NUMBERS:
            stopped_manually = True; break  
        remaining = total_seconds - int(time.time() - start_time)
        mins, secs = divmod(remaining, 60)
        time_str = f"{mins:02d}:{secs:02d}"

        if time.time() - last_ui_update >= 3:
            res, err = durian_get("getMsg", params)
            mode_tag = "🚀 [Bulk Mode]" if is_bulk else f"🎯 [Project: {used_pid}]"
            status_text = f"{mode_tag}\n📱 Number: `{p_num}` ({c_display})\ntelegram: *{tg_status}*\n⏳ *Status:* ওটিপির জন্য অপেক্ষা করা হচ্ছে...\n️ *Time Left:* `{time_str}`"
            action_keyboard = {
                "inline_keyboard": [
                    [{"text": f"⌛ {time_str} Min Left", "callback_data": "none_click"}],
                    [{"text": f" Stop Tracking", "callback_data": f"stp_{p_num}_{used_pid}"}, {"text": "🚫 Blacklist", "callback_data": f"blk_{p_num}_{used_pid}"}],
                    [{"text": f"🔄 Get Another {c_display}", "callback_data": f"nxt_{country_code or 'none'}_{used_pid}"}]
                ]
            }
            if not err and res:
                c_status = str(res.get("code"))
                if c_status == "200" and res.get("data"):
                    final_text = f" *সফল! ওটিপি কোড এসে গেছে!*\n\n{mode_tag}\n📱 Number: `{p_num}` ({c_display})\ntelegram: *{tg_status}*\n💬 OTP Code: `{res['data']}`"
                    send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": final_text, "reply_markup": {"inline_keyboard": [[{"text": f" Get Another {c_display}", "callback_data": f"nxt_{country_code or 'none'}_{used_pid}"}]]}, "parse_mode": "Markdown"})
                    otp_found = True; break
                elif c_status != "908" and c_status != "None":
                    send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": f"❌ বাতিল: {res.get('msg')}", "reply_markup": {"inline_keyboard": [[{"text": f" Get Another {c_display}", "callback_data": f"nxt_{country_code or 'none'}_{used_pid}"}]]}})
                    break
            send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": status_text, "reply_markup": action_keyboard, "parse_mode": "Markdown"})
            last_ui_update = time.time()
        time.sleep(1)

    if stopped_manually:
        send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": f" `{p_num}` ওটিপি ট্র্যাকিং বন্ধ।", "reply_markup": {"inline_keyboard": [[{"text": f"🔄 Get Another {c_display}", "callback_data": f"nxt_{country_code or 'none'}_{used_pid}"}]]}, "parse_mode": "Markdown"})
    elif not otp_found and p_num in ACTIVE_POLLING_NUMBERS:
        send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": f"⏰ টাইমআউট! `{p_num}` নম্বরে ওটিপি আসেনি।\ntelegram: *{tg_status}*", "reply_markup": {"inline_keyboard": [[{"text": f"🔄 Get Another {c_display}", "callback_data": f"nxt_{country_code or 'none'}_{used_pid}"}]]}, "parse_mode": "Markdown"})
    ACTIVE_POLLING_NUMBERS.discard(p_num)

def single_number_loop_worker(chat_id, message_id, country, pid):
    global SINGLE_LOOP_ACTIVE
    attempts = 0
    while SINGLE_LOOP_ACTIVE:
        attempts += 1
        country_display = country.upper() if country else "GLOBAL"
        send_telegram_request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": f"⏳ `{country_display}` প্যানেল থেকে [PID: {pid}] নম্বর খোঁজা হচ্ছে...\n🔄 চেষ্টা নম্বর: {attempts}"})
        p_num, detected_cuy, err = fetch_phone_number(country, pid)
        if p_num:
            live_otp_countdown_poller(chat_id, message_id, p_num, pid, detected_cuy, is_bulk=False)
            break
        time.sleep(3.5)

def bulk_worker():
    global BULK_ACTIVE
    while BULK_ACTIVE:
        countries = SELECTED_COUNTRIES or [CURRENT_COUNTRY]
        for country in countries:
            if not BULK_ACTIVE: break
            if ADMIN_CHAT_ID is None: time.sleep(2); continue
            fixed_pid = get_correct_pid(country)
            p_num, detected_cuy, err = fetch_phone_number(country, fixed_pid)
            if p_num and ADMIN_CHAT_ID:
                init_msg = send_telegram_request("sendMessage", {"chat_id": ADMIN_CHAT_ID, "text": f"🚀 [Bulk Mode]\n📱 `{p_num}` ({detected_cuy.upper()}) ওটিপি বক্স তৈরি হচ্ছে...", "parse_mode": "Markdown"})
                if init_msg and init_msg.get("ok"):
                    threading.Thread(target=live_otp_countdown_poller, args=(ADMIN_CHAT_ID, init_msg["result"]["message_id"], p_num, fixed_pid, detected_cuy, True), daemon=True).start()
            time.sleep(4)
        time.sleep(2)

def start_new_single_number_box(chat_id, country, pid):
    global SINGLE_LOOP_ACTIVE
    SINGLE_LOOP_ACTIVE = True
    init_msg = send_telegram_request("sendMessage", {"chat_id": chat_id, "text": f"⏳ নতুন নম্বর খোঁজা হচ্ছে..."})
    if init_msg and init_msg.get("ok"):
        threading.Thread(target=single_number_loop_worker, args=(chat_id, init_msg["result"]["message_id"], country, pid), daemon=True).start()

def get_checker_inline_keyboard():
    global TELEGRAM_CHECKER_ON
    checker_text = "🔴 Turn Checker OFF" if TELEGRAM_CHECKER_ON else "🟢 Turn Checker ON"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(checker_text, callback_data="btn_toggle_checker"), 
         InlineKeyboardButton("📊 Proxy MB Status", callback_data="btn_proxy_status")],
        [InlineKeyboardButton("⚙️ Set/Edit Proxy", callback_data="btn_edit_proxy")],
        [InlineKeyboardButton("➕ Add Telethon Session", callback_data="btn_add_session"),
         InlineKeyboardButton("📋 Sessions Pool", callback_data="btn_status")]
    ])

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID: return
    reset_input_modes()
    await update.message.reply_text(get_main_menu_text(), reply_markup=get_reply_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("️ **টেলিগ্রাম চেকার, প্রক্সি ও সেশন কন্ট্রোল প্যানেল:**", reply_markup=get_checker_inline_keyboard())

def reset_input_modes():
    global WAITING_FOR_COUNTRY, WAITING_FOR_ADD_COUNTRIES, WAITING_FOR_REMOVE_COUNTRIES
    global WAITING_FOR_SET_PREFIX, WAITING_FOR_REMOVE_PREFIX, WAITING_FOR_SEE_PREFIX
    WAITING_FOR_COUNTRY = False
    WAITING_FOR_ADD_COUNTRIES = False
    WAITING_FOR_REMOVE_COUNTRIES = False
    WAITING_FOR_SET_PREFIX = False
    WAITING_FOR_REMOVE_PREFIX = False
    WAITING_FOR_SEE_PREFIX = False

async def handle_bot_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_COUNTRY, SELECTED_COUNTRIES, WAITING_FOR_COUNTRY, ADMIN_CHAT_ID, PROXY_SETTINGS
    global WAITING_FOR_ADD_COUNTRIES, WAITING_FOR_REMOVE_COUNTRIES, BULK_ACTIVE, SINGLE_LOOP_ACTIVE
    global WAITING_FOR_SET_PREFIX, WAITING_FOR_REMOVE_PREFIX, WAITING_FOR_SEE_PREFIX
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    text_lower = text.lower()
    
    if user_id != ALLOWED_USER_ID: return
    ADMIN_CHAT_ID = chat_id

    # ১. প্রথমে বাটন কমান্ড চেক করা (যাতে Waiting মোডে থাকলেও বাটন কাজ করে)
    if "start / refresh" in text_lower or text == "🏁 Start / Refresh":
        reset_input_modes()
        await update.message.reply_text(get_main_menu_text(), reply_markup=get_reply_keyboard(), parse_mode="Markdown")
        await update.message.reply_text("⚙️ **টেলিগ্রাম চেকার, প্রক্সি ও সেশন কন্ট্রোল প্যানেল:**", reply_markup=get_checker_inline_keyboard())
        return
    elif "project: 0257" in text_lower:
        reset_input_modes(); start_new_single_number_box(chat_id, None, "0257"); return
    elif "project: 6003" in text_lower:
        reset_input_modes(); start_new_single_number_box(chat_id, None, "6003"); return
    elif "single number" in text_lower:
        reset_input_modes(); start_new_single_number_box(chat_id, CURRENT_COUNTRY, get_correct_pid(CURRENT_COUNTRY)); return
    elif "set single country" in text_lower:
        reset_input_modes(); WAITING_FOR_COUNTRY = True
        await update.message.reply_text(f"🌍 বর্তমানে সেট করা দেশ: `{CURRENT_COUNTRY.upper()}`\n\nনতুন ২ অক্ষরের কান্ট্রি কোডটি লিখে পাঠান।")
        return
    elif "add countries" in text_lower:
        reset_input_modes(); WAITING_FOR_ADD_COUNTRIES = True
        await update.message.reply_text("🌍 যোগ করার জন্য কান্ট্রি কোড লিখুন (যেমন: th,id)")
        return
    elif "selected countries" in text_lower:
        reset_input_modes()
        t_str = " *Selected Countries:*\n\n"
        for c in SELECTED_COUNTRIES: t_str += f"🏳️ `{c.upper()}` -> PID: `{get_correct_pid(c)}`\n"
        await update.message.reply_text(t_str, parse_mode="Markdown")
        return
    elif "remove countries" in text_lower:
        reset_input_modes(); WAITING_FOR_REMOVE_COUNTRIES = True
        await update.message.reply_text("🗑️ সরাতে চান এমন কোড লিখুন।")
        return
    elif "bulk start" in text_lower:
        reset_input_modes()
        if not BULK_ACTIVE:
            BULK_ACTIVE = True
            threading.Thread(target=bulk_worker, daemon=True).start()
        await update.message.reply_text(f"🚀 Bulk মোড চালু হয়েছে।", reply_markup=get_reply_keyboard())
        return
    elif "bulk stop" in text_lower:
        reset_input_modes(); BULK_ACTIVE = False
        await update.message.reply_text(" Bulk মোড বন্ধ করা হয়েছে।", reply_markup=get_reply_keyboard())
        return
    elif "total bot stop" in text_lower:
        reset_input_modes(); BULK_ACTIVE = False; SINGLE_LOOP_ACTIVE = False
        await update.message.reply_text("🛑 *TOTAL BOT STOP*", parse_mode="Markdown")
        return
    elif "report" in text_lower:
        reset_input_modes()
        params = {"name": DURIAN_USERNAME, "ApiKey": DURIAN_API_KEY, "pid": "", "vip": ""}
        res, err = durian_get("getCountryPhoneNum", params)
        if not err and res and res.get("code") == 200:
            r_text = "📊 *লাইভ অনলাইন ফোন নম্বরের বিবরণ:*\n\n"
            for k, v in res["data"].items(): r_text += f"️ {k.upper()}: {v} টি সচল নম্বর\n"
        else: r_text = "❌ রিপোর্ট ডাটা পাওয়া যায়নি।"
        await update.message.reply_text(r_text, parse_mode="Markdown")
        return
    elif text.startswith("+"):
        checking_msg = await update.message.reply_text(f"⏳ প্রক্সি সেশন পুল ব্যবহার করে `{text}` নম্বরটি চেক করা হচ্ছে...")
        status = await telethon_check_number_status(text)
        await checking_msg.edit_text(f"📱 **ম্যানুয়ালি নম্বর চেকার রেজাল্ট:**\n\nনম্বর: `{text}`\nস্ট্যাটাস: *{status}*", parse_mode="Markdown")
        return
    elif "set prefix" in text_lower:
        reset_input_modes()
        WAITING_FOR_SET_PREFIX = True
        await update.message.reply_text("️ **প্রিফিক্স সেট করুন**\n\nফরম্যাট: `CountryCode,Prefix1.Prefix2.Prefix3`\nউদাহরণ: `TJ,99290.99297.99255`\n\nকান্ট্রি কোড এবং প্রিফিক্সগুলো লিখে পাঠান:")
        return
    elif "see prefix" in text_lower:
        reset_input_modes()
        WAITING_FOR_SEE_PREFIX = True
        await update.message.reply_text("👁️ **প্রিফিক্স দেখুন**\n\nকান্ট্রি কোডটি লিখুন (যেমন: `TJ`) অথবা সব দেখতে `all` লিখুন:")
        return
    elif "remove prefix" in text_lower:
        reset_input_modes()
        WAITING_FOR_REMOVE_PREFIX = True
        await update.message.reply_text("🗑️ **প্রিফিক্স রিমুভ করুন**\n\nফরম্যাট: `CountryCode,Prefix`\nউদাহরণ: `TJ,99297`\n\nকান্ট্রি কোড এবং রিমুভ করার প্রিফিক্স লিখে পাঠান:")
        return

    # ২. ইউজার স্টেট চেক (প্রক্সি/সেশন সেটআপ)
    if user_id in user_states:
        state = user_states[user_id]["step"]
        if state == "WAITING_PROXY_INPUT":
            try:
                parts = text.split("|")
                if len(parts) >= 3:
                    PROXY_SETTINGS = {
                        'type': parts[0].strip().lower(),
                        'addr': parts[1].strip(),
                        'port': int(parts[2].strip()),
                        'user': parts[3].strip() if len(parts) > 3 else None,
                        'pass': parts[4].strip() if len(parts) > 4 else None
                    }
                    await update.message.reply_text(f"✅ প্রক্সি সফলভাবে সেভ হয়েছে!\nType: `{PROXY_SETTINGS['type']}`\nHost: `{PROXY_SETTINGS['addr']}:{PROXY_SETTINGS['port']}`", parse_mode="Markdown")
                else:
                    await update.message.reply_text("❌ ফরম্যাট ভুল! দয়া করে সঠিক ফরম্যাটে দিন।")
            except Exception as e:
                await update.message.reply_text(f"❌ প্রক্সি সেভ করতে সমস্যা হয়েছে: {e}")
            user_states.pop(user_id, None)
            return
            
        elif state == "WAITING_API_ID":
            if not text.isdigit(): await update.message.reply_text("❌ API_ID অবশ্যই সংখ্যা হতে হবে।"); return
            user_states[user_id]["api_id"] = int(text)
            user_states[user_id]["step"] = "WAITING_API_HASH"
            await update.message.reply_text("🔑 এবার অ্যাপের **API_HASH** লিখে পাঠান:")
            return
        elif state == "WAITING_API_HASH":
            user_states[user_id]["api_hash"] = text
            user_states[user_id]["step"] = "WAITING_PHONE"
            await update.message.reply_text("📱 এবার টেলিগ্রাম নম্বরটি আন্তর্জাতিক ফর্ম্যাটে প্লাস (+) সহ পাঠান:")
            return
        elif state == "WAITING_PHONE":
            if not text.startswith("+"): await update.message.reply_text("❌ ফোন নম্বরটি অবশ্যই '+' সহ হতে হবে।"); return
            user_states[user_id]["phone"] = text
            api_id = user_states[user_id]["api_id"]
            api_hash = user_states[user_id]["api_hash"]
            session_name = f"sessions/session_{text.replace('+', '')}"
            checking_msg = await update.message.reply_text("⏳ প্রক্সি হয়ে টেলিগ্রাম সার্ভারে কানেক্ট করা হচ্ছে...")
            try:
                client = TelegramClient(session_name, api_id, api_hash, proxy=get_telethon_proxy())
                await client.connect()
                phone_code_hash = await client.send_code_request(text)
                user_states[user_id].update({"step": "WAITING_OTP", "client": client, "phone_code_hash": phone_code_hash.phone_code_hash, "session_path": session_name})
                await checking_msg.edit_text(f"📩 আপনার `{text}` নম্বরে ওটিপি পাঠানো হয়েছে। কোডটি পাঠান:")
            except Exception as e:
                await checking_msg.edit_text(f"❌ এরর এসেছে: {str(e)}")
                user_states.pop(user_id, None)
            return
        elif state == "WAITING_OTP":
            client, phone, phone_code_hash = user_states[user_id]["client"], user_states[user_id]["phone"], user_states[user_id]["phone_code_hash"]
            try:
                await client.sign_in(phone, text, phone_code_hash=phone_code_hash)
                save_session_to_file(user_states[user_id]["session_path"], user_states[user_id]["api_id"], user_states[user_id]["api_hash"])
                active_sessions.append({"session_path": user_states[user_id]["session_path"], "api_id": user_states[user_id]["api_id"], "api_hash": user_states[user_id]["api_hash"]})
                await update.message.reply_text(f"🎉 অ্যাকাউন্ট `{phone}` সেশন পুলে সাকসেসফুলি যুক্ত হয়েছে।")
                user_states.pop(user_id, None)
            except SessionPasswordNeededError:
                user_states[user_id]["step"] = "WAITING_PASSWORD"
                await update.message.reply_text("🔐 টু-স্টেপ ভেরিফিকেশন পাসওয়ার্ড দিন:")
            except Exception as e:
                await update.message.reply_text(f"❌ ভুল ওটিপি। Error: {str(e)}")
                user_states.pop(user_id, None)
            return
        elif state == "WAITING_PASSWORD":
            client, phone = user_states[user_id]["client"], user_states[user_id]["phone"]
            try:
                await client.sign_in(password=text)
                save_session_to_file(user_states[user_id]["session_path"], user_states[user_id]["api_id"], user_states[user_id]["api_hash"])
                active_sessions.append({"session_path": user_states[user_id]["session_path"], "api_id": user_states[user_id]["api_id"], "api_hash": user_states[user_id]["api_hash"]})
                await update.message.reply_text(f"🎉 পাসওয়ার্ড সঠিক! অ্যাকাউন্ট `{phone}` পুলে যুক্ত হয়েছে।")
            except Exception as e: await update.message.reply_text(f"❌ ভুল পাসওয়ার্ড। Error: {str(e)}")
            user_states.pop(user_id, None)
            return

    # ৩. Waiting মোড চেক
    elif WAITING_FOR_COUNTRY:
        if len(text) == 2 and text.isalpha():
            CURRENT_COUNTRY = text.lower(); reset_input_modes()
            await update.message.reply_text(f"✅ কান্ট্রি কোড `{CURRENT_COUNTRY.upper()}` সেট হয়েছে।")
        else: await update.message.reply_text("❌ ভুল কোড!")
    elif WAITING_FOR_ADD_COUNTRIES:
        cleaned = text.replace(",", " ").split()
        for part in cleaned:
            code = part.strip().lower()
            if len(code) == 2 and code not in SELECTED_COUNTRIES: SELECTED_COUNTRIES.append(code)
        reset_input_modes(); await update.message.reply_text("✅ কান্ট্রি যোগ করা হয়েছে।")
    elif WAITING_FOR_REMOVE_COUNTRIES:
        cleaned = text.replace(",", " ").split()
        SELECTED_COUNTRIES[:] = [c for c in SELECTED_COUNTRIES if c not in cleaned]
        reset_input_modes(); await update.message.reply_text("🗑️ মেমোরি থেকে সরানো হয়েছে।")
    elif WAITING_FOR_SET_PREFIX:
        if "," in text:
            parts = text.split(",", 1)
            country = parts[0].strip()
            prefixes = parts[1].strip()
            if len(country) >= 2 and prefixes:
                result = prefix_manager.set_prefix(country, prefixes)
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("❌ ভুল ফরম্যাট! উদাহরণ: `TJ,99290.99297`")
        else:
            await update.message.reply_text("❌ ভুল ফরম্যাট! কমা (,) দিয়ে কান্ট্রি কোড এবং প্রিফিক্স আলাদা করুন। উদাহরণ: `TJ,99290.99297`")
        reset_input_modes()
    elif WAITING_FOR_REMOVE_PREFIX:
        if "," in text:
            parts = text.split(",", 1)
            country = parts[0].strip()
            prefixes = parts[1].strip()
            if len(country) >= 2 and prefixes:
                result = prefix_manager.remove_prefix(country, prefixes)
                await update.message.reply_text(result)
            else:
                await update.message.reply_text(" ভুল ফরম্যাট! উদাহরণ: `TJ,99297`")
        else:
            await update.message.reply_text("❌ ভুল ফরম্যাট! কমা (,) দিয়ে কান্ট্রি কোড এবং প্রিফিক্স আলাদা করুন। উদাহরণ: `TJ,99297`")
        reset_input_modes()
    elif WAITING_FOR_SEE_PREFIX:
        country = text.strip()
        if country.lower() in ["all", "সব"]:
            result = prefix_manager.see_prefix()
        else:
            result = prefix_manager.see_prefix(country)
        await update.message.reply_text(result)
        reset_input_modes()

async def handle_callback_queries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ACTIVE_POLLING_NUMBERS, active_sessions, TELEGRAM_CHECKER_ON
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if user_id != ALLOWED_USER_ID: return

    if data == "btn_toggle_checker":
        TELEGRAM_CHECKER_ON = not TELEGRAM_CHECKER_ON
        status_text = "চালু (ACTIVE )" if TELEGRAM_CHECKER_ON else "বন্ধ (DISABLED 🛑)"
        await query.message.reply_text(f"⚙️ টেলিগ্রাম রোটেশনাল চেকার এখন **{status_text}** করা হয়েছে।")
        await query.message.edit_reply_markup(reply_markup=get_checker_inline_keyboard())
        
    elif data == "btn_proxy_status":
        total_mb = (TOTAL_PROXY_BYTES_SENT + TOTAL_PROXY_BYTES_RECV) / (1024 * 1024)
        sent_mb = TOTAL_PROXY_BYTES_SENT / (1024 * 1024)
        recv_mb = TOTAL_PROXY_BYTES_RECV / (1024 * 1024)
        status_text = (
            f"📊 **লাইভ প্রক্সি মেগাবাইট (MB) স্ট্যাটাস:**\n\n"
            f"📥 ডেটা ডাউনলোড (Received): `{recv_mb:.3f} MB`\n"
            f"📤 ডেটা আপলোড (Sent): `{sent_mb:.3f} MB`\n"
            f"📈 **মোট ব্যবহৃত ডেটা:** `{total_mb:.2f} MB`"
        )
        await query.message.reply_text(status_text, parse_mode="Markdown")
        
    elif data == "btn_edit_proxy":
        user_states[user_id] = {"step": "WAITING_PROXY_INPUT"}
        help_msg = (
            "⚙️ **প্রক্সি সেটআপ ফরম্যাট:**\n\n"
            "নিচের ফরম্যাটে লিখে পাঠান:\n"
            "`proxy_type|ip_address|port|username|password`\n\n"
            "💡 *উদাহরণ:* `socks5|192.168.1.1|1080|alex55|pass123`\n"
            "(ইউজারনেম-পাসওয়ার্ড না থাকলে শুধু: `socks5|192.168.1.1|1080` দিন)"
        )
        await query.message.reply_text(help_msg, parse_mode="Markdown")
        
    elif data == "btn_status":
        await query.message.reply_text(f" বর্তমানে রোটেশনাল চেকিং পুলে মোট **{len(active_sessions)}** টি সেশন যুক্ত আছে।")
    elif data == "btn_add_session":
        user_states[user_id] = {"step": "WAITING_API_ID"}
        await query.message.reply_text(" অনুগ্রহ করে আপনার অ্যাপের **API_ID** টি লিখে পাঠান:")
    elif data.startswith("stp_"):
        p_num = data.split("_")[1]; ACTIVE_POLLING_NUMBERS.discard(p_num)
    elif data.startswith("nxt_"):
        parts = data.split("_"); target_cuy = parts[1]; target_pid = parts[2]
        actual_cuy = None if target_cuy in ["none", "unknown"] else target_cuy
        start_new_single_number_box(query.message.chat_id, actual_cuy, target_pid)
    elif data.startswith("blk_"):
        parts = data.split("_"); p_num, used_pid = parts[1], parts[2]
        ACTIVE_POLLING_NUMBERS.discard(p_num)
        params = {"name": DURIAN_USERNAME, "ApiKey": DURIAN_API_KEY, "pn": p_num, "pid": used_pid}
        res, _ = durian_get("addBlack", params)
        if res and res.get("code") == 200: await query.message.reply_text(f"🚫 `{p_num}` ব্ল্যাকলিস্ট করা হয়েছে।")

def main():
    if not os.path.exists('sessions'): os.makedirs('sessions')
    load_sessions() 
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CallbackQueryHandler(handle_callback_queries))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bot_text_input))
    print("🚀 প্রক্সি অ্যান্ড মেগাবাইট ট্র্যাকার বট সাকসেসফুলি রানিং...")
    application.run_polling()

if __name__ == '__main__':
    main()