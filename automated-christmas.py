import datetime
import time
import threading
import socket
import json
import random
from rpi_ws281x import PixelStrip, Color
from astral import LocationInfo
from astral.sun import sun
from flask import Flask, request, render_template_string, jsonify
from flask_httpauth import HTTPBasicAuth
from flask_socketio import SocketIO, emit

# LED strip configuration
LED_COUNT = 300      # Number of LED pixels (change this to your setup)
LED_PIN = 18        # GPIO pin connected to the pixels (18 uses PWM)
LED_FREQ_HZ = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA = 10        # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 50  # Set to 0 for darkest and 255 for brightest
LED_INVERT = False    # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

# Location for sunset calculation
location = LocationInfo("Austin", "Texas", "America/Chicago", 30.2672, -97.7431)

# Effect selection (initial; can be changed via web)
SELECTED_EFFECT = 'rainbow'

# Turn-off time (initial; can be changed via web)
TURN_OFF_HOUR = 23
TURN_OFF_MINUTE = 0

# Custom solid color (new feature: RGB for solid effect)
CUSTOM_SOLID_COLOR = (255, 0, 0)  # Default red

# Effect speed multiplier (new feature: adjustable speed for effects, 1.0 = normal)
EFFECT_SPEED = 1.0

# Persistence file (new feature: save/load settings)
CONFIG_FILE = 'led_config.json'

# Load saved config if exists
def load_config():
    global LED_COUNT, LED_BRIGHTNESS, SELECTED_EFFECT, location, TURN_OFF_HOUR, TURN_OFF_MINUTE, CUSTOM_SOLID_COLOR, EFFECT_SPEED
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            LED_COUNT = config.get('led_count', LED_COUNT)
            LED_BRIGHTNESS = config.get('brightness', LED_BRIGHTNESS)
            SELECTED_EFFECT = config.get('effect', SELECTED_EFFECT)
            location = LocationInfo(
                config.get('loc_name', location.name),
                config.get('loc_region', location.region),
                config.get('loc_timezone', location.timezone),
                config.get('loc_lat', location.latitude),
                config.get('loc_lon', location.longitude)
            )
            TURN_OFF_HOUR = config.get('turn_off_hour', TURN_OFF_HOUR)
            TURN_OFF_MINUTE = config.get('turn_off_minute', TURN_OFF_MINUTE)
            CUSTOM_SOLID_COLOR = tuple(config.get('custom_solid_color', CUSTOM_SOLID_COLOR))
            EFFECT_SPEED = config.get('effect_speed', EFFECT_SPEED)
    except FileNotFoundError:
        pass

# Save config
def save_config():
    config = {
        'led_count': LED_COUNT,
        'brightness': LED_BRIGHTNESS,
        'effect': SELECTED_EFFECT,
        'loc_name': location.name,
        'loc_region': location.region,
        'loc_timezone': location.timezone,
        'loc_lat': location.latitude,
        'loc_lon': location.longitude,
        'turn_off_hour': TURN_OFF_HOUR,
        'turn_off_minute': TURN_OFF_MINUTE,
        'custom_solid_color': list(CUSTOM_SOLID_COLOR),
        'effect_speed': EFFECT_SPEED
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

# Create NeoPixel object with appropriate configuration
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

# Flask app for web control
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'  # For SocketIO
socketio = SocketIO(app)
auth = HTTPBasicAuth()

# Helper to get local IP for web access
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"  # Fallback

def get_env(var_name, default=0):
    try:
        value = os.environ.get(var_name)
        if value is None:
            raise EnvironmentError(f"Environment varaible '{var_name}' not found")
        else:
            return value
    except Exception as e:
        print(f"Error: {e}")
        return None
        

users = {
    #get_env(UNAME): get_env(CHRISTMASPASSWORD)  
    "admin": "password123"
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

# Global control variables
manual_off = False
manual_on = False
stop_event = threading.Event()
current_effect_thread = None
current_effect_func = None

# Helper function to set all pixels to a color
def color_wipe(strip, color, wait_ms=50):
    wait_ms /= EFFECT_SPEED  # Adjust for speed
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms / 1000.0)

# Effect: Solid color (uses custom color)
def solid_color(strip, stop_event):
    r, g, b = CUSTOM_SOLID_COLOR
    color_wipe(strip, Color(r, g, b), 10)
    while not stop_event.is_set():
        time.sleep(1)  # Keep lit

# Effect: Color wipe (cycles through colors)
def color_wipe_effect(strip, stop_event):
    while not stop_event.is_set():
        color_wipe(strip, Color(255, 0, 0), 50)  # Red wipe
        if stop_event.is_set(): break
        color_wipe(strip, Color(0, 255, 0), 50)  # Green wipe
        if stop_event.is_set(): break
        color_wipe(strip, Color(0, 0, 255), 50)  # Blue wipe

# Effect: Theater chase
def theater_chase(strip, color, wait_ms=50, iterations=10):
    wait_ms /= EFFECT_SPEED
    for j in range(iterations):
        if stop_event.is_set(): return
        for q in range(3):
            for i in range(0, strip.numPixels(), 3):
                strip.setPixelColor(i + q, color)
            strip.show()
            time.sleep(wait_ms / 1000.0)
            for i in range(0, strip.numPixels(), 3):
                strip.setPixelColor(i + q, 0)

def theater_chase_effect(strip, stop_event):
    while not stop_event.is_set():
        theater_chase(strip, Color(127, 127, 127))  # White
        if stop_event.is_set(): break
        theater_chase(strip, Color(127, 0, 0))      # Red
        if stop_event.is_set(): break
        theater_chase(strip, Color(0, 0, 127))      # Blue

# Effect: Rainbow cycle
def wheel(pos):
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

def rainbow_cycle(strip, wait_ms=20):
    wait_ms /= EFFECT_SPEED
    for j in range(256):
        if stop_event.is_set(): return
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, wheel((i + j) & 255))
        strip.show()
        time.sleep(wait_ms / 1000.0)

def rainbow_effect(strip, stop_event):
    while not stop_event.is_set():
        rainbow_cycle(strip)

def snake_effect(strip, stop_event):
    snake_length = 15  # Initial length
    position = 0  # Starting position
    direction = 1  # 1 = forward, -1 = backward
    food = random.randint(0, strip.numPixels() - 1)
    while not stop_event.is_set():
        # Clear strip
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, Color(0, 0, 0))
        
        # Draw snake with random colors
        for i in range(snake_length):
            strip.setPixelColor(food, Color(255, 0, 0))  # Food is red
            if 0 <= position - i * direction < strip.numPixels():
                r = random.randint(0, 255)
                g = random.randint(0, 255)
                b = random.randint(0, 255)
                strip.setPixelColor(position - i * direction, Color(r, g, b))
            if position == food:
                food = random.randint(0, strip.numPixels() - 1)
                snake_length += 1  # Grow snake
        if snake_length > strip.numPixels() // 2:
            #Burst
            for i in range(strip.numPixels()):
                strip.setPixelColor(i, Color(255, 255, 255))
            snake_length = 15  # Reset length if too long

        
        strip.show()
        
        # Move and bounce
        position += direction
        if position >= strip.numPixels() or position < 0:
            direction *= -1
            position += direction * 2  # Adjust to bounce smoothly
            snake_length = max(1, snake_length + random.choice([-1, 1]))  # Grow/shrink randomly
        
        time.sleep(0.1 / EFFECT_SPEED)  # Speed control

def plague_spread_effect(strip, stop_event):
    mid = strip.numPixels() // 2  # Start in middle
    infected = [mid]  # Initial infected LED
    base_color = Color(random.randint(50, 255), random.randint(0, 100), random.randint(0, 100))  # Random starting color
    
    while not stop_event.is_set():
        # Light infected LEDs with color variations
        for i in infected:
            variation = random.randint(-20, 20)
            r = max(0, min(255, (base_color >> 16) + variation))
            g = max(0, min(255, ((base_color >> 8) & 0xFF) + variation))
            b = max(0, min(255, (base_color & 0xFF) + variation))
            strip.setPixelColor(i, Color(r, g, b))
        strip.show()
        
        # Spread to neighbors
        new_infected = set(infected)
        for pos in infected:
            if pos > 0 and pos - 1 not in infected:
                new_infected.add(pos - 1)
            if pos < strip.numPixels() - 1 and pos + 1 not in infected:
                new_infected.add(pos + 1)
        infected = list(new_infected)
        
        # Reset if fully spread
        if len(infected) == strip.numPixels():
            time.sleep(1 / EFFECT_SPEED)  # Pause at full
            infected = [mid]  # Reset to middle
            base_color = Color(random.randint(50, 255), random.randint(0, 100), random.randint(0, 100))  # New color
        
        time.sleep(0.2 / EFFECT_SPEED)  # Spread speed
        
        # Clear uninfected
        for i in range(strip.numPixels()):
            if i not in infected:
                strip.setPixelColor(i, Color(0, 0, 0))
import colorsys  # Add this import at top if not present

def random_multi_color_effect(strip, stop_event):
    while not stop_event.is_set():
        for i in range(strip.numPixels()):
            # Generate random HSL for varied colors
            h = random.random()  # Hue 0-1
            s = random.uniform(0.5, 1.0)  # Saturation for vibrant colors
            l = random.uniform(0.3, 0.7)  # Lightness for variety
            r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
            strip.setPixelColor(i, Color(r, g, b))
        
        strip.show()
        time.sleep(1 / EFFECT_SPEED)  # Change rate

def twinkling_starfield_effect(strip, stop_event):
    intensities = [0] * strip.numPixels()  # Per-LED brightness
    while not stop_event.is_set():
        for i in range(strip.numPixels()):
            # Randomly adjust intensity
            intensities[i] += random.randint(-20, 20)
            intensities[i] = max(0, min(255, intensities[i]))
            # White-yellow tint
            color = Color(intensities[i], intensities[i], random.randint(200, 255) if random.random() > 0.5 else intensities[i])
            strip.setPixelColor(i, color)
        
        strip.show()
        time.sleep(0.05 / EFFECT_SPEED)  # Fast twinkle

def fire_flicker_effect(strip, stop_event):
    # Base fire colors: reds, oranges, yellows
    fire_colors = [
        Color(255, 69, 0),   # OrangeRed
        Color(255, 140, 0),  # DarkOrange
        Color(255, 165, 0),  # Orange
        Color(255, 215, 0),  # Gold
        Color(255, 0, 0)     # Red
    ]
    intensities = [random.randint(50, 255) for _ in range(strip.numPixels())]  # Initial random intensities
    
    while not stop_event.is_set():
        for i in range(strip.numPixels()):
            # Flicker: random small changes
            intensities[i] += random.randint(-30, 30)
            intensities[i] = max(50, min(255, intensities[i]))  # Clamp for subtle flicker
            
            # Pick a base color and scale with intensity
            base_color = random.choice(fire_colors)
            r = (base_color >> 16) * intensities[i] // 255
            g = ((base_color >> 8) & 0xFF) * intensities[i] // 255
            b = (base_color & 0xFF) * intensities[i] // 255
            strip.setPixelColor(i, Color(r, g, b))
        
        strip.show()
        time.sleep(0.05 / EFFECT_SPEED)  # Fast flicker for realism

def phase_out(strip, stop_event):
    steps = 50
    delay = 50 / EFFECT_SPEED  # Adjust for speed
    for step in range(steps):
        if stop_event.is_set():
            break
        factor = (steps - step) / steps
        for i in range(strip.numPixels()):
            r = int(((strip.getPixelColor(i) >> 16) & 0xFF) * factor)
            g = int(((strip.getPixelColor(i) >> 8) & 0xFF) * factor)
            b = int((strip.getPixelColor(i) & 0xFF) * factor)
            strip.setPixelColor(i, Color(r, g, b))
        strip.show()
        time.sleep(delay / 1000.0)
def michigan(strip, stop_event):
    # Maize and Blue colors
    maize = Color(200, 255, 0)
    blue = Color(7, 23, 242)
    
    # Precompute positions
    evens = list(range(0, strip.numPixels(), 2))
    odds = list(range(1, strip.numPixels(), 2))
    
    iteration = 0
    while not stop_event.is_set():
        # Determine current and target colors for evens/odds
        if iteration % 2 == 0:
            even_color_start = maize
            odd_color_start = blue
            even_color_target = blue
            odd_color_target = maize
        else:
            even_color_start = blue
            odd_color_start = maize
            even_color_target = maize
            odd_color_target = blue
        
        # Fade transition over steps
        fade_steps = 20  # Number of fade frames; increase for slower fade
        for step in range(fade_steps + 1):
            if stop_event.is_set(): return
            
            # Interpolation factor (0 to 1)
            t = step / fade_steps
            
            # Lerp function for color components
            def lerp(start, target, t):
                return int(start + t * (target - start))
            
            # Compute interpolated colors
            even_r = lerp((even_color_start >> 16) & 0xFF, (even_color_target >> 16) & 0xFF, t)
            even_g = lerp((even_color_start >> 8) & 0xFF, (even_color_target >> 8) & 0xFF, t)
            even_b = lerp(even_color_start & 0xFF, even_color_target & 0xFF, t)
            odd_r = lerp((odd_color_start >> 16) & 0xFF, (odd_color_target >> 16) & 0xFF, t)
            odd_g = lerp((odd_color_start >> 8) & 0xFF, (odd_color_target >> 8) & 0xFF, t)
            odd_b = lerp(odd_color_start & 0xFF, odd_color_target & 0xFF, t)
            
            even_color = Color(even_r, even_g, even_b)
            odd_color = Color(odd_r, odd_g, odd_b)
            
            # Set pixels
            for pos in evens:
                strip.setPixelColor(pos, even_color)
            for pos in odds:
                strip.setPixelColor(pos, odd_color)
            
            strip.show()
            time.sleep(0.02 / EFFECT_SPEED)  # Frame delay; adjust for smoothness
        
        # Hold the pattern for a bit before next fade
        time.sleep(1.0 / EFFECT_SPEED)  # Pause duration; adjust as needed
        
        iteration += 1
# Turn off all LEDs
def turn_off(strip):
    color_wipe(strip, Color(0, 0, 0), 10)

# Select the effect function based on name
def get_effect_function(effect_name):
    if effect_name == 'solid':
        return solid_color
    elif effect_name == 'wipe':
        return color_wipe_effect
    elif effect_name == 'chase':
        return theater_chase_effect
    elif effect_name == 'rainbow':
        return rainbow_effect
    elif effect_name == 'snake':
        return snake_effect
    elif effect_name == 'plague':
        return plague_spread_effect
    elif effect_name == 'random_multi':
        return random_multi_color_effect
    elif effect_name == 'twinkle':
        return twinkling_starfield_effect
    elif effect_name == 'fire_flicker':
        return fire_flicker_effect
    elif effect_name == 'phase_out':
        return phase_out
    elif effect_name == 'michigan':
        return michigan
    else:
        raise ValueError("Unknown effect: " + effect_name)

# Stop current effect if running
def stop_current_effect():
    global current_effect_thread
    if current_effect_thread and current_effect_thread.is_alive():
        stop_event.set()
        current_effect_thread.join()

# Start effect
def start_effect():
    global current_effect_thread, current_effect_func
    stop_event.clear()
    current_effect_thread = threading.Thread(target=current_effect_func, args=(strip, stop_event))
    current_effect_thread.start()

# Helper to check if in scheduled time window
def is_in_time_window():
    now = datetime.datetime.now(location.tzinfo)
    s = sun(location.observer, date=now.date(), tzinfo=location.tzinfo)
    sunset = s['sunset']
    turn_on_time = sunset - datetime.timedelta(minutes=30)
    turn_off_time = now.replace(hour=TURN_OFF_HOUR, minute=TURN_OFF_MINUTE, second=0, microsecond=0)
    return turn_on_time <= now < turn_off_time

# Broadcast current state to all clients (updated with new features)
def broadcast_state():
    state = {
        'current_effect': SELECTED_EFFECT,
        'manual_on': manual_on,
        'manual_off': manual_off,
        'brightness': LED_BRIGHTNESS,
        'led_count': LED_COUNT,
        'loc_name': location.name,
        'loc_region': location.region,
        'loc_timezone': location.timezone,
        'loc_lat': location.latitude,
        'loc_lon': location.longitude,
        'turn_off_hour': TURN_OFF_HOUR,
        'turn_off_minute': TURN_OFF_MINUTE,
        'custom_solid_r': CUSTOM_SOLID_COLOR[0],
        'custom_solid_g': CUSTOM_SOLID_COLOR[1],
        'custom_solid_b': CUSTOM_SOLID_COLOR[2],
        'effect_speed': EFFECT_SPEED
    }
    socketio.emit('update_state', state)

# SocketIO events
@socketio.on('connect')
def handle_connect():
    broadcast_state()  # Send current state on connect

# Web endpoints
@app.route('/')
@auth.login_required
def index():
    # Polished HTML dashboard with CSS and JS for real-time and AJAX
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>LED Control Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.4/socket.io.js"></script>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f0f4f8;
                color: #333;
                margin: 0;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }
            .container {
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
                padding: 30px;
                max-width: 500px;
                width: 100%;
            }
            h1 {
                text-align: center;
                color: #2c3e50;
                margin-bottom: 20px;
            }
            .status {
                background: #e8f4fd;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 20px;
            }
            .status p {
                margin: 8px 0;
                font-size: 16px;
            }
            h2 {
                color: #34495e;
                font-size: 18px;
                margin-top: 20px;
                margin-bottom: 10px;
            }
            .controls {
                display: flex;
                justify-content: space-around;
                margin-bottom: 20px;
            }
            button {
                background: #3498db;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                transition: background 0.3s, transform 0.1s;
            }
            button:hover {
                background: #2980b9;
                transform: translateY(-2px);
            }
            button:active {
                transform: translateY(0);
            }
            .effect-buttons {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 10px;
                margin-bottom: 20px;
            }
            .effect-buttons button {
                background: #bdc3c7;
                color: #2c3e50;
            }
            .effect-buttons button:hover {
                background: #95a5a6;
            }
            form {
                display: flex;
                flex-direction: column;
                margin-bottom: 20px;
            }
            input[type="range"], input[type="number"], input[type="text"], input[type="color"], input[type="time"] {
                padding: 10px;
                margin-bottom: 10px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
            }
            input[type="submit"] {
                background: #27ae60;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                transition: background 0.3s;
            }
            input[type="submit"]:hover {
                background: #219d54;
            }
            .slider-value {
                text-align: center;
                font-size: 14px;
                margin-top: -10px;
                margin-bottom: 10px;
            }
            @media (max-width: 400px) {
                .controls {
                    flex-direction: column;
                }
                .controls button {
                    margin-bottom: 10px;
                }
                .effect-buttons {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Young's Christmas Light Control!</h1>
            <div class="status">
                <p id="current_effect">Current Effect: {{ current_effect }}</p>
                <p id="manual_on">Manual On: {{ manual_on }}</p>
                <p id="manual_off">Manual Off: {{ manual_off }}</p>
            </div>
            <h2>Controls</h2>
            <div class="controls">
                <button onclick="callEndpoint('/on')">Turn On</button>
                <button onclick="callEndpoint('/off')">Turn Off</button>
            </div>
            <h2>Select Effect</h2>
            <div class="effect-buttons">
                <button onclick="callEndpoint('/effect/solid')">Solid</button>
                <button onclick="callEndpoint('/effect/wipe')">Wipe</button>
                <button onclick="callEndpoint('/effect/chase')">Chase</button>
                <button onclick="callEndpoint('/effect/rainbow')">Rainbow</button>
                <button onclick="callEndpoint('/effect/snake')">Snake</button>
                <button onclick="callEndpoint('/effect/plague')">Plague Spread</button>
                <button onclick="callEndpoint('/effect/random_multi')">Random Multi-Color</button>
                <button onclick="callEndpoint('/effect/twinkle')">Twinkle Starfield</button>
                <button onclick="callEndpoint('/effect/fire_flicker')">Fire Flicker</button>
                <button onclick="callEndpoint('/effect/phase_out')">Phase Out</button>
                <button onclick="callEndpoint('/effect/michigan')">Michigan</button>
            </div>
            <h2>Custom Solid Color</h2>
            <form id="custom_color_form" onsubmit="submitForm(event, '/custom_color')">
                <input type="color" name="color" value="#ff0000">
                <input type="submit" value="Set Color">
            </form>
            <h2>Effect Speed (0.5-2.0)</h2>
            <form id="effect_speed_form" onsubmit="submitForm(event, '/effect_speed')">
                <input type="range" name="speed" min="0.5" max="2.0" step="0.1" value="1.0" oninput="updateSliderValue(this.value, 'speed_value')">
                <p class="slider-value" id="speed_value">Value: 1.0</p>
                <input type="submit" value="Set">
            </form>
            <h2>Set Brightness (0-255)</h2>
            <form id="brightness_form" onsubmit="submitForm(event, '/brightness')">
                <input type="range" id="brightness_slider" name="level" min="0" max="255" value="{{ brightness }}" oninput="updateSliderValue(this.value, 'brightness_value')">
                <p class="slider-value" id="brightness_value">Value: {{ brightness }}</p>
                <input type="submit" value="Set">
            </form>
            <h2>Set LED Count</h2>
            <form id="led_count_form" onsubmit="submitForm(event, '/led_count')">
                <input type="number" name="count" min="1" value="{{ led_count }}">
                <input type="submit" value="Set">
            </form>
            <h2>Set Turn-Off Time</h2>
            <form id="turn_off_time_form" onsubmit="submitForm(event, '/turn_off_time')">
                <input type="time" name="time" value="23:00">
                <input type="submit" value="Set">
            </form>
            <h2>Set Location</h2>
            <form id="location_form" onsubmit="submitForm(event, '/location')">
                <input type="text" name="name" value="{{ loc_name }}" placeholder="Name">
                <input type="text" name="region" value="{{ loc_region }}" placeholder="Region">
                <input type="text" name="timezone" value="{{ loc_timezone }}" placeholder="Timezone">
                <input type="number" name="lat" step="any" value="{{ loc_lat }}" placeholder="Latitude">
                <input type="number" name="lon" step="any" value="{{ loc_lon }}" placeholder="Longitude">
                <input type="submit" value="Set">
            </form>
        </div>
        <script>
            const socket = io();

            socket.on('update_state', function(state) {
                document.getElementById('current_effect').innerText = 'Current Effect: ' + state.current_effect;
                document.getElementById('manual_on').innerText = 'Manual On: ' + state.manual_on;
                document.getElementById('manual_off').innerText = 'Manual Off: ' + state.manual_off;
                document.getElementById('brightness_slider').value = state.brightness;
                document.getElementById('brightness_value').innerText = 'Value: ' + state.brightness;
                document.querySelector('#led_count_form input[name="count"]').value = state.led_count;
                document.querySelector('#location_form input[name="name"]').value = state.loc_name;
                document.querySelector('#location_form input[name="region"]').value = state.loc_region;
                document.querySelector('#location_form input[name="timezone"]').value = state.loc_timezone;
                document.querySelector('#location_form input[name="lat"]').value = state.loc_lat;
                document.querySelector('#location_form input[name="lon"]').value = state.loc_lon;
                document.querySelector('#custom_color_form input[name="color"]').value = rgbToHex(state.custom_solid_r, state.custom_solid_g, state.custom_solid_b);
                document.querySelector('#effect_speed_form input[name="speed"]').value = state.effect_speed;
                document.getElementById('speed_value').innerText = 'Value: ' + state.effect_speed;
                const turnOffTime = `${state.turn_off_hour.toString().padStart(2, '0')}:${state.turn_off_minute.toString().padStart(2, '0')}`;
                document.querySelector('#turn_off_time_form input[name="time"]').value = turnOffTime;
            });

            function rgbToHex(r, g, b) {
                return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
            }

            function updateSliderValue(value, id) {
                document.getElementById(id).innerText = 'Value: ' + value;
            }

            async function callEndpoint(endpoint) {
                try {
                    const response = await fetch(endpoint);
                    if (response.ok) {
                        console.log('Success');
                    } else {
                        console.error('Error');
                    }
                } catch (error) {
                    console.error('Fetch error:', error);
                }
            }

            async function submitForm(event, endpoint) {
                event.preventDefault();
                const form = event.target;
                const formData = new FormData(form);
                const params = new URLSearchParams(formData).toString();
                try {
                    const response = await fetch(endpoint + '?' + params);
                    if (response.ok) {
                        console.log('Success');
                    } else {
                        console.error('Error');
                    }
                } catch (error) {
                    console.error('Fetch error:', error);
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, current_effect=SELECTED_EFFECT, manual_on=manual_on, manual_off=manual_off,
                                  brightness=LED_BRIGHTNESS, led_count=LED_COUNT,
                                  loc_name=location.name, loc_region=location.region, loc_timezone=location.timezone,
                                  loc_lat=location.latitude, loc_lon=location.longitude)

@app.route('/on')
@auth.login_required
def turn_on_via_web():
    global manual_on, manual_off
    manual_on = True
    manual_off = False
    if not (current_effect_thread and current_effect_thread.is_alive()):
        start_effect()
    broadcast_state()
    return jsonify({"message": "Lights turned on!"}), 200

@app.route('/off')
@auth.login_required
def turn_off_via_web():
    global manual_on, manual_off
    manual_on = False
    manual_off = True
    stop_current_effect()
    turn_off(strip)
    broadcast_state()
    return jsonify({"message": "Lights turned off!"}), 200

@app.route('/effect/<effect_name>')
@auth.login_required
def set_effect(effect_name):
    global SELECTED_EFFECT, current_effect_func
    try:
        current_effect_func = get_effect_function(effect_name)
        SELECTED_EFFECT = effect_name
        save_config()
        if manual_on or (not manual_off and is_in_time_window()):
            stop_current_effect()
            start_effect()
        broadcast_state()
        return jsonify({"message": f"Effect set to {effect_name}!"}), 200
    except ValueError:
        return jsonify({"error": "Invalid effect!"}), 400

@app.route('/brightness')
@auth.login_required
def set_brightness():
    level = request.args.get('level', type=int)
    if level is not None and 0 <= level <= 255:
        global LED_BRIGHTNESS
        LED_BRIGHTNESS = level
        strip.setBrightness(LED_BRIGHTNESS)
        strip.show()
        save_config()
        broadcast_state()
        return jsonify({"message": f"Brightness set to {level}!"}), 200
    return jsonify({"error": "Invalid brightness level!"}), 400

@app.route('/led_count')
@auth.login_required
def set_led_count():
    count = request.args.get('count', type=int)
    if count is not None and count > 0:
        global LED_COUNT, strip
        LED_COUNT = count
        strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        strip.begin()
        save_config()
        broadcast_state()
        return jsonify({"message": f"LED count set to {count}!"}), 200
    return jsonify({"error": "Invalid LED count!"}), 400

@app.route('/location')
@auth.login_required
def set_location():
    name = request.args.get('name')
    region = request.args.get('region')
    timezone = request.args.get('timezone')
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    if all([name, region, timezone, lat is not None, lon is not None]):
        global location
        location = LocationInfo(name, region, timezone, lat, lon)
        save_config()
        broadcast_state()
        return jsonify({"message": "Location updated!"}), 200
    return jsonify({"error": "Invalid location parameters!"}), 400

@app.route('/turn_off_time')
@auth.login_required
def set_turn_off_time():
    time_str = request.args.get('time')
    if time_str:
        try:
            hour, minute = map(int, time_str.split(':'))
            global TURN_OFF_HOUR, TURN_OFF_MINUTE
            TURN_OFF_HOUR = hour
            TURN_OFF_MINUTE = minute
            save_config()
            broadcast_state()
            return jsonify({"message": "Turn-off time updated!"}), 200
        except ValueError:
            pass
    return jsonify({"error": "Invalid time format!"}), 400

@app.route('/custom_color')
@auth.login_required
def set_custom_color():
    color_hex = request.args.get('color')
    if color_hex and len(color_hex) == 7 and color_hex.startswith('#'):
        try:
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            global CUSTOM_SOLID_COLOR
            CUSTOM_SOLID_COLOR = (r, g, b)
            save_config()
            if SELECTED_EFFECT == 'solid' and (manual_on or (not manual_off and is_in_time_window())):
                stop_current_effect()
                start_effect()
            broadcast_state()
            return jsonify({"message": "Custom color set!"}), 200
        except ValueError:
            pass
    return jsonify({"error": "Invalid color!"}), 400

@app.route('/effect_speed')
@auth.login_required
def set_effect_speed():
    speed = request.args.get('speed', type=float)
    if speed is not None and 0.5 <= speed <= 2.0:
        global EFFECT_SPEED
        EFFECT_SPEED = speed
        save_config()
        if current_effect_thread and current_effect_thread.is_alive():
            stop_current_effect()
            start_effect()
        broadcast_state()
        return jsonify({"message": f"Effect speed set to {speed}!"}), 200
    return jsonify({"error": "Invalid speed (0.5-2.0)!"}), 400

# Main scheduling logic
def main_logic():
    global manual_on, manual_off, current_effect_func, stop_event, current_effect_thread
    load_config()  # Load on start
    current_effect_func = get_effect_function(SELECTED_EFFECT)
    
    while True:
        now = datetime.datetime.now(location.tzinfo)
        
        # Get today's sun times
        s = sun(location.observer, date=now.date(), tzinfo=location.tzinfo)
        sunset = s['sunset']
        
        turn_on_time = sunset - datetime.timedelta(minutes=30)
        turn_off_time = now.replace(hour=TURN_OFF_HOUR, minute=TURN_OFF_MINUTE, second=0, microsecond=0)
        
        if turn_on_time > turn_off_time:
            turn_off(strip)
            manual_on = False
            manual_off = False
            next_day = now + datetime.timedelta(days=1)
            sleep_seconds = (next_day.replace(hour=0, minute=0, second=0) - now).total_seconds()
            time.sleep(sleep_seconds)
            continue
        
        should_be_on = manual_on or (not manual_off and turn_on_time <= now < turn_off_time)
        
        if should_be_on:
            if not (current_effect_thread and current_effect_thread.is_alive()):
                start_effect()
            
            # Wait while should be on
            while (manual_on or (not manual_off and turn_on_time <= (now := datetime.datetime.now(location.tzinfo)) < turn_off_time)):
                time.sleep(1)
            
            # If exited due to time, turn off unless manual_on
            if not manual_on:
                stop_current_effect()
                turn_off(strip)
        
        else:
            stop_current_effect()
            turn_off(strip)
            
            if now >= turn_off_time:
                manual_on = False
                manual_off = False
            
            if now < turn_on_time:
                sleep_seconds = (turn_on_time - now).total_seconds()
            else:
                next_day = now + datetime.timedelta(days=1)
                next_s = sun(location.observer, date=next_day.date(), tzinfo=location.tzinfo)
                next_turn_on = next_s['sunset'] - datetime.timedelta(minutes=30)
                sleep_seconds = (next_turn_on - now).total_seconds()
            
            time.sleep(sleep_seconds)

# Main program entry
if __name__ == '__main__':
    # Start Flask/SocketIO in a separate thread
    flask_thread = threading.Thread(target=socketio.run, args=(app,), kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': False, 'use_reloader': False})
    flask_thread.daemon = True
    flask_thread.start()
    
    # Print access info
    local_ip = get_local_ip()
    print(f"Web dashboard available at: http://{local_ip}:5000/")
    print("Access from your phone on the same network to control everything.")
    
    try:
        main_logic()
    except KeyboardInterrupt:
        stop_event.set()
        if current_effect_thread and current_effect_thread.is_alive():
            current_effect_thread.join()
        turn_off(strip)
