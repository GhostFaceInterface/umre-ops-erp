#!/bin/bash
# Umre Ops - Canlı VPS Akıllı OneDrive Yedekleme Betiği
set -e

# Hata durumunda log yaz
trap 'echo "$(date "+%Y-%m-%d %H:%M:%S") - Hata: Betik beklenmedik bir şekilde sonlandı!" >&2' ERR

# Dizinleri tanımla
BACKUP_DIR="/opt/muhasebe/backups"
LAST_BACKUP_FILE="${BACKUP_DIR}/.last_backup_time"
RCLONE_CONFIG="${BACKUP_DIR}/rclone.conf"

mkdir -p "${BACKUP_DIR}"

# 1. Rclone konfigürasyonunu kontrol et
if [ ! -f "${RCLONE_CONFIG}" ]; then
    echo "$(date "+%Y-%m-%d %H:%M:%S") - Hata: Rclone konfigürasyon dosyası (${RCLONE_CONFIG}) bulunamadı!" >&2
    exit 1
fi

# 2. Aktif backend Docker konteynerini bul
CONTAINER_NAME=$(docker ps -q -f name=backend | head -n 1)

if [ -z "${CONTAINER_NAME}" ]; then
    echo "$(date "+%Y-%m-%d %H:%M:%S") - Hata: Canlı backend konteyneri bulunamadı!" >&2
    exit 1
fi

# 3. Veritabanındaki en son Operational Expense değişiklik tarihini al
# (Sorguyu backend konteyneri içinde çalıştırıp, site adını 'frontend' olarak belirtiyoruz)
LATEST_CHANGE=$(docker exec -i "${CONTAINER_NAME}" bench --site frontend execute 'frappe.db.get_value("Operational Expense", {}, "modified", order_by="modified desc")' 2>/dev/null | tr -d '\r' | xargs)

if [ -z "${LATEST_CHANGE}" ] || [ "${LATEST_CHANGE}" = "None" ]; then
    LATEST_CHANGE="1970-01-01 00:00:00"
fi

# 4. Son başarılı yedekleme tarihini durum dosyasından oku
LAST_BACKUP_TIME="1970-01-01 00:00:00"
if [ -f "${LAST_BACKUP_FILE}" ]; then
    LAST_BACKUP_TIME=$(cat "${LAST_BACKUP_FILE}" | tr -d '\r' | xargs)
fi

# 5. Zaman damgalarını saniye cinsinden karşılaştır
SEC_LATEST=$(date -d "${LATEST_CHANGE}" +%s 2>/dev/null || date -jf "%Y-%m-%d %H:%M:%S" "${LATEST_CHANGE}" +%s 2>/dev/null || echo 0)
if [ "${SEC_LATEST}" -eq 0 ]; then
    SEC_LATEST=$(date -d "${LATEST_CHANGE}" +%s 2>/dev/null || echo 0)
fi

SEC_LAST=$(date -d "${LAST_BACKUP_TIME}" +%s 2>/dev/null || date -jf "%Y-%m-%d %H:%M:%S" "${LAST_BACKUP_TIME}" +%s 2>/dev/null || echo 0)
if [ "${SEC_LAST}" -eq 0 ]; then
    SEC_LAST=$(date -d "${LAST_BACKUP_TIME}" +%s 2>/dev/null || echo 0)
fi

if [ "${SEC_LATEST}" -le "${SEC_LAST}" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Sistemde yeni gider girişi veya değişiklik tespit edilmedi. Yedekleme pas geçiliyor."
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - Yeni değişiklik tespit edildi! (Son Gider Tarihi: ${LATEST_CHANGE}). Yedekleme başlatılıyor..."

# 6. Konteyner içinde yedeklemeyi tetikle (Database ve fiziksel dosyalar)
echo "$(date '+%Y-%m-%d %H:%M:%S') - Konteyner içinde bench yedeklemesi tetikleniyor..."
docker exec -i "${CONTAINER_NAME}" bench --site frontend backup --with-files

# 7. Sıkıştırılmış yedek arşivlerini yerel raw klasörüne kopyala
mkdir -p "${BACKUP_DIR}/raw"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Yedek dosyaları konteynerden host sunucuya kopyalanıyor..."
docker cp "${CONTAINER_NAME}":/home/frappe/frappe-bench/sites/frontend/private/backups/. "${BACKUP_DIR}/raw/"

# 8. Tarih damgalı hedef alt klasörü oluştur
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DEST_SUBDIR="${BACKUP_DIR}/${TIMESTAMP}"
mkdir -p "${DEST_SUBDIR}"

# raw klasöründeki yedekleri buraya taşı
mv "${BACKUP_DIR}/raw"/* "${DEST_SUBDIR}/"
rm -rf "${BACKUP_DIR}/raw"

# 9. Rclone ile OneDrive'a yükle (Artımlı kopyalama - rclone copy)
echo "$(date '+%Y-%m-%d %H:%M:%S') - OneDrive'a yükleniyor (Klasör: Umre_Ops_Backups/${TIMESTAMP})..."
rclone --config "${RCLONE_CONFIG}" copy "${DEST_SUBDIR}" "onedrive:Umre_Ops_Backups/${TIMESTAMP}"

# 10. Son başarılı yedekleme zaman damgasını güncelle
echo "${LATEST_CHANGE}" > "${LAST_BACKUP_FILE}"

# 11. Yerel sunucu temizliği (Disk dolmasını önlemek için 3 günden eski yedek klasörlerini sil)
echo "$(date '+%Y-%m-%d %H:%M:%S') - Yerel diskteki eski yedekler temizleniyor..."
find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime +3 -exec rm -rf {} \;

# 12. OneDrive Yedek Yaşlandırma (OneDrive'daki 7 günden eski yedek klasörlerini sil)
echo "$(date '+%Y-%m-%d %H:%M:%S') - OneDrive üzerindeki 7 günden eski yedekler temizleniyor..."
rclone --config "${RCLONE_CONFIG}" delete "onedrive:Umre_Ops_Backups" --min-age 7d --rmdirs

echo "$(date '+%Y-%m-%d %H:%M:%S') - Akıllı yedekleme ve OneDrive senkronizasyonu başarıyla tamamlandı!"
