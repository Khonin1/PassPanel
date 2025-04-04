#!/usr/bin/env python3

import RPi.GPIO as GPIO
import serial
import csv
import os
import time

RS485_ENABLE_PIN = 4  # Пин для управления передачей RS485
CSV_FILE = "data_log.csv"  # Файл для хранения данных

GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_ENABLE_PIN, GPIO.OUT)
GPIO.output(RS485_ENABLE_PIN, GPIO.LOW)  # Режим приема

ser = serial.Serial("/dev/ttyS0", 9600, timeout=1)  # Открываем порт

# Функция загрузки данных из CSV
def load_csv_data():
    if not os.path.exists(CSV_FILE):
        return set()  # Если файла нет, возвращаем пустое множество

    with open(CSV_FILE, newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        return {row[0] for row in reader}  # Сохраняем все полученные данные в множество

# Функция записи новых данных в CSV
def save_to_csv(data):
    with open(CSV_FILE, "a", newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([data])

# Загружаем старые данные
known_data = load_csv_data()

print("⏳ Ожидание данных с RS485...")

while True:
    try:
        received_data = ser.read(ser.in_waiting or 1)  # Читаем данные с порта
        if received_data:
            hex_data = received_data.hex()  # Переводим в HEX строку
            print(f"📥 Получено: {hex_data}")

            # Проверяем в базе
            if hex_data in known_data:
                print("✅ Данные уже есть в базе.")
            else:
                print("🆕 Новые данные! Добавляем в базу...")
                save_to_csv(hex_data)
                known_data.add(hex_data)  # Добавляем в список известных

        time.sleep(0.1)  # Немного ждем, чтобы не грузить процессор

    except serial.SerialException as e:
        print(f"❌ Ошибка работы с последовательным портом: {e}")
        time.sleep(1)  # Ждем 1 сек и пробуем снова
    except KeyboardInterrupt:
        print("\n🚪 Завершение работы программы...")
        GPIO.cleanup()  # Освобождаем GPIO
        ser.close()
        break  # Выход из цикла, если нажали Ctrl+C
    
