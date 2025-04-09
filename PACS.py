#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import RPi.GPIO as GPIO
import serial
import time
import sqlite3
from gpiozero import Button
import paho.mqtt.client as mqtt


conn = sqlite3.connect('keys_database.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS keys (
    key_code BLOB PRIMARY KEY,
    name TEXT
)
''')
conn.commit()
# Настройки MQTT
MQTT_BROKER = "localhost"      # или IP адрес брокера
MQTT_PORT = 1883
MQTT_USERNAME = "admin"
MQTT_PASSWORD = "milk"
# Список топиков на которые надо подписаться
MQTT_TOPIC = "door/control" 
MQTT_TOPIC_STATUS = "door/status"

light_status = None # Хранит цвет светодиода
# Режим работы двери
mode = True # True =  Short Режим с автоматический закрытием, Long Режим который открывает на длительное время
bloke_mode = False # Режим работы True = открытие только из внутри, False = можно  открыть с двух сторон
status_door = False # True когда  дверь открыта, False если закрыта



# Настройки кнопки
LONG_PRESS_TIME = 1.5       # Время, после которого считается длинное нажатие
DOUBLE_PRESS_INTERVAL = 0.3  # Максимальное время между двумя коротким нажатием
WAIT_FOR_PRESS_TIMEOUT = 0.1   # Максимальное время ожидания первого нажатия


# Контакты Gpio
RS485_ENABLE_PIN = 4  # RSE TX/RX Control Pin RS485
open_pin = 17  # Реле замка
button = Button(22)  # Кнопка открытия
red_light = 27 # Подсветка красная
green_light = 5 # Подсветка зеленая

GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_ENABLE_PIN, GPIO.OUT)
GPIO.setup(open_pin, GPIO.OUT)
GPIO.setup(red_light, GPIO.OUT)
GPIO.setup(green_light, GPIO.OUT)
GPIO.output(RS485_ENABLE_PIN, GPIO.LOW)

# Параметры RS458
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
        light_rele('green')
        GPIO.output(open_pin, GPIO.HIGH)
        status_door = True
        client.publish(MQTT_TOPIC_STATUS, "opened", retain=True)  # Публикуем статус
        time.sleep(duration)
        GPIO.output(open_pin, GPIO.LOW)
        light_rele('red')
        status_door = False
        client.publish(MQTT_TOPIC_STATUS, "closed", retain=True)  # Публикуем статус
        print("Close")
    else:
        if status_door:
            GPIO.output(open_pin, GPIO.LOW)
            print("Close")
            status_door = False
            light_rele('red')
            client.publish(MQTT_TOPIC_STATUS, "closed", retain=True)
        else:
            print("Open")
            GPIO.output(open_pin, GPIO.HIGH)
            status_door = True
            light_rele('green')
            client.publish(MQTT_TOPIC_STATUS, "opened", retain=True)
            
            
# Управляет реле для изменение цвета подсветки кнопки и считывателя
def light_rele(color):
    global light_status
    if color == 'red':
        GPIO.output(green_light, GPIO.HIGH)
        GPIO.output(red_light, GPIO.LOW)
        light_status = 'red'
    elif color == 'green':
        GPIO.output(red_light, GPIO.HIGH)
        GPIO.output(green_light, GPIO.LOW)
        light_status = 'green'
    elif color == 'yellow':
        GPIO.output(red_light, GPIO.LOW)
        GPIO.output(green_light, GPIO.LOW)
        light_status == 'yellow'
    elif color == 'yellow_red':
        for _ in range(2):
                GPIO.output(red_light, GPIO.LOW)
                GPIO.output(green_light, GPIO.LOW)
                time.sleep(0.2)
                GPIO.output(green_light, GPIO.HIGH)
                GPIO.output(red_light, GPIO.LOW)
                time.sleep(0.2)
                light_rele(light_status)


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
# MQTT Connect
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT Broker" if rc == 0 else f"Failed to connect, return code {rc}")
    client.subscribe(MQTT_TOPIC)
    
#MQTT Открытие замка
def on_message(client, userdata, msg):
    global bloke_mode
    global mode
    message = msg.payload.decode()
    print(f"MQTT message received: {message}")
    
    if message == "open":
        send_gpio_signal()
        bloke_mode = False  # чтобы не блокировало
    elif message == "Long_mode":
        mode = False
        print("Mode changed via MQTT: Long")
        light_rele('yellow_red')
    elif message == 'Short_mode':
        mode = True
        print("Mode changed via MQTT: Short")
        light_rele('yellow_red')
# Создание MQTT клиента
client = mqtt.Client()
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = lambda client, userdata, rc: print(f"Disconnected with result code {rc}") or client.reconnect()
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()  # Запускаем в фоновом потоке

try:
    while True:
        response = receive_data()
        if response and bloke_mode == False:
            print(f"Key code: {response}")
            check_master_code(response)
        elif bloke_mode == True:
            light_rele('yellow')
            print("Waiting button")
        else:
            print("Waiting for data")
        press = detect_button_press(lambda: button.is_pressed)
        if press == 0:  # Длинное нажатие
            if bloke_mode == False:
                GPIO.output(open_pin, GPIO.LOW)
                light_rele('red')
            bloke_mode = not bloke_mode
            print("Long press")
            print(bloke_mode)
        elif press == 1:  # Одинарное нажатие
            send_gpio_signal()
            bloke_mode = False # При нажатие bloke_mode выключается
        # В обработчике двойного нажатия кнопки (где меняется mode):
        elif press == 2:  # Двойное нажатие
            if mode:
                send_gpio_signal(1)
            else:
                GPIO.output(open_pin, GPIO.LOW)
                light_rele('red')
            mode = not mode
            client.publish(MQTT_TOPIC_STATUS, "mode_changed", retain=True)
            print("Mode changed:", "Short" if mode else "Long")
            light_rele('yellow_red')
        time.sleep(0.1)

except KeyboardInterrupt:
    print("Exiting")

finally:
    client.loop_stop() # Остановка клиента MQTT
    client.disconnect()

    conn.close() # Остановка SQL
    
    ser.close()
    GPIO.cleanup() # Очистка GPIO
    