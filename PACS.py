#!/usr/bin/env python3
import RPi.GPIO as GPIO
import serial
import time
import sqlite3


conn = sqlite3.connect('keys_database.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS keys (
    key_code BLOB PRIMARY KEY,
    name TEXT
)
''')
conn.commit()
mode = True # Режим работы Значение True замок всегда закрыт и открывается когда приложили карту
            #              Значение False замок остается открытым до еще одного прикладывания карты 
RS485_ENABLE_PIN =  4 # RSE TX/RX Control Pin RS485
open_pin = 17 # Open Rele Pin

GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_ENABLE_PIN,GPIO.OUT)
GPIO.setup(open_pin, GPIO.OUT)
GPIO.output(RS485_ENABLE_PIN,GPIO.LOW)

ser = serial.Serial(
	port='/dev/ttyS0',
	baudrate=9600,
	bytesize=serial.EIGHTBITS,
	parity=serial.PARITY_NONE,
	stopbits=serial.STOPBITS_ONE,
	timeout=1
	)
# data
code_database = { b'E\x19`$x\x03\x952\x07\x81\x19B\x03B4`7E\x80' : 'Khonin Alexander'}


def check_master_code(data): # Проверяет мастер карты из словаря code_database
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
        
        
def insert_key(key_code, name): # Добавляет новую карту в базу
    cursor.execute('''
    INSERT OR REPLACE INTO keys (key_code, name) 
    VALUES (?, ?)
    ''', (key_code, name))
    conn.commit()
    print("New card add")
    return None
    

def check_code_in_database(data): # Сравнивает получиный код с таблицей SQL
    cursor.execute('SELECT name FROM keys WHERE key_code = ?', (data,))
    result = cursor.fetchone()
    
    if result:
        print(f"Access granted: {result[0]}")
        send_gpio_signal()
        return result[0]
    else:
        print("Access denied")
        return None

        
        
def send_gpio_signal(duration=3, mode): # Open/Close реле замка (duration = время на которое открывается замок в режиме mode = False) 
    print("Open")
    GPIO.output(open_pin, GPIO.HIGH)
    time.sleep(duration)
    GPIO.output(open_pin, GPIO.LOW)
    print("Close")
    

def receive_data():
	#GPIO.output(RS485_ENABLE_PIN,GPIO.LOW) # Set LOW to Receive
	if ser.in_waiting > 0:
		print(ser.in_waiting)
		data=ser.read(ser.in_waiting)
		#data=ser.read_until(293) 
		#time.sleep(1)
		#data=ser.readall()
		ser.reset_input_buffer()
		#ser.flushInput()
		#GPIO.output(RS485_ENABLE_PIN,GPIO.HIGH) # Set HIGH to SEND
		return data 
   

try:
    while True:
        response = receive_data()
        if response:
            print(f"Key code: {response}")
            check_master_code(response)
        else:
            print("Waiting for data")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Exiting")

finally:
    ser.close()
    GPIO.cleanup()