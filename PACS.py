#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import RPi.GPIO as GPIO
import serial
import time
import sqlite3
from gpiozero import Button
import paho.mqtt.client as mqtt

# Создание базы данных
with sqlite3.connect('keys_database.db') as conn:
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
MQTT_TOPIC_ADD_NAME = "door/add_name"



light_status = None # Хранит цвет светодиода
new_name_from_mqtt = None
flag_stop_while = False

# Режим работы двери
mode = True           # True =  Short Режим с автоматический закрытием, Long Режим который открывает на длительное время
bloke_mode = False    # Режим работы True = открытие только из внутри, False = можно  открыть с двух сторон
status_door = False   # True когда  дверь открыта, False если закрыта



# Настройки кнопки
LONG_PRESS_TIME = 1.5          # Время, после которого считается длинное нажатием
DOUBLE_PRESS_INTERVAL = 0.3    # Максимальное время между двумя коротким нажатием
WAIT_FOR_PRESS_TIMEOUT = 0.1   # Максимальное время ожидания первого нажатия


# Контакты Gpio
RS485_ENABLE_PIN = 4  # RSE TX/RX Control Pin RS485
open_pin = 17         # Реле замка
button = Button(22)   # Кнопка открытия
red_light = 27        # Подсветка красная считывателя
green_light = 5       # Подсветка зеленая считывателя
buzzer = 6            # Зумер считывателя

GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_ENABLE_PIN, GPIO.OUT)
GPIO.setup(open_pin, GPIO.OUT)
GPIO.setup(red_light, GPIO.OUT)
GPIO.setup(green_light, GPIO.OUT)
GPIO.setup(buzzer, GPIO.OUT)
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
# Мастер ключ
code_database = {
    b'E\x19`$x\x03\x952\x07\x81\x19B\x03B4`7E\x80': 'Khonin Alexander'}

# Различает нажатия на кнопку
def detect_button_press(read_button_state): 

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

# Проверяет мастер карты из словаря code_database
def check_master_code(data): 
    if data in code_database:
        print("Add new card")
        counter = 0
        while True:
            key_code = receive_data()
            if key_code:
                print(f"New Key code: {key_code}")
                name = input()
                insert_key(key_code, name)
                return None
            else:
                print("Waiting for new card")
                light_rele('buzzer')
                time.sleep(0.2)
                counter += 1
                if counter > 30:
                    return None
    else:
        check_code_in_database(data)
        return None

# Добавляет новую карту в базу
def insert_key(key_code, name):
    print(name)
    with sqlite3.connect('keys_database.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO keys (key_code, name) 
            VALUES (?, ?)
        ''', (key_code, name))
        conn.commit()
    print("New card added")



# Сравнивает получиный код с таблицей SQL
def check_code_in_database(data):
    with sqlite3.connect('keys_database.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM keys WHERE key_code = ?', (data,))
        result = cursor.fetchone()

    if result:
        print(f"Access granted: {result[0]}")
        send_gpio_signal()
        return result[0]
    else:
        print("Access denied")
        return None

    
# Открыть замок
def open_signal():
        global status_door
        print("Open")
        light_rele('green')
        GPIO.output(open_pin, GPIO.HIGH)
        status_door = True
        client.publish(MQTT_TOPIC_STATUS, "opened", retain=True)  # Публикуем статус


# Закрыть замок
def close_signal():
        global status_door
        GPIO.output(open_pin, GPIO.LOW)
        light_rele('red')
        status_door = False
        client.publish(MQTT_TOPIC_STATUS, "closed", retain=True)  # Публикуем статус
        print("Close")


# Логика работы режимов
def send_gpio_signal(duration=3):    
    global status_door
    if mode:
        open_signal()
        time.sleep(duration)
        close_signal()
    else:
        close_signal() if status_door else open_signal()
    
            
# Управляет цветом подсветки
def light_rele(color):
    global light_status
    def red_light_def():
        global light_status
        GPIO.output(green_light, GPIO.HIGH)
        GPIO.output(red_light, GPIO.LOW)
        light_status = 'red'
    def green_light_def():
        global light_status
        GPIO.output(red_light, GPIO.HIGH)
        GPIO.output(green_light, GPIO.LOW)
        light_status = 'green'  
    def yellow_light_def():
        global light_status  
        GPIO.output(red_light, GPIO.LOW)
        GPIO.output(green_light, GPIO.LOW)
        light_status == 'yellow'
    
    if color == 'red':
        red_light_def()
    elif color == 'green':
        green_light_def()
    elif color == 'yellow':
        yellow_light_def()
    elif color == 'yellow_red':
        for _ in range(2):
                red_light_def()
                time.sleep(0.2) 
                yellow_light_def()
                time.sleep(0.2)
        light_rele(light_status)
    elif color == 'buzzer':
        GPIO.output(buzzer, GPIO.LOW)
        red_light_def()
        time.sleep(0.1)
        yellow_light_def()
        time.sleep(0.1)
        green_light_def()
        time.sleep(0.1)
        light_rele(light_status)
        GPIO.output(buzzer, GPIO.HIGH)

# RS485
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
    if rc == 0:
        print("Connected to MQTT Broker")
        client.subscribe([
            (MQTT_TOPIC, 0),
            (MQTT_TOPIC_ADD_NAME, 0),
            (MQTT_TOPIC_STATUS, 0)
        ])
    else:
        print(f"Failed to connect, return code {rc}")


#MQTT Открытие замка, Добавление новой карты
def on_message(client, userdata, msg):
    global bloke_mode
    global mode
    global flag_stop_while
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
    elif msg.topic == MQTT_TOPIC_ADD_NAME: #MQTT Добавление новой карты
        global new_name_from_mqtt
        new_name_from_mqtt = message
        print(f"Name received for new card: {new_name_from_mqtt}")
        sum = 0
        flag_stop_while = True
        while True:
            key_code = receive_data()
            if key_code:
                print(f"New Key code: {key_code}")
                insert_key(key_code, new_name_from_mqtt)
                break
            else:
                print("Waiting for new card")
                light_rele('buzzer')
                sum += 1
            if sum > 30:
                break
        flag_stop_while = False
        
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
        if flag_stop_while == False:
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
                
            elif press == 2:  # Двойное нажатие
                mode = not mode
                client.publish(MQTT_TOPIC_STATUS, "mode_changed", retain=True)
                print("Mode changed:", "Short" if mode else "Long")
                light_rele('yellow_red')
                GPIO.output(open_pin, GPIO.LOW)
                light_rele('red')

        time.sleep(0.1)

except KeyboardInterrupt:
    print("Exiting")

finally:
    client.loop_stop() # Остановка клиента MQTT
    client.disconnect()
    
    ser.close()
    GPIO.cleanup() # Очистка GPIO
    