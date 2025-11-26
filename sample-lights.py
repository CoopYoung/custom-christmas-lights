import time
from rpi_ws281x import PixelStrip, Color
LED_COUNT = 1  # Test with first LED
LED_PIN = 18
strip = PixelStrip(LED_COUNT, LED_PIN)
strip.begin()
strip.setPixelColor(0, Color(255, 0, 0))  # Set to red
strip.show()
print("LED should be red if working.")
time.sleep(10)  # Hold for inspection
