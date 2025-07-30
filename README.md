---

# Raspberry Pi 5 & Google Coral Tabanlı Gelişmiş Güvenlik Sistemi

Bu proje, bir **Raspberry Pi 5**'in işlem gücünü bir **Google Coral TPU** ile birleştirerek, nesne tanıma tabanlı **Frigate NVR** üzerinden yıldırım hızında görüntü işleme yeteneğine sahip, son derece gelişmiş ve kaynak-verimli bir güvenlik çözümüdür. Sistem, manyetik kontak sensörleri kullanarak iki ayrı bölgeyi izler ve **Telegram Bot** aracılığıyla tamamen uzaktan kontrol edilebilir.

| Frigate Arayüzü & Yapay Zeka Tespiti                                   | Telegram Üzerinden Kontrol ve Bildirimler                                   |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| ![Frigate Events Arayüzü](https://raw.githubusercontent.com/MehmetEmreee/Guvenlik-Sistemi/main/pictures/1.jpeg)   | ![Telegram Bildirimleri](https://raw.githubusercontent.com/MehmetEmreee/Guvenlik-Sistemi/main/pictures/3.jpeg)  |
| **Canlı Kamera Görüntüleri**                                              | **Otomatik ve Anlık Olay Bildirimleri**                                         |
| ![Frigate Canlı İzleme](https://raw.githubusercontent.com/MehmetEmreee/Guvenlik-Sistemi/main/pictures/2.jpeg)   | ![Telegram Komutları](https://raw.githubusercontent.com/MehmetEmreee/Guvenlik-Sistemi/main/pictures/4.jpeg)   |
*Görsel 1: Frigate'in nesneleri (Person, Car) etiketlere göre sınıflandırması. Görsel 2: Çoklu kamera akışının canlı izlenmesi. Görsel 3: Kapı durumu ve sistem başlangıcı gibi olayların anlık bildirimleri. Görsel 4: Telegram komutları ile sistemin anlık kontrolü.*

---

## 🌟 Temel Özellikler

Bu script, basit bir GPIO kontrolünden çok daha fazlasını sunar. Güvenilirlik, hız ve kararlılık ön planda tutularak tasarlanmıştır.

*   **🚀 Yüksek Hızlı Görüntü İşleme & Frigate Entegrasyonu:**
    *   Bir alarm tetiklendiğinde, sistem anında Frigate NVR ile iletişime geçer.
    *   **Raspberry Pi 5 ve Google Coral TPU'nun gücü sayesinde**, nesne tespiti (örneğin, bir insanın kapıyı açması) neredeyse **anlık** olarak yapılır ve yanlış alarmlar en aza indirilir.
    *   Alarm anına ait en net kamera görüntüsü, Telegram bildirimi ile saniyeler içinde size ulaşır.

*   **📡 İnternet Kotası Dostu Raporlama (Crontab ile):**
    *   Sistem, **Turkcell Superbox** gibi kısıtlı veya kotalı internet bağlantıları düşünülerek tasarlanmıştır.
    *   Gün içinde alarm durumu yaratmayan, ancak kaydedilmesi istenen olaylar (örneğin, alana giren araçların tespiti) Frigate tarafından işlenir.
    *   Ancak bu olayların bildirimleri, internet trafiğinin yoğun olmadığı ve tehlikenin az olduğu gece saatlerinde, `crontab` ile zamanlanmış bir görev tarafından toplu olarak Telegram'a gönderilir.
    *   Bu yaklaşım, gün içindeki **değerli internet kotasını kritik alarm bildirimleri için korur.**

*   **🛡️ Çift Bölgeli Sensör Takibi:** İki ayrı sensörü bağımsız olarak izler ve her biri için ayrı ayrı alarm kurma/kapatma imkanı sunar.

*   **🤖 Tam Telegram Entegrasyonu:**
    *   `/aktifet` & `/deaktifet` komutları ile sistemi uzaktan kurun ve devre dışı bırakın.
    *   Sistemi devre dışı bırakan kullanıcının adını bildirerek yetkisiz kullanımı takip edin.

*   **❤️ Healthchecks.io Entegrasyonu:**
    *   Sistemin "hayatta" olduğunu periyodik olarak Healthchecks.io'ya bildirir (Heartbeat). Eğer ana script çökerse veya Raspberry Pi kapanırsa, anında uyarı alırsınız.

*   **🧠 Akıllı Durum Yönetimi:**
    *   **Kalıcı Durum Kaydı:** Sistemin kurulu olup olmadığı bilgisini dosyaya kaydeder. Elektrik kesintisi veya yeniden başlatma sonrası sistem kaldığı yerden devam eder.
    *   **Çökme ve Yeniden Başlatma Tespiti:** Sistemin normal bir şekilde mi, yoksa bir çökme sonrası mı yeniden başladığını anlar ve başlangıçta buna göre farklı bir bildirim gönderir.

*   **⚙️ Sağlam ve Kararlı Çalışma:**
    *   **Multi-Threading:** Tüm işlemler (sensör okuma, Telegram dinleme, Heartbeat) ana programı bloklamayan ayrı thread'lerde çalışır.
    *   **lgpio Kütüphanesi:** Raspberry Pi 5 ve modern Linux çekirdekleri için en güncel ve kararlı GPIO kütüphanesini kullanır.

*   **🏡 MQTT Entegrasyonu:**
    *   Sistemin durumunu (KURULU, DEVRE DIŞI, ALARM) bir MQTT broker'a yayınlar. Bu sayede Home Assistant gibi otomasyon platformlarına kolayca entegre edilebilir.

---

## 🛠️ Donanım Listesi ve Kurulum

Bu sistemde kullanılan donanımlar, yüksek performans ve güvenilirlik için özenle seçilmiştir.

*   **Ana İşlem Birimi:** Raspberry Pi 5 (8 GB RAM)
*   **Depolama:** M.2 SSD (512 GB) - *Yüksek hızlı veri kaydı ve Frigate klipleri için.*
*   **Soğutma:** Raspberry Pi 5 Aktif Soğutucu (Resmi Çift Fanlı)
*   **İnternet Bağlantısı:** Turkcell Superbox (veya benzeri mobil/kotalı hat)
*   **Sensörler:** 2 x Metal Manyetik Kontak Sensörü
*   **Alarm Çıkışı:** 1 x Motorlu Siren
*   **Kontrol Ünitesi:** 1 x Çift Kanallı GPIO Röle Modülü

#### Kurulum Adımları

1.  **Kodu İndirin:**
    ```bash
    git clone https://github.com/MehmetEmreee/Guvenlik-Sistemi.git
    cd Guvenlik-Sistemi
    ```2.  **Gerekli Kütüphaneleri Yükleyin:**
    ```bash
    sudo apt-get update && sudo apt-get install python3-pip -y
    pip install -r requirements.txt
    ```
3.  **Yapılandırma Dosyasını Oluşturun:**
    Örnek dosyayı kopyalayarak başlayın ve kendi bilgilerinizle düzenleyin.
    ```bash
    cp .env.example .env
    nano .env
    ```

---

## 🚀 Sistemin Servis Olarak Çalıştırılması (Önerilir)

Sistemin Raspberry Pi her açıldığında otomatik olarak başlaması için bir `systemd` servisi oluşturun.

1.  Servis dosyası oluşturun:
    ```bash
    sudo nano /etc/systemd/system/security.service
    ```
2.  Aşağıdaki içeriği yapıştırın (`User` ve `WorkingDirectory` yollarını kendinize göre düzenleyin):
    ```ini
    [Unit]
    Description=Guvenlik Sistemi Kontrolcusu
    After=network.target

    [Service]
    User=pi
    WorkingDirectory=/home/pi/Guvenlik-Sistemi
    ExecStart=/usr/bin/python3 /home/pi/Guvenlik-Sistemi/security_system.py
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    ```
3.  Servisi etkinleştirin ve başlatın:
    ```bash
    sudo systemctl enable security.service
    sudo systemctl start security.service
    ```

---

## 💬 Kullanım - Telegram Komutları

*   `/aktifet1` - 1. Bölge için alarmı kurar.
*   `/deaktifet1` - 1. Bölge için alarmı devre dışı bırakır.
*   `/aktifet2` - 2. Bölge için alarmı kurar.
*   `/deaktifet2` - 2. Bölge için alarmı devre dışı bırakır.
*   `/otomatikalarmkapat` - Otomatik kurulum özelliğini geçici olarak devre dışı bırakır.

---

## 🤝 Katkıda Bulunma

Katkılarınız projeyi daha da iyi hale getirecektir! Lütfen bir "pull request" açmaktan veya "issue" oluşturmaktan çekinmeyin.

---

## 📄 Lisans

Bu proje, MIT Lisansı altında lisanslanmıştır. Detaylar için `LICENSE` dosyasına bakınız.
