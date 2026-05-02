#include "Display.h"

#include <Wire.h>
#include <stdarg.h>
#include <string.h>

static constexpr uint8_t OLED_SDA = 4;
static constexpr uint8_t OLED_SCL = 15;
static constexpr uint8_t OLED_RST = 16;
static constexpr uint8_t OLED_ADDR = 0x3C;

bool Display::begin() {
    pinMode(OLED_RST, OUTPUT);
    digitalWrite(OLED_RST, LOW);
    delay(20);
    digitalWrite(OLED_RST, HIGH);
    delay(20);

    Wire1.begin(OLED_SDA, OLED_SCL);
    Wire1.setClock(400000);

    ok_ = oled_.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
    if (!ok_) return false;

    oled_.clearDisplay();
    oled_.setTextSize(1);
    oled_.setTextColor(SSD1306_WHITE);
    oled_.setCursor(0, 0);
    oled_.display();
    return true;
}

void Display::clear() {
    title_[0] = 0;
    for (int i = 0; i < LINES; ++i) buf_[i][0] = 0;
    next_ = 0;
    if (ok_) {
        oled_.clearDisplay();
        oled_.display();
    }
}

void Display::title(const char* t) {
    strncpy(title_, t, LINE_LEN - 1);
    title_[LINE_LEN - 1] = 0;
    render_();
}

void Display::log(const char* fmt, ...) {
    char tmp[LINE_LEN];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);

    if (next_ < LINES) {
        strncpy(buf_[next_++], tmp, LINE_LEN - 1);
    } else {
        for (int i = 1; i < LINES; ++i) {
            memcpy(buf_[i - 1], buf_[i], LINE_LEN);
        }
        strncpy(buf_[LINES - 1], tmp, LINE_LEN - 1);
        buf_[LINES - 1][LINE_LEN - 1] = 0;
    }
    render_();
}

void Display::replaceLast(const char* fmt, ...) {
    char tmp[LINE_LEN];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);

    int idx = (next_ == 0) ? 0 : (next_ <= LINES ? next_ - 1 : LINES - 1);
    strncpy(buf_[idx], tmp, LINE_LEN - 1);
    buf_[idx][LINE_LEN - 1] = 0;
    if (next_ == 0) next_ = 1;
    render_();
}

void Display::show() {
    render_();
}

void Display::render_() {
    if (!ok_) return;
    oled_.clearDisplay();
    oled_.setCursor(0, 0);
    if (title_[0]) {
        oled_.println(title_);
        oled_.drawFastHLine(0, 9, 128, SSD1306_WHITE);
        oled_.setCursor(0, 12);
    }
    for (int i = 0; i < LINES; ++i) {
        if (buf_[i][0]) oled_.println(buf_[i]);
    }
    oled_.display();
}
