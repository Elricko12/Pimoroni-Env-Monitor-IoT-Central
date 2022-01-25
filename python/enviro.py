#!/usr/bin/env python3

import time
import colorsys
import os
import sys
import ST7735
try:
    from ltr559 import LTR559
    ltr559 = LTR559()
except ImportError:
    import ltr559

import iotc
from iotc import IOTConnectType, IOTLogLevel
from random import randint

from bme280 import BME280
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError
from enviroplus import gas
from subprocess import PIPE, Popen
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from fonts.ttf import RobotoMedium as UserFont
import logging

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

logging.info("""Displays readings from all of Enviro plus' sensors

Press Ctrl+C to exit!

""")

# BME280 temperature/pressure/humidity sensor
bme280 = BME280()

# PMS5003 particulate sensor
pms5003 = PMS5003()
time.sleep(1.0)

# Create ST7735 LCD display class
st7735 = ST7735.ST7735(
    port=0,
    cs=1,
    dc=9,
    backlight=12,
    rotation=270,
    spi_speed_hz=10000000
)

# Initialize display
st7735.begin()

WIDTH = st7735.width
HEIGHT = st7735.height

# Create a values dict to store the data
variables = ["temperature",
             "pressure",
             "humidity",
             "light",
             "oxidised",
             "reduced",
             "nh3",
             "pm1",
             "pm25",
             "pm10"]

values = {}

units = ["C",
         "hPa",
         "%",
         "Lux",
         "kO",
         "kO",
         "kO",
         "ug/m3",
         "ug/m3",
         "ug/m3"]


def save_data(idx, data):
    variable = variables[idx]
    # Maintain length of list
    values[variable] = values[variable][1:] + [data]
    unit = units[idx]
    message = "{}: {:.1f} {}".format(variable[:4], data, unit)
    logging.info(message)

# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    process = Popen(['vcgencmd', 'measure_temp'], stdout=PIPE, universal_newlines=True)
    output, _error = process.communicate()
    return float(output[output.index('=') + 1:output.rindex("'")])

# Tuning factor for compensation. Decrease this number to adjust the
# temperature down, and increase to adjust up
factor = 2.25

cpu_temps = [get_cpu_temperature()] * 5

delay = 0.5  # Debounce the proximity tap
mode = 10    # The starting mode
last_page = 0
light = 1

for v in variables:
    values[v] = [1] * WIDTH

deviceId = "rpzw-p100"
scopeId = "0ne00499281"
deviceKey = "WcpajHwtTQdAlnHqVCqERs01uTz9jK2aWwiNGeUL3YY="

iotc = iotc.Device(scopeId, deviceKey, deviceId, IOTConnectType.IOTC_CONNECT_SYMM_KEY)
iotc.setLogLevel(IOTLogLevel.IOTC_LOGGING_API_ONLY)

gCanSend = False
gCounter = 0

def onconnect(info):
  global gCanSend
  print("- [onconnect] => status:" + str(info.getStatusCode()))
  if info.getStatusCode() == 0:
     if iotc.isConnected():
       gCanSend = True

def onmessagesent(info):
  print("\t- [onmessagesent] => " + str(info.getPayload()))

def oncommand(info):
  print("- [oncommand] => " + info.getTag() + " => " + str(info.getPayload()))

def onsettingsupdated(info):
  print("- [onsettingsupdated] => " + info.getTag() + " => " + info.getPayload())

iotc.on("ConnectionStatus", onconnect)
iotc.on("MessageSent", onmessagesent)
iotc.on("Command", oncommand)
iotc.on("SettingsUpdated", onsettingsupdated)

while True:
    iotc.connect()

    while iotc.isConnected():
      iotc.doNext() # do the async work needed to be done for MQTT
      if gCanSend == True:
        if gCounter % 20 == 0:
          gCounter = 0

          proximity = ltr559.get_proximity()
          # Everything on one screen
          cpu_temp = get_cpu_temperature()
          # Smooth out with some averaging to decrease jitter
          cpu_temps = cpu_temps[1:] + [cpu_temp]
          avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
          raw_temp = bme280.get_temperature()
          raw_data = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
          save_data(0, raw_data)
          raw_data = bme280.get_pressure()
          save_data(1, raw_data)
          raw_data = bme280.get_humidity()
          save_data(2, raw_data)

          if proximity < 10:
                raw_data = ltr559.get_lux()
          else:
                raw_data = 1
          
          save_data(3, raw_data)
          
          gas_data = gas.read_all()

          save_data(4, gas_data.oxidising / 1000)
          save_data(5, gas_data.reducing / 1000)
          save_data(6, gas_data.nh3 / 1000)
          pms_data = None
          try:
              pms_data = pms5003.read()
          except pmsReadTimeoutError:
              logging.warn("Failed to read PMS5003")
          else:
              save_data(7, float(pms_data.pm_ug_per_m3(1.0)))
              save_data(8, float(pms_data.pm_ug_per_m3(2.5)))
              save_data(9, float(pms_data.pm_ug_per_m3(10)))

          print("Sending telemetry..")
          iotc.sendTelemetry("{ \
    \"temperature\": " + str(values[variables[0]][-1]) + ", \
    \"pressure\": " + str(values[variables[1]][-1]) + ", \
    \"humidity\": " + str(values[variables[2]][-1]) + ", \
    \"light\": " + str(values[variables[3]][-1]) + ", \
    \"oxidation\": " + str(values[variables[4]][-1]) + ", \
    \"nh3\": " + str(values[variables[6]][-1]) + ", \
    \"pm1\": " + str(values[variables[7]][-1]) + ", \
    \"pm25\": " + str(values[variables[8]][-1]) + ", \
    \"pm10\": " + str(values[variables[9]][-1]) + ", \
    \"redu\": " + str(values[variables[5]][-1]) + "}")

        gCounter += 1
