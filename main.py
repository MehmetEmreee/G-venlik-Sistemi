# =================================================================
# GÜVENLİK SİSTEMİ KONTROLCÜSÜ v6.1 - TAM SÜRÜM
#
# ÖZELLİKLER:
# - Raspberry Pi 5 ve lgpio kütüphanesi ile tam uyumlu.
# - Telegram komutları ile sistemi AÇMA/KAPATMA (/aktifet1, /deaktifet1, /aktifet2, /deaktifet2).
# - Alarm anında Frigate'den anlık görüntü alıp Telegram'a YÜKLEME.
# - Sürekli okuma (Polling) ile daha sağlam sensör takibi.
# - Healthchecks.io entegrasyonu ile sistemin çökmesini takip etme (Heartbeat).
# - Sistemin normal mi yoksa çökme sonrası mı başladığını anlayan bildirim.
# - Tüm işlemlerin ana programı bloklamaması için Threading.
# =================================================================

import lgpio
import paho.mqtt.client as mqtt
import time
import requests
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

# --- AYARLAR: LÜTFEN BU BÖLÜMÜ KENDİ BİLGİLERİNİZLE DOLDURUN ---

# GPIO Pin Numaraları (BCM Modunda)
KAPI1_SENSOR_PIN = 23  # Mazot Tankı 1
KAPI2_SENSOR_PIN = 17  # Mazot Tankı 2
ALARM_ROLE_PIN = 24
GPIO_CHIP = 0  # Raspberry Pi 5 için bu değeri değiştirmeyin.

# MQTT Broker Ayarları
MQTT_BROKER_IP = "localhost"
MQTT_PORT = 1883
MQTT_DURUM_TOPIC = "guvenlik/sistem/durum"

# TELEGRAM AYARLARI
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN" # BotFather'dan alınan token
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"     # Bildirimlerin gönderileceği sohbet ID'si

# RÖLE ÇALIŞMA MANTIĞI (Ters çalışan röle için bu şekilde kalmalı)
ROLE_ACIK = 0    # Röleyi AÇAN sinyal (0 = LOW)
ROLE_KAPALI = 1  # Röleyi KAPATAN sinyal (1 = HIGH)

# HEARTBEAT AYARLARI (Sistem Çökme Takibi)
# Healthchecks.io sitesinden aldığınız özel Ping URL'nizi yapıştırın.
HEALTHCHECKS_PING_URL = "YOUR_HEALTHCHECKS_PING_URL" # Örn: "https://hc-ping.com/..."

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLEAN_SHUTDOWN_FLAG = os.path.join(BASE_DIR, "security_system_shutdown.flag")
SYSTEM_STATE_FILE = os.path.join(BASE_DIR, "security_system_state.flag")

# --- GLOBAL DEĞİŞKENLER ---
sistem_kurulu1 = False
sistem_kurulu2 = False
alarm1_tetiklendi_mi = False
alarm2_tetiklendi_mi = False
gpio_handle = None
mqtt_client = None
otomatik_alarm_kapali = False  # /otomatikalarmkapat komutu ile kontrol edilir


# =================================================================
# FONKSİYONLAR
# =================================================================

def send_heartbeat():
    """Healthchecks.io'ya 'hayattayım' sinyali gönderir."""
    if not HEALTHCHECKS_PING_URL or "hc-ping.com" not in HEALTHCHECKS_PING_URL:
        return
    try:
        requests.get(HEALTHCHECKS_PING_URL, timeout=10)
        print("Heartbeat sinyali başarıyla gönderildi.")
    except requests.RequestException as e:
        print(f"Heartbeat sinyali gönderilemedi: {e}")

def heartbeat_loop(stop_event):
    """Her 1 dakikada bir heartbeat sinyali gönderir."""
    print("Heartbeat döngüsü başlatıldı (1 dakikada bir).")
    while not stop_event.is_set():
        send_heartbeat()
        # 1 dakika (60 saniye) boyunca bekle.
        for _ in range(60):
            if stop_event.is_set():
                break
            time.sleep(1)

def send_telegram_notification(message, camera_name="tapo", max_retry=3):
    """Bildirim gönderir. Frigate'den fotoğrafı önce indirir, sonra Telegram'a yükler."""
    def task():
        FRIGATE_IP = "YOUR_FRIGATE_IP" # Frigate sunucunuzun yerel IP adresi
        FRIGATE_PORT = 5000
        photo_url = f"http://{FRIGATE_IP}:{FRIGATE_PORT}/api/{camera_name}/latest.jpg?h=480"
        
        image_content = None
        try:
            print(f"Frigate'den görüntü indiriliyor: {photo_url}")
            frigate_response = requests.get(photo_url, timeout=5)
            if frigate_response.status_code == 200:
                image_content = frigate_response.content
                print("Görüntü başarıyla indirildi.")
            else:
                print(f"Frigate'den görüntü alınamadı. HTTP Kodu: {frigate_response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Frigate sunucusuna bağlanırken hata oluştu: {e}")

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        for attempt in range(max_retry):
            try:
                if image_content:
                    files = {'photo': image_content}
                    data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': message}
                    telegram_response = requests.post(telegram_url, data=data, files=files, timeout=15)
                    if telegram_response.status_code == 200:
                        print("Fotoğraflı Telegram bildirimi başarıyla gönderildi.")
                        break
                    else:
                        raise ValueError(f"Telegram fotoğraf yüklemesini reddetti: {telegram_response.status_code}")
                else:
                    raise ValueError("Frigate görüntüsü mevcut değil.")
            except (ValueError, requests.exceptions.RequestException) as e:
                print(f"Hata nedeniyle sadece metin gönderiliyor (deneme {attempt+1}/{max_retry}): {e}")
                try:
                    url_text = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    error_note = "\n\n(Frigate'den kamera görüntüsü alınamadı.)" if attempt == max_retry - 1 else ""
                    data_text = {'chat_id': TELEGRAM_CHAT_ID, 'text': message + error_note}
                    response = requests.post(url_text, data=data_text, timeout=10)
                    if response.status_code == 200:
                        print("Metin bildirimi başarıyla gönderildi.")
                        break
                except Exception as text_error:
                    print(f"Metin bildirimi de gönderilemedi: {text_error}")
                    if attempt == max_retry - 1:
                        print("Tüm Telegram gönderim denemeleri başarısız!")

    threading.Thread(target=task).start()

def send_telegram_silent_photo(message, camera_name="tapo"):
    """Kapı hareketlerinde sessiz bildirim ve fotoğraf gönderir."""
    def task():
        FRIGATE_IP = "YOUR_FRIGATE_IP" # Frigate sunucunuzun yerel IP adresi
        FRIGATE_PORT = 5000
        photo_url = f"http://{FRIGATE_IP}:{FRIGATE_PORT}/api/{camera_name}/latest.jpg?h=480"
        image_content = None
        try:
            frigate_response = requests.get(photo_url, timeout=5)
            if frigate_response.status_code == 200:
                image_content = frigate_response.content
        except requests.exceptions.RequestException:
            pass

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            if image_content:
                files = {'photo': image_content}
                data = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'caption': message,
                    'disable_notification': True
                }
                requests.post(telegram_url, data=data, files=files, timeout=15)
            else:
                url_text = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data_text = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': message + "\n\n(Kamera görüntüsü alınamadı.)",
                    'disable_notification': True
                }
                requests.post(url_text, data=data_text, timeout=10)
        except Exception as e:
            print(f"Sessiz bildirim gönderilemedi: {e}")

    threading.Thread(target=task).start()

# --- DURUMU DOSYADA SAKLAMA ---
def save_system_state():
    with open(SYSTEM_STATE_FILE, "w") as f:
        state = []
        state.append("AKTIF1" if sistem_kurulu1 else "DEAKTIF1")
        state.append("AKTIF2" if sistem_kurulu2 else "DEAKTIF2")
        state.append("OTOMATIK_KAPALI" if otomatik_alarm_kapali else "OTOMATIK_ACIK")
        f.write(",".join(state))
        f.flush()
        os.fsync(f.fileno())

def load_system_state():
    global sistem_kurulu1, sistem_kurulu2, otomatik_alarm_kapali
    if os.path.exists(SYSTEM_STATE_FILE):
        with open(SYSTEM_STATE_FILE, "r") as f:
            state = f.read().strip().split(",")
            sistem_kurulu1 = "AKTIF1" in state
            sistem_kurulu2 = "AKTIF2" in state
            otomatik_alarm_kapali = "OTOMATIK_KAPALI" in state
    else:
        sistem_kurulu1 = False
        sistem_kurulu2 = False
        otomatik_alarm_kapali = False

def sensor_polling_loop(stop_event):
    """Her iki kapı sensörünü ayrı ayrı okur ve alarmı tetikler."""
    global alarm1_tetiklendi_mi, alarm2_tetiklendi_mi, sistem_kurulu1, sistem_kurulu2
    sensor_polling_loop.kapali_baslangic1 = None
    sensor_polling_loop.kapali_baslangic2 = None
    sensor_polling_loop.alarm_warning_sent1 = False
    sensor_polling_loop.alarm_warning_sent2 = False
    print("Sensör okuma döngüsü başlatıldı.")

    # İlk değerleri başlat
    last_pin_degeri1 = lgpio.gpio_read(gpio_handle, KAPI1_SENSOR_PIN)
    last_pin_degeri2 = lgpio.gpio_read(gpio_handle, KAPI2_SENSOR_PIN)
    alarm_repeat_time = 10
    alarm1_last_sent = 0
    alarm2_last_sent = 0

    while not stop_event.is_set():
        try:
            pin_degeri1 = lgpio.gpio_read(gpio_handle, KAPI1_SENSOR_PIN)
            pin_degeri2 = lgpio.gpio_read(gpio_handle, KAPI2_SENSOR_PIN)
            now = time.time()

            # Mazot Tankı 1 için otomatik kurulum ve uyarı
            if not sistem_kurulu1 and not otomatik_alarm_kapali:
                # Mazot Tankı 1 için sayaçlar ve otomatik kurulum
                # Kapı 1 kapalıysa
                if pin_degeri1 == 0:
                    if sensor_polling_loop.kapali_baslangic1 is None:
                        sensor_polling_loop.kapali_baslangic1 = now
                        sensor_polling_loop.alarm_warning_sent1 = False
                    elapsed1 = now - sensor_polling_loop.kapali_baslangic1 if sensor_polling_loop.kapali_baslangic1 else 0
                    if elapsed1 > 3300 and not sensor_polling_loop.alarm_warning_sent1:
                        send_telegram_notification("⏰ Mazot Tankı 1 kapısı 55 dakikadır kapalı. 5 dakika sonra alarm otomatik olarak kurulacak!", camera_name="tapo")
                        sensor_polling_loop.alarm_warning_sent1 = True
                    if elapsed1 > 3600:
                        sistem_kurulu1 = True
                        alarm1_tetiklendi_mi = False
                        save_system_state()
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU1", retain=True)
                        send_telegram_notification("ℹ️ Mazot Tankı 1 kapısı 1 saatten fazla kapalı kaldı. Alarm otomatik olarak KURULDU.", camera_name="tapo")
                        print("Mazot Tankı 1 kapısı 1 saat kapalı kaldı, alarm otomatik kuruldu.")
                        sensor_polling_loop.kapali_baslangic1 = None
                        sensor_polling_loop.alarm_warning_sent1 = False
                else:
                    sensor_polling_loop.kapali_baslangic1 = None
                    sensor_polling_loop.alarm_warning_sent1 = False

            # Mazot Tankı 2 için otomatik kurulum ve uyarı
            if not sistem_kurulu2 and not otomatik_alarm_kapali:
                # Mazot Tankı 2 için sayaçlar ve otomatik kurulum
                # Kapı 2 kapalıysa
                if pin_degeri2 == 0:
                    if sensor_polling_loop.kapali_baslangic2 is None:
                        sensor_polling_loop.kapali_baslangic2 = now
                        sensor_polling_loop.alarm_warning_sent2 = False
                    elapsed2 = now - sensor_polling_loop.kapali_baslangic2 if sensor_polling_loop.kapali_baslangic2 else 0
                    if elapsed2 > 3300 and not sensor_polling_loop.alarm_warning_sent2:
                        send_telegram_notification("⏰ Mazot Tankı 2 kapısı 55 dakikadır kapalı. 5 dakika sonra alarm otomatik olarak kurulacak!", camera_name="tapo2")
                        sensor_polling_loop.alarm_warning_sent2 = True
                    if elapsed2 > 3600:
                        sistem_kurulu2 = True
                        alarm2_tetiklendi_mi = False
                        save_system_state()
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU2", retain=True)
                        send_telegram_notification("ℹ️ Mazot Tankı 2 kapısı 1 saatten fazla kapalı kaldı. Alarm otomatik olarak KURULDU.", camera_name="tapo2")
                        print("Mazot Tankı 2 kapısı 1 saat kapalı kaldı, alarm otomatik kuruldu.")
                        sensor_polling_loop.kapali_baslangic2 = None
                        sensor_polling_loop.alarm_warning_sent2 = False
                else:
                    sensor_polling_loop.kapali_baslangic2 = None
                    sensor_polling_loop.alarm_warning_sent2 = False

            # Kapı durumu değişimini algıla (sessiz bildirim)
            if pin_degeri1 != last_pin_degeri1:
                if not sistem_kurulu1:
                    if pin_degeri1 == 1:
                        send_telegram_silent_photo("🚪 Mazot Tankı 1 kapısı açıldı (alarm devre dışı).", camera_name="tapo")
                    else:
                        send_telegram_silent_photo("🚪 Mazot Tankı 1 kapısı kapandı (alarm devre dışı).", camera_name="tapo")
                last_pin_degeri1 = pin_degeri1

            if pin_degeri2 != last_pin_degeri2:
                if not sistem_kurulu2:
                    if pin_degeri2 == 1:
                        send_telegram_silent_photo("🚪 Mazot Tankı 2 kapısı açıldı (alarm devre dışı).", camera_name="tapo2")
                    else:
                        send_telegram_silent_photo("🚪 Mazot Tankı 2 kapısı kapandı (alarm devre dışı).", camera_name="tapo2")
                last_pin_degeri2 = pin_degeri2

            # --- Alarm tetikleme ve tekrar bildirimi ---
            if sistem_kurulu1:
                # Mazot Tankı 1 alarmı
                if pin_degeri1 == 1 or alarm1_tetiklendi_mi:
                    if not alarm1_tetiklendi_mi:
                        alarm1_tetiklendi_mi = True
                        alarm1_last_sent = now
                        print("ALARM1! Sistem kurulu iken Mazot Tankı 1 kapısı açıldı!")
                        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_ACIK)
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "ALARM1_CALIYOR", retain=True)
                        send_telegram_notification("🚨🚨🚨 ALARM1! 🚨🚨🚨\nMAZOT TANKI 1 KAPISI ZORLA AÇILDI!\nLütfen hemen müdahale edin!", camera_name="tapo")
                    elif now - alarm1_last_sent > alarm_repeat_time:
                        alarm1_last_sent = now
                        if pin_degeri1 == 1:
                            send_telegram_notification("🚨🚨🚨 ALARM1 DEVAM EDİYOR! 🚨🚨🚨\nMazot Tankı 1 kapısı HALA AÇIK! Lütfen hemen müdahale edin!", camera_name="tapo")
                        else:
                            send_telegram_notification("🚨🚨🚨 ALARM1 DEVAM EDİYOR! 🚨🚨🚨\nKapı kapandı ancak alarm durumu siz devre dışı bırakana kadar devam edecek!", camera_name="tapo")
                        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_ACIK)

            if sistem_kurulu2:
                # Mazot Tankı 2 alarmı
                if pin_degeri2 == 1 or alarm2_tetiklendi_mi:
                    if not alarm2_tetiklendi_mi:
                        alarm2_tetiklendi_mi = True
                        alarm2_last_sent = now
                        print("ALARM2! Sistem kurulu iken Mazot Tankı 2 kapısı açıldı!")
                        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_ACIK)
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "ALARM2_CALIYOR", retain=True)
                        send_telegram_notification("🚨🚨🚨 ALARM2! 🚨🚨🚨\nMAZOT TANKI 2 KAPISI ZORLA AÇILDI!\nLütfen hemen müdahale edin!", camera_name="tapo2")
                    elif now - alarm2_last_sent > alarm_repeat_time:
                        alarm2_last_sent = now
                        if pin_degeri2 == 1:
                            send_telegram_notification("🚨🚨🚨 ALARM2 DEVAM EDİYOR! 🚨🚨🚨\nMazot Tankı 2 kapısı HALA AÇIK! Lütfen hemen müdahale edin!", camera_name="tapo2")
                        else:
                            send_telegram_notification("🚨🚨🚨 ALARM2 DEVAM EDİYOR! 🚨🚨🚨\nKapı kapandı ancak alarm durumu siz devre dışı bırakana kadar devam edecek!", camera_name="tapo2")
                        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_ACIK)

            # Sistem devre dışı bırakıldıysa alarmı ve röleyi kapat
            if not sistem_kurulu1 and not sistem_kurulu2:
                if alarm1_tetiklendi_mi or alarm2_tetiklendi_mi:
                    alarm1_tetiklendi_mi = False
                    alarm2_tetiklendi_mi = False
                    lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_KAPALI)
                    if mqtt_client:
                        mqtt_client.publish(MQTT_DURUM_TOPIC, "DEVRE_DISI", retain=True)
                    send_telegram_notification("✅ Alarm devre dışı bırakıldı, sistem kapandı.")
            time.sleep(0.1)
        except Exception as e:
            print(f"Sensör okuma döngüsünde hata: {e}")
            time.sleep(1)

def on_connect(client, userdata, flags, rc):
    """MQTT broker'a bağlanınca çalışır."""
    if rc == 0:
        print("MQTT Broker'a başarıyla bağlanıldı.")
        client.publish(MQTT_DURUM_TOPIC, "DEVRE_DISI", retain=True)
    else:
        print(f"MQTT bağlantı hatası! Kod: {rc}")

# --- TELEGRAM KOMUTLARI ---
async def aktifet1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/aktifet1 komutunu işler."""
    global sistem_kurulu1, alarm1_tetiklendi_mi
    sensor_polling_loop.kapali_baslangic1 = None
    sensor_polling_loop.alarm_warning_sent1 = False

    if not sistem_kurulu1:
        sistem_kurulu1 = True
        alarm1_tetiklendi_mi = False
        save_system_state()
        print("Mazot Tankı 1 '/aktifet1' komutu ile kuruldu (ARMED).")
        if mqtt_client:
            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU1", retain=True)
        await update.message.reply_text("✅ Mazot Tankı 1 için sistem kuruldu.")
    else:
        await update.message.reply_text("ℹ️ Mazot Tankı 1 zaten kurulu.")

async def deaktifet1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deaktifet1 komutunu işler ve kimin yaptığını bildirir."""
    global sistem_kurulu1, alarm1_tetiklendi_mi
    sensor_polling_loop.kapali_baslangic1 = None
    sensor_polling_loop.alarm_warning_sent1 = False

    user = update.message.from_user
    user_info = user.first_name
    if user.last_name:
        user_info += f" {user.last_name}"

    if sistem_kurulu1:
        sistem_kurulu1 = False
        alarm1_tetiklendi_mi = False
        save_system_state()
        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_KAPALI)
        message = f"❌ Mazot Tankı 1 için sistem, **{user_info}** tarafından devre dışı bırakıldı."
        print(f"Mazot Tankı 1, kullanıcı '{user_info}' (ID: {user.id}) tarafından devre dışı bırakıldı.")
        await update.message.reply_text(message, parse_mode='Markdown')
        if mqtt_client:
            mqtt_client.publish(MQTT_DURUM_TOPIC, "DEVRE_DISI1", retain=True)
    else:
        await update.message.reply_text("ℹ️ Mazot Tankı 1 zaten devre dışı.")

async def aktifet2_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/aktifet2 komutunu işler."""
    global sistem_kurulu2, alarm2_tetiklendi_mi
    sensor_polling_loop.kapali_baslangic2 = None
    sensor_polling_loop.alarm_warning_sent2 = False

    if not sistem_kurulu2:
        sistem_kurulu2 = True
        alarm2_tetiklendi_mi = False
        save_system_state()
        print("Mazot Tankı 2 '/aktifet2' komutu ile kuruldu (ARMED).")
        if mqtt_client:
            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU2", retain=True)
        await update.message.reply_text("✅ Mazot Tankı 2 için sistem kuruldu.")
    else:
        await update.message.reply_text("ℹ️ Mazot Tankı 2 zaten kurulu.")

async def deaktifet2_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deaktifet2 komutunu işler ve kimin yaptığını bildirir."""
    global sistem_kurulu2, alarm2_tetiklendi_mi
    sensor_polling_loop.kapali_baslangic2 = None
    sensor_polling_loop.alarm_warning_sent2 = False

    user = update.message.from_user
    user_info = user.first_name
    if user.last_name:
        user_info += f" {user.last_name}"

    if sistem_kurulu2:
        sistem_kurulu2 = False
        alarm2_tetiklendi_mi = False
        save_system_state()
        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_KAPALI)
        message = f"❌ Mazot Tankı 2 için sistem, **{user_info}** tarafından devre dışı bırakıldı."
        print(f"Mazot Tankı 2, kullanıcı '{user_info}' (ID: {user.id}) tarafından devre dışı bırakıldı.")
        await update.message.reply_text(message, parse_mode='Markdown')
        if mqtt_client:
            mqtt_client.publish(MQTT_DURUM_TOPIC, "DEVRE_DISI2", retain=True)
    else:
        await update.message.reply_text("ℹ️ Mazot Tankı 2 zaten devre dışı.")

async def otomatikalarmkapat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global otomatik_alarm_kapali
    otomatik_alarm_kapali = True
    save_system_state()
    await update.message.reply_text("✅ Otomatik alarm kurulumları saat 18:30'a kadar devre dışı bırakıldı.")

def otomatik_alarm_reset_gorevi():
    global otomatik_alarm_kapali, sistem_kurulu1, sistem_kurulu2, gpio_handle, mqtt_client
    otomatik_kurulum_baslangic = None
    
    while True:
        now = time.localtime()
        current_time = time.time()
        
        # 18:30'da otomatik alarmları tekrar aktif et
        if otomatik_alarm_kapali and (now.tm_hour > 18 or (now.tm_hour == 18 and now.tm_min >= 30)):
            otomatik_alarm_kapali = False
            save_system_state()
            otomatik_kurulum_baslangic = current_time
            send_telegram_notification("ℹ️ Otomatik alarm kurulumları tekrar aktif edildi. 5 dakika sonra kapalı kapılar varsa alarmlar otomatik kurulacak!")
        
        # 5 dakika sonra alarmları kur (30 saniye uyarısı kaldırıldı)
        if (otomatik_kurulum_baslangic is not None and 
            not otomatik_alarm_kapali and 
            current_time - otomatik_kurulum_baslangic >= 300):  # 5 dakika = 300 saniye
            
            kurulum_yapildi = False
            
            # Tank 1 kontrolü
            if not sistem_kurulu1 and gpio_handle is not None:
                try:
                    pin_degeri1 = lgpio.gpio_read(gpio_handle, KAPI1_SENSOR_PIN)
                    if pin_degeri1 == 0:  # Kapı kapalıysa
                        sistem_kurulu1 = True
                        kurulum_yapildi = True
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU1", retain=True)
                        send_telegram_notification("🔒 Mazot Tankı 1 otomatik alarm süresi doldu - Alarm KURULDU!", camera_name="tapo")
                        print("Mazot Tankı 1 otomatik alarm süresi sonunda kuruldu.")
                    else:
                        send_telegram_notification("⚠️ Mazot Tankı 1 kapısı açık olduğu için alarm kurulamadı.", camera_name="tapo")
                except Exception as e:
                    print(f"Tank 1 otomatik kurulum hatası: {e}")
            
            # Tank 2 kontrolü
            if not sistem_kurulu2 and gpio_handle is not None:
                try:
                    pin_degeri2 = lgpio.gpio_read(gpio_handle, KAPI2_SENSOR_PIN)
                    if pin_degeri2 == 0:  # Kapı kapalıysa
                        sistem_kurulu2 = True
                        kurulum_yapildi = True
                        if mqtt_client:
                            mqtt_client.publish(MQTT_DURUM_TOPIC, "KURULU2", retain=True)
                        send_telegram_notification("🔒 Mazot Tankı 2 otomatik alarm süresi doldu - Alarm KURULDU!", camera_name="tapo2")
                        print("Mazot Tankı 2 otomatik alarm süresi sonunda kuruldu.")
                    else:
                        send_telegram_notification("⚠️ Mazot Tankı 2 kapısı açık olduğu için alarm kurulamadı.", camera_name="tapo2")
                except Exception as e:
                    print(f"Tank 2 otomatik kurulum hatası: {e}")
            
            # State kaydet ve süreç bitir
            if kurulum_yapildi:
                save_system_state()
            
            otomatik_kurulum_baslangic = None
        
        time.sleep(60)

# --- ANA PROGRAM ---
def main():
    global gpio_handle, mqtt_client, sistem_kurulu1, sistem_kurulu2
    stop_event = threading.Event()
    sensor_thread = None
    heartbeat_thread = None

    try:
        load_system_state()

        # GPIO Kurulumu
        gpio_handle = lgpio.gpiochip_open(GPIO_CHIP)
        lgpio.gpio_claim_output(gpio_handle, ALARM_ROLE_PIN)
        lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_KAPALI)
        flags = lgpio.SET_PULL_UP
        lgpio.gpio_claim_input(gpio_handle, KAPI1_SENSOR_PIN, flags)
        lgpio.gpio_claim_input(gpio_handle, KAPI2_SENSOR_PIN, flags)
        print("GPIO kurulumu tamamlandı.")

        # Kapıların anlık durumu
        try:
            pin_degeri1 = lgpio.gpio_read(gpio_handle, KAPI1_SENSOR_PIN)
            pin_degeri2 = lgpio.gpio_read(gpio_handle, KAPI2_SENSOR_PIN)
            kapi_durum1 = "Kapalı" if pin_degeri1 == 0 else "Açık"
            kapi_durum2 = "Kapalı" if pin_degeri2 == 0 else "Açık"
        except Exception:
            kapi_durum1 = "Bilinmiyor"
            kapi_durum2 = "Bilinmiyor"

        alarm_durum1 = "KURULU" if sistem_kurulu1 else "DEVRE DIŞI"
        alarm_durum2 = "KURULU" if sistem_kurulu2 else "DEVRE DIŞI"

        mesaj = ""
        if os.path.exists(CLEAN_SHUTDOWN_FLAG):
            mesaj = f"✅ Sistem normal şekilde başlatıldı.\n\n🔒 Mazot Tankı 1 alarm durumu: {alarm_durum1}\n🚪 Mazot Tankı 1 kapı durumu: {kapi_durum1}\n🔒 Mazot Tankı 2 alarm durumu: {alarm_durum2}\n🚪 Mazot Tankı 2 kapı durumu: {kapi_durum2}"
            send_telegram_notification(mesaj)
            os.remove(CLEAN_SHUTDOWN_FLAG)
        else:
            mesaj = f"⚠️ DİKKAT: Sistem beklenmedik bir kesinti sonrası yeniden başlatıldı!\n\n🔒 Mazot Tankı 1 alarm durumu: {alarm_durum1}\n🚪 Mazot Tankı 1 kapı durumu: {kapi_durum1}\n🔒 Mazot Tankı 2 alarm durumu: {alarm_durum2}\n🚪 Mazot Tankı 2 kapı durumu: {kapi_durum2}"
            send_telegram_notification(mesaj)
            send_heartbeat()

        print("Telegram Bot dinleyicisi başlatılıyor...")
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CommandHandler("aktifet1", aktifet1_command))
        application.add_handler(CommandHandler("deaktifet1", deaktifet1_command))
        application.add_handler(CommandHandler("aktifet2", aktifet2_command))
        application.add_handler(CommandHandler("deaktifet2", deaktifet2_command))
        application.add_handler(CommandHandler("otomatikalarmkapat", otomatikalarmkapat_command))

        # Otomatik alarm reset görevini başlat
        otomatik_alarm_thread = threading.Thread(target=otomatik_alarm_reset_gorevi)
        otomatik_alarm_thread.daemon = True
        otomatik_alarm_thread.start()

        sensor_thread = threading.Thread(target=sensor_polling_loop, args=(stop_event,))
        heartbeat_thread = threading.Thread(target=heartbeat_loop, args=(stop_event,))
        sensor_thread.start()
        heartbeat_thread.start()

        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "SecurityControllerPi5")
        mqtt_client.on_connect = on_connect
        mqtt_client.connect(MQTT_BROKER_IP, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print("MQTT istemcisi arka planda başlatıldı.")

        application.run_polling()

    finally:
        print("\nProgram sonlandırılıyor...")
        save_system_state()
        with open(CLEAN_SHUTDOWN_FLAG, "w") as f:
            f.write("shutdown")
        stop_event.set()
        if sensor_thread: sensor_thread.join()
        if heartbeat_thread: heartbeat_thread.join()
        if mqtt_client: mqtt_client.loop_stop()
        if gpio_handle:
            lgpio.gpio_write(gpio_handle, ALARM_ROLE_PIN, ROLE_KAPALI)
            lgpio.gpiochip_close(gpio_handle)
        print("Tüm kaynaklar temizlendi. Güvenli çıkış yapıldı.")

if __name__ == "__main__":
    main()
