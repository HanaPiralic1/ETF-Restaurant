# ====================== Importi ====================== #
from machine import Pin, SPI
from micropython import const
import ili934xnew
import tt14
import tt24
import tt32
import time
import network
from umqtt.simple import MQTTClient
from ili934xnew import ILI9341, color565

# ================= Definisanje pinova za TFT ================= #
TFT_CLK_PIN = const(18)
TFT_MOSI_PIN = const(19)
TFT_MISO_PIN = const(16)
TFT_CS_PIN = const(17)
TFT_RST_PIN = const(20)
TFT_DC_PIN = const(15)

# ================ Konfiguracija Wi-Fi/MQTT  ================ #
WIFI_SSID     = 'Redmi Note 13'
WIFI_PASSWORD = 'ilmailma'
MQTT_BROKER   = 'broker.emqx.io'
MQTT_TOPIC    = b'neda/blue'

# ================== Debounce za enkoder ================== #
ROTARY_DEBOUNCE_MS = const(150)
BUTTON_DEBOUNCE_MS = const(250)

# ==================== Inicijalizacija SPI/TFT ===================== #
spi = SPI(0,
          baudrate=40_000_000,
          sck=Pin(TFT_CLK_PIN),
          mosi=Pin(TFT_MOSI_PIN))

tft = ILI9341(spi,
              cs=Pin(TFT_CS_PIN),
              dc=Pin(TFT_DC_PIN),
              rst=Pin(TFT_RST_PIN),
              w=320, h=240, r=0)

tft.init()

# ================= Pinovi rotacionog enkodera ================= #
clk = Pin(0, Pin.IN, Pin.PULL_UP)
dt  = Pin(1, Pin.IN, Pin.PULL_UP)
sw  = Pin(2, Pin.IN, Pin.PULL_UP)

# ================= Meni i pocetna stanja ================= #
# Lista stavki u meniju - Format: (naziv, cijena)
menu_items_base = [
    ("Pizza",   "5"),
    ("Sendvic", "3.5"),
    ("Sok",     "2"),
    ("Kolac",   "2.5"),
]

order_list   = []   # Lista narucenih proizvoda
selected_index = 0  # Trenutno selektovana stavka u meniju
confirm_index  = 0   # 0 = DA, 1 = NE
screen         = 0   # 0 dobrodosli, 1 meni, 2 potvrdi, 3 finalno, 4 potvrdi prazno

total_price = 0.0

last_rotate_time = time.ticks_ms()
last_button_time = time.ticks_ms()
last_state       = (clk.value(), dt.value())    #   Zadnje stanje enkodera

# ================= Wi-Fi/MQTT postavljanje ================= #
#Konekcija na Wi-Fi mrezu 
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Povezivanje na Wi-Fi...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep(0.5)
    print('Povezan! IP:', wlan.ifconfig()[0])

#Slanje MQTT poruke
def send_mqtt_message(msg_bytes):
    try:
        client = MQTTClient("pico_narudzba", MQTT_BROKER)
        client.connect()
        client.publish(MQTT_TOPIC, msg_bytes)
        client.disconnect()
        print("MQTT poslan:", msg_bytes)
    except Exception as e:
        print("MQTT greska:", e)

# ================= Pomocne funkcije za UI ================= #
# Brisanje svega s ekrana
def clear_to_black():
    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.erase()

def wait_for_click_release():
    while sw.value() == 0:
        time.sleep(0.01)
# ====================== UI ============================ #
# Trenutni meni
def current_menu():
    return menu_items_base + [("Zavrsi narudzbu", "")] 

# Pocetni ekran dobrodoslice 
def show_welcome():
    clear_to_black()
    tft.set_font(tt32)
    tft.set_pos(30, 140)
    tft.print("Dobrodosli!")

#Prikazivanje menija 
def show_menu(selected):
    items = current_menu()
    clear_to_black()
    tft.set_font(tt24)
    tft.set_color(color565(0, 255, 255), color565(0, 0, 0))
    tft.set_pos(10, 20)
    tft.print("Proizvodi:")

    y_start = 50
    y_step  = 35
    for i, (item, price) in enumerate(items):
        y = y_start + i * y_step
        if i == selected:
            tft.set_color(color565(0, 0, 0), color565(255, 255, 0))
        else:
            tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
        tft.set_pos(10, y)
        tft.print(item)
        tft.set_pos(160, y)
        if item == "Zavrsi narudzbu":
            tft.print("->")
        else:
            tft.print("{} KM".format(price))
        tft.set_color(color565(100, 100, 100), color565(0, 0, 0))
        tft.set_pos(10, y + 20)
        tft.print("-----------------------------")

#   Ekran za potvrdu dodavanja stavke 
def show_confirmation(item, price):
    clear_to_black()
    tft.set_font(tt24)
    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.set_pos(10, 90)
    tft.print("Dodati u narudzbu?")
    tft.set_pos(10, 110)
    tft.print("{} ({} KM)".format(item, price))

    da_color = color565(0, 0, 0) if confirm_index == 0 else color565(255, 255, 255)
    da_bg    = color565(0, 255, 0) if confirm_index == 0 else color565(0, 0, 0)
    ne_color = color565(0, 0, 0) if confirm_index == 1 else color565(255, 255, 255)
    ne_bg    = color565(255, 0, 0) if confirm_index == 1 else color565(0, 0, 0)

    tft.set_color(da_color, da_bg)
    tft.set_pos(50, 160)
    tft.print(" DA ")
    tft.set_color(ne_color, ne_bg)
    tft.set_pos(130, 160)
    tft.print(" NE ")

    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.set_pos(50 + 80 * confirm_index, 185)
    tft.print("^")

#   Ekran za prikaz potvrde za narudzbu
def show_order_confirm():
    clear_to_black()
    tft.set_font(tt24)
    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.set_pos(10, 90)
    tft.print("Jeste li sigurni da")
    tft.set_pos(10, 110)
    tft.print("zelite potvrditi")
    tft.set_pos(10, 130)
    tft.print("narudzbu?")

    # DA / NE dugmad
    da_color = color565(0, 0, 0) if confirm_index == 0 else color565(255, 255, 255)
    da_bg    = color565(0, 255, 0) if confirm_index == 0 else color565(0, 0, 0)
    ne_color = color565(0, 0, 0) if confirm_index == 1 else color565(255, 255, 255)
    ne_bg    = color565(255, 0, 0) if confirm_index == 1 else color565(0, 0, 0)

    tft.set_color(da_color, da_bg)
    tft.set_pos(50, 180)
    tft.print(" DA ")
    tft.set_color(ne_color, ne_bg)
    tft.set_pos(130, 180)
    tft.print(" NE ")
    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.set_pos(50 + 80 * confirm_index, 205)
    tft.print("^")

#   Finalni ekran prikaza narudzbe 
def show_final():
    clear_to_black()
    tft.set_font(tt24)
    tft.set_color(color565(0, 255, 0), color565(0, 0, 0))
    tft.set_pos(10, 90)
    tft.print("Narudzba poslana!")
    tft.set_pos(10, 110)
    tft.print("Stavki: {}".format(len(order_list)))
    tft.set_pos(10, 130)
    tft.print("Ukupno: {:.2f} KM".format(total_price))

    # Lista prvih 5 (ili manje) narucenih proizvoda 
    tft.print("Narucili ste:")
    y = 180
    for name, _ in order_list[:5]:
        tft.set_pos(20, y)
        tft.print("- " + name)
        y += 20

    if len(order_list) > 5:
        tft.set_pos(20, y)
        tft.print("+ {}...".format(len(order_list) - 5))

#   Ekran za otkazivanje naruzbe 
def show_empty_confirm():
    clear_to_black()
    tft.set_font(tt24)
    tft.set_color(color565(255, 255, 0), color565(0, 0, 0))
    tft.set_pos(30, 110)
    tft.print("Lista je prazna.")
    tft.set_pos(20, 140)
    tft.print("Nastaviti narudzbu?")

    # DA / NE
    da_color = color565(0, 0, 0) if confirm_index == 0 else color565(255, 255, 255)
    da_bg    = color565(0, 255, 0) if confirm_index == 0 else color565(0, 0, 0)
    ne_color = color565(0, 0, 0) if confirm_index == 1 else color565(255, 255, 255)
    ne_bg    = color565(255, 0, 0) if confirm_index == 1 else color565(0, 0, 0)

    tft.set_color(da_color, da_bg)
    tft.set_pos(50, 180)
    tft.print(" DA ")
    tft.set_color(ne_color, ne_bg)
    tft.set_pos(130, 180)
    tft.print(" NE ")
    tft.set_color(color565(255, 255, 255), color565(0, 0, 0))
    tft.set_pos(50 + 80 * confirm_index, 205)
    tft.print("^")

# ====================== Pocetak ============================= #
connect_wifi()
show_welcome()

# ==================== Glavna petlja ========================= #
#Glavna logika rada aplikacije - obrada enkodera, klikova i prikaza 
while True:
    now = time.ticks_ms()
    current_state = (clk.value(), dt.value())
    items = current_menu()

    #   Obrada rotacije enkodera
    if current_state != last_state and time.ticks_diff(now, last_rotate_time) > ROTARY_DEBOUNCE_MS:
        if last_state == (1, 1):
            if screen in (2, 4, 5):
                if current_state == (1, 0):
                    confirm_index = (confirm_index + 1) % 2
                    if screen == 2:
                        show_confirmation(*selected_item)
                    elif screen == 4:
                        show_empty_confirm()
                    else: 
                        show_order_confirm()
                elif current_state == (0, 1):
                    confirm_index = (confirm_index - 1) % 2
                    if screen == 2:
                        show_confirmation(*selected_item)
                    else:
                        show_empty_confirm()
            elif screen == 1:
                if current_state == (1, 0) and selected_index < len(items) - 1:
                    selected_index += 1
                    show_menu(selected_index)
                elif current_state == (0, 1) and selected_index > 0:
                    selected_index -= 1
                    show_menu(selected_index)
        last_rotate_time = now
        last_state = current_state

    #   Obrada klika dugmeta na enkoderu 
    if sw.value() == 0 and time.ticks_diff(now, last_button_time) > BUTTON_DEBOUNCE_MS:
        wait_for_click_release()
        last_button_time = time.ticks_ms()

        current_item, current_price_str = items[selected_index]

        if screen == 0:
            screen = 1
            show_menu(selected_index)

        elif screen == 1:
            if current_item == "Zavrsi narudzbu":
                if order_list:
                    confirm_index = 0
                    screen = 5  # idemo na ekran potvrde narudzbe
                    show_order_confirm()
                else:
                    screen = 4
                    confirm_index = 0
                    show_empty_confirm()
            else:
                selected_item = (current_item, current_price_str)
                confirm_index = 0
                screen = 2
                show_confirmation(*selected_item)

        elif screen == 2:
            if confirm_index == 0:
                price_float = float(selected_item[1])
                order_list.append((selected_item[0], price_float))
                total_price += price_float
            screen = 1
            show_menu(selected_index)
            confirm_index = 0

        elif screen == 4:
            if confirm_index == 0:
                screen = 1
                show_menu(selected_index)
            else:
                screen = 0
                show_welcome()
            confirm_index = 0

        elif screen == 3:
            order_list.clear()
            total_price = 0.0
            selected_index = 0
            screen = 0
            show_welcome()
        
        elif screen == 5:
            if confirm_index == 0:
            # Potvrda DA - saljemo narudzbu i prikazujemo finalni ekran
                names_only = [name for name, _ in order_list]
                payload = ", ".join(names_only).encode()
                send_mqtt_message(payload)
                show_final()
                screen = 3
            else:
                # Potvrda NE - vracamo se na pocetni ekran
                screen = 0
                show_welcome
            confirm_index = 0


    time.sleep(0.005) # Mali delay radi stabilnosti 