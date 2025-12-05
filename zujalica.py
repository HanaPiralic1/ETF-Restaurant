from machine import Pin, PWM
from time import sleep_ms, ticks_ms, ticks_diff
import network
from umqtt.simple import MQTTClient

# ======================= Wi-Fi & MQTT =======================
WIFI_SSID     = 'Redmi Note 13'
WIFI_PASSWORD = 'ilmailma'
MQTT_BROKER   = 'broker.emqx.io'
MQTT_TOPIC    = b'neda/blue'

# ==================== Hardver pinovi ====================
BUZZER_PIN = 16                       # piezo-buzzer (pasivni) - PWM
buzzer = PWM(Pin(BUZZER_PIN))

LED_SHOW = Pin(25, Pin.OUT)           # ugradjena LED-ica za signalizaciju

button = Pin(0, Pin.IN, Pin.PULL_DOWN)  # prekidni taster

segments = [Pin(i, Pin.OUT) for i in range(8, 16)]  # A...DP = GP8-GP15
digits   = [Pin(i, Pin.OUT) for i in range(4, 8)]    # D1...D4 = GP4-GP7

# ======================== Globalne varijable ========================
prekini_animaciju   = False   # postavlja se u IRQ-u
countdown_trenutno  = False   # True dok traje odbrojavanje ili alarm
queued_seconds      = 0       # sekunde cekaju da krenu

# ======================== 7-segment font ========================
numbers = {
    '0': [0,0,0,0,0,0,1,1],
    '1': [1,0,0,1,1,1,1,1],
    '2': [0,0,1,0,0,1,0,1],
    '3': [0,0,0,0,1,1,0,1],
    '4': [1,0,0,1,1,0,0,1],
    '5': [0,1,0,0,1,0,0,1],
    '6': [0,1,0,0,0,0,0,1],
    '7': [0,0,0,1,1,1,1,1],
    '8': [0,0,0,0,0,0,0,1],
    '9': [0,0,0,0,1,0,0,1],
    ' ': [1,1,1,1,1,1,1,1]
}

# ======================== Taster interrupt ========================
def prekidac_handler(pin):
    global prekini_animaciju
    prekini_animaciju = True

button.irq(trigger=Pin.IRQ_RISING, handler=prekidac_handler)

# ======================== 7-segment pomocne ========================
def clear_all():
    for d in digits:   d.value(1)
    for s in segments: s.value(1)

def display_digit(pos: int, char: str):
    clear_all()
    digits[pos].value(0)
    pattern = numbers.get(char, numbers[' '])
    for i in range(8):
        segments[i].value(pattern[i])

def display_number(num_str: str):
    padded = num_str + ' ' * (4 - len(num_str))
    for _ in range(4):                      # otprilike 12 ms za jedan prolaz
        for pos in range(4):
            display_digit(pos, padded[pos])
            sleep_ms(3)
        clear_all()

# ======================== Alarm: blink displeja + buzzer ========================
leds = [Pin(i, Pin.OUT) for i in range(4, 12)]  # GP4-GP11 za 8 LED-ica

# Izmijeni alert_effect:
def alert_effect():
    """
    Blinka: 500 ms parne LED-ice + zvuk, 500 ms neparne LED-ice + tisina.
    Radi sve dok korisnik ne pritisne taster (prekini_animaciju=True).
    """
    faza = 0  # 0 = parni LED + zvuk, 1 = neparni LED + tisina
    while not prekini_animaciju:
        if faza == 0:
            buzzer.freq(2000)
            buzzer.duty_u16(32768)  # zvuk ON
            for i in range(8):
                leds[i].value(1 if i % 2 == 0 else 0)  # upali parne
        else:
            buzzer.duty_u16(0)  # zvuk OFF
            for i in range(8):
                leds[i].value(1 if i % 2 == 1 else 0)  # upali neparne

        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < 500:
            if prekini_animaciju:
                break
            sleep_ms(20)  # da ne blokira prekid

        faza = 1 - faza  # zamijeni fazu

    # Po izlasku sve ugasimo
    buzzer.duty_u16(0)
    for led in leds:
        led.value(0)


# ======================== Countdown ========================
def countdown(total_seconds: int):
    global prekini_animaciju, countdown_trenutno
    countdown_trenutno = True
    prekini_animaciju  = False

    for remaining in range(total_seconds, -1, -1):
        if prekini_animaciju:
            break
        mins, secs = divmod(remaining, 60)
        time_str   = f"{mins:02d}{secs:02d}"
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < 1000:
            display_number(time_str)
            if prekini_animaciju:
                break

    clear_all()

    # Alarm start 
    if not prekini_animaciju:
        alert_effect()

    # Reset stanja
    prekini_animaciju  = False
    countdown_trenutno = False

# ======================== Wi-Fi & MQTT ========================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Povezujem se na Wi-Fi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            sleep_ms(500)
    print("Wi-Fi OK:", wlan.ifconfig())

def mqtt_callback(topic, msg):
    global queued_seconds
    tekst   = msg.decode()
    stavke  = [s.strip() for s in tekst.split(',') if s.strip()]
    if stavke:
        dodatno = 10 * len(stavke)
        queued_seconds += dodatno
        print("MQTT", stavke, "-> +", dodatno, "s (ukupno", queued_seconds, ")")

def connect_mqtt():
    try:
        c = MQTTClient("pico_primalac", MQTT_BROKER)
        c.set_callback(mqtt_callback)
        c.connect()
        c.subscribe(MQTT_TOPIC)
        print("Sub:", MQTT_TOPIC)
        return c
    except Exception as e:
        print("MQTT greaka:", e)
        return None

#======================== MAIN PETLJA ========================
connect_wifi()
client = connect_mqtt()

while True:
    # 1) MQTT poruke
    try:
        if client:
            client.check_msg()
        else:
            client = connect_mqtt()
    except OSError as e:
        print("MQTT I/O greska:", e)
        sleep_ms(1000)
        client = connect_mqtt()

    # 2) Pokreni countdown ako ima nesto u redu cekanja
    if queued_seconds > 0 and not countdown_trenutno:
        trajanje = queued_seconds
        queued_seconds = 0          # isprazni red
        countdown(trajanje)

    sleep_ms(200)