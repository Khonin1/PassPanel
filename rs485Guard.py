#!/usr/bin/env python3
import lgpio
import serial
import csv
import os
import time

RS485_ENABLE_PIN = 4  # BCM-пин для RS485 DE
CSV_FILE = "data_log.csv"  # Файл для хранения данных

# Открываем GPIO-чип (обычно 0 на Raspberry Pi)
h = lgpio.gpiochip_open(0)

# Захватываем пин как выход
lgpio.gpio_claim_output(h, RS485_ENABLE_PIN)

# Устанавливаем LOW для режима приёма
lgpio.gpio_write(h, RS485_ENABLE_PIN, 0)

# Открываем последовательный порт
ser = serial.Serial("/dev/ttyS0", 9600, timeout=1)

# Функция загрузки данных из CSV
def load_csv_data():
    if not os.path.exists(CSV_FILE):
        return set()
    with open(CSV_FILE, newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        return {row[0] for row in reader}

# Функция записи новых данных в CSV
def save_to_csv(data):
    with open(CSV_FILE, "a", newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([data])

# Загружаем старые данные
known_data = load_csv_data()

print("⏳ Ожидание данных с RS485...")

try:
    while True:
        try:
            received_data = ser.read(ser.in_waiting or 1)
            if received_data:
                hex_data = received_data.hex()
                print(f"📥 Получено: {hex_data}")

                if hex_data in known_data:
                    print("✅ Данные уже есть в базе.")
                else:
                    print("🆕 Новые данные! Добавляем в базу...")
                    save_to_csv(hex_data)
                    known_data.add(hex_data)

            time.sleep(0.1)

        except serial.SerialException as e:
            print(f"❌ Ошибка работы с последовательным портом: {e}")
            time.sleep(1)

except KeyboardInterrupt:
    print("\n🚪 Завершение работы программы...")
    ser.close()
    lgpio.gpiochip_close(h)  # Освобождаем GPIO

