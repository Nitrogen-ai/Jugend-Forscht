"""LED-Ansteuerung (Beleuchtung fuer Emissionsmessungen) ueber RPi.GPIO PWM an Pin 7
(BOARD-Nummerierung). Portiert aus LambdaSpektrometer/Python_scripts/led.py
(Maurice Kahre, 2021, CC BY 4.0) -- dort eine Endlosschleife mit fixer Helligkeit,
hier eine Klasse mit on()/off()/set_brightness(), die der Flask-Prozess haelt.
"""
import RPi.GPIO as GPIO

PIN = 7


class Led:
    def __init__(self, pin=PIN, brightness=100):
        self.pin = pin
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(self.pin, GPIO.OUT)
        self._pwm = GPIO.PWM(self.pin, 50)
        self._pwm.start(0)
        self._on = False
        self._brightness = max(0, min(100, brightness))

    def set_brightness(self, percent):
        self._brightness = max(0, min(100, percent))
        if self._on:
            self._pwm.ChangeDutyCycle(self._brightness)

    def on(self):
        self._on = True
        self._pwm.ChangeDutyCycle(self._brightness)

    def off(self):
        self._on = False
        self._pwm.ChangeDutyCycle(0)

    @property
    def is_on(self):
        return self._on

    @property
    def brightness(self):
        return self._brightness
