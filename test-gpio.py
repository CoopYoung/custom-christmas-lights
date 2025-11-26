import RPi.GPIO as GPIO
import time
GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.OUT)
for _ in range(5):
    GPIO.output(18, GPIO.HIGH)
    print("HIGH")
    time.sleep(1)
    GPIO.output(18, GPIO.LOW)
    print("LOW")
    time.sleep(1)
GPIO.cleanup()
