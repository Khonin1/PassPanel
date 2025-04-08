#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import RPi.GPIO as GPIO
import serial
import time
import sqlite3
from gpiozero import Button

conn = sqlite3.connect('keys_database.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS keys (
    key_code BLOB PRIMARY KEY,
    name TEXT
)
''')
conn.commit()
# Режим работы двери
mode = True  # Режим работы: True = замок всегда закрыт и открывается когда приложили карту, False замок остается открытым до еще одного прикладывания карты
bloke_mode = False # Режим работы True = открытие только из внутри, False = можно  открыть с двух сторон
status_door = False # True когда  дверь открыта, False если закрыта



# Настройки кнопки
LONG_PRESS_TIME = 1.5       # Время, после которого считается длинное нажатие
DOUBLE_PRESS_INTERVAL = 0.3  # Максимальное время между двумя короткими нажатиями
WAIT_FOR_PRESS_TIMEOUT = 0.1   # Максимальное время ожидания первого нажатия


# Контакты Gpio
RS485_ENABLE_PIN = 4  # RSE TX/RX Control Pin RS485
open_pin = 17  # Реле замка
button = Button(22)  # Кнопка открытия

GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_ENABLE_PIN, GPIO.OUT)
GPIO.setup(open_pin, GPIO.OUT)
GPIO.output(RS485_ENABLE_PIN, GPIO.LOW)

ser = serial.Serial(
    port='/dev/ttyS0',
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1
)
# data
code_database = {
    b'E\x19`$x\x03\x952\x07\x81\x19B\x03B4`7E\x80': 'Khonin Alexander'}


def detect_button_press(read_button_state): # Различает разные нажатия на кнопку

    #  Определяет тип нажатия кнопки:
    #  - 0 — длинное нажатие
    #  - 1 — одиночное нажатие
    #  - 2 — двойное нажатие
    #  - None — нажатия не было в течение времени ожидания

    def wait_for_release(timeout=None):
        start = time.time()
        while read_button_state():
            if timeout and (time.time() - start) > timeout:
                break
            time.sleep(0.01)

    # Ожидаем первое нажатие (но не вечно)
    start_wait = time.time()
    while not read_button_state():
        if time.time() - start_wait > WAIT_FOR_PRESS_TIMEOUT:
            return None  # Нажатия не было
        time.sleep(0.01)

    press_start = time.time()

    # Ждём отпускание или длинное нажатие
    while read_button_state():
        if time.time() - press_start > LONG_PRESS_TIME:
            wait_for_release()
            return 0  # Длинное нажатие
        time.sleep(0.01)

    press_duration = time.time() - press_start
    if press_duration > LONG_PRESS_TIME:
        return 0  # Длинное нажатие (страховка)

    # Ожидаем возможное второе нажатие
    second_press_wait_start = time.time()
    while (time.time() - second_press_wait_start) < DOUBLE_PRESS_INTERVAL:
        if read_button_state():
            wait_for_release()
            return 2  # Двойное нажатие
        time.sleep(0.01)

    return 1  # Одиночное нажатие


def check_master_code(data):  # Проверяет мастер карты из словаря code_database
    if data in code_database:
        print("Add new card")
        while True:
            key_code = receive_data()
            if key_code:
                print(f"New Key code: {key_code}")
                name = input()
                insert_key(key_code, name)
                return None
            else:
                print("Waiting for new card")
                time.sleep(0.5)
    else:
        check_code_in_database(data)
        return None


def insert_key(key_code, name):  # Добавляет новую карту в базу
    cursor.execute('''
    INSERT OR REPLACE INTO keys (key_code, name) 
    VALUES (?, ?)
    ''', (key_code, name))
    conn.commit()
    print("New card add")
    return None


def check_code_in_database(data):  # Сравнивает получиный код с таблицей SQL
    cursor.execute('SELECT name FROM keys WHERE key_code = ?', (data,))
    result = cursor.fetchone()

    if result:
        print(f"Access granted: {result[0]}")
        send_gpio_signal()
        return result[0]
    else:
        print("Access denied")
        return None


# Open/Close реле замка (duration = время на которое открывается замок в режим mode = False)
def send_gpio_signal(duration=3):
    global status_door
    if  mode:
        print("Open")
        GPIO.output(open_pin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(open_pin, GPIO.LOW)
        print("Close")
    else:
        if status_door:
            GPIO.output(open_pin, GPIO.LOW)
            print("Close")
            status_door = False
        else:
            print("Open")
            GPIO.output(open_pin, GPIO.HIGH)
            status_door = True
        


def receive_data():
    # GPIO.output(RS485_ENABLE_PIN,GPIO.LOW) # Set LOW to Receive
    if ser.in_waiting > 0:
        print(ser.in_waiting)
        data = ser.read(ser.in_waiting)
        # data=ser.read_until(293)
        # time.sleep(1)
        # data=ser.readall()
        ser.reset_input_buffer()
        # ser.flushInput()
        # GPIO.output(RS485_ENABLE_PIN,GPIO.HIGH) # Set HIGH to SEND
        return data


try:
    while True:
        response = receive_data()
        if response and bloke_mode == False:
            print(f"Key code: {response}")
            check_master_code(response)
        else:
            print("Waiting for data")
        press = detect_button_press(lambda: button.is_pressed)
        if press == 0:  # Длинное нажатие
            bloke_mode = not bloke_mode
            print("Long press")
            print(bloke_mode)
        elif press == 1:  # Одинарное нажатие
            send_gpio_signal()
            bloke_mode = False # При нажатие bloke_mode выключается
        elif press == 2:  # Двойное нажатие
            mode = not mode
            print("Mode changed:", "Long" if mode else "Short")
        time.sleep(0.1)

except KeyboardInterrupt:
    print("Exiting")

finally:
    ser.close()
    GPIO.cleanup()
    